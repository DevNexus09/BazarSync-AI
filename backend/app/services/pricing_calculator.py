from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP


MONEY_QUANT_BY_CURRENCY = {
    "BDT": Decimal("0.01"),
}
RATE_QUANT = Decimal("0.000001")


class PricingCalculationError(ValueError):
    pass


@dataclass(frozen=True)
class FeeInputs:
    percentage_commission_rate: Decimal = Decimal("0")
    payment_fee_rate: Decimal = Decimal("0")
    fixed_per_order_fee: Decimal = Decimal("0")
    fixed_per_unit_fee: Decimal = Decimal("0")
    fulfilment_fee: Decimal = Decimal("0")
    shipping_subsidy: Decimal = Decimal("0")
    other_variable_cost: Decimal = Decimal("0")

    @property
    def percentage_fee_rate(self) -> Decimal:
        return self.percentage_commission_rate + self.payment_fee_rate

    @property
    def fixed_costs(self) -> Decimal:
        return (
            self.fixed_per_order_fee
            + self.fixed_per_unit_fee
            + self.fulfilment_fee
            + self.shipping_subsidy
            + self.other_variable_cost
        )


@dataclass(frozen=True)
class FeeBreakdown:
    price: Decimal
    percentage_commission_amount: Decimal
    payment_fee_amount: Decimal
    fixed_per_order_fee: Decimal
    fixed_per_unit_fee: Decimal
    fulfilment_fee: Decimal
    shipping_subsidy: Decimal
    other_variable_cost: Decimal
    total_fee_amount: Decimal


@dataclass(frozen=True)
class CandidateValidation:
    is_valid: bool
    reasons: list[str]
    fee_breakdown: FeeBreakdown
    unit_profit: Decimal
    margin_rate: Decimal
    minimum_safe_price: Decimal


class PricingCalculator:
    def __init__(self, *, currency: str = "BDT") -> None:
        self.currency = currency.upper()

    def round_currency(self, value: Decimal | int | str) -> Decimal:
        return _decimal(value).quantize(self._money_quant(), rounding=ROUND_HALF_UP)

    def round_to_marketplace_increment(
        self,
        value: Decimal | int | str,
        increment: Decimal | int | str,
        *,
        direction: str = "nearest",
    ) -> Decimal:
        amount = _decimal(value)
        step = _decimal(increment)
        if step <= 0:
            raise PricingCalculationError("price increment must be positive")
        quotient = amount / step
        if direction == "up":
            rounded_units = quotient.to_integral_value(rounding=ROUND_CEILING)
        elif direction == "down":
            rounded_units = quotient.to_integral_value(rounding=ROUND_FLOOR)
        elif direction == "nearest":
            rounded_units = quotient.to_integral_value(rounding=ROUND_HALF_UP)
        else:
            raise PricingCalculationError("direction must be nearest, up, or down")
        return self.round_currency(rounded_units * step)

    def calculate_fee_breakdown(
        self,
        *,
        price: Decimal | int | str,
        fees: FeeInputs,
    ) -> FeeBreakdown:
        self._validate_fees(fees)
        amount = _nonnegative_decimal(price, "price")
        percentage_commission = amount * fees.percentage_commission_rate
        payment_fee = amount * fees.payment_fee_rate
        total = (
            percentage_commission
            + payment_fee
            + fees.fixed_per_order_fee
            + fees.fixed_per_unit_fee
            + fees.fulfilment_fee
            + fees.shipping_subsidy
            + fees.other_variable_cost
        )
        return FeeBreakdown(
            price=amount,
            percentage_commission_amount=percentage_commission,
            payment_fee_amount=payment_fee,
            fixed_per_order_fee=fees.fixed_per_order_fee,
            fixed_per_unit_fee=fees.fixed_per_unit_fee,
            fulfilment_fee=fees.fulfilment_fee,
            shipping_subsidy=fees.shipping_subsidy,
            other_variable_cost=fees.other_variable_cost,
            total_fee_amount=total,
        )

    def calculate_unit_profit(
        self,
        *,
        price: Decimal | int | str,
        unit_cost: Decimal | int | str,
        fees: FeeInputs,
    ) -> Decimal:
        cost = _nonnegative_decimal(unit_cost, "unit_cost")
        breakdown = self.calculate_fee_breakdown(price=price, fees=fees)
        return breakdown.price - cost - breakdown.total_fee_amount

    def calculate_margin_rate(
        self,
        *,
        price: Decimal | int | str,
        unit_cost: Decimal | int | str,
        fees: FeeInputs,
    ) -> Decimal:
        amount = _nonnegative_decimal(price, "price")
        if amount <= 0:
            raise PricingCalculationError("price must be greater than zero")
        profit = self.calculate_unit_profit(price=amount, unit_cost=unit_cost, fees=fees)
        return (profit / amount).quantize(RATE_QUANT, rounding=ROUND_HALF_UP)

    def calculate_minimum_safe_price(
        self,
        *,
        unit_cost: Decimal | int | str,
        fees: FeeInputs,
        minimum_margin_rate: Decimal | int | str,
        minimum_unit_profit: Decimal | int | str = Decimal("0"),
        price_increment: Decimal | int | str = Decimal("0.01"),
    ) -> Decimal:
        cost = _nonnegative_decimal(unit_cost, "unit_cost")
        margin = _rate(minimum_margin_rate, "minimum_margin_rate")
        unit_profit_floor = _nonnegative_decimal(minimum_unit_profit, "minimum_unit_profit")
        self._validate_fees(fees)
        if fees.percentage_fee_rate + margin >= Decimal("1"):
            raise PricingCalculationError("percentage fee rate plus minimum margin rate must be below 1")

        fixed_costs = fees.fixed_costs
        margin_price = (cost + fixed_costs) / (Decimal("1") - fees.percentage_fee_rate - margin)
        profit_price = (cost + fixed_costs + unit_profit_floor) / (Decimal("1") - fees.percentage_fee_rate)
        safe_price = max(margin_price, profit_price)
        return self.round_to_marketplace_increment(safe_price, price_increment, direction="up")

    def validate_candidate_price(
        self,
        *,
        candidate_price: Decimal | int | str,
        current_price: Decimal | int | str,
        unit_cost: Decimal | int | str,
        fees: FeeInputs,
        minimum_margin_rate: Decimal | int | str,
        minimum_unit_profit: Decimal | int | str,
        price_increment: Decimal | int | str,
        minimum_allowed_price: Decimal | int | str | None = None,
        maximum_allowed_price: Decimal | int | str | None = None,
        maximum_price_decrease_rate: Decimal | int | str | None = None,
        maximum_price_increase_rate: Decimal | int | str | None = None,
    ) -> CandidateValidation:
        candidate = _nonnegative_decimal(candidate_price, "candidate_price")
        current = _nonnegative_decimal(current_price, "current_price")
        minimum_safe = self.calculate_minimum_safe_price(
            unit_cost=unit_cost,
            fees=fees,
            minimum_margin_rate=minimum_margin_rate,
            minimum_unit_profit=minimum_unit_profit,
            price_increment=price_increment,
        )
        breakdown = self.calculate_fee_breakdown(price=candidate, fees=fees)
        profit = self.calculate_unit_profit(price=candidate, unit_cost=unit_cost, fees=fees)
        margin = self.calculate_margin_rate(price=candidate, unit_cost=unit_cost, fees=fees) if candidate > 0 else Decimal("0")
        reasons: list[str] = []
        if candidate < minimum_safe:
            reasons.append("below_minimum_safe_price")
        if minimum_allowed_price is not None and candidate < _decimal(minimum_allowed_price):
            reasons.append("below_minimum_allowed_price")
        if maximum_allowed_price is not None and candidate > _decimal(maximum_allowed_price):
            reasons.append("above_maximum_allowed_price")
        if current > 0 and maximum_price_decrease_rate is not None:
            decrease_floor = current * (Decimal("1") - _rate(maximum_price_decrease_rate, "maximum_price_decrease_rate"))
            if candidate < decrease_floor:
                reasons.append("exceeds_maximum_price_decrease")
        if current > 0 and maximum_price_increase_rate is not None:
            increase_ceiling = current * (Decimal("1") + _rate(maximum_price_increase_rate, "maximum_price_increase_rate", allow_above_one=True))
            if candidate > increase_ceiling:
                reasons.append("exceeds_maximum_price_increase")
        if profit < _decimal(minimum_unit_profit):
            reasons.append("below_minimum_unit_profit")
        if margin < _decimal(minimum_margin_rate):
            reasons.append("below_minimum_margin_rate")
        return CandidateValidation(
            is_valid=not reasons,
            reasons=reasons,
            fee_breakdown=breakdown,
            unit_profit=profit,
            margin_rate=margin,
            minimum_safe_price=minimum_safe,
        )

    def _money_quant(self) -> Decimal:
        return MONEY_QUANT_BY_CURRENCY.get(self.currency, Decimal("0.01"))

    @staticmethod
    def _validate_fees(fees: FeeInputs) -> None:
        for name in (
            "percentage_commission_rate",
            "payment_fee_rate",
            "fixed_per_order_fee",
            "fixed_per_unit_fee",
            "fulfilment_fee",
            "shipping_subsidy",
            "other_variable_cost",
        ):
            value = getattr(fees, name)
            if value < 0:
                raise PricingCalculationError(f"{name} cannot be negative")
        if fees.percentage_commission_rate >= 1 or fees.payment_fee_rate >= 1:
            raise PricingCalculationError("fee rates must be below 1")
        if fees.percentage_fee_rate >= 1:
            raise PricingCalculationError("total percentage fee rate must be below 1")


def _decimal(value: Decimal | int | str) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _nonnegative_decimal(value: Decimal | int | str, name: str) -> Decimal:
    number = _decimal(value)
    if number < 0:
        raise PricingCalculationError(f"{name} cannot be negative")
    return number


def _rate(value: Decimal | int | str, name: str, *, allow_above_one: bool = False) -> Decimal:
    number = _nonnegative_decimal(value, name)
    if not allow_above_one and number >= 1:
        raise PricingCalculationError(f"{name} must be below 1")
    return number
