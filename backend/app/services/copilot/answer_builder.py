from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Iterable

from app.services.copilot.intent_classifier import CopilotIntent, CopilotIntentResult
from app.services.copilot.tool_registry import ToolExecutionResult, ToolExecutionStatus


NO_CONTEXT_ANSWER_EN = "I could not find enough seller-specific history to answer this reliably."
NO_CONTEXT_ANSWER_BN = "এই প্রশ্নের নির্ভরযোগ্য উত্তর দেওয়ার মতো পর্যাপ্ত seller-specific তথ্য পাইনি।"
NO_CONTEXT_ANSWER_BANGLISH = "Ei proshner nirbhorjoggo uttor deyar moto jothesto seller-specific tottho pai ni."
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


# Lead sentence per intent; the answer is this line, one line per product, and at most one next step.
LEAD_BY_INTENT: dict[CopilotIntent, tuple[str, str]] = {
    CopilotIntent.RESTOCK_ADVICE: ("These products need restocking:", "এই পণ্যগুলো রিস্টক করা দরকার:"),
    CopilotIntent.REVENUE_DIAGNOSIS: ("Here is what changed in your sales:", "আপনার বিক্রিতে যা বদলেছে:"),
    CopilotIntent.COMPETITOR_THREAT_ANALYSIS: ("These products face the most competitor pressure:", "এই পণ্যগুলোতে কম্পিটিটরের চাপ সবচেয়ে বেশি:"),
    CopilotIntent.TODAY_ACTIONS: ("Do these first today:", "আজ আগে এগুলো করুন:"),
    CopilotIntent.PRICING_ADVICE: ("Here is the pricing suggestion:", "দামের পরামর্শ:"),
    CopilotIntent.ACTION_REQUEST_PRICE_CHANGE: ("Here is the pricing suggestion:", "দামের পরামর্শ:"),
    CopilotIntent.PROMOTION_ADVICE: ("These products are good for a promotion:", "এই পণ্যগুলো প্রমোশনের জন্য ভালো:"),
    CopilotIntent.ACTION_REQUEST_PROMOTION: ("These products are good for a promotion:", "এই পণ্যগুলো প্রমোশনের জন্য ভালো:"),
    CopilotIntent.DEAD_STOCK_RECOVERY: ("These products are stuck in stock:", "এই পণ্যগুলো স্টকে আটকে আছে:"),
    CopilotIntent.SEO_ADVICE: ("These listings need improvement:", "এই লিস্টিংগুলো উন্নত করা দরকার:"),
    CopilotIntent.BUSINESS_MEMORY_SEARCH: ("Here is what your business history shows:", "আপনার ব্যবসার ইতিহাসে যা পাওয়া গেছে:"),
}
DEFAULT_LEAD = ("Here is your business summary:", "আপনার ব্যবসার সারাংশ:")
NOTHING_FOUND = ("I could not find a clear answer in your data yet.", "আপনার ডেটায় এখনো পরিষ্কার উত্তর পাইনি।")
MAX_LIST_LINES = 8

OVERVIEW_TOOLS = ("get_business_overview",)
FINANCIAL_TOOLS = ("get_revenue_summary", "get_profit_summary", "explain_revenue_change_deterministic")
MEMORY_TOOLS = ("retrieve_business_memory", "search_business_memory")

# Ordered: the first field present on a row is that product's key number.
PRODUCT_KEY_FIELDS: tuple[tuple[str, str | None], ...] = (
    ("reorder_quantity", "reorder"),
    ("suggested_quantity", "reorder"),
    ("locked_capital", "locked capital"),
    ("recommended_price", "price"),
    ("price_gap", "price gap"),
    ("action_type", None),
    ("recommended_action", None),
    ("recovery_action", None),
    ("promotion_type", None),
    ("suggested_improvement", None),
    ("issue", None),
    ("missing_setup_fields", "missing"),
    ("units_sold", "sold"),
    ("stock_quantity", "stock"),
    ("current_stock", "stock"),
    ("risk_level", "risk"),
    ("urgency", "urgency"),
)


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
            return CopilotBuiltAnswer(
                answer=NO_CONTEXT_ANSWER_BANGLISH,
                summary=NO_CONTEXT_ANSWER_BANGLISH,
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
            return CopilotBuiltAnswer(
                answer=answer,
                summary=answer,
                confidence="NO_CONTEXT",
                language=language,
                evidence=[],
                missing_data=missing_data or ["No seller-specific evidence was available."],
                recommended_next_steps=[_text("Refresh seller data, then ask again.", "Seller data refresh করে আবার জিজ্ঞেস করুন।", language)],
                action_proposal=action_proposal,
            )

        lines = _answer_lines(classification.intent, rows_by_tool)
        next_step = _next_step(classification.intent, language) if lines else None
        lead = _text(*(LEAD_BY_INTENT.get(classification.intent, DEFAULT_LEAD) if lines else NOTHING_FOUND), language)
        answer = "\n".join([lead, *(f"- {line}" for line in lines)])
        if next_step:
            answer = f"{answer}\n\n{next_step}"
        return CopilotBuiltAnswer(
            answer=answer,
            summary=lead,
            confidence=_confidence(tool_results=tool_results, evidence=evidence, missing_data=missing_data),
            language=language,
            evidence=evidence,
            missing_data=missing_data,
            recommended_next_steps=[next_step] if next_step else [],
            action_proposal=action_proposal,
        )


# Revenue/overview figures only answer "how is my business / sales" questions, not restock or pricing ones.
SUMMARY_INTENTS = {CopilotIntent.REVENUE_DIAGNOSIS, CopilotIntent.GENERAL_HELP, CopilotIntent.UNKNOWN}
# When this tool returned rows, its products alone answer the question; other tools' products are context.
PRIMARY_TOOL_BY_INTENT: dict[CopilotIntent, str] = {
    CopilotIntent.RESTOCK_ADVICE: "get_restock_recommendations",
    CopilotIntent.COMPETITOR_THREAT_ANALYSIS: "get_competitor_threats",
    CopilotIntent.TODAY_ACTIONS: "get_today_actions",
    CopilotIntent.PRICING_ADVICE: "get_pricing_recommendations",
    CopilotIntent.ACTION_REQUEST_PRICE_CHANGE: "get_pricing_recommendations",
    CopilotIntent.PROMOTION_ADVICE: "get_promotion_recommendations",
    CopilotIntent.ACTION_REQUEST_PROMOTION: "get_promotion_recommendations",
    CopilotIntent.DEAD_STOCK_RECOVERY: "get_dead_stock_recovery",
    CopilotIntent.SEO_ADVICE: "get_seo_opportunities",
}


def _answer_lines(intent: CopilotIntent, rows_by_tool: dict[str, list[dict[str, Any]]]) -> list[str]:
    if intent == CopilotIntent.BUSINESS_MEMORY_SEARCH:
        lines = _memory_lines(rows_by_tool)
    else:
        primary = PRIMARY_TOOL_BY_INTENT.get(intent)
        product_rows = {primary: rows_by_tool[primary]} if primary and rows_by_tool.get(primary) else rows_by_tool
        lines = _product_lines(product_rows)
        if intent in SUMMARY_INTENTS:
            lines = [*_financial_lines(rows_by_tool), *_overview_lines(rows_by_tool), *lines]
    limit = 3 if intent == CopilotIntent.TODAY_ACTIONS else MAX_LIST_LINES
    return _dedupe(lines)[:limit]


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


def _overview_lines(rows_by_tool: dict[str, list[dict[str, Any]]]) -> list[str]:
    keys = (
        "total_products",
        "products_with_stock",
        "products_with_inventory_risk",
        "products_with_dead_stock_risk",
        "total_revenue",
        "estimated_profit",
        "active_alerts",
        "pending_recommendations",
    )
    lines: list[str] = []
    for tool_name in OVERVIEW_TOOLS:
        for row in (rows_by_tool.get(tool_name) or [])[:1]:
            lines.extend(f"{_label(key)}: {_safe_value(row[key])}" for key in keys if row.get(key) is not None)
    return lines


def _financial_lines(rows_by_tool: dict[str, list[dict[str, Any]]]) -> list[str]:
    keys = (
        "gross_revenue",
        "net_revenue",
        "previous_period_revenue",
        "revenue_change",
        "percentage_change",
        "revenue_delta",
        "units_sold",
        "units_sold_delta",
        "order_count",
        "average_order_value",
        "estimated_profit",
        "margin_rate",
    )
    lines: list[str] = []
    for tool_name in FINANCIAL_TOOLS:
        for row in (rows_by_tool.get(tool_name) or [])[:1]:
            repeats_gross = row.get("net_revenue") == row.get("gross_revenue")
            lines.extend(
                f"{_label(key)}: {_safe_value(row[key])}"
                for key in keys
                if row.get(key) is not None and not (key == "net_revenue" and repeats_gross)
            )
    return lines


def _memory_lines(rows_by_tool: dict[str, list[dict[str, Any]]]) -> list[str]:
    lines = []
    for tool_name in MEMORY_TOOLS:
        for row in (rows_by_tool.get(tool_name) or [])[:5]:
            title = row.get("title")
            detail = row.get("summary") or row.get("chunk_text")
            if title or detail:
                lines.append(": ".join(_safe_value(part) for part in (title, detail) if part))
    return lines


def _product_lines(rows_by_tool: dict[str, list[dict[str, Any]]]) -> list[str]:
    """One line per product (duplicates across tools merged): title plus its key number."""
    details: dict[str, str | None] = {}
    skip = {*OVERVIEW_TOOLS, *FINANCIAL_TOOLS, *MEMORY_TOOLS}
    for tool_name, rows in rows_by_tool.items():
        if tool_name in skip:
            continue
        for row in rows:
            title = _product_title(row)
            if not title:
                continue
            if details.get(title) is None:
                details[title] = _key_detail(row)
    return [f"{title}: {detail}" if detail else title for title, detail in details.items()]


def _key_detail(row: dict[str, Any]) -> str | None:
    product: dict[str, Any] = row["product"] if isinstance(row.get("product"), dict) else {}
    for key, label in PRODUCT_KEY_FIELDS:
        value = row.get(key, product.get(key))
        if value in (None, "", [], {}):
            continue
        value_text = _humanize(_safe_value(value))
        return f"{label} {value_text}" if label else value_text
    return None


def _next_step(intent: CopilotIntent, language: str) -> str | None:
    if intent == CopilotIntent.RESTOCK_ADVICE:
        return _text("Check supplier lead time, then place the order.", "Supplier lead time দেখে order দিন।", language)
    if intent in {CopilotIntent.PRICING_ADVICE, CopilotIntent.ACTION_REQUEST_PRICE_CHANGE}:
        return _text("Approve the price change yourself if it looks right.", "ঠিক মনে হলে দামের পরিবর্তন নিজে approve করুন।", language)
    if intent == CopilotIntent.COMPETITOR_THREAT_ANALYSIS:
        return _text("Compare the competitor price before you respond.", "উত্তর দেওয়ার আগে কম্পিটিটরের দাম মিলিয়ে দেখুন।", language)
    if intent == CopilotIntent.DEAD_STOCK_RECOVERY:
        return _text("Start with the product holding the most stock.", "যে পণ্যে সবচেয়ে বেশি স্টক আটকে আছে, সেটা দিয়ে শুরু করুন।", language)
    return None


def _product_title(row: dict[str, Any]) -> str | None:
    for key in ("product", "affected_product"):
        product = row.get(key)
        if isinstance(product, dict) and (product.get("title") or product.get("name")):
            return str(product.get("title") or product.get("name"))
    return None


def _label(key: str) -> str:
    return key.replace("_", " ")


def _humanize(value: str) -> str:
    """Enum codes such as PRICE_LOWER read as "price lower"."""
    return value.replace("_", " ").lower() if value.isupper() else value


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


def _text(en: str, bn: str, language: str) -> str:
    return bn if language == "bn" else en


def _safe_value(value: Any) -> str:
    if isinstance(value, (str, int, float, Decimal)) and not isinstance(value, bool):
        number = _two_places(value)
        if number is not None:
            return number
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


# Internal lines that must never reach the seller, even with a value ("Confidence: HIGH").
_INTERNAL_LINE = re.compile(
    r"^(confidence( level)?|evidence( ids?)?|sources?|tools?( used)?|tool status|data freshness|freshness( warnings?)?|"
    r"missing data|missing visibility data|required missing setup|blocked reasons|safety notes?|safety checks?)\b\s*:?",
    re.IGNORECASE,
)
# Section labels: dropped when alone, stripped when they prefix content ("Next step: ...").
_SECTION_LABEL = re.compile(
    r"^(answer|summary|direct answer|risk( level)?|urgency|priority|next steps?|what to do next|"
    r"recommendation|recommended response|expected impact)\s*(:|$)",
    re.IGNORECASE,
)
_INTERNAL_TOKEN = re.compile(r"\b(SUCCEEDED|FAILED|TIMED_OUT|NO_CONTEXT|evidence_id|ev-\d+)\b")


def clean_answer_text(answer: str, *, evidence_ids: Iterable[str] = ()) -> str:
    """Drop section headers, confidence/evidence/tool-status lines and repeated lines from a model answer."""
    ids = [item for item in evidence_ids if item]
    kept: list[str] = []
    seen: set[str] = set()
    for raw in answer.splitlines():
        line = raw.strip()
        if not line:
            if kept and kept[-1]:
                kept.append("")
            continue
        bare = line.lstrip("#>*-• \t").replace("**", "").strip()
        if _INTERNAL_LINE.match(bare) or _INTERNAL_TOKEN.search(line) or any(item in line for item in ids):
            continue
        label = _SECTION_LABEL.match(bare)
        if label:
            bare = bare[label.end():].strip()
            if not bare:
                continue
            line = bare
        if bare.casefold() in seen:
            continue
        seen.add(bare.casefold())
        kept.append(line)
    return "\n".join(kept).strip()


def _two_places(value: str | int | float | Decimal) -> str | None:
    """6142.50000000 reads as 6142.50; whole numbers and non-numbers are left alone."""
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    if not number.is_finite() or number.as_tuple().exponent >= -2:  # type: ignore[operator]
        return None
    return str(number.quantize(Decimal("0.01")))
