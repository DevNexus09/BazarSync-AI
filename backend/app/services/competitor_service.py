from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.competitor import Competitor
from app.models.competitor_ranking import CompetitorRanking
from app.models.price_history import PriceHistory
from app.models.product import Product
from app.models.scrape_run import ScrapeRun


class ProductNotFoundError(Exception):
    pass


class CompetitorService:
    def __init__(self, db: Session) -> None:
        self._db = db

    # -----------------------------
    # Store competitors
    # -----------------------------
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
            title = (
                item.get("competitor_title")
                or item.get("product_title")
                or ""
            ).strip()

            if not title:
                continue

            product_url = item.get("product_url") or item.get("daraz_product_url")
            competitor = self._find_existing_competitor(
                product_id=product.id,
                marketplace=marketplace,
                product_url=product_url,
                title=title,
                store=item.get("competitor_store") or item.get("store_name"),
            )
            if competitor is None:
                competitor = Competitor(product_id=product.id)
                self._db.add(competitor)

            competitor.scrape_run_id = scrape_run.id
            competitor.competitor_title = title
            competitor.competitor_description = item.get("product_description") or item.get("competitor_description")
            competitor.competitor_category = item.get("product_category") or item.get("competitor_category")
            competitor.competitor_brand = item.get("product_brand") or item.get("competitor_brand")
            competitor.competitor_attributes = item.get("product_attributes") or item.get("competitor_attributes")
            competitor.competitor_price = self._to_decimal(item.get("competitor_price") or item.get("product_price"))
            competitor.original_price = self._to_decimal(item.get("original_price"))
            competitor.discount_percentage = self._to_int(item.get("discount_percentage"))
            competitor.competitor_rating = self._to_float(item.get("competitor_rating") or item.get("rating"))
            competitor.rating_count = self._to_int(item.get("rating_count"))
            competitor.competitor_sold = item.get("competitor_sold") or item.get("sold_count")
            competitor.competitor_store = item.get("competitor_store") or item.get("store_name")
            competitor.stock_status = item.get("stock_status")
            competitor.similarity_score = self._to_float(item.get("similarity_score"))
            competitor.title_similarity = self._to_float(item.get("title_similarity"))
            competitor.description_similarity = self._to_float(item.get("description_similarity"))
            competitor.attribute_similarity = self._to_float(item.get("attribute_similarity"))
            competitor.keyword_score = self._to_float(item.get("keyword_score"))
            competitor.ranking_score = self._to_float(item.get("ranking_score"))
            competitor.match_confidence = self._to_float(item.get("match_confidence"))
            competitor.category_match = item.get("category_match")
            competitor.matched_attributes = item.get("matched_attributes")
            competitor.marketplace = marketplace
            competitor.product_url = product_url
            competitor.image_url = item.get("image_url") or item.get("product_image_url")
            competitor.search_position = self._to_int(item.get("search_position"))
            competitor_rows.append(competitor)

        if not competitor_rows:
            return []

        self._db.add_all(competitor_rows)
        self._db.flush()  # ensures IDs are generated

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

    # -----------------------------
    # Fetch latest competitors
    # -----------------------------
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
            raise ProductNotFoundError("Product not found")

        run_statement = (
            select(ScrapeRun)
            .where(
                ScrapeRun.product_id == product_id,
                ScrapeRun.seller_id == seller_id,
                ScrapeRun.status.in_(("COMPLETED", "completed")),
            )
            .order_by(
                ScrapeRun.finished_at.desc().nullslast(),
                ScrapeRun.created_at.desc(),
            )
            .limit(1)
        )

        scrape_run = self._db.execute(run_statement).scalar_one_or_none()

        if not scrape_run:
            return [], 0, None

        statement = (
            select(Competitor)
            .outerjoin(
                CompetitorRanking,
                (CompetitorRanking.scrape_run_id == Competitor.scrape_run_id)
                & (CompetitorRanking.competitor_id == Competitor.id)
                & (CompetitorRanking.product_id == Competitor.product_id),
            )
            .where(
                Competitor.product_id == product_id,
                Competitor.scrape_run_id == scrape_run.id,
            )
            .order_by(
                CompetitorRanking.market_rank.asc().nullslast(),
                CompetitorRanking.total_score.desc().nullslast(),
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

    # -----------------------------
    # Type converters
    # -----------------------------
    @staticmethod
    def _to_decimal(value: Any) -> Decimal | None:
        if value is None or value == "":
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None

    @staticmethod
    def _to_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    # -----------------------------
    # Internal helper
    # -----------------------------
    def _get_product(self, seller_id: UUID, product_id: UUID) -> Product | None:
        statement = select(Product).where(
            Product.id == product_id,
            Product.seller_id == seller_id,
        )
        return self._db.execute(statement).scalar_one_or_none()

    def _find_existing_competitor(
        self,
        *,
        product_id: UUID,
        marketplace: str,
        product_url: str | None,
        title: str,
        store: str | None,
    ) -> Competitor | None:
        if product_url:
            statement = select(Competitor).where(
                Competitor.product_id == product_id,
                Competitor.marketplace == marketplace,
                Competitor.product_url == product_url,
            )
            existing = self._db.execute(statement.limit(1)).scalar_one_or_none()
            if existing:
                return existing

        statement = select(Competitor).where(
            Competitor.product_id == product_id,
            Competitor.marketplace == marketplace,
            Competitor.competitor_title == title,
            Competitor.competitor_store == store,
        )
        return self._db.execute(statement.limit(1)).scalar_one_or_none()
