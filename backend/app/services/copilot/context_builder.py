from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import json
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.services.copilot.evidence_system import (
    CopilotConfidenceScorer,
    CopilotEvidenceBuilder,
    CopilotFreshnessAnalyzer,
    CopilotMissingDataAggregator,
    tool_usage_items,
)
from app.services.copilot.question_planner import CopilotQuestionPlan
from app.services.copilot.tool_registry import ToolExecutionResult, ToolExecutionStatus


@dataclass(frozen=True, slots=True)
class CopilotAnswerContext:
    question: str
    question_type: str
    language: str
    domains_used: list[str]
    tools_used: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    missing_data: list[str]
    data_freshness: list[dict[str, Any]]
    facts: dict[str, Any]
    allowed_evidence_ids: set[str]
    allowed_numbers: set[str]
    has_direct_evidence: bool
    has_memory_evidence: bool
    has_visibility_evidence: bool
    has_reliable_no_sales_evidence: bool
    has_financial_evidence: bool
    has_profit_margin_evidence: bool
    backend_action_executed: bool = False
    confidence_result: dict[str, Any] = field(default_factory=dict)
    # Set only when multilingual chat is enabled: "en", "bn" or "banglish".
    reply_language: str | None = None
    # Set only when conversation memory is enabled: earlier turns, oldest first.
    conversation: list[dict[str, str]] = field(default_factory=list)
    # Tools whose facts were shortened or omitted to fit the prompt budget.
    truncated_facts: list[str] = field(default_factory=list)

    def to_prompt_payload(self) -> dict[str, Any]:
        payload = self._base_prompt_payload()
        if self.reply_language:
            payload["language"] = self.reply_language
            payload["reply_script"] = "bengali" if self.reply_language == "bn" else "latin"
        if self.conversation:
            payload["conversation_so_far"] = {
                "note": "Earlier turns for follow-up context only. Not evidence; numbers must come from current facts.",
                "turns": self.conversation,
            }
        if self.truncated_facts:
            payload["facts_truncated_for_length"] = self.truncated_facts
        return payload

    def _base_prompt_payload(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "question_type": self.question_type,
            "language": self.language,
            "domains_used": self.domains_used,
            "tools_used": self.tools_used,
            "evidence": _prompt_evidence(self.evidence),
            "missing_data": self.missing_data,
            "data_freshness": _prompt_freshness(self.data_freshness),
            "facts": self.facts,
            "context_priority": [
                "current direct database facts",
                "deterministic analytics results",
                "current engine recommendations",
                "historical RAG memory",
                "general safe explanation",
            ],
            "rules": [
                "Use only supplied facts.",
                "Do not calculate metrics.",
                "Do not invent numbers or evidence IDs.",
                "Never claim marketplace actions were executed.",
                "Prefer direct current data over stale or conflicting memory.",
            ],
        }


class CopilotContextBuilder:
    def __init__(
        self,
        *,
        evidence_builder: CopilotEvidenceBuilder | None = None,
        missing_aggregator: CopilotMissingDataAggregator | None = None,
        freshness_analyzer: CopilotFreshnessAnalyzer | None = None,
        confidence_scorer: CopilotConfidenceScorer | None = None,
        tool_chars_budget: int | None = None,
        total_chars_budget: int | None = None,
    ) -> None:
        self._evidence_builder = evidence_builder or CopilotEvidenceBuilder()
        self._missing_aggregator = missing_aggregator or CopilotMissingDataAggregator()
        self._freshness_analyzer = freshness_analyzer or CopilotFreshnessAnalyzer()
        self._confidence_scorer = confidence_scorer or CopilotConfidenceScorer()
        self._tool_chars_budget = tool_chars_budget or settings.copilot_prompt_tool_chars
        self._total_chars_budget = total_chars_budget or settings.copilot_prompt_total_chars

    def build(
        self,
        *,
        question: str,
        plan: CopilotQuestionPlan,
        tool_results: list[ToolExecutionResult],
        missing_data: list[str],
    ) -> CopilotAnswerContext:
        evidence_items = self._evidence_builder.build(tool_results)
        missing_items = self._missing_aggregator.aggregate(tool_results, extra_missing=missing_data)
        freshness_items = self._freshness_analyzer.analyze(tool_results)
        confidence_result = self._confidence_scorer.score(
            evidence=evidence_items,
            missing_data=missing_items,
            freshness=freshness_items,
            tool_results=tool_results,
        )
        evidence = [item.to_dict() for item in evidence_items]
        structured_missing = [item.to_dict() for item in missing_items]
        freshness = [item.to_dict() for item in freshness_items]
        facts = {
            result.tool_name: _bounded_data(result.data)
            for result in tool_results
            if result.status == ToolExecutionStatus.SUCCEEDED
        }
        tools_used = [
            item.to_dict() | {"name": item.tool_name, "status": item.status}
            for item in tool_usage_items(tool_results)
        ]
        allowed_ids = {item["evidence_id"] for item in evidence}
        allowed_numbers = _numbers_from_payload({"facts": facts, "evidence": evidence, "question": question})
        facts, truncated_facts = budget_facts(facts, tool_chars=self._tool_chars_budget, total_chars=self._total_chars_budget)
        tool_names = {result.tool_name for result in tool_results if result.status == ToolExecutionStatus.SUCCEEDED}
        has_memory = any(item.get("domain") == "RAG_MEMORY" or str(item.get("evidence_id", "")).startswith("rag:") for item in evidence)
        return CopilotAnswerContext(
            question=question,
            question_type=plan.question_type.value,
            language=plan.language,
            domains_used=plan.required_domains,
            tools_used=tools_used,
            evidence=evidence,
            missing_data=structured_missing,
            data_freshness=freshness,
            facts=facts,
            allowed_evidence_ids=allowed_ids,
            allowed_numbers=allowed_numbers,
            truncated_facts=truncated_facts,
            has_direct_evidence=any(evidence_item.get("domain") != "RAG_MEMORY" for evidence_item in evidence),
            has_memory_evidence=has_memory,
            has_visibility_evidence=bool(tool_names & {"get_seo_opportunities", "get_visibility_summary", "get_visibility_history", "get_listing_quality_issues"}),
            has_reliable_no_sales_evidence="get_products_with_no_sales" in tool_names,
            has_financial_evidence=bool(tool_names & {"get_revenue_summary", "get_sales_trends", "explain_revenue_change_deterministic", "explain_revenue_drop"}),
            has_profit_margin_evidence=bool(tool_names & {"get_profit_summary", "get_margin_safety", "get_pricing_recommendations", "simulate_price_change"}),
            confidence_result=confidence_result.to_dict(),
        )


def _collect_context_evidence(tool_results: list[ToolExecutionResult]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    seen: set[str] = set()
    for result in tool_results:
        for index, item in enumerate(result.evidence):
            normalized = _normalize_evidence(item, len(evidence), tool_name=result.tool_name, data=result.data, index=index)
            if normalized["evidence_id"] in seen:
                continue
            evidence.append(normalized)
            seen.add(normalized["evidence_id"])
    return evidence


def _normalize_evidence(item: Any, fallback_index: int, *, tool_name: str, data: dict[str, Any], index: int) -> dict[str, Any]:
    source_type = "unknown"
    evidence_id = f"{tool_name}:{fallback_index + 1}"
    title = tool_name
    event_time = None
    if isinstance(item, dict):
        evidence_id = str(item.get("evidence_id") or f"{item.get('source_table', tool_name)}:{item.get('source_id', fallback_index + 1)}")
        source_type = str(item.get("source_type") or item.get("source_table") or tool_name)
        title = str(item.get("title") or item.get("source_table") or tool_name)
        event_time = item.get("event_time")
    priority = "HISTORICAL_MEMORY" if tool_name == "retrieve_business_memory" or evidence_id.startswith("rag:") else "CURRENT_DIRECT"
    chunk = _memory_chunk_for_evidence(data, evidence_id, index)
    stale = _is_stale(chunk.get("event_time") if chunk else event_time) if priority == "HISTORICAL_MEMORY" else False
    return {
        "evidence_id": evidence_id,
        "source_type": source_type,
        "title": title,
        "event_time": _json_safe(chunk.get("event_time") if chunk else event_time),
        "tool_name": tool_name,
        "priority": priority,
        "stale": stale,
        "source_metadata": chunk or {},
    }


def _memory_chunk_for_evidence(data: dict[str, Any], evidence_id: str, index: int) -> dict[str, Any] | None:
    chunks = data.get("memory_chunks")
    if not isinstance(chunks, list):
        return None
    for chunk in chunks:
        if isinstance(chunk, dict) and chunk.get("evidence_id") == evidence_id:
            return chunk
    if index < len(chunks) and isinstance(chunks[index], dict):
        return chunks[index]
    return None


def _data_freshness(tool_results: list[ToolExecutionResult]) -> list[dict[str, Any]]:
    rows = []
    for result in tool_results:
        event_times = []
        for item in _collect_event_times(result.data):
            event_times.append(item)
        rows.append(
            {
                "source": result.tool_name,
                "status": result.status.value,
                "latest_event_time": max(event_times).isoformat() if event_times else None,
                "stale": _is_stale(max(event_times)) if event_times else None,
            }
        )
    return rows


def _collect_event_times(value: Any) -> list[datetime]:
    times = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"event_time", "created_at", "updated_at", "captured_at", "calculated_at", "generated_at", "sold_at"}:
                parsed = _parse_datetime(item)
                if parsed:
                    times.append(parsed)
            else:
                times.extend(_collect_event_times(item))
    elif isinstance(value, list):
        for item in value:
            times.extend(_collect_event_times(item))
    return times


def _is_stale(value: Any, *, max_age_days: int = 90) -> bool:
    parsed = _parse_datetime(value)
    if parsed is None:
        return False
    now = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (now - parsed).days > max_age_days


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _numbers_from_payload(value: Any) -> set[str]:
    import re

    text = str(_json_safe(value))
    values = set()
    for match in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?%?", text):
        normalized = match.rstrip("%")
        if len(normalized.replace(".", "").replace("-", "")) <= 1:
            continue
        values.add(normalized)
    return values


LIST_CAPS = (50, 20, 10, 5, 3, 1)
MEMORY_TOOL = "retrieve_business_memory"


# Evidence is one item per source row (a week of sales is hundreds) and is not budgeted with facts.
# The model only needs a few IDs to cite; validation still checks against the full list.
PROMPT_EVIDENCE_LIMIT = 12


def _prompt_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """First items only, without empty fields, so small-quota LLM tiers stay under their token limit."""
    return [{key: value for key, value in item.items() if value not in (None, "", [], {})} for item in evidence[:PROMPT_EVIDENCE_LIMIT]]


def _prompt_freshness(freshness: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Distinct domain/status pairs: per-table messages repeat and are never shown to the seller."""
    pairs = dict.fromkeys((str(item.get("domain")), str(item.get("status"))) for item in freshness if isinstance(item, dict))
    return [{"domain": domain, "status": status} for domain, status in pairs]


def budget_facts(facts: dict[str, Any], *, tool_chars: int, total_chars: int) -> tuple[dict[str, Any], list[str]]:
    """Keep the prompt inside a character budget without breaking its JSON shape.

    Each tool's facts are shortened by trimming long lists first; direct tools are kept
    ahead of RAG memory (the lowest ``context_priority``) when the total budget runs out.
    """
    order = sorted(facts, key=lambda name: name == MEMORY_TOOL)
    fitted: dict[str, Any] = {}
    truncated: list[str] = []
    used = 0
    for name in order:
        value, shortened = _fit_to_budget(facts[name], tool_chars)
        size = _json_size(value)
        if used + size > total_chars:
            fitted[name] = {"_omitted": "prompt length budget"}
            truncated.append(name)
            continue
        fitted[name] = value
        used += size
        if shortened:
            truncated.append(name)
    return {name: fitted[name] for name in facts}, truncated


def _fit_to_budget(value: Any, limit: int) -> tuple[Any, bool]:
    if _json_size(value) <= limit:
        return value, False
    for cap in LIST_CAPS:
        shortened = _cap_lists(value, cap)
        if _json_size(shortened) <= limit:
            return (shortened | {"_truncated": True} if isinstance(shortened, dict) else shortened), True
    return {"_truncated": True, "preview": json.dumps(value, ensure_ascii=False, default=str)[: max(0, limit - 64)]}, True


def _cap_lists(value: Any, cap: int) -> Any:
    if isinstance(value, dict):
        return {key: _cap_lists(item, cap) for key, item in value.items()}
    if isinstance(value, list):
        return [_cap_lists(item, cap) for item in value[:cap]]
    return value


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))


def _bounded_data(data: dict[str, Any]) -> dict[str, Any]:
    return _json_safe(data)


def _json_safe(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "isoformat") and value.__class__.__name__ == "date":
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value
