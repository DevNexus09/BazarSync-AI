from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from uuid import uuid4

from app.models.rag_memory import RagMemorySourceType
from app.services import rag_observability
from app.services.rag_prompt_builder import MAX_PROMPT_CHARS, RagPromptBuilder, sanitize_prompt_text
from app.services.rag_retrieval_service import MAX_RETRIEVAL_TOP_K, RagEvidence, RagRetrievalResult, RagRetrievalService


class FakeEmbeddingService:
    def embed_text(self, text):
        del text
        return [0.1, 0.2, 0.3]


class CaptureRepository:
    def __init__(self, rows=None) -> None:
        self.rows = rows or []
        self.limits = []

    def vector_search(self, **kwargs):
        self.limits.append(kwargs["limit"])
        return self.rows

    def keyword_search(self, **kwargs):
        del kwargs
        return []

    def get_documents_by_ids(self, *, seller_id, document_ids):
        del seller_id
        return {
            document_id: SimpleNamespace(
                id=document_id,
                source_type=RagMemorySourceType.ALERT,
                product_id=None,
                source_table="alerts",
                source_id="1",
                title="Alert",
                event_time=datetime(2026, 7, 5, tzinfo=timezone.utc),
            )
            for document_id in document_ids
        }


def chunk(*, seller_id):
    document_id = uuid4()
    return SimpleNamespace(
        id=uuid4(),
        seller_id=seller_id,
        memory_document_id=document_id,
        product_id=None,
        source_type=RagMemorySourceType.ALERT,
        chunk_text="Inventory alert has 20 units.",
        metadata_json={},
        event_time=datetime(2026, 7, 5, tzinfo=timezone.utc),
    )


class Phase12HardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        rag_observability.reset_metrics()

    def test_prompt_sanitizer_removes_secrets_and_raw_html(self):
        text = "<script>alert(1)</script><b>stock</b> api_key=secret-token password=hunter2"

        sanitized = sanitize_prompt_text(text)

        self.assertNotIn("<script", sanitized)
        self.assertNotIn("<b>", sanitized)
        self.assertNotIn("secret-token", sanitized)
        self.assertNotIn("hunter2", sanitized)
        self.assertIn("[REDACTED]", sanitized)

    def test_retrieval_top_k_is_bounded(self):
        seller_id = uuid4()
        owned = chunk(seller_id=seller_id)
        repo = CaptureRepository(rows=[(owned, 0.2)])
        service = RagRetrievalService(repository=repo, embedding_service=FakeEmbeddingService())

        service.retrieve_context(seller_id=seller_id, question="alerts", top_k=500, min_similarity=0.1)

        self.assertEqual(MAX_RETRIEVAL_TOP_K * 4, repo.limits[0])

    def test_cross_seller_rows_are_blocked_and_counted(self):
        seller_id = uuid4()
        other = chunk(seller_id=uuid4())
        repo = CaptureRepository(rows=[(other, 0.01)])
        service = RagRetrievalService(repository=repo, embedding_service=FakeEmbeddingService())

        result = service.retrieve_context(seller_id=seller_id, question="alerts", min_similarity=0.1)

        self.assertEqual("NO_CONTEXT", result.retrieval_confidence)
        self.assertEqual(1, rag_observability.snapshot_metrics()["counters"]["rag_cross_tenant_blocked_total"])

    def test_prompt_context_length_is_bounded(self):
        evidence = []
        documents = []
        for _ in range(30):
            document_id = uuid4()
            chunk_id = uuid4()
            evidence.append(
                RagEvidence(
                    evidence_id=f"rag:{document_id}:{chunk_id}",
                    chunk_id=chunk_id,
                    memory_document_id=document_id,
                    source_type=RagMemorySourceType.ALERT,
                    product_id=None,
                    event_time=datetime(2026, 7, 5, tzinfo=timezone.utc),
                    chunk_text="x" * 2000,
                    similarity_score=0.8,
                    final_score=0.8,
                )
            )
            documents.append({"id": document_id, "title": "Alert", "source_table": "alerts", "source_id": "1"})
        retrieval = RagRetrievalResult(
            retrieved_chunks=evidence,
            source_documents=documents,
            similarity_scores={},
            evidence_ids=[item.evidence_id for item in evidence],
            retrieval_confidence="HIGH",
        )

        prompt = RagPromptBuilder().build_prompt(question="What happened?", retrieval=retrieval)

        self.assertLessEqual(len(prompt.messages[1]["content"]), MAX_PROMPT_CHARS + 80)

    def test_no_groq_key_in_frontend_source(self):
        frontend_root = Path(__file__).resolve().parents[4] / "frontend" / "src"
        matches = []
        for path in frontend_root.rglob("*"):
            if path.is_file() and path.suffix in {".ts", ".tsx", ".js", ".jsx"}:
                text = path.read_text(errors="ignore")
                if "GROQ_API_KEY" in text or "VITE_GROQ" in text:
                    matches.append(str(path))
        self.assertEqual([], matches)


if __name__ == "__main__":
    unittest.main()
