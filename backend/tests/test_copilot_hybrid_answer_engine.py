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

    async def _answer(self, question: str, groq_payload, tools, *, usage=None):
        async def groq(messages, **kwargs):
            response = {"model": "test-model", "content": groq_payload}
            if usage is not None:
                response["usage"] = usage
            return response

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

    async def test_no_sales_claim_accepted_when_revenue_summary_for_period_is_zero(self):
        zero_day = {
            "gross_revenue": "0", "order_count": 0, "units_sold": 0,
            "filters_used": {"from_date": "2026-07-04", "to_date": "2026-07-04"},
            "latest_recorded_sale_date": "2026-07-02",
        }
        result = await self._answer("Gotokal kono sales hoise?", _payload("No sales were recorded yesterday.", "get_revenue_summary:1"), [_tool("get_revenue_summary", zero_day)])

        self.assertTrue(result.context.has_reliable_no_sales_evidence)
        self.assertEqual("No sales were recorded yesterday.", result.payload["answer"])

        without_date = {key: value for key, value in zero_day.items() if key != "latest_recorded_sale_date"}
        other_period = {**zero_day, "filters_used": {"from_date": "2026-06-01", "to_date": "2026-06-30"}}
        for data in (without_date, other_period):
            result = await self._answer("Gotokal kono sales hoise?", _payload("No sales were recorded yesterday.", "get_revenue_summary:1"), [_tool("get_revenue_summary", data)])
            self.assertFalse(result.context.has_reliable_no_sales_evidence)

    async def test_no_sales_claim_still_rejected_without_any_sales_lookup(self):
        result = await self._answer("Gotokal kono sales hoise?", _payload("No sales were recorded yesterday.", "count_products:1"), [_tool("count_products", {"count": 12})])

        self.assertFalse(result.context.has_reliable_no_sales_evidence)
        self.assertNotEqual("No sales were recorded yesterday.", result.payload["answer"])

    async def test_overview_revenue_claim_accepted(self):
        result = await self._answer("Give me my business overview", _payload("Revenue is 250.00.", "get_business_overview:1"), [_tool("get_business_overview", {"gross_revenue": "250.00"})])

        self.assertTrue(result.context.has_financial_evidence)
        self.assertEqual("Revenue is 250.00.", result.payload["answer"])

    async def test_records_sales_zero_rows_backs_no_sales_and_financial_claims(self):
        records = {"entity": "sales", "aggregate": "count", "rows": [], "row_count": 0, "filters": {"from_date": "2026-07-04", "to_date": "2026-07-04"}, "latest_recorded_sale_date": "2026-07-02"}
        result = await self._answer("Gotokal kono sales hoise?", _payload("No sales were recorded yesterday.", "query_business_records:1"), [_tool("query_business_records", records)])

        self.assertTrue(result.context.has_reliable_no_sales_evidence)
        self.assertTrue(result.context.has_financial_evidence)

    async def test_fallback_answers_only_from_primary_tools(self):
        async def down(messages, **kwargs):
            raise RuntimeError("model down")

        question = "Last 7 din e amar revenue koto?"
        classification, plan = self._classification_plan(question)
        tools = [_tool("get_inventory_risks", {"risks": [{"product": {"title": "Unrelated Risky Shoe"}, "risk_level": "HIGH"}]}), _tool("get_revenue_summary", {"gross_revenue": "250.00", "order_count": 3, "units_sold": 4})]

        result = await CopilotHybridAnswerEngine(groq_json=down, model="test-model", timeout_seconds=1).answer(
            question=question, classification=classification, plan=plan, tool_results=tools, missing_data=[], request_id="req-test", primary_tools={"get_revenue_summary"},
        )

        self.assertEqual(frozenset({"get_revenue_summary"}), result.context.primary_tools)
        self.assertIn("250.00", result.payload["answer"])
        self.assertNotIn("Unrelated Risky Shoe", result.payload["answer"])
        self.assertIn(result.context.resolved_period["from_date"], result.payload["answer"])

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

    async def test_token_usage_recorded_for_validated_answer(self):
        usage = {"prompt_tokens": 120, "completion_tokens": 40, "total_tokens": 160}
        result = await self._answer(
            "How many products do I have?",
            _payload("You have 12 products.", "count_products:1"),
            [_tool("count_products", {"count": 12})],
            usage=usage,
        )

        self.assertIsNone(result.validation_error)
        self.assertEqual(usage, result.token_usage)

    async def test_token_usage_kept_when_answer_is_rejected(self):
        usage = {"prompt_tokens": 120, "completion_tokens": 40, "total_tokens": 160}
        result = await self._answer(
            "How many products do I have?",
            _payload("You have 99 products.", "count_products:1"),
            [_tool("count_products", {"count": 12})],
            usage=usage,
        )

        self.assertIsNotNone(result.validation_error)
        self.assertEqual(usage, result.token_usage)

    async def test_token_usage_absent_without_model_call(self):
        result = await self._answer("How many products do I have?", _payload("unused", "none"), [], usage={"total_tokens": 5})

        self.assertIsNone(result.token_usage)

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


class PromptSizeTests(unittest.TestCase):
    """Groq's on_demand tier rejects requests over 8000 tokens/minute, so unbounded prompt lists must stay capped."""

    def test_evidence_is_capped_and_empty_fields_dropped(self):
        from app.services.copilot.context_builder import PROMPT_EVIDENCE_LIMIT, _prompt_evidence

        evidence = [{"evidence_id": f"sales_records:{index}", "snippet": None, "url": ""} for index in range(300)]

        trimmed = _prompt_evidence(evidence)

        self.assertEqual(PROMPT_EVIDENCE_LIMIT, len(trimmed))
        self.assertEqual({"evidence_id": "sales_records:0"}, trimmed[0])

    def test_freshness_is_reduced_to_distinct_domain_status_pairs(self):
        from app.services.copilot.context_builder import _prompt_freshness

        freshness = [{"domain": "SALES_REVENUE", "status": "MISSING", "message": f"tool {index} freshness is missing."} for index in range(20)]

        self.assertEqual([{"domain": "SALES_REVENUE", "status": "MISSING"}], _prompt_freshness(freshness))

    def test_primary_tool_never_omitted_when_secondary_tools_fill_budget(self):
        from app.services.copilot.context_builder import _json_size, budget_facts

        def fact(chars: int) -> dict:
            rows = [{"value": "x" * 80} for _ in range(chars // 94)]
            return {"rows": rows}

        primary = fact(9000)
        facts = {"get_sales_trends": fact(8000), "get_inventory_risks": fact(8000), "get_competitor_threats": fact(8000), "query_business_records": primary}
        self.assertGreater(_json_size(primary), 8500)

        fitted, truncated = budget_facts(facts, tool_chars=4000, total_chars=20000, primary={"query_business_records"})

        self.assertEqual(primary, fitted["query_business_records"])
        self.assertNotIn("query_business_records", truncated)
        self.assertTrue(set(truncated) & {"get_sales_trends", "get_inventory_risks", "get_competitor_threats"})
        self.assertEqual(list(facts), list(fitted))  # key order unchanged


if __name__ == "__main__":
    unittest.main()


class MissingFactsPromptTests(unittest.TestCase):
    def test_system_prompt_names_what_is_not_recorded_and_the_closest_data(self):
        from types import SimpleNamespace

        from app.services.copilot.hybrid_answer_engine import _prompt_from_context

        context = SimpleNamespace(to_prompt_payload=lambda: {"facts": {}}, reply_language=None, conversation=None)
        system = _prompt_from_context(context)[0]["content"]

        self.assertIn("say exactly what is not recorded", system)
        self.assertIn("closest available data", system)
        self.assertIn("NO_MATCHING_RECORDS", system)
        # Live eval: "You issued 138 invoices" restated orders as invoices.
        self.assertIn("Never present one kind of record as another", system)
        self.assertIn("only when no supplied fact covers it", system)


class RepeatedToolFactsTests(unittest.TestCase):
    def test_a_second_call_to_the_same_tool_keeps_its_own_facts(self):
        from app.services.copilot.context_builder import _facts_by_tool

        first = _tool("query_business_records", {"entity": "stock_ins", "rows": [{"quantity": 40}]})
        second = _tool("query_business_records", {"entity": "sales", "rows": [{"value": 138}]})

        facts = _facts_by_tool([first, second])

        self.assertEqual(["query_business_records", "query_business_records#2"], list(facts))
        self.assertEqual("stock_ins", facts["query_business_records"]["entity"])
        self.assertEqual("sales", facts["query_business_records#2"]["entity"])


class RoundedFactNumberTests(unittest.TestCase):
    def test_long_decimal_facts_may_be_stated_rounded(self):
        from app.services.copilot.context_builder import _numbers_from_payload

        allowed = _numbers_from_payload({"percentage_change": "7.029649509550046737014016080", "estimated_profit": "144764.67800000", "price": "1874.00"})

        self.assertTrue({"7.03", "7.0", "144764.68", "144764.7", "1874.00"} <= allowed)
        self.assertNotIn("7", allowed)
        self.assertNotIn("144765", allowed)
