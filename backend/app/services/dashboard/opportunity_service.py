from __future__ import annotations

import logging
import time
from typing import Any, Mapping

from sqlalchemy.exc import SQLAlchemyError

from app.recommendations.opportunity_calculator import OpportunityCalculator, OpportunityInput
from app.repositories.query_utils import PaginationParams, SortDirection, build_pagination_meta
from app.repositories.recommendation_repository import RecommendationRepository
from app.schemas.dashboard.opportunity_schema import OpportunityListResponse, OpportunityRecord
from app.services.dashboard.events import DashboardEventEmitter, NoopEventEmitter
from app.services.dashboard.exceptions import DashboardDatabaseError


class OpportunityDashboardService:
    def __init__(
        self,
        repository: RecommendationRepository,
        *,
        calculator: OpportunityCalculator | None = None,
        logger: logging.Logger | None = None,
        event_emitter: DashboardEventEmitter | None = None,
    ) -> None:
        self._repo = repository
        self._calculator = calculator or OpportunityCalculator()
        self._logger = logger or logging.getLogger(__name__)
        self._events = event_emitter or NoopEventEmitter()

    async def list_opportunities(
        self,
        *,
        seller_id: str | None,
        min_revenue: float | None,
        date_from: Any,
        date_to: Any,
        sort_by: str,
        sort_direction: SortDirection,
        pagination: PaginationParams,
    ) -> OpportunityListResponse:
        start = time.monotonic()
        try:
            rows, total = await self._repo.list_opportunities(
                seller_id=seller_id,
                min_revenue=min_revenue,
                date_from=date_from,
                date_to=date_to,
                sort_by=sort_by,
                sort_direction=sort_direction,
                pagination=pagination,
            )
        except SQLAlchemyError as exc:
            raise DashboardDatabaseError("Failed to load opportunity analytics.") from exc
        items = [self._to_record(row) for row in rows]
        meta = build_pagination_meta(total, pagination)
        duration_ms = int((time.monotonic() - start) * 1000)
        self._logger.info(
            "dashboard_opportunities_list total=%s duration_ms=%s seller_id=%s min_revenue=%s page=%s page_size=%s",
            total,
            duration_ms,
            seller_id,
            min_revenue,
            pagination.page,
            pagination.page_size,
        )
        return OpportunityListResponse(items=items, meta=meta)

    def _to_record(self, row: Mapping[str, Any]) -> OpportunityRecord:
        context, analytics = _split_context_snapshot(row.get("recommendation_context"))
        seller_price = _to_float(context.get("seller_price")) or _to_float(row.get("seller_price")) or 0.0
        recommended_price = _to_float(context.get("recommended_price"))
        stock_quantity = _to_int(context.get("seller_stock")) or _to_int(row.get("stock_quantity")) or 0
        margin_percent = _to_float(analytics.get("estimated_margin_percent"))
        if margin_percent is None:
            margin_percent = _compute_margin_percent(
                _to_float(row.get("seller_price")) or 0.0,
                _to_float(row.get("cost_price")) or 0.0,
            )
        opportunity_score = _to_float(analytics.get("opportunity_score"))
        if opportunity_score is None:
            opportunity_score = _to_float(analytics.get("market_competitiveness_score")) or 0.0
        demand_indicator = _to_float(analytics.get("demand_indicator")) or 0.0
        competitor_oos_ratio = _compute_oos_ratio(analytics)
        inventory_turnover_days = _to_float(context.get("inventory_turnover_days"))

        opportunity_input = OpportunityInput(
            seller_price=seller_price,
            recommended_price=recommended_price,
            current_stock=stock_quantity,
            margin_percent=margin_percent,
            opportunity_score=opportunity_score,
            demand_indicator=demand_indicator,
            competitor_oos_ratio=competitor_oos_ratio,
            inventory_turnover_days=inventory_turnover_days,
        )
        result = self._calculator.calculate(opportunity_input)
        return OpportunityRecord(
            recommendation_id=str(row["recommendation_id"]),
            product_id=str(row["product_id"]),
            product_title=row["product_title"],
            revenue_opportunity=_to_float(row.get("revenue_opportunity")) or 0.0,
            inventory_capture_units=result.inventory_capture_units,
            projected_demand_shift=result.projected_demand_shift,
            estimated_profit_impact=result.estimated_profit_impact,
            competitor_oos_ratio=competitor_oos_ratio,
            market_opportunity_score=result.revenue_opportunity_score,
            created_at=row.get("created_at"),
        )


def _split_context_snapshot(payload: Mapping[str, Any] | None) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        return {}, {}
    if "context" in payload or "analytics" in payload:
        context = payload.get("context")
        analytics = payload.get("analytics")
        return (
            context if isinstance(context, Mapping) else {},
            analytics if isinstance(analytics, Mapping) else {},
        )
    return payload, {}


def _compute_oos_ratio(analytics: Mapping[str, Any]) -> float:
    out_of_stock = _to_int(analytics.get("out_of_stock_competitor_count")) or 0
    in_stock = _to_int(analytics.get("in_stock_competitor_count")) or 0
    total = out_of_stock + in_stock
    if total == 0:
        return 0.0
    return out_of_stock / total


def _compute_margin_percent(selling_price: float, cost_price: float) -> float:
    if selling_price <= 0:
        return 0.0
    return ((selling_price - cost_price) / selling_price) * 100.0


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
