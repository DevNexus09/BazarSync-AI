from __future__ import annotations

import unittest

from app.services.copilot.answer_builder import CopilotAnswerBuilder, clean_answer_text
from app.services.copilot.intent_classifier import (
    CopilotIntent,
    CopilotIntentConfidence,
    CopilotIntentResult,
)
from app.services.copilot.tool_registry import ToolExecutionResult, ToolExecutionStatus


def _classification(intent: CopilotIntent, *, language: str = "en") -> CopilotIntentResult:
    return CopilotIntentResult(
        intent=intent,
        confidence=CopilotIntentConfidence.HIGH,
        suggested_tools=[],
        requires_action_proposal=intent.name.startswith("ACTION_REQUEST"),
        requires_confirmation=intent.name.startswith("ACTION_REQUEST"),
        language=language,
        product_mentions=[],
        date_range=None,
    )


def _result(tool_name: str, rows_key: str, rows: list[dict], *, missing: list[str] | None = None) -> ToolExecutionResult:
    evidence = [{"source_table": tool_name, "source_id": str(index + 1), "title": f"{tool_name} evidence"} for index, _ in enumerate(rows)]
    return ToolExecutionResult(
        tool_name=tool_name,
        tool_version="v1",
        status=ToolExecutionStatus.SUCCEEDED,
        data={rows_key: [row | {"evidence": evidence[index]} for index, row in enumerate(rows)], "missing_data": missing or []},
        evidence=evidence,
        missing_data=missing or [],
        error=None,
        runtime_ms=1,
    )


JUNK = ("**", "Confidence", "Evidence", "Missing data", "Next steps", "Safety", "Risk level", "SUCCEEDED", "FAILED", "execute automatically")


class CopilotAnswerBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = CopilotAnswerBuilder()

    def assert_clean(self, text: str) -> None:
        for junk in JUNK:
            self.assertNotIn(junk, text)

    def test_restock_answer_is_direct_list_with_one_next_step(self):
        answer = self.builder.build(
            classification=_classification(CopilotIntent.RESTOCK_ADVICE),
            tool_results=[
                _result("get_restock_recommendations", "recommendations", [{"product": {"title": "Black Casual Shoes For Men"}, "risk_level": "HIGH", "reorder_quantity": 72}]),
                _result("get_inventory_risks", "risks", [{"product": {"title": "Black Casual Shoes For Men"}, "risk_level": "HIGH"}]),
            ],
            evidence=[],
            missing_data=["Supplier lead time is stale."],
        )

        self.assertEqual(
            "These products need restocking:\n- Black Casual Shoes For Men: reorder 72\n\nCheck supplier lead time, then place the order.",
            answer.answer,
        )
        self.assert_clean(answer.answer)
        self.assertNotIn("Supplier lead time is stale.", answer.answer)
        # Metadata stays available to the API even though it is not shown.
        self.assertTrue(answer.evidence)
        self.assertIn("Supplier lead time is stale.", answer.missing_data)

    def test_duplicate_products_across_tools_are_merged(self):
        answer = self.builder.build(
            classification=_classification(CopilotIntent.COMPETITOR_THREAT_ANALYSIS),
            tool_results=[
                _result("get_competitor_threats", "threats", [{"affected_product": {"title": "Product A"}, "price_gap": "-10", "threat_reason": "PRICE_DROP"}]),
                _result("get_pricing_recommendations", "recommendations", [{"product": {"title": "Product A"}, "recommended_action": "HOLD"}]),
            ],
            evidence=[],
            missing_data=[],
        )

        self.assertEqual(1, answer.answer.count("Product A"))
        self.assertIn("- Product A: price gap -10", answer.answer)
        self.assert_clean(answer.answer)

    def test_today_actions_lists_at_most_three(self):
        rows = [{"product": {"title": f"Product {name}"}, "action_type": "REORDER"} for name in "ABCD"]
        answer = self.builder.build(
            classification=_classification(CopilotIntent.TODAY_ACTIONS),
            tool_results=[_result("get_today_actions", "actions", rows)],
            evidence=[],
            missing_data=[],
        )

        self.assertIn("- Product A: reorder", answer.answer)
        self.assertNotIn("Product D", answer.answer)
        self.assert_clean(answer.answer)

    def test_financial_answer_uses_plain_labels(self):
        answer = self.builder.build(
            classification=_classification(CopilotIntent.REVENUE_DIAGNOSIS),
            tool_results=[_result("get_revenue_summary", "time_series", [{"gross_revenue": "1200.00", "units_sold": 30}])],
            evidence=[],
            missing_data=[],
        )

        self.assertIn("- gross revenue: 1200.00", answer.answer)
        self.assertIn("- units sold: 30", answer.answer)
        self.assert_clean(answer.answer)

    def test_period_totals_are_not_replaced_by_the_top_products_figures(self):
        # Regression: get_revenue_summary's nested top product (59150.00) was reported as the period's gross revenue.
        summary = ToolExecutionResult(
            tool_name="get_revenue_summary",
            tool_version="v1",
            status=ToolExecutionStatus.SUCCEEDED,
            data={
                "gross_revenue": "290360.28",
                "units_sold": 312,
                "order_count": 138,
                "top_products_by_revenue": [{"product": {"title": "Hafsa Sneaker"}, "gross_revenue": "59150.00", "units_sold": 35, "order_count": 15}],
                "evidence": [{"source_table": "sales_records", "source_id": "1"}],
                "missing_data": [],
            },
            evidence=[{"source_table": "sales_records", "source_id": "1"}],
            missing_data=[],
            error=None,
            runtime_ms=1,
        )

        answer = self.builder.build(classification=_classification(CopilotIntent.REVENUE_DIAGNOSIS), tool_results=[summary], evidence=summary.evidence, missing_data=[])

        self.assertIn("- gross revenue: 290360.28", answer.answer)
        self.assertIn("- order count: 138", answer.answer)
        self.assertNotIn("59150.00", answer.answer)

    def test_rows_without_usable_facts_say_so_plainly(self):
        answer = self.builder.build(
            classification=_classification(CopilotIntent.SEO_ADVICE),
            tool_results=[_result("get_seo_opportunities", "opportunities", [{"note": "nothing"}])],
            evidence=[],
            missing_data=["Visibility history is incomplete."],
        )

        self.assertEqual("I could not find a clear answer in your data yet.", answer.answer)

    def test_no_context_answer_is_one_plain_sentence(self):
        answer = self.builder.build(
            classification=_classification(CopilotIntent.RESTOCK_ADVICE),
            tool_results=[],
            evidence=[],
            missing_data=["Sales velocity is missing."],
        )

        self.assertEqual("NO_CONTEXT", answer.confidence)
        self.assertNotIn("\n", answer.answer)
        self.assertNotIn("Sales velocity", answer.answer)

    def test_bangla_answer(self):
        answer = self.builder.build(
            classification=_classification(CopilotIntent.RESTOCK_ADVICE, language="bn"),
            tool_results=[
                _result("get_restock_recommendations", "recommendations", [{"product": {"title": "Product A"}, "reorder_quantity": 12}]),
            ],
            evidence=[],
            missing_data=[],
        )

        self.assertTrue(answer.answer.startswith("এই পণ্যগুলো রিস্টক করা দরকার:"))
        self.assertIn("- Product A: reorder 12", answer.answer)
        self.assertEqual("bn", answer.language)

    def _mixed_tool_results(self) -> list[ToolExecutionResult]:
        return [
            _result("get_revenue_summary", "time_series", [{"gross_revenue": "22750.00", "net_revenue": "22750.00", "units_sold": 13, "estimated_profit": "6142.50000000"}]),
            _result("get_inventory_risks", "risks", [{"product": {"title": "Bata Sandal"}, "risk_level": "CRITICAL"}]),
            _result("get_restock_recommendations", "recommendations", [{"product": {"title": "Black Casual Shoes For Men"}, "reorder_quantity": 72}]),
            _result("get_pricing_recommendations", "recommendations", [{"product": {"title": "Black Casual Shoes For Men"}, "recommended_action": "HOLD"}]),
        ]

    def test_restock_question_shows_only_restock_products(self):
        answer = self.builder.build(
            classification=_classification(CopilotIntent.RESTOCK_ADVICE, language="bn"),
            tool_results=self._mixed_tool_results(),
            evidence=[],
            missing_data=[],
        )

        self.assertEqual(
            "এই পণ্যগুলো রিস্টক করা দরকার:\n- Black Casual Shoes For Men: reorder 72\n\nSupplier lead time দেখে order দিন।",
            answer.answer,
        )

    def test_business_health_question_has_no_unrelated_next_step(self):
        answer = self.builder.build(
            classification=_classification(CopilotIntent.GENERAL_HELP, language="bn"),
            tool_results=self._mixed_tool_results(),
            evidence=[],
            missing_data=[],
        )

        self.assertIn("- gross revenue: 22750.00", answer.answer)
        self.assertNotIn("net revenue", answer.answer)
        self.assertIn("- estimated profit: 6142.50\n", answer.answer)
        self.assertNotIn("6142.500", answer.answer)
        self.assertNotIn("approve", answer.answer)
        self.assertEqual([], answer.recommended_next_steps)


    def test_top_selling_products_show_units_sold(self):
        answer = self.builder.build(
            classification=_classification(CopilotIntent.UNKNOWN),
            tool_results=[
                _result("get_top_products_by_revenue", "products", [{"product": {"title": "NORTH STAR HAFSA"}, "gross_revenue": "22750.00", "units_sold": 13}]),
            ],
            evidence=[],
            missing_data=[],
        )

        self.assertIn("- NORTH STAR HAFSA: sold 13", answer.answer)


class CleanAnswerTextTests(unittest.TestCase):
    def test_strips_headers_internals_and_duplicates(self):
        raw = (
            "**Answer**\n"
            "Black Casual Shoes For Men: reorder 72\n"
            "- Black Casual Shoes For Men: reorder 72\n\n"
            "**Confidence**: HIGH\n"
            "Evidence: inventory_risk:abc\n"
            "Tools used: get_restock_recommendations (SUCCEEDED)\n"
            "Data freshness: stale\n"
            "**Next steps**\n"
            "Next step: Supplier lead time check kore order din"
        )

        self.assertEqual(
            "Black Casual Shoes For Men: reorder 72\n\nSupplier lead time check kore order din",
            clean_answer_text(raw, evidence_ids=["inventory_risk:abc"]),
        )

    def test_keeps_prose_that_starts_with_a_label_word(self):
        self.assertEqual("Risk is low because stock is fine.", clean_answer_text("Risk is low because stock is fine."))


if __name__ == "__main__":
    unittest.main()
