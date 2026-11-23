"""Offline retrieval-quality scoring for the RAG eval harness (never used in request handlers).

Chunks are matched by stable criteria (source type, SKU, text fragments) rather than chunk IDs,
so a re-index does not invalidate the golden set.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ExpectedHit:
    source_type: str
    product_sku: str | None = None
    contains: tuple[str, ...] = ()


def hit_matches(chunk: Mapping[str, Any], expected: ExpectedHit) -> bool:
    if chunk.get("source_type") != expected.source_type:
        return False
    if expected.product_sku is not None and chunk.get("product_sku") != expected.product_sku:
        return False
    text = str(chunk.get("chunk_text") or "").casefold()
    return all(fragment.casefold() in text for fragment in expected.contains)


def recall_at_k(chunks: Sequence[Mapping[str, Any]], expected: Sequence[ExpectedHit], k: int) -> float:
    if not expected:
        return 1.0
    top = chunks[:k]
    found = sum(1 for item in expected if any(hit_matches(chunk, item) for chunk in top))
    return found / len(expected)


def reciprocal_rank(chunks: Sequence[Mapping[str, Any]], expected: Sequence[ExpectedHit]) -> float:
    for index, chunk in enumerate(chunks):
        if any(hit_matches(chunk, item) for item in expected):
            return 1 / (index + 1)
    return 0.0


def top_group_share(chunks: Sequence[Mapping[str, Any]], k: int) -> float:
    top = chunks[:k]
    if not top:
        return 0.0
    counts = Counter((chunk.get("source_type"), chunk.get("product_sku")) for chunk in top)
    return max(counts.values()) / len(top)
