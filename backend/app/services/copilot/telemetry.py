from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Iterable
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.models.copilot_telemetry import CopilotRunTelemetry
from app.services.rag_observability import increment_metric, log_event


logger = logging.getLogger(__name__)

PLANNER_MISS_CODES = (
    "NO_DOMAIN_MATCH",
    "NO_METRIC_MATCH",
    "NO_TOOL_MATCH",
    "METRIC_NOT_EXECUTABLE",
    "INVALID_FILTER",
    "AMBIGUOUS_ENTITY",
    "CURRENT_DATA_DISABLED",
    "MEMORY_DISABLED",
    "RAG_NO_RESULTS",
    "TOOL_LIMIT_REACHED",
    "TOOL_TIMEOUT",
    "VALIDATION_FALLBACK",
)
_PLANNER_MISS_CODE_SET = frozenset(PLANNER_MISS_CODES)


@dataclass(frozen=True, slots=True)
class CopilotTelemetrySnapshot:
    run_id: UUID
    seller_id: UUID
    conversation_id: UUID | None
    request_mode: str
    question_type: str
    selected_domains: list[str]
    selected_metrics: list[str]
    selected_tools: list[str]
    planner_status: str
    planner_fallback_used: bool
    clarification_requested: bool
    tools_succeeded: int
    tools_failed: int
    rag_requested: bool
    rag_result_count: int
    evidence_count: int
    missing_data_count: int
    final_confidence: str | None
    result_status: str
    planner_miss_reasons: list[str]
    planner_duration_ms: int | None
    tool_duration_ms: int | None
    rag_duration_ms: int | None
    groq_duration_ms: int | None
    total_duration_ms: int | None


def request_mode(*, include_current_data: bool, include_memory: bool) -> str:
    if include_current_data and include_memory:
        return "BOTH"
    if include_current_data:
        return "CURRENT_ONLY"
    if include_memory:
        return "MEMORY_ONLY"
    return "DISABLED"


def normalize_miss_reasons(values: Iterable[str] | None) -> list[str]:
    normalized: list[str] = []
    for value in values or ():
        code = str(value).split(":", 1)[0].upper()
        if code in _PLANNER_MISS_CODE_SET and code not in normalized:
            normalized.append(code)
    return normalized


def derive_planner_miss_reasons(
    *,
    plan: Any,
    include_current_data: bool,
    include_memory: bool,
    selected_tools: Iterable[Any] = (),
    tool_results: Iterable[Any] = (),
) -> list[str]:
    """Convert planner/tool safety signals into bounded operational codes."""

    reasons: list[str] = []
    domains = list(getattr(plan, "required_domains", ()) or ())
    metrics = list(getattr(plan, "metric_plan", ()) or ())
    planned_tools = list(getattr(plan, "tool_plan", ()) or ())
    selected = list(selected_tools or ())
    safety_flags = [str(flag) for flag in (getattr(plan, "safety_flags", ()) or ())]
    if not domains:
        reasons.append("NO_DOMAIN_MATCH")
    if not metrics and any(token in str(getattr(plan, "question_type", "")).upper() for token in ("METRIC", "ANALYTIC", "COMPARISON", "TREND")):
        reasons.append("NO_METRIC_MATCH")
    if not planned_tools and not selected:
        reasons.append("NO_TOOL_MATCH")
    if not include_current_data:
        reasons.append("CURRENT_DATA_DISABLED")
    if not include_memory:
        reasons.append("MEMORY_DISABLED")
    if bool(getattr(plan, "needs_clarification", False)) or any(flag.endswith("_AMBIGUITY") for flag in safety_flags):
        reasons.append("AMBIGUOUS_ENTITY")
    if any(flag.startswith("UNSUPPORTED_METRIC") or flag.startswith("INVALID_METRIC") for flag in safety_flags):
        reasons.append("METRIC_NOT_EXECUTABLE")
    if any(flag.startswith("INVALID_") for flag in safety_flags):
        reasons.append("INVALID_FILTER")
    if "TOOL_LIMIT_ENFORCED" in safety_flags:
        reasons.append("TOOL_LIMIT_REACHED")
    if any(flag.startswith("INVALID_TOOL_ARGS") or flag.startswith("VALIDATION") for flag in safety_flags):
        reasons.append("VALIDATION_FALLBACK")
    for result in tool_results or ():
        error = getattr(result, "error", None) or {}
        code = str(error.get("code", "")).upper() if isinstance(error, dict) else ""
        if code in {"TIMEOUT", "TOOL_TIMEOUT"}:
            reasons.append("TOOL_TIMEOUT")
        if getattr(result, "tool_name", None) == "retrieve_business_memory" and not getattr(result, "evidence", None):
            reasons.append("RAG_NO_RESULTS")
    return normalize_miss_reasons(reasons)


def persist_copilot_run(
    db: Session | None,
    *,
    snapshot: CopilotTelemetrySnapshot,
) -> None:
    """Persist telemetry without making a successful answer fail on telemetry."""

    for reason in snapshot.planner_miss_reasons:
        increment_metric(f"copilot_planner_miss_{reason.lower()}")
    increment_metric("copilot_runs_total")
    if snapshot.planner_fallback_used:
        increment_metric("copilot_planner_fallback_total")
    if snapshot.result_status == "FAILED":
        increment_metric("copilot_runs_failed_total")

    log_event(
        logger,
        logging.INFO,
        "copilot_run_telemetry",
        run_id=snapshot.run_id,
        seller_id=snapshot.seller_id,
        conversation_id=snapshot.conversation_id,
        request_mode=snapshot.request_mode,
        question_type=snapshot.question_type,
        planner_status=snapshot.planner_status,
        result_status=snapshot.result_status,
        tools_succeeded=snapshot.tools_succeeded,
        tools_failed=snapshot.tools_failed,
        rag_result_count=snapshot.rag_result_count,
        evidence_count=snapshot.evidence_count,
        missing_data_count=snapshot.missing_data_count,
        total_duration_ms=snapshot.total_duration_ms,
        planner_miss_reasons=",".join(snapshot.planner_miss_reasons),
    )
    if db is None:
        return
    try:
        db.add(
            CopilotRunTelemetry(
                run_id=snapshot.run_id,
                seller_id=snapshot.seller_id,
                conversation_id=snapshot.conversation_id,
                request_mode=snapshot.request_mode,
                question_type=snapshot.question_type,
                selected_domains_json=snapshot.selected_domains,
                selected_metrics_json=snapshot.selected_metrics,
                selected_tools_json=snapshot.selected_tools,
                planner_status=snapshot.planner_status,
                planner_fallback_used=snapshot.planner_fallback_used,
                clarification_requested=snapshot.clarification_requested,
                tools_succeeded=snapshot.tools_succeeded,
                tools_failed=snapshot.tools_failed,
                rag_requested=snapshot.rag_requested,
                rag_result_count=snapshot.rag_result_count,
                evidence_count=snapshot.evidence_count,
                missing_data_count=snapshot.missing_data_count,
                final_confidence=snapshot.final_confidence,
                result_status=snapshot.result_status,
                planner_miss_reasons_json=snapshot.planner_miss_reasons,
                planner_duration_ms=snapshot.planner_duration_ms,
                tool_duration_ms=snapshot.tool_duration_ms,
                rag_duration_ms=snapshot.rag_duration_ms,
                groq_duration_ms=snapshot.groq_duration_ms,
                total_duration_ms=snapshot.total_duration_ms,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        log_event(
            logger,
            logging.WARNING,
            "copilot_run_telemetry_persist_failed",
            run_id=snapshot.run_id,
            seller_id=snapshot.seller_id,
            error_code="TELEMETRY_WRITE_FAILED",
        )


def new_run_id() -> UUID:
    return uuid4()
