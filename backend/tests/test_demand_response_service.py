from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
import unittest
from uuid import uuid4

from app.models.demand_elasticity_estimate import DemandEstimateDataStatus, DemandEstimationMethod
from app.models.sales_record import SalesRecordStatus
from app.services.demand_response_service import DemandObservation, DemandResponseConfig, DemandResponseService


class DemandResponseServiceTests(unittest.TestCase):
    def test_valid_historical_elasticity(self) -> None:
        seller_id, product_id = uuid4(), uuid4()
        service = DemandResponseService(config=_config())

        estimate = service.estimate_from_observations(
            seller_id=seller_id,
            product_id=product_id,
            observations=_observations(seller_id, product_id),
            as_of_date=date(2026, 6, 30),
        )

        self.assertEqual(DemandEstimationMethod.HISTORICAL_ELASTICITY, estimate.method)
        self.assertEqual(DemandEstimateDataStatus.SUFFICIENT, estimate.data_status)
        self.assertEqual(6, estimate.sample_count)
        self.assertLess(estimate.elasticity, Decimal("0"))
        self.assertIn("r_squared", estimate.quality_metrics)

    def test_insufficient_observations(self) -> None:
        seller_id, product_id = uuid4(), uuid4()
        estimate = DemandResponseService(config=_config(allow_fallback=False)).estimate_from_observations(
            seller_id=seller_id,
            product_id=product_id,
            observations=_observations(seller_id, product_id)[:2],
            as_of_date=date(2026, 6, 30),
        )

        self.assertEqual(DemandEstimationMethod.INSUFFICIENT_DATA, estimate.method)
        self.assertIn("insufficient_observations", estimate.quality_metrics["eligibility_failures"])

    def test_no_price_variation(self) -> None:
        seller_id, product_id = uuid4(), uuid4()
        obs = [
            _obs(seller_id, product_id, date(2026, 6, 1) + timedelta(days=i * 3), Decimal("100.00"), 10)
            for i in range(6)
        ]

        estimate = DemandResponseService(config=_config(allow_fallback=False)).estimate_from_observations(
            seller_id=seller_id,
            product_id=product_id,
            observations=obs,
            as_of_date=date(2026, 6, 30),
        )

        self.assertEqual(DemandEstimationMethod.INSUFFICIENT_DATA, estimate.method)
        self.assertIn("insufficient_price_variation", estimate.quality_metrics["eligibility_failures"])

    def test_zero_sales_periods_are_supported_with_adjustment(self) -> None:
        seller_id, product_id = uuid4(), uuid4()
        obs = _observations(seller_id, product_id)
        obs[0] = _obs(seller_id, product_id, obs[0].observed_date, obs[0].price, 0)

        estimate = DemandResponseService(config=_config()).estimate_from_observations(
            seller_id=seller_id,
            product_id=product_id,
            observations=obs,
            as_of_date=date(2026, 6, 30),
        )

        self.assertEqual(DemandEstimationMethod.HISTORICAL_ELASTICITY, estimate.method)
        self.assertEqual("ln(units + 1.0)", estimate.quality_metrics["zero_unit_transformation"])

    def test_promotion_distortion_blocks_historical(self) -> None:
        seller_id, product_id = uuid4(), uuid4()
        obs = _observations(seller_id, product_id)
        obs[1] = _obs(seller_id, product_id, obs[1].observed_date, obs[1].price, obs[1].units_sold, promotion=True)

        estimate = DemandResponseService(config=_config(allow_fallback=False)).estimate_from_observations(
            seller_id=seller_id,
            product_id=product_id,
            observations=obs,
            as_of_date=date(2026, 6, 30),
        )

        self.assertEqual(DemandEstimationMethod.INSUFFICIENT_DATA, estimate.method)
        self.assertIn("promotion_distortion", estimate.quality_metrics["eligibility_failures"])

    def test_returns_are_netted_once(self) -> None:
        seller_id, product_id = uuid4(), uuid4()
        obs = _observations(seller_id, product_id)
        obs[0] = _obs(seller_id, product_id, obs[0].observed_date, obs[0].price, 20, returned=3, restocked=2)

        estimate = DemandResponseService(config=_config()).estimate_from_observations(
            seller_id=seller_id,
            product_id=product_id,
            observations=obs,
            as_of_date=date(2026, 6, 30),
        )

        expected = sum(item.net_units for item in obs) / len(obs)
        self.assertEqual(Decimal(str(expected)).quantize(Decimal("0.0001")), estimate.baseline_units)

    def test_future_data_leakage_is_excluded(self) -> None:
        seller_id, product_id = uuid4(), uuid4()
        obs = _observations(seller_id, product_id)
        obs.append(_obs(seller_id, product_id, date(2026, 7, 10), Decimal("50.00"), 999))

        estimate = DemandResponseService(config=_config()).estimate_from_observations(
            seller_id=seller_id,
            product_id=product_id,
            observations=obs,
            as_of_date=date(2026, 6, 30),
        )

        self.assertEqual(6, estimate.sample_count)
        self.assertTrue(
            any(item["reason"] == "future_observation_excluded" for item in estimate.quality_metrics["rejected_observations"])
        )

    def test_implausible_elasticity_clamping(self) -> None:
        seller_id, product_id = uuid4(), uuid4()
        obs = [
            _obs(seller_id, product_id, date(2026, 6, 1), Decimal("100.00"), 2000),
            _obs(seller_id, product_id, date(2026, 6, 5), Decimal("110.00"), 400),
            _obs(seller_id, product_id, date(2026, 6, 9), Decimal("120.00"), 80),
            _obs(seller_id, product_id, date(2026, 6, 13), Decimal("130.00"), 10),
            _obs(seller_id, product_id, date(2026, 6, 17), Decimal("140.00"), 2),
            _obs(seller_id, product_id, date(2026, 6, 21), Decimal("150.00"), 0),
        ]

        estimate = DemandResponseService(config=_config()).estimate_from_observations(
            seller_id=seller_id,
            product_id=product_id,
            observations=obs,
            as_of_date=date(2026, 6, 30),
        )

        self.assertEqual(Decimal("-5.000000"), estimate.elasticity)
        self.assertTrue(estimate.quality_metrics["elasticity_clamped"])

    def test_heuristic_fallback(self) -> None:
        seller_id, product_id = uuid4(), uuid4()
        estimate = DemandResponseService(config=_config()).estimate_from_observations(
            seller_id=seller_id,
            product_id=product_id,
            observations=[],
            as_of_date=date(2026, 6, 30),
        )

        self.assertEqual(DemandEstimationMethod.CONSERVATIVE_HEURISTIC, estimate.method)
        self.assertEqual(Decimal("-0.800000"), estimate.elasticity)
        self.assertTrue(estimate.evidence["not_learned_from_seller_data"])

    def test_strict_no_fallback_policy(self) -> None:
        seller_id, product_id = uuid4(), uuid4()
        estimate = DemandResponseService(config=_config(allow_fallback=False)).estimate_from_observations(
            seller_id=seller_id,
            product_id=product_id,
            observations=[],
            as_of_date=date(2026, 6, 30),
        )

        self.assertEqual(DemandEstimationMethod.INSUFFICIENT_DATA, estimate.method)
        self.assertIsNone(estimate.elasticity)

    def test_uncertainty_range_and_cap(self) -> None:
        service = DemandResponseService(config=_config(max_multiplier="2.0"))
        estimate = service._fallback_or_insufficient(clean=[], rejected=[], reasons=["test"])

        forecast = service.forecast_candidate_units(
            current_price=Decimal("100.00"),
            candidate_price=Decimal("50.00"),
            baseline_units=Decimal("100.00"),
            forecast_horizon_days=30,
            baseline_period={"days": 30},
            estimate=estimate,
        )

        self.assertEqual(DemandEstimationMethod.CONSERVATIVE_HEURISTIC, forecast.method)
        self.assertLessEqual(forecast.upper_estimate, Decimal("200.0000"))
        self.assertLess(forecast.lower_estimate, forecast.central_estimate)
        self.assertGreater(forecast.upper_estimate, forecast.central_estimate)

    def test_seller_isolation(self) -> None:
        seller_id, other_seller, product_id = uuid4(), uuid4(), uuid4()
        obs = _observations(seller_id, product_id)
        obs.append(_obs(other_seller, product_id, date(2026, 6, 20), Decimal("50.00"), 999))

        estimate = DemandResponseService(config=_config()).estimate_from_observations(
            seller_id=seller_id,
            product_id=product_id,
            observations=obs,
            as_of_date=date(2026, 6, 30),
        )

        self.assertEqual(6, estimate.sample_count)
        self.assertTrue(
            any(item["reason"] == "seller_or_product_mismatch" for item in estimate.quality_metrics["rejected_observations"])
        )

    def test_deterministic_results(self) -> None:
        seller_id, product_id = uuid4(), uuid4()
        service = DemandResponseService(config=_config())
        obs = _observations(seller_id, product_id)

        first = service.estimate_from_observations(seller_id=seller_id, product_id=product_id, observations=obs, as_of_date=date(2026, 6, 30))
        second = service.estimate_from_observations(seller_id=seller_id, product_id=product_id, observations=list(reversed(obs)), as_of_date=date(2026, 6, 30))

        self.assertEqual(first.elasticity, second.elasticity)
        self.assertEqual(first.quality_metrics["r_squared"], second.quality_metrics["r_squared"])


def test_order_level_rows_estimate_like_daily_totals() -> None:
    seller_id, product_id = uuid4(), uuid4()
    service = DemandResponseService(config=_config())
    daily = _observations(seller_id, product_id)
    orders = [
        DemandObservation(
            seller_id=seller_id,
            product_id=product_id,
            observed_date=obs.observed_date,
            price=obs.price,
            units_sold=1,
            source_reference=f"order-{obs.observed_date}-{n}",
        )
        for obs in daily
        for n in range(obs.units_sold)
    ]

    by_day = service.estimate_from_observations(
        seller_id=seller_id, product_id=product_id, observations=daily, as_of_date=date(2026, 6, 30)
    )
    by_order = service.estimate_from_observations(
        seller_id=seller_id, product_id=product_id, observations=orders, as_of_date=date(2026, 6, 30)
    )

    assert by_order.method == DemandEstimationMethod.HISTORICAL_ELASTICITY
    assert by_order.sample_count == 6
    assert by_order.elasticity == by_day.elasticity
    assert by_order.baseline_units == by_day.baseline_units


def _observations(seller_id, product_id):
    return [
        _obs(seller_id, product_id, date(2026, 6, 1), Decimal("90.00"), 19),
        _obs(seller_id, product_id, date(2026, 6, 5), Decimal("95.00"), 18),
        _obs(seller_id, product_id, date(2026, 6, 9), Decimal("100.00"), 16),
        _obs(seller_id, product_id, date(2026, 6, 13), Decimal("105.00"), 15),
        _obs(seller_id, product_id, date(2026, 6, 17), Decimal("110.00"), 13),
        _obs(seller_id, product_id, date(2026, 6, 21), Decimal("115.00"), 12),
    ]


def _obs(seller_id, product_id, observed_date, price, units, *, returned=0, restocked=0, promotion=False):
    return DemandObservation(
        seller_id=seller_id,
        product_id=product_id,
        observed_date=observed_date,
        price=price,
        units_sold=units,
        returned_units=returned,
        refunded_restocked_units=restocked,
        status=SalesRecordStatus.COMPLETED,
        promotion_active=promotion,
        source_reference=f"{observed_date.isoformat()}:{price}",
    )


def _config(*, allow_fallback=True, max_multiplier="3.0") -> DemandResponseConfig:
    return DemandResponseConfig(
        min_observations=6,
        min_price_variation_rate=Decimal("0.05"),
        min_coverage_days=14,
        max_data_age_days=45,
        zero_unit_adjustment=Decimal("1.0"),
        min_elasticity=Decimal("-5.0"),
        max_elasticity=Decimal("-0.1"),
        conservative_elasticity_prior=Decimal("-0.8"),
        allow_heuristic_fallback=allow_fallback,
        max_forecast_multiplier=Decimal(max_multiplier),
        calculation_version="v1",
    )


if __name__ == "__main__":
    unittest.main()
