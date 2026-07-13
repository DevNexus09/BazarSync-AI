from __future__ import annotations

import unittest
from unittest.mock import patch
from uuid import uuid4

from app.models.rag_memory import RagMemorySourceType
from app.tasks import rag_memory_tasks as tasks


class FakeSession:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeBackfillResult:
    created_count = 2
    skipped_count = 3
    updated_count = 1
    failed_count = 0
    dry_run_count = 0
    soft_deleted_count = 0
    unsupported_count = 0


class FakeEmbedResult:
    embedded_count = 4
    failed_count = 1
    dimension = 7
    model = "BAAI/test-bge"


class RagMemoryTaskTests(unittest.TestCase):
    def test_requested_task_names_are_registered(self):
        self.assertEqual("rag_backfill_memory", tasks.rag_backfill_memory.name)
        self.assertEqual("rag_embed_pending_chunks", tasks.rag_embed_pending_chunks.name)
        self.assertEqual("rag_reindex_source_record", tasks.rag_reindex_source_record.name)
        self.assertEqual("rag_full_reindex_for_seller", tasks.rag_full_reindex_for_seller.name)

    def test_backfill_task_passes_scope_and_returns_counts(self):
        seller_id = str(uuid4())
        product_id = str(uuid4())
        captured = {}
        session = FakeSession()

        class BackfillService:
            def __init__(self, db, *, log):
                self.db = db
                self.log = log

            def backfill(self, **kwargs):
                captured.update(kwargs)
                return FakeBackfillResult()

        with (
            patch.object(tasks, "SessionLocal", return_value=session),
            patch.object(tasks, "_try_advisory_lock", return_value=True),
            patch.object(tasks, "_release_advisory_lock"),
            patch.object(tasks, "RagMemoryBackfillService", BackfillService),
        ):
            result = tasks.rag_backfill_memory.run(
                seller_id=seller_id,
                product_id=product_id,
                source_type="ALERT",
                from_date="2026-07-01T00:00:00+00:00",
                to_date="2026-07-31T00:00:00+00:00",
                batch_size=25,
            )

        self.assertEqual(2, result["created_count"])
        self.assertEqual(3, result["skipped_count"])
        self.assertEqual(25, captured["batch_size"])
        self.assertEqual(RagMemorySourceType.ALERT, captured["source_type"])
        self.assertTrue(session.closed)

    def test_locked_backfill_is_skipped_without_running_service(self):
        with (
            patch.object(tasks, "SessionLocal", return_value=FakeSession()),
            patch.object(tasks, "_try_advisory_lock", return_value=False),
            patch.object(tasks, "_release_advisory_lock"),
            patch.object(tasks.RagMemoryBackfillService, "backfill", side_effect=AssertionError("should not run")),
        ):
            result = tasks.rag_backfill_memory.run(seller_id=str(uuid4()))

        self.assertEqual("locked", result["skipped_reason"])
        self.assertEqual(0, result["created_count"])

    def test_embed_pending_chunks_uses_batch_size_and_source_filter(self):
        seller_id = str(uuid4())
        captured = {}

        class EmbeddingService:
            def embed_pending_chunks(self, *, repository, seller_id, source_type, limit):
                del repository
                captured.update(seller_id=seller_id, source_type=source_type, limit=limit)
                return FakeEmbedResult()

        class Repository:
            def __init__(self, session):
                del session

            def count_searchable_chunks(self, *, seller_id, source_type):
                captured["count_scope"] = (seller_id, source_type)
                return 9

        with (
            patch.object(tasks, "SessionLocal", return_value=FakeSession()),
            patch.object(tasks, "_try_advisory_lock", return_value=True),
            patch.object(tasks, "_release_advisory_lock"),
            patch.object(tasks, "_get_embedding_service", return_value=EmbeddingService()),
            patch.object(tasks, "RagMemoryRepository", Repository),
        ):
            result = tasks.rag_embed_pending_chunks.run(
                seller_id=seller_id,
                source_type="ALERT",
                batch_size=12,
            )

        self.assertEqual(4, result["embedded_count"])
        self.assertEqual(1, result["failed_count"])
        self.assertEqual(12, captured["limit"])
        self.assertEqual(RagMemorySourceType.ALERT, captured["source_type"])
        self.assertEqual(9, result["searchable_count"])

    def test_reindex_source_record_is_scoped_and_idempotent(self):
        seller_id = str(uuid4())
        source_id = str(uuid4())
        captured = {}

        class BackfillService:
            def __init__(self, db, *, log):
                del db, log

            def reindex_source_record(self, **kwargs):
                captured.update(kwargs)
                return FakeBackfillResult()

        with (
            patch.object(tasks, "SessionLocal", return_value=FakeSession()),
            patch.object(tasks, "_try_advisory_lock", return_value=True),
            patch.object(tasks, "_release_advisory_lock"),
            patch.object(tasks, "RagMemoryBackfillService", BackfillService),
        ):
            result = tasks.rag_reindex_source_record.run(
                seller_id=seller_id,
                source_type="ALERT",
                source_id=source_id,
            )

        self.assertEqual(2, result["created_count"])
        self.assertEqual(source_id, captured["source_id"])
        self.assertEqual(RagMemorySourceType.ALERT, captured["source_type"])

    def test_full_reindex_combines_backfill_embedding_and_verification_counts(self):
        seller_id = str(uuid4())

        class BackfillService:
            def __init__(self, db, *, log):
                del db, log

            def backfill(self, **kwargs):
                self.kwargs = kwargs
                return FakeBackfillResult()

        class EmbeddingService:
            def embed_pending_chunks(self, *, repository, seller_id, source_type, limit):
                del repository, seller_id, source_type, limit
                return FakeEmbedResult()

        class Repository:
            def __init__(self, session):
                del session

            def count_searchable_chunks(self, *, seller_id, source_type):
                del seller_id, source_type
                return 11

        with (
            patch.object(tasks, "SessionLocal", return_value=FakeSession()),
            patch.object(tasks, "_try_advisory_lock", return_value=True),
            patch.object(tasks, "_release_advisory_lock"),
            patch.object(tasks, "RagMemoryBackfillService", BackfillService),
            patch.object(tasks, "_get_embedding_service", return_value=EmbeddingService()),
            patch.object(tasks, "RagMemoryRepository", Repository),
        ):
            result = tasks.rag_full_reindex_for_seller.run(
                seller_id=seller_id,
                source_type="ALERT",
                batch_size=50,
            )

        self.assertEqual(2, result["created_count"])
        self.assertEqual(4, result["embedded_count"])
        self.assertEqual(1, result["failed_count"])
        self.assertEqual(11, result["searchable_count"])

    def test_enqueue_full_reindex_chain_keeps_task_arguments_isolated(self):
        seller_id = str(uuid4())

        class Workflow:
            def __init__(self, *signatures):
                self.signatures = signatures
                self.applied = False

            def apply_async(self):
                self.applied = True
                return self

        captured = {}

        def fake_chain(*signatures):
            workflow = Workflow(*signatures)
            captured["workflow"] = workflow
            return workflow

        with patch.object(tasks, "chain", fake_chain):
            workflow = tasks.enqueue_rag_full_reindex_for_seller(
                seller_id=seller_id,
                source_type="ALERT",
                batch_size=10,
            )

        self.assertTrue(workflow.applied)
        self.assertEqual(
            ["rag_backfill_memory", "rag_embed_pending_chunks"],
            [signature.task for signature in captured["workflow"].signatures],
        )
        self.assertTrue(captured["workflow"].signatures[1].immutable)


if __name__ == "__main__":
    unittest.main()
