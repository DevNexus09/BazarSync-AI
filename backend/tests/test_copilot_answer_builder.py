from __future__ import annotations

import unittest

from app.services.copilot.answer_builder import CopilotAnswerBuilder
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


class CopilotAnswerBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = CopilotAnswerBuilder()

    def test_restock_answer_returns_expected_structure(self):
        answer = self.builder.build(
            classification=_classification(CopilotIntent.RESTOCK_ADVICE),
            tool_results=[
                _result("get_restock_recommendations", "recommendations", [{"product": {"title": "Product A"}, "risk_level": "HIGH", "reorder_quantity": 12}]),
                _result("get_inventory_risks", "risks", [{"product": {"title": "Product A"}, "risk_level": "HIGH"}]),
            ],
            evidence=[],
            missing_data=["Supplier lead time is stale."],
        )

        for section in ("Quick recommendation", "Products to restock", "Why now", "Risk level", "Suggested quantity", "Missing data", "Next steps"):
            self.assertIn(f"**{section}**", answer.answer)
        self.assertIn("Supplier lead time is stale.", answer.answer)
        self.assertTrue(answer.evidence)

    def test_revenue_diagnosis_returns_expected_structure(self):
        answer = self.builder.build(
            classification=_classification(CopilotIntent.REVENUE_DIAGNOSIS),
            tool_results=[
                _result("explain_revenue_drop", "recommendations", [{"likely_factors": [{"reason": "Inventory risk"}]}]),
                _result("get_competitor_threats", "threats", [{"affected_product": {"title": "Product A"}, "threat_reason": "PRICE_DROP"}]),
                _result("get_inventory_risks", "risks", [{"product": {"title": "Product A"}, "risk_level": "HIGH"}]),
                _result("get_pricing_recommendations", "recommendations", [{"product": {"title": "Product A"}, "recommended_action": "HOLD"}]),
                _result("get_promotion_recommendations", "promotions", [{"product": {"title": "Product A"}, "promotion_type": "DISCOUNT"}]),
            ],
            evidence=[],
            missing_data=[],
        )

        for section in ("Main likely causes", "Evidence", "Product-level impact", "Competitor, pricing, inventory, and promotion factors", "Confidence", "What to do next"):
            self.assertIn(f"**{section}**", answer.answer)
        self.assertIn("Competitor pressure", answer.answer)

    def test_competitor_threat_returns_expected_structure(self):
        answer = self.builder.build(
            classification=_classification(CopilotIntent.COMPETITOR_THREAT_ANALYSIS),
            tool_results=[
                _result("get_competitor_threats", "threats", [{"affected_product": {"title": "Product A"}, "price_gap": "-10", "threat_reason": "PRICE_DROP"}]),
                _result("get_pricing_recommendations", "recommendations", [{"product": {"title": "Product A"}, "recommended_action": "HOLD"}]),
            ],
            evidence=[],
            missing_data=[],
        )

        for section in ("Competitors hurting you most", "Affected products", "Evidence", "Price gap or stock advantage", "Recommended response", "Safety notes"):
            self.assertIn(f"**{section}**", answer.answer)
        self.assertIn("Recommendations do not execute automatically", answer.answer)

    def test_today_actions_returns_expected_structure(self):
        answer = self.builder.build(
            classification=_classification(CopilotIntent.TODAY_ACTIONS),
            tool_results=[
                _result("get_today_actions", "actions", [{"product": {"title": "Product A"}, "action_type": "REORDER", "urgency": "HIGH"}]),
                _result("get_dead_stock_recovery", "recovery", [{"product": {"title": "Product B"}, "recovery_action": "DISCOUNT"}]),
            ],
            evidence=[],
            missing_data=[],
        )

        for section in ("Top 3 actions", "Expected impact", "Urgency", "Confidence", "Evidence", "What not to do yet"):
            self.assertIn(f"**{section}**", answer.answer)
        self.assertIn("REORDER", answer.answer)

    def test_pricing_answer_returns_expected_structure(self):
        answer = self.builder.build(
            classification=_classification(CopilotIntent.PRICING_ADVICE),
            tool_results=[
                _result("get_pricing_recommendations", "recommendations", [{"product": {"title": "Product A"}, "recommended_action": "PRICE_LOWER", "margin_safety": {"safe": True}, "expected_impact": {"profit": "tool-value"}}]),
            ],
            evidence=[],
            missing_data=["Marketplace fee policy missing."],
        )

        for section in ("Recommended pricing decision", "Margin safety", "Expected impact", "Blocked reasons", "Required missing setup"):
            self.assertIn(f"**{section}**", answer.answer)
        self.assertIn("Marketplace fee policy missing.", answer.answer)

    def test_promotion_answer_returns_expected_structure(self):
        answer = self.builder.build(
            classification=_classification(CopilotIntent.PROMOTION_ADVICE),
            tool_results=[
                _result("get_promotion_recommendations", "promotions", [{"product": {"title": "Product A"}, "promotion_type": "DISCOUNT", "expected_impact": {"revenue": "tool-value"}}]),
                _result("get_pricing_recommendations", "recommendations", [{"product": {"title": "Product A"}, "margin_safety": {"safe": True}}]),
            ],
            evidence=[],
            missing_data=[],
        )

        for section in ("Promotion recommendation", "Product/category", "Why this promotion", "Safety checks", "Expected impact", "Missing data"):
            self.assertIn(f"**{section}**", answer.answer)

    def test_dead_stock_answer_returns_expected_structure(self):
        answer = self.builder.build(
            classification=_classification(CopilotIntent.DEAD_STOCK_RECOVERY),
            tool_results=[
                _result("get_dead_stock_recovery", "recovery", [{"product": {"title": "Product A"}, "locked_capital": "tool-value", "recovery_action": "BUNDLE", "potential_recovery_range": {"low": "tool-low"}}]),
            ],
            evidence=[],
            missing_data=[],
        )

        for section in ("Dead/at-risk products", "Locked capital", "Recovery action", "Expected recovery range", "Missing data"):
            self.assertIn(f"**{section}**", answer.answer)

    def test_seo_answer_returns_expected_structure(self):
        answer = self.builder.build(
            classification=_classification(CopilotIntent.SEO_ADVICE),
            tool_results=[
                _result("get_seo_opportunities", "opportunities", [{"product": {"title": "Product A"}, "issue": "Low quality score", "suggested_improvement": "Improve title"}]),
            ],
            evidence=[],
            missing_data=["Visibility history is incomplete."],
        )

        for section in ("Listing issues", "Suggested improvements", "Evidence", "Priority", "Missing visibility data"):
            self.assertIn(f"**{section}**", answer.answer)
        self.assertIn("Visibility history is incomplete.", answer.answer)

    def test_bangla_answer_quality(self):
        answer = self.builder.build(
            classification=_classification(CopilotIntent.RESTOCK_ADVICE, language="bn"),
            tool_results=[
                _result("get_restock_recommendations", "recommendations", [{"product": {"title": "Product A"}, "risk_level": "HIGH", "reorder_quantity": 12}]),
            ],
            evidence=[],
            missing_data=["Supplier lead time নেই।"],
        )

        self.assertIn("**দ্রুত পরামর্শ**", answer.answer)
        self.assertIn("automatic execute হবে না", answer.answer)
        self.assertEqual("bn", answer.language)

    def test_english_answer_quality_missing_data_evidence_and_no_fake_numbers(self):
        answer = self.builder.build(
            classification=_classification(CopilotIntent.RESTOCK_ADVICE),
            tool_results=[
                _result("get_restock_recommendations", "recommendations", [{"product": {"title": "Product A"}, "risk_level": "HIGH", "reorder_quantity": 12}]),
            ],
            evidence=[],
            missing_data=["Sales velocity is missing."],
        )

        self.assertIn("**Evidence**", answer.answer)
        self.assertIn("Sales velocity is missing.", answer.answer)
        self.assertNotIn("999", answer.answer)
        self.assertNotIn("{", answer.answer)
        self.assertTrue(answer.evidence)


if __name__ == "__main__":
    unittest.main()
