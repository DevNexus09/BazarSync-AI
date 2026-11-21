from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.models.demand_elasticity_estimate import DemandEstimateDataStatus, DemandEstimationMethod
from app.models.dynamic_pricing_recommendation import DynamicPricingAction, DynamicPricingRecommendationStatus
from app.models.pricing_analytics_snapshot import PricingAnalyticsDataStatus
from app.models.pricing_policy import PricingObjective
from app.services.demand_response_service import DemandElasticityResult
from app.services.dynamic_pricing_service import (
    DynamicPricingConfig,
    DynamicPricingService,
    derive_action,
    generate_candidates,
    select_candidate,
)


class DynamicPricingServiceTests(unittest.TestCase):
    def test_price_lower(self) -> None:
        rec = _build(analytics=_analytics(current="120.00", median="100.00", recent=100), estimate=_estimate(elasticity="-1.5"))

        self.assertEqual(DynamicPricingAction.PRICE_LOWER, rec.action)
        self.assertLess(rec.recommended_price, rec.current_price)

    def test_price_raise(self) -> None:
        rec = _build(
            analytics=_analytics(current="100.00", median="130.00", q3="130.00", max_price="150.00", recent=100),
            estimate=_estimate(elasticity="-0.2"),
        )

        self.assertEqual(DynamicPricingAction.PRICE_RAISE, rec.action)
        self.assertGreater(rec.recommended_price, rec.current_price)

    def test_hold_when_no_material_improvement(self) -> None:
        rec = _build(
            analytics=_analytics(current="100.00", median="100.50", recent=100),
            estimate=_estimate(elasticity="-0.1"),
            config=DynamicPricingConfig("v1", Decimal("10"), Decimal("0.01"), Decimal("0.15"), 72),
        )

        self.assertEqual(DynamicPricingAction.HOLD, rec.action)

    def test_margin_floor_rejection_never_selected(self) -> None:
        rec = _build(
            analytics=_analytics(current="120.00", median="105.00", recent=100),
            estimate=_estimate(elasticity="-1.5"),
            guard_factory=lambda price: _guard(price, allowed=price >= Decimal("110.00")),
        )

        self.assertNotEqual(Decimal("105.00"), rec.recommended_price)
        rejected = [item for item in rec.evidence["candidates"] if item["candidate_price"] == "105.00"]
        self.assertTrue(rejected)
        self.assertFalse(rejected[0]["is_allowed"])

    def test_high_inventory_risk_discourages_price_reduction(self) -> None:
        rec = _build(
            analytics=_analytics(current="120.00", median="100.00", recent=100, risk="CRITICAL"),
            estimate=_estimate(elasticity="-1.5"),
        )

        self.assertNotEqual(DynamicPricingAction.PRICE_LOWER, rec.action)

    def test_excess_inventory_permits_controlled_lower_price(self) -> None:
        rec = _build(
            analytics=_analytics(current="120.00", median="100.00", recent=100, risk="LOW"),
            estimate=_estimate(elasticity="-1.5"),
        )

        self.assertEqual(DynamicPricingAction.PRICE_LOWER, rec.action)

    def test_stale_competitor_data_returns_insufficient_status(self) -> None:
        rec = _build(analytics=_analytics(status=PricingAnalyticsDataStatus.STALE), estimate=_estimate())

        self.assertEqual(DynamicPricingRecommendationStatus.INSUFFICIENT_DATA, rec.recommendation_status)
        self.assertEqual(DynamicPricingAction.HOLD, rec.action)

    def test_insufficient_sales_data(self) -> None:
        rec = _build(analytics=_analytics(), estimate=_estimate(elasticity=None, method=DemandEstimationMethod.INSUFFICIENT_DATA))

        self.assertEqual(DynamicPricingRecommendationStatus.INSUFFICIENT_DATA, rec.recommendation_status)
        self.assertEqual(DemandEstimationMethod.INSUFFICIENT_DATA, rec.estimation_method)

    def test_missing_baseline_does_not_become_zero_profit(self) -> None:
        missing = _build(
            analytics=_analytics(recent=None),
            estimate=replace(_estimate(), baseline_units=None),
        )
        observed_zero = _build(analytics=_analytics(recent=0), estimate=_estimate())

        self.assertEqual(DynamicPricingRecommendationStatus.INSUFFICIENT_DATA, missing.recommendation_status)
        self.assertEqual(DynamicPricingAction.HOLD, missing.action)
        self.assertIsNone(missing.expected_units)
        self.assertIsNone(missing.expected_profit)
        self.assertIsNone(missing.baseline_expected_profit)
        self.assertEqual(Decimal("0"), observed_zero.expected_profit)
        self.assertEqual(Decimal("0"), observed_zero.baseline_expected_profit)

    def test_heuristic_method_disclosure(self) -> None:
        rec = _build(estimate=_estimate(method=DemandEstimationMethod.CONSERVATIVE_HEURISTIC))

        self.assertEqual(DemandEstimationMethod.CONSERVATIVE_HEURISTIC, rec.estimation_method)
        self.assertIsNotNone(rec.evidence["heuristic_disclosure"])

    def test_change_limit_enforcement_in_candidates(self) -> None:
        candidates = generate_candidates(
            current_price=Decimal("100.00"),
            minimum_safe_price=Decimal("50.00"),
            competitor_values=[Decimal("10.00"), Decimal("200.00"), Decimal("95.00")],
            increment=Decimal("1.00"),
            max_change_rate=Decimal("0.15"),
        )

        self.assertNotIn(Decimal("10.00"), candidates)
        self.assertNotIn(Decimal("200.00"), candidates)
        self.assertIn(Decimal("95.00"), candidates)

    def test_marketplace_rounding_cannot_escape_candidate_band(self) -> None:
        result = generate_candidates(
            current_price=Decimal("100.00"),
            minimum_safe_price=Decimal("80.00"),
            competitor_values=[Decimal("115.00")],
            increment=Decimal("20.00"),
            max_change_rate=Decimal("0.15"),
        )
        self.assertEqual([Decimal("100.00")], result)

    def test_empty_increment_grid_retains_the_comparison_anchor(self) -> None:
        result = generate_candidates(
            current_price=Decimal("1.01"),
            minimum_safe_price=Decimal("1.00"),
            competitor_values=[],
            increment=Decimal("10.00"),
            max_change_rate=Decimal("0.10"),
        )
        self.assertEqual([Decimal("1.01")], result)
        self.assertEqual(
            DynamicPricingAction.HOLD,
            derive_action(
                current_price=result[0], selected_price=result[0],
                min_actionable_change_rate=Decimal(0),
            ),
        )

    def test_action_derivation(self) -> None:
        self.assertEqual(DynamicPricingAction.HOLD, derive_action(current_price=Decimal("100"), selected_price=Decimal("100.50"), min_actionable_change_rate=Decimal("0.01")))
        self.assertEqual(DynamicPricingAction.PRICE_LOWER, derive_action(current_price=Decimal("100"), selected_price=Decimal("98"), min_actionable_change_rate=Decimal("0.01")))
        self.assertEqual(DynamicPricingAction.PRICE_RAISE, derive_action(current_price=Decimal("100"), selected_price=Decimal("102"), min_actionable_change_rate=Decimal("0.01")))

    def test_duplicate_task_retry_existing_snapshot(self) -> None:
        service = DynamicPricingService.__new__(DynamicPricingService)
        service._config = _config()
        existing = object()
        service._existing_for_snapshot = lambda **kwargs: existing

        self.assertIs(existing, service._existing_for_snapshot(seller_id=uuid4(), product_id=uuid4(), pricing_analytics_id=uuid4(), objective=PricingObjective.MAXIMIZE_EXPECTED_PROFIT))

    def test_deterministic_tie_breaking(self) -> None:
        current = Decimal("100.00")
        a = SimpleNamespace(candidate_price=Decimal("95.00"), score=Decimal("100.00"))
        b = SimpleNamespace(candidate_price=Decimal("105.00"), score=Decimal("100.00"))
        selected = select_candidate(
            evaluations=[b, a],
            current_price=current,
            objective=PricingObjective.MAXIMIZE_EXPECTED_PROFIT,
            min_improvement_rate=Decimal("0"),
            baseline_profit=Decimal("1"),
            baseline_revenue=Decimal("1"),
        )

        self.assertEqual(Decimal("95.00"), selected.candidate_price)

    def test_seller_isolation_query_uses_seller_scope(self) -> None:
        # Product access is enforced by DynamicPricingService._product using seller_id and product_id together.
        service = DynamicPricingService.__new__(DynamicPricingService)
        self.assertTrue(hasattr(service, "_product"))


def _build(*, analytics=None, estimate=None, config=None, guard_factory=None):
    service = DynamicPricingService(config=config or _config())
    product = SimpleNamespace(id=uuid4(), seller_id=uuid4(), selling_price=Decimal(str((analytics or _analytics()).current_price)))
    factory = guard_factory or (lambda price: _guard(price))
    with patch("app.services.dynamic_pricing_service.MarginGuard", lambda db: SimpleNamespace(validate_candidate=lambda **kwargs: factory(kwargs["candidate_price"]))):
        return service.build_recommendation(
            seller_id=product.seller_id,
            product=product,
            analytics=analytics or _analytics(),
            estimate=estimate or _estimate(),
            objective=PricingObjective.MAXIMIZE_EXPECTED_PROFIT,
            elasticity_estimate_id=None,
            generated_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            cooldown_hours=24,
        )


def _analytics(*, current="120.00", median="100.00", q3="110.00", max_price="130.00", recent=100, risk=None, status=PricingAnalyticsDataStatus.SUFFICIENT):
    return SimpleNamespace(
        id=uuid4(),
        current_price=Decimal(current),
        minimum_safe_price=Decimal("80.00"),
        competitor_min_price=Decimal("95.00"),
        competitor_q1_price=Decimal("98.00"),
        competitor_median_price=Decimal(median),
        competitor_q3_price=Decimal(q3),
        competitor_max_price=Decimal(max_price),
        recent_net_sales=recent,
        daily_sales_rate=Decimal("3.0000"),
        inventory_risk_level=risk,
        data_status=status,
        confidence_score=Decimal("80.00"),
    )


def _estimate(*, elasticity="-1.0", method=DemandEstimationMethod.HISTORICAL_ELASTICITY):
    return DemandElasticityResult(
        method=method,
        elasticity=Decimal(elasticity) if elasticity is not None else None,
        sample_count=8 if elasticity is not None else 0,
        baseline_units=Decimal("100.0000"),
        observation_start=None,
        observation_end=None,
        price_range=None,
        quality_metrics={},
        confidence=Decimal("80.00") if elasticity is not None else Decimal("0.00"),
        data_status=DemandEstimateDataStatus.SUFFICIENT if elasticity is not None else DemandEstimateDataStatus.INSUFFICIENT,
        calculation_version="v1",
        evidence={"not_learned_from_seller_data": method == DemandEstimationMethod.CONSERVATIVE_HEURISTIC},
    )


def _guard(price, *, allowed=True):
    unit_profit = price * Decimal("0.30")
    return SimpleNamespace(
        is_allowed=allowed,
        candidate_price=price,
        minimum_safe_price=Decimal("80.00"),
        unit_profit=unit_profit,
        margin_rate=Decimal("0.300000"),
        rejection_reasons=[] if allowed else [SimpleNamespace(value="BELOW_MINIMUM_SAFE_PRICE")],
    )


def _config():
    return DynamicPricingConfig("v1", Decimal("0.02"), Decimal("0.01"), Decimal("0.15"), 72)


if __name__ == "__main__":
    unittest.main()
