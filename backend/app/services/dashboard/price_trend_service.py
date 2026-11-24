from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import time
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.product import Product
from app.schemas.dashboard.price_trend_schema import CompetitorPriceTrendPoint
from app.services.dashboard.exceptions import DashboardDatabaseError


class CompetitorPriceTrendService:
    def __init__(self, session: AsyncSession, *, logger: logging.Logger | None = None) -> None:
        self._session = session
        self._logger = logger or logging.getLogger(__name__)

    async def get_price_trend(
        self,
        *,
        seller_id: str,
        product_id: str | None = None,
        days: int = 14,
    ) -> list[CompetitorPriceTrendPoint]:
        start = time.monotonic()
        window_start = datetime.now(timezone.utc) - timedelta(days=days)
        # Snapshots are written for every scrape run (including seeded history);
        # price_history only covers live scrapes, which left the chart with one day.
        observed_at = func.coalesce(
            CompetitorSnapshot.price_observed_at, CompetitorSnapshot.captured_at
        )
        bucket = func.date_trunc("day", observed_at).label("bucket")

        stmt = (
            select(
                bucket,
                func.min(CompetitorSnapshot.price).label("competitor_price"),
                func.avg(CompetitorSnapshot.price).label("market_average"),
                func.avg(Product.selling_price).label("seller_price"),
            )
            .join(Product, CompetitorSnapshot.product_id == Product.id)
            .where(Product.seller_id == seller_id)
            .where(CompetitorSnapshot.price.is_not(None))
            .where(observed_at >= window_start)
            .group_by(bucket)
            .order_by(bucket)
        )

        product_uuid = _to_uuid(product_id)
        if product_id and not product_uuid:
            return []
        if product_uuid:
            stmt = stmt.where(Product.id == product_uuid)

        try:
            result = await self._session.execute(stmt)
            rows = result.mappings().all()
        except SQLAlchemyError as exc:
            raise DashboardDatabaseError("Failed to load competitor price trends.") from exc

        points = [
            CompetitorPriceTrendPoint(
                timestamp=row["bucket"],
                competitor_price=_to_float(row.get("competitor_price")) or 0.0,
                seller_price=_to_float(row.get("seller_price")) or 0.0,
                market_average=_to_float(row.get("market_average")) or 0.0,
            )
            for row in rows
        ]
        duration_ms = int((time.monotonic() - start) * 1000)
        self._logger.info(
            "dashboard_price_trend count=%s duration_ms=%s seller_id=%s product_id=%s",
            len(points),
            duration_ms,
            seller_id,
            product_id,
        )
        return points


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_uuid(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None
