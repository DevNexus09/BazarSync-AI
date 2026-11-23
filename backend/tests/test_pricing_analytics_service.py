from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
import unittest

from app.models.competitor_ranking import CompetitorRanking
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.pricing_analytics_snapshot import PricingAnalyticsDataStatus
from app.models.sales_velocity import SalesVelocityDataStatus
from app.services.pricing_analytics_service import (
    PricingAnalyticsConfig,
    calculate_confidence,
    calculate_demand_score,
    calculate_market_stats,
    determine_data_status,
    percentile,
    weighted_market_price,
    _dedupe_key,
    _is_fresh,
)


class PricingAnalyticsServiceTests(unittest.TestCase):
    def test_complete_market_analytics(self) -> None:
        competitor_a = uuid4()
        competitor_b = uuid4()
        competitor_c = uuid4()
        snapshots = [
            _snapshot(competitor_a, "100.00", "IN_STOCK"),
            _snapshot(competitor_b, "200.00", "OUT_OF_STOCK"),
            _snapshot(competitor_c, "300.00", "IN_STOCK"),
        ]
        rankings = {
            competitor_a: _ranking(competitor_a, "100.00"),
            competitor_b: _ranking(competitor_b, "50.00"),
            competitor_c: _ranking(competitor_c, "25.00"),
        }

        stats = calculate_market_stats(snapshots=snapshots, rankings=rankings, seller_price=Decimal("250.00"))

        self.assertEqual(Decimal("100.00"), stats.min_price)
        self.assertEqual(Decimal("150.00"), stats.q1_price)
        self.assertEqual(Decimal("200.00"), stats.mean_price)
        self.assertEqual(Decimal("200.00"), stats.median_price)
        self.assertEqual(Decimal("250.00"), stats.q3_price)
        self.assertEqual(Decimal("300.00"), stats.max_price)
        self.assertEqual(Decimal("50.00"), stats.seller_price_difference_from_median)
        self.assertEqual(Decimal("66.67"), stats.seller_price_percentile)
        self.assertEqual(3, stats.competitor_count)
        self.assertEqual(2, stats.in_stock_competitor_count)
        self.assertEqual(Decimal("157.14"), stats.weighted_market_price)

    def test_no_competitors_does_not_fabricate_zero_prices(self) -> None:
        stats = calculate_market_stats(snapshots=[], rankings={}, seller_price=Decimal("250.00"))

        self.assertIsNone(stats.min_price)
        self.assertIsNone(stats.median_price)
        self.assertEqual(0, stats.competitor_count)

    def test_one_competitor_statistics(self) -> None:
        stats = calculate_market_stats(
            snapshots=[_snapshot(uuid4(), "175.00", "IN_STOCK")],
            rankings={},
            seller_price=Decimal("200.00"),
        )

        self.assertEqual(Decimal("175.00"), stats.min_price)
        self.assertEqual(Decimal("175.00"), stats.q1_price)
        self.assertEqual(Decimal("175.00"), stats.median_price)
        self.assertEqual(Decimal("175.00"), stats.q3_price)
        self.assertEqual(Decimal("100.00"), stats.seller_price_percentile)

    def test_invalid_prices_are_excluded(self) -> None:
        stats = calculate_market_stats(
            snapshots=[
                _snapshot(uuid4(), None, "IN_STOCK"),
                _snapshot(uuid4(), "0.00", "IN_STOCK"),
                _snapshot(uuid4(), "120.00", "IN_STOCK"),
            ],
            rankings={},
            seller_price=Decimal("100.00"),
        )

        self.assertEqual(1, stats.competitor_count)
        self.assertEqual(Decimal("120.00"), stats.median_price)

    def test_median_and_quartile_calculations(self) -> None:
        values = [Decimal("100"), Decimal("200"), Decimal("300"), Decimal("400")]

        self.assertEqual(Decimal("175.00"), percentile(values, Decimal("0.25")).quantize(Decimal("0.01")))
        self.assertEqual(Decimal("250.00"), percentile(values, Decimal("0.50")).quantize(Decimal("0.01")))
        self.assertEqual(Decimal("325.00"), percentile(values, Decimal("0.75")).quantize(Decimal("0.01")))

    def test_weighted_market_price_requires_ranking_data(self) -> None:
        snapshot = _snapshot(uuid4(), "100.00", "IN_STOCK")

        self.assertIsNone(weighted_market_price([snapshot], {}))

    def test_stale_competitor_data_status(self) -> None:
        status = determine_data_status(
            run_exists=True,
            run_fresh=False,
            has_competitor_prices=True,
            inventory_exists=True,
            inventory_fresh=True,
            velocity_exists=True,
            velocity_fresh=True,
            velocity_usable=True,
        )

        self.assertEqual(PricingAnalyticsDataStatus.STALE, status)

    def test_missing_inventory_limited_status(self) -> None:
        status = determine_data_status(
            run_exists=True,
            run_fresh=True,
            has_competitor_prices=True,
            inventory_exists=False,
            inventory_fresh=False,
            velocity_exists=True,
            velocity_fresh=True,
            velocity_usable=True,
        )

        self.assertEqual(PricingAnalyticsDataStatus.LIMITED, status)

    def test_missing_sales_velocity_demand_insufficient(self) -> None:
        demand = calculate_demand_score(
            daily_sales_rate=None,
            recent_net_sales=None,
            product_age_days=30,
            competitor_count=3,
            in_stock_competitor_count=2,
            out_of_stock_competitor_count=1,
            velocity_status=None,
            config=_config(),
        )

        self.assertIsNone(demand.score)
        self.assertEqual(PricingAnalyticsDataStatus.INSUFFICIENT, demand.status)

    def test_demand_score_boundaries(self) -> None:
        demand = calculate_demand_score(
            daily_sales_rate=Decimal("999.00"),
            recent_net_sales=999,
            product_age_days=365,
            competitor_count=2,
            in_stock_competitor_count=0,
            out_of_stock_competitor_count=2,
            velocity_status=SalesVelocityDataStatus.SUFFICIENT,
            config=_config(),
        )

        self.assertEqual(Decimal("100.00"), demand.score)

    def test_limited_velocity_reduces_demand_status(self) -> None:
        demand = calculate_demand_score(
            daily_sales_rate=Decimal("1.00"),
            recent_net_sales=5,
            product_age_days=5,
            competitor_count=0,
            in_stock_competitor_count=0,
            out_of_stock_competitor_count=0,
            velocity_status=SalesVelocityDataStatus.LIMITED,
            config=_config(),
        )

        self.assertEqual(PricingAnalyticsDataStatus.LIMITED, demand.status)

    def test_all_unknown_competitor_stock_is_neutral(self) -> None:
        demand = _demand(competitor_count=4, in_stock=0, out_of_stock=0)

        self.assertEqual("50.00", demand.components["competitor_availability_score"])
        self.assertEqual("unknown", demand.components["competitor_availability"])
        self.assertEqual(4, demand.components["competitor_stock_unknown_count"])

    def test_mixed_known_and_unknown_stock_uses_known_only(self) -> None:
        # 1 in stock, 1 out of stock, 2 unknown -> 1/2 out of stock, not 3/4.
        demand = _demand(competitor_count=4, in_stock=1, out_of_stock=1)

        self.assertEqual("50.00", demand.components["competitor_availability_score"])
        self.assertEqual("known", demand.components["competitor_availability"])

    def test_regression_unknown_stock_no_longer_inflates_demand(self) -> None:
        # v1 counted UNKNOWN as out of stock: 3 unknown + 1 in stock scored 75.
        demand = _demand(competitor_count=4, in_stock=1, out_of_stock=0)

        self.assertEqual("0.00", demand.components["competitor_availability_score"])

    def test_market_stats_counts_unknown_stock_separately(self) -> None:
        stats = calculate_market_stats(
            snapshots=[
                _snapshot(uuid4(), "100.00", "IN_STOCK"),
                _snapshot(uuid4(), "110.00", "OUT_OF_STOCK"),
                _snapshot(uuid4(), "120.00", "UNKNOWN"),
            ],
            rankings={},
            seller_price=Decimal("100.00"),
        )

        self.assertEqual(1, stats.in_stock_competitor_count)
        self.assertEqual(1, stats.out_of_stock_competitor_count)

    def test_confidence_calculation(self) -> None:
        confidence = calculate_confidence(
            data_status=PricingAnalyticsDataStatus.SUFFICIENT,
            demand_confidence=Decimal("85.00"),
            run_fresh=True,
            inventory_fresh=True,
            velocity_fresh=True,
            competitor_count=7,
        )

        self.assertEqual(Decimal("92.50"), confidence)

    def test_idempotent_retry_uses_same_dedupe_key(self) -> None:
        seller_id = uuid4()
        product_id = uuid4()
        sources = [uuid4(), uuid4(), uuid4(), uuid4()]

        first = _dedupe_key(
            seller_id=seller_id,
            product_id=product_id,
            calculation_version="v1",
            source_ids=sources,
            current_price=Decimal("500.00"),
            unit_cost=Decimal("300.00"),
        )
        second = _dedupe_key(
            seller_id=seller_id,
            product_id=product_id,
            calculation_version="v1",
            source_ids=sources,
            current_price=Decimal("500.00"),
            unit_cost=Decimal("300.00"),
        )

        self.assertEqual(first, second)

    def test_formula_versioning_changes_dedupe_key(self) -> None:
        seller_id = uuid4()
        product_id = uuid4()

        first = _dedupe_key(
            seller_id=seller_id,
            product_id=product_id,
            calculation_version="v1",
            source_ids=[],
            current_price=Decimal("500.00"),
            unit_cost=Decimal("300.00"),
        )
        second = _dedupe_key(
            seller_id=seller_id,
            product_id=product_id,
            calculation_version="v2",
            source_ids=[],
            current_price=Decimal("500.00"),
            unit_cost=Decimal("300.00"),
        )

        self.assertNotEqual(first, second)

    def test_freshness_boundary(self) -> None:
        now = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)

        self.assertTrue(_is_fresh(now - timedelta(hours=24), now, timedelta(hours=24)))
        self.assertFalse(_is_fresh(now - timedelta(hours=25), now, timedelta(hours=24)))

    def test_weight_validation(self) -> None:
        with self.assertRaisesRegex(ValueError, "must total 100"):
            PricingAnalyticsConfig(
                max_competitor_data_age=timedelta(hours=24),
                max_inventory_data_age=timedelta(hours=48),
                max_velocity_data_age=timedelta(hours=48),
                demand_velocity_weight=Decimal("50"),
                demand_recent_sales_weight=Decimal("25"),
                demand_competitor_availability_weight=Decimal("15"),
                demand_product_maturity_weight=Decimal("15"),
                demand_velocity_reference_units_per_day=Decimal("10"),
                demand_recent_sales_reference_units=Decimal("100"),
                calculation_version="v1",
            ).validate()


def _snapshot(competitor_id, price: str | None, stock_status: str) -> CompetitorSnapshot:
    return CompetitorSnapshot(
        id=uuid4(),
        scrape_run_id=uuid4(),
        competitor_id=competitor_id,
        product_id=uuid4(),
        price=Decimal(price) if price is not None else None,
        stock_status=stock_status,
        captured_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )


def _ranking(competitor_id, total_score: str) -> CompetitorRanking:
    return CompetitorRanking(
        id=uuid4(),
        seller_id=uuid4(),
        product_id=uuid4(),
        competitor_id=competitor_id,
        scrape_run_id=uuid4(),
        price_score=Decimal("0"),
        rating_score=Decimal("0"),
        review_score=Decimal("0"),
        availability_score=Decimal("0"),
        total_score=Decimal(total_score),
        market_rank=1,
        formula_version="v1",
        calculated_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )


def _config() -> PricingAnalyticsConfig:
    return PricingAnalyticsConfig(
        max_competitor_data_age=timedelta(hours=24),
        max_inventory_data_age=timedelta(hours=48),
        max_velocity_data_age=timedelta(hours=48),
        demand_velocity_weight=Decimal("45"),
        demand_recent_sales_weight=Decimal("25"),
        demand_competitor_availability_weight=Decimal("15"),
        demand_product_maturity_weight=Decimal("15"),
        demand_velocity_reference_units_per_day=Decimal("10"),
        demand_recent_sales_reference_units=Decimal("100"),
        calculation_version="v1",
    )


if __name__ == "__main__":
    unittest.main()


def _demand(*, competitor_count: int, in_stock: int, out_of_stock: int):
    return calculate_demand_score(
        daily_sales_rate=Decimal("1.00"),
        recent_net_sales=10,
        product_age_days=30,
        competitor_count=competitor_count,
        in_stock_competitor_count=in_stock,
        out_of_stock_competitor_count=out_of_stock,
        velocity_status=SalesVelocityDataStatus.SUFFICIENT,
        config=_config(),
    )
