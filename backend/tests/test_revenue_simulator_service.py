from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.models.demand_elasticity_estimate import DemandEstimateDataStatus, DemandEstimationMethod
from app.services.demand_response_service import DemandElasticityResult
from app.services.revenue_simulator_service import RevenueSimulatorService


class RevenueSimulatorServiceTests(unittest.TestCase):
    def test_simulation_uses_margin_guard_and_forecast(self) -> None:
        seller_id = uuid4()
        product_id = uuid4()
        analytics_id = uuid4()
        product = SimpleNamespace(
            id=product_id,
            seller_id=seller_id,
            title="Test product",
        )
        analytics = SimpleNamespace(
            id=analytics_id,
            current_price=Decimal("100.00"),
            recent_net_sales=30,
            daily_sales_rate=None,
            data_status=SimpleNamespace(value="SUFFICIENT"),
            confidence_score=Decimal("80.00"),
        )
        estimate = DemandElasticityResult(
            method=DemandEstimationMethod.CONSERVATIVE_HEURISTIC,
            elasticity=Decimal("-0.8"),
            sample_count=0,
            baseline_units=None,
            observation_start=None,
            observation_end=None,
            price_range=None,
            quality_metrics={},
            confidence=Decimal("40.00"),
            data_status=DemandEstimateDataStatus.LIMITED,
            calculation_version="v1",
            evidence={},
        )

        service = RevenueSimulatorService(db=None)
        service._product = lambda **kwargs: product

        with (
            patch(
                "app.services.revenue_simulator_service.PricingAnalyticsService",
                lambda db: SimpleNamespace(latest=lambda **kwargs: analytics),
            ),
            patch(
                "app.services.revenue_simulator_service.DemandResponseService",
                lambda *args, **kwargs: SimpleNamespace(
                    estimate_for_product=lambda **kwargs: estimate,
                    forecast_candidate_units=lambda **kwargs: SimpleNamespace(
                        lower_estimate=Decimal("25.0000"),
                        central_estimate=Decimal("30.0000"),
                        upper_estimate=Decimal("35.0000"),
                        confidence=Decimal("40.00"),
                        method=DemandEstimationMethod.CONSERVATIVE_HEURISTIC,
                        data_status=DemandEstimateDataStatus.LIMITED,
                        assumptions={},
                        calculation_version="v1",
                    ),
                ),
            ),
            patch(
                "app.services.revenue_simulator_service.MarginGuard",
                lambda db: SimpleNamespace(validate_candidate=lambda **kwargs: _guard()),
            ),
        ):
            result = service.simulate(
                seller_id=seller_id,
                product_id=product_id,
                candidate_prices=[Decimal("110.00")],
                forecast_horizon_days=30,
            )

        self.assertEqual(analytics_id, result.pricing_analytics_id)
        self.assertEqual(Decimal("30.0000"), result.baseline_units)
        self.assertEqual(Decimal("3300.00"), result.scenarios[0].expected_revenue)
        self.assertEqual(Decimal("900.00"), result.scenarios[0].expected_profit)
        self.assertEqual("-0.8", result.evidence["elasticity"])
        self.assertEqual(0, result.evidence["elasticity_sample_count"])

    def test_simulation_prepares_missing_pricing_analytics_snapshot(self) -> None:
        seller_id = uuid4()
        product_id = uuid4()
        analytics_id = uuid4()
        product = SimpleNamespace(
            id=product_id,
            seller_id=seller_id,
            title="Test product",
        )
        analytics = SimpleNamespace(
            id=analytics_id,
            current_price=Decimal("100.00"),
            recent_net_sales=30,
            daily_sales_rate=None,
            data_status=SimpleNamespace(value="LIMITED"),
            confidence_score=Decimal("60.00"),
        )
        estimate = DemandElasticityResult(
            method=DemandEstimationMethod.CONSERVATIVE_HEURISTIC,
            elasticity=Decimal("-0.8"),
            sample_count=0,
            baseline_units=None,
            observation_start=None,
            observation_end=None,
            price_range=None,
            quality_metrics={},
            confidence=Decimal("40.00"),
            data_status=DemandEstimateDataStatus.LIMITED,
            calculation_version="v1",
            evidence={},
        )
        generated = {"called": False}

        class AnalyticsStub:
            def __init__(self, db) -> None:
                pass

            def latest(self, **kwargs):
                return None

            def generate_for_product(self, **kwargs):
                generated["called"] = True
                return analytics

        service = RevenueSimulatorService(db=None)
        service._product = lambda **kwargs: product

        with (
            patch("app.services.revenue_simulator_service.PricingAnalyticsService", AnalyticsStub),
            patch(
                "app.services.revenue_simulator_service.DemandResponseService",
                lambda *args, **kwargs: SimpleNamespace(
                    estimate_for_product=lambda **kwargs: estimate,
                    forecast_candidate_units=lambda **kwargs: SimpleNamespace(
                        lower_estimate=Decimal("25.0000"),
                        central_estimate=Decimal("30.0000"),
                        upper_estimate=Decimal("35.0000"),
                        confidence=Decimal("40.00"),
                        method=DemandEstimationMethod.CONSERVATIVE_HEURISTIC,
                        data_status=DemandEstimateDataStatus.LIMITED,
                        assumptions={},
                        calculation_version="v1",
                    ),
                ),
            ),
            patch(
                "app.services.revenue_simulator_service.MarginGuard",
                lambda db: SimpleNamespace(validate_candidate=lambda **kwargs: _guard()),
            ),
        ):
            result = service.simulate(
                seller_id=seller_id,
                product_id=product_id,
                candidate_prices=[Decimal("110.00")],
                forecast_horizon_days=30,
            )

        self.assertTrue(generated["called"])
        self.assertEqual(analytics_id, result.pricing_analytics_id)


def _guard():
    return SimpleNamespace(
        is_allowed=True,
        unit_profit=Decimal("30.00"),
        margin_rate=Decimal("0.300000"),
        minimum_safe_price=Decimal("80.00"),
        rejection_reasons=[],
        to_evidence=lambda: {},
    )


if __name__ == "__main__":
    unittest.main()
