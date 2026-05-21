from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.competitor import Competitor
from app.models.price_history import PriceHistory
from app.models.product import Product
from app.models.scrape_run import ScrapeRun


class CompetitorService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def store_competitors(
        self,
        *,
        scrape_run: ScrapeRun,
        product: Product,
        marketplace: str,
        competitors: list[dict[str, Any]],
        observed_at: datetime | None = None,
    ) -> list[Competitor]:
        observed_timestamp = observed_at or datetime.now(timezone.utc)
        competitor_rows: list[Competitor] = []
        price_rows: list[PriceHistory] = []

        for item in competitors:
            title = item.get("competitor_title") or item.get("product_title") or ""
            if not title:
                continue

            competitor = Competitor(
                scrape_run_id=scrape_run.id,
                product_id=product.id,
                competitor_title=title,
                competitor_description=item.get("product_description")
                or item.get("competitor_description"),
                competitor_category=item.get("product_category")
                or item.get("competitor_category"),
                competitor_brand=item.get("product_brand")
                or item.get("competitor_brand"),
                competitor_attributes=item.get("product_attributes")
                or item.get("competitor_attributes"),
                competitor_price=self._to_decimal(item.get("competitor_price") or item.get("product_price")),
                original_price=self._to_decimal(item.get("original_price")),
                discount_percentage=self._to_int(item.get("discount_percentage")),
                competitor_rating=self._to_float(item.get("competitor_rating") or item.get("rating")),
                rating_count=self._to_int(item.get("rating_count")),
                competitor_sold=item.get("competitor_sold") or item.get("sold_count"),
                competitor_store=item.get("competitor_store") or item.get("store_name"),
                stock_status=item.get("stock_status"),
                similarity_score=self._to_float(item.get("similarity_score")),
                title_similarity=self._to_float(item.get("title_similarity")),
                description_similarity=self._to_float(item.get("description_similarity")),
                attribute_similarity=self._to_float(item.get("attribute_similarity")),
                keyword_score=self._to_float(item.get("keyword_score")),
                ranking_score=self._to_float(item.get("ranking_score")),
                match_confidence=self._to_float(item.get("match_confidence")),
                category_match=item.get("category_match"),
                matched_attributes=item.get("matched_attributes"),
                marketplace=marketplace,
                product_url=item.get("product_url") or item.get("daraz_product_url"),
                image_url=item.get("image_url") or item.get("product_image_url"),
                search_position=self._to_int(item.get("search_position")),
            )
            competitor_rows.append(competitor)

        if not competitor_rows:
            return []

        self._db.add_all(competitor_rows)
        self._db.flush()

        for competitor in competitor_rows:
            if competitor.competitor_price is None:
                continue
            price_rows.append(
                PriceHistory(
                    competitor_id=competitor.id,
                    observed_price=competitor.competitor_price,
                    observed_at=observed_timestamp,
                )
            )

        if price_rows:
            self._db.add_all(price_rows)

        return competitor_rows

    def list_latest_competitors(
        self,
        seller_id: UUID,
        product_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[Competitor], int, ScrapeRun | None]:
        product = self._get_product(seller_id, product_id)
        if not product:
            raise ProductNotFoundError

        run_statement = (
            select(ScrapeRun)
            .where(
                ScrapeRun.product_id == product_id,
                ScrapeRun.seller_id == seller_id,
                ScrapeRun.status == "completed",
            )
            .order_by(ScrapeRun.finished_at.desc().nullslast(), ScrapeRun.created_at.desc())
            .limit(1)
        )
        scrape_run = self._db.execute(run_statement).scalar_one_or_none()
        if not scrape_run:
            return [], 0, None

        statement = (
            select(Competitor)
            .where(
                Competitor.product_id == product_id,
                Competitor.scrape_run_id == scrape_run.id,
            )
            .order_by(
                Competitor.similarity_score.desc().nullslast(),
                Competitor.created_at.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        items = self._db.execute(statement).scalars().all()

        total_statement = (
            select(func.count())
            .select_from(Competitor)
            .where(
                Competitor.product_id == product_id,
                Competitor.scrape_run_id == scrape_run.id,
            )
        )
        total = self._db.execute(total_statement).scalar_one()
        return items, total, scrape_run

    @staticmethod
    def _to_decimal(value: Any) -> Decimal | None:
        if value is None or value == "":
            return None
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _to_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _get_product(self, seller_id: UUID, product_id: UUID) -> Product | None:
        statement = select(Product).where(
            Product.id == product_id,
            Product.seller_id == seller_id,
        )
        return self._db.execute(statement).scalar_one_or_none()


class ProductNotFoundError(Exception):
    pass
