from __future__ import annotations

import unittest

from app.models.rag_memory import RagMemorySourceType
from app.services.rag_memory_source_registry import RAG_SOURCE_REGISTRY, implemented_source_types


class RagMemorySourceRegistryTruthfulTests(unittest.TestCase):
    def test_required_sources_report_implementation_state(self):
        required = {
            RagMemorySourceType.PRODUCT_PROFILE,
            RagMemorySourceType.SALES_HISTORY,
            RagMemorySourceType.SALES_REVENUE_SUMMARY,
            RagMemorySourceType.INVENTORY_LIFECYCLE,
            RagMemorySourceType.PRICING_HISTORY,
            RagMemorySourceType.COMPETITOR_HISTORY,
            RagMemorySourceType.DEAD_STOCK_HISTORY,
            RagMemorySourceType.SEO_VISIBILITY_HISTORY,
            RagMemorySourceType.ALERT_HISTORY,
            RagMemorySourceType.RECOMMENDATION_HISTORY,
            RagMemorySourceType.COPILOT_HISTORY,
            RagMemorySourceType.PROMOTION_PLAN,
            RagMemorySourceType.PROMOTION_RESULT,
            RagMemorySourceType.SELLER_PRICE_HISTORY,
        }

        self.assertTrue(required.issubset(RAG_SOURCE_REGISTRY))
        for source_type in required:
            with self.subTest(source_type=source_type):
                definition = RAG_SOURCE_REGISTRY[source_type]
                self.assertTrue(definition.implemented)
                self.assertTrue(definition.adapter_function)
                self.assertTrue(definition.builder_function)
                self.assertTrue(definition.seller_field or definition.product_field)
                self.assertNotEqual("future_extension", definition.chunking_rules.get("mode"))

    def test_future_sources_are_not_marked_implemented(self):
        self.assertFalse(RAG_SOURCE_REGISTRY[RagMemorySourceType.CUSTOMER_CONTEXT].implemented)
        self.assertFalse(RAG_SOURCE_REGISTRY[RagMemorySourceType.SUPPORT_LOG].implemented)
        self.assertFalse(RAG_SOURCE_REGISTRY[RagMemorySourceType.ACTION_CENTER].implemented)

    def test_implemented_source_types_excludes_unimplemented_sources(self):
        implemented = set(implemented_source_types())

        self.assertIn(RagMemorySourceType.PRODUCT_PROFILE, implemented)
        self.assertIn(RagMemorySourceType.PROMOTION_RESULT, implemented)
        self.assertNotIn(RagMemorySourceType.CUSTOMER_CONTEXT, implemented)


if __name__ == "__main__":
    unittest.main()
