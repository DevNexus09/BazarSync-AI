from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.models.dead_stock_assessment import DeadStockClassification, DeadStockRiskLevel
from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryAction
from app.models.telegram_inventory_alert import TelegramInventoryAlertType
from app.tasks import dead_stock_workflow_tasks as tasks


class DeadStockWorkflowTaskTests(unittest.TestCase):
    def setUp(self) -> None:
        tasks._LAST_ENQUEUED_AT.clear()

    def test_full_daily_phase9_pipeline_order(self):
        workflow = tasks._phase9_workflow_chain(
            batch_size=100,
            as_of_date="2026-07-03",
            seller_id=str(uuid4()),
            product_id=None,
        )

        self.assertEqual(
            [
                "inventory_history.capture_daily_inventory_snapshots",
                "inventory_aging.calculate_inventory_aging",
                "sales_velocity.calculate_daily_sales_velocity",
                "dead_stock.assess_dead_stock",
                "dead_stock.generate_recovery_recommendations_batch",
                "dead_stock.estimate_capital_recovery_batch",
                "dead_stock.refresh_dashboard",
                "dead_stock.generate_phase9_alerts",
                "telegram_inventory_alerts.enqueue_due",
            ],
            [signature.task for signature in workflow.tasks],
        )

    def test_product_recalculation_chain_is_scoped(self):
        seller_id = uuid4()
        product_id = uuid4()
        workflow = tasks._phase9_workflow_chain(
            batch_size=1,
            as_of_date="2026-07-03",
            seller_id=str(seller_id),
            product_id=str(product_id),
        )

        for signature in workflow.tasks[:6]:
            self.assertEqual(str(seller_id), signature.kwargs["seller_id"])
            self.assertEqual(str(product_id), signature.kwargs["product_id"])

    def test_irrelevant_recalculation_reason_is_ignored(self):
        with patch.object(tasks.recalculate_product_dead_stock_workflow_task, "delay") as delay:
            enqueued = tasks.enqueue_dead_stock_recalculation(
                seller_id=uuid4(),
                product_id=uuid4(),
                reason="title_changed",
            )

        self.assertFalse(enqueued)
        delay.assert_not_called()

    def test_duplicate_recalculation_is_debounced(self):
        seller_id = uuid4()
        product_id = uuid4()
        with patch.object(tasks.recalculate_product_dead_stock_workflow_task, "delay") as delay:
            first = tasks.enqueue_dead_stock_recalculation(
                seller_id=seller_id,
                product_id=product_id,
                reason="inventory_adjustment",
            )
            second = tasks.enqueue_dead_stock_recalculation(
                seller_id=seller_id,
                product_id=product_id,
                reason="inventory_adjustment",
            )

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(1, delay.call_count)

    def test_recalculation_enqueue_redis_failure_is_safe(self):
        with patch.object(tasks.recalculate_product_dead_stock_workflow_task, "delay", side_effect=RuntimeError("redis down")):
            enqueued = tasks.enqueue_dead_stock_recalculation(
                seller_id=uuid4(),
                product_id=uuid4(),
                reason="completed_sale",
            )

        self.assertFalse(enqueued)

    def test_recalculation_can_enqueue_after_debounce_window(self):
        seller_id = uuid4()
        product_id = uuid4()
        tasks._LAST_ENQUEUED_AT[(str(seller_id), str(product_id))] = (
            datetime.now(timezone.utc) - timedelta(seconds=tasks.settings.dead_stock_workflow_debounce_seconds + 1)
        )

        with patch.object(tasks.recalculate_product_dead_stock_workflow_task, "delay") as delay:
            enqueued = tasks.enqueue_dead_stock_recalculation(
                seller_id=seller_id,
                product_id=product_id,
                reason="return",
            )

        self.assertTrue(enqueued)
        delay.assert_called_once()

    def test_recovery_generation_failure_is_isolated_to_product(self):
        seller_id = uuid4()
        first = uuid4()
        second = uuid4()
        session = FakeSession()

        class FakeRecoveryService:
            def __init__(self, _session):
                pass

            def generate_for_product(self, *, seller_id, product_id):
                if product_id == first:
                    raise RuntimeError("boom")
                return object(), True

        class FakeRecoveryRepo:
            def __init__(self, _session):
                pass

            def latest_assessment(self, *, seller_id, product_id):
                return object()

        with (
            patch.object(tasks, "SessionLocal", return_value=session),
            patch.object(tasks, "DeadStockRecoveryRepository", FakeRecoveryRepo),
            patch.object(tasks, "DeadStockRecoveryService", FakeRecoveryService),
            patch.object(tasks, "_iter_recovery_product_ids", return_value=[(seller_id, first), (seller_id, second)]),
        ):
            result = tasks.generate_dead_stock_recovery_recommendations_batch_task.run(batch_size=2)

        self.assertEqual(1, result["created_count"])
        self.assertEqual(1, result["failed_count"])
        self.assertEqual(1, session.rollback_count)
        self.assertTrue(session.closed)

    def test_recovery_generation_skips_products_without_assessment(self):
        seller_id = uuid4()
        product_id = uuid4()

        class FakeRecoveryRepo:
            def __init__(self, _session):
                pass

            def latest_assessment(self, *, seller_id, product_id):
                return None

        class FakeRecoveryService:
            def __init__(self, _session):
                pass

            def generate_for_product(self, *, seller_id, product_id):
                raise AssertionError("should not generate without an assessment")

        with (
            patch.object(tasks, "SessionLocal", return_value=FakeSession()),
            patch.object(tasks, "DeadStockRecoveryRepository", FakeRecoveryRepo),
            patch.object(tasks, "DeadStockRecoveryService", FakeRecoveryService),
            patch.object(tasks, "_iter_recovery_product_ids", return_value=[(seller_id, product_id)]),
        ):
            result = tasks.generate_dead_stock_recovery_recommendations_batch_task.run(batch_size=1)

        self.assertEqual(0, result["created_count"])
        self.assertEqual(1, result["skipped_count"])
        self.assertEqual(0, result["failed_count"])

    def test_capital_estimation_failure_is_isolated_to_product(self):
        seller_id = uuid4()
        first = uuid4()
        second = uuid4()
        session = FakeSession()

        class FakeCapitalService:
            def __init__(self, _session):
                pass

            def latest_estimate(self, *, seller_id, product_id):
                return None

            def latest_recovery_recommendation(self, *, seller_id, product_id):
                return object()

            def estimate_for_product(self, *, seller_id, product_id):
                if product_id == first:
                    raise RuntimeError("boom")
                return object()

        with (
            patch.object(tasks, "SessionLocal", return_value=session),
            patch.object(tasks, "DeadStockCapitalRecoveryService", FakeCapitalService),
            patch.object(tasks, "_iter_recovery_product_ids", return_value=[(seller_id, first), (seller_id, second)]),
        ):
            result = tasks.estimate_dead_stock_capital_recovery_batch_task.run(batch_size=2)

        self.assertEqual(1, result["created_count"])
        self.assertEqual(1, result["failed_count"])
        self.assertEqual(1, session.rollback_count)
        self.assertTrue(session.closed)

    def test_capital_estimation_retry_skips_existing_formula_result(self):
        seller_id = uuid4()
        product_id = uuid4()
        recommendation = type("Recommendation", (), {"id": uuid4()})()
        existing = type(
            "Estimate",
            (),
            {
                "recovery_recommendation_id": recommendation.id,
                "calculation_version": tasks.settings.dead_stock_capital_recovery_formula_version,
            },
        )()

        class FakeCapitalService:
            def __init__(self, _session):
                pass

            def latest_estimate(self, *, seller_id, product_id):
                return existing

            def latest_recovery_recommendation(self, *, seller_id, product_id):
                return recommendation

            def estimate_for_product(self, *, seller_id, product_id):
                raise AssertionError("should skip duplicate")

        with (
            patch.object(tasks, "SessionLocal", return_value=FakeSession()),
            patch.object(tasks, "DeadStockCapitalRecoveryService", FakeCapitalService),
            patch.object(tasks, "_iter_recovery_product_ids", return_value=[(seller_id, product_id)]),
        ):
            result = tasks.estimate_dead_stock_capital_recovery_batch_task.run(batch_size=1)

        self.assertEqual(0, result["created_count"])
        self.assertEqual(1, result["skipped_count"])
        self.assertEqual(0, result["failed_count"])

    def test_capital_estimation_skips_products_without_recommendation(self):
        seller_id = uuid4()
        product_id = uuid4()

        class FakeCapitalService:
            def __init__(self, _session):
                pass

            def latest_estimate(self, *, seller_id, product_id):
                return None

            def latest_recovery_recommendation(self, *, seller_id, product_id):
                return None

            def estimate_for_product(self, *, seller_id, product_id):
                raise AssertionError("should not estimate without a recommendation")

        with (
            patch.object(tasks, "SessionLocal", return_value=FakeSession()),
            patch.object(tasks, "DeadStockCapitalRecoveryService", FakeCapitalService),
            patch.object(tasks, "_iter_recovery_product_ids", return_value=[(seller_id, product_id)]),
        ):
            result = tasks.estimate_dead_stock_capital_recovery_batch_task.run(batch_size=1)

        self.assertEqual(0, result["created_count"])
        self.assertEqual(1, result["skipped_count"])
        self.assertEqual(0, result["failed_count"])

    def test_phase9_alerts_fail_closed_when_disabled(self):
        result = tasks.generate_dead_stock_phase9_alerts_task(
            seller_id=str(uuid4()),
            product_id=str(uuid4()),
        )

        self.assertEqual(0, result["created_count"])
        self.assertEqual(1, result["skipped_count"])

    def test_phase9_alert_candidates_for_meaningful_changes(self):
        assessment = _assessment(
            classification=DeadStockClassification.DEAD_STOCK,
            risk_level=DeadStockRiskLevel.CRITICAL,
            age=95,
        )
        previous = _assessment(
            seller_id=assessment.seller_id,
            product_id=assessment.product_id,
            classification=DeadStockClassification.AT_RISK,
            risk_level=DeadStockRiskLevel.HIGH,
            age=70,
        )
        recommendation = SimpleNamespace(id=uuid4(), primary_action=DeadStockRecoveryAction.DISCOUNT)
        capital = SimpleNamespace(id=uuid4(), locked_capital=Decimal("12000.00"), gross_recovered_cash=Decimal("7000.00"), evidence={"currency": "BDT"})

        alerts = tasks._phase9_alert_candidates(
            product=SimpleNamespace(title="Dove Body Lotion", stock_quantity=120),
            assessment=assessment,
            previous=previous,
            recommendation=recommendation,
            capital=capital,
            alert_repo=FakeAlertRepo(),
        )

        self.assertEqual(
            {
                TelegramInventoryAlertType.DEAD_STOCK_CLASSIFIED,
                TelegramInventoryAlertType.DEAD_STOCK_CRITICAL_RISK,
                TelegramInventoryAlertType.DEAD_STOCK_LOCKED_CAPITAL,
                TelegramInventoryAlertType.DEAD_STOCK_RECOVERY_AVAILABLE,
                TelegramInventoryAlertType.DEAD_STOCK_AGED,
            },
            {alert.alert_type for alert in alerts},
        )
        self.assertTrue(all("estimated cash recovery" in (alert.message_text or "") for alert in alerts))

    def test_phase9_alert_cooldown_suppresses_sent_alert(self):
        assessment = _assessment(
            classification=DeadStockClassification.DEAD_STOCK,
            risk_level=DeadStockRiskLevel.CRITICAL,
            age=95,
        )
        recent = SimpleNamespace(sent_at=datetime.now(timezone.utc))

        alerts = tasks._phase9_alert_candidates(
            product=SimpleNamespace(title="Product", stock_quantity=10),
            assessment=assessment,
            previous=None,
            recommendation=None,
            capital=None,
            alert_repo=FakeAlertRepo(recent=recent),
        )

        self.assertEqual([], alerts)

    def test_phase9_alert_task_honors_seller_preferences(self):
        seller_id = uuid4()
        product_id = uuid4()

        with (
            patch.object(tasks.settings, "dead_stock_alerts_enabled", True),
            patch.object(tasks, "SessionLocal", return_value=FakeSession()),
            patch.object(tasks, "_iter_recovery_product_ids", return_value=[(seller_id, product_id)]),
            patch.object(tasks, "TelegramInventoryAlertRepository", lambda _session: FakeAlertRepo(connection=SimpleNamespace(is_connected=False, telegram_chat_id=None))),
            patch.object(tasks, "DeadStockRecoveryRepository"),
            patch.object(tasks, "DeadStockCapitalRecoveryRepository"),
        ):
            result = tasks.generate_dead_stock_phase9_alerts_task.run(seller_id=str(seller_id), product_id=str(product_id))

        self.assertEqual(0, result["created_count"])
        self.assertEqual(1, result["skipped_count"])


class FakeSession:
    def __init__(self) -> None:
        self.rollback_count = 0
        self.closed = False

    def rollback(self) -> None:
        self.rollback_count += 1

    def close(self) -> None:
        self.closed = True


class FakeAlertRepo:
    def __init__(self, *, recent=None, connection=None) -> None:
        self.recent = recent
        self.connection = connection or SimpleNamespace(is_connected=True, telegram_chat_id="123")

    def latest_sent(self, **_kwargs):
        return self.recent

    def get_connection(self, _seller_id):
        return self.connection


def _assessment(
    *,
    seller_id=None,
    product_id=None,
    classification,
    risk_level,
    age,
):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=seller_id or uuid4(),
        product_id=product_id or uuid4(),
        classification=classification,
        risk_level=risk_level,
        inventory_age_days=age,
        days_since_last_sale=67,
        as_of_date=datetime(2026, 7, 3, tzinfo=timezone.utc).date(),
        assessed_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
        calculation_version="v1",
    )


if __name__ == "__main__":
    unittest.main()
