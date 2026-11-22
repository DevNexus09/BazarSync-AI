from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import unittest

from app.services.copilot.context_builder import CopilotContextBuilder
from app.services.copilot.date_range_parser import CopilotDateRangeParser, default_period
from app.services.copilot.entity_resolver import CopilotEntityResolver
from app.services.copilot.intent_classifier import CopilotIntentClassifier
from app.services.copilot.language.normalizer import normalize_query
from app.services.copilot.question_planner import CopilotQuestionPlanner
from app.services.copilot.tool_registry import CopilotToolRegistry
from tests.test_copilot_question_planner import SELLER_ID, _FakeProductSource

# Sunday 2026-11-22, 21:00 in Dhaka (15:00 UTC).
NOW = datetime(2026, 11, 22, 21, 0, tzinfo=timezone(timedelta(hours=6)))


class DateRangeParserTests(unittest.TestCase):
    def assertRange(self, question: str, start: str, end: str) -> None:
        for text in (question, normalize_query(question).planning_text):
            parsed = CopilotDateRangeParser(now=NOW).parse(text).date_range
            self.assertIsNotNone(parsed, text)
            self.assertEqual((date.fromisoformat(start), date.fromisoformat(end)), (parsed.from_date, parsed.to_date), text)

    def test_banglish_and_english_periods(self) -> None:
        self.assertRange("Last 7 din e amar revenue koto?", "2026-11-16", "2026-11-22")
        self.assertRange("Ei shoptahe koyta order paisi?", "2026-11-16", "2026-11-22")
        self.assertRange("October e amar estimated profit koto?", "2026-10-01", "2026-10-31")
        self.assertRange("December er sales", "2025-12-01", "2025-12-31")
        self.assertRange("November er prothom 15 dine", "2026-11-01", "2026-11-15")
        self.assertRange("Gotokal koto taka bikri hoise?", "2026-11-21", "2026-11-21")
        self.assertRange("Ei bochor e total revenue", "2026-01-01", "2026-11-22")
        self.assertRange("ajke koyta order?", "2026-11-22", "2026-11-22")
        self.assertRange("Goto shoptahe sales koto?", "2026-11-09", "2026-11-15")
        self.assertRange("gotomash er profit", "2026-10-01", "2026-10-31")
        self.assertRange("ei mashe sales", "2026-11-01", "2026-11-22")
        self.assertRange("May mashe koto sale?", "2026-05-01", "2026-05-31")

    def test_current_month_name_is_clamped_to_today(self) -> None:
        self.assertRange("November er sales", "2026-11-01", "2026-11-22")

    def test_modal_may_is_not_a_month(self) -> None:
        self.assertIsNone(CopilotDateRangeParser(now=NOW).parse("Which products may run out of stock?").date_range)

    def test_iso_pair_unchanged(self) -> None:
        parsed = CopilotDateRangeParser(now=NOW).parse("revenue from 2026-01-05 to 2026-02-10").date_range
        self.assertEqual((date(2026, 1, 5), date(2026, 2, 10), "2026-01-05 to 2026-02-10"), (parsed.from_date, parsed.to_date, parsed.source_text))

    def test_default_period_spans_recorded_history(self) -> None:
        period = default_period(date(2026, 11, 22))
        self.assertEqual((date(2016, 11, 24), date(2026, 11, 22)), (period.from_date, period.to_date))
        self.assertTrue(period.defaulted)
        self.assertIn("no period given", period.source_text)


class NoPeriodPlanningTests(unittest.TestCase):
    def _plan(self, question: str):
        classification = CopilotIntentClassifier(now=NOW, seller_timezone="Asia/Dhaka").classify(seller_id=SELLER_ID, question=question)
        planner = CopilotQuestionPlanner(entity_resolver=CopilotEntityResolver(product_source=_FakeProductSource([])), now=NOW)
        return planner.plan(
            seller_id=SELLER_ID, question=question, language=classification.language, conversation_history=[], product_id=None,
            from_date=None, to_date=None, top_k=8, include_memory=True, business_catalog=None, metric_catalog=None,
            tool_registry=CopilotToolRegistry(), classification_hint=classification, max_tools=10, memory_source_types=None,
        )

    def test_no_period_uses_stated_default_for_every_dated_tool(self) -> None:
        plan = self._plan("Amar average order value koto?")
        dated = [step for step in plan.tool_plan if step.args.get("from_date") is not None]
        self.assertIn("get_revenue_summary", {step.tool_name for step in dated})
        for step in dated:
            self.assertEqual(("2016-11-24", "2026-11-22"), (str(step.args["from_date"]), str(step.args["to_date"])), step.tool_name)
        self.assertIn("no period given", plan.entities.date_range["source_text"])

    def test_default_period_does_not_filter_memory_search(self) -> None:
        # Memory search drops undated documents under a date filter, so "no period" stays unfiltered there.
        plan = self._plan("Amar business er memory te ki ache?")
        for step in plan.tool_plan:
            if step.tool_name == "retrieve_business_memory":
                self.assertIsNone(step.args.get("from_date"))

    def test_resolved_period_reaches_the_prompt(self) -> None:
        plan = self._plan("Last 7 din e amar revenue koto?")
        payload = CopilotContextBuilder().build(question="Last 7 din e amar revenue koto?", plan=plan, tool_results=[], missing_data=[]).to_prompt_payload()
        self.assertEqual({"from_date": "2026-11-16", "to_date": "2026-11-22", "label": "last 7 days", "defaulted": False}, payload["period"])


if __name__ == "__main__":
    unittest.main()
