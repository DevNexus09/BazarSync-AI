from __future__ import annotations

import logging
import time
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.recommendation import Recommendation, RecommendationAction, RecommendationConfidence
from app.schemas.dashboard.opportunity_metrics_schema import OpportunityMetricRecord
from app.services.dashboard.exceptions import DashboardDatabaseError


class OpportunityMetricsService:
    def __init__(self, session: AsyncSession, *, logger: logging.Logger | None = None) -> None:
        self._session = session
        self._logger = logger or logging.getLogger(__name__)

    async def get_metrics(self, *, seller_id: str) -> list[OpportunityMetricRecord]:
        start = time.monotonic()
        stmt = (
            select(Recommendation, Product.title.label("product_title"))
            .join(Product, Recommendation.product_id == Product.id)
            .where(Product.seller_id == seller_id)
            .order_by(Recommendation.created_at.desc(), Recommendation.id.desc())
            .limit(2)
        )
        try:
            result = await self._session.execute(stmt)
            rows = result.all()
        except SQLAlchemyError as exc:
            raise DashboardDatabaseError("Failed to load opportunity metrics.") from exc

        latest = rows[0] if rows else None
        previous = rows[1] if len(rows) > 1 else None

        latest_rec = latest[0] if latest else None
        prev_rec = previous[0] if previous else None
        if latest_rec is None:
            # No recommendations means no evidence; return nothing rather than zero-valued tiles.
            return []

        _, latest_analytics = _split_context_snapshot(
            latest_rec.recommendation_context if latest_rec else None
        )
        _, prev_analytics = _split_context_snapshot(
            prev_rec.recommendation_context if prev_rec else None
        )

        revenue_now = _to_float(latest_rec.revenue_opportunity) if latest_rec else 0.0
        revenue_prev = _to_float(prev_rec.revenue_opportunity) if prev_rec else None
        confidence_now = _confidence_score(latest_rec.confidence) if latest_rec else 0.0
        confidence_prev = _confidence_score(prev_rec.confidence) if prev_rec else None
        opportunity_now = _normalize_index(
            latest_analytics.get("market_competitiveness_score")
            or latest_analytics.get("opportunity_score")
        )
        opportunity_prev = _normalize_index(
            prev_analytics.get("market_competitiveness_score")
            or prev_analytics.get("opportunity_score")
        )

        metrics = [
            OpportunityMetricRecord(
                id="revenue-opportunity",
                label="Revenue opportunity",
                value=revenue_now or 0.0,
                delta=_delta(revenue_now, revenue_prev),
                trend=_trend(revenue_now, revenue_prev),
            ),
            OpportunityMetricRecord(
                id="confidence",
                label="Confidence",
                value=confidence_now,
                delta=_delta(confidence_now, confidence_prev),
                trend=_trend(confidence_now, confidence_prev),
            ),
            OpportunityMetricRecord(
                id="action-recommendation",
                label="Action recommendation",
                value=_action_label(latest_rec.action if latest_rec else None),
                delta=_action_delta(
                    latest_rec.action if latest_rec else None,
                    prev_rec.action if prev_rec else None,
                ),
                trend="flat",
            ),
            OpportunityMetricRecord(
                id="opportunity-score",
                label="Opportunity score",
                value=opportunity_now,
                delta=_delta(opportunity_now, opportunity_prev),
                trend=_trend(opportunity_now, opportunity_prev),
            ),
        ]

        duration_ms = int((time.monotonic() - start) * 1000)
        self._logger.info(
            "dashboard_opportunity_metrics duration_ms=%s seller_id=%s",
            duration_ms,
            seller_id,
        )
        return metrics


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


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _confidence_score(value: RecommendationConfidence | None) -> float:
    if value is RecommendationConfidence.HIGH:
        return 90.0
    if value is RecommendationConfidence.MEDIUM:
        return 70.0
    if value is RecommendationConfidence.LOW:
        return 50.0
    return 0.0


def _normalize_index(value: Any) -> float:
    numeric = _to_float(value)
    if 0 <= numeric <= 1:
        return numeric * 100.0
    return numeric


def _delta(current: float, previous: float | None) -> float | None:
    if previous is None:
        return None
    return round(current - previous, 2)


def _trend(current: float, previous: float | None) -> str:
    if previous is None:
        return "flat"
    if current > previous:
        return "up"
    if current < previous:
        return "down"
    return "flat"


def _action_label(action: RecommendationAction | None) -> str:
    if action is RecommendationAction.LOWER:
        return "Lower price"
    if action is RecommendationAction.RAISE:
        return "Raise price"
    if action is RecommendationAction.REORDER:
        return "Restock"
    if action is RecommendationAction.HOLD:
        return "Hold"
    return "Hold"


def _action_delta(
    current: RecommendationAction | None, previous: RecommendationAction | None
) -> str:
    if not previous:
        return "Latest"
    if current == previous:
        return "Stable"
    return "Updated"
