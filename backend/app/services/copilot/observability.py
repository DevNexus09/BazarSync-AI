from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.copilot_telemetry import CopilotRunTelemetry
from app.models.rag_memory import RagMemoryDocument, RagMemoryEmbeddingStatus
from app.services.copilot.metric_catalog import MetricCatalogService, MetricImplementationStatus
from app.services.copilot.tool_registry import CopilotToolRegistry
from app.services.rag_memory_source_registry import RAG_SOURCE_REGISTRY
from app.services.rag_observability import snapshot_metrics


def capability_snapshot(db: Session | None = None, *, seller_id: UUID | None = None) -> dict[str, Any]:
    catalog = MetricCatalogService()
    metrics = catalog.list_metrics()
    metric_counts = Counter(metric.implementation_status.value for metric in metrics)
    executor_keys: set[str] = set()
    if db is not None:
        from app.services.copilot.metric_execution_service import MetricExecutionService

        executor_keys = set(MetricExecutionService(db)._handlers)
    tools = CopilotToolRegistry().list_tools()
    reachable_tools = [
        tool.name
        for tool in tools
        if tool.allowed_in_read_only_mode and tool.implementation is not None
    ]
    implemented_sources = [definition for definition in RAG_SOURCE_REGISTRY.values() if definition.implemented]
    sources_with_hooks = [definition for definition in implemented_sources if definition.reindex_supported and definition.reindex_triggers]
    stale_source_count = 0
    if db is not None:
        stale_statement = select(func.count(distinct(RagMemoryDocument.source_type))).where(
            RagMemoryDocument.deleted_at.is_(None),
            RagMemoryDocument.embedding_status == RagMemoryEmbeddingStatus.STALE,
        )
        if seller_id is not None:
            stale_statement = stale_statement.where(RagMemoryDocument.seller_id == seller_id)
        stale_source_count = int(db.execute(stale_statement).scalar_one() or 0)
    return {
        # Client-facing switches: the chat UI only uses a feature the backend reports as on.
        "features": {
            "multilingual": settings.copilot_multilingual_enabled,
            "languages": ["auto", "en", "bn", "banglish"] if settings.copilot_multilingual_enabled else ["auto", "en", "bn"],
            "streaming": settings.copilot_streaming_enabled,
            "follow_ups": settings.copilot_follow_ups_enabled,
            "feedback": True,
            "conversation_memory": settings.copilot_conversation_memory_enabled,
        },
        "metrics": {
            "declared": len(metrics),
            "implemented": metric_counts.get(MetricImplementationStatus.IMPLEMENTED.value, 0),
            "partial": metric_counts.get(MetricImplementationStatus.PARTIAL.value, 0),
            "unsupported": metric_counts.get(MetricImplementationStatus.UNSUPPORTED.value, 0),
            "implemented_keys": sorted(metric.metric_key for metric in metrics if metric.implementation_status == MetricImplementationStatus.IMPLEMENTED),
            "partial_keys": sorted(metric.metric_key for metric in metrics if metric.implementation_status == MetricImplementationStatus.PARTIAL),
            "unsupported_keys": sorted(metric.metric_key for metric in metrics if metric.implementation_status == MetricImplementationStatus.UNSUPPORTED),
            "executor_coverage": round((len(executor_keys & {metric.metric_key for metric in metrics}) / len(metrics)) * 100, 2) if metrics else 100.0,
        },
        "tools": {
            "registered": len(tools),
            "reachable_by_planner": len(reachable_tools),
            "reachable_names": sorted(reachable_tools),
        },
        "rag_sources": {
            "declared": len(RAG_SOURCE_REGISTRY),
            "implemented": len(implemented_sources),
            "with_write_hooks": len(sources_with_hooks),
            "coverage_percent": round((len(implemented_sources) / len(RAG_SOURCE_REGISTRY)) * 100, 2) if RAG_SOURCE_REGISTRY else 100.0,
            "write_hook_coverage_percent": round((len(sources_with_hooks) / len(implemented_sources)) * 100, 2) if implemented_sources else 100.0,
            "unimplemented": sorted(definition.source_type.value for definition in RAG_SOURCE_REGISTRY.values() if not definition.implemented),
            "stale_source_count": stale_source_count,
        },
    }


def copilot_health_snapshot(db: Session, *, seller_id: UUID) -> dict[str, Any]:
    aggregates = db.execute(
        select(
            func.count(CopilotRunTelemetry.id),
            func.count(CopilotRunTelemetry.id).filter(CopilotRunTelemetry.result_status == "FAILED"),
            func.avg(CopilotRunTelemetry.total_duration_ms),
            func.avg(CopilotRunTelemetry.planner_duration_ms),
            func.avg(CopilotRunTelemetry.tool_duration_ms),
            func.avg(CopilotRunTelemetry.rag_duration_ms),
            func.avg(CopilotRunTelemetry.groq_duration_ms),
        ).where(CopilotRunTelemetry.seller_id == seller_id)
    ).one()
    recent = db.execute(
        select(CopilotRunTelemetry.planner_miss_reasons_json)
        .where(CopilotRunTelemetry.seller_id == seller_id)
        .order_by(CopilotRunTelemetry.created_at.desc())
        .limit(1000)
    ).scalars().all()
    miss_counts: Counter[str] = Counter()
    for reasons in recent:
        if isinstance(reasons, list):
            miss_counts.update(str(reason) for reason in reasons)
    metrics = snapshot_metrics()
    counters = metrics.get("counters", {})
    return {
        "status": "ok",
        "telemetry": {
            "runs": int(aggregates[0] or 0),
            "failed_runs": int(aggregates[1] or 0),
            "average_duration_ms": _rounded(aggregates[2]),
            "average_planner_duration_ms": _rounded(aggregates[3]),
            "average_tool_duration_ms": _rounded(aggregates[4]),
            "average_rag_duration_ms": _rounded(aggregates[5]),
            "average_groq_duration_ms": _rounded(aggregates[6]),
            "planner_miss_counts": dict(sorted(miss_counts.items())),
        },
        "runtime_metrics": {
            key: value
            for key, value in counters.items()
            if key.startswith("copilot_")
        },
        "limits": _limits_snapshot(),
        "calculated_at": datetime.now(timezone.utc).isoformat(),
    }


def rag_quality_snapshot() -> dict[str, Any]:
    metrics = snapshot_metrics()
    counters = metrics.get("counters", {})
    timings = metrics.get("timings", {})
    quality_keys = (
        "rag_keyword_results_total",
        "rag_vector_results_total",
        "rag_fused_results_total",
        "rag_final_context_total",
        "rag_retrieval_no_result_total",
        "rag_filtered_by_seller_total",
        "rag_stale_results_total",
        "rag_retrieval_queries_total",
    )
    return {
        "counters": {key: counters.get(key, 0) for key in quality_keys},
        "timings": {
            "retrieval_ms": list(timings.get("rag_retrieval_latency_ms", []))[-100:],
            "top_score_milli": list(timings.get("rag_retrieval_top_score_milli", []))[-100:],
            "average_score_milli": list(timings.get("rag_retrieval_average_score_milli", []))[-100:],
        },
    }


def _limits_snapshot() -> dict[str, int]:
    return {
        "max_tool_calls": max(1, settings.copilot_max_tool_calls),
        "max_iterations": max(1, min(settings.copilot_max_iterations, 3)),
        "groq_timeout_seconds": max(1, int(settings.copilot_groq_timeout_seconds)),
        "overall_timeout_seconds": max(1, int(settings.copilot_overall_timeout_seconds)),
        "prompt_max_chars": 16000,
        "rag_top_k_max": 20,
        "source_result_limit_max": 25,
        "conversation_page_limit_max": 100,
    }


def _rounded(value: Any) -> int | None:
    return round(float(value)) if value is not None else None
