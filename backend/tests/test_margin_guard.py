from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.models.recommendation import RecommendationAction
from app.services.margin_guard import MarginGuard, MarginGuardRejectionReason
from app.services.recommendation_service import RecommendationService


class MarginGuardTests(unittest.TestCase):
    def test_price_exactly_at_safe_floor(self) -> None:
        result = _guard().validate_candidate(
            seller_id=uuid4(),
            product=_product(cost="600.00", price="1000.00"),
            candidate_price=Decimal("858.00"),
        )

        self.assertTrue(result.is_allowed)
        self.assertEqual(Decimal("858.00"), result.minimum_safe_price)
        self.assertEqual([], result.rejection_reasons)

    def test_one_currency_increment_below_floor(self) -> None:
        result = _guard().validate_candidate(
            seller_id=uuid4(),
            product=_product(cost="600.00", price="1000.00"),
            candidate_price=Decimal("857.00"),
        )

        self.assertFalse(result.is_allowed)
        self.assertIn(MarginGuardRejectionReason.BELOW_MINIMUM_SAFE_PRICE, result.rejection_reasons)

    def test_negative_profit(self) -> None:
        result = _guard().validate_candidate(
            seller_id=uuid4(),
            product=_product(cost="600.00", price="1000.00"),
            candidate_price=Decimal("400.00"),
        )

        self.assertIn(MarginGuardRejectionReason.NEGATIVE_UNIT_PROFIT, result.rejection_reasons)

    def test_minimum_margin_boundary(self) -> None:
        result = _guard(policy=_policy(min_margin="0.20")).validate_candidate(
            seller_id=uuid4(),
            product=_product(cost="600.00", price="1000.00"),
            candidate_price=Decimal("858.00"),
        )

        self.assertGreaterEqual(result.margin_rate, Decimal("0.200000"))
        self.assertNotIn(MarginGuardRejectionReason.BELOW_MINIMUM_MARGIN, result.rejection_reasons)

    def test_minimum_unit_profit_boundary(self) -> None:
        result = _guard(policy=_policy(min_margin="0.05", min_profit="100.00")).validate_candidate(
            seller_id=uuid4(),
            product=_product(cost="100.00", price="300.00"),
            candidate_price=Decimal("223.00"),
        )

        self.assertTrue(result.unit_profit >= Decimal("100.00"))
        self.assertNotIn(MarginGuardRejectionReason.BELOW_MINIMUM_UNIT_PROFIT, result.rejection_reasons)

    def test_maximum_increase(self) -> None:
        result = _guard(policy=_policy(max_increase="0.10")).validate_candidate(
            seller_id=uuid4(),
            product=_product(cost="100.00", price="100.00"),
            candidate_price=Decimal("120.00"),
        )

        self.assertIn(MarginGuardRejectionReason.EXCEEDS_MAXIMUM_INCREASE, result.rejection_reasons)

    def test_maximum_decrease(self) -> None:
        result = _guard(policy=_policy(max_decrease="0.10")).validate_candidate(
            seller_id=uuid4(),
            product=_product(cost="100.00", price="200.00"),
            candidate_price=Decimal("150.00"),
        )

        self.assertIn(MarginGuardRejectionReason.EXCEEDS_MAXIMUM_DECREASE, result.rejection_reasons)

    def test_missing_cost(self) -> None:
        result = _guard().validate_candidate(
            seller_id=uuid4(),
            product=_product(cost=None, price="200.00"),
            candidate_price=Decimal("150.00"),
        )

        self.assertFalse(result.is_allowed)
        self.assertIn(MarginGuardRejectionReason.MISSING_COST_DATA, result.rejection_reasons)

    def test_missing_fees(self) -> None:
        result = _guard(fee=_fee(id=None, is_default=True)).validate_candidate(
            seller_id=uuid4(),
            product=_product(cost="100.00", price="200.00"),
            candidate_price=Decimal("150.00"),
        )

        self.assertFalse(result.is_allowed)
        self.assertIn(MarginGuardRejectionReason.MISSING_FEE_DATA, result.rejection_reasons)

    def test_invalid_policy(self) -> None:
        result = _guard(policy=_policy(min_margin="0.95"), fee=_fee(commission="0.10")).validate_candidate(
            seller_id=uuid4(),
            product=_product(cost="100.00", price="200.00"),
            candidate_price=Decimal("150.00"),
        )

        self.assertFalse(result.is_allowed)
        self.assertIn(MarginGuardRejectionReason.INVALID_POLICY, result.rejection_reasons)

    def test_decimal_rounding_boundary_and_increment(self) -> None:
        result = _guard(policy=_policy(increment="0.05")).validate_candidate(
            seller_id=uuid4(),
            product=_product(cost="100.00", price="200.00"),
            candidate_price=Decimal("175.03"),
        )

        self.assertIn(MarginGuardRejectionReason.INVALID_MARKETPLACE_INCREMENT, result.rejection_reasons)

    def test_absolute_bounds(self) -> None:
        result = _guard(policy=_policy(min_price="150.00", max_price="250.00")).validate_candidate(
            seller_id=uuid4(),
            product=_product(cost="100.00", price="200.00"),
            candidate_price=Decimal("260.00"),
        )

        self.assertIn(MarginGuardRejectionReason.ABOVE_ABSOLUTE_MAXIMUM, result.rejection_reasons)


class RecommendationMarginGuardTests(unittest.TestCase):
    def test_recommendation_save_cannot_select_lower_without_successful_guard(self) -> None:
        db = FakeDb()
        service = RecommendationService(db)
        product = _product(cost="100.00", price="200.00")
        ai_response = _ai_response("LOWER")
        analytics = {"competitor_median_price": 120.0}

        with patch("app.services.recommendation_service.MarginGuard", FakeBlockingGuard):
            recommendation = service.save_recommendation(product, ai_response, {"recommended_action": "LOWER"}, analytics)

        self.assertTrue(FakeBlockingGuard.called)
        self.assertEqual(RecommendationAction.HOLD, recommendation.action)
        self.assertEqual("LOW", recommendation.confidence.value)
        self.assertTrue(recommendation.recommendation_context["margin_guard"]["fail_closed"])
        self.assertEqual(Decimal("0.00"), recommendation.revenue_opportunity)


def _guard(*, policy=None, fee=None) -> MarginGuard:
    return MarginGuard(
        FakeDb(),
        pricing_policy_service_factory=lambda db: FakePricingPolicyService(policy or _policy(), fee or _fee()),
    )


def _product(*, cost, price):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=uuid4(),
        cost_price=Decimal(cost) if cost is not None else None,
        selling_price=Decimal(price),
    )


def _policy(
    *,
    min_margin="0.20",
    min_profit="0.00",
    max_decrease=None,
    max_increase=None,
    min_price=None,
    max_price=None,
    increment="1.00",
):
    return SimpleNamespace(
        id=uuid4(),
        currency="BDT",
        minimum_margin_rate=Decimal(min_margin),
        minimum_unit_profit=Decimal(min_profit),
        maximum_price_decrease_rate=Decimal(max_decrease) if max_decrease is not None else None,
        maximum_price_increase_rate=Decimal(max_increase) if max_increase is not None else None,
        minimum_allowed_price=Decimal(min_price) if min_price is not None else None,
        maximum_allowed_price=Decimal(max_price) if max_price is not None else None,
        price_increment=Decimal(increment),
    )


def _fee(*, id=None, is_default=False, commission="0.10"):
    return SimpleNamespace(
        id=id if id is not None else uuid4(),
        version="v1",
        is_default=is_default,
        percentage_commission_rate=Decimal(commission),
        payment_fee_rate=Decimal("0.00"),
        fixed_per_order_fee=Decimal("0.00"),
        fixed_per_unit_fee=Decimal("0.00"),
        fulfilment_fee=Decimal("0.00"),
        shipping_subsidy=Decimal("0.00"),
        other_variable_cost=Decimal("0.00"),
    )


def _ai_response(action: str):
    return SimpleNamespace(
        recommendation=SimpleNamespace(
            action=action,
            confidence="HIGH",
            reasoning_bn="দাম কমানোর সুপারিশ।",
            revenue_opportunity=100,
        )
    )


class FakePricingPolicyService:
    def __init__(self, policy, fee) -> None:
        self.policy = policy
        self.fee = fee

    def get_product_policy(self, **kwargs):
        return self.policy

    def effective_fee_policy(self, **kwargs):
        return self.fee


class FakeDb:
    def add(self, item):
        self.item = item

    def commit(self):
        pass

    def refresh(self, item):
        pass


class FakeBlockingGuard:
    called = False

    def __init__(self, db):
        pass

    def validate_candidate(self, **kwargs):
        FakeBlockingGuard.called = True
        return SimpleNamespace(
            is_allowed=False,
            candidate_price=Decimal("120.00"),
            rejection_reasons=[MarginGuardRejectionReason.BELOW_MINIMUM_SAFE_PRICE],
            to_evidence=lambda: {
                "is_allowed": False,
                "candidate_price": "120.00",
                "rejection_reasons": [MarginGuardRejectionReason.BELOW_MINIMUM_SAFE_PRICE.value],
            },
        )


if __name__ == "__main__":
    unittest.main()
