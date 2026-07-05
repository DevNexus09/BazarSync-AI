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
from app.models.dead_stock_capital_recovery import CapitalRecoveryEstimateStatus
from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryAction
from app.models.inventory_aging import InventoryAgeSource
from app.models.sales_velocity import SalesVelocityDataStatus
from app.services.dead_stock_capital_recovery_service import DeadStockCapitalRecoveryService, RecoverySimulationInput
from app.services.dead_stock_recovery_service import DeadStockRecoveryService
from app.services.dead_stock_service import DeadStockService
from app.services.inventory_aging_service import InventoryAgingService, InventoryLotState

AS_OF = date(2026, 7, 3)
NOW = datetime(2026, 7, 3, 9, tzinfo=timezone.utc)


class Phase9AcceptanceReadinessTests(unittest.TestCase):
    def setUp(self):
        self._original = {
            "dead_stock_no_sales_threshold_days": settings.dead_stock_no_sales_threshold_days,
            "dead_stock_inventory_age_threshold_days": settings.dead_stock_inventory_age_threshold_days,
            "dead_stock_product_age_grace_period_days": settings.dead_stock_product_age_grace_period_days,
            "dead_stock_recovery_discount_rates": settings.dead_stock_recovery_discount_rates,
            "dead_stock_capital_recovery_heuristic_low_sell_through_rate": settings.dead_stock_capital_recovery_heuristic_low_sell_through_rate,
            "dead_stock_capital_recovery_heuristic_central_sell_through_rate": settings.dead_stock_capital_recovery_heuristic_central_sell_through_rate,
            "dead_stock_capital_recovery_heuristic_high_sell_through_rate": settings.dead_stock_capital_recovery_heuristic_high_sell_through_rate,
        }
        settings.dead_stock_no_sales_threshold_days = 45
        settings.dead_stock_inventory_age_threshold_days = 60
        settings.dead_stock_product_age_grace_period_days = 30
        settings.dead_stock_recovery_discount_rates = [0.05, 0.10, 0.15, 0.20]
        settings.dead_stock_capital_recovery_heuristic_low_sell_through_rate = 0.25
        settings.dead_stock_capital_recovery_heuristic_central_sell_through_rate = 0.40
        settings.dead_stock_capital_recovery_heuristic_high_sell_through_rate = 0.55

    def tearDown(self):
        for key, value in self._original.items():
            setattr(settings, key, value)

    def test_dove_body_lotion_acceptance_scenario(self):
        owner = seller()
        item = product(
            owner,
            title="Dove Body Lotion",
            stock=120,
            cost=Decimal("200.00"),
            price=Decimal("350.00"),
            created_at=NOW - timedelta(days=120),
        )
        aging = exact_aging(owner, item, days_old=92, quantity=120)

        self.assertEqual(92, aging.oldest_age_days)
        self.assertEqual(Decimal("92.0000"), aging.weighted_average_age_days)
        self.assertEqual(InventoryAgeSource.PURCHASE_RECEIPT, aging.age_source)

        assessment = dead_stock_assessment(
            owner,
            item,
            aging=aging,
            sales=sales_summary(last_sale_days_ago=67, records=4, valid=4),
            velocity=velocity(owner, item, rate="0.0000"),
            visibility=None,
        )

        self.assertEqual(DeadStockNoSalesState.NO_SALES_WITHIN_THRESHOLD, assessment.no_sales_state)
        self.assertEqual(DeadStockInventoryAgeState.AGE_THRESHOLD_EXCEEDED, assessment.inventory_age_state)
        self.assertEqual(DeadStockVisibilityStatus.VISIBILITY_DATA_UNAVAILABLE, assessment.visibility_status)
        self.assertEqual(DeadStockClassification.DEAD_STOCK, assessment.classification)
        self.assertIn(assessment.risk_level, {DeadStockRiskLevel.HIGH, DeadStockRiskLevel.CRITICAL})
        self.assertNotIn("LOW_VISIBILITY", assessment.triggered_rules)

        recovery_repo = RecoveryRepo(owner, item, assessment)
        guard = FixtureMarginGuard(max_discount=Decimal("0.15"), fee=Decimal("20.00"))
        recommendation, _ = DeadStockRecoveryService(
            repository=recovery_repo,
            margin_guard_factory=lambda _db: guard,
        ).generate_for_product(seller_id=owner.id, product_id=item.id)

        self.assertGreaterEqual(len(guard.calls), 4)
        self.assertIn(recommendation.primary_action, {DeadStockRecoveryAction.DISCOUNT, DeadStockRecoveryAction.FLASH_SALE, DeadStockRecoveryAction.BUNDLE})
        self.assertIn("SEO_FIX", [row["action"] for row in recommendation.rejected_actions])
        self.assertIn("EXCEEDS_MAXIMUM_DECREASE", {reason for row in recommendation.rejected_actions for reason in row["reasons"]})
        self.assertTrue(recommendation.evidence["no_automatic_execution"])

        capital_repo = CapitalRepo(owner, item, assessment, recommendation)
        estimate = DeadStockCapitalRecoveryService(
            repository=capital_repo,
            margin_guard_factory=lambda _db: FixtureMarginGuard(fee=Decimal("20.00")),
        ).estimate_for_product(seller_id=owner.id, product_id=item.id, calculated_at=NOW)

        self.assertEqual(Decimal("24000.00"), estimate.locked_capital)
        self.assertIsNotNone(estimate.gross_recovered_cash_low)
        self.assertIsNotNone(estimate.gross_recovered_cash)
        self.assertIsNotNone(estimate.gross_recovered_cash_high)
        self.assertGreater(estimate.gross_recovered_cash_high, estimate.gross_recovered_cash_low)
        self.assertEqual("BDT", estimate.evidence["currency"])

    def test_new_product_grace_period_prevents_dead_stock(self):
        owner = seller()
        item = product(owner, stock=20, created_at=NOW - timedelta(days=10))
        assessment = dead_stock_assessment(
            owner,
            item,
            aging=exact_aging(owner, item, days_old=10, quantity=20),
            sales=sales_summary(last_sale_days_ago=None, records=0, valid=0),
            velocity=velocity(owner, item, rate="0.0000"),
            visibility=None,
        )

        self.assertEqual(DeadStockNoSalesState.PRODUCT_TOO_NEW, assessment.no_sales_state)
        self.assertNotEqual(DeadStockClassification.DEAD_STOCK, assessment.classification)

    def test_old_inventory_with_recent_sales_is_not_automatic_dead_stock(self):
        owner = seller()
        item = product(owner, stock=120, created_at=NOW - timedelta(days=200))
        assessment = dead_stock_assessment(
            owner,
            item,
            aging=exact_aging(owner, item, days_old=100, quantity=120),
            sales=sales_summary(last_sale_days_ago=3, records=10, valid=10),
            velocity=velocity(owner, item, rate="0.5000"),
            visibility=None,
        )

        self.assertEqual(DeadStockNoSalesState.RECENT_SALE, assessment.no_sales_state)
        self.assertNotEqual(DeadStockClassification.DEAD_STOCK, assessment.classification)

    def test_missing_sales_data_does_not_claim_no_sales_threshold(self):
        owner = seller()
        item = product(owner, stock=20, created_at=NOW - timedelta(days=100))
        assessment = dead_stock_assessment(
            owner,
            item,
            aging=exact_aging(owner, item, days_old=80, quantity=20),
            sales=None,
            velocity=velocity(owner, item, rate="0.0000", status=SalesVelocityDataStatus.INSUFFICIENT),
            visibility=None,
        )

        self.assertEqual(DeadStockNoSalesState.SALES_DATA_INSUFFICIENT, assessment.no_sales_state)
        self.assertEqual(DeadStockClassification.INSUFFICIENT_DATA, assessment.classification)
        self.assertNotIn("NO_VALID_SALES", assessment.triggered_rules)

    def test_estimated_inventory_age_is_labelled_and_lowers_confidence(self):
        owner = seller()
        item = product(owner, stock=120, created_at=NOW - timedelta(days=120))
        exact = dead_stock_assessment(
            owner,
            item,
            aging=exact_aging(owner, item, days_old=92, quantity=120),
            sales=sales_summary(last_sale_days_ago=67),
            velocity=velocity(owner, item, rate="0.0000"),
            visibility=None,
        )
        estimated = dead_stock_assessment(
            owner,
            item,
            aging=estimated_aging(owner, item, days_old=92, quantity=120),
            sales=sales_summary(last_sale_days_ago=67),
            velocity=velocity(owner, item, rate="0.0000"),
            visibility=None,
        )

        self.assertTrue(estimated.inventory_age_is_estimated)
        self.assertIn("INVENTORY_AGE_ESTIMATED", estimated.triggered_rules)
        self.assertLess(estimated.confidence_score, exact.confidence_score)

    def test_missing_cost_allows_classification_but_not_locked_capital(self):
        owner = seller()
        item = product(owner, stock=120, cost=None, created_at=NOW - timedelta(days=120))
        assessment = dead_stock_assessment(
            owner,
            item,
            aging=exact_aging(owner, item, days_old=92, quantity=120),
            sales=sales_summary(last_sale_days_ago=67),
            velocity=velocity(owner, item, rate="0.0000"),
            visibility=None,
        )
        recommendation = SimpleNamespace(
            id=uuid4(),
            seller_id=owner.id,
            product_id=item.id,
            dead_stock_assessment_id=assessment.id,
            primary_action=DeadStockRecoveryAction.DISCOUNT,
            recommended_price=Decimal("300.00"),
            recommended_quantity=120,
            suggested_duration_days=7,
        )

        estimate = DeadStockCapitalRecoveryService(
            repository=CapitalRepo(owner, item, assessment, recommendation),
            margin_guard_factory=lambda _db: FixtureMarginGuard(),
        ).simulate_for_product(
            seller_id=owner.id,
            product_id=item.id,
            simulation=RecoverySimulationInput(action=DeadStockRecoveryAction.DISCOUNT),
            calculated_at=NOW,
        )

        self.assertEqual(DeadStockClassification.DEAD_STOCK, assessment.classification)
        self.assertIsNone(estimate.locked_capital)
        self.assertEqual("MISSING_COST_DATA", estimate.evidence["reason"])

    def test_missing_marketplace_fees_keep_locked_capital_but_block_recovery_estimate(self):
        owner = seller()
        item = product(owner, stock=120, cost=Decimal("200.00"), created_at=NOW - timedelta(days=120))
        assessment = SimpleNamespace(id=uuid4(), seller_id=owner.id, product_id=item.id, eligible_quantity=120)
        recommendation = SimpleNamespace(
            id=uuid4(),
            seller_id=owner.id,
            product_id=item.id,
            dead_stock_assessment_id=assessment.id,
            primary_action=DeadStockRecoveryAction.DISCOUNT,
            recommended_price=Decimal("300.00"),
            recommended_quantity=120,
            suggested_duration_days=7,
        )

        estimate = DeadStockCapitalRecoveryService(
            repository=CapitalRepo(owner, item, assessment, recommendation),
            margin_guard_factory=lambda _db: FixtureMarginGuard(allowed=False, reasons=["MISSING_FEE_DATA"]),
        ).simulate_for_product(
            seller_id=owner.id,
            product_id=item.id,
            simulation=RecoverySimulationInput(action=DeadStockRecoveryAction.DISCOUNT),
            calculated_at=NOW,
        )

        self.assertEqual(Decimal("24000.00"), estimate.locked_capital)
        self.assertEqual(CapitalRecoveryEstimateStatus.INSUFFICIENT_DATA, estimate.estimate_status)
        self.assertEqual("MISSING_FEE_DATA", estimate.evidence["reason"])
        self.assertIsNone(estimate.gross_recovered_cash)

    def test_zero_stock_is_not_active_dead_stock(self):
        owner = seller()
        item = product(owner, stock=0, created_at=NOW - timedelta(days=120))
        assessment = dead_stock_assessment(
            owner,
            item,
            aging=exact_aging(owner, item, days_old=92, quantity=0),
            sales=sales_summary(last_sale_days_ago=67),
            velocity=velocity(owner, item, rate="0.0000"),
            visibility=None,
        )

        self.assertEqual(0, assessment.eligible_quantity)
        self.assertNotEqual(DeadStockClassification.DEAD_STOCK, assessment.classification)


def seller():
    return SimpleNamespace(id=uuid4(), timezone="Asia/Dhaka")


def product(owner, *, title="Product", stock=20, cost=Decimal("200.00"), price=Decimal("350.00"), created_at=None):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner.id,
        seller=owner,
        title=title,
        stock_quantity=stock,
        cost_price=cost,
        selling_price=price,
        category="beauty",
        specifications={},
        created_at=created_at or NOW - timedelta(days=120),
    )


def exact_aging(owner, item, *, days_old: int, quantity: int):
    outcome = InventoryAgingService(repository=IdempotentAgingRepo()).calculate_for_product(
        product=item,
        seller=owner,
        as_of_date=AS_OF,
        calculated_at=NOW,
        lots=[
            InventoryLotState(
                received_date=AS_OF - timedelta(days=days_old),
                remaining_quantity=quantity,
                source=InventoryAgeSource.PURCHASE_RECEIPT,
            )
        ],
    )
    return outcome.snapshot


def estimated_aging(owner, item, *, days_old: int, quantity: int):
    del quantity
    outcome = InventoryAgingService(repository=IdempotentAgingRepo()).calculate_for_product(
        product=item,
        seller=owner,
        as_of_date=AS_OF,
        calculated_at=NOW,
        first_positive_snapshot=SimpleNamespace(
            id=uuid4(),
            seller_id=owner.id,
            product_id=item.id,
            snapshot_date=AS_OF - timedelta(days=days_old),
            captured_at=NOW,
            quantity_on_hand=item.stock_quantity,
            quantity_reserved=0,
            quantity_available=item.stock_quantity,
        ),
    )
    return outcome.snapshot


def dead_stock_assessment(owner, item, *, aging, sales, velocity, visibility):
    return DeadStockService(repository=IdempotentDeadStockRepo()).build_assessment(
        product=item,
        seller=owner,
        inventory_aging=aging,
        sales_velocity=velocity,
        sales_summary=sales,
        visibility=visibility,
        as_of_date=AS_OF,
        assessed_at=NOW,
    )


def velocity(owner, item, *, rate, status=SalesVelocityDataStatus.SUFFICIENT):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner.id,
        product_id=item.id,
        daily_sales_rate=Decimal(rate),
        data_status=status,
        as_of_date=AS_OF,
    )


def sales_summary(*, last_sale_days_ago=None, records=1, valid=1):
    return {
        "sales_record_count": records,
        "valid_positive_sale_count": valid,
        "last_valid_sale_at": None if last_sale_days_ago is None else NOW - timedelta(days=last_sale_days_ago),
    }


class IdempotentAgingRepo:
    def __init__(self):
        self.rows = {}

    def add_idempotent(self, snapshot):
        snapshot.id = uuid4()
        key = (snapshot.product_id, snapshot.as_of_date, snapshot.calculation_version)
        existing = self.rows.get(key)
        if existing:
            return existing, False
        self.rows[key] = snapshot
        return snapshot, True


class IdempotentDeadStockRepo:
    pass


class RecoveryRepo:
    def __init__(self, owner, item, assessment):
        self.owner = owner
        self.item = item
        self.assessment = assessment
        self.rows = {}

    def product(self, *, seller_id, product_id):
        return self.item if seller_id == self.owner.id and product_id == self.item.id else None

    def latest_assessment(self, *, seller_id, product_id):
        return self.assessment if seller_id == self.owner.id and product_id == self.item.id else None

    def latest_aging(self, **_kwargs):
        return None

    def latest_velocity(self, **_kwargs):
        return None

    def visibility_for_product(self, **_kwargs):
        return None

    def promotion_history_for_product(self, **_kwargs):
        return []

    def bundle_compatibility_for_product(self, **_kwargs):
        return []

    def companion_products(self, **_kwargs):
        return []

    def add_idempotent(self, recommendation):
        recommendation.id = uuid4()
        self.rows[recommendation.id] = recommendation
        return recommendation, True


class CapitalRepo:
    def __init__(self, owner, item, assessment, recommendation):
        self.owner = owner
        self.item = item
        self.assessment = assessment
        self.recommendation = recommendation
        self.rows = []

    def product(self, *, seller_id, product_id):
        return self.item if seller_id == self.owner.id and product_id == self.item.id else None

    def latest_assessment(self, *, seller_id, product_id):
        return self.assessment if seller_id == self.owner.id and product_id == self.item.id else None

    def latest_recovery_recommendation(self, *, seller_id, product_id):
        return self.recommendation if seller_id == self.owner.id and product_id == self.item.id else None

    def latest_demand_estimate(self, **_kwargs):
        return None

    def promotion_history_for_product(self, **_kwargs):
        return []

    def category_promotion_history(self, **_kwargs):
        return []

    def add(self, estimate):
        estimate.id = uuid4()
        self.rows.append(estimate)
        return estimate

    def latest_estimate(self, *, seller_id, product_id):
        rows = [row for row in self.rows if row.seller_id == seller_id and row.product_id == product_id]
        return rows[-1] if rows else None


class FixtureMarginGuard:
    def __init__(self, *, allowed=True, reasons=None, max_discount=None, fee=Decimal("15.00")):
        self.allowed = allowed
        self.reasons = reasons or []
        self.max_discount = max_discount
        self.fee = fee
        self.calls = []

    def validate_candidate(self, *, seller_id, product, candidate_price):
        self.calls.append(candidate_price)
        allowed = self.allowed
        reasons = list(self.reasons)
        if self.max_discount is not None:
            discount = (Decimal(str(product.selling_price)) - Decimal(str(candidate_price))) / Decimal(str(product.selling_price))
            if discount > self.max_discount:
                allowed = False
                reasons.append("EXCEEDS_MAXIMUM_DECREASE")
        return SimpleNamespace(
            is_allowed=allowed,
            rejection_reasons=[SimpleNamespace(value=reason) for reason in reasons],
            margin_rate=Decimal("0.25") if allowed else None,
            to_evidence=lambda: {
                "is_allowed": allowed,
                "rejection_reasons": reasons,
                "fee_breakdown": {
                    "percentage_commission_amount": "10.00",
                    "payment_fee_amount": "2.00",
                    "fixed_fees": "3.00",
                    "other_variable_cost": str(self.fee - Decimal("15.00")),
                    "total_fee_amount": str(self.fee),
                },
            },
        )


if __name__ == "__main__":
    unittest.main()
