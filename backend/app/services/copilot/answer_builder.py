from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.copilot.intent_classifier import CopilotIntent, CopilotIntentResult
from app.services.copilot.tool_registry import ToolExecutionResult, ToolExecutionStatus


NO_CONTEXT_ANSWER_EN = "I could not find enough seller-specific history to answer this reliably."
NO_CONTEXT_ANSWER_BN = "এই প্রশ্নের নির্ভরযোগ্য উত্তর দেওয়ার মতো পর্যাপ্ত seller-specific তথ্য পাইনি।"
NO_CONTEXT_ANSWER_BANGLISH = "Ei proshner nirbhorjoggo uttor deyar moto jothesto seller-specific tottho pai ni."
NO_CONTEXT_MISSING_LABEL_BANGLISH = "Missing data"
NO_CONTEXT_NEXT_STEP_BANGLISH = "Seller data refresh kore abar jiggesh korun."


@dataclass(frozen=True, slots=True)
class CopilotBuiltAnswer:
    answer: str
    summary: str
    confidence: str
    language: str
    evidence: list[dict[str, Any]]
    missing_data: list[str]
    recommended_next_steps: list[str]
    action_proposal: dict[str, Any] | None = None
    reply_language: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = self._base_payload()
        if self.reply_language:
            payload["reply_language"] = self.reply_language
        return payload

    def _base_payload(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "summary": self.summary,
            "confidence": self.confidence,
            "language": self.language,
            "evidence": self.evidence,
            "missing_data": self.missing_data,
            "recommended_next_steps": self.recommended_next_steps,
            "action_proposal": self.action_proposal,
        }


ANSWER_STRUCTURE_BY_INTENT: dict[CopilotIntent, list[str]] = {
    CopilotIntent.RESTOCK_ADVICE: [
        "Quick recommendation",
        "Products to restock",
        "Why now",
        "Risk level",
        "Suggested quantity",
        "Missing data",
        "Next steps",
    ],
    CopilotIntent.REVENUE_DIAGNOSIS: [
        "Financial summary",
        "Main likely causes",
        "Evidence",
        "Product-level impact",
        "Competitor, pricing, inventory, and promotion factors",
        "Confidence",
        "What to do next",
    ],
    CopilotIntent.COMPETITOR_THREAT_ANALYSIS: [
        "Competitors hurting you most",
        "Affected products",
        "Evidence",
        "Price gap or stock advantage",
        "Recommended response",
        "Safety notes",
    ],
    CopilotIntent.TODAY_ACTIONS: [
        "Top 3 actions",
        "Expected impact",
        "Urgency",
        "Confidence",
        "Evidence",
        "What not to do yet",
    ],
    CopilotIntent.PRICING_ADVICE: [
        "Recommended pricing decision",
        "Margin safety",
        "Expected impact",
        "Blocked reasons",
        "Required missing setup",
    ],
    CopilotIntent.ACTION_REQUEST_PRICE_CHANGE: [
        "Recommended pricing decision",
        "Margin safety",
        "Expected impact",
        "Blocked reasons",
        "Required missing setup",
    ],
    CopilotIntent.PROMOTION_ADVICE: [
        "Promotion recommendation",
        "Product/category",
        "Why this promotion",
        "Safety checks",
        "Expected impact",
        "Missing data",
    ],
    CopilotIntent.ACTION_REQUEST_PROMOTION: [
        "Promotion recommendation",
        "Product/category",
        "Why this promotion",
        "Safety checks",
        "Expected impact",
        "Missing data",
    ],
    CopilotIntent.DEAD_STOCK_RECOVERY: [
        "Dead/at-risk products",
        "Locked capital",
        "Recovery action",
        "Expected recovery range",
        "Missing data",
    ],
    CopilotIntent.SEO_ADVICE: [
        "Listing issues",
        "Suggested improvements",
        "Evidence",
        "Priority",
        "Missing visibility data",
    ],
    CopilotIntent.BUSINESS_MEMORY_SEARCH: [
        "Business memory",
        "Evidence",
        "Missing data",
        "Next steps",
    ],
    CopilotIntent.GENERAL_HELP: [
        "Business overview",
        "Products",
        "Evidence",
        "Missing data",
        "Next steps",
    ],
    CopilotIntent.UNKNOWN: [
        "Business overview",
        "Products",
        "Evidence",
        "Missing data",
        "Next steps",
    ],
}

BN_SECTION_LABELS = {
    "Quick recommendation": "দ্রুত পরামর্শ",
    "Products to restock": "যে পণ্য রিস্টক করা দরকার",
    "Why now": "এখন কেন",
    "Risk level": "ঝুঁকি",
    "Suggested quantity": "প্রস্তাবিত পরিমাণ",
    "Missing data": "যে তথ্য নেই",
    "Next steps": "পরের ধাপ",
    "Main likely causes": "সম্ভাব্য প্রধান কারণ",
    "Evidence": "প্রমাণ",
    "Product-level impact": "পণ্যভিত্তিক প্রভাব",
    "Competitor, pricing, inventory, and promotion factors": "কম্পিটিটর, দাম, ইনভেন্টরি ও প্রমোশন ফ্যাক্টর",
    "Confidence": "কনফিডেন্স",
    "What to do next": "এখন কী করবেন",
    "Competitors hurting you most": "যে কম্পিটিটর সবচেয়ে বেশি চাপ দিচ্ছে",
    "Affected products": "প্রভাবিত পণ্য",
    "Price gap or stock advantage": "দামের পার্থক্য বা স্টক সুবিধা",
    "Recommended response": "প্রস্তাবিত প্রতিক্রিয়া",
    "Safety notes": "সেফটি নোট",
    "Top 3 actions": "আজকের সেরা ৩ কাজ",
    "Expected impact": "সম্ভাব্য প্রভাব",
    "Urgency": "জরুরি মাত্রা",
    "What not to do yet": "এখন যা করবেন না",
    "Recommended pricing decision": "দামের সিদ্ধান্ত",
    "Margin safety": "মার্জিন সেফটি",
    "Blocked reasons": "যে কারণে ব্লক হতে পারে",
    "Required missing setup": "যে সেটআপ/তথ্য দরকার",
    "Promotion recommendation": "প্রমোশন পরামর্শ",
    "Product/category": "পণ্য/ক্যাটাগরি",
    "Why this promotion": "এই প্রমোশন কেন",
    "Safety checks": "সেফটি চেক",
    "Dead/at-risk products": "ডেড/ঝুঁকিতে থাকা পণ্য",
    "Locked capital": "আটকে থাকা মূলধন",
    "Recovery action": "রিকভারি অ্যাকশন",
    "Expected recovery range": "সম্ভাব্য রিকভারি রেঞ্জ",
    "Listing issues": "লিস্টিং সমস্যা",
    "Suggested improvements": "উন্নতির পরামর্শ",
    "Priority": "প্রায়োরিটি",
    "Missing visibility data": "যে visibility data নেই",
    "Business overview": "ব্যবসার সারাংশ",
    "Business memory": "ব্যবসার মেমরি",
    "Products": "পণ্য",
    "Financial summary": "আর্থিক সারাংশ",
}


class CopilotAnswerBuilder:
    def build(
        self,
        *,
        classification: CopilotIntentResult,
        tool_results: list[ToolExecutionResult],
        evidence: list[dict[str, Any]],
        missing_data: list[str],
        action_proposal: dict[str, Any] | None = None,
        reply_language: str | None = None,
    ) -> CopilotBuiltAnswer:
        language = classification.language
        rows_by_tool = _rows_by_tool(tool_results)
        evidence = evidence or _collect_evidence(tool_results)
        missing_data = _dedupe(missing_data + _collect_missing(tool_results))
        if not evidence and not any(rows_by_tool.values()) and reply_language == "banglish":
            answer = NO_CONTEXT_ANSWER_BANGLISH
            if missing_data:
                answer = f"{answer}\n\n{NO_CONTEXT_MISSING_LABEL_BANGLISH}\n- " + "\n- ".join(missing_data)
            return CopilotBuiltAnswer(
                answer=answer,
                summary=answer.splitlines()[0],
                confidence="NO_CONTEXT",
                language="bn",
                evidence=[],
                missing_data=missing_data or ["No seller-specific evidence was available."],
                recommended_next_steps=[NO_CONTEXT_NEXT_STEP_BANGLISH],
                action_proposal=action_proposal,
                reply_language="banglish",
            )
        if not evidence and not any(rows_by_tool.values()):
            answer = NO_CONTEXT_ANSWER_BN if language == "bn" else NO_CONTEXT_ANSWER_EN
            if missing_data:
                answer = f"{answer}\n\n{_section('Missing data', language)}\n- " + "\n- ".join(missing_data)
            return CopilotBuiltAnswer(
                answer=answer,
                summary=answer.splitlines()[0],
                confidence="NO_CONTEXT",
                language=language,
                evidence=[],
                missing_data=missing_data or ["No seller-specific evidence was available."],
                recommended_next_steps=[_text("Refresh seller data, then ask again.", "Seller data refresh করে আবার জিজ্ঞেস করুন।", language)],
                action_proposal=action_proposal,
            )

        sections = list(ANSWER_STRUCTURE_BY_INTENT.get(classification.intent) or ["Answer", "Evidence", "Missing data", "Next steps"])
        if evidence and "Evidence" not in sections:
            insert_at = max(1, len(sections) - 2)
            sections.insert(insert_at, "Evidence")
        confidence = _confidence(tool_results=tool_results, evidence=evidence, missing_data=missing_data)
        answer_parts = [self._section_text(section, language, rows_by_tool, evidence, missing_data, confidence) for section in sections]
        answer_parts.append(_non_execution_note(language))
        answer = "\n\n".join(part for part in answer_parts if part)
        return CopilotBuiltAnswer(
            answer=answer,
            summary=_summary_for_intent(classification.intent, language),
            confidence=confidence,
            language=language,
            evidence=evidence,
            missing_data=missing_data,
            recommended_next_steps=_next_steps(classification.intent, language),
            action_proposal=action_proposal,
        )

    def expected_sections(self, intent: CopilotIntent, *, language: str = "en") -> list[str]:
        return [_section(section, language) for section in ANSWER_STRUCTURE_BY_INTENT.get(intent, ["Answer", "Evidence", "Missing data", "Next steps"])]

    def _section_text(
        self,
        section: str,
        language: str,
        rows_by_tool: dict[str, list[dict[str, Any]]],
        evidence: list[dict[str, Any]],
        missing_data: list[str],
        confidence: str,
    ) -> str:
        label = _section(section, language)
        if section in {"Quick recommendation", "Main likely causes", "Recommended pricing decision", "Promotion recommendation"}:
            return f"{label}\n{_recommendation_line(rows_by_tool, language)}"
        if section == "Business overview":
            return f"{label}\n{_business_overview_lines(rows_by_tool, language)}"
        if section == "Business memory":
            return f"{label}\n{_memory_lines(rows_by_tool, language)}"
        if section == "Financial summary":
            return f"{label}\n{_financial_summary_lines(rows_by_tool, language)}"
        if section == "Products":
            return f"{label}\n{_product_lines(rows_by_tool, language)}"
        if section in {"Products to restock", "Affected products", "Product/category", "Dead/at-risk products"}:
            return f"{label}\n{_bullet_products(rows_by_tool, language)}"
        if section in {"Why now", "Competitor, pricing, inventory, and promotion factors", "Why this promotion"}:
            return f"{label}\n{_factor_lines(rows_by_tool, language)}"
        if section in {"Risk level", "Urgency", "Priority"}:
            return f"{label}\n{_field_lines(rows_by_tool, ('risk_level', 'urgency', 'priority'), language)}"
        if section == "Suggested quantity":
            return f"{label}\n{_field_lines(rows_by_tool, ('reorder_quantity', 'suggested_quantity'), language)}"
        if section in {"Evidence", "Price gap or stock advantage"}:
            return f"{label}\n{_evidence_lines(evidence, language)}"
        if section in {"Expected impact", "Expected recovery range", "Locked capital"}:
            return f"{label}\n{_field_lines(rows_by_tool, ('expected_impact', 'potential_recovery_range', 'locked_capital'), language)}"
        if section in {"Confidence"}:
            return f"{label}\n- {confidence}"
        if section in {"What to do next", "Next steps", "Recommended response"}:
            return f"{label}\n" + "\n".join(f"- {item}" for item in _next_steps_for_rows(rows_by_tool, language))
        if section in {"Safety notes", "Safety checks", "What not to do yet", "Margin safety"}:
            return f"{label}\n- {_non_execution_sentence(language)}\n- {_text('Do not override MarginGuard or missing-data warnings.', 'MarginGuard বা missing-data warning override করবেন না।', language)}"
        if section in {"Blocked reasons", "Required missing setup", "Missing data", "Missing visibility data"}:
            return f"{label}\n{_missing_lines(missing_data, language)}"
        if section in {"Listing issues", "Suggested improvements"}:
            keys = ("issue",) if section == "Listing issues" else ("suggested_improvement",)
            return f"{label}\n{_field_lines(rows_by_tool, keys, language)}"
        if section == "Top 3 actions":
            return f"{label}\n{_top_actions(rows_by_tool, language)}"
        return f"{label}\n{_recommendation_line(rows_by_tool, language)}"


def _rows_by_tool(tool_results: list[ToolExecutionResult]) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    for result in tool_results:
        rows = _extract_rows(result.data)
        output[result.tool_name] = rows
    return output


def _extract_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    for key in ("actions", "recommendations", "risks", "threats", "promotions", "recovery", "opportunities", "memory_chunks", "products", "time_series", "top_products_by_revenue", "likely_factors", "profit_by_product"):
        rows = value.get(key)
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
    overview = value.get("overview")
    if isinstance(overview, dict):
        return [overview]
    product = value.get("product")
    if isinstance(product, dict):
        return [product]
    items = value.get("items")
    if isinstance(items, dict):
        rows = items.get("rows")
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
    if value.get("revenue_change") or value.get("likely_factors") or value.get("gross_revenue") is not None or value.get("estimated_profit") is not None or value.get("revenue_delta") is not None:
        return [value]
    return []


def _recommendation_line(rows_by_tool: dict[str, list[dict[str, Any]]], language: str) -> str:
    first = _first_row(rows_by_tool)
    if not first:
        return _text("No clear recommendation yet because evidence is limited.", "Evidence কম, তাই এখনো পরিষ্কার recommendation নেই।", language)
    product = _product_title(first)
    action = first.get("action_type") or first.get("recommended_action") or first.get("promotion_type") or first.get("recovery_action")
    if product and action:
        return f"- {_text('Start with', 'আগে দেখুন', language)} {product}: {action}."
    if product:
        return f"- {_text('Start with', 'আগে দেখুন', language)} {product}."
    return f"- {_text('Use the top cited evidence before acting.', 'কোনো action নেওয়ার আগে cited evidence দেখুন।', language)}"


def _business_overview_lines(rows_by_tool: dict[str, list[dict[str, Any]]], language: str) -> str:
    overview_rows = rows_by_tool.get("get_business_overview") or []
    overview = overview_rows[0] if overview_rows else None
    if not overview:
        return _text("- No business overview data was returned.", "- Business overview data পাওয়া যায়নি।", language)
    keys = (
        "total_products",
        "products_with_stock",
        "products_missing_cost",
        "products_missing_fee_policy",
        "products_missing_pricing_policy",
        "products_with_inventory_risk",
        "products_with_dead_stock_risk",
        "total_revenue",
        "estimated_profit",
        "active_alerts",
        "pending_recommendations",
    )
    lines = []
    for key in keys:
        if key in overview and overview[key] is not None:
            lines.append(f"- {key.replace('_', ' ')} = {_safe_value(overview[key])}")
    return "\n".join(lines) if lines else _text("- Overview fields are unavailable.", "- Overview field পাওয়া যায়নি।", language)


def _financial_summary_lines(rows_by_tool: dict[str, list[dict[str, Any]]], language: str) -> str:
    lines = []
    for tool_name in ("get_revenue_summary", "get_profit_summary", "explain_revenue_change_deterministic"):
        rows = rows_by_tool.get(tool_name) or []
        row = rows[0] if rows else None
        if not row:
            continue
        for key in (
            "gross_revenue",
            "net_revenue",
            "units_sold",
            "order_count",
            "average_order_value",
            "previous_period_revenue",
            "revenue_change",
            "percentage_change",
            "estimated_profit",
            "margin_rate",
            "revenue_delta",
            "units_sold_delta",
            "average_selling_price_delta",
        ):
            if key in row and row[key] is not None:
                lines.append(f"- {key.replace('_', ' ')} = {_safe_value(row[key])}")
        if row.get("revenue_is_estimated"):
            lines.append(f"- {_text('Revenue is estimated because transaction unit price is missing for some records.', 'কিছু record-এ transaction unit price নেই, তাই revenue estimated।', language)}")
        if row.get("profit_label") == "PARTIAL":
            lines.append(f"- {_text('Profit is partial because some products were excluded.', 'কিছু product বাদ পড়েছে, তাই profit partial।', language)}")
    return "\n".join(lines[:12]) if lines else _text("- Financial figures are unavailable from tools.", "- Tool থেকে financial figure পাওয়া যায়নি।", language)


def _memory_lines(rows_by_tool: dict[str, list[dict[str, Any]]], language: str) -> str:
    rows = rows_by_tool.get("retrieve_business_memory") or rows_by_tool.get("search_business_memory") or []
    if not rows:
        return _text("- No relevant business memory was returned.", "- প্রাসঙ্গিক business memory পাওয়া যায়নি।", language)
    lines = []
    for row in rows[:5]:
        title = row.get("title") or row.get("source_type") or row.get("id") or _text("Memory", "মেমরি", language)
        detail = row.get("summary") or row.get("chunk_text") or row.get("event_time")
        lines.append(f"- {title}" + (f": {_safe_value(detail)}" if detail else ""))
    return "\n".join(lines)


def _product_lines(rows_by_tool: dict[str, list[dict[str, Any]]], language: str) -> str:
    rows = []
    for tool_name in ("get_product_profile", "list_products", "search_products", "get_products_missing_setup", "count_products"):
        rows.extend(rows_by_tool.get(tool_name) or [])
    if not rows:
        return _text("- No product data was returned.", "- Product data পাওয়া যায়নি।", language)
    lines = []
    for row in rows[:8]:
        product = row.get("product") if isinstance(row.get("product"), dict) else row
        title = product.get("name") or product.get("title") or product.get("id") or _text("Product", "পণ্য", language)
        details = []
        for key in ("stock_quantity", "current_stock", "selling_price", "cost_price", "category", "count"):
            if key in product and product[key] not in (None, "", [], {}):
                details.append(f"{key.replace('_', ' ')}: {_safe_value(product[key])}")
            elif key in row and row[key] not in (None, "", [], {}):
                details.append(f"{key.replace('_', ' ')}: {_safe_value(row[key])}")
        missing = row.get("missing_setup_fields") or product.get("missing_setup_data")
        if missing:
            details.append(f"missing: {_safe_value(missing)}")
        lines.append(f"- {title}" + (f" ({'; '.join(details[:3])})" if details else ""))
    return "\n".join(lines)


def _bullet_products(rows_by_tool: dict[str, list[dict[str, Any]]], language: str) -> str:
    rows = _all_rows(rows_by_tool)[:5]
    if not rows:
        return _text("- No product-specific evidence found.", "- পণ্যভিত্তিক evidence পাওয়া যায়নি।", language)
    lines = []
    for row in rows:
        product = _product_title(row) or _text("Unknown product", "অজানা পণ্য", language)
        detail = row.get("risk_level") or row.get("classification") or row.get("recommended_action") or row.get("issue")
        lines.append(f"- {product}" + (f": {detail}" if detail else ""))
    return "\n".join(lines)


def _factor_lines(rows_by_tool: dict[str, list[dict[str, Any]]], language: str) -> str:
    factors = []
    if rows_by_tool.get("get_inventory_risks"):
        factors.append(_text("Inventory risk is present.", "Inventory risk আছে।", language))
    if rows_by_tool.get("get_competitor_threats"):
        factors.append(_text("Competitor pressure is present.", "Competitor pressure আছে।", language))
    if rows_by_tool.get("get_pricing_recommendations"):
        factors.append(_text("Pricing recommendations exist; check MarginGuard.", "Pricing recommendation আছে; MarginGuard দেখুন।", language))
    if rows_by_tool.get("get_promotion_recommendations"):
        factors.append(_text("Promotion signals exist, but campaign creation is not automatic.", "Promotion signal আছে, কিন্তু campaign automatic তৈরি হবে না।", language))
    return "\n".join(f"- {item}" for item in factors) if factors else _text("- Not enough factor data.", "- Factor data পর্যাপ্ত নয়।", language)


def _field_lines(rows_by_tool: dict[str, list[dict[str, Any]]], keys: tuple[str, ...], language: str) -> str:
    lines = []
    for row in _all_rows(rows_by_tool):
        product = _product_title(row)
        for key in keys:
            if key in row and row[key] not in (None, "", [], {}):
                prefix = f"{product}: " if product else ""
                lines.append(f"- {prefix}{key.replace('_', ' ')} = {_safe_value(row[key])}")
                break
        if len(lines) >= 5:
            break
    return "\n".join(lines) if lines else _text("- Data not available from tools.", "- Tool output-এ এই data নেই।", language)


def _top_actions(rows_by_tool: dict[str, list[dict[str, Any]]], language: str) -> str:
    rows = rows_by_tool.get("get_today_actions") or _all_rows(rows_by_tool)
    if not rows:
        return _text("- No prioritized actions found.", "- Prioritized action পাওয়া যায়নি।", language)
    lines = []
    for index, row in enumerate(rows[:3], start=1):
        product = _product_title(row)
        action = row.get("action_type") or row.get("recommended_action") or row.get("recovery_action") or row.get("promotion_type") or _text("Review", "রিভিউ", language)
        lines.append(f"{index}. {action}" + (f" - {product}" if product else ""))
    return "\n".join(lines)


def _evidence_lines(evidence: list[dict[str, Any]], language: str) -> str:
    if not evidence:
        return _text("- No evidence IDs available.", "- Evidence ID পাওয়া যায়নি।", language)
    return "\n".join(f"- {item.get('evidence_id')} ({item.get('source_type')})" for item in evidence[:8])


def _missing_lines(missing_data: list[str], language: str) -> str:
    if not missing_data:
        return _text("- No major missing data reported.", "- বড় কোনো missing data report হয়নি।", language)
    return "\n".join(f"- {item}" for item in missing_data[:8])


def _next_steps_for_rows(rows_by_tool: dict[str, list[dict[str, Any]]], language: str) -> list[str]:
    if rows_by_tool.get("get_restock_recommendations"):
        return [_text("Review reorder quantities and supplier lead time.", "Reorder quantity ও supplier lead time যাচাই করুন।", language)]
    if rows_by_tool.get("get_pricing_recommendations"):
        return [_text("Review MarginGuard before approving any price proposal.", "Price proposal approve করার আগে MarginGuard দেখুন।", language)]
    if rows_by_tool.get("get_competitor_threats"):
        return [_text("Compare competitor price, stock, and ranking before responding.", "Response দেওয়ার আগে competitor price, stock ও ranking মিলিয়ে দেখুন।", language)]
    return [_text("Review cited evidence and ask a narrower follow-up.", "Cited evidence দেখে আরও নির্দিষ্ট follow-up করুন।", language)]


def _next_steps(intent: CopilotIntent, language: str) -> list[str]:
    if intent == CopilotIntent.RESTOCK_ADVICE:
        return [_text("Confirm supplier lead time.", "Supplier lead time নিশ্চিত করুন।", language), _text("Review reorder quantity before ordering.", "Order করার আগে reorder quantity যাচাই করুন।", language)]
    if intent in {CopilotIntent.PRICING_ADVICE, CopilotIntent.ACTION_REQUEST_PRICE_CHANGE}:
        return [_text("Check MarginGuard and approve manually if you choose to proceed.", "MarginGuard দেখে proceed করলে manually approve করুন।", language)]
    if intent in {CopilotIntent.PROMOTION_ADVICE, CopilotIntent.ACTION_REQUEST_PROMOTION}:
        return [_text("Validate margin safety before creating a campaign.", "Campaign করার আগে margin safety যাচাই করুন।", language)]
    return [_text("Review cited evidence before taking action.", "Action নেওয়ার আগে cited evidence দেখুন।", language)]


def _summary_for_intent(intent: CopilotIntent, language: str) -> str:
    label = intent.value.replace("_", " ").title()
    return _text(f"{label} answer built from seller evidence.", f"{label} উত্তর seller evidence থেকে তৈরি।", language)


def _first_row(rows_by_tool: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
    rows = _all_rows(rows_by_tool)
    return rows[0] if rows else None


def _all_rows(rows_by_tool: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for value in rows_by_tool.values():
        rows.extend(value)
    return rows


def _product_title(row: dict[str, Any]) -> str | None:
    for key in ("product", "affected_product"):
        product = row.get(key)
        if isinstance(product, dict) and product.get("title"):
            return str(product["title"])
    return None


def _collect_evidence(tool_results: list[ToolExecutionResult]) -> list[dict[str, Any]]:
    evidence = []
    for result in tool_results:
        for item in result.evidence:
            evidence.append(_normalize_evidence(item, len(evidence)))
    return evidence


def _collect_missing(tool_results: list[ToolExecutionResult]) -> list[str]:
    missing = []
    for result in tool_results:
        missing.extend(result.missing_data)
    return missing


def _confidence(*, tool_results: list[ToolExecutionResult], evidence: list[dict[str, Any]], missing_data: list[str]) -> str:
    successful = [result for result in tool_results if result.status == ToolExecutionStatus.SUCCEEDED and result.evidence]
    if not successful:
        return "NO_CONTEXT"
    if len(successful) >= 2 and len(evidence) >= 2 and not missing_data:
        return "HIGH"
    if evidence:
        return "MEDIUM"
    return "LOW"


def _non_execution_note(language: str) -> str:
    return f"{_section('Safety notes', language)}\n- {_non_execution_sentence(language)}"


def _non_execution_sentence(language: str) -> str:
    return _text("Recommendations do not execute automatically.", "এই recommendation গুলো automatic execute হবে না।", language)


def _section(label: str, language: str) -> str:
    display = BN_SECTION_LABELS.get(label, label) if language == "bn" else label
    return f"**{display}**"


def _text(en: str, bn: str, language: str) -> str:
    return bn if language == "bn" else en


def _safe_value(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{key}: {subvalue}" for key, subvalue in value.items() if subvalue not in (None, "", [], {})) or "available"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value[:3])
    return str(value)


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(str(item) for item in items if item))


def _normalize_evidence(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"evidence_id": f"ev-{index + 1}", "source_type": "unknown", "title": "Evidence", "event_time": None}
    return {
        "evidence_id": str(item.get("evidence_id") or f"{item.get('source_table', 'source')}:{item.get('source_id', index + 1)}"),
        "source_type": str(item.get("source_type") or item.get("source_table") or "unknown"),
        "title": str(item.get("title") or item.get("source_table") or "Evidence"),
        "event_time": item.get("event_time"),
    }
