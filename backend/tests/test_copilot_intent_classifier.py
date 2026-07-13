from __future__ import annotations

from datetime import datetime
import unittest
from uuid import UUID

from app.services.copilot.intent_classifier import (
    CopilotIntent,
    CopilotIntentClassifier,
    CopilotIntentConfidence,
    ProductCandidate,
)


SELLER_ID = UUID("00000000-0000-0000-0000-000000000001")
PRODUCT_A_ID = UUID("00000000-0000-0000-0000-000000000010")
PRODUCT_B_ID = UUID("00000000-0000-0000-0000-000000000011")


class _FakeProductResolver:
    def __init__(self, products: list[ProductCandidate]) -> None:
        self.products = products
        self.seller_ids: list[UUID] = []

    def list_products(self, *, seller_id, limit: int = 200):
        self.seller_ids.append(seller_id)
        return self.products[:limit]


class CopilotIntentClassifierTests(unittest.TestCase):
    def _classifier(self, products: list[ProductCandidate] | None = None) -> CopilotIntentClassifier:
        return CopilotIntentClassifier(
            product_resolver=_FakeProductResolver(products or []),
            now=datetime(2026, 7, 5, 10, 30),
            seller_timezone="Asia/Dhaka",
        )

    def test_bangla_restock_question(self):
        result = self._classifier().classify(seller_id=SELLER_ID, question="আমি কোন পণ্য রিস্টক করব?")

        self.assertEqual(CopilotIntent.RESTOCK_ADVICE, result.intent)
        self.assertEqual("bn", result.language)
        self.assertIn("get_restock_recommendations", result.suggested_tools)
        self.assertFalse(result.requires_action_proposal)

    def test_english_restock_question(self):
        result = self._classifier().classify(seller_id=SELLER_ID, question="What should I restock?")

        self.assertEqual(CopilotIntent.RESTOCK_ADVICE, result.intent)
        self.assertEqual("en", result.language)
        self.assertIn("get_inventory_risks", result.suggested_tools)

    def test_revenue_question(self):
        result = self._classifier().classify(seller_id=SELLER_ID, question="Why is revenue down?")

        self.assertEqual(CopilotIntent.REVENUE_DIAGNOSIS, result.intent)
        self.assertEqual(CopilotIntentConfidence.HIGH, result.confidence)
        self.assertEqual(
            [
                "explain_revenue_drop",
                "get_competitor_threats",
                "get_inventory_risks",
                "get_pricing_recommendations",
                "get_promotion_recommendations",
                "retrieve_business_memory",
            ],
            result.suggested_tools,
        )

    def test_competitor_question(self):
        result = self._classifier().classify(seller_id=SELLER_ID, question="Which competitor is hurting me?")

        self.assertEqual(CopilotIntent.COMPETITOR_THREAT_ANALYSIS, result.intent)
        self.assertIn("get_competitor_threats", result.suggested_tools)

    def test_price_change_action_request(self):
        result = self._classifier().classify(seller_id=SELLER_ID, question="Lower price by 5%")

        self.assertEqual(CopilotIntent.ACTION_REQUEST_PRICE_CHANGE, result.intent)
        self.assertTrue(result.requires_action_proposal)
        self.assertTrue(result.requires_confirmation)
        self.assertIn("simulate_price_change", result.suggested_tools)
        self.assertNotIn("apply_price_change", result.suggested_tools)

    def test_promotion_action_request(self):
        result = self._classifier().classify(seller_id=SELLER_ID, question="Generate Eid promotion")

        self.assertEqual(CopilotIntent.ACTION_REQUEST_PROMOTION, result.intent)
        self.assertTrue(result.requires_action_proposal)
        self.assertTrue(result.requires_confirmation)
        self.assertEqual(["get_promotion_recommendations", "get_pricing_recommendations"], result.suggested_tools)

    def test_unknown_question(self):
        result = self._classifier().classify(seller_id=SELLER_ID, question="Can the sky be green?")

        self.assertEqual(CopilotIntent.UNKNOWN, result.intent)
        self.assertEqual(CopilotIntentConfidence.LOW, result.confidence)
        self.assertEqual([], result.suggested_tools)

    def test_product_mention_resolution_is_seller_scoped(self):
        resolver = _FakeProductResolver(
            [
                ProductCandidate(id=PRODUCT_A_ID, title="Product A", category="Gadgets", searchable_text="product a gadgets"),
                ProductCandidate(id=PRODUCT_B_ID, title="Product B", category="Gadgets", searchable_text="product b gadgets"),
            ]
        )
        classifier = CopilotIntentClassifier(product_resolver=resolver, now=datetime(2026, 7, 5, 10, 30))

        result = classifier.classify(seller_id=SELLER_ID, question="Should I restock Product A?")

        self.assertEqual([SELLER_ID], resolver.seller_ids)
        self.assertEqual(1, len(result.product_mentions))
        self.assertEqual(PRODUCT_A_ID, result.product_mentions[0].product_id)
        self.assertIsNone(result.missing_clarification)

    def test_ambiguous_product_mention_requests_clarification(self):
        result = self._classifier(
            [
                ProductCandidate(id=PRODUCT_A_ID, title="USB Charger 20W", category="charger", searchable_text="usb charger fast"),
                ProductCandidate(id=PRODUCT_B_ID, title="USB Charger 30W", category="charger", searchable_text="usb charger fast"),
            ]
        ).classify(seller_id=SELLER_ID, question="Should I restock charger?")

        self.assertEqual(CopilotIntent.RESTOCK_ADVICE, result.intent)
        self.assertIsNotNone(result.missing_clarification)
        self.assertEqual(2, len(result.product_mentions[0].matched_products))

    def test_relative_date_parsing_english_and_bangla(self):
        english = self._classifier().classify(seller_id=SELLER_ID, question="Why was revenue down last week?")
        bangla = self._classifier().classify(seller_id=SELLER_ID, question="গত সপ্তাহে বিক্রি কেন কমেছে?")
        today = self._classifier().classify(seller_id=SELLER_ID, question="What should I do today?")
        yesterday = self._classifier().classify(seller_id=SELLER_ID, question="কাল inventory alerts কী ছিল?")

        self.assertEqual("2026-06-22", english.date_range.from_date.isoformat())
        self.assertEqual("2026-06-28", english.date_range.to_date.isoformat())
        self.assertEqual("2026-06-22", bangla.date_range.from_date.isoformat())
        self.assertEqual("2026-07-05", today.date_range.from_date.isoformat())
        self.assertEqual("2026-07-04", yesterday.date_range.from_date.isoformat())

    def test_action_intent_never_executes_directly(self):
        for question, intent in (
            ("Lower price by 5%", CopilotIntent.ACTION_REQUEST_PRICE_CHANGE),
            ("Generate Eid promotion", CopilotIntent.ACTION_REQUEST_PROMOTION),
            ("Order stock for Product A", CopilotIntent.ACTION_REQUEST_REORDER_PLAN),
        ):
            with self.subTest(question=question):
                result = self._classifier().classify(seller_id=SELLER_ID, question=question)
                self.assertEqual(intent, result.intent)
                self.assertTrue(result.requires_action_proposal)
                self.assertTrue(result.requires_confirmation)
                self.assertFalse(any(tool.startswith("execute_") or tool.startswith("apply_") for tool in result.suggested_tools))

    def test_output_shape_matches_contract(self):
        payload = self._classifier().classify(seller_id=SELLER_ID, question="What should I restock?").to_dict()

        self.assertEqual(
            {
                "intent",
                "confidence",
                "suggested_tools",
                "requires_action_proposal",
                "requires_confirmation",
                "language",
                "product_mentions",
                "date_range",
                "missing_clarification",
            },
            set(payload),
        )


if __name__ == "__main__":
    unittest.main()
