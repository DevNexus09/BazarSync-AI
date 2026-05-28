from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert
from app.models.product import Product
from app.repositories.query_utils import PaginationParams, SortDirection, apply_date_range, apply_sorting


class AlertRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_alerts(
        self,
        *,
        seller_id: str | None = None,
        product_id: str | None = None,
        urgency_level: str | None = None,
        action_type: str | None = None,
        delivery_status: str | None = None,
        is_read: bool | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        sort_by: str,
        sort_direction: SortDirection,
        pagination: PaginationParams,
    ) -> tuple[list[Mapping[str, Any]], int]:
        base_stmt = (
            select(
                Alert.id.label("alert_id"),
                Alert.product_id.label("product_id"),
                Product.title.label("product_title"),
                Alert.alert_type.label("alert_type"),
                Alert.urgency_level.label("urgency_level"),
                Alert.action_type.label("action_type"),
                Alert.confidence.label("confidence"),
                Alert.delivery_status.label("delivery_status"),
                Alert.delivered_at.label("delivered_at"),
                Alert.read_at.label("read_at"),
                Alert.telegram_chat_id.label("telegram_chat_id"),
                Alert.telegram_message_id.label("telegram_message_id"),
                Alert.created_at.label("created_at"),
            )
            .join(Product, Alert.product_id == Product.id)
        )

        if seller_id:
            base_stmt = base_stmt.where(Alert.seller_id == seller_id)
        if product_id:
            base_stmt = base_stmt.where(Alert.product_id == product_id)
        if urgency_level:
            base_stmt = base_stmt.where(Alert.urgency_level == urgency_level)
        if action_type:
            base_stmt = base_stmt.where(Alert.action_type == action_type)
        if delivery_status:
            base_stmt = base_stmt.where(Alert.delivery_status == delivery_status)
        if is_read is True:
            base_stmt = base_stmt.where(Alert.read_at.is_not(None))
        if is_read is False:
            base_stmt = base_stmt.where(Alert.read_at.is_(None))

        base_stmt = apply_date_range(
            base_stmt,
            column=Alert.created_at,
            start=date_from,
            end=date_to,
        )

        urgency_rank = case(
            (Alert.urgency_level == "CRITICAL", 4),
            (Alert.urgency_level == "HIGH", 3),
            (Alert.urgency_level == "MEDIUM", 2),
            (Alert.urgency_level == "LOW", 1),
            else_=0,
        )
        allowed_sort = {
            "created_at": Alert.created_at,
            "urgency_score": urgency_rank,
            "delivery_status": Alert.delivery_status,
        }
        base_stmt = apply_sorting(
            base_stmt,
            sort_by=sort_by,
            sort_direction=sort_direction,
            allowed=allowed_sort,
        )

        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total = await self._session.scalar(count_stmt) or 0

        page_stmt = base_stmt.limit(pagination.limit).offset(pagination.offset)
        result = await self._session.execute(page_stmt)
        rows = result.mappings().all()
        return rows, total
