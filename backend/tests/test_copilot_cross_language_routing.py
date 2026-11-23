"""The same business question asked in English, Banglish and Bangla must plan the same answering tool.

Runs the orchestrator's multilingual planning path (normalize_query -> classifier -> planner) with no LLM,
which is what answers when every model route is down.
"""

from __future__ import annotations

from datetime import datetime
import unittest
from uuid import UUID

from app.services.copilot.entity_resolver import CopilotEntityResolver
from app.services.copilot.intent_classifier import CopilotIntentClassifier
from app.services.copilot.language import normalize_query
from app.services.copilot.question_planner import CopilotQuestionPlanner
from app.services.copilot.tool_registry import CopilotToolRegistry

SELLER_ID = UUID("00000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 7, 5, 10, 0)


class _NoProducts:
    def list_products(self, *, seller_id, limit: int = 200):
        return []


def _plan(question: str):
    text = normalize_query(question).planning_text
    classification = CopilotIntentClassifier(now=NOW, seller_timezone="Asia/Dhaka").classify(seller_id=SELLER_ID, question=text)
    planner = CopilotQuestionPlanner(entity_resolver=CopilotEntityResolver(product_source=_NoProducts()), now=NOW)
    plan = planner.plan(
        seller_id=SELLER_ID, question=text, language=classification.language, conversation_history=[], product_id=None,
        from_date=None, to_date=None, top_k=8, include_memory=True, business_catalog=None, metric_catalog=None,
        tool_registry=CopilotToolRegistry(), classification_hint=classification, max_tools=6, memory_source_types=None,
    )
    return [step for step in plan.tool_plan if step.tool_name != "retrieve_business_memory"]


# (expected tool, required args, phrasings in English / Banglish spellings / Bangla)
CASES = (
    ("count_products", {}, ("How many products do I have?", "amar koyta ponno ache?", "Amar mot koyta product ache?", "kotogulo product ache amar?", "আমার কয়টি পণ্য আছে?")),
    ("count_products", {"status": "LISTED"}, ("How many products are listed?", "amar koyta ponno listed ache", "koyti product listed ache?")),
    ("count_products", {"has_stock": True}, ("How many products are available?", "amar koyti product available ache?", "koyta product stock e ache?")),
    ("get_revenue_summary", {}, ("What were my sales yesterday?", "amar gotokal er bikri koto?", "গতকাল আমার বিক্রি কত?")),
    ("get_restock_recommendations", {}, ("What should I restock?", "ki restock korbo?", "kon product restock korbo?")),
    ("get_today_actions", {}, ("What should I do today?", "ajke ki korbo?")),
)


class CrossLanguageRoutingTests(unittest.TestCase):
    def test_every_phrasing_plans_the_answering_tool(self):
        for tool_name, args, questions in CASES:
            for question in questions:
                with self.subTest(question=question):
                    steps = [step for step in _plan(question) if step.tool_name == tool_name]
                    self.assertTrue(steps, f"{question!r} did not plan {tool_name}")
                    self.assertEqual(args, {key: steps[0].args.get(key) for key in args})

    def test_filtered_counts_are_not_led_by_the_unfiltered_metric(self):
        # The fallback answers from the first tool that succeeds, so an unfiltered total must not come first.
        for question in ("amar koyti product available ache?", "amar koyta ponno listed ache"):
            with self.subTest(question=question):
                first = next(step for step in _plan(question) if step.tool_name in {"run_seller_metric_query", "count_products"})
                self.assertEqual("count_products", first.tool_name)


class TranslationTests(unittest.TestCase):
    def test_banglish_is_rendered_in_word_order_with_planner_plurals(self):
        self.assertEqual("my total how many products have", normalize_query("Amar mot koyta product ache?").translated)
        self.assertEqual("my how many products listed have", normalize_query("amar koyta ponno listed ache").translated)
        self.assertIn("how many orders", normalize_query("October e total koyta order chilo?").translated)

    def test_bangla_count_word_is_translated(self):
        self.assertIn("how many products", normalize_query("আমার কয়টি পণ্য আছে?").translated)

    def test_english_question_is_untouched(self):
        for question in ("How many products do I have?", "What should I restock?"):
            query = normalize_query(question)
            self.assertEqual("", query.translated, question)
            self.assertEqual(query.normalized, query.planning_text, question)


if __name__ == "__main__":
    unittest.main()
