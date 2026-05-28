from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.repositories.query_utils import PaginationParams, SortDirection, build_pagination_meta
from app.repositories.recommendation_repository import RecommendationRepository
from app.schemas.dashboard.recommendation_schema import (
    RecommendationListResponse,
    RecommendationRecord,
)
from app.services.dashboard.events import DashboardEventEmitter, NoopEventEmitter
from app.services.dashboard.exceptions import DashboardDatabaseError


class RecommendationDashboardService:
    def __init__(
        self,
        repository: RecommendationRepository,
        *,
        logger: logging.Logger | None = None,
        event_emitter: DashboardEventEmitter | None = None,
    ) -> None:
        self._repo = repository
        self._logger = logger or logging.getLogger(__name__)
        self._events = event_emitter or NoopEventEmitter()

    async def list_recommendations(
        self,
        *,
        seller_id: str | None,
        product_id: str | None,
        action_type: str | None,
        confidence: str | None,
        search: str | None,
        date_from: Any,
        date_to: Any,
        sort_by: str,
        sort_direction: SortDirection,
        pagination: PaginationParams,
    ) -> RecommendationListResponse:
        start = time.monotonic()
        try:
            rows, total = await self._repo.list_recommendations(
                seller_id=seller_id,
                product_id=product_id,
                action_type=action_type,
                confidence=confidence,
                search=search,
                date_from=date_from,
                date_to=date_to,
                sort_by=sort_by,
                sort_direction=sort_direction,
                pagination=pagination,
            )
        except SQLAlchemyError as exc:
            raise DashboardDatabaseError("Failed to load recommendations.") from exc
        items = [self._to_record(row) for row in rows]
        meta = build_pagination_meta(total, pagination)
        duration_ms = int((time.monotonic() - start) * 1000)
        self._logger.info(
            "dashboard_recommendations_list total=%s duration_ms=%s seller_id=%s product_id=%s action=%s confidence=%s page=%s page_size=%s",
            total,
            duration_ms,
            seller_id,
            product_id,
            action_type,
            confidence,
            pagination.page,
            pagination.page_size,
        )
        return RecommendationListResponse(items=items, meta=meta)

    def _to_record(self, row: Any) -> RecommendationRecord:
        return RecommendationRecord(
            recommendation_id=str(row["recommendation_id"]),
            product_id=str(row["product_id"]),
            product_title=row["product_title"],
            action_type=str(row["action_type"]),
            confidence=str(row["confidence"]),
            urgency_score=_normalize_score(row.get("urgency_score")),
            price_gap_percent=_to_float(row.get("price_gap_percent")),
            stock_risk_score=_to_float(row.get("stock_risk_score")),
            reasoning=row.get("reasoning") or "",
            revenue_opportunity=_to_float(row.get("revenue_opportunity")) or 0.0,
            created_at=row.get("created_at"),
        )


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_score(value: Any) -> float | None:
    numeric = _to_float(value)
    if numeric is None:
        return None
    if 0 <= numeric <= 1:
        return numeric * 100.0
    return numeric
