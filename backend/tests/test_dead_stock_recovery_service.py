from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from uuid import uuid4

from app.core.config import settings
from app.models.dead_stock_assessment import DeadStockClassification, DeadStockRiskLevel
from app.models.dead_stock_recovery_recommendation import (
    DeadStockRecoveryAction,
    DeadStockRecoveryRecommendationStatus,
)
from app.services.dead_stock_recovery_service import DeadStockRecoveryService


class Reason:
    def __init__(self, value):
        self.value = value


class GuardResult:
    def __init__(self, *, allowed=True, reasons=None, margin=Decimal("0.25")):
        self.is_allowed = allowed
        self.rejection_reasons = [Reason(reason) for reason in (reasons or [])]
        self.margin_rate = margin

    def to_evidence(self):
        return {
            "is_allowed": self.is_allowed,
            "rejection_reasons": [reason.value for reason in self.rejection_reasons],
            "margin_rate": str(self.margin_rate),
        }


class FakeMarginGuard:
    def __init__(self, *, reject_all=None, max_discount=None, increment=None):
        self.reject_all = reject_all or []
        self.max_discount = max_discount
        self.increment = increment

    def validate_candidate(self, *, seller_id, product, candidate_price):
        del seller_id
        if self.reject_all:
            return GuardResult(allowed=False, reasons=self.reject_all)
        price = Decimal(str(candidate_price))
        current = Decimal(str(product.selling_price))
        discount = (current - price) / current
        if self.max_discount is not None and discount > Decimal(str(self.max_discount)):
            return GuardResult(allowed=False, reasons=["EXCEEDS_MAXIMUM_DECREASE"])
        if self.increment is not None and price.remainder_near(Decimal(str(self.increment))) != 0:
            return GuardResult(allowed=False, reasons=["INVALID_MARKETPLACE_INCREMENT"])
        return GuardResult(allowed=True)


class FakeRepo:
    def __init__(self):
        self.products = {}
        self.assessments = {}
        self.aging = {}
        self.velocity = {}
        self.visibility = {}
        self.promotions = {}
        self.bundle_data = {}
        self.companions = {}
        self.rows = {}

    def product(self, *, seller_id, product_id):
        item = self.products.get(product_id)
        return item if item and item.seller_id == seller_id else None

    def latest_assessment(self, *, seller_id, product_id):
        item = self.assessments.get(product_id)
        return item if item and item.seller_id == seller_id else None

    def latest_aging(self, *, seller_id, product_id, as_of_date):
        del seller_id, as_of_date
        return self.aging.get(product_id)

    def latest_velocity(self, *, seller_id, product_id, as_of_date):
        del seller_id, as_of_date
        return self.velocity.get(product_id)

    def visibility_for_product(self, *, seller_id, product_id, as_of_date):
        del seller_id, as_of_date
        return self.visibility.get(product_id)

    def promotion_history_for_product(self, *, seller_id, product_id):
        del seller_id
        return self.promotions.get(product_id, [])

    def bundle_compatibility_for_product(self, *, seller_id, product_id):
        del seller_id
        return self.bundle_data.get(product_id, [])

    def companion_products(self, *, seller_id, product, limit=5):
        del seller_id, limit
        return self.companions.get(product.id, [])

    def add_idempotent(self, recommendation):
        key = (recommendation.dead_stock_assessment_id, recommendation.calculation_version)
        existing = self.rows.get(key)
        if existing:
            return existing, False
        recommendation.id = uuid4()
        self.rows[key] = recommendation
        return recommendation, True

    def latest_recommendation(self, *, seller_id, product_id):
        rows = [row for row in self.rows.values() if row.seller_id == seller_id and row.product_id == product_id]
        rows.sort(key=lambda row: row.generated_at, reverse=True)
        return rows[0] if rows else None

    def list_recommendations(self, *, seller_id, product_id, limit, offset):
        rows = [row for row in self.rows.values() if row.seller_id == seller_id and row.product_id == product_id]
        rows.sort(key=lambda row: row.generated_at, reverse=True)
        return rows[offset : offset + limit], len(rows)

    def get(self, *, seller_id, recommendation_id):
        return next((row for row in self.rows.values() if row.seller_id == seller_id and row.id == recommendation_id), None)

    def save(self, recommendation):
        return recommendation


def seller():
    return SimpleNamespace(id=uuid4())


def product(owner, *, stock=20, cost=Decimal("50.00"), price=Decimal("100.00"), category="general", specifications=None):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner.id,
        stock_quantity=stock,
        cost_price=cost,
        selling_price=price,
        category=category,
        specifications=specifications or {},
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def assessment(owner, item, *, classification=DeadStockClassification.AT_RISK, risk=DeadStockRiskLevel.HIGH, eligible=20, age=90, rules=None):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner.id,
        product_id=item.id,
        as_of_date=date(2026, 6, 30),
        classification=classification,
        risk_level=risk,
        risk_score=Decimal("80.00"),
        eligible_quantity=eligible,
        inventory_age_days=age,
        triggered_rules=rules or [],
    )


class DeadStockRecoveryServiceTests(unittest.TestCase):
    def setUp(self):
        self._original = {
            "dead_stock_recovery_discount_rates": settings.dead_stock_recovery_discount_rates,
            "dead_stock_recovery_bundle_min_quantity": settings.dead_stock_recovery_bundle_min_quantity,
            "dead_stock_recovery_flash_sale_min_quantity": settings.dead_stock_recovery_flash_sale_min_quantity,
            "dead_stock_recovery_flash_sale_duration_days": settings.dead_stock_recovery_flash_sale_duration_days,
            "dead_stock_recovery_expiration_days": settings.dead_stock_recovery_expiration_days,
            "dead_stock_inventory_age_threshold_days": settings.dead_stock_inventory_age_threshold_days,
        }
        settings.dead_stock_recovery_discount_rates = [0.05, 0.10, 0.15, 0.20]
        settings.dead_stock_recovery_bundle_min_quantity = 5
        settings.dead_stock_recovery_flash_sale_min_quantity = 10
        settings.dead_stock_recovery_flash_sale_duration_days = 3
        settings.dead_stock_recovery_expiration_days = 7
        settings.dead_stock_inventory_age_threshold_days = 60

    def tearDown(self):
        for key, value in self._original.items():
            setattr(settings, key, value)

    def service(self, repo, guard=None):
        return DeadStockRecoveryService(
            repository=repo,
            margin_guard_factory=lambda db: guard or FakeMarginGuard(),
        )

    def arrange(self, *, classification=DeadStockClassification.AT_RISK, risk=DeadStockRiskLevel.HIGH, eligible=20, age=90, stock=20, cost=Decimal("50.00"), visibility=None, companions=None, bundle_data=None, guard=None, specifications=None):
        owner = seller()
        item = product(owner, stock=stock, cost=cost, specifications=specifications)
        repo = FakeRepo()
        repo.products[item.id] = item
        repo.assessments[item.id] = assessment(owner, item, classification=classification, risk=risk, eligible=eligible, age=age)
        if visibility is not None:
            repo.visibility[item.id] = visibility
        if companions is not None:
            repo.companions[item.id] = companions
        if bundle_data is not None:
            repo.bundle_data[item.id] = bundle_data
        return owner, item, repo, self.service(repo, guard)

    def test_bundle_recommendation(self):
        owner, item, repo, service = self.arrange(classification=DeadStockClassification.SLOW_MOVING, risk=DeadStockRiskLevel.MEDIUM, eligible=8)

        rec, created = service.generate_for_product(seller_id=owner.id, product_id=item.id)

        self.assertTrue(created)
        self.assertEqual(DeadStockRecoveryAction.BUNDLE, rec.primary_action)
        self.assertTrue(rec.evidence["candidate_actions"][0]["evidence"]["companion_selection_requires_manual_review"])

    def test_discount_recommendation(self):
        owner, item, repo, service = self.arrange(eligible=5, stock=5, age=45)

        rec, _ = service.generate_for_product(seller_id=owner.id, product_id=item.id)

        self.assertEqual(DeadStockRecoveryAction.DISCOUNT, rec.primary_action)
        self.assertEqual(Decimal("0.200000"), rec.recommended_discount_rate)
        self.assertEqual(Decimal("80.00"), rec.recommended_price)

    def test_flash_sale_recommendation(self):
        owner, item, repo, service = self.arrange(classification=DeadStockClassification.DEAD_STOCK, risk=DeadStockRiskLevel.CRITICAL, eligible=30, stock=30, age=120)

        rec, _ = service.generate_for_product(seller_id=owner.id, product_id=item.id)

        self.assertEqual(DeadStockRecoveryAction.FLASH_SALE, rec.primary_action)
        self.assertEqual(3, rec.suggested_duration_days)
        self.assertEqual(30, rec.recommended_quantity)

    def test_seo_fix_recommendation_with_real_visibility_evidence(self):
        owner, item, repo, service = self.arrange(
            classification=DeadStockClassification.SLOW_MOVING,
            risk=DeadStockRiskLevel.MEDIUM,
            eligible=2,
            visibility={"impressions": 25, "click_through_rate": "0.005", "listing_quality_score": 30},
        )

        rec, _ = service.generate_for_product(seller_id=owner.id, product_id=item.id)

        self.assertEqual(DeadStockRecoveryAction.SEO_FIX, rec.primary_action)
        self.assertIn("LOW_IMPRESSIONS", rec.evidence["candidate_actions"][0]["evidence"]["triggering_visibility_rules"])

    def test_missing_visibility_prevents_unsupported_seo_recommendation(self):
        owner, item, repo, service = self.arrange(classification=DeadStockClassification.SLOW_MOVING, risk=DeadStockRiskLevel.MEDIUM, eligible=2)

        rec, _ = service.generate_for_product(seller_id=owner.id, product_id=item.id)

        self.assertNotEqual(DeadStockRecoveryAction.SEO_FIX, rec.primary_action)
        self.assertIn("SEO_FIX", [item["action"] for item in rec.rejected_actions])

    def test_healthy_product_produces_hold(self):
        owner, item, repo, service = self.arrange(classification=DeadStockClassification.HEALTHY, risk=DeadStockRiskLevel.LOW)

        rec, _ = service.generate_for_product(seller_id=owner.id, product_id=item.id)

        self.assertEqual(DeadStockRecoveryAction.HOLD, rec.primary_action)

    def test_missing_fee_data_produces_manual_review(self):
        owner, item, repo, service = self.arrange(eligible=2, guard=FakeMarginGuard(reject_all=["MISSING_FEE_DATA"]))

        rec, _ = service.generate_for_product(seller_id=owner.id, product_id=item.id)

        self.assertEqual(DeadStockRecoveryAction.MANUAL_REVIEW, rec.primary_action)
        self.assertEqual(DeadStockRecoveryRecommendationStatus.INSUFFICIENT_DATA, rec.recommendation_status)

    def test_margin_guard_rejects_unsafe_discount(self):
        owner, item, repo, service = self.arrange(eligible=2, guard=FakeMarginGuard(reject_all=["BELOW_MINIMUM_MARGIN"]))

        rec, _ = service.generate_for_product(seller_id=owner.id, product_id=item.id)

        self.assertEqual(DeadStockRecoveryAction.MANUAL_REVIEW, rec.primary_action)
        self.assertIn("BELOW_MINIMUM_MARGIN", rec.rejected_actions[0]["reasons"])

    def test_missing_cost(self):
        owner, item, repo, service = self.arrange(eligible=2, cost=None, guard=FakeMarginGuard(reject_all=["MISSING_COST_DATA"]))

        rec, _ = service.generate_for_product(seller_id=owner.id, product_id=item.id)

        self.assertEqual(DeadStockRecoveryAction.MANUAL_REVIEW, rec.primary_action)

    def test_maximum_discount_policy(self):
        owner, item, repo, service = self.arrange(eligible=5, stock=5, age=45, guard=FakeMarginGuard(max_discount=Decimal("0.10")))

        rec, _ = service.generate_for_product(seller_id=owner.id, product_id=item.id)

        self.assertEqual(DeadStockRecoveryAction.DISCOUNT, rec.primary_action)
        self.assertEqual(Decimal("0.100000"), rec.recommended_discount_rate)
        rejected_rates = [row.get("discount_rate") for row in rec.rejected_actions]
        self.assertIn("0.15", rejected_rates)

    def test_marketplace_price_increment(self):
        settings.dead_stock_recovery_discount_rates = [0.05, 0.10]
        owner, item, repo, service = self.arrange(eligible=5, stock=5, age=45, guard=FakeMarginGuard(increment=Decimal("10.00")))

        rec, _ = service.generate_for_product(seller_id=owner.id, product_id=item.id)

        self.assertEqual(DeadStockRecoveryAction.DISCOUNT, rec.primary_action)
        self.assertEqual(Decimal("0.100000"), rec.recommended_discount_rate)
        self.assertIn("INVALID_MARKETPLACE_INCREMENT", rec.rejected_actions[0]["reasons"])

    def test_multiple_candidate_actions(self):
        owner, item, repo, service = self.arrange(
            classification=DeadStockClassification.DEAD_STOCK,
            risk=DeadStockRiskLevel.CRITICAL,
            eligible=30,
            visibility={"status": "LOW_VISIBILITY"},
        )

        rec, _ = service.generate_for_product(seller_id=owner.id, product_id=item.id)

        actions = [item["action"] for item in rec.evidence["candidate_actions"]]
        self.assertIn("BUNDLE", actions)
        self.assertIn("DISCOUNT", actions)
        self.assertIn("FLASH_SALE", actions)
        self.assertIn("SEO_FIX", actions)

    def test_primary_action_ranking(self):
        owner, item, repo, service = self.arrange(classification=DeadStockClassification.DEAD_STOCK, risk=DeadStockRiskLevel.CRITICAL, eligible=30, age=120)

        rec, _ = service.generate_for_product(seller_id=owner.id, product_id=item.id)

        self.assertEqual(DeadStockRecoveryAction.FLASH_SALE, rec.primary_action)
        self.assertIn("DISCOUNT", rec.secondary_actions)

    def test_duplicate_task_retry(self):
        owner, item, repo, service = self.arrange()

        first, first_created = service.generate_for_product(seller_id=owner.id, product_id=item.id)
        second, second_created = service.generate_for_product(seller_id=owner.id, product_id=item.id)

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertIs(first, second)

    def test_recommendation_lifecycle(self):
        owner, item, repo, service = self.arrange()
        rec, _ = service.generate_for_product(seller_id=owner.id, product_id=item.id)

        acknowledged = service.acknowledge(seller_id=owner.id, recommendation_id=rec.id)
        self.assertEqual(DeadStockRecoveryRecommendationStatus.ACKNOWLEDGED, acknowledged.recommendation_status)
        dismissed = service.dismiss(seller_id=owner.id, recommendation_id=rec.id)

        self.assertEqual(DeadStockRecoveryRecommendationStatus.DISMISSED, dismissed.recommendation_status)
        self.assertIsNotNone(dismissed.dismissed_at)

    def test_seller_isolation(self):
        owner, item, repo, service = self.arrange()
        other = seller()
        rec, _ = service.generate_for_product(seller_id=owner.id, product_id=item.id)

        self.assertIsNone(service.latest_recommendation(seller_id=other.id, product_id=item.id))
        self.assertIsNone(service.acknowledge(seller_id=other.id, recommendation_id=rec.id))

    def test_historical_preservation(self):
        owner, item, repo, service = self.arrange()
        first, _ = service.generate_for_product(seller_id=owner.id, product_id=item.id)
        repo.assessments[item.id] = assessment(owner, item, classification=DeadStockClassification.DEAD_STOCK, risk=DeadStockRiskLevel.CRITICAL, eligible=30, age=120)

        second, created = service.generate_for_product(seller_id=owner.id, product_id=item.id)

        self.assertTrue(created)
        self.assertNotEqual(first.dead_stock_assessment_id, second.dead_stock_assessment_id)
        rows, total = service.recommendation_history(seller_id=owner.id, product_id=item.id, limit=10, offset=0)
        self.assertEqual(2, total)
        self.assertEqual(2, len(rows))


if __name__ == "__main__":
    unittest.main()
