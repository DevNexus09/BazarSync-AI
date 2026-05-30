from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import os
import time
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from sqlalchemy import Float, and_, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert
from app.models.competitor import Competitor
from app.models.product import Product
from app.models.recommendation import Recommendation
from app.schemas.dashboard.summary_schema import DashboardSummaryResponse, RealtimeActivityCounters
from app.services.dashboard.exceptions import DashboardDatabaseError
from app.services.dashboard.events import DashboardEventEmitter, NoopEventEmitter


@dataclass(frozen=True)
class DashboardSummaryConfig:
    activity_window_minutes: int = 60
    alert_activity_window_hours: int = 24
    high_stock_risk_threshold: float = 0.7

    @classmethod
    def from_env(cls) -> "DashboardSummaryConfig":
        return cls(
            activity_window_minutes=_get_env_int("BAZARSYNC_ACTIVITY_WINDOW_MINUTES", 60),
            alert_activity_window_hours=_get_env_int(
                "BAZARSYNC_ALERT_ACTIVITY_HOURS", 24
            ),
            high_stock_risk_threshold=_get_env_float(
                "BAZARSYNC_HIGH_STOCK_RISK_THRESHOLD", 0.7
            ),
        )


class DashboardService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        config: DashboardSummaryConfig | None = None,
        logger: logging.Logger | None = None,
        event_emitter: DashboardEventEmitter | None = None,
    ) -> None:
        self._session = session
        self._config = config or DashboardSummaryConfig.from_env()
        self._logger = logger or logging.getLogger(__name__)
        self._events = event_emitter or NoopEventEmitter()

    async def get_summary(self, *, seller_id: str | None = None) -> DashboardSummaryResponse:
        start = time.monotonic()
        now = datetime.now(timezone.utc)
        activity_start = now - timedelta(minutes=self._config.activity_window_minutes)
        alert_window_start = now - timedelta(hours=self._config.alert_activity_window_hours)

        urgency_score_expr = _json_float("urgency_score")
        price_gap_expr = _json_float("price_gap_percent")
        stock_risk_expr = _json_float("stock_risk_score")
        try:
            total_products = await self._session.scalar(
                _count_query(Product.id, seller_id=seller_id)
            )
            active_alerts = await self._session.scalar(
                _count_query(
                    Alert.id,
                    seller_id=seller_id,
                    extra_filter=and_(
                        Alert.created_at >= alert_window_start,
                        Alert.delivery_status != "failed",
                    ),
                )
            )
            opportunity_count = await self._session.scalar(
                _count_query(
                    Recommendation.id,
                    seller_id=seller_id,
                    extra_filter=Recommendation.revenue_opportunity > 0,
                )
            )
            high_risk_stock_count = await self._session.scalar(
                _count_query(
                    Recommendation.id,
                    seller_id=seller_id,
                    extra_filter=stock_risk_expr >= self._config.high_stock_risk_threshold,
                )
            )

            average_urgency_score = await self._session.scalar(
                _avg_query(urgency_score_expr, seller_id=seller_id)
            )
            latest_urgency_score = await self._session.scalar(
                _latest_score_query(urgency_score_expr, seller_id=seller_id)
            )
            average_price_gap = await self._session.scalar(
                _avg_query(price_gap_expr, seller_id=seller_id)
            )

            recommendations_last_hour = await self._session.scalar(
                _count_query(
                    Recommendation.id,
                    seller_id=seller_id,
                    extra_filter=Recommendation.created_at >= activity_start,
                )
            )
            alerts_last_hour = await self._session.scalar(
                _count_query(
                    Alert.id,
                    seller_id=seller_id,
                    extra_filter=Alert.created_at >= activity_start,
                )
            )
            competitor_updates_last_hour = await self._session.scalar(
                _count_query(
                    Competitor.id,
                    seller_id=seller_id,
                    extra_filter=Competitor.updated_at >= activity_start,
                    join_product=True,
                )
            )
            stock_risk_events_last_hour = await self._session.scalar(
                _count_query(
                    Recommendation.id,
                    seller_id=seller_id,
                    extra_filter=and_(
                        Recommendation.created_at >= activity_start,
                        stock_risk_expr >= self._config.high_stock_risk_threshold,
                    ),
                )
            )
        except SQLAlchemyError as exc:
            raise DashboardDatabaseError("Failed to load dashboard summary.") from exc

        normalized_urgency = _normalize_score(average_urgency_score)
        latest_urgency = _normalize_score(latest_urgency_score)
        normalized_gap = float(average_price_gap or 0.0)
        trend_summary = _build_market_trend_summary(normalized_urgency, normalized_gap)

        duration_ms = int((time.monotonic() - start) * 1000)
        self._logger.info(
            "dashboard_summary duration_ms=%s seller_id=%s total_products=%s",
            duration_ms,
            seller_id,
            total_products,
        )

        return DashboardSummaryResponse(
            total_monitored_products=total_products or 0,
            active_alerts=active_alerts or 0,
            opportunity_count=opportunity_count or 0,
            high_risk_stock_count=high_risk_stock_count or 0,
            average_urgency_score=round(normalized_urgency, 2),
            latest_urgency_score=round(latest_urgency, 2),
            average_competitor_price_gap=round(normalized_gap, 2),
            market_trend_summary=trend_summary,
            realtime_activity=RealtimeActivityCounters(
                recommendations_last_hour=recommendations_last_hour or 0,
                alerts_last_hour=alerts_last_hour or 0,
                competitor_updates_last_hour=competitor_updates_last_hour or 0,
                stock_risk_events_last_hour=stock_risk_events_last_hour or 0,
            ),
            generated_at=now,
        )


def _json_float(key: str):
    analytics = Recommendation.recommendation_context["analytics"]
    return cast(analytics[key].astext, Float)


def _count_query(
    column,
    *,
    seller_id: str | None,
    extra_filter=None,
    join_product: bool = False,
):
    stmt = select(func.count(column)).select_from(column.table)
    if join_product:
        stmt = stmt.select_from(Competitor).join(Product, Competitor.product_id == Product.id)
    if seller_id and not join_product:
        if column.table.name == "products":
            stmt = stmt.where(Product.seller_id == seller_id)
        elif column.table.name == "alerts":
            stmt = stmt.where(Alert.seller_id == seller_id)
        elif column.table.name == "recommendations":
            stmt = stmt.join(Product, Recommendation.product_id == Product.id).where(
                Product.seller_id == seller_id
            )
    if seller_id and join_product:
        stmt = stmt.where(Product.seller_id == seller_id)
    if extra_filter is not None:
        stmt = stmt.where(extra_filter)
    return stmt


def _avg_query(expression, *, seller_id: str | None):
    stmt = select(func.avg(expression)).select_from(Recommendation)
    if seller_id:
        stmt = stmt.join(Product, Recommendation.product_id == Product.id).where(
            Product.seller_id == seller_id
        )
    return stmt


def _latest_score_query(expression, *, seller_id: str | None):
    stmt = select(expression).select_from(Recommendation)
    if seller_id:
        stmt = stmt.join(Product, Recommendation.product_id == Product.id).where(
            Product.seller_id == seller_id
        )
    stmt = stmt.order_by(Recommendation.created_at.desc(), Recommendation.id.desc()).limit(1)
    return stmt


def _build_market_trend_summary(avg_urgency: float, avg_gap: float) -> str:
    if avg_urgency >= 75:
        return "High volatility with aggressive competitor pressure."
    if avg_urgency >= 55 and avg_gap >= 5:
        return "Moderate volatility with rising competitor pressure."
    if avg_urgency >= 55:
        return "Moderate volatility with stable pricing."
    if avg_gap >= 5:
        return "Stable demand but widening price gaps."
    return "Stable market conditions with balanced pricing."


def _normalize_score(value: float | None) -> float:
    if value is None:
        return 0.0
    numeric = float(value)
    if 0 <= numeric <= 1:
        return numeric * 100.0
    return numeric


def _get_env_int(key: str, default: int) -> int:
    value = os.getenv(key)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_env_float(key: str, default: float) -> float:
    value = os.getenv(key)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default
