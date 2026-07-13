from __future__ import annotations

from datetime import datetime, timezone
import unittest
from uuid import uuid4

from app.models.rag_memory import RagMemorySourceType
from app.api.v1.rag import _seller_owns_product
from app.services.rag_answer_service import RagAnswerService
from app.services.rag_retrieval_service import RagEvidence, RagRetrievalResult


class FakeRetrievalService:
    def __init__(self, retrieval: RagRetrievalResult) -> None:
        self.retrieval = retrieval

    def retrieve_context(self, **kwargs):
        del kwargs
        return self.retrieval


class RagApiBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_groq_exception_returns_safe_fallback_without_stack_trace_or_action(self):
        retrieval = _retrieval()

        async def failing_groq(*args, **kwargs):
            del args, kwargs
            raise RuntimeError("Traceback: secret stack")

        service = RagAnswerService(
            retrieval_service=FakeRetrievalService(retrieval),
            groq_json_completion=failing_groq,
        )

        result = await service.answer_question(seller_id=uuid4(), question="Restock this now and execute order")
        payload = result.to_dict()
        joined = " ".join(str(value) for value in payload.values())

        self.assertEqual("FALLBACK", payload["answer_status"])
        self.assertNotIn("Traceback", joined)
        self.assertNotIn("secret stack", joined)
        self.assertNotIn("executed", joined.lower())
        self.assertEqual([retrieval.evidence_ids[0]], payload["evidence_ids"])

    async def test_product_ownership_filter_blocks_other_seller_product(self):
        session = FakeProductSession(found=False)

        allowed = _seller_owns_product(session, seller_id=uuid4(), product_id=uuid4())

        self.assertFalse(allowed)


def _retrieval() -> RagRetrievalResult:
    document_id = uuid4()
    chunk_id = uuid4()
    evidence = RagEvidence(
        evidence_id=f"rag:{document_id}:{chunk_id}",
        chunk_id=chunk_id,
        memory_document_id=document_id,
        source_type=RagMemorySourceType.RECOMMENDATION,
        product_id=uuid4(),
        event_time=datetime(2026, 7, 5, tzinfo=timezone.utc),
        chunk_text="Reorder recommendation suggested reviewing inventory.",
        similarity_score=0.8,
        final_score=0.9,
        source_table="reorder_recommendations",
        source_id=str(uuid4()),
    )

    return RagRetrievalResult(
        retrieved_chunks=[evidence],
        source_documents=[
            {
                "id": document_id,
                "title": "Reorder recommendation",
                "source_type": RagMemorySourceType.RECOMMENDATION,
                "source_table": "reorder_recommendations",
                "source_id": str(uuid4()),
                "event_time": evidence.event_time,
            }
        ],
        similarity_scores={str(chunk_id): 0.8},
        evidence_ids=[evidence.evidence_id],
        retrieval_confidence="MEDIUM",
    )


class FakeProductSession:
    def __init__(self, *, found: bool) -> None:
        self.found = found

    def execute(self, statement):
        self.statement = statement
        return self

    def scalar_one_or_none(self):
        return uuid4() if self.found else None


if __name__ == "__main__":
    unittest.main()
