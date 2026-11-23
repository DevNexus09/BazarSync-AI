from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from uuid import uuid4

from app.core.config import settings
from app.models.inventory_risk import InventoryRiskDataStatus, InventoryRiskLevel
from app.models.reorder_recommendation import ReorderRecommendationAction
from app.models.stockout_prediction import StockoutPredictionStatus
from app.models.telegram_inventory_alert import (
    TelegramInventoryAlert,
    TelegramInventoryAlertStatus,
    TelegramInventoryAlertType,
)
from app.services.telegram.inventory_alert_formatter import (
    InventoryAlertMessageContext,
    format_inventory_alert_message,
)
from app.services.telegram.inventory_alert_service import TelegramInventoryAlertService
from app.services.telegram.telegram_service import DeliveryStatus, TelegramDeliveryResult


class FakeInventoryAlertRepository:
    def __init__(self) -> None:
        self.assessments = {}
        self.previous = {}
        self.alerts_by_key = {}
        self.alerts_by_id = {}
        self.sent_alerts = {}
        self.connection = SimpleNamespace(is_connected=True, telegram_chat_id="12345", last_alert_sent_at=None)
        self.failed = []
        self.sent = []

    def get_risk_with_context(self, risk_assessment_id):
        return self.assessments.get(risk_assessment_id)

    def previous_risk(self, assessment):
        return self.previous.get(assessment.product_id)

    def add_idempotent(self, alert):
        existing = self.alerts_by_key.get(alert.dedupe_key)
        if existing:
            return existing, False
        self.alerts_by_key[alert.dedupe_key] = alert
        self.alerts_by_id[alert.id] = alert
        return alert, True

    def latest_sent(self, *, seller_id, product_id, alert_type, risk_level=None):
        return self.sent_alerts.get((seller_id, product_id, alert_type, risk_level))

    def get_alert_for_delivery(self, alert_id):
        return self.alerts_by_id.get(alert_id)

    def due_alerts(self, *, limit=100):
        return list(self.alerts_by_id.values())[:limit]

    def get_connection(self, seller_id):
        return self.connection

    def mark_sending(self, alert):
        if alert.status == TelegramInventoryAlertStatus.SENT:
            return False
        alert.status = TelegramInventoryAlertStatus.SENDING
        alert.attempt_count = (alert.attempt_count or 0) + 1
        return True

    def mark_sent(self, alert, *, sent_at):
        alert.status = TelegramInventoryAlertStatus.SENT
        alert.sent_at = sent_at
        self.sent.append(alert.id)

    def mark_failed(self, alert, *, failure_code, next_attempt_at, terminal):
        alert.status = TelegramInventoryAlertStatus.CANCELLED if terminal else TelegramInventoryAlertStatus.FAILED
        alert.failure_code = failure_code
        alert.next_attempt_at = next_attempt_at
        self.failed.append((alert.id, failure_code, terminal))


class FakeTelegramService:
    def __init__(self, result=None):
        self.result = result or TelegramDeliveryResult(
            success=True,
            status=DeliveryStatus.delivered,
            message_id=100,
            chat_id=12345,
        )
        self.calls = []

    async def send_text_message(self, text, **kwargs):
        self.calls.append((text, kwargs))
        return self.result


def product(owner_id, *, title="Dove Body Lotion"):
    return SimpleNamespace(id=uuid4(), seller_id=owner_id, title=title)


def prediction(owner_id, item_id, *, days=5, inventory_position=17, status=StockoutPredictionStatus.PREDICTED):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner_id,
        product_id=item_id,
        inventory_position=inventory_position,
        daily_sales_rate=Decimal("3.4"),
        days_remaining=Decimal(str(days)),
        predicted_stockout_date=date(2026, 7, 4),
        prediction_status=status,
    )


def reorder(owner_id, item_id, *, deadline=date(2026, 6, 29), action=ReorderRecommendationAction.REORDER):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner_id,
        product_id=item_id,
        supplier_lead_time_days=8,
        safety_buffer_days=3,
        action=action,
        recommended_quantity=150,
        reorder_deadline=deadline,
    )


NO_REORDER_OVERRIDE = object()


def assessment(*, risk_level=InventoryRiskLevel.HIGH, days=5, inventory_position=17, status=StockoutPredictionStatus.PREDICTED, as_of=date(2026, 6, 29), owner_id=None, item=None, reorder_obj=NO_REORDER_OVERRIDE):
    owner_id = owner_id or uuid4()
    item = item or product(owner_id)
    pred = prediction(owner_id, item.id, days=days, inventory_position=inventory_position, status=status)
    recommendation = reorder(owner_id, item.id) if reorder_obj is NO_REORDER_OVERRIDE else reorder_obj
    return SimpleNamespace(
        id=uuid4(),
        seller_id=owner_id,
        product_id=item.id,
        product=item,
        stockout_prediction=pred,
        reorder_recommendation=recommendation,
        reorder_recommendation_id=getattr(recommendation, "id", None),
        risk_level=risk_level,
        data_status=InventoryRiskDataStatus.SUFFICIENT,
        as_of_date=as_of,
        calculation_version="v1",
    )


class TelegramInventoryAlertServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.old_cooldown = settings.telegram_inventory_alert_cooldown_hours
        self.old_drop = settings.telegram_inventory_alert_material_days_drop
        settings.telegram_inventory_alert_cooldown_hours = 24
        settings.telegram_inventory_alert_material_days_drop = 2.0

    def tearDown(self):
        settings.telegram_inventory_alert_cooldown_hours = self.old_cooldown
        settings.telegram_inventory_alert_material_days_drop = self.old_drop

    def test_critical_alert(self):
        repo = FakeInventoryAlertRepository()
        current = assessment(risk_level=InventoryRiskLevel.CRITICAL)
        repo.assessments[current.id] = current

        result = TelegramInventoryAlertService(repository=repo, telegram_service=FakeTelegramService()).generate_for_risk_assessment(current.id)

        self.assertGreaterEqual(result.created_count, 1)
        self.assertIn(TelegramInventoryAlertType.CRITICAL_RISK, {alert.alert_type for alert in repo.alerts_by_id.values()})

    def test_high_risk_alert(self):
        repo = FakeInventoryAlertRepository()
        current = assessment(risk_level=InventoryRiskLevel.HIGH, reorder_obj=None)
        repo.assessments[current.id] = current

        result = TelegramInventoryAlertService(repository=repo, telegram_service=FakeTelegramService()).generate_for_risk_assessment(current.id)

        self.assertEqual(1, result.created_count)
        self.assertEqual(TelegramInventoryAlertType.HIGH_RISK, next(iter(repo.alerts_by_id.values())).alert_type)

    def test_medium_risk_produces_no_urgent_alert(self):
        repo = FakeInventoryAlertRepository()
        current = assessment(risk_level=InventoryRiskLevel.MEDIUM, reorder_obj=None)
        repo.assessments[current.id] = current

        result = TelegramInventoryAlertService(repository=repo, telegram_service=FakeTelegramService()).generate_for_risk_assessment(current.id)

        self.assertEqual(0, result.created_count)

    def test_risk_escalation(self):
        repo = FakeInventoryAlertRepository()
        current = assessment(risk_level=InventoryRiskLevel.HIGH)
        previous = assessment(risk_level=InventoryRiskLevel.MEDIUM, owner_id=current.seller_id, item=current.product, as_of=date(2026, 6, 28))
        repo.assessments[current.id] = current
        repo.previous[current.product_id] = previous

        TelegramInventoryAlertService(repository=repo, telegram_service=FakeTelegramService()).generate_for_risk_assessment(current.id)

        self.assertIn(TelegramInventoryAlertType.RISK_ESCALATION, {alert.alert_type for alert in repo.alerts_by_id.values()})

    def test_duplicate_task_retry_uses_dedupe_key(self):
        repo = FakeInventoryAlertRepository()
        current = assessment(risk_level=InventoryRiskLevel.CRITICAL)
        repo.assessments[current.id] = current
        service = TelegramInventoryAlertService(repository=repo, telegram_service=FakeTelegramService())

        first = service.generate_for_risk_assessment(current.id)
        second = service.generate_for_risk_assessment(current.id)

        self.assertGreater(first.created_count, 0)
        self.assertEqual(0, second.created_count)
        self.assertGreater(second.skipped_count, 0)

    def test_cooldown_suppresses_repeated_high(self):
        repo = FakeInventoryAlertRepository()
        current = assessment(risk_level=InventoryRiskLevel.HIGH)
        repo.assessments[current.id] = current
        old_alert = TelegramInventoryAlert(
            seller_id=current.seller_id,
            product_id=current.product_id,
            risk_assessment_id=current.id,
            alert_type=TelegramInventoryAlertType.HIGH_RISK,
            dedupe_key="old",
            sent_at=datetime.now(timezone.utc) - timedelta(hours=1),
            status=TelegramInventoryAlertStatus.SENT,
            alert_metadata={"risk_level": "HIGH"},
        )
        repo.sent_alerts[(current.seller_id, current.product_id, TelegramInventoryAlertType.HIGH_RISK, "HIGH")] = old_alert

        result = TelegramInventoryAlertService(repository=repo, telegram_service=FakeTelegramService()).generate_for_risk_assessment(current.id)

        self.assertNotIn(TelegramInventoryAlertType.HIGH_RISK, {alert.alert_type for alert in repo.alerts_by_id.values()})
        self.assertGreater(result.skipped_count, 0)

    def test_material_prediction_change(self):
        repo = FakeInventoryAlertRepository()
        current = assessment(risk_level=InventoryRiskLevel.MEDIUM, days=3, reorder_obj=None)
        previous = assessment(risk_level=InventoryRiskLevel.MEDIUM, days=8, owner_id=current.seller_id, item=current.product, as_of=date(2026, 6, 28), reorder_obj=None)
        repo.assessments[current.id] = current
        repo.previous[current.product_id] = previous

        TelegramInventoryAlertService(repository=repo, telegram_service=FakeTelegramService()).generate_for_risk_assessment(current.id)

        self.assertIn(TelegramInventoryAlertType.DAYS_REMAINING_DROP, {alert.alert_type for alert in repo.alerts_by_id.values()})

    async def test_delivery_respects_disabled_telegram(self):
        repo = FakeInventoryAlertRepository()
        alert = self._alert()
        repo.alerts_by_id[alert.id] = alert
        repo.connection = SimpleNamespace(is_connected=False, telegram_chat_id="123")

        outcome = await TelegramInventoryAlertService(repository=repo, telegram_service=FakeTelegramService()).deliver_alert(alert.id)

        self.assertEqual(TelegramInventoryAlertStatus.CANCELLED, outcome.status)
        self.assertEqual("telegram_disabled", alert.failure_code)

    async def test_delivery_respects_missing_chat_id(self):
        repo = FakeInventoryAlertRepository()
        alert = self._alert()
        repo.alerts_by_id[alert.id] = alert
        repo.connection = SimpleNamespace(is_connected=True, telegram_chat_id=None)

        outcome = await TelegramInventoryAlertService(repository=repo, telegram_service=FakeTelegramService()).deliver_alert(alert.id)

        self.assertEqual(TelegramInventoryAlertStatus.CANCELLED, outcome.status)
        self.assertEqual("missing_chat_id", alert.failure_code)

    async def test_rate_limit_and_network_failures_are_sanitized_and_retried(self):
        for detail, expected in [
            ("Telegram rate limit exceeded. retry after 10", "rate_limited"),
            ("Telegram network failure: host unreachable", "temporary_network_failure"),
        ]:
            with self.subTest(detail=detail):
                repo = FakeInventoryAlertRepository()
                alert = self._alert()
                repo.alerts_by_id[alert.id] = alert
                telegram = FakeTelegramService(
                    TelegramDeliveryResult(success=False, status=DeliveryStatus.failed, detail=detail)
                )

                outcome = await TelegramInventoryAlertService(repository=repo, telegram_service=telegram).deliver_alert(alert.id)

                self.assertEqual(TelegramInventoryAlertStatus.FAILED, outcome.status)
                self.assertEqual(expected, alert.failure_code)
                self.assertIsNotNone(alert.next_attempt_at)

    async def test_permanent_delivery_failure_is_sanitized(self):
        repo = FakeInventoryAlertRepository()
        alert = self._alert()
        repo.alerts_by_id[alert.id] = alert
        telegram = FakeTelegramService(
            TelegramDeliveryResult(success=False, status=DeliveryStatus.failed, detail="Bot does not have access to the chat. raw token abc")
        )

        outcome = await TelegramInventoryAlertService(repository=repo, telegram_service=telegram).deliver_alert(alert.id)

        self.assertEqual(TelegramInventoryAlertStatus.CANCELLED, outcome.status)
        self.assertEqual("invalid_chat", alert.failure_code)
        self.assertNotIn("token", alert.failure_code)

    async def test_successful_delivery_marks_sent_once(self):
        repo = FakeInventoryAlertRepository()
        alert = self._alert()
        repo.alerts_by_id[alert.id] = alert
        telegram = FakeTelegramService()
        service = TelegramInventoryAlertService(repository=repo, telegram_service=telegram)

        first = await service.deliver_alert(alert.id)
        second = await service.deliver_alert(alert.id)

        self.assertEqual(TelegramInventoryAlertStatus.SENT, first.status)
        self.assertEqual(TelegramInventoryAlertStatus.SENT, second.status)
        self.assertEqual(1, len(telegram.calls))

    def test_seller_isolation_uses_seller_in_dedupe(self):
        repo = FakeInventoryAlertRepository()
        one = assessment(risk_level=InventoryRiskLevel.CRITICAL)
        two = assessment(risk_level=InventoryRiskLevel.CRITICAL)
        repo.assessments[one.id] = one
        repo.assessments[two.id] = two
        service = TelegramInventoryAlertService(repository=repo, telegram_service=FakeTelegramService())

        service.generate_for_risk_assessment(one.id)
        service.generate_for_risk_assessment(two.id)

        keys = set(repo.alerts_by_key)
        self.assertTrue(any(str(one.seller_id) in key for key in keys))
        self.assertTrue(any(str(two.seller_id) in key for key in keys))

    def test_message_formatting(self):
        message = format_inventory_alert_message(
            InventoryAlertMessageContext(
                alert_type=TelegramInventoryAlertType.CRITICAL_RISK,
                product_name="Dove Body Lotion",
                current_stock=17,
                daily_sales_rate=Decimal("3.4"),
                days_remaining=Decimal("5"),
                predicted_stockout_date=date(2026, 7, 4),
                supplier_lead_time_days=8,
                safety_buffer_days=3,
                risk_level=InventoryRiskLevel.CRITICAL,
                recommended_action="REORDER",
                recommended_quantity=150,
                reorder_deadline=date(2026, 6, 29),
            )
        )

        self.assertIn("Inventory Alert", message)
        self.assertIn("Product: Dove Body Lotion", message)
        self.assertIn("Daily Sales Rate: 3.4 units/day", message)
        self.assertIn("Risk Level: CRITICAL", message)
        self.assertNotIn("uuid", message.lower())

    def _alert(self):
        return TelegramInventoryAlert(
            id=uuid4(),
            seller_id=uuid4(),
            product_id=uuid4(),
            risk_assessment_id=uuid4(),
            alert_type=TelegramInventoryAlertType.CRITICAL_RISK,
            dedupe_key=str(uuid4()),
            status=TelegramInventoryAlertStatus.PENDING,
            attempt_count=0,
            message_text="Inventory Alert\nProduct: Dove Body Lotion",
            alert_metadata={"risk_level": "CRITICAL"},
        )


if __name__ == "__main__":
    unittest.main()


def test_inventory_dashboard_url_deep_links_to_product_drawer():
    from uuid import uuid4

    from app.services.telegram.inventory_alert_service import inventory_dashboard_url

    product_id = uuid4()
    assert inventory_dashboard_url(None, product_id=product_id, reorder=True) is None
    assert inventory_dashboard_url("https://app.example.com", product_id=None, reorder=True) is None
    assert (
        inventory_dashboard_url("https://app.example.com/", product_id=product_id, reorder=True)
        == f"https://app.example.com/app/inventory-intelligence?tab=reorder&product={product_id}"
    )
    assert inventory_dashboard_url("https://app.example.com", product_id=product_id, reorder=False).endswith(
        f"?tab=today&product={product_id}"
    )
