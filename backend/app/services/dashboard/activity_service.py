from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import Float, cast, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert
from app.models.competitor import Competitor
from app.models.product import Product
from app.models.recommendation import Recommendation
from app.schemas.dashboard.activity_schema import ActivityCategory, ActivityItem, ActivitySeverity
from app.services.dashboard.exceptions import DashboardDatabaseError


class ActivityDashboardService:
    def __init__(self, session: AsyncSession, *, logger: logging.Logger | None = None) -> None:
        self._session = session
        self._logger = logger or logging.getLogger(__name__)

    async def get_activity_feed(
        self, *, seller_id: str, limit: int = 12
    ) -> list[ActivityItem]:
        start = time.monotonic()
        per_stream = max(limit, 6)
        try:
            recommendations = await self._fetch_recommendations(seller_id, per_stream)
            alerts = await self._fetch_alerts(seller_id, per_stream)
            competitors = await self._fetch_competitors(seller_id, per_stream)
        except SQLAlchemyError as exc:
            raise DashboardDatabaseError("Failed to load activity feed.") from exc

        items = recommendations + alerts + competitors
        items.sort(key=lambda item: item.timestamp, reverse=True)
        trimmed = items[:limit]
        duration_ms = int((time.monotonic() - start) * 1000)
        self._logger.info(
            "dashboard_activity_feed count=%s duration_ms=%s seller_id=%s",
            len(trimmed),
            duration_ms,
            seller_id,
        )
        return trimmed

    async def _fetch_recommendations(self, seller_id: str, limit: int) -> list[ActivityItem]:
        analytics = Recommendation.recommendation_context["analytics"]
        urgency_expr = cast(analytics["urgency_score"].astext, Float).label("urgency_score")
        stmt = (
            select(
                Recommendation.id.label("recommendation_id"),
                Recommendation.action.label("action_type"),
                Recommendation.reasoning_bn.label("reasoning"),
                Recommendation.created_at.label("created_at"),
                Product.title.label("product_title"),
                urgency_expr,
            )
            .join(Product, Recommendation.product_id == Product.id)
            .where(Product.seller_id == seller_id)
            .order_by(Recommendation.created_at.desc(), Recommendation.id.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        rows = result.mappings().all()
        items: list[ActivityItem] = []
        for row in rows:
            urgency = _normalize_score(row.get("urgency_score"))
            severity = _severity_from_score(urgency)
            action_label = _format_action(row.get("action_type"))
            product_title = row.get("product_title") or "product"
            description = (
                row.get("reasoning") or f"{action_label} recommendation for {product_title}."
            )
            items.append(
                ActivityItem(
                    id=f"rec-{row['recommendation_id']}",
                    title="Recommendation generated",
                    description=description,
                    timestamp=row.get("created_at"),
                    category=ActivityCategory.recommendation,
                    severity=severity,
                )
            )
        return items

    async def _fetch_alerts(self, seller_id: str, limit: int) -> list[ActivityItem]:
        stmt = (
            select(
                Alert.id.label("alert_id"),
                Alert.alert_type.label("alert_type"),
                Alert.urgency_level.label("urgency_level"),
                Alert.action_type.label("action_type"),
                Alert.created_at.label("created_at"),
                Product.title.label("product_title"),
            )
            .join(Product, Alert.product_id == Product.id)
            .where(Alert.seller_id == seller_id)
            .order_by(Alert.created_at.desc(), Alert.id.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        rows = result.mappings().all()
        items: list[ActivityItem] = []
        for row in rows:
            product_title = row.get("product_title") or "product"
            action_label = _format_label(row.get("action_type"))
            alert_label = _format_label(row.get("alert_type"))
            items.append(
                ActivityItem(
                    id=f"alert-{row['alert_id']}",
                    title=f"{action_label.title()} alert",
                    description=f"{alert_label} alert for {product_title}.",
                    timestamp=row.get("created_at"),
                    category=ActivityCategory.alert,
                    severity=_severity_from_urgency(row.get("urgency_level")),
                )
            )
        return items

    async def _fetch_competitors(self, seller_id: str, limit: int) -> list[ActivityItem]:
        stmt = (
            select(
                Competitor.id.label("competitor_id"),
                Competitor.competitor_title.label("competitor_title"),
                Competitor.stock_status.label("stock_status"),
                Competitor.updated_at.label("updated_at"),
                Product.title.label("product_title"),
            )
            .join(Product, Competitor.product_id == Product.id)
            .where(Product.seller_id == seller_id)
            .order_by(Competitor.updated_at.desc(), Competitor.id.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        rows = result.mappings().all()
        items: list[ActivityItem] = []
        for row in rows:
            competitor_title = row.get("competitor_title") or "Competitor"
            product_title = row.get("product_title") or "product"
            severity = (
                ActivitySeverity.warning
                if (row.get("stock_status") or "").lower() in {"out_of_stock", "low_stock"}
                else ActivitySeverity.info
            )
            items.append(
                ActivityItem(
                    id=f"comp-{row['competitor_id']}",
                    title="Competitor update",
                    description=f"{competitor_title} adjusted {product_title}.",
                    timestamp=row.get("updated_at"),
                    category=ActivityCategory.competitor,
                    severity=severity,
                )
            )
        return items


def _normalize_score(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if 0 <= numeric <= 1:
        return numeric * 100.0
    return numeric


def _severity_from_score(score: float) -> ActivitySeverity:
    if score >= 80:
        return ActivitySeverity.critical
    if score >= 60:
        return ActivitySeverity.warning
    return ActivitySeverity.info


def _severity_from_urgency(value: Any) -> ActivitySeverity:
    level = str(value or "").upper()
    if level == "CRITICAL":
        return ActivitySeverity.critical
    if level in {"HIGH", "MEDIUM"}:
        return ActivitySeverity.warning
    return ActivitySeverity.info


def _format_label(value: Any) -> str:
    if value is None:
        return "alert"
    return str(value).replace("_", " ").lower()


def _format_action(value: Any) -> str:
    normalized = str(value or "").upper()
    if normalized == "LOWER":
        return "Lower price"
    if normalized == "RAISE":
        return "Raise price"
    if normalized == "REORDER":
        return "Restock"
    return "Hold"
