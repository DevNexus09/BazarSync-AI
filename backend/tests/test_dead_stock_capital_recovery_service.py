from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from uuid import uuid4

from app.core.config import settings
from app.models.dead_stock_capital_recovery import CapitalRecoveryEstimationMethod, CapitalRecoveryEstimateStatus
from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryAction
from app.models.demand_elasticity_estimate import DemandEstimateDataStatus, DemandEstimationMethod
from app.services.dead_stock_capital_recovery_service import DeadStockCapitalRecoveryService, RecoverySimulationInput


class Reason:
    def __init__(self, value):
        self.value = value


class GuardResult:
    def __init__(self, *, allowed=True, reasons=None, fee=Decimal("15.00")):
        self.is_allowed = allowed
        self.rejection_reasons = [Reason(reason) for reason in (reasons or [])]
        self.fee = fee

    def to_evidence(self):
        return {
            "is_allowed": self.is_allowed,
            "rejection_reasons": [reason.value for reason in self.rejection_reasons],
            "fee_breakdown": {
                "percentage_commission_amount": "10.00",
                "payment_fee_amount": "2.00",
                "fixed_fees": "3.00",
                "other_variable_cost": "0.00",
                "total_fee_amount": str(self.fee),
            },
        }


class FakeMarginGuard:
    def __init__(self, result=None):
        self.result = result or GuardResult()
        self.calls = []

    def validate_candidate(self, *, seller_id, product, candidate_price):
        self.calls.append((seller_id, product.id, candidate_price))
        return self.result


class FakeRepo:
    def __init__(self):
        self.products = {}
        self.assessments = {}
        self.recommendations = {}
        self.demand = {}
        self.promotions = {}
        self.category_promotions = {}
        self.rows = []

    def product(self, *, seller_id, product_id):
        item = self.products.get(product_id)
        return item if item and item.seller_id == seller_id else None

    def latest_assessment(self, *, seller_id, product_id):
        row = self.assessments.get(product_id)
        return row if row and row.seller_id == seller_id else None

    def latest_recovery_recommendation(self, *, seller_id, product_id):
        row = self.recommendations.get(product_id)
        return row if row and row.seller_id == seller_id else None

    def latest_demand_estimate(self, *, seller_id, product_id):
        row = self.demand.get(product_id)
        return row if row and row.seller_id == seller_id else None

    def promotion_history_for_product(self, *, seller_id, product_id):
        del seller_id
        return self.promotions.get(product_id, [])

    def category_promotion_history(self, *, seller_id, category):
        del seller_id
        return self.category_promotions.get(category, [])

    def add(self, estimate):
        estimate.id = uuid4()
        self.rows.append(estimate)
        return estimate

    def latest_estimate(self, *, seller_id, product_id):
        rows = [row for row in self.rows if row.seller_id == seller_id and row.product_id == product_id]
        rows.sort(key=lambda row: row.calculated_at, reverse=True)
        return rows[0] if rows else None


def seller():
    return SimpleNamespace(id=uuid4())


def product(owner, *, stock=100, cost=Decimal("200.00"), price=Decimal("300.00"), category="general"):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner.id,
        stock_quantity=stock,
        cost_price=cost,
        selling_price=price,
        category=category,
    )


def assessment(owner, item, *, eligible=100):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner.id,
        product_id=item.id,
        eligible_quantity=eligible,
    )


def recommendation(owner, item, assessment_id, *, action=DeadStockRecoveryAction.DISCOUNT, price=Decimal("285.00"), qty=60):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner.id,
        product_id=item.id,
        dead_stock_assessment_id=assessment_id,
        primary_action=action,
        recommended_price=price,
        recommended_quantity=qty,
        suggested_duration_days=7,
    )


def demand(owner, item):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner.id,
        product_id=item.id,
        estimation_method=DemandEstimationMethod.HISTORICAL_ELASTICITY,
        elasticity=Decimal("-1.000000"),
        sample_count=8,
        baseline_units=Decimal("30.0000"),
        observation_start=date(2026, 5, 1),
        observation_end=date(2026, 6, 1),
        quality_metrics={},
        confidence=Decimal("80.00"),
        data_status=DemandEstimateDataStatus.SUFFICIENT,
        calculation_version="demand_v1",
    )


class CapitalRecoveryServiceTests(unittest.TestCase):
    def setUp(self):
        self._original = {
            "dead_stock_capital_recovery_heuristic_low_sell_through_rate": settings.dead_stock_capital_recovery_heuristic_low_sell_through_rate,
            "dead_stock_capital_recovery_heuristic_central_sell_through_rate": settings.dead_stock_capital_recovery_heuristic_central_sell_through_rate,
            "dead_stock_capital_recovery_heuristic_high_sell_through_rate": settings.dead_stock_capital_recovery_heuristic_high_sell_through_rate,
        }
        settings.dead_stock_capital_recovery_heuristic_low_sell_through_rate = 0.25
        settings.dead_stock_capital_recovery_heuristic_central_sell_through_rate = 0.40
        settings.dead_stock_capital_recovery_heuristic_high_sell_through_rate = 0.55

    def tearDown(self):
        for key, value in self._original.items():
            setattr(settings, key, value)

    def arrange(self, *, cost=Decimal("200.00"), price=Decimal("300.00"), stock=100, eligible=100, rec_price=Decimal("285.00"), rec_qty=60, guard=None):
        owner = seller()
        item = product(owner, cost=cost, price=price, stock=stock)
        repo = FakeRepo()
        repo.products[item.id] = item
        assess = assessment(owner, item, eligible=eligible)
        repo.assessments[item.id] = assess
        repo.recommendations[item.id] = recommendation(owner, item, assess.id, price=rec_price, qty=rec_qty)
        guard_obj = guard or FakeMarginGuard()
        service = DeadStockCapitalRecoveryService(repository=repo, margin_guard_factory=lambda db: guard_obj)
        return owner, item, repo, service, guard_obj

    def test_locked_capital(self):
        owner, item, repo, service, guard = self.arrange()

        estimate = service.simulate_for_product(seller_id=owner.id, product_id=item.id, simulation=RecoverySimulationInput(action=DeadStockRecoveryAction.DISCOUNT))

        self.assertEqual(60, estimate.eligible_quantity)
        self.assertEqual(Decimal("12000.00"), estimate.locked_capital)

    def test_missing_cost(self):
        owner, item, repo, service, guard = self.arrange(cost=None)

        estimate = service.simulate_for_product(seller_id=owner.id, product_id=item.id, simulation=RecoverySimulationInput(action=DeadStockRecoveryAction.DISCOUNT))

        self.assertIsNone(estimate.locked_capital)
        self.assertEqual(CapitalRecoveryEstimateStatus.INSUFFICIENT_DATA, estimate.estimate_status)
        self.assertEqual("MISSING_COST_DATA", estimate.evidence["reason"])

    def test_gross_recovered_cash_and_marketplace_fees(self):
        owner, item, repo, service, guard = self.arrange()

        estimate = service.simulate_for_product(seller_id=owner.id, product_id=item.id, simulation=RecoverySimulationInput(action=DeadStockRecoveryAction.DISCOUNT))

        self.assertEqual(Decimal("24.0000"), estimate.expected_units)
        self.assertEqual(Decimal("6840.00"), estimate.gross_recovered_cash)
        self.assertEqual(Decimal("6480.00"), estimate.net_cash_recovered)
        self.assertEqual("15.00", estimate.evidence["per_unit_selling_costs"])

    def test_negative_contribution_is_not_hidden(self):
        owner, item, repo, service, guard = self.arrange(cost=Decimal("300.00"), rec_price=Decimal("250.00"), guard=FakeMarginGuard(GuardResult(fee=Decimal("15.00"))))

        estimate = service.simulate_for_product(seller_id=owner.id, product_id=item.id, simulation=RecoverySimulationInput(action=DeadStockRecoveryAction.BUNDLE))

        self.assertLess(estimate.contribution_recovered, Decimal("0"))

    def test_cost_basis_recovery_and_ratio(self):
        owner, item, repo, service, guard = self.arrange()

        estimate = service.simulate_for_product(seller_id=owner.id, product_id=item.id, simulation=RecoverySimulationInput(action=DeadStockRecoveryAction.DISCOUNT))

        self.assertEqual(Decimal("6480.00"), estimate.cost_basis_recovered)
        self.assertEqual(Decimal("5520.00"), estimate.remaining_locked_capital)
        self.assertEqual(Decimal("0.540000"), estimate.capital_recovery_ratio)

    def test_low_central_high_estimates(self):
        owner, item, repo, service, guard = self.arrange()

        estimate = service.simulate_for_product(seller_id=owner.id, product_id=item.id, simulation=RecoverySimulationInput(action=DeadStockRecoveryAction.DISCOUNT))

        self.assertEqual(Decimal("15.0000"), estimate.expected_units_low)
        self.assertEqual(Decimal("24.0000"), estimate.expected_units)
        self.assertEqual(Decimal("33.0000"), estimate.expected_units_high)

    def test_margin_guard_rejection(self):
        owner, item, repo, service, guard = self.arrange(guard=FakeMarginGuard(GuardResult(allowed=False, reasons=["BELOW_MINIMUM_MARGIN"])))

        estimate = service.simulate_for_product(seller_id=owner.id, product_id=item.id, simulation=RecoverySimulationInput(action=DeadStockRecoveryAction.DISCOUNT))

        self.assertEqual(CapitalRecoveryEstimateStatus.BLOCKED_BY_MARGIN_POLICY, estimate.estimate_status)
        self.assertEqual("MARGIN_GUARD_REJECTED", estimate.evidence["reason"])

    def test_missing_fee_data_fails_closed_without_zero_fee_assumption(self):
        owner, item, repo, service, guard = self.arrange(guard=FakeMarginGuard(GuardResult(allowed=False, reasons=["MISSING_FEE_DATA"], fee=Decimal("0.00"))))

        estimate = service.simulate_for_product(seller_id=owner.id, product_id=item.id, simulation=RecoverySimulationInput(action=DeadStockRecoveryAction.HOLD))

        self.assertEqual(Decimal("12000.00"), estimate.locked_capital)
        self.assertEqual(CapitalRecoveryEstimateStatus.INSUFFICIENT_DATA, estimate.estimate_status)
        self.assertEqual("MISSING_FEE_DATA", estimate.evidence["reason"])
        self.assertIsNone(estimate.net_cash_recovered)

    def test_historical_demand_estimate(self):
        owner, item, repo, service, guard = self.arrange()
        repo.demand[item.id] = demand(owner, item)

        estimate = service.simulate_for_product(seller_id=owner.id, product_id=item.id, simulation=RecoverySimulationInput(action=DeadStockRecoveryAction.DISCOUNT))

        self.assertEqual(CapitalRecoveryEstimationMethod.HISTORICAL_DEMAND_RESPONSE, estimate.estimation_method)
        self.assertEqual(CapitalRecoveryEstimateStatus.CALCULATED, estimate.estimate_status)
        self.assertEqual(Decimal("80.00"), estimate.confidence_score)

    def test_heuristic_fallback(self):
        owner, item, repo, service, guard = self.arrange()

        estimate = service.simulate_for_product(seller_id=owner.id, product_id=item.id, simulation=RecoverySimulationInput(action=DeadStockRecoveryAction.DISCOUNT))

        self.assertEqual(CapitalRecoveryEstimationMethod.CONSERVATIVE_HEURISTIC, estimate.estimation_method)
        self.assertTrue(estimate.evidence["unit_estimate"]["not_historically_learned"])

    def test_insufficient_data_zero_inventory(self):
        owner, item, repo, service, guard = self.arrange(stock=0, eligible=0, rec_qty=0)

        estimate = service.simulate_for_product(seller_id=owner.id, product_id=item.id, simulation=RecoverySimulationInput(action=DeadStockRecoveryAction.DISCOUNT))

        self.assertEqual(CapitalRecoveryEstimateStatus.INSUFFICIENT_DATA, estimate.estimate_status)
        self.assertEqual("ZERO_ELIGIBLE_INVENTORY", estimate.evidence["reason"])

    def test_decimal_precision(self):
        owner, item, repo, service, guard = self.arrange(cost=Decimal("123.456"), price=Decimal("300.00"), rec_price=Decimal("271.239"))

        estimate = service.simulate_for_product(seller_id=owner.id, product_id=item.id, simulation=RecoverySimulationInput(action=DeadStockRecoveryAction.DISCOUNT))

        self.assertEqual(Decimal("123.46"), estimate.unit_cost)
        self.assertEqual(Decimal("271.24"), estimate.candidate_price)
        self.assertEqual(Decimal("0.830223"), estimate.capital_recovery_ratio)

    def test_seller_isolation(self):
        owner, item, repo, service, guard = self.arrange()
        other = seller()

        with self.assertRaises(ValueError):
            service.simulate_for_product(seller_id=other.id, product_id=item.id, simulation=RecoverySimulationInput(action=DeadStockRecoveryAction.DISCOUNT))

    def test_no_state_mutation_during_simulation(self):
        owner, item, repo, service, guard = self.arrange()
        before_price = item.selling_price
        before_stock = item.stock_quantity

        service.simulate_for_product(seller_id=owner.id, product_id=item.id, simulation=RecoverySimulationInput(action=DeadStockRecoveryAction.DISCOUNT, candidate_discount=Decimal("0.10")))

        self.assertEqual(before_price, item.selling_price)
        self.assertEqual(before_stock, item.stock_quantity)
        self.assertEqual([], repo.rows)

    def test_persisted_estimate_for_get_endpoint(self):
        owner, item, repo, service, guard = self.arrange()

        saved = service.estimate_for_product(seller_id=owner.id, product_id=item.id, calculated_at=datetime(2026, 7, 3, tzinfo=timezone.utc))
        latest = service.latest_estimate(seller_id=owner.id, product_id=item.id)

        self.assertIs(saved, latest)
        self.assertEqual(1, len(repo.rows))


if __name__ == "__main__":
    unittest.main()
