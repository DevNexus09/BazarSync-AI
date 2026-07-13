from __future__ import annotations

from collections import defaultdict
import logging
from threading import Lock
from time import monotonic
from typing import Any


_COUNTERS: dict[str, int] = defaultdict(int)
_TIMINGS: dict[str, list[int]] = defaultdict(list)
_LOCK = Lock()


def increment_metric(name: str, value: int = 1) -> None:
    with _LOCK:
        _COUNTERS[name] += value


def observe_latency(name: str, duration_ms: int) -> None:
    with _LOCK:
        _TIMINGS[name].append(max(0, int(duration_ms)))


def snapshot_metrics() -> dict[str, Any]:
    with _LOCK:
        return {
            "counters": dict(_COUNTERS),
            "timings": {key: list(value) for key, value in _TIMINGS.items()},
        }


def reset_metrics() -> None:
    with _LOCK:
        _COUNTERS.clear()
        _TIMINGS.clear()


def record_rag_retrieval_quality(
    *,
    keyword_result_count: int,
    vector_result_count: int,
    fused_result_count: int,
    final_context_count: int,
    top_score: float | None,
    average_score: float | None,
    filtered_by_seller_count: int,
    stale_result_count: int,
    duration_ms: int,
) -> None:
    """Record bounded aggregate retrieval facts; never record text or vectors."""

    for name, value in (
        ("rag_keyword_results_total", keyword_result_count),
        ("rag_vector_results_total", vector_result_count),
        ("rag_fused_results_total", fused_result_count),
        ("rag_final_context_total", final_context_count),
        ("rag_filtered_by_seller_total", filtered_by_seller_count),
        ("rag_stale_results_total", stale_result_count),
    ):
        increment_metric(name, max(0, int(value)))
    increment_metric("rag_retrieval_queries_total")
    if final_context_count == 0:
        increment_metric("rag_retrieval_no_result_total")
    if top_score is not None:
        observe_latency("rag_retrieval_top_score_milli", round(max(0.0, min(1.0, top_score)) * 1000))
    if average_score is not None:
        observe_latency("rag_retrieval_average_score_milli", round(max(0.0, min(1.0, average_score)) * 1000))
    observe_latency("rag_retrieval_latency_ms", duration_ms)


def now_ms() -> float:
    return monotonic() * 1000


def elapsed_ms(start_ms: float) -> int:
    return max(0, int(now_ms() - start_ms))


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    safe_fields = {key: value for key, value in fields.items() if value is not None}
    payload = " ".join(f"{key}={value}" for key, value in safe_fields.items())
    logger.log(level, f"{event} {payload}".strip())
