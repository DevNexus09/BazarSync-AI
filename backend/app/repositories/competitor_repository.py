from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import Float, and_, case, cast, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.competitor import Competitor
from app.models.price_history import PriceHistory
from app.models.product import Product
from app.repositories.query_utils import PaginationParams, SortDirection, apply_search, apply_sorting


class CompetitorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_competitors(
        self,
        *,
        seller_id: str | None = None,
        product_id: str | None = None,
        stock_status: str | None = None,
        search: str | None = None,
        sort_by: str,
        sort_direction: SortDirection,
        pagination: PaginationParams,
    ) -> tuple[list[Mapping[str, Any]], int]:
        price_gap_expr = case(
            (
                and_(Competitor.competitor_price.is_not(None), Competitor.competitor_price > 0),
                (
                    (cast(Product.selling_price, Float) - cast(Competitor.competitor_price, Float))
                    / cast(Competitor.competitor_price, Float)
                    * 100.0
                ),
            ),
            else_=None,
        ).label("price_gap_percent")

        trend_subquery = self._price_trend_subquery()
        trend_expr = case(
            (trend_subquery.c.latest_price.is_(None), literal("stable")),
            (trend_subquery.c.previous_price.is_(None), literal("stable")),
            (trend_subquery.c.latest_price > trend_subquery.c.previous_price, literal("up")),
            (trend_subquery.c.latest_price < trend_subquery.c.previous_price, literal("down")),
            else_=literal("flat"),
        ).label("price_trend")

        base_stmt = (
            select(
                Competitor.id.label("competitor_id"),
                Competitor.product_id.label("product_id"),
                Product.title.label("product_title"),
                Product.selling_price.label("seller_price"),
                Competitor.competitor_title.label("competitor_title"),
                Competitor.competitor_store.label("competitor_store"),
                Competitor.competitor_price.label("competitor_price"),
                Competitor.stock_status.label("stock_status"),
                Competitor.search_position.label("ranking_position"),
                Competitor.similarity_score.label("similarity_score"),
                Competitor.marketplace.label("marketplace"),
                Competitor.product_url.label("product_url"),
                Competitor.created_at.label("created_at"),
                price_gap_expr,
                trend_expr,
            )
            .join(Product, Competitor.product_id == Product.id)
            .outerjoin(trend_subquery, trend_subquery.c.competitor_id == Competitor.id)
        )

        if seller_id:
            base_stmt = base_stmt.where(Product.seller_id == seller_id)
        if product_id:
            base_stmt = base_stmt.where(Competitor.product_id == product_id)
        if stock_status:
            base_stmt = base_stmt.where(Competitor.stock_status == stock_status)

        base_stmt = apply_search(
            base_stmt,
            search=search,
            columns=[Competitor.competitor_title, Competitor.competitor_store, Product.title],
        )

        allowed_sort = {
            "created_at": Competitor.created_at,
            "price_gap": price_gap_expr,
            "ranking_position": Competitor.search_position,
            "similarity_score": Competitor.similarity_score,
            "competitor_price": Competitor.competitor_price,
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

    def _price_trend_subquery(self):
        ranked = select(
            PriceHistory.competitor_id.label("competitor_id"),
            PriceHistory.observed_price.label("observed_price"),
            func.row_number()
            .over(
                partition_by=PriceHistory.competitor_id,
                order_by=PriceHistory.observed_at.desc(),
            )
            .label("rn"),
        ).subquery()

        latest_price = func.max(
            case((ranked.c.rn == 1, ranked.c.observed_price), else_=None)
        ).label("latest_price")
        previous_price = func.max(
            case((ranked.c.rn == 2, ranked.c.observed_price), else_=None)
        ).label("previous_price")

        return (
            select(
                ranked.c.competitor_id,
                latest_price,
                previous_price,
            )
            .group_by(ranked.c.competitor_id)
            .subquery()
        )
