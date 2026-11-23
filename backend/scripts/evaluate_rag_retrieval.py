"""Offline RAG retrieval-quality eval against a seeded seller (outside request handlers).

Runs every golden question through ``RagRetrievalService.retrieve_context`` once per config and
scores recall@5, recall@12, MRR, no-context rate, top-group share and latency. Read-only: it
never writes business tables. Results go to ``artifacts/rag_eval/<timestamp>.json``.

    python scripts/evaluate_rag_retrieval.py --seller-id <uuid>
    python scripts/evaluate_rag_retrieval.py --seller-id <uuid> --configs baseline,translation,translation+reranker

A config is ``+``-joined feature names on top of the baseline (all new flags off, existing
``RAG_RRF_ENABLED`` / ``RAG_COSINE_DISTANCE_ENABLED`` as set in the environment).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import time
from typing import Any
from uuid import UUID

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

FIXTURE = BACKEND / "tests" / "fixtures" / "rag_retrieval_golden.json"
OUTPUT_DIR = BACKEND / "artifacts" / "rag_eval"

# Feature name -> settings overrides. A feature whose setting does not exist yet is reported, not run.
FEATURES: dict[str, dict[str, Any]] = {
    "translation": {"rag_keyword_translation_enabled": True},
    "reranker": {"rag_reranker_enabled": True},
    "fulltext": {"rag_fulltext_keyword_enabled": True},
    "groupcap": {"rag_max_chunks_per_group": 3},
}
NEW_FLAG_DEFAULTS: dict[str, Any] = {
    "rag_keyword_translation_enabled": False,
    "rag_reranker_enabled": False,
    "rag_fulltext_keyword_enabled": False,
    "rag_max_chunks_per_group": 0,
}


def _overrides(config: str) -> dict[str, Any]:
    overrides = dict(NEW_FLAG_DEFAULTS)
    for feature in [name for name in config.split("+") if name and name != "baseline"]:
        if feature not in FEATURES:
            raise SystemExit(f"Unknown feature {feature!r}; known: {', '.join(FEATURES)}")
        overrides.update(FEATURES[feature])
    return overrides


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))], 1)


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [row for row in rows if row["expected_count"]]
    unanswerable = [row for row in rows if not row["expected_count"]]
    latencies = [row["latency_ms"] for row in rows]
    return {
        "cases": len(rows),
        "recall_at_5": round(statistics.fmean(row["recall_at_5"] for row in answerable), 4) if answerable else None,
        "recall_at_12": round(statistics.fmean(row["recall_at_12"] for row in answerable), 4) if answerable else None,
        "mrr": round(statistics.fmean(row["reciprocal_rank"] for row in answerable), 4) if answerable else None,
        "no_context_rate_unanswerable": round(sum(row["returned"] == 0 for row in unanswerable) / len(unanswerable), 4) if unanswerable else None,
        "top_group_share_at_12": round(statistics.fmean(row["top_group_share"] for row in rows), 4) if rows else None,
        "latency_p50_ms": _percentile(latencies, 0.5),
        "latency_p95_ms": _percentile(latencies, 0.95),
    }


def run(*, seller_id: UUID, fixture: Path, top_k: int, configs: list[str]) -> dict[str, Any]:
    from sqlalchemy import select

    from app.core.config import settings
    from app.db.session import SessionLocal
    from app.models.product import Product
    from app.services.rag_retrieval_metrics import ExpectedHit, recall_at_k, reciprocal_rank, top_group_share
    from app.services.rag_retrieval_service import RagRetrievalService

    cases = json.loads(fixture.read_text(encoding="utf-8"))
    report: dict[str, Any] = {"seller_id": str(seller_id), "fixture": str(fixture), "top_k": top_k, "configs": {}}
    with SessionLocal() as session:
        sku_by_product = {
            product_id: sku
            for product_id, sku in session.execute(select(Product.id, Product.sku).where(Product.seller_id == seller_id)).all()
        }
        for config in configs:
            overrides = _overrides(config)
            missing = [name for name in overrides if name not in type(settings).model_fields]
            if any(overrides[name] != NEW_FLAG_DEFAULTS.get(name) for name in missing):
                report["configs"][config] = {"skipped": f"settings not implemented yet: {', '.join(missing)}"}
                continue
            if overrides.get("rag_reranker_enabled"):
                from app.services.rag_reranker_service import RagRerankerService

                # Requests never wait for the model; the eval must, or it would measure the skip path.
                if not RagRerankerService().wait_until_loaded(timeout_s=900):
                    report["configs"][config] = {"skipped": f"reranker model {settings.rag_reranker_model} did not load"}
                    continue
            previous = {name: getattr(settings, name) for name in overrides if name not in missing}
            try:
                for name, value in previous.items():
                    setattr(settings, name, overrides[name])
                rows = [_run_case(case, session=session, seller_id=seller_id, top_k=top_k, translate=bool(overrides.get("rag_keyword_translation_enabled")),
                                  sku_by_product=sku_by_product, service_cls=RagRetrievalService, scorers=(ExpectedHit, recall_at_k, reciprocal_rank, top_group_share))
                        for case in cases]
            finally:
                for name, value in previous.items():
                    setattr(settings, name, value)
            report["configs"][config] = {
                "overall": _summary(rows),
                "by_language": {language: _summary([row for row in rows if row["language"] == language]) for language in sorted({row["language"] for row in rows})},
                "misses": [row for row in rows if row["expected_count"] and row["recall_at_12"] < 1.0],
                "rows": rows,
            }
    return report


def _run_case(case, *, session, seller_id, top_k, translate, sku_by_product, service_cls, scorers) -> dict[str, Any]:
    ExpectedHit, recall_at_k, reciprocal_rank, top_group_share = scorers
    keyword_terms = None
    if translate:
        from app.services.copilot.language import english_search_terms

        keyword_terms = english_search_terms(case["question"])
    started = time.perf_counter()
    kwargs: dict[str, Any] = {"seller_id": seller_id, "question": case["question"], "top_k": top_k}
    if keyword_terms is not None:
        kwargs["keyword_terms"] = keyword_terms
    result = service_cls(session).retrieve_context(**kwargs)
    latency_ms = (time.perf_counter() - started) * 1000
    chunks = [
        {"source_type": getattr(item.source_type, "value", str(item.source_type)), "product_sku": sku_by_product.get(item.product_id), "chunk_text": item.chunk_text}
        for item in result.retrieved_chunks
    ]
    expected = [ExpectedHit(item["source_type"], item.get("product_sku"), tuple(item.get("contains", ()))) for item in case["expected"]]
    return {
        "id": case["id"],
        "language": case["language"],
        "expected_count": len(expected),
        "returned": len(chunks),
        "recall_at_5": recall_at_k(chunks, expected, 5),
        "recall_at_12": recall_at_k(chunks, expected, 12),
        "reciprocal_rank": reciprocal_rank(chunks, expected),
        "top_group_share": top_group_share(chunks, 12),
        "latency_ms": round(latency_ms, 1),
        "top3": [f"{chunk['source_type']}: {chunk['chunk_text'][:80]}" for chunk in chunks[:3]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seller-id", required=True, type=UUID)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--top-k", type=int, default=12)
    parser.add_argument("--configs", default="baseline")
    args = parser.parse_args()
    report = run(seller_id=args.seller_id, fixture=args.fixture, top_k=args.top_k, configs=[item.strip() for item in args.configs.split(",") if item.strip()])
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    for config, body in report["configs"].items():
        print(config, json.dumps(body.get("overall") or body, ensure_ascii=False))
        for language, summary in (body.get("by_language") or {}).items():
            print(f"  {language}", json.dumps(summary))
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
