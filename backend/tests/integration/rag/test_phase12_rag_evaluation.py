from __future__ import annotations

from datetime import datetime, timezone
import re
import unittest
from uuid import UUID, uuid4

from app.models.rag_memory import RagMemorySourceType
from app.services.rag_answer_service import RagAnswerService
from app.services.rag_retrieval_service import RagEvidence, RagRetrievalResult


SELLER_A = uuid4()
SELLER_B = uuid4()
PRODUCT_A = uuid4()
PRODUCT_B = uuid4()

QUESTIONS = [
    "Which competitors dropped price for Product A last week?",
    "Why did Product B stock out?",
    "Which pricing recommendations were ignored?",
    "What inventory alerts were sent yesterday?",
    "Which promotions improved revenue?",
    "What should I do today based on recent alerts?",
]


class SeededRetrievalService:
    def __init__(self) -> None:
        self.data = {
            SELLER_A: [
                _evidence(
                    seller_id=SELLER_A,
                    product_id=PRODUCT_A,
                    source_type=RagMemorySourceType.COMPETITOR_HISTORY,
                    text="Competitor Alpha dropped Product A price by 20 last week.",
                    number="20",
                ),
                _evidence(
                    seller_id=SELLER_A,
                    product_id=PRODUCT_B,
                    source_type=RagMemorySourceType.INVENTORY_HISTORY,
                    text="Product B stocked out because available inventory was 0 after high sales velocity.",
                    number="0",
                ),
                _evidence(
                    seller_id=SELLER_A,
                    product_id=PRODUCT_A,
                    source_type=RagMemorySourceType.PRICE_HISTORY,
                    text="Pricing recommendation HOLD was ignored for Product A.",
                    number=None,
                ),
                _evidence(
                    seller_id=SELLER_A,
                    product_id=PRODUCT_B,
                    source_type=RagMemorySourceType.ALERT,
                    text="Inventory alert sent yesterday for Product B low stock.",
                    number=None,
                ),
                _evidence(
                    seller_id=SELLER_A,
                    product_id=PRODUCT_A,
                    source_type=RagMemorySourceType.PROMOTION_RESULT,
                    text="Promotion for Product A improved revenue by 15.",
                    number="15",
                ),
            ],
            SELLER_B: [
                _evidence(
                    seller_id=SELLER_B,
                    product_id=uuid4(),
                    source_type=RagMemorySourceType.COMPETITOR_HISTORY,
                    text="Seller B competitor Beta dropped price by 999.",
                    number="999",
                )
            ],
        }

    def retrieve_context(self, *, seller_id: UUID, question: str, **kwargs) -> RagRetrievalResult:
        del kwargs
        terms = set(re.findall(r"[a-z0-9]+", question.lower()))
        selected = [
            item
            for item in self.data[seller_id]
            if terms & set(re.findall(r"[a-z0-9]+", item.chunk_text.lower()))
        ][:3]
        if not selected:
            selected = self.data[seller_id][:2]
        return RagRetrievalResult(
            retrieved_chunks=selected,
            source_documents=[
                {
                    "id": item.memory_document_id,
                    "source_type": item.source_type,
                    "product_id": item.product_id,
                    "source_table": item.source_table,
                    "source_id": item.source_id,
                    "title": f"{item.source_type.value} memory",
                    "event_time": item.event_time,
                }
                for item in selected
            ],
            similarity_scores={str(item.chunk_id): item.similarity_score for item in selected},
            evidence_ids=[item.evidence_id for item in selected],
            retrieval_confidence="HIGH",
        )


class Phase12RagEvaluationTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_questions_use_only_seller_a_evidence(self):
        retrieval_service = SeededRetrievalService()

        async def fake_groq(messages, **kwargs):
            del kwargs
            prompt = " ".join(message["content"] for message in messages)
            evidence_id = re.search(r"rag:[^\"\\]+", prompt).group(0)
            return {
                "model": "llama-test",
                "content": {
                    "answer": "Seller A answer uses only the cited evidence.",
                    "summary": "Grounded in Seller A evidence.",
                    "evidence": [
                        {
                            "evidence_id": evidence_id,
                            "source_type": "ALERT",
                            "source_title": "Seller A memory",
                            "event_time": "2026-07-05T00:00:00+00:00",
                        }
                    ],
                    "confidence": "HIGH",
                    "missing_context": [],
                    "recommended_next_steps": ["Review cited evidence."],
                    "language": "en",
                    "disclaimer": "Evidence only.",
                },
            }

        service = RagAnswerService(retrieval_service=retrieval_service, groq_json_completion=fake_groq)

        for question in QUESTIONS:
            with self.subTest(question=question):
                result = await service.answer_question(seller_id=SELLER_A, question=question, min_similarity=0.1)
                joined = f"{result.answer} {result.summary}"
                self.assertEqual("SUCCESS", result.answer_status)
                self.assertTrue(result.evidence_ids)
                self.assertNotIn("Seller B", joined)
                self.assertNotIn("999", joined)
                for evidence_id in result.evidence_ids:
                    self.assertIn(evidence_id, retrieval_service.retrieve_context(seller_id=SELLER_A, question=question).evidence_ids)


def _evidence(*, seller_id, product_id, source_type, text, number):
    document_id = uuid4()
    chunk_id = uuid4()
    del seller_id, number
    return RagEvidence(
        evidence_id=f"rag:{document_id}:{chunk_id}",
        chunk_id=chunk_id,
        memory_document_id=document_id,
        source_type=source_type,
        product_id=product_id,
        event_time=datetime(2026, 7, 5, tzinfo=timezone.utc),
        chunk_text=text,
        similarity_score=0.86,
        final_score=0.92,
        source_table="rag_eval",
        source_id=str(uuid4()),
        metadata_json={},
    )


if __name__ == "__main__":
    unittest.main()
