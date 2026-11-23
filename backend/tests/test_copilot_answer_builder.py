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


WEEK = {"from_date": "2026-11-16", "to_date": "2026-11-22", "label": "last 7 din", "defaulted": False}
WEEK_FILTERS = {"from_date": "2026-11-16", "to_date": "2026-11-22"}


def _data_result(tool_name: str, data: dict) -> ToolExecutionResult:
    evidence = [{"source_table": tool_name, "source_id": "1"}]
    return ToolExecutionResult(tool_name=tool_name, tool_version="v1", status=ToolExecutionStatus.SUCCEEDED, data={**data, "missing_data": []}, evidence=evidence, missing_data=[], error=None, runtime_ms=1)


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

    def test_empty_period_says_no_sales_recorded_not_zero_revenue(self):
        # Review Focus 5: an observed zero is "no sales recorded", never "gross revenue: 0".
        empty = ToolExecutionResult(
            tool_name="get_revenue_summary",
            tool_version="v1",
            status=ToolExecutionStatus.SUCCEEDED,
            data={"gross_revenue": "0", "units_sold": 0, "order_count": 0, "top_products_by_revenue": [], "evidence": [], "missing_data": []},
            evidence=[],
            missing_data=[],
            error=None,
            runtime_ms=1,
        )

        answer = self.builder.build(classification=_classification(CopilotIntent.REVENUE_DIAGNOSIS), tool_results=[empty], evidence=[{"source_table": "sales_records", "source_id": "x"}], missing_data=[])

        self.assertIn("No sales found for this period", answer.answer)
        self.assertNotIn("gross revenue: 0", answer.answer)
        self.assertNotIn("order count: 0", answer.answer)

        profit = ToolExecutionResult(tool_name="get_profit_summary", tool_version="v1", status=ToolExecutionStatus.SUCCEEDED, data={"gross_revenue": "0", "estimated_profit": "0", "missing_data": []}, evidence=[], missing_data=[], error=None, runtime_ms=1)
        both = self.builder.build(classification=_classification(CopilotIntent.REVENUE_DIAGNOSIS), tool_results=[empty, profit], evidence=[{"source_table": "sales_records", "source_id": "x"}], missing_data=[])
        self.assertEqual(1, both.answer.count("No sales found for this period"))
        self.assertNotIn(": 0", both.answer)

    def test_banglish_fallback_uses_latin_header_and_only_primary_tool_rows(self):
        revenue = _data_result("get_revenue_summary", {"gross_revenue": "93503.00", "order_count": 40, "units_sold": 61, "filters_used": WEEK_FILTERS})
        risks = _result("get_inventory_risks", "risks", [{"product": {"title": "Unrelated Risky Shoe"}, "risk_level": "HIGH"}])

        answer = self.builder.build(
            classification=_classification(CopilotIntent.REVENUE_DIAGNOSIS, language="bn"),
            tool_results=[revenue, risks], evidence=[{"source_table": "sales_records", "source_id": "x"}], missing_data=[],
            reply_language="banglish", primary_tools={"get_revenue_summary"}, period=WEEK,
        )

        self.assertTrue(answer.answer.startswith("Apnar data theke (2026-11-16 theke 2026-11-22):"), answer.answer)
        self.assertIn("93503.00", answer.answer)
        self.assertNotIn("Unrelated Risky Shoe", answer.answer)
        self.assertFalse(any("\u0980" <= char <= "\u09ff" for char in answer.answer), answer.answer)

    def test_fallback_no_sales_line_names_last_recorded_sale_date(self):
        yesterday = {"from_date": "2026-11-21", "to_date": "2026-11-21", "label": "gotokal", "defaulted": False}
        zero = {"gross_revenue": "0", "order_count": 0, "units_sold": 0, "filters_used": {"from_date": "2026-11-21", "to_date": "2026-11-21"}}

        proven = self.builder.build(classification=_classification(CopilotIntent.REVENUE_DIAGNOSIS), tool_results=[_data_result("get_revenue_summary", zero | {"latest_recorded_sale_date": "2026-11-19"})], evidence=[{"source_table": "sales_records", "source_id": "x"}], missing_data=[], primary_tools={"get_revenue_summary"}, period=yesterday)
        unproven = self.builder.build(classification=_classification(CopilotIntent.REVENUE_DIAGNOSIS), tool_results=[_data_result("get_revenue_summary", zero)], evidence=[{"source_table": "sales_records", "source_id": "x"}], missing_data=[], primary_tools={"get_revenue_summary"}, period=yesterday)

        self.assertIn("No sales recorded for this period; last recorded sale: 2026-11-19", proven.answer)
        self.assertNotIn("No sales recorded", unproven.answer)
        self.assertIn("could not be confirmed", unproven.answer)
        self.assertNotIn(": 0", proven.answer + unproven.answer)

    def test_fallback_omits_inventory_risk_rows_for_a_sales_question(self):
        revenue = _data_result("get_revenue_summary", {"gross_revenue": "93503.00", "order_count": 40, "units_sold": 61, "filters_used": WEEK_FILTERS})
        risks = _result("get_inventory_risks", "risks", [{"product": {"title": "Unrelated Risky Shoe"}, "risk_level": "HIGH"}])

        answer = self.builder.build(classification=_classification(CopilotIntent.RESTOCK_ADVICE), tool_results=[risks, revenue], evidence=[{"source_table": "sales_records", "source_id": "x"}], missing_data=[], primary_tools={"get_revenue_summary"}, period=WEEK)

        self.assertTrue(answer.answer.startswith("From your data (2026-11-16 to 2026-11-22):"), answer.answer)
        self.assertIn("gross revenue: 93503.00", answer.answer)
        self.assertNotIn("Unrelated Risky Shoe", answer.answer)
        self.assertNotIn("restock", answer.answer.lower())

    def test_fallback_answers_from_records_and_product_profile_facts(self):
        records = _data_result("query_business_records", {"entity": "sales", "aggregate": "sum", "measure": "revenue", "group_by": "weekday", "rows": [{"weekday": "Friday", "is_weekend": True, "value": "33676.00", "row_count": 12}], "row_count": 12})
        profile = _data_result("get_product_profile", {"product": {"name": "Power XORISE", "current_stock": 14, "selling_price": "3374.00"}})
        default = {"from_date": "2016-11-24", "to_date": "2026-11-22", "label": "all recorded history (no period given)", "defaulted": True}

        answer = self.builder.build(classification=_classification(CopilotIntent.UNKNOWN), tool_results=[records, profile], evidence=[{"source_table": "sales_records", "source_id": "x"}], missing_data=[], primary_tools={"query_business_records", "get_product_profile"}, period=default)

        self.assertTrue(answer.answer.startswith("From your data (all recorded history):"), answer.answer)
        self.assertIn("Friday: 33676.00", answer.answer)
        self.assertIn("Power XORISE: stock 14, price 3374.00", answer.answer)

    def test_fallback_states_a_count_tool_result_in_the_reply_script(self):
        count = _data_result("count_products", {"count": 15, "filters_used": {}})

        bangla = self.builder.build(classification=_classification(CopilotIntent.UNKNOWN, language="bn"), tool_results=[count], evidence=[{"source_table": "products", "source_id": "x"}], missing_data=[], reply_language="bn", primary_tools={"count_products"}, period=None)

        self.assertIn("15", bangla.answer)
        self.assertTrue(bangla.answer.startswith("আপনার ডেটা থেকে"), bangla.answer)

    def test_fallback_states_a_calculated_metric(self):
        metric = _data_result("run_seller_metric_query", {"metric_key": "product_count", "status": "CALCULATED", "value": 15, "rows": [{"title": "Shoe"}], "unit": "count"})

        for lang, header in (("en", "From your data"), ("banglish", "Apnar data theke")):
            answer = self.builder.build(classification=_classification(CopilotIntent.UNKNOWN), tool_results=[metric], evidence=[{"source_table": "products", "source_id": "x"}], missing_data=[], reply_language=lang, primary_tools={"run_seller_metric_query"}, period=None)
            self.assertTrue(answer.answer.startswith(header), answer.answer)
            self.assertIn("product count: 15", answer.answer)

    def test_fallback_never_prints_a_zero_sales_metric(self):
        metric = _data_result("run_seller_metric_query", {"metric_key": "gross_revenue", "status": "CALCULATED", "value": "0.00", "currency": "BDT"})

        answer = self.builder.build(classification=_classification(CopilotIntent.REVENUE_DIAGNOSIS), tool_results=[metric], evidence=[{"source_table": "sales_records", "source_id": "x"}], missing_data=[], primary_tools={"run_seller_metric_query"}, period=WEEK)

        self.assertNotIn("0.00", answer.answer)

    def test_fallback_uses_other_tools_when_the_primary_has_no_readable_fact(self):
        # A metric the builder cannot read (a trend series) must not hide the revenue summary beside it.
        trend = _data_result("run_seller_metric_query", {"metric_key": "revenue_trend", "status": "CALCULATED", "value": None, "rows": [{"day": "2026-11-16", "value": "10.00"}]})
        revenue = _data_result("get_revenue_summary", {"gross_revenue": "93503.00", "order_count": 40, "units_sold": 61, "filters_used": WEEK_FILTERS})

        answer = self.builder.build(classification=_classification(CopilotIntent.REVENUE_DIAGNOSIS), tool_results=[trend, revenue], evidence=[{"source_table": "sales_records", "source_id": "x"}], missing_data=[], primary_tools={"run_seller_metric_query"}, period=WEEK)

        self.assertIn("gross revenue: 93503.00", answer.answer)
        self.assertNotIn("could not find", answer.answer)

    def test_listed_count_states_the_account_total_first(self):
        count = _data_result("count_products", {"count": 14, "filters_used": {"listed": True}, "listing_summary": {"total_products_in_account": 15, "products_with_active_marketplace_listing": 14, "how_to_answer": "..."}})

        answer = self.builder.build(classification=_classification(CopilotIntent.UNKNOWN), tool_results=[count], evidence=[{"source_table": "products", "source_id": "x"}], missing_data=[], reply_language="banglish", primary_tools={"count_products"}, period=None)

        self.assertEqual(["- total products in account: 15", "- products with active marketplace listing: 14"], answer.answer.splitlines()[1:])

    def test_product_list_rows_are_named_without_a_period_or_primary_tool(self):
        products = _result("list_products", "products", [{"id": "1", "title": "Lex Loafer", "stock_quantity": 9}])

        answer = self.builder.build(classification=_classification(CopilotIntent.UNKNOWN), tool_results=[products], evidence=[{"source_table": "products", "source_id": "1"}], missing_data=[], reply_language="banglish")

        self.assertIn("Lex Loafer", answer.answer)
        self.assertNotIn("porishkar", answer.answer)

    def test_fallback_shows_memory_only_for_memory_questions(self):
        memory = _result("retrieve_business_memory", "memory_chunks", [{"title": "Supplier delay note", "summary": "late in March"}])
        revenue = _data_result("get_revenue_summary", {"gross_revenue": "250.00", "order_count": 3, "units_sold": 4})

        sales = self.builder.build(classification=_classification(CopilotIntent.REVENUE_DIAGNOSIS), tool_results=[revenue, memory], evidence=[{"source_table": "sales_records", "source_id": "x"}], missing_data=[], period=WEEK)
        history = self.builder.build(classification=_classification(CopilotIntent.BUSINESS_MEMORY_SEARCH), tool_results=[memory], evidence=[{"source_table": "sales_records", "source_id": "x"}], missing_data=[], period=WEEK)

        self.assertNotIn("Supplier delay note", sales.answer)
        self.assertIn("Supplier delay note", history.answer)

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
