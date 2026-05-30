from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import time
from typing import Any

from sqlalchemy import Float, case, cast, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.recommendation import Recommendation
from app.schemas.dashboard.market_trend_schema import MarketTrendPoint
from app.services.dashboard.exceptions import DashboardDatabaseError


class MarketTrendDashboardService:
    def __init__(self, session: AsyncSession, *, logger: logging.Logger | None = None) -> None:
        self._session = session
        self._logger = logger or logging.getLogger(__name__)

    async def get_market_trends(
        self, *, seller_id: str, days: int = 14
    ) -> list[MarketTrendPoint]:
        start = time.monotonic()
        window_start = datetime.now(timezone.utc) - timedelta(days=days)
        analytics = Recommendation.recommendation_context["analytics"]
        urgency_expr = cast(analytics["urgency_score"].astext, Float)
        market_comp_expr = cast(analytics["market_competitiveness_score"].astext, Float)
        pricing_pressure_expr = cast(analytics["pricing_pressure_score"].astext, Float)
        price_gap_expr = cast(analytics["price_gap_percent"].astext, Float)
        out_of_stock_expr = cast(analytics["out_of_stock_competitor_count"].astext, Float)
        in_stock_expr = cast(analytics["in_stock_competitor_count"].astext, Float)
        total_expr = out_of_stock_expr + in_stock_expr
        demand_ratio_expr = case(
            (total_expr > 0, out_of_stock_expr / total_expr),
            else_=0.0,
        )
        bucket = func.date_trunc("day", Recommendation.created_at).label("bucket")
        stmt = (
            select(
                bucket,
                func.avg(urgency_expr).label("urgency_score"),
                func.avg(market_comp_expr).label("market_competitiveness_score"),
                func.avg(pricing_pressure_expr).label("pricing_pressure_score"),
                func.avg(price_gap_expr).label("price_gap"),
                func.avg(demand_ratio_expr).label("demand_ratio"),
            )
            .join(Product, Recommendation.product_id == Product.id)
            .where(Product.seller_id == seller_id)
            .where(Recommendation.created_at >= window_start)
            .group_by(bucket)
            .order_by(bucket)
        )
        try:
            result = await self._session.execute(stmt)
            rows = result.mappings().all()
        except SQLAlchemyError as exc:
            raise DashboardDatabaseError("Failed to load market trends.") from exc

        points: list[MarketTrendPoint] = []
        for row in rows:
            opportunity_raw = row.get("market_competitiveness_score")
            if opportunity_raw is None:
                opportunity_raw = row.get("pricing_pressure_score")
            points.append(
                MarketTrendPoint(
                    timestamp=row["bucket"],
                    demand_index=_normalize_index(row.get("demand_ratio"), scale=100.0),
                    urgency_index=_normalize_index(row.get("urgency_score"), scale=100.0),
                    opportunity_index=_normalize_index(opportunity_raw, scale=100.0),
                    price_index=_to_float(row.get("price_gap")) or 0.0,
                )
            )

        duration_ms = int((time.monotonic() - start) * 1000)
        self._logger.info(
            "dashboard_market_trends count=%s duration_ms=%s seller_id=%s",
            len(points),
            duration_ms,
            seller_id,
        )
        return points


def _normalize_index(value: Any, *, scale: float) -> float:
    numeric = _to_float(value)
    if numeric is None:
        return 0.0
    if 0 <= numeric <= 1:
        return numeric * scale
    return numeric


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
