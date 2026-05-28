from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import Float, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.recommendation import Recommendation
from app.repositories.query_utils import (
    PaginationParams,
    SortDirection,
    apply_date_range,
    apply_search,
    apply_sorting,
)


class RecommendationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_recommendations(
        self,
        *,
        seller_id: str | None = None,
        product_id: str | None = None,
        action_type: str | None = None,
        confidence: str | None = None,
        search: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        sort_by: str,
        sort_direction: SortDirection,
        pagination: PaginationParams,
    ) -> tuple[list[Mapping[str, Any]], int]:
        analytics = Recommendation.recommendation_context["analytics"]
        urgency_score_expr = cast(analytics["urgency_score"].astext, Float).label(
            "urgency_score"
        )
        price_gap_expr = cast(analytics["price_gap_percent"].astext, Float).label(
            "price_gap_percent"
        )
        stock_risk_expr = cast(analytics["stock_risk_score"].astext, Float).label(
            "stock_risk_score"
        )

        base_stmt = (
            select(
                Recommendation.id.label("recommendation_id"),
                Recommendation.product_id.label("product_id"),
                Product.title.label("product_title"),
                Recommendation.action.label("action_type"),
                Recommendation.confidence.label("confidence"),
                Recommendation.reasoning_bn.label("reasoning"),
                Recommendation.revenue_opportunity.label("revenue_opportunity"),
                Recommendation.created_at.label("created_at"),
                urgency_score_expr,
                price_gap_expr,
                stock_risk_expr,
            )
            .join(Product, Recommendation.product_id == Product.id)
        )

        if seller_id:
            base_stmt = base_stmt.where(Product.seller_id == seller_id)
        if product_id:
            base_stmt = base_stmt.where(Recommendation.product_id == product_id)
        if action_type:
            base_stmt = base_stmt.where(Recommendation.action == action_type)
        if confidence:
            base_stmt = base_stmt.where(Recommendation.confidence == confidence)

        base_stmt = apply_search(
            base_stmt,
            search=search,
            columns=[Product.title, Recommendation.reasoning_bn],
        )
        base_stmt = apply_date_range(
            base_stmt,
            column=Recommendation.created_at,
            start=date_from,
            end=date_to,
        )

        allowed_sort = {
            "created_at": Recommendation.created_at,
            "urgency_score": urgency_score_expr,
            "confidence": Recommendation.confidence,
            "opportunity": Recommendation.revenue_opportunity,
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

    async def list_opportunities(
        self,
        *,
        seller_id: str | None = None,
        min_revenue: float | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        sort_by: str,
        sort_direction: SortDirection,
        pagination: PaginationParams,
    ) -> tuple[list[Mapping[str, Any]], int]:
        analytics = Recommendation.recommendation_context["analytics"]
        base_stmt = (
            select(
                Recommendation.id.label("recommendation_id"),
                Recommendation.product_id.label("product_id"),
                Product.title.label("product_title"),
                Recommendation.revenue_opportunity.label("revenue_opportunity"),
                Recommendation.recommendation_context.label("recommendation_context"),
                Recommendation.created_at.label("created_at"),
                Product.selling_price.label("seller_price"),
                Product.cost_price.label("cost_price"),
                Product.stock_quantity.label("stock_quantity"),
            )
            .join(Product, Recommendation.product_id == Product.id)
            .where(Recommendation.revenue_opportunity > 0)
        )

        if seller_id:
            base_stmt = base_stmt.where(Product.seller_id == seller_id)
        if min_revenue is not None:
            base_stmt = base_stmt.where(Recommendation.revenue_opportunity >= min_revenue)

        base_stmt = apply_date_range(
            base_stmt,
            column=Recommendation.created_at,
            start=date_from,
            end=date_to,
        )

        allowed_sort = {
            "revenue_opportunity": Recommendation.revenue_opportunity,
            "created_at": Recommendation.created_at,
            "market_opportunity_score": cast(
                analytics["market_opportunity_score"].astext, Float
            ),
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
