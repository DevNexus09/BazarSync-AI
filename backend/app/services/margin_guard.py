from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.product import Product
from app.services.pricing_calculator import FeeBreakdown, FeeInputs, PricingCalculationError, PricingCalculator
from app.services.pricing_policy_service import PricingPolicyService


class MarginGuardRejectionReason(str, Enum):
    BELOW_MINIMUM_SAFE_PRICE = "BELOW_MINIMUM_SAFE_PRICE"
    NEGATIVE_UNIT_PROFIT = "NEGATIVE_UNIT_PROFIT"
    BELOW_MINIMUM_MARGIN = "BELOW_MINIMUM_MARGIN"
    BELOW_MINIMUM_UNIT_PROFIT = "BELOW_MINIMUM_UNIT_PROFIT"
    EXCEEDS_MAXIMUM_DECREASE = "EXCEEDS_MAXIMUM_DECREASE"
    EXCEEDS_MAXIMUM_INCREASE = "EXCEEDS_MAXIMUM_INCREASE"
    BELOW_ABSOLUTE_MINIMUM = "BELOW_ABSOLUTE_MINIMUM"
    ABOVE_ABSOLUTE_MAXIMUM = "ABOVE_ABSOLUTE_MAXIMUM"
    INVALID_MARKETPLACE_INCREMENT = "INVALID_MARKETPLACE_INCREMENT"
    MISSING_COST_DATA = "MISSING_COST_DATA"
    MISSING_FEE_DATA = "MISSING_FEE_DATA"
    INVALID_POLICY = "INVALID_POLICY"
    UNSUPPORTED_CURRENCY = "UNSUPPORTED_CURRENCY"


@dataclass(frozen=True)
class MarginGuardFeeBreakdown:
    percentage_commission_amount: Decimal | None
    payment_fee_amount: Decimal | None
    fixed_fees: Decimal | None
    other_variable_cost: Decimal | None
    total_fee_amount: Decimal | None


@dataclass(frozen=True)
class MarginGuardResult:
    is_allowed: bool
    candidate_price: Decimal
    minimum_safe_price: Decimal | None
    unit_profit: Decimal | None
    margin_rate: Decimal | None
    fee_breakdown: MarginGuardFeeBreakdown
    rejection_reasons: list[MarginGuardRejectionReason]
    policy_version: str | None
    calculation_version: str
    percentage_fee_rate: Decimal | None
    fixed_fee_amount: Decimal | None
    other_variable_cost: Decimal | None
    unit_cost: Decimal | None
    minimum_required_margin: Decimal | None
    minimum_required_unit_profit: Decimal | None
    price_change_percentage: Decimal | None
    marketplace_increment_valid: bool | None

    def to_evidence(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["rejection_reasons"] = [reason.value for reason in self.rejection_reasons]
        payload["fee_breakdown"] = {
            key: _json_decimal(value)
            for key, value in payload["fee_breakdown"].items()
        }
        for key, value in list(payload.items()):
            if isinstance(value, Decimal):
                payload[key] = _json_decimal(value)
        return payload


class MarginGuard:
    calculation_version = "margin_guard_v1"

    def __init__(self, db: Session, *, pricing_policy_service_factory=None) -> None:
        self._db = db
        self._pricing_policy_service_factory = pricing_policy_service_factory or PricingPolicyService

    def validate_candidate(
        self,
        *,
        seller_id: UUID,
        product: Product,
        candidate_price: Decimal,
        marketplace: str = "Daraz Bangladesh",
    ) -> MarginGuardResult:
        reasons: list[MarginGuardRejectionReason] = []
        candidate = _decimal(candidate_price)
        if product.cost_price is None:
            reasons.append(MarginGuardRejectionReason.MISSING_COST_DATA)
            return _blocked_result(candidate, reasons, unit_cost=None)
        unit_cost = _decimal(product.cost_price)
        if unit_cost < 0:
            reasons.append(MarginGuardRejectionReason.MISSING_COST_DATA)

        policy = None
        fee_policy = None
        fees: FeeInputs | None = None
        calculator = PricingCalculator(currency="BDT")
        try:
            policy_service = self._pricing_policy_service_factory(self._db)
            policy = policy_service.get_product_policy(
                seller_id=seller_id,
                product_id=product.id,
                marketplace=marketplace,
            )
            if policy.currency.upper() != "BDT":
                reasons.append(MarginGuardRejectionReason.UNSUPPORTED_CURRENCY)
            calculator = PricingCalculator(currency=policy.currency)
            fee_policy = policy_service.effective_fee_policy(
                seller_id=seller_id,
                product_id=product.id,
                marketplace=marketplace,
            )
            if fee_policy.id is None or getattr(fee_policy, "is_default", False):
                reasons.append(MarginGuardRejectionReason.MISSING_FEE_DATA)
            fees = _fee_inputs(fee_policy)
            if fees.percentage_fee_rate + _decimal(policy.minimum_margin_rate) >= Decimal("1"):
                reasons.append(MarginGuardRejectionReason.INVALID_POLICY)
        except Exception:
            reasons.append(MarginGuardRejectionReason.INVALID_POLICY)

        if policy is None or fees is None:
            return _blocked_result(candidate, reasons, unit_cost=unit_cost)

        minimum_safe_price = None
        unit_profit = None
        margin_rate = None
        fee_breakdown = None
        try:
            minimum_safe_price = calculator.calculate_minimum_safe_price(
                unit_cost=unit_cost,
                fees=fees,
                minimum_margin_rate=policy.minimum_margin_rate,
                minimum_unit_profit=policy.minimum_unit_profit,
                price_increment=policy.price_increment,
            )
            raw_breakdown = calculator.calculate_fee_breakdown(price=candidate, fees=fees)
            fee_breakdown = _guard_breakdown(raw_breakdown, fees)
            unit_profit = calculator.calculate_unit_profit(price=candidate, unit_cost=unit_cost, fees=fees)
            margin_rate = calculator.calculate_margin_rate(price=candidate, unit_cost=unit_cost, fees=fees) if candidate > 0 else Decimal("0")
        except PricingCalculationError:
            reasons.append(MarginGuardRejectionReason.INVALID_POLICY)

        if minimum_safe_price is not None and candidate < minimum_safe_price:
            reasons.append(MarginGuardRejectionReason.BELOW_MINIMUM_SAFE_PRICE)
        if unit_profit is not None and unit_profit < 0:
            reasons.append(MarginGuardRejectionReason.NEGATIVE_UNIT_PROFIT)
        if margin_rate is not None and margin_rate < _decimal(policy.minimum_margin_rate):
            reasons.append(MarginGuardRejectionReason.BELOW_MINIMUM_MARGIN)
        if unit_profit is not None and unit_profit < _decimal(policy.minimum_unit_profit):
            reasons.append(MarginGuardRejectionReason.BELOW_MINIMUM_UNIT_PROFIT)
        if policy.minimum_allowed_price is not None and candidate < _decimal(policy.minimum_allowed_price):
            reasons.append(MarginGuardRejectionReason.BELOW_ABSOLUTE_MINIMUM)
        if policy.maximum_allowed_price is not None and candidate > _decimal(policy.maximum_allowed_price):
            reasons.append(MarginGuardRejectionReason.ABOVE_ABSOLUTE_MAXIMUM)

        change_pct = _price_change_percentage(current_price=_decimal(product.selling_price), candidate_price=candidate)
        if change_pct is not None:
            if policy.maximum_price_decrease_rate is not None and change_pct < -_decimal(policy.maximum_price_decrease_rate):
                reasons.append(MarginGuardRejectionReason.EXCEEDS_MAXIMUM_DECREASE)
            if policy.maximum_price_increase_rate is not None and change_pct > _decimal(policy.maximum_price_increase_rate):
                reasons.append(MarginGuardRejectionReason.EXCEEDS_MAXIMUM_INCREASE)
        increment_valid = _increment_valid(candidate, _decimal(policy.price_increment))
        if not increment_valid:
            reasons.append(MarginGuardRejectionReason.INVALID_MARKETPLACE_INCREMENT)

        return MarginGuardResult(
            is_allowed=not reasons,
            candidate_price=_money(candidate),
            minimum_safe_price=_money(minimum_safe_price) if minimum_safe_price is not None else None,
            unit_profit=_money(unit_profit) if unit_profit is not None else None,
            margin_rate=margin_rate,
            fee_breakdown=fee_breakdown or MarginGuardFeeBreakdown(None, None, None, None, None),
            rejection_reasons=list(dict.fromkeys(reasons)),
            policy_version=getattr(fee_policy, "version", None),
            calculation_version=self.calculation_version,
            percentage_fee_rate=fees.percentage_fee_rate,
            fixed_fee_amount=fees.fixed_per_order_fee + fees.fixed_per_unit_fee + fees.fulfilment_fee + fees.shipping_subsidy,
            other_variable_cost=fees.other_variable_cost,
            unit_cost=_money(unit_cost),
            minimum_required_margin=_decimal(policy.minimum_margin_rate),
            minimum_required_unit_profit=_money(_decimal(policy.minimum_unit_profit)),
            price_change_percentage=change_pct.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP) if change_pct is not None else None,
            marketplace_increment_valid=increment_valid,
        )


def _blocked_result(
    candidate: Decimal,
    reasons: list[MarginGuardRejectionReason],
    *,
    unit_cost: Decimal | None,
) -> MarginGuardResult:
    return MarginGuardResult(
        is_allowed=False,
        candidate_price=_money(candidate),
        minimum_safe_price=None,
        unit_profit=None,
        margin_rate=None,
        fee_breakdown=MarginGuardFeeBreakdown(None, None, None, None, None),
        rejection_reasons=list(dict.fromkeys(reasons)),
        policy_version=None,
        calculation_version=MarginGuard.calculation_version,
        percentage_fee_rate=None,
        fixed_fee_amount=None,
        other_variable_cost=None,
        unit_cost=_money(unit_cost) if unit_cost is not None else None,
        minimum_required_margin=None,
        minimum_required_unit_profit=None,
        price_change_percentage=None,
        marketplace_increment_valid=None,
    )


def _fee_inputs(policy) -> FeeInputs:
    return FeeInputs(
        percentage_commission_rate=_decimal(policy.percentage_commission_rate),
        payment_fee_rate=_decimal(policy.payment_fee_rate),
        fixed_per_order_fee=_decimal(policy.fixed_per_order_fee),
        fixed_per_unit_fee=_decimal(policy.fixed_per_unit_fee),
        fulfilment_fee=_decimal(policy.fulfilment_fee),
        shipping_subsidy=_decimal(policy.shipping_subsidy),
        other_variable_cost=_decimal(policy.other_variable_cost),
    )


def _guard_breakdown(breakdown: FeeBreakdown, fees: FeeInputs) -> MarginGuardFeeBreakdown:
    fixed_fees = fees.fixed_per_order_fee + fees.fixed_per_unit_fee + fees.fulfilment_fee + fees.shipping_subsidy
    return MarginGuardFeeBreakdown(
        percentage_commission_amount=_money(breakdown.percentage_commission_amount),
        payment_fee_amount=_money(breakdown.payment_fee_amount),
        fixed_fees=_money(fixed_fees),
        other_variable_cost=_money(fees.other_variable_cost),
        total_fee_amount=_money(breakdown.total_fee_amount),
    )


def _price_change_percentage(*, current_price: Decimal, candidate_price: Decimal) -> Decimal | None:
    if current_price <= 0:
        return None
    return (candidate_price - current_price) / current_price


def _increment_valid(candidate: Decimal, increment: Decimal) -> bool:
    if increment <= 0:
        return False
    return candidate.remainder_near(increment) == 0


def _decimal(value) -> Decimal:
    return Decimal(str(value))


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _json_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")
