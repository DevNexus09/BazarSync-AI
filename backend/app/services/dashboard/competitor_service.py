from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.analytics.metrics import normalize_stock_status
from app.repositories.competitor_repository import CompetitorRepository
from app.repositories.query_utils import PaginationParams, SortDirection, build_pagination_meta
from app.schemas.dashboard.competitor_schema import CompetitorListResponse, CompetitorRecord
from app.services.dashboard.exceptions import DashboardDatabaseError
from app.services.dashboard.events import DashboardEventEmitter, NoopEventEmitter


class CompetitorDashboardService:
    def __init__(
        self,
        repository: CompetitorRepository,
        *,
        logger: logging.Logger | None = None,
        event_emitter: DashboardEventEmitter | None = None,
    ) -> None:
        self._repo = repository
        self._logger = logger or logging.getLogger(__name__)
        self._events = event_emitter or NoopEventEmitter()

    async def list_competitors(
        self,
        *,
        seller_id: str | None,
        product_id: str | None,
        stock_status: str | None,
        search: str | None,
        sort_by: str,
        sort_direction: SortDirection,
        pagination: PaginationParams,
    ) -> CompetitorListResponse:
        start = time.monotonic()
        try:
            rows, total = await self._repo.list_competitors(
                seller_id=seller_id,
                product_id=product_id,
                stock_status=stock_status,
                search=search,
                sort_by=sort_by,
                sort_direction=sort_direction,
                pagination=pagination,
            )
        except SQLAlchemyError as exc:
            raise DashboardDatabaseError("Failed to load competitor data.") from exc
        items = [self._to_record(row) for row in rows]
        meta = build_pagination_meta(total, pagination)
        duration_ms = int((time.monotonic() - start) * 1000)
        self._logger.info(
            "dashboard_competitors_list total=%s duration_ms=%s seller_id=%s product_id=%s search=%s page=%s page_size=%s",
            total,
            duration_ms,
            seller_id,
            product_id,
            search,
            pagination.page,
            pagination.page_size,
        )
        return CompetitorListResponse(
            items=items,
            meta=meta,
        )

    def _to_record(self, row: Any) -> CompetitorRecord:
        status = normalize_stock_status(row.get("stock_status"))
        out_of_stock = status == "out_of_stock"
        return CompetitorRecord(
            competitor_id=str(row["competitor_id"]),
            product_id=str(row["product_id"]),
            product_title=row["product_title"],
            competitor_title=row["competitor_title"],
            competitor_store=row.get("competitor_store"),
            competitor_price=_to_float(row.get("competitor_price")),
            seller_price=_to_float(row.get("seller_price")),
            price_gap_percent=_to_float(row.get("price_gap_percent")),
            stock_status=row.get("stock_status"),
            out_of_stock=out_of_stock,
            ranking_position=row.get("ranking_position"),
            similarity_score=_to_float(row.get("similarity_score")),
            marketplace=row.get("marketplace"),
            product_url=row.get("product_url"),
            price_trend=row.get("price_trend") or "stable",
            created_at=row.get("created_at"),
        )


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
