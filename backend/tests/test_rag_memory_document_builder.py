from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from uuid import uuid4

from app.models.alert import AlertActionType, AlertConfidence, AlertDeliveryStatus, AlertUrgencyLevel
from app.models.competitor_event import CompetitorEventSeverity, CompetitorEventType
from app.models.rag_memory import RagMemorySourceType
from app.models.recommendation import RecommendationAction, RecommendationConfidence
from app.services.rag_memory_document_builder import RagMemoryBuildError, RagMemoryDocumentBuilder


def product(*, seller_id=None, product_id=None, title="Product A", price=Decimal("470.00")):
    return SimpleNamespace(
        id=product_id or uuid4(),
        seller_id=seller_id or uuid4(),
        title=title,
        selling_price=price,
    )


class RagMemoryDocumentBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = RagMemoryDocumentBuilder()

    def test_competitor_document_text_is_deterministic_and_preserves_scope(self):
        seller_id = uuid4()
        product_id = uuid4()
        competitor_id = uuid4()
        event = SimpleNamespace(
            id=uuid4(),
            seller_id=seller_id,
            product_id=product_id,
            competitor_id=competitor_id,
            scrape_run_id=uuid4(),
            previous_snapshot_id=uuid4(),
            current_snapshot_id=uuid4(),
            event_type=CompetitorEventType.PRICE_DROP,
            old_value={"price": Decimal("500.00")},
            new_value={"price": Decimal("450.00")},
            price_change_amount=Decimal("50.00"),
            price_change_percent=Decimal("10.00"),
            severity=CompetitorEventSeverity.HIGH,
            detected_at=datetime(2026, 7, 5, 9, tzinfo=timezone.utc),
            product=product(seller_id=seller_id, product_id=product_id),
            competitor=SimpleNamespace(competitor_title="Competitor X"),
        )

        first = self.builder.build_from_competitor_event(event)
        second = self.builder.build_from_competitor_event(event)

        self.assertEqual(first, second)
        self.assertEqual(seller_id, first.seller_id)
        self.assertEqual(product_id, first.product_id)
        self.assertEqual(RagMemorySourceType.COMPETITOR_HISTORY, first.source_type)
        self.assertIn("Competitor price changed from BDT 500 to BDT 450", first.content_text)
        self.assertIn("Seller product price at the time: BDT 470", first.content_text)

    def test_sensitive_fields_and_raw_html_are_excluded(self):
        seller_id = uuid4()
        product_id = uuid4()
        alert = SimpleNamespace(
            id=uuid4(),
            seller_id=seller_id,
            product_id=product_id,
            recommendation_id=uuid4(),
            alert_type="<b>stock_warning</b>",
            urgency_level=AlertUrgencyLevel.CRITICAL,
            action_type=AlertActionType.REORDER,
            confidence=AlertConfidence.HIGH,
            delivery_status=AlertDeliveryStatus.failed,
            telegram_chat_id="123456789",
            delivery_error="Traceback (most recent call last): secret token=abc",
            payload={"api_key": "secret", "safe_metric": "kept"},
            created_at=datetime(2026, 7, 5, 10, tzinfo=timezone.utc),
            product=product(seller_id=seller_id, product_id=product_id, title="<i>Product A</i>"),
        )

        document = self.builder.build_from_alert(alert)

        self.assertNotIn("<b>", document.content_text)
        self.assertNotIn("<i>", document.content_text)
        self.assertNotIn("telegram_chat_id", str(document.metadata_json))
        self.assertNotIn("api_key", str(document.metadata_json))
        self.assertNotIn("Traceback", document.content_text)
        self.assertEqual("kept", document.metadata_json.get("payload", {}).get("safe_metric"))

    def test_content_hash_changes_for_business_content_not_irrelevant_metadata(self):
        seller_id = uuid4()
        product_id = uuid4()
        created_at = datetime(2026, 7, 5, 10, tzinfo=timezone.utc)
        base = {
            "id": uuid4(),
            "seller_id": seller_id,
            "product_id": product_id,
            "recommendation_id": None,
            "alert_type": "inventory_risk",
            "urgency_level": AlertUrgencyLevel.HIGH,
            "action_type": AlertActionType.STOCK_WARNING,
            "confidence": AlertConfidence.HIGH,
            "delivery_status": AlertDeliveryStatus.pending,
            "created_at": created_at,
            "product": product(seller_id=seller_id, product_id=product_id),
        }
        first = self.builder.build_from_alert(SimpleNamespace(**base, telegram_chat_id="111"))
        second = self.builder.build_from_alert(SimpleNamespace(**base, telegram_chat_id="222"))
        changed = self.builder.build_from_alert(
            SimpleNamespace(**{**base, "urgency_level": AlertUrgencyLevel.CRITICAL})
        )

        self.assertEqual(first.content_hash, second.content_hash)
        self.assertNotEqual(first.content_hash, changed.content_hash)

    def test_inventory_document_combines_snapshot_risk_velocity_and_stockout(self):
        seller_id = uuid4()
        product_id = uuid4()
        snapshot = SimpleNamespace(
            id=uuid4(),
            seller_id=seller_id,
            product_id=product_id,
            snapshot_date=datetime(2026, 7, 5, tzinfo=timezone.utc).date(),
            captured_at=datetime(2026, 7, 5, 6, tzinfo=timezone.utc),
            quantity_on_hand=20,
            quantity_reserved=3,
            quantity_available=17,
            quantity_incoming=0,
            source="DAILY_SNAPSHOT",
            product=product(seller_id=seller_id, product_id=product_id),
        )
        risk = SimpleNamespace(id=uuid4(), risk_level="CRITICAL")
        velocity = SimpleNamespace(id=uuid4(), daily_sales_rate=Decimal("3.40"))
        stockout = SimpleNamespace(id=uuid4(), days_remaining=Decimal("5.00"))

        document = self.builder.build_from_inventory_snapshot_or_risk(
            snapshot,
            risk_assessment=risk,
            sales_velocity=velocity,
            stockout_prediction=stockout,
        )

        self.assertIn("17 units available", document.content_text)
        self.assertIn("Sales velocity was 3.4 units/day", document.content_text)
        self.assertIn("Predicted stockout was 5 days", document.content_text)
        self.assertIn("Inventory risk: CRITICAL", document.content_text)

    def test_recommendation_customer_private_fields_are_redacted(self):
        owner_product = product()
        recommendation = SimpleNamespace(
            id=uuid4(),
            product_id=owner_product.id,
            product=owner_product,
            action=RecommendationAction.LOWER,
            confidence=RecommendationConfidence.HIGH,
            reasoning_bn="Customer email buyer@example.com and phone +880 1711 222333 should not appear.",
            suggested_price_min=Decimal("300"),
            suggested_price_max=Decimal("320"),
            revenue_opportunity=Decimal("1000"),
            created_at=datetime(2026, 7, 5, 10, tzinfo=timezone.utc),
        )

        document = self.builder.build_from_recommendation(recommendation)

        self.assertNotIn("buyer@example.com", document.content_text)
        self.assertNotIn("+880 1711 222333", document.content_text)
        self.assertIn("[REDACTED_EMAIL]", document.content_text)
        self.assertIn("[REDACTED_PHONE]", document.content_text)

    def test_unsupported_generic_source_type_fails_safely(self):
        with self.assertRaises(RagMemoryBuildError):
            self.builder.build_generic_from_registered_source(
                source_type=RagMemorySourceType.DEAD_STOCK,
                source={"seller_id": uuid4(), "id": uuid4()},
            )

    def test_promotion_result_builder(self):
        seller_id = uuid4()
        product_id = uuid4()

        document = self.builder.build_from_promotion_result(
            {
                "id": "promo-1",
                "seller_id": seller_id,
                "product_id": product_id,
                "product_name": "Product A",
                "promotion_name": "July sale",
                "started_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
                "ended_at": datetime(2026, 7, 5, tzinfo=timezone.utc),
                "units_sold": 12,
                "gross_revenue": Decimal("5400"),
                "estimated_profit": Decimal("1200"),
                "result_status": "CALCULATED",
                "customer_message": "private message",
            }
        )

        self.assertEqual(seller_id, document.seller_id)
        self.assertEqual(product_id, document.product_id)
        self.assertEqual(RagMemorySourceType.PROMOTION_RESULT, document.source_type)
        self.assertIn("July sale", document.content_text)
        self.assertNotIn("private message", str(document.metadata_json))

    def test_promotion_plan_builder(self):
        seller_id = uuid4()
        product_id = uuid4()

        document = self.builder.build_from_promotion_plan(
            {
                "id": "plan-1",
                "seller_id": seller_id,
                "product_id": product_id,
                "product_name": "Product A",
                "title": "July plan",
                "promotion_type": "DISCOUNT",
                "status": "APPROVED",
                "proposed_discount_rate": Decimal("0.10"),
                "created_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
            }
        )

        self.assertEqual(RagMemorySourceType.PROMOTION_PLAN, document.source_type)
        self.assertIn("marketplace execution is not implemented", document.content_text.lower())

    def test_seller_price_history_builder_labels_baseline(self):
        seller_id = uuid4()
        product_id = uuid4()

        document = self.builder.build_from_seller_price_history(
            {
                "id": "price-1",
                "seller_id": seller_id,
                "product_id": product_id,
                "new_price": Decimal("99.00"),
                "currency": "BDT",
                "source": "BASELINE_CURRENT_PRICE",
                "changed_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
            }
        )

        self.assertEqual(RagMemorySourceType.SELLER_PRICE_HISTORY, document.source_type)
        self.assertTrue(document.metadata_json["baseline_not_historical_change"])

    def test_new_business_source_builders_create_documents(self):
        seller_id = uuid4()
        product_id = uuid4()
        item = product(seller_id=seller_id, product_id=product_id, title="Catalog Product")
        item.category = "Electronics"
        item.specifications = {"sku": "SKU-1"}
        item.cost_price = Decimal("200")
        item.stock_quantity = 5
        item.created_at = datetime(2026, 7, 1, tzinfo=timezone.utc)

        sale = SimpleNamespace(
            id=uuid4(),
            seller_id=seller_id,
            product_id=product_id,
            product=item,
            sold_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
            quantity_sold=2,
            returned_units=0,
            refunded_restocked_units=0,
            unit_price=Decimal("450"),
            line_total=None,
            status="COMPLETED",
            is_test_order=False,
        )
        visibility = SimpleNamespace(
            id=uuid4(),
            seller_id=seller_id,
            product_id=product_id,
            product=item,
            metric_date=datetime(2026, 7, 5, tzinfo=timezone.utc).date(),
            impressions=100,
            views=20,
            clicks=4,
            search_rank=3,
            listing_quality_score=Decimal("82"),
        )

        product_doc = self.builder.build_from_product_profile(item)
        sale_doc = self.builder.build_from_sales_record(sale)
        visibility_doc = self.builder.build_from_visibility_metric(visibility)

        self.assertEqual(RagMemorySourceType.PRODUCT_PROFILE, product_doc.source_type)
        self.assertEqual(RagMemorySourceType.SALES_HISTORY, sale_doc.source_type)
        self.assertEqual(RagMemorySourceType.SEO_VISIBILITY_HISTORY, visibility_doc.source_type)
        self.assertIn("SKU-1", product_doc.content_text)
        self.assertIn("Revenue contribution: BDT 900", sale_doc.content_text)
        self.assertIn("CTR 0.2", visibility_doc.content_text)

    def test_sales_record_document_uses_persisted_line_total_when_available(self):
        seller_id = uuid4()
        product_id = uuid4()
        item = product(seller_id=seller_id, product_id=product_id)
        sale = SimpleNamespace(
            id=uuid4(),
            seller_id=seller_id,
            product_id=product_id,
            product=item,
            sold_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
            quantity_sold=2,
            returned_units=0,
            refunded_restocked_units=0,
            unit_price=None,
            line_total=Decimal("875.50"),
            price_source="IMPORTED_TRANSACTION",
            status="COMPLETED",
            is_test_order=False,
        )

        document = self.builder.build_from_sales_record(sale)

        self.assertIn("Transaction unit price: unavailable", document.content_text)
        self.assertIn("Revenue contribution: BDT 875.5", document.content_text)
        self.assertEqual("875.5", document.metadata_json["revenue"])

    def test_sales_summary_document_includes_completeness_status(self):
        seller_id = uuid4()

        document = self.builder.build_from_sales_revenue_summary(
            {
                "id": "summary-1",
                "seller_id": seller_id,
                "from_date": datetime(2026, 7, 1, tzinfo=timezone.utc).date(),
                "to_date": datetime(2026, 7, 5, tzinfo=timezone.utc).date(),
                "revenue": None,
                "units_sold": 0,
                "order_count": 0,
                "trend": "not_calculated",
                "top_products": "not_calculated",
                "missing_data": "SALES_COMPLETENESS_UNKNOWN_OR_PARTIAL",
                "completeness_status": "UNKNOWN",
            }
        )

        self.assertIn("Sales completeness: UNKNOWN", document.content_text)
        self.assertEqual("UNKNOWN", document.metadata_json["completeness_status"])

    def test_copilot_history_redacts_sensitive_content(self):
        seller_id = uuid4()
        message = SimpleNamespace(
            id=uuid4(),
            seller_id=seller_id,
            product_id=None,
            conversation_id=uuid4(),
            role="ASSISTANT",
            content="Answer included token=secret and customer buyer@example.com",
            answer_confidence="HIGH",
            created_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
        )

        document = self.builder.build_from_copilot_history(message)

        self.assertEqual(RagMemorySourceType.COPILOT_HISTORY, document.source_type)
        self.assertNotIn("secret", document.content_text)
        self.assertNotIn("buyer@example.com", document.content_text)


if __name__ == "__main__":
    unittest.main()
