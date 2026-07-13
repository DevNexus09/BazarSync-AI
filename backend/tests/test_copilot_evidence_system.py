from __future__ import annotations

from datetime import datetime, timezone
import unittest

from app.services.copilot.evidence_system import (
    CopilotConfidenceScorer,
    CopilotEvidenceBuilder,
    CopilotFreshnessAnalyzer,
    CopilotMissingDataAggregator,
)
from app.services.copilot.tool_registry import ToolExecutionResult, ToolExecutionStatus


def _result(tool_name: str, *, data=None, evidence=None, missing=None, status=ToolExecutionStatus.SUCCEEDED):
    return ToolExecutionResult(
        tool_name=tool_name,
        tool_version="v1",
        status=status,
        data=data or {},
        evidence=evidence or [],
        missing_data=missing or [],
        error=None if status == ToolExecutionStatus.SUCCEEDED else {"message": "failed"},
        runtime_ms=3,
    )


class CopilotEvidenceSystemTests(unittest.TestCase):
    def test_evidence_built_from_direct_tool(self):
        items = CopilotEvidenceBuilder().build(
            [
                _result(
                    "count_products",
                    data={"count": 2, "product": {"id": "p1", "title": "Product A"}},
                    evidence=[{"source_table": "products", "source_id": "seller_scope", "title": "Products"}],
                )
            ]
        )

        self.assertEqual("PRODUCT_CATALOG", items[0].domain)
        self.assertEqual("products", items[0].source_table)
        self.assertEqual("Product A", items[0].product_name)

    def test_evidence_built_from_rag_memory(self):
        items = CopilotEvidenceBuilder().build(
            [
                _result(
                    "retrieve_business_memory",
                    data={"memory_chunks": [{"evidence_id": "rag:doc:chunk", "snippet": "Old recommendation worked"}]},
                    evidence=[{"evidence_id": "rag:doc:chunk", "source_table": "rag_memory_chunks", "source_id": "chunk"}],
                )
            ]
        )

        self.assertEqual("RAG_MEMORY", items[0].domain)
        self.assertEqual("Old recommendation worked", items[0].snippet)

    def test_missing_data_deduplicated(self):
        items = CopilotMissingDataAggregator().aggregate(
            [
                _result("get_profit_summary", missing=["Missing cost", "Missing cost"]),
                _result("get_pricing_recommendations", missing=["Marketplace fee policy missing."]),
            ]
        )

        keys = [item.key for item in items]
        self.assertEqual(1, keys.count("MISSING_PRODUCT_COST"))
        self.assertIn("MISSING_MARKETPLACE_FEE_POLICY", keys)
        self.assertTrue(next(item for item in items if item.key == "MISSING_PRODUCT_COST").blocking)

    def test_freshness_fresh_stale_missing(self):
        analyzer = CopilotFreshnessAnalyzer()
        fresh = analyzer.analyze([_result("get_revenue_summary", data={"sold_at": datetime.now(timezone.utc).isoformat()}, evidence=[{"source_table": "sales_records", "source_id": "1"}])])[0]
        stale = analyzer.analyze([_result("get_revenue_summary", data={"sold_at": "2024-01-01T00:00:00+00:00"}, evidence=[{"source_table": "sales_records", "source_id": "1"}])])[0]
        missing = analyzer.analyze([_result("get_revenue_summary", data={}, evidence=[])])[0]

        self.assertEqual("FRESH", fresh.status)
        self.assertEqual("STALE", stale.status)
        self.assertEqual("MISSING", missing.status)

    def test_confidence_high_low_and_no_context(self):
        evidence_builder = CopilotEvidenceBuilder()
        missing_aggregator = CopilotMissingDataAggregator()
        freshness_analyzer = CopilotFreshnessAnalyzer()
        scorer = CopilotConfidenceScorer()
        strong_result = _result("count_products", data={"created_at": datetime.now(timezone.utc).isoformat()}, evidence=[{"source_table": "products", "source_id": "1"}])
        strong_evidence = evidence_builder.build([strong_result])
        strong_missing = missing_aggregator.aggregate([strong_result])
        strong_freshness = freshness_analyzer.analyze([strong_result])

        self.assertEqual("HIGH", scorer.score(evidence=strong_evidence, missing_data=strong_missing, freshness=strong_freshness, tool_results=[strong_result]).level)

        stale_result = _result("get_revenue_summary", data={"sold_at": "2024-01-01T00:00:00+00:00"}, evidence=[{"source_table": "sales_records", "source_id": "1"}])
        self.assertEqual(
            "LOW",
            scorer.score(
                evidence=evidence_builder.build([stale_result]),
                missing_data=missing_aggregator.aggregate([stale_result]),
                freshness=freshness_analyzer.analyze([stale_result]),
                tool_results=[stale_result],
            ).level,
        )

        self.assertEqual("NO_CONTEXT", scorer.score(evidence=[], missing_data=[], freshness=[], tool_results=[]).level)


if __name__ == "__main__":
    unittest.main()
