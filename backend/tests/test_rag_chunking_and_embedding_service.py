from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from uuid import uuid4

from app.models.rag_memory import RagMemoryEmbeddingStatus, RagMemorySourceType
from app.services.rag_chunking_service import RagChunkingService
from app.services.rag_embedding_service import RagEmbeddingError, RagEmbeddingService


class FakeBackend:
    def __init__(self, *, dimension: int = 5, fail: bool = False) -> None:
        self.dimension = dimension
        self.fail = fail
        self.calls: list[tuple[list[str], bool]] = []

    def encode(self, texts: list[str], *, normalize_embeddings: bool):
        self.calls.append((texts, normalize_embeddings))
        if self.fail:
            raise RuntimeError("embedding failed api_key=secret-token")
        return [[float(index + 1) for index in range(self.dimension)] for _ in texts]


class FakeEmbeddingRepository:
    def __init__(self, chunks) -> None:
        self.chunks = chunks
        self.embedded_updates = []
        self.failed_updates = []
        self.document_updates = []

    def find_unembedded_chunks(self, *, seller_id=None, source_type=None, limit=100):
        del seller_id, source_type
        return self.chunks[:limit]

    def mark_chunks_embedded(self, *, updates):
        self.embedded_updates.extend(updates)
        return len(updates)

    def mark_chunks_failed(self, *, chunk_ids, failure_reason):
        self.failed_updates.append((list(chunk_ids), failure_reason))
        return len(chunk_ids)

    def update_document_embedding_statuses(self, *, document_ids):
        self.document_updates.extend(document_ids)
        return len(document_ids)


def document(content: str, *, seller_id=None, product_id=None):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=seller_id or uuid4(),
        product_id=product_id or uuid4(),
        source_type=RagMemorySourceType.PRODUCT_PROFILE,
        source_table="products",
        source_id=str(uuid4()),
        source_version="product_profile_v1",
        title="Product A",
        metadata_json={"source_table": "products", "safe": "yes"},
        event_time=datetime(2026, 7, 5, tzinfo=timezone.utc),
        content_hash="a" * 64,
        chunking_version="v1",
        content_text=content,
    )


def chunk(text: str, *, seller_id=None, document_id=None):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=seller_id or uuid4(),
        memory_document_id=document_id or uuid4(),
        chunk_text=text,
    )


class RagChunkingAndEmbeddingServiceTests(unittest.TestCase):
    def test_embedding_vector_dimension_stored_correctly_and_batch_works(self):
        backend = FakeBackend(dimension=7)
        service = RagEmbeddingService(
            backend=backend,
            model_name="BAAI/test-bge",
            batch_size=2,
            normalize=True,
            embedding_version="v-test",
        )
        chunks = [chunk("first chunk"), chunk("second chunk")]
        repo = FakeEmbeddingRepository(chunks)

        result = service.embed_pending_chunks(repository=repo)

        self.assertEqual(2, result.embedded_count)
        self.assertEqual(7, result.dimension)
        self.assertEqual(1, len(backend.calls))
        self.assertTrue(backend.calls[0][1])
        for update in repo.embedded_updates:
            _, vector, model, dimension, version, _ = update
            self.assertEqual(7, len(vector))
            self.assertEqual(7, dimension)
            self.assertEqual("BAAI/test-bge", model)
            self.assertEqual("v-test", version)

    def test_failed_embedding_marks_status_with_sanitized_reason(self):
        backend = FakeBackend(fail=True)
        service = RagEmbeddingService(backend=backend, batch_size=2)
        chunks = [chunk("first chunk"), chunk("second chunk")]
        repo = FakeEmbeddingRepository(chunks)

        result = service.embed_pending_chunks(repository=repo)

        self.assertEqual(0, result.embedded_count)
        self.assertEqual(2, result.failed_count)
        self.assertEqual([item.id for item in chunks], repo.failed_updates[0][0])
        self.assertIn("[REDACTED]", repo.failed_updates[0][1])
        self.assertNotIn("secret-token", repo.failed_updates[0][1])

    def test_empty_text_rejected(self):
        service = RagEmbeddingService(backend=FakeBackend())

        with self.assertRaises(RagEmbeddingError):
            service.embed_text("  ")

    def test_model_config_respected_and_health_check_uses_backend(self):
        service = RagEmbeddingService(
            provider="local_bge",
            model_name="BAAI/custom-bge",
            device="cpu",
            normalize=False,
            backend=FakeBackend(dimension=3),
        )

        health = service.health_check()

        self.assertEqual("BAAI/custom-bge", health["model"])
        self.assertEqual("cpu", health["device"])
        self.assertFalse(health["normalize"])
        self.assertEqual(3, health["dimension"])

    def test_deterministic_chunking_overlap_and_metadata_preserved(self):
        text = (
            "Price BDT 500 stayed intact. Inventory had 17 units available. "
            "Sales velocity was 3.4 units per day. Recommendation was HOLD. "
            "Risk level was HIGH."
        )
        doc = document(text)
        chunker = RagChunkingService(max_chunk_chars=70, overlap_chars=20, chunking_version="chunk-v1")

        first = chunker.chunk_document(doc)
        second = chunker.chunk_document(doc)

        self.assertEqual(first, second)
        self.assertGreater(len(first), 1)
        self.assertEqual(0, first[0].chunk_index)
        self.assertEqual(doc.seller_id, first[0].seller_id)
        self.assertEqual(doc.product_id, first[0].product_id)
        self.assertEqual("products", first[0].metadata_json["source_table"])
        self.assertEqual("yes", first[0].metadata_json["safe"])
        self.assertFalse(first[0].chunk_text.endswith("BDT"))
        overlap_words = set(first[0].chunk_text.split()) & set(first[1].chunk_text.split())
        self.assertTrue(overlap_words)

    def test_chunking_rejects_empty_content(self):
        chunker = RagChunkingService(max_chunk_chars=50, overlap_chars=5)

        with self.assertRaises(Exception):
            chunker.chunk_text("   ")


if __name__ == "__main__":
    unittest.main()
