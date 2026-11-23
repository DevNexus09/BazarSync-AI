"""Helpers for tables that are re-calculated over time (one row per product per run)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

# Dead-stock classifications that still tie up capital.
UNHEALTHY_STOCK_CLASSES = frozenset({"DEAD_STOCK", "AT_RISK", "SLOW_MOVING"})
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def latest_per_product(rows: Iterable[Any], time_field: str) -> list[Any]:
    """Keep only each product's most recent row; older runs describe the past, not today."""
    latest: dict[Any, Any] = {}
    for row in rows:
        current = latest.get(row.product_id)
        if current is None or (getattr(row, time_field) or _EPOCH) > (getattr(current, time_field) or _EPOCH):
            latest[row.product_id] = row
    return list(latest.values())
