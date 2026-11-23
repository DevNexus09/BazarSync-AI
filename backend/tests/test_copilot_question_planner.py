from __future__ import annotations

from datetime import date, datetime
import unittest
from uuid import UUID

from app.services.copilot.entity_resolver import CopilotEntityResolver, ProductEntityCandidate
from app.services.copilot.intent_classifier import CopilotIntentClassifier
from app.services.copilot.question_planner import CopilotQuestionPlanner, CopilotQuestionType
from app.services.copilot.tool_registry import CopilotToolRegistry


SELLER_ID = UUID("00000000-0000-0000-0000-000000000001")
PRODUCT_A_ID = UUID("00000000-0000-0000-0000-000000000010")
PRODUCT_B_ID = UUID("00000000-0000-0000-0000-000000000011")


class _FakeProductSource:
    def __init__(self, products: list[ProductEntityCandidate]) -> None:
        self.products = products

    def list_products(self, *, seller_id, limit: int = 200):
        return self.products[:limit]


class CopilotQuestionPlannerTests(unittest.TestCase):
    def _plan(
        self,
        question: str,
        *,
        max_tools: int = 6,
        product_id=None,
        from_date=None,
        to_date=None,
        products: list[ProductEntityCandidate] | None = None,
    ):
        classifier = CopilotIntentClassifier(now=datetime(2026, 7, 5, 10, 0), seller_timezone="Asia/Dhaka")
        seller_products = list(products or [])
        if product_id and all(item.id != product_id for item in seller_products):
            seller_products.append(ProductEntityCandidate(id=product_id, title=str(product_id)))
        planner = CopilotQuestionPlanner(
            entity_resolver=CopilotEntityResolver(product_source=_FakeProductSource(seller_products)),
            now=datetime(2026, 7, 5, 10, 0),
        )
        classification = classifier.classify(seller_id=SELLER_ID, question=question)
        return planner.plan(
            seller_id=SELLER_ID,
            question=question,
            language=classification.language,
            conversation_history=[],
            product_id=product_id,
            from_date=from_date,
            to_date=to_date,
            top_k=8,
            include_memory=True,
            business_catalog=None,
            metric_catalog=None,
            tool_registry=CopilotToolRegistry(),
            classification_hint=classification,
            max_tools=max_tools,
            memory_source_types=None,
        )

    def test_product_count_question_generates_product_tools(self):
        plan = self._plan("How many products do I have?")

        self.assertEqual(CopilotQuestionType.LOOKUP, plan.question_type)
        self.assertIn("run_seller_metric_query", [step.tool_name for step in plan.tool_plan])
        self.assertIn("count_products", [step.tool_name for step in plan.tool_plan])

    def test_listed_and_available_counts_lead_with_count_products(self):
        # count_products reports the account total beside the listed subset, and filters stock; the metric does neither.
        for question, filters in (("How many products do I have listed?", {"status": "LISTED"}), ("How many products are available?", {"has_stock": True})):
            tools = [step for step in self._plan(question).tool_plan if step.tool_name in {"run_seller_metric_query", "count_products"}]
            self.assertEqual("count_products", tools[0].tool_name, question)
            self.assertEqual(filters, {key: tools[0].args.get(key) for key in filters}, question)

    def test_unavailable_count_is_not_an_in_stock_count(self):
        count = next(step for step in self._plan("How many products are unavailable?").tool_plan if step.tool_name == "count_products")
        self.assertIs(False, count.args.get("has_stock"))

    def test_missing_cost_question_generates_list_products(self):
        plan = self._plan("Which products are missing cost?")

        tools = [step.tool_name for step in plan.tool_plan]
        self.assertIn("run_seller_metric_query", tools)
        self.assertIn("list_products", tools)
        list_step = next(step for step in plan.tool_plan if step.tool_name == "list_products")
        self.assertTrue(list_step.args["missing_cost"])

    def test_revenue_question_generates_revenue_tools(self):
        plan = self._plan("What is my revenue this month?")

        self.assertEqual(CopilotQuestionType.ANALYTIC, plan.question_type)
        metric_steps = [step for step in plan.tool_plan if step.tool_name == "run_seller_metric_query"]
        self.assertTrue(any(step.args["metric_key"] == "gross_revenue" for step in metric_steps))
        self.assertTrue(any(step.args["metric_key"] == "revenue_trend" for step in metric_steps))
        self.assertIn("get_revenue_summary", [step.tool_name for step in plan.tool_plan])
        self.assertIn("get_sales_trends", [step.tool_name for step in plan.tool_plan])

    def test_planner_does_not_select_unsupported_net_revenue_metric(self):
        plan = self._plan("What is my net revenue this month?")

        metric_steps = [step for step in plan.tool_plan if step.tool_name == "run_seller_metric_query"]
        self.assertFalse(any(step.args["metric_key"] == "net_revenue" for step in metric_steps))

    def test_competitor_question_generates_competitor_tools(self):
        plan = self._plan("Which competitor is hurting me?")

        self.assertIn("get_competitor_threats", [step.tool_name for step in plan.tool_plan])
        self.assertIn("COMPETITOR", plan.required_domains)

    def test_broad_business_summary_uses_multiple_domains(self):
        plan = self._plan("Summarize my business today and biggest risks")

        tools = {step.tool_name for step in plan.tool_plan}
        self.assertEqual(CopilotQuestionType.GENERAL_BUSINESS, plan.question_type)
        self.assertIn("get_business_overview", tools)
        self.assertGreaterEqual(len(plan.required_domains), 3)

    def test_bangla_question_works(self):
        plan = self._plan("গত সপ্তাহে বিক্রি কেন কমেছে?")

        self.assertEqual("bn", plan.language)
        self.assertIn("get_revenue_summary", [step.tool_name for step in plan.tool_plan])
        self.assertEqual("2026-06-22", plan.entities.date_range["from_date"])

    def test_product_ambiguity_returns_clarification(self):
        plan = self._plan(
            "Should I restock charger?",
            products=[
                ProductEntityCandidate(id=PRODUCT_A_ID, title="USB Charger 20W", category="charger", searchable_text="usb charger fast"),
                ProductEntityCandidate(id=PRODUCT_B_ID, title="USB Charger 30W", category="charger", searchable_text="usb charger fast"),
            ],
        )

        self.assertTrue(plan.needs_clarification)
        self.assertIn("Which product", plan.clarification_question)

    def test_unknown_business_question_still_retrieves_memory(self):
        plan = self._plan("What happened with basket quality before?")

        self.assertIn("retrieve_business_memory", [step.tool_name for step in plan.tool_plan])
        self.assertTrue(plan.memory_search_plan.enabled)

    def test_action_request_becomes_proposal_plan(self):
        plan = self._plan("Lower price by 5%", product_id=PRODUCT_A_ID)

        self.assertEqual(CopilotQuestionType.ACTION_REQUEST, plan.question_type)
        self.assertIn("ACTION_PROPOSAL_ONLY", plan.safety_flags)
        self.assertIn("simulate_price_change", [step.tool_name for step in plan.tool_plan])

    def test_planner_only_uses_registered_tools(self):
        registry_tools = {tool.name for tool in CopilotToolRegistry().list_tools()}
        plan = self._plan("Which products are unsafe to discount?")

        self.assertTrue(plan.tool_plan)
        self.assertTrue({step.tool_name for step in plan.tool_plan}.issubset(registry_tools))

    def test_tool_limit_enforced(self):
        plan = self._plan("Why is revenue down this week?", max_tools=2)

        self.assertLessEqual(len(plan.tool_plan), 2)
        self.assertIn("TOOL_LIMIT_ENFORCED", plan.safety_flags)

    def test_invalid_date_handled_safely(self):
        plan = self._plan("Why is revenue down?", from_date=date(2026, 7, 5), to_date=date(2026, 7, 1))

        self.assertTrue(any(flag.startswith("INVALID_DATE_RANGE") for flag in plan.safety_flags))
        for step in plan.tool_plan:
            self.assertNotEqual(step.args.get("from_date"), "2026-07-05")


if __name__ == "__main__":
    unittest.main()
