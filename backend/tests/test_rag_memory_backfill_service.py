from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from uuid import uuid4

from app.models.alert import AlertActionType, AlertConfidence, AlertDeliveryStatus, AlertUrgencyLevel
from app.models.competitor_event import CompetitorEventSeverity, CompetitorEventType
from app.models.rag_memory import RagMemoryEmbeddingStatus, RagMemorySourceType
from app.models.recommendation import RecommendationAction, RecommendationConfidence
from app.services.rag_memory_backfill_service import RagMemoryBackfillService


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _ScalarResult(self._rows)


class FakeSession:
    def __init__(self, rows_by_table):
        self.rows_by_table = {key: list(value) for key, value in rows_by_table.items()}
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)
        sql = str(statement)
        for table, batches in sorted(self.rows_by_table.items(), key=lambda item: len(item[0]), reverse=True):
            if table in sql:
                if batches:
                    return _Result(batches.pop(0))
                return _Result([])
        return _Result([])


class FakeRagRepository:
    def __init__(self):
        self.documents = {}
        self.chunks = []
        self.stale_calls = []
        self.soft_delete_calls = []

    def get_by_source(self, *, seller_id, source_table, source_id, source_version=None, content_hash=None, include_deleted=False):
        del seller_id, source_version, content_hash, include_deleted
        return self.documents.get((source_table, source_id))

    def create_memory_document(self, payload):
        key = (payload.source_table, payload.source_id)
        existing = self.documents.get(key)
        if existing and existing.content_hash == payload.content_hash:
            return existing, False
        doc = SimpleNamespace(**payload.model_dump(), id=uuid4())
        self.documents[key] = doc
        return doc, True

    def create_chunks(self, payloads):
        self.chunks.extend(payloads)
        return payloads

    def count_chunks_for_document(self, document_id):
        return len([chunk for chunk in self.chunks if chunk.memory_document_id == document_id])

    def mark_stale(self, *, seller_id, source_table, source_id):
        self.stale_calls.append((seller_id, source_table, source_id))
        existing = self.documents.get((source_table, source_id))
        if existing:
            existing.embedding_status = RagMemoryEmbeddingStatus.STALE
        return 1 if existing else 0

    def soft_delete_by_source(self, *, seller_id, source_table, source_id):
        self.soft_delete_calls.append((seller_id, source_table, source_id))
        self.documents.pop((source_table, source_id), None)
        return 1


def product(*, seller_id=None, product_id=None, title="Product A"):
    return SimpleNamespace(
        id=product_id or uuid4(),
        seller_id=seller_id or uuid4(),
        title=title,
        selling_price=Decimal("470"),
    )


class RagMemoryBackfillServiceTests(unittest.TestCase):
    def test_competitor_adapter_creates_memory_document(self):
        seller_id = uuid4()
        product_id = uuid4()
        row = SimpleNamespace(
            id=uuid4(),
            seller_id=seller_id,
            product_id=product_id,
            competitor_id=uuid4(),
            scrape_run_id=uuid4(),
            previous_snapshot_id=None,
            current_snapshot_id=None,
            event_type=CompetitorEventType.PRICE_DROP,
            old_value={"price": Decimal("500")},
            new_value={"price": Decimal("450")},
            price_change_amount=Decimal("50"),
            price_change_percent=Decimal("10"),
            severity=CompetitorEventSeverity.HIGH,
            detected_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
            product=product(seller_id=seller_id, product_id=product_id),
            competitor=SimpleNamespace(competitor_title="Competitor X"),
            market_opportunity=SimpleNamespace(id=uuid4(), opportunity_score=Decimal("88"), recommended_action="PRICE_RAISE"),
        )
        repo = FakeRagRepository()

        result = RagMemoryBackfillService(
            FakeSession({"competitor_events": [[row], []]}),
            repository=repo,
        ).backfill(seller_id=seller_id, source_type=RagMemorySourceType.COMPETITOR_HISTORY)

        self.assertEqual(1, result.created_count)
        document = next(iter(repo.documents.values()))
        self.assertEqual(seller_id, document.seller_id)
        self.assertEqual(product_id, document.product_id)
        self.assertIn("Opportunity score: 88", document.content_text)
        self.assertEqual(1, len(repo.chunks))

    def test_price_inventory_recommendation_and_alert_adapters_create_documents(self):
        seller_id = uuid4()
        product_id = uuid4()
        item = product(seller_id=seller_id, product_id=product_id)
        rows_by_source = {
            RagMemorySourceType.PRICE_HISTORY: (
                "dynamic_pricing_recommendations",
                SimpleNamespace(
                    id=uuid4(),
                    seller_id=seller_id,
                    product_id=product_id,
                    pricing_analytics_id=uuid4(),
                    elasticity_estimate_id=None,
                    action="PRICE_RAISE",
                    current_price=Decimal("450"),
                    recommended_price=Decimal("470"),
                    minimum_safe_price=Decimal("390"),
                    expected_revenue=Decimal("9000"),
                    expected_profit=Decimal("2300"),
                    revenue_impact=Decimal("100"),
                    profit_impact=Decimal("200"),
                    margin_rate=Decimal("0.25"),
                    confidence_score=Decimal("80"),
                    recommendation_status="OPEN",
                    objective="MAXIMIZE_EXPECTED_PROFIT",
                    estimation_method="CONSERVATIVE_HEURISTIC",
                    formula_version="v1",
                    generated_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
                    created_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
                    product=item,
                ),
            ),
            RagMemorySourceType.INVENTORY_HISTORY: (
                "inventory_history",
                SimpleNamespace(
                    id=uuid4(),
                    seller_id=seller_id,
                    product_id=product_id,
                    snapshot_date=datetime(2026, 7, 5, tzinfo=timezone.utc).date(),
                    captured_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
                    quantity_on_hand=20,
                    quantity_reserved=3,
                    quantity_available=17,
                    quantity_incoming=0,
                    source="DAILY_SNAPSHOT",
                    product=item,
                ),
            ),
            RagMemorySourceType.RECOMMENDATION: (
                "recommendations",
                SimpleNamespace(
                    id=uuid4(),
                    product_id=product_id,
                    product=item,
                    action=RecommendationAction.LOWER,
                    confidence=RecommendationConfidence.HIGH,
                    reasoning_bn="Lower price carefully.",
                    suggested_price_min=Decimal("430"),
                    suggested_price_max=Decimal("440"),
                    revenue_opportunity=Decimal("500"),
                    created_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
                ),
            ),
            RagMemorySourceType.ALERT: (
                "alerts",
                SimpleNamespace(
                    id=uuid4(),
                    seller_id=seller_id,
                    product_id=product_id,
                    recommendation_id=None,
                    alert_type="inventory_risk",
                    urgency_level=AlertUrgencyLevel.HIGH,
                    action_type=AlertActionType.STOCK_WARNING,
                    confidence=AlertConfidence.HIGH,
                    delivery_status=AlertDeliveryStatus.pending,
                    payload={},
                    created_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
                    product=item,
                ),
            ),
        }

        for source_type, (table, row) in rows_by_source.items():
            with self.subTest(source_type=source_type):
                repo = FakeRagRepository()
                result = RagMemoryBackfillService(
                    FakeSession({table: [[row], []]}),
                    repository=repo,
                ).backfill(seller_id=seller_id, source_type=source_type)
                self.assertEqual(1, result.created_count)
                self.assertEqual(1, len(repo.documents))
                self.assertEqual(1, len(repo.chunks))

    def test_idempotent_backfill_and_updated_source_reindexes(self):
        seller_id = uuid4()
        product_id = uuid4()
        row = SimpleNamespace(
            id=uuid4(),
            seller_id=seller_id,
            product_id=product_id,
            recommendation_id=None,
            alert_type="inventory_risk",
            urgency_level=AlertUrgencyLevel.HIGH,
            action_type=AlertActionType.STOCK_WARNING,
            confidence=AlertConfidence.HIGH,
            delivery_status=AlertDeliveryStatus.pending,
            payload={},
            created_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
            product=product(seller_id=seller_id, product_id=product_id),
        )
        repo = FakeRagRepository()
        service = RagMemoryBackfillService(FakeSession({"alerts": [[row], []]}), repository=repo)

        first = service.backfill(seller_id=seller_id, source_type=RagMemorySourceType.ALERT)
        second = RagMemoryBackfillService(FakeSession({"alerts": [[row], []]}), repository=repo).backfill(
            seller_id=seller_id,
            source_type=RagMemorySourceType.ALERT,
        )
        row.urgency_level = AlertUrgencyLevel.CRITICAL
        third = RagMemoryBackfillService(FakeSession({"alerts": [[row], []]}), repository=repo).backfill(
            seller_id=seller_id,
            source_type=RagMemorySourceType.ALERT,
        )

        self.assertEqual(1, first.created_count)
        self.assertEqual(1, second.skipped_count)
        self.assertEqual(1, third.updated_count)
        self.assertEqual(1, third.soft_deleted_count)
        self.assertEqual(2, len(repo.chunks))

    def test_retry_repairs_existing_document_without_chunks(self):
        seller_id = uuid4()
        product_id = uuid4()
        row = SimpleNamespace(
            id=uuid4(),
            seller_id=seller_id,
            product_id=product_id,
            recommendation_id=None,
            alert_type="inventory_risk",
            urgency_level=AlertUrgencyLevel.HIGH,
            action_type=AlertActionType.STOCK_WARNING,
            confidence=AlertConfidence.HIGH,
            delivery_status=AlertDeliveryStatus.pending,
            payload={},
            created_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
            product=product(seller_id=seller_id, product_id=product_id),
        )
        repo = FakeRagRepository()
        first = RagMemoryBackfillService(FakeSession({"alerts": [[row], []]}), repository=repo).backfill(
            seller_id=seller_id,
            source_type=RagMemorySourceType.ALERT,
        )
        repo.chunks.clear()

        second = RagMemoryBackfillService(FakeSession({"alerts": [[row], []]}), repository=repo).backfill(
            seller_id=seller_id,
            source_type=RagMemorySourceType.ALERT,
        )

        self.assertEqual(1, first.created_count)
        self.assertEqual(1, second.skipped_count)
        self.assertEqual(1, len(repo.chunks))

    def test_failed_source_does_not_stop_entire_batch(self):
        seller_id = uuid4()
        product_id = uuid4()
        bad = SimpleNamespace(id=uuid4(), fail=True)
        good = SimpleNamespace(
            id=uuid4(),
            seller_id=seller_id,
            product_id=product_id,
            recommendation_id=None,
            alert_type="inventory_risk",
            urgency_level=AlertUrgencyLevel.HIGH,
            action_type=AlertActionType.STOCK_WARNING,
            confidence=AlertConfidence.HIGH,
            delivery_status=AlertDeliveryStatus.pending,
            payload={},
            created_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
            product=product(seller_id=seller_id, product_id=product_id),
        )

        class Builder:
            def build_from_alert(self, row):
                if getattr(row, "fail", False):
                    raise RuntimeError("bad source")
                from app.services.rag_memory_document_builder import RagMemoryDocumentBuilder

                return RagMemoryDocumentBuilder().build_from_alert(row)

            def build_from_telegram_inventory_alert(self, row):
                from app.services.rag_memory_document_builder import RagMemoryDocumentBuilder

                return RagMemoryDocumentBuilder().build_from_telegram_inventory_alert(row)

        repo = FakeRagRepository()

        result = RagMemoryBackfillService(
            FakeSession({"alerts": [[bad, good], []], "telegram_inventory_alerts": [[], []]}),
            repository=repo,
            builder=Builder(),
        ).backfill(seller_id=seller_id, source_type=RagMemorySourceType.ALERT)

        self.assertEqual(1, result.created_count)
        self.assertEqual(1, result.failed_count)
        self.assertEqual(1, len(repo.documents))

    def test_recommendation_adapter_includes_reorder_and_dead_stock_recommendations(self):
        seller_id = uuid4()
        product_id = uuid4()
        item = product(seller_id=seller_id, product_id=product_id)
        reorder = SimpleNamespace(
            id=uuid4(),
            seller_id=seller_id,
            product_id=product_id,
            product=item,
            inventory_snapshot_id=None,
            sales_velocity_id=None,
            stockout_prediction_id=None,
            action="REORDER",
            recommended_quantity=50,
            reorder_deadline=datetime(2026, 7, 8, tzinfo=timezone.utc).date(),
            supplier_lead_time_days=8,
            daily_sales_rate=Decimal("3.4"),
            confidence_score=Decimal("78"),
            recommendation_status="OPEN",
            explanation="Stock coverage is short.",
            calculation_version="v1",
            generated_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
        )
        dead_stock = SimpleNamespace(
            id=uuid4(),
            seller_id=seller_id,
            product_id=product_id,
            product=item,
            dead_stock_assessment_id=uuid4(),
            primary_action="FLASH_SALE",
            secondary_actions=["SEO_FIX"],
            recommended_discount_rate=Decimal("0.10"),
            recommended_price=Decimal("405"),
            suggested_duration_days=3,
            recommended_quantity=10,
            confidence_score=Decimal("66"),
            recommendation_status="OPEN",
            explanation="Dead stock recovery is available.",
            calculation_version="v1",
            generated_at=datetime(2026, 7, 6, tzinfo=timezone.utc),
        )
        repo = FakeRagRepository()

        result = RagMemoryBackfillService(
            FakeSession(
                {
                    "recommendations": [[], []],
                    "reorder_recommendations": [[reorder], []],
                    "dead_stock_recovery_recommendations": [[dead_stock], []],
                }
            ),
            repository=repo,
        ).backfill(seller_id=seller_id, source_type=RagMemorySourceType.RECOMMENDATION)

        self.assertEqual(2, result.created_count)
        tables = {document.source_table for document in repo.documents.values()}
        self.assertEqual({"reorder_recommendations", "dead_stock_recovery_recommendations"}, tables)

    def test_date_product_filters_batching_and_dry_run(self):
        seller_id = uuid4()
        product_id = uuid4()
        session = FakeSession({"alerts": [[], []], "telegram_inventory_alerts": [[], []]})

        result = RagMemoryBackfillService(session, repository=FakeRagRepository()).backfill(
            seller_id=seller_id,
            product_id=product_id,
            source_type=RagMemorySourceType.ALERT,
            from_date=datetime(2026, 7, 1, tzinfo=timezone.utc),
            to_date=datetime(2026, 7, 31, tzinfo=timezone.utc),
            batch_size=1,
            dry_run=True,
        )

        self.assertEqual(0, result.created_count)
        sql = "\n".join(str(statement) for statement in session.statements)
        self.assertIn("alerts.seller_id", sql)
        self.assertIn("alerts.product_id", sql)
        self.assertIn("alerts.created_at", sql)

    def test_source_deletion_and_unsupported_source_are_handled_safely(self):
        seller_id = uuid4()
        repo = FakeRagRepository()
        service = RagMemoryBackfillService(FakeSession({}), repository=repo)

        deleted = service.soft_delete_source(seller_id=seller_id, source_table="alerts", source_id="missing")
        result = service.backfill(source_type=RagMemorySourceType.ACTION_CENTER)
        invalid = service.backfill(source_type="NOT_A_SOURCE")

        self.assertEqual(1, deleted)
        self.assertEqual(1, result.unsupported_count)
        self.assertEqual(1, invalid.unsupported_count)


if __name__ == "__main__":
    unittest.main()
