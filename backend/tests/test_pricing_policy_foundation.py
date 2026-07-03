from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from uuid import uuid4

from app.models.marketplace_fee_policy import MarketplaceFeePolicy
from app.services.pricing_calculator import FeeInputs, PricingCalculationError, PricingCalculator
from app.services.pricing_policy_service import select_effective_fee_policy


class PricingCalculatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calculator = PricingCalculator(currency="BDT")

    def test_percentage_fee(self) -> None:
        breakdown = self.calculator.calculate_fee_breakdown(
            price=Decimal("1000.00"),
            fees=FeeInputs(percentage_commission_rate=Decimal("0.10")),
        )

        self.assertEqual(Decimal("100.0000"), breakdown.percentage_commission_amount.quantize(Decimal("0.0001")))
        self.assertEqual(Decimal("100.0000"), breakdown.total_fee_amount.quantize(Decimal("0.0001")))

    def test_fixed_fee(self) -> None:
        profit = self.calculator.calculate_unit_profit(
            price=Decimal("500.00"),
            unit_cost=Decimal("300.00"),
            fees=FeeInputs(fixed_per_order_fee=Decimal("20.00"), fixed_per_unit_fee=Decimal("5.00")),
        )

        self.assertEqual(Decimal("175.00"), profit)

    def test_combined_fees_and_margin(self) -> None:
        fees = FeeInputs(
            percentage_commission_rate=Decimal("0.08"),
            payment_fee_rate=Decimal("0.02"),
            fixed_per_order_fee=Decimal("10.00"),
            fulfilment_fee=Decimal("15.00"),
            shipping_subsidy=Decimal("5.00"),
            other_variable_cost=Decimal("2.00"),
        )

        profit = self.calculator.calculate_unit_profit(price=Decimal("1000.00"), unit_cost=Decimal("600.00"), fees=fees)
        margin = self.calculator.calculate_margin_rate(price=Decimal("1000.00"), unit_cost=Decimal("600.00"), fees=fees)

        self.assertEqual(Decimal("268.0000"), profit.quantize(Decimal("0.0001")))
        self.assertEqual(Decimal("0.268000"), margin)

    def test_minimum_margin_safe_price(self) -> None:
        safe = self.calculator.calculate_minimum_safe_price(
            unit_cost=Decimal("600.00"),
            fees=FeeInputs(percentage_commission_rate=Decimal("0.10"), fixed_per_unit_fee=Decimal("20.00")),
            minimum_margin_rate=Decimal("0.20"),
            price_increment=Decimal("1.00"),
        )

        self.assertEqual(Decimal("886.00"), safe)

    def test_minimum_unit_profit_can_raise_safe_price(self) -> None:
        safe = self.calculator.calculate_minimum_safe_price(
            unit_cost=Decimal("100.00"),
            fees=FeeInputs(percentage_commission_rate=Decimal("0.10")),
            minimum_margin_rate=Decimal("0.05"),
            minimum_unit_profit=Decimal("100.00"),
            price_increment=Decimal("1.00"),
        )

        self.assertEqual(Decimal("223.00"), safe)

    def test_invalid_total_rate(self) -> None:
        with self.assertRaises(PricingCalculationError):
            self.calculator.calculate_minimum_safe_price(
                unit_cost=Decimal("100.00"),
                fees=FeeInputs(percentage_commission_rate=Decimal("0.60")),
                minimum_margin_rate=Decimal("0.40"),
            )

    def test_negative_fee_rejection(self) -> None:
        with self.assertRaises(PricingCalculationError):
            self.calculator.calculate_fee_breakdown(
                price=Decimal("100.00"),
                fees=FeeInputs(fixed_per_unit_fee=Decimal("-1.00")),
            )

    def test_currency_rounding(self) -> None:
        self.assertEqual(Decimal("10.24"), self.calculator.round_currency(Decimal("10.235")))

    def test_marketplace_increment_rounding(self) -> None:
        self.assertEqual(
            Decimal("100.00"),
            self.calculator.round_to_marketplace_increment(Decimal("99.51"), Decimal("1.00"), direction="up"),
        )
        self.assertEqual(
            Decimal("99.50"),
            self.calculator.round_to_marketplace_increment(Decimal("99.51"), Decimal("0.50"), direction="down"),
        )

    def test_candidate_validation_reasons(self) -> None:
        result = self.calculator.validate_candidate_price(
            candidate_price=Decimal("80.00"),
            current_price=Decimal("100.00"),
            unit_cost=Decimal("70.00"),
            fees=FeeInputs(percentage_commission_rate=Decimal("0.10")),
            minimum_margin_rate=Decimal("0.20"),
            minimum_unit_profit=Decimal("0.00"),
            price_increment=Decimal("1.00"),
            maximum_price_decrease_rate=Decimal("0.10"),
        )

        self.assertFalse(result.is_valid)
        self.assertIn("below_minimum_safe_price", result.reasons)
        self.assertIn("exceeds_maximum_price_decrease", result.reasons)


class PricingFeeSelectionTests(unittest.TestCase):
    def test_effective_date_selection_uses_latest_valid_policy(self) -> None:
        product_id = uuid4()
        now = datetime(2026, 7, 1, tzinfo=timezone.utc)
        older = _fee(product_id=None, category=None, effective_from=now - timedelta(days=10), version="old")
        latest = _fee(product_id=None, category=None, effective_from=now - timedelta(days=1), version="new")

        selected = select_effective_fee_policy([older, latest], product_id=product_id, category="Beauty", as_of=now)

        self.assertEqual("new", selected.version)

    def test_seller_level_default(self) -> None:
        product_id = uuid4()
        now = datetime(2026, 7, 1, tzinfo=timezone.utc)
        selected = select_effective_fee_policy(
            [_fee(product_id=None, category=None, effective_from=now - timedelta(days=1), version="seller")],
            product_id=product_id,
            category="Beauty",
            as_of=now,
        )

        self.assertEqual("seller", selected.version)

    def test_product_override_wins_over_category_and_seller_default(self) -> None:
        product_id = uuid4()
        now = datetime(2026, 7, 1, tzinfo=timezone.utc)
        seller_default = _fee(product_id=None, category=None, effective_from=now - timedelta(days=1), version="seller")
        category_default = _fee(product_id=None, category="Beauty", effective_from=now - timedelta(days=1), version="category")
        product_override = _fee(product_id=product_id, category=None, effective_from=now - timedelta(days=2), version="product")

        selected = select_effective_fee_policy(
            [seller_default, category_default, product_override],
            product_id=product_id,
            category="Beauty",
            as_of=now,
        )

        self.assertEqual("product", selected.version)

    def test_historical_fee_preservation_selects_by_as_of(self) -> None:
        product_id = uuid4()
        now = datetime(2026, 7, 1, tzinfo=timezone.utc)
        old = _fee(
            product_id=None,
            category=None,
            effective_from=now - timedelta(days=10),
            effective_to=now - timedelta(days=2),
            version="old",
        )
        new = _fee(product_id=None, category=None, effective_from=now - timedelta(days=2), version="new")

        selected = select_effective_fee_policy(
            [old, new],
            product_id=product_id,
            category=None,
            as_of=now - timedelta(days=5),
        )

        self.assertEqual("old", selected.version)

    def test_seller_isolation_is_enforced_by_candidate_scope(self) -> None:
        product_id = uuid4()
        now = datetime(2026, 7, 1, tzinfo=timezone.utc)
        seller_a = uuid4()
        seller_b = uuid4()
        candidates = [
            _fee(product_id=None, category=None, effective_from=now - timedelta(days=1), version="seller-a", seller_id=seller_a),
            _fee(product_id=None, category=None, effective_from=now - timedelta(days=1), version="seller-b", seller_id=seller_b),
        ]
        seller_a_candidates = [fee for fee in candidates if fee.seller_id == seller_a]

        selected = select_effective_fee_policy(
            seller_a_candidates,
            product_id=product_id,
            category=None,
            as_of=now,
        )

        self.assertEqual("seller-a", selected.version)


def _fee(
    *,
    product_id,
    category,
    effective_from,
    version,
    seller_id=None,
    effective_to=None,
):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=seller_id or uuid4(),
        product_id=product_id,
        marketplace="Daraz Bangladesh",
        category=category,
        currency="BDT",
        percentage_commission_rate=Decimal("0.10"),
        payment_fee_rate=Decimal("0.01"),
        fixed_per_order_fee=Decimal("0.00"),
        fixed_per_unit_fee=Decimal("0.00"),
        fulfilment_fee=Decimal("0.00"),
        shipping_subsidy=Decimal("0.00"),
        other_variable_cost=Decimal("0.00"),
        source="TEST",
        version=version,
        is_active=True,
        effective_from=effective_from,
        effective_to=effective_to,
        created_at=effective_from,
    )


if __name__ == "__main__":
    unittest.main()
