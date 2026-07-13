from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.product import Product
from app.models.rag_index_outbox import RagIndexOutbox, RagIndexOutboxStatus
from app.models.rag_memory import RagMemorySourceType
from app.models.seller import Seller
from app.services.rag_index_outbox_service import RagIndexOutboxService


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kwargs) -> str:
    return "JSON"


class RagIndexOutboxServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(
            self.engine,
            tables=[Seller.__table__, Product.__table__, RagIndexOutbox.__table__],
        )
        self.db = Session(self.engine)
        self.seller = Seller(email="outbox@example.com", password_hash="hash")
        self.other_seller = Seller(email="other-outbox@example.com", password_hash="hash")
        self.db.add_all([self.seller, self.other_seller])
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(
            self.engine,
            tables=[RagIndexOutbox.__table__, Product.__table__, Seller.__table__],
        )
        self.engine.dispose()

    def test_enqueue_is_idempotent_for_same_source_version(self) -> None:
        changed_at = datetime(2026, 7, 13, tzinfo=timezone.utc)
        service = RagIndexOutboxService(self.db)
        first = service.enqueue_upsert(
            seller_id=self.seller.id,
            source_type=RagMemorySourceType.PRODUCT_PROFILE,
            source_id="product-1",
            source_updated_at=changed_at,
        )
        self.db.commit()
        duplicate = service.enqueue_upsert(
            seller_id=self.seller.id,
            source_type=RagMemorySourceType.PRODUCT_PROFILE,
            source_id="product-1",
            source_updated_at=changed_at,
        )

        self.assertEqual(first.id, duplicate.id)
        self.assertEqual(
            1,
            self.db.scalar(
                select(func.count()).select_from(RagIndexOutbox).where(RagIndexOutbox.seller_id == self.seller.id)
            ),
        )

    def test_rollback_does_not_leave_an_outbox_event(self) -> None:
        service = RagIndexOutboxService(self.db)
        service.enqueue_upsert(
            seller_id=self.seller.id,
            source_type=RagMemorySourceType.SALES_HISTORY,
            source_id="sale-rollback",
        )
        self.db.rollback()

        self.assertIsNone(
            self.db.scalar(
                select(RagIndexOutbox.id).where(RagIndexOutbox.source_id == "sale-rollback")
            )
        )

    def test_claim_is_seller_scoped_and_retryable(self) -> None:
        service = RagIndexOutboxService(self.db)
        own = service.enqueue_upsert(
            seller_id=self.seller.id,
            source_type=RagMemorySourceType.ALERT,
            source_id="own-alert",
        )
        service.enqueue_upsert(
            seller_id=self.other_seller.id,
            source_type=RagMemorySourceType.ALERT,
            source_id="other-alert",
        )
        self.db.commit()

        claimed = service.claim_batch(batch_size=10, seller_id=self.seller.id, lease_seconds=1)

        self.assertEqual([own.id], [item.id for item in claimed])
        self.assertEqual(RagIndexOutboxStatus.PROCESSING, claimed[0].status)
        self.assertEqual(1, claimed[0].attempts)

        status = service.mark_failed(
            own.id,
            error_code="SOURCE_FAILURE",
            error_summary="Source unavailable",
            max_attempts=5,
            initial_backoff_seconds=1,
            max_backoff_seconds=1,
        )
        self.assertEqual(RagIndexOutboxStatus.FAILED, status)
        failed = self.db.get(RagIndexOutbox, own.id)
        assert failed is not None
        failed.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.db.commit()
        retried = service.claim_batch(batch_size=1, seller_id=self.seller.id, include_failed=True)
        self.assertEqual([own.id], [item.id for item in retried])

    def test_dead_letter_after_attempt_limit(self) -> None:
        service = RagIndexOutboxService(self.db)
        event = service.enqueue_upsert(
            seller_id=self.seller.id,
            source_type=RagMemorySourceType.PROMOTION_RESULT,
            source_id="promotion-result-1",
        )
        self.db.commit()
        service.claim_batch(batch_size=1, seller_id=self.seller.id)

        status = service.mark_failed(
            event.id,
            error_code="FAILED_SOURCE",
            error_summary="failure details are not persisted",
            max_attempts=1,
        )

        self.assertEqual(RagIndexOutboxStatus.DEAD_LETTER, status)
        stored = self.db.get(RagIndexOutbox, event.id)
        assert stored is not None
        self.assertEqual(RagIndexOutboxStatus.DEAD_LETTER, stored.status)
        self.assertLessEqual(len(stored.last_error_summary or ""), 255)


if __name__ == "__main__":
    unittest.main()
