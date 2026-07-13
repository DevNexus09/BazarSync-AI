from __future__ import annotations

from datetime import datetime
import unittest

from app.services.copilot.hybrid_answer_engine import CopilotHybridAnswerEngine
from app.services.copilot.intent_classifier import CopilotIntentClassifier
from app.services.copilot.question_planner import CopilotQuestionPlanner
from app.services.copilot.tool_registry import ToolExecutionResult, ToolExecutionStatus

from tests.test_copilot_orchestrator import SELLER_ID


def _tool(name: str, data: dict, *, evidence_id: str | None = None):
    evidence = [{"evidence_id": evidence_id or f"{name}:1", "source_table": name, "source_id": "1"}]
    return ToolExecutionResult(
        tool_name=name,
        tool_version="v1",
        status=ToolExecutionStatus.SUCCEEDED,
        data={**data, "evidence": evidence, "missing_data": data.get("missing_data", [])},
        evidence=evidence,
        missing_data=data.get("missing_data", []),
        error=None,
        runtime_ms=1,
    )


class CopilotHybridAnswerEngineTests(unittest.IsolatedAsyncioTestCase):
    def _classification_plan(self, question: str):
        classifier = CopilotIntentClassifier(now=datetime(2026, 7, 5, 10, 0))
        classification = classifier.classify(seller_id=SELLER_ID, question=question)
        planner = CopilotQuestionPlanner(now=datetime(2026, 7, 5, 10, 0))
        plan = planner.plan(
            seller_id=SELLER_ID,
            question=question,
            language=classification.language,
            conversation_history=[],
            product_id=None,
            from_date=None,
            to_date=None,
            top_k=8,
            include_memory=True,
            business_catalog=None,
            metric_catalog=None,
            tool_registry=_Registry(),
            classification_hint=classification,
            max_tools=6,
            memory_source_types=None,
        )
        return classification, plan

    async def _answer(self, question: str, groq_payload, tools):
        async def groq(messages, **kwargs):
            return {"model": "test-model", "content": groq_payload}

        classification, plan = self._classification_plan(question)
        return await CopilotHybridAnswerEngine(groq_json=groq, model="test-model", timeout_seconds=1).answer(
            question=question,
            classification=classification,
            plan=plan,
            tool_results=tools,
            missing_data=[],
            request_id="req-test",
        )

    async def test_exact_product_count_answered_from_direct_tool(self):
        result = await self._answer(
            "How many products do I have?",
            _payload("You have 12 products.", "count_products:1"),
            [_tool("count_products", {"count": 12})],
        )

        self.assertEqual("HIGH", result.payload["confidence"])
        self.assertIn("12", result.payload["answer"])

    async def test_revenue_answered_from_analytics_tool(self):
        result = await self._answer(
            "What is my revenue?",
            _payload("Revenue is 250.00.", "get_revenue_summary:1"),
            [_tool("get_revenue_summary", {"gross_revenue": "250.00"})],
        )

        self.assertIn("250.00", result.payload["answer"])

    async def test_historical_question_uses_rag(self):
        result = await self._answer(
            "What happened last time?",
            _payload("Historical memory says supplier delay happened.", "rag:doc:chunk"),
            [_tool("retrieve_business_memory", {"memory_chunks": [{"evidence_id": "rag:doc:chunk", "snippet": "supplier delay happened"}]}, evidence_id="rag:doc:chunk")],
        )

        self.assertTrue(result.context.has_memory_evidence)
        self.assertEqual("Historical memory says supplier delay happened.", result.payload["answer"])

    async def test_direct_data_overrides_stale_rag(self):
        result = await self._answer(
            "How many products do I have?",
            _payload("You have 12 products.", "count_products:1"),
            [
                _tool("count_products", {"count": 12}),
                _tool(
                    "retrieve_business_memory",
                    {"memory_chunks": [{"evidence_id": "rag:old:chunk", "snippet": "old count was 99", "event_time": "2025-01-01T00:00:00+00:00"}]},
                    evidence_id="rag:old:chunk",
                ),
            ],
        )

        self.assertTrue(result.context.has_direct_evidence)
        self.assertTrue(result.context.has_memory_evidence)
        self.assertIn("12", result.payload["answer"])

    async def test_unsupported_number_rejected(self):
        result = await self._answer(
            "How many products do I have?",
            _payload("You have 99 products.", "count_products:1"),
            [_tool("count_products", {"count": 12})],
        )

        self.assertIsNotNone(result.validation_error)
        self.assertNotEqual("You have 99 products.", result.payload["answer"])

    async def test_invalid_evidence_id_removed(self):
        result = await self._answer(
            "How many products do I have?",
            _payload("You have 12 products.", "not-real"),
            [_tool("count_products", {"count": 12})],
        )

        self.assertEqual(["count_products:1"], [item["evidence_id"] for item in result.payload["evidence"]])

    async def test_low_visibility_rejected_without_visibility_evidence(self):
        result = await self._answer(
            "How is visibility?",
            _payload("Visibility is low.", "count_products:1"),
            [_tool("count_products", {"count": 12})],
        )

        self.assertIsNotNone(result.validation_error)

    async def test_no_sales_rejected_without_reliable_sales_history(self):
        result = await self._answer(
            "Which products have no sales?",
            _payload("Product A has no sales.", "count_products:1"),
            [_tool("count_products", {"count": 12})],
        )

        self.assertIsNotNone(result.validation_error)

    async def test_bangla_answer(self):
        result = await self._answer(
            "আজ কত পণ্য আছে?",
            _payload("আপনার 12টি পণ্য আছে।", "count_products:1", language="bn"),
            [_tool("count_products", {"count": 12})],
        )

        self.assertEqual("bn", result.payload["language"])

    async def test_invalid_json_fallback(self):
        async def groq(messages, **kwargs):
            return {"model": "test-model", "content": "not-json"}

        classification, plan = self._classification_plan("How many products?")
        result = await CopilotHybridAnswerEngine(groq_json=groq, model="test-model", timeout_seconds=1).answer(
            question="How many products?",
            classification=classification,
            plan=plan,
            tool_results=[_tool("count_products", {"count": 12})],
            missing_data=[],
        )

        self.assertIsNotNone(result.validation_error)
        self.assertIn("count_products:1", [item["evidence_id"] for item in result.payload["evidence"]])


class _Registry:
    def list_tools(self):
        class Tool:
            def __init__(self, name):
                self.name = name

        return [Tool(name) for name in ("count_products", "get_revenue_summary", "retrieve_business_memory")]

    def validate_arguments(self, name, arguments):
        return True, arguments, None


def _payload(answer: str, evidence_id: str, *, language: str = "en") -> dict:
    return {
        "answer": answer,
        "summary": answer,
        "confidence": "HIGH",
        "language": language,
        "evidence": [{"evidence_id": evidence_id}],
        "missing_data": [],
        "recommended_next_steps": ["Review evidence."],
    }


if __name__ == "__main__":
    unittest.main()
