from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from uuid import uuid4

from app.models.inventory_history import InventoryHistory
from app.models.inventory_risk import InventoryRiskDataStatus, InventoryRiskLevel
from app.models.product import Product
from app.models.reorder_recommendation import ReorderRecommendationAction, ReorderRecommendationStatus
from app.models.sales_velocity import SalesVelocityDataStatus
from app.models.seller import Seller
from app.models.stockout_prediction import StockoutPredictionStatus
from app.models.telegram_inventory_alert import TelegramInventoryAlertStatus, TelegramInventoryAlertType
from app.services.inventory_risk_service import InventoryRiskService
from app.services.reorder_recommendation_service import ReorderRecommendationService
from app.services.sales_velocity_service import SalesVelocityService
from app.services.stockout_prediction_service import StockoutPredictionService
from app.services.telegram.inventory_alert_service import TelegramInventoryAlertService
from app.services.telegram.telegram_service import DeliveryStatus, TelegramDeliveryResult


class FakeInventoryAlertRepository:
    def __init__(self, current, previous=None) -> None:
        self.current = current
        self.previous = previous
        self.alerts_by_key = {}
        self.alerts_by_id = {}
        self.connection = SimpleNamespace(is_connected=True, telegram_chat_id="12345")

    def get_risk_with_context(self, risk_assessment_id):
        return self.current if self.current.id == risk_assessment_id else None

    def previous_risk(self, assessment):
        return self.previous

    def add_idempotent(self, alert):
        existing = self.alerts_by_key.get(alert.dedupe_key)
        if existing:
            return existing, False
        self.alerts_by_key[alert.dedupe_key] = alert
        self.alerts_by_id[alert.id] = alert
        return alert, True

    def latest_sent(self, *, seller_id, product_id, alert_type, risk_level=None):
        return None

    def get_alert_for_delivery(self, alert_id):
        return self.alerts_by_id.get(alert_id)

    def due_alerts(self, *, limit=100):
        return list(self.alerts_by_id.values())[:limit]

    def get_connection(self, seller_id):
        return self.connection

    def mark_sending(self, alert):
        if alert.status not in {TelegramInventoryAlertStatus.PENDING, TelegramInventoryAlertStatus.FAILED}:
            return False
        alert.status = TelegramInventoryAlertStatus.SENDING
        alert.attempt_count = (alert.attempt_count or 0) + 1
        return True

    def mark_sent(self, alert, *, sent_at):
        alert.status = TelegramInventoryAlertStatus.SENT
        alert.sent_at = sent_at

    def mark_failed(self, alert, *, failure_code, next_attempt_at, terminal):
        alert.status = TelegramInventoryAlertStatus.CANCELLED if terminal else TelegramInventoryAlertStatus.FAILED
        alert.failure_code = failure_code
        alert.next_attempt_at = next_attempt_at


class FakeTelegramService:
    def __init__(self) -> None:
        self.calls = []

    async def send_text_message(self, text, **kwargs):
        self.calls.append((text, kwargs))
        return TelegramDeliveryResult(
            success=True,
            status=DeliveryStatus.delivered,
            message_id=10,
            chat_id=kwargs.get("chat_id"),
        )


class Phase6AcceptanceWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.seller = Seller(id=uuid4(), email="seller@example.com", password_hash="x")
        self.as_of_date = date(2026, 6, 29)
        self.calculated_at = datetime(2026, 6, 29, 6, tzinfo=timezone.utc)

    async def test_dove_body_lotion_acceptance_scenario(self):
        product = self._product(stock=40)
        inventory = self._inventory(product, stock=40)
        velocity = self._velocity(product, net_units=300, valid_records=30)
        prediction = self._prediction(product, inventory, velocity)
        recommendation = self._recommendation(product, inventory, velocity, prediction)
        risk = self._risk(product, prediction, recommendation)

        self.assertEqual(Decimal("10.0000"), velocity.daily_sales_rate)
        self.assertEqual(Decimal("4.0000"), prediction.days_remaining)
        self.assertEqual(date(2026, 7, 3), prediction.predicted_stockout_date)
        self.assertEqual(110, recommendation.reorder_point)
        self.assertEqual(150, recommendation.target_stock)
        self.assertEqual(110, recommendation.evidence["raw_reorder_quantity"])
        self.assertEqual(ReorderRecommendationAction.REORDER, recommendation.action)
        self.assertEqual(110, recommendation.recommended_quantity)
        self.assertEqual(self.as_of_date, recommendation.reorder_deadline)
        self.assertEqual(InventoryRiskLevel.CRITICAL, risk.risk_level)

        repo = FakeInventoryAlertRepository(risk)
        telegram = FakeTelegramService()
        alert_service = TelegramInventoryAlertService(repository=repo, telegram_service=telegram)
        generation = alert_service.generate_for_risk_assessment(risk.id)

        self.assertGreaterEqual(generation.created_count, 1)
        critical_alerts = [
            alert for alert in repo.alerts_by_id.values()
            if alert.alert_type == TelegramInventoryAlertType.CRITICAL_RISK
        ]
        self.assertEqual(1, len(critical_alerts))
        message = critical_alerts[0].message_text or ""
        self.assertIn("Dove Body Lotion", message)
        self.assertIn("Current Stock: 40 units", message)
        self.assertIn("Daily Sales Rate: 10 units/day", message)
        self.assertIn("Predicted Stockout: 4 days", message)
        self.assertIn("Recommended Quantity: 110 units", message)

        await alert_service.deliver_alert(critical_alerts[0].id)
        await alert_service.deliver_alert(critical_alerts[0].id)

        self.assertEqual(1, len(telegram.calls))
        self.assertEqual(TelegramInventoryAlertStatus.SENT, critical_alerts[0].status)

    def test_healthy_stock_holds_and_no_urgent_alert(self):
        product = self._product(stock=500)
        inventory = self._inventory(product, stock=500)
        velocity = self._velocity(product, net_units=300, valid_records=30)
        prediction = self._prediction(product, inventory, velocity)
        recommendation = self._recommendation(product, inventory, velocity, prediction)
        risk = self._risk(product, prediction, recommendation)

        self.assertEqual(Decimal("50.0000"), prediction.days_remaining)
        self.assertEqual(ReorderRecommendationAction.HOLD, recommendation.action)
        self.assertEqual(InventoryRiskLevel.LOW, risk.risk_level)

        repo = FakeInventoryAlertRepository(risk)
        generation = TelegramInventoryAlertService(repository=repo, telegram_service=FakeTelegramService()).generate_for_risk_assessment(risk.id)

        self.assertEqual(0, generation.created_count)

    def test_no_recent_sales_has_no_finite_stockout_or_deadline(self):
        product = self._product(stock=40)
        inventory = self._inventory(product, stock=40)
        velocity = self._velocity(product, net_units=0, valid_records=1)
        prediction = self._prediction(product, inventory, velocity)
        recommendation = self._recommendation(product, inventory, velocity, prediction)

        self.assertEqual(Decimal("0.0000"), velocity.daily_sales_rate)
        self.assertEqual(SalesVelocityDataStatus.SUFFICIENT, velocity.data_status)
        self.assertEqual(StockoutPredictionStatus.NO_RECENT_DEMAND, prediction.prediction_status)
        self.assertIsNone(prediction.predicted_stockout_date)
        self.assertEqual(ReorderRecommendationAction.HOLD, recommendation.action)
        self.assertIsNone(recommendation.reorder_deadline)
        self.assertEqual(0, recommendation.recommended_quantity)

    def test_insufficient_sales_history_does_not_fabricate_values(self):
        product = self._product(stock=40)
        inventory = self._inventory(product, stock=40)
        velocity = self._velocity(product, net_units=0, valid_records=0)
        prediction = self._prediction(product, inventory, velocity)
        recommendation = self._recommendation(product, inventory, velocity, prediction)
        risk = self._risk(product, prediction, recommendation)

        self.assertEqual(SalesVelocityDataStatus.INSUFFICIENT, velocity.data_status)
        self.assertEqual(StockoutPredictionStatus.INSUFFICIENT_DATA, prediction.prediction_status)
        self.assertIsNone(prediction.predicted_stockout_date)
        self.assertEqual(ReorderRecommendationStatus.INSUFFICIENT_DATA, recommendation.recommendation_status)
        self.assertIsNone(recommendation.reorder_deadline)
        self.assertEqual(0, recommendation.recommended_quantity)
        self.assertEqual(InventoryRiskDataStatus.INSUFFICIENT, risk.data_status)
        self.assertIsNone(risk.risk_level)

    def test_already_out_of_stock_reorders_and_alerts_once(self):
        product = self._product(stock=0)
        inventory = self._inventory(product, stock=0)
        velocity = self._velocity(product, net_units=300, valid_records=30)
        prediction = self._prediction(product, inventory, velocity)
        recommendation = self._recommendation(product, inventory, velocity, prediction)
        risk = self._risk(product, prediction, recommendation)

        self.assertEqual(Decimal("0.0000"), prediction.days_remaining)
        self.assertEqual(StockoutPredictionStatus.ALREADY_OUT_OF_STOCK, prediction.prediction_status)
        self.assertEqual(ReorderRecommendationAction.REORDER, recommendation.action)
        self.assertEqual(InventoryRiskLevel.CRITICAL, risk.risk_level)

        repo = FakeInventoryAlertRepository(risk)
        service = TelegramInventoryAlertService(repository=repo, telegram_service=FakeTelegramService())
        first = service.generate_for_risk_assessment(risk.id)
        second = service.generate_for_risk_assessment(risk.id)

        self.assertGreater(first.created_count, 0)
        self.assertEqual(0, second.created_count)
        self.assertIn(TelegramInventoryAlertType.OUT_OF_STOCK, {alert.alert_type for alert in repo.alerts_by_id.values()})

    def _product(self, *, stock: int) -> Product:
        return Product(
            id=uuid4(),
            seller_id=self.seller.id,
            title="Dove Body Lotion",
            description="Daily moisturising lotion for dry skin.",
            category="Personal Care",
            specifications={
                "safety_buffer_days": "3",
                "review_period_days": "4",
                "minimum_order_quantity": "50",
                "pack_size": "10",
            },
            cost_price=Decimal("200.00"),
            selling_price=Decimal("320.00"),
            stock_quantity=stock,
            supplier_lead_time=8,
            minimum_margin=Decimal("20.00"),
        )

    def _inventory(self, product: Product, *, stock: int) -> InventoryHistory:
        return InventoryHistory(
            id=uuid4(),
            seller_id=self.seller.id,
            product_id=product.id,
            snapshot_date=self.as_of_date,
            captured_at=self.calculated_at,
            quantity_on_hand=stock,
            quantity_reserved=0,
            quantity_available=stock,
            quantity_incoming=0,
            source="DAILY_SNAPSHOT",
            source_reference=f"acceptance:{product.id}",
            content_hash="hash",
        )

    def _velocity(self, product: Product, *, net_units: int, valid_records: int):
        calculation = SalesVelocityService(repository=SimpleNamespace()).calculate_from_aggregate(
            product=product,
            seller=self.seller,
            as_of_date=self.as_of_date,
            window_days=30,
            aggregate={
                "gross_units_sold": net_units,
                "returned_units": 0,
                "net_units_sold": net_units,
                "valid_sales_records": valid_records,
                "sales_days": 30 if valid_records else 0,
            },
            calculation_version="v1",
        )
        return SimpleNamespace(
            id=uuid4(),
            seller_id=self.seller.id,
            product_id=product.id,
            as_of_date=calculation.as_of_date,
            window_days=calculation.window_days,
            observed_days=calculation.observed_days,
            gross_units_sold=calculation.gross_units_sold,
            returned_units=calculation.returned_units,
            net_units_sold=calculation.net_units_sold,
            daily_sales_rate=calculation.daily_sales_rate,
            sales_days=calculation.sales_days,
            confidence_score=calculation.confidence_score,
            data_status=calculation.data_status,
            calculation_version=calculation.calculation_version,
        )

    def _prediction(self, product: Product, inventory: InventoryHistory, velocity) -> object:
        prediction = StockoutPredictionService(repository=SimpleNamespace()).build_prediction(
            product=product,
            seller=self.seller,
            inventory_snapshot=inventory,
            sales_velocity=velocity,
            as_of_date=self.as_of_date,
            calculated_at=self.calculated_at,
            calculation_version="v1",
            confirmed_incoming_quantity=0,
        )
        prediction.id = uuid4()
        return prediction

    def _recommendation(self, product: Product, inventory: InventoryHistory, velocity, prediction) -> object:
        recommendation = ReorderRecommendationService(repository=SimpleNamespace()).build_recommendation(
            product=product,
            seller=self.seller,
            inventory_snapshot=inventory,
            sales_velocity=velocity,
            stockout_prediction=prediction,
            as_of_date=self.as_of_date,
            generated_at=self.calculated_at,
            calculation_version="v1",
            confirmed_incoming_quantity=0,
        )
        recommendation.id = uuid4()
        return recommendation

    def _risk(self, product: Product, prediction, recommendation) -> object:
        assessment = InventoryRiskService(repository=SimpleNamespace()).build_assessment(
            product=product,
            seller=self.seller,
            stockout_prediction=prediction,
            reorder_recommendation=recommendation,
            as_of_date=self.as_of_date,
            assessed_at=self.calculated_at,
            calculation_version="v1",
        )
        assessment.id = uuid4()
        assessment.product = product
        assessment.stockout_prediction = prediction
        assessment.reorder_recommendation = recommendation
        return assessment


if __name__ == "__main__":
    unittest.main()
