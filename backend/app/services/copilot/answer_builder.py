from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Iterable

from app.services.copilot.context_builder import is_zero_sales, zero_sales_proven
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
        primary_tools: set[str] | frozenset[str] = frozenset(),
        period: dict[str, Any] | None = None,
    ) -> CopilotBuiltAnswer:
        """Deterministic answer from tool facts, used when no model answer is available or valid.

        With ``primary_tools`` or ``period`` (the hybrid engine passes both), lines come only from the
        tools that answer the question, under a header in the reply language that names the period.
        """
        language = classification.language
        lang = reply_language if reply_language in {"en", "bn", "banglish"} else language
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

        if primary_tools or period is not None:
            answering = [result for result in tool_results if not primary_tools or result.tool_name in primary_tools]
            with_memory = classification.intent == CopilotIntent.BUSINESS_MEMORY_SEARCH or bool(set(primary_tools) & set(MEMORY_TOOLS))
            lines = _dedupe(_fact_lines(answering, period=period, lang=lang, with_memory=with_memory))[:MAX_LIST_LINES]
            if not lines and primary_tools:
                # The primary tools gave no readable fact; other tools' facts beat a "nothing found" reply.
                answering = [result for result in tool_results if result.status == ToolExecutionStatus.SUCCEEDED]
                lines = _dedupe(_fact_lines(answering, period=period, lang=lang, with_memory=with_memory))[:MAX_LIST_LINES]
            # The intent's next step only fits when its own tool answered; Banglish has no Latin-script step text.
            own_tool = PRIMARY_TOOL_BY_INTENT.get(classification.intent)
            next_step = _next_step(classification.intent, language) if lines and lang != "banglish" and own_tool in {result.tool_name for result in answering} else None
            lead = _header(lang, period) if lines else _by_lang(NOTHING_FOUND_BY_LANG, lang)
        else:
            lines = _answer_lines(classification.intent, rows_by_tool, lang=lang)
            if not lines:
                # The intent had no line format for these tools; their facts beat a "nothing found" reply.
                succeeded = [result for result in tool_results if result.status == ToolExecutionStatus.SUCCEEDED]
                lines = _dedupe(_fact_lines(succeeded, period=None, lang=lang, with_memory=classification.intent == CopilotIntent.BUSINESS_MEMORY_SEARCH))[:MAX_LIST_LINES]
            next_step = _next_step(classification.intent, language) if lines and lang != "banglish" else None
            lead = HEADER["banglish"] + ":" if lang == "banglish" and lines else _text(*(LEAD_BY_INTENT.get(classification.intent, DEFAULT_LEAD) if lines else NOTHING_FOUND), language)
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


HEADER = {"en": "From your data", "bn": "আপনার ডেটা থেকে", "banglish": "Apnar data theke"}
PERIOD_JOIN = {"en": "to", "bn": "থেকে", "banglish": "theke"}
ALL_HISTORY = {"en": "all recorded history", "bn": "সব রেকর্ড করা ইতিহাস", "banglish": "shob recorded history"}
NOTHING_FOUND_BY_LANG = {"en": NOTHING_FOUND[0], "bn": NOTHING_FOUND[1], "banglish": "Apnar data te ekhono porishkar uttor pai ni."}
NO_SALES_PROVEN = {
    "en": "No sales recorded for this period; last recorded sale: {date}",
    "bn": "এই সময়ে কোনো বিক্রি রেকর্ড হয়নি; সর্বশেষ বিক্রি: {date}",
    "banglish": "Ei somoye kono sale record hoy nai; shesh recorded sale: {date}",
}
NO_SALES_UNCONFIRMED = {
    "en": "No sales found for this period, but the sales history could not be confirmed",
    "bn": "এই সময়ে কোনো বিক্রি পাওয়া যায়নি, তবে বিক্রির ইতিহাস নিশ্চিত করা যায়নি",
    "banglish": "Ei somoye kono sale pawa jay nai, kintu sales history confirm kora jay nai",
}
# Group and list rows carry these alongside their label; they are not part of it.
RECORD_META = {"value", "row_count", "evidence", "id", "is_weekend"}


def _by_lang(texts: dict[str, str], lang: str) -> str:
    return texts.get(lang, texts["en"])


def _header(lang: str, period: dict[str, Any] | None) -> str:
    header = _by_lang(HEADER, lang)
    if not period:
        return f"{header}:"
    if period.get("defaulted"):
        return f"{header} ({_by_lang(ALL_HISTORY, lang)}):"
    return f"{header} ({period['from_date']} {_by_lang(PERIOD_JOIN, lang)} {period['to_date']}):"


def _fact_lines(results: list[ToolExecutionResult], *, period: dict[str, Any] | None, lang: str, with_memory: bool) -> list[str]:
    """Lines from every kind of answering tool; memory snippets only when memory answers the question."""
    rows_by_tool = _rows_by_tool(results)
    lines = [*_financial_lines(rows_by_tool, period=period, lang=lang), *_overview_lines(rows_by_tool)]
    for result in results:
        data = result.data if isinstance(result.data, dict) else {}
        if result.tool_name == "query_business_records":
            lines.extend(_records_lines(data, period=period, lang=lang))
        elif result.tool_name == "get_product_profile" and isinstance(data.get("product"), dict):
            lines.append(_profile_line(data["product"]))
        elif isinstance(data.get("count"), int) and not isinstance(data.get("count"), bool) and not isinstance(data.get("listing_summary"), dict):
            # count_* tools return one top-level figure and no rows.
            lines.append(f"{_label(result.tool_name.removeprefix('count_'))}: {data['count']}")
        elif metric_line := _metric_line(data):
            lines.append(metric_line)
        if isinstance(data.get("listing_summary"), dict):
            # Account total first: sellers saying "listed" usually mean every product they have.
            summary = data["listing_summary"]
            lines.extend(f"{_label(key)}: {summary[key]}" for key in ("total_products_in_account", "products_with_active_marketplace_listing") if summary.get(key) is not None)
    others = {name: rows for name, rows in rows_by_tool.items() if name not in {"query_business_records", "get_product_profile"}}
    return [*lines, *_product_lines(others), *(_memory_lines(rows_by_tool) if with_memory else [])]


SALES_METRIC_WORDS = ("revenue", "order", "unit", "sales", "profit")
PRODUCT_ROW_TOOLS = frozenset({"list_products", "search_products"})


def _metric_line(data: dict[str, Any]) -> str | None:
    """One line for a calculated scalar metric (run_seller_metric_query); a zero sales figure is left to the sales tools."""
    value = data.get("value")
    metric_key = data.get("metric_key")
    if not isinstance(metric_key, str) or data.get("status") != "CALCULATED" or value is None or isinstance(value, (bool, dict, list)):
        return None
    if _is_zero(value) and any(word in metric_key for word in SALES_METRIC_WORDS):
        return None  # an observed zero only becomes "no sales" with proof of history (see _no_sales_line)
    currency = data.get("currency")
    return f"{_label(metric_key)}: {_safe_value(value)}{f' {currency}' if currency else ''}"


def _no_sales_line(tool_name: str, data: dict[str, Any], *, period: dict[str, Any] | None, lang: str) -> str:
    if zero_sales_proven(tool_name, data, period):
        return _by_lang(NO_SALES_PROVEN, lang).format(date=data["latest_recorded_sale_date"])
    return _by_lang(NO_SALES_UNCONFIRMED, lang)


def _records_lines(data: dict[str, Any], *, period: dict[str, Any] | None, lang: str) -> list[str]:
    if is_zero_sales("query_business_records", data):
        return [_no_sales_line("query_business_records", data, period=period, lang=lang)]
    measure = data.get("measure")
    lines: list[str] = []
    for row in (data.get("rows") or [])[:MAX_LIST_LINES]:
        if not isinstance(row, dict):
            continue
        if data.get("aggregate") == "list":
            title = _product_title(row) or row.get("title") or row.get("id")
            value = row.get(measure) if measure else None
            lines.append(f"{title}: {_safe_value(value)}" if value is not None else str(title))
            continue
        label = ", ".join(_product_title({"product": value}) or _safe_value(value) for key, value in row.items() if key not in RECORD_META and value not in (None, ""))
        lines.append(f"{label or _label(str(measure or data.get('aggregate') or 'value'))}: {_safe_value(row.get('value'))}")
    return lines


def _profile_line(product: dict[str, Any]) -> str:
    parts = [f"{label} {_safe_value(product[key])}" for key, label in (("current_stock", "stock"), ("selling_price", "price")) if product.get(key) is not None]
    name = str(product.get("name") or product.get("title") or "Product")
    return f"{name}: {', '.join(parts)}" if parts else name


def _answer_lines(intent: CopilotIntent, rows_by_tool: dict[str, list[dict[str, Any]]], *, lang: str = "en") -> list[str]:
    if intent == CopilotIntent.BUSINESS_MEMORY_SEARCH:
        lines = _memory_lines(rows_by_tool)
    else:
        primary = PRIMARY_TOOL_BY_INTENT.get(intent)
        product_rows = {primary: rows_by_tool[primary]} if primary and rows_by_tool.get(primary) else rows_by_tool
        lines = _product_lines(product_rows)
        if intent in SUMMARY_INTENTS:
            lines = [*_financial_lines(rows_by_tool, period=None, lang=lang), *_overview_lines(rows_by_tool), *lines]
    limit = 3 if intent == CopilotIntent.TODAY_ACTIONS else MAX_LIST_LINES
    return _dedupe(lines)[:limit]


def _rows_by_tool(tool_results: list[ToolExecutionResult]) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    for result in tool_results:
        rows = _extract_rows(result.data)
        if result.tool_name in FINANCIAL_TOOLS and isinstance(result.data, dict) and any(
            result.data.get(key) is not None for key in ("gross_revenue", "estimated_profit", "revenue_change", "revenue_delta")
        ):
            # Period totals live at the top level; nested per-product rows must not stand in for them.
            rows = [result.data]
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


def _financial_lines(rows_by_tool: dict[str, list[dict[str, Any]]], *, period: dict[str, Any] | None, lang: str) -> list[str]:
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
            if row.get("order_count") == 0 and not row.get("units_sold") or _is_zero(row.get("gross_revenue")) and not row.get("units_sold"):
                # Observed zero: no zero figures; "no sales recorded" only when the history is shown to exist.
                lines.append(_no_sales_line(tool_name, row, period=period, lang=lang))
                continue
            repeats_gross = row.get("net_revenue") == row.get("gross_revenue")
            lines.extend(
                f"{_label(key)}: {_safe_value(row[key])}"
                for key in keys
                if row.get(key) is not None and not (key == "net_revenue" and repeats_gross)
            )
    return lines


def _is_zero(value: Any) -> bool:
    try:
        return value is not None and Decimal(str(value)) == 0
    except (ArithmeticError, ValueError):
        return False


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
            # list/search rows are products themselves, with a top-level title.
            title = _product_title(row) or (str(row["title"]) if tool_name in PRODUCT_ROW_TOOLS and row.get("title") else None)
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
