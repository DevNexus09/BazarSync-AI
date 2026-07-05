from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from uuid import uuid4

from app.core.config import settings
from app.models.dead_stock_assessment import (
    DeadStockClassification,
    DeadStockDataStatus,
    DeadStockInventoryAgeState,
    DeadStockNoSalesState,
    DeadStockRiskLevel,
    DeadStockVisibilityStatus,
)
from app.models.inventory_aging import InventoryAgeSource
from app.models.sales_velocity import SalesVelocityDataStatus
from app.services.dead_stock_service import DeadStockService


class FakeDeadStockRepository:
    def __init__(self, *, fail_product_ids=None) -> None:
        self.products = []
        self.aging_by_product = {}
        self.velocity_by_product = {}
        self.sales_by_product = {}
        self.visibility_by_product = {}
        self.rows = {}
        self.fail_product_ids = set(fail_product_ids or [])

    def iter_product_batches(self, *, batch_size, seller_id=None, product_id=None):
        filtered = [
            row
            for row in self.products
            if (seller_id is None or row[0].seller_id == seller_id)
            and (product_id is None or row[0].id == product_id)
        ]
        for index in range(0, len(filtered), batch_size):
            yield filtered[index : index + batch_size]

    def latest_aging_for_products(self, *, seller_id, product_ids, as_of_date):
        return {
            product_id: row
            for product_id, row in self.aging_by_product.items()
            if product_id in product_ids and row.seller_id == seller_id and row.as_of_date <= as_of_date
        }

    def latest_velocity_for_products(self, *, seller_id, product_ids, as_of_date):
        return {
            product_id: row
            for product_id, row in self.velocity_by_product.items()
            if product_id in product_ids and row.seller_id == seller_id and row.as_of_date <= as_of_date
        }

    def sales_summaries_for_products(self, *, seller_id, product_ids):
        if self.sales_by_product is None:
            return None
        return {
            product_id: row
            for product_id, row in self.sales_by_product.items()
            if product_id in product_ids
        }

    def visibility_for_products(self, *, seller_id, product_ids, as_of_date):
        return {
            product_id: row
            for product_id, row in self.visibility_by_product.items()
            if product_id in product_ids
        }

    def add_idempotent(self, assessment):
        if assessment.product_id in self.fail_product_ids:
            raise RuntimeError("simulated failure")
        key = (assessment.product_id, assessment.as_of_date, assessment.calculation_version)
        existing = self.rows.get(key)
        if existing:
            return existing, False
        self.rows[key] = assessment
        return assessment, True

    def latest(self, *, seller_id, product_id, calculation_version):
        rows = [
            row
            for row in self.rows.values()
            if row.seller_id == seller_id
            and row.product_id == product_id
            and (calculation_version is None or row.calculation_version == calculation_version)
        ]
        rows.sort(key=lambda row: row.as_of_date, reverse=True)
        return rows[0] if rows else None

    def history(self, *, seller_id, product_id, from_date, to_date, calculation_version, order, limit, offset):
        rows = [
            row
            for row in self.rows.values()
            if row.seller_id == seller_id
            and row.product_id == product_id
            and (from_date is None or row.as_of_date >= from_date)
            and (to_date is None or row.as_of_date <= to_date)
            and (calculation_version is None or row.calculation_version == calculation_version)
        ]
        rows.sort(key=lambda row: row.as_of_date, reverse=order == "desc")
        return rows[offset : offset + limit], len(rows)

    def list_assessments(self, **kwargs):
        seller_id = kwargs["seller_id"]
        rows = [row for row in self.rows.values() if row.seller_id == seller_id]
        classification = kwargs.get("classification")
        if classification:
            rows = [row for row in rows if row.classification == classification]
        return rows[kwargs["offset"] : kwargs["offset"] + kwargs["limit"]], len(rows)


def seller(seller_id=None, timezone_name=None):
    return SimpleNamespace(id=seller_id or uuid4(), timezone=timezone_name)


def product(owner, *, stock=10, product_id=None, created_at=None, category="general"):
    return SimpleNamespace(
        id=product_id or uuid4(),
        seller_id=owner.id,
        seller=owner,
        stock_quantity=stock,
        category=category,
        created_at=created_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def aging(owner, item, *, age_days, eligible=10, estimated=False, source=InventoryAgeSource.INVENTORY_LOT):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner.id,
        product_id=item.id,
        inventory_snapshot_id=uuid4(),
        as_of_date=date(2026, 6, 30),
        eligible_unsold_quantity=eligible,
        oldest_age_days=age_days,
        is_estimated=estimated,
        age_source=source,
    )


def velocity(owner, item, *, rate="1.0000", status=SalesVelocityDataStatus.SUFFICIENT):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner.id,
        product_id=item.id,
        as_of_date=date(2026, 6, 30),
        daily_sales_rate=Decimal(rate),
        data_status=status,
    )


def sales_summary(*, last_sale_days_ago=None, records=1, valid=1):
    last_sale_at = None
    if last_sale_days_ago is not None:
        last_sale_at = datetime(2026, 6, 30, 8, tzinfo=timezone.utc) - timedelta(days=last_sale_days_ago)
    return {
        "sales_record_count": records,
        "valid_positive_sale_count": valid,
        "last_valid_sale_at": last_sale_at,
    }


class DeadStockServiceTests(unittest.TestCase):
    def setUp(self):
        self._original = {
            "dead_stock_no_sales_threshold_days": settings.dead_stock_no_sales_threshold_days,
            "dead_stock_inventory_age_threshold_days": settings.dead_stock_inventory_age_threshold_days,
            "dead_stock_product_age_grace_period_days": settings.dead_stock_product_age_grace_period_days,
            "dead_stock_slow_velocity_units_per_day": settings.dead_stock_slow_velocity_units_per_day,
            "dead_stock_strong_velocity_units_per_day": settings.dead_stock_strong_velocity_units_per_day,
            "dead_stock_excess_coverage_days": settings.dead_stock_excess_coverage_days,
            "dead_stock_low_visibility_threshold": settings.dead_stock_low_visibility_threshold,
            "dead_stock_inventory_age_weight": settings.dead_stock_inventory_age_weight,
            "dead_stock_no_sales_weight": settings.dead_stock_no_sales_weight,
            "dead_stock_sales_velocity_weight": settings.dead_stock_sales_velocity_weight,
            "dead_stock_excess_coverage_weight": settings.dead_stock_excess_coverage_weight,
            "dead_stock_visibility_weight": settings.dead_stock_visibility_weight,
        }
        settings.dead_stock_no_sales_threshold_days = 45
        settings.dead_stock_inventory_age_threshold_days = 60
        settings.dead_stock_product_age_grace_period_days = 30
        settings.dead_stock_slow_velocity_units_per_day = 0.25
        settings.dead_stock_strong_velocity_units_per_day = 1.0
        settings.dead_stock_excess_coverage_days = 90
        settings.dead_stock_low_visibility_threshold = 35
        settings.dead_stock_inventory_age_weight = 30
        settings.dead_stock_no_sales_weight = 30
        settings.dead_stock_sales_velocity_weight = 15
        settings.dead_stock_excess_coverage_weight = 15
        settings.dead_stock_visibility_weight = 10

    def tearDown(self):
        for key, value in self._original.items():
            setattr(settings, key, value)

    def assess(self, *, item=None, owner=None, age_days=61, eligible=10, sales=None, vel=None, visibility=None, estimated=False):
        owner = owner or seller()
        item = item or product(owner)
        service = DeadStockService(repository=FakeDeadStockRepository())
        return service.build_assessment(
            product=item,
            seller=owner,
            inventory_aging=aging(owner, item, age_days=age_days, eligible=eligible, estimated=estimated),
            sales_velocity=vel if vel is not None else velocity(owner, item, rate="1.0000"),
            sales_summary=sales if sales is not None else sales_summary(last_sale_days_ago=10),
            visibility=visibility,
            as_of_date=date(2026, 6, 30),
            assessed_at=datetime(2026, 6, 30, 9, tzinfo=timezone.utc),
        )

    def test_no_sales_for_more_than_threshold(self):
        assessment = self.assess(age_days=30, sales=sales_summary(last_sale_days_ago=46))

        self.assertEqual(DeadStockNoSalesState.NO_SALES_WITHIN_THRESHOLD, assessment.no_sales_state)
        self.assertEqual(DeadStockClassification.AT_RISK, assessment.classification)

    def test_inventory_age_above_threshold(self):
        assessment = self.assess(age_days=61, sales=sales_summary(last_sale_days_ago=10))

        self.assertEqual(DeadStockInventoryAgeState.AGE_THRESHOLD_EXCEEDED, assessment.inventory_age_state)
        self.assertEqual(DeadStockClassification.AT_RISK, assessment.classification)

    def test_both_major_rules_trigger_dead_stock(self):
        assessment = self.assess(age_days=90, sales=sales_summary(last_sale_days_ago=67))

        self.assertEqual(DeadStockClassification.DEAD_STOCK, assessment.classification)
        self.assertIn("NO_VALID_SALES", assessment.triggered_rules)
        self.assertIn("INVENTORY_AGE_THRESHOLD", assessment.triggered_rules)

    def test_only_no_sales_rule_triggered(self):
        assessment = self.assess(age_days=20, sales=sales_summary(last_sale_days_ago=67))

        self.assertEqual(DeadStockClassification.AT_RISK, assessment.classification)
        self.assertIn("NO_VALID_SALES", assessment.triggered_rules)
        self.assertNotIn("INVENTORY_AGE_THRESHOLD", assessment.triggered_rules)

    def test_only_age_rule_triggered(self):
        assessment = self.assess(age_days=90, sales=sales_summary(last_sale_days_ago=5))

        self.assertEqual(DeadStockClassification.AT_RISK, assessment.classification)
        self.assertIn("INVENTORY_AGE_THRESHOLD", assessment.triggered_rules)
        self.assertNotIn("NO_VALID_SALES", assessment.triggered_rules)

    def test_low_visibility_with_reliable_data(self):
        assessment = self.assess(
            age_days=50,
            sales=sales_summary(last_sale_days_ago=20),
            visibility={"score": Decimal("20.00")},
        )

        self.assertEqual(DeadStockVisibilityStatus.LOW_VISIBILITY, assessment.visibility_status)
        self.assertIn("LOW_VISIBILITY", assessment.triggered_rules)

    def test_missing_visibility_data_is_not_low_visibility(self):
        assessment = self.assess(age_days=30, sales=sales_summary(last_sale_days_ago=5), visibility=None)

        self.assertEqual(DeadStockVisibilityStatus.VISIBILITY_DATA_UNAVAILABLE, assessment.visibility_status)
        self.assertNotIn("LOW_VISIBILITY", assessment.triggered_rules)

    def test_new_product_grace_period(self):
        owner = seller()
        item = product(owner, created_at=datetime(2026, 6, 15, tzinfo=timezone.utc))
        assessment = self.assess(item=item, owner=owner, age_days=10, sales=sales_summary(records=0, valid=0))

        self.assertEqual(DeadStockNoSalesState.PRODUCT_TOO_NEW, assessment.no_sales_state)
        self.assertEqual(DeadStockClassification.HEALTHY, assessment.classification)

    def test_never_sold_product(self):
        assessment = self.assess(age_days=90, sales=sales_summary(records=0, valid=0))

        self.assertEqual(DeadStockNoSalesState.NEVER_SOLD, assessment.no_sales_state)
        self.assertEqual(DeadStockClassification.DEAD_STOCK, assessment.classification)

    def test_missing_sales_data(self):
        owner = seller()
        item = product(owner)
        service = DeadStockService(repository=FakeDeadStockRepository())
        assessment = service.build_assessment(
            product=item,
            seller=owner,
            inventory_aging=aging(owner, item, age_days=90),
            sales_velocity=velocity(owner, item),
            sales_summary=None,
            visibility=None,
            as_of_date=date(2026, 6, 30),
            assessed_at=datetime(2026, 6, 30, 9, tzinfo=timezone.utc),
        )

        self.assertEqual(DeadStockNoSalesState.SALES_DATA_INSUFFICIENT, assessment.no_sales_state)
        self.assertEqual(DeadStockClassification.INSUFFICIENT_DATA, assessment.classification)

    def test_estimated_inventory_age(self):
        assessment = self.assess(age_days=90, sales=sales_summary(last_sale_days_ago=67), estimated=True)

        self.assertTrue(assessment.inventory_age_is_estimated)
        self.assertEqual(DeadStockInventoryAgeState.AGE_ESTIMATED, assessment.inventory_age_state)
        self.assertEqual(DeadStockDataStatus.LIMITED, assessment.data_status)

    def test_no_eligible_stock(self):
        assessment = self.assess(age_days=90, eligible=0, sales=sales_summary(last_sale_days_ago=67))

        self.assertEqual(DeadStockClassification.INSUFFICIENT_DATA, assessment.classification)
        self.assertEqual(0, assessment.eligible_quantity)

    def test_threshold_boundary_exactly_45_days(self):
        assessment = self.assess(age_days=30, sales=sales_summary(last_sale_days_ago=45))

        self.assertEqual(DeadStockNoSalesState.NO_SALES_WITHIN_THRESHOLD, assessment.no_sales_state)

    def test_threshold_boundary_exactly_60_days(self):
        assessment = self.assess(age_days=60, sales=sales_summary(last_sale_days_ago=10))

        self.assertEqual(DeadStockInventoryAgeState.AGE_THRESHOLD_EXCEEDED, assessment.inventory_age_state)

    def test_configurable_thresholds(self):
        settings.dead_stock_no_sales_threshold_days = 30
        settings.dead_stock_inventory_age_threshold_days = 40
        assessment = self.assess(age_days=40, sales=sales_summary(last_sale_days_ago=30))

        self.assertEqual(DeadStockClassification.DEAD_STOCK, assessment.classification)
        self.assertEqual(30, assessment.rule_results["no_sales_threshold_days"])
        self.assertEqual(40, assessment.rule_results["inventory_age_threshold_days"])

    def test_duplicate_task_retry_and_historical_preservation(self):
        owner = seller()
        item = product(owner)
        repo = FakeDeadStockRepository()
        repo.products = [(item, owner)]
        repo.aging_by_product[item.id] = aging(owner, item, age_days=90)
        repo.velocity_by_product[item.id] = velocity(owner, item)
        repo.sales_by_product[item.id] = sales_summary(last_sale_days_ago=67)
        service = DeadStockService(repository=repo)

        first = service.assess_batch(batch_size=1, as_of_date=date(2026, 6, 30))
        repeated = service.assess_batch(batch_size=1, as_of_date=date(2026, 6, 30))

        self.assertEqual(1, first.created_count)
        self.assertEqual(0, repeated.created_count)
        self.assertEqual(1, repeated.skipped_count)
        self.assertEqual(1, len(repo.rows))

    def test_seller_isolation(self):
        first_seller = seller()
        second_seller = seller()
        item = product(first_seller)
        repo = FakeDeadStockRepository()
        service = DeadStockService(repository=repo)
        service.assess_for_product(
            product=item,
            seller=first_seller,
            inventory_aging=aging(first_seller, item, age_days=90),
            sales_velocity=velocity(first_seller, item),
            sales_summary=sales_summary(last_sale_days_ago=67),
            visibility=None,
            as_of_date=date(2026, 6, 30),
        )

        rows, total = service.assessment_history(
            seller_id=second_seller.id,
            product_id=item.id,
            from_date=None,
            to_date=None,
            calculation_version=None,
            order="desc",
            limit=20,
            offset=0,
        )

        self.assertEqual(0, total)
        self.assertEqual([], rows)

    def test_risk_score_boundaries(self):
        low = self.assess(age_days=20, sales=sales_summary(last_sale_days_ago=2), visibility={"score": Decimal("95.00")})
        medium = self.assess(age_days=90, sales=sales_summary(last_sale_days_ago=5), visibility={"score": Decimal("90.00")})
        high = self.assess(age_days=90, sales=sales_summary(last_sale_days_ago=67), visibility={"score": Decimal("90.00")})
        critical_owner = seller()
        critical_item = product(critical_owner)
        critical = self.assess(
            item=critical_item,
            owner=critical_owner,
            age_days=120,
            sales=sales_summary(last_sale_days_ago=90),
            vel=velocity(critical_owner, critical_item, rate="0.0000"),
            visibility={"score": Decimal("0.00")},
        )

        self.assertEqual(DeadStockRiskLevel.LOW, low.risk_level)
        self.assertEqual(DeadStockRiskLevel.MEDIUM, medium.risk_level)
        self.assertEqual(DeadStockRiskLevel.HIGH, high.risk_level)
        self.assertEqual(DeadStockRiskLevel.CRITICAL, critical.risk_level)

    def test_missing_visibility_is_unavailable_and_weights_renormalize(self):
        assessment = self.assess(age_days=30, sales=sales_summary(last_sale_days_ago=5), visibility=None)

        self.assertIsNone(assessment.rule_results["risk_component_scores"]["visibility_weakness"])
        self.assertEqual("UNAVAILABLE", assessment.rule_results["risk_component_statuses"]["visibility_weakness"])
        self.assertEqual("0.00", assessment.rule_results["risk_effective_weights"]["visibility_weakness"])
        self.assertLess(assessment.confidence_score, Decimal("85.00"))

    def test_zero_velocity_is_high_velocity_weakness_without_dividing_coverage(self):
        owner = seller()
        item = product(owner)
        assessment = self.assess(
            item=item,
            owner=owner,
            age_days=30,
            sales=sales_summary(last_sale_days_ago=5),
            vel=velocity(owner, item, rate="0.0000"),
            visibility={"score": Decimal("90.00")},
        )

        self.assertEqual("100.00", assessment.rule_results["risk_component_scores"]["sales_velocity_weakness"])
        self.assertIsNone(assessment.rule_results["inventory_coverage_days"])
        self.assertEqual("UNAVAILABLE", assessment.rule_results["risk_component_statuses"]["excess_coverage"])

    def test_missing_velocity_is_unavailable_not_zero(self):
        owner = seller()
        item = product(owner)
        service = DeadStockService(repository=FakeDeadStockRepository())
        assessment = service.build_assessment(
            product=item,
            seller=owner,
            inventory_aging=aging(owner, item, age_days=30),
            sales_velocity=None,
            sales_summary=sales_summary(last_sale_days_ago=5),
            visibility={"score": Decimal("90.00")},
            as_of_date=date(2026, 6, 30),
            assessed_at=datetime(2026, 6, 30, 9, tzinfo=timezone.utc),
        )

        self.assertIsNone(assessment.rule_results["risk_component_scores"]["sales_velocity_weakness"])
        self.assertEqual("UNAVAILABLE", assessment.rule_results["risk_component_statuses"]["sales_velocity_weakness"])
        self.assertLess(assessment.confidence_score, Decimal("85.00"))

    def test_excessive_inventory_coverage_component(self):
        owner = seller()
        item = product(owner)
        assessment = self.assess(
            item=item,
            owner=owner,
            age_days=30,
            eligible=100,
            sales=sales_summary(last_sale_days_ago=5),
            vel=velocity(owner, item, rate="1.0000"),
            visibility={"score": Decimal("90.00")},
        )

        self.assertEqual("100.00", assessment.rule_results["inventory_coverage_days"])
        self.assertGreater(Decimal(assessment.rule_results["risk_component_scores"]["excess_coverage"]), Decimal("75"))
        self.assertIn("EXCESSIVE_INVENTORY_COVERAGE", assessment.triggered_rules)

    def test_estimated_aging_reduces_data_status_and_confidence_but_scores_age(self):
        assessment = self.assess(age_days=90, sales=sales_summary(last_sale_days_ago=5), estimated=True, visibility={"score": Decimal("90.00")})

        self.assertEqual(DeadStockDataStatus.LIMITED, assessment.data_status)
        self.assertLess(assessment.confidence_score, Decimal("85.00"))
        self.assertEqual("AVAILABLE", assessment.rule_results["risk_component_statuses"]["inventory_age_severity"])

    def test_insufficient_data_still_returns_explainable_available_score_parts(self):
        owner = seller()
        item = product(owner)
        service = DeadStockService(repository=FakeDeadStockRepository())
        assessment = service.build_assessment(
            product=item,
            seller=owner,
            inventory_aging=None,
            sales_velocity=None,
            sales_summary=None,
            visibility=None,
            as_of_date=date(2026, 6, 30),
            assessed_at=datetime(2026, 6, 30, 9, tzinfo=timezone.utc),
        )

        self.assertEqual(DeadStockClassification.INSUFFICIENT_DATA, assessment.classification)
        self.assertEqual(Decimal("0.00"), assessment.risk_score)
        self.assertEqual(DeadStockRiskLevel.LOW, assessment.risk_level)
        self.assertTrue(all(status == "UNAVAILABLE" for status in assessment.rule_results["risk_component_statuses"].values()))

    def test_weight_validation_rejects_invalid_weights(self):
        settings.dead_stock_inventory_age_weight = -1

        with self.assertRaises(ValueError):
            self.assess(age_days=30, sales=sales_summary(last_sale_days_ago=5))

    def test_reweighted_score_uses_only_available_components(self):
        with_visibility = self.assess(age_days=30, sales=sales_summary(last_sale_days_ago=5), visibility={"score": Decimal("0.00")})
        without_visibility = self.assess(age_days=30, sales=sales_summary(last_sale_days_ago=5), visibility=None)

        self.assertGreater(with_visibility.risk_score, without_visibility.risk_score)
        self.assertEqual("16.67", without_visibility.rule_results["risk_effective_weights"]["sales_velocity_weakness"])

    def test_configurable_thresholds_change_component_scores(self):
        baseline = self.assess(age_days=40, sales=sales_summary(last_sale_days_ago=5), visibility={"score": Decimal("90.00")})
        settings.dead_stock_inventory_age_threshold_days = 40
        shifted = self.assess(age_days=40, sales=sales_summary(last_sale_days_ago=5), visibility={"score": Decimal("90.00")})

        self.assertEqual("0.00", baseline.rule_results["risk_component_scores"]["inventory_age_severity"])
        self.assertEqual("75.00", shifted.rule_results["risk_component_scores"]["inventory_age_severity"])

    def test_formula_versioning_and_deterministic_calculation(self):
        first = self.assess(age_days=60, sales=sales_summary(last_sale_days_ago=45), visibility={"score": Decimal("90.00")})
        second = self.assess(age_days=60, sales=sales_summary(last_sale_days_ago=45), visibility={"score": Decimal("90.00")})

        self.assertEqual(first.risk_score, second.risk_score)
        self.assertEqual("v1", first.calculation_version)
        self.assertEqual("weighted_average_available_components_v1", first.rule_results["risk_formula"])


if __name__ == "__main__":
    unittest.main()
