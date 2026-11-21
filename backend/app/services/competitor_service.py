from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.competitor import Competitor
from app.models.competitor_ranking import CompetitorRanking
from app.models.price_history import PriceHistory
from app.models.product import Product
from app.models.scrape_run import ScrapeRun
from app.scraper.utils import first_present, normalize_sold_count, normalize_text
from app.services.competitor_snapshot_service import CompetitorObservation, normalize_stock_status


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
        price_observed_at_by_url: dict[str, datetime] | None = None,
        stock_observed_at_by_url: dict[str, datetime] | None = None,
    ) -> tuple[list[Competitor], dict[UUID, CompetitorObservation]]:
        if (scrape_run.product_id, scrape_run.seller_id) != (product.id, product.seller_id):
            raise ValueError("Scrape run does not belong to the seller product.")
        observed_timestamp = observed_at or datetime.now(timezone.utc)

        observed: dict[Competitor, CompetitorObservation] = {}
        seen_listings: set[str | tuple[str, str | None]] = set()

        for item in competitors:
            title = (
                item.get("competitor_title")
                or item.get("product_title")
                or ""
            ).strip()

            if not title:
                continue

            product_url = item.get("product_url") or item.get("daraz_product_url")
            store = item.get("competitor_store") or item.get("store_name") or None
            listing_key = product_url or (title, store)
            if listing_key in seen_listings:
                continue
            seen_listings.add(listing_key)
            competitor = self._find_existing_competitor(
                product_id=product.id,
                marketplace=marketplace,
                product_url=product_url,
                title=title,
                store=store,
            )
            if competitor in observed:
                continue
            if competitor is None:
                competitor = Competitor(product_id=product.id)
                self._db.add(competitor)

            price = self._to_decimal(first_present(item.get("competitor_price"), item.get("product_price")))
            rating = self._to_float(first_present(item.get("competitor_rating"), item.get("rating")))
            if rating is not None and not 0 <= rating <= 5:
                rating = None
            raw_stock = normalize_text(item.get("stock_status")) or None
            observation = CompetitorObservation(
                price=price,
                rating=rating,
                review_count=self._to_int(item.get("rating_count")),
                stock_status=raw_stock,
                price_observed_at=(price_observed_at_by_url or {}).get(product_url) if product_url else None,
                stock_observed_at=(stock_observed_at_by_url or {}).get(product_url) if product_url else None,
                match_score=self._to_float(item.get("match_confidence")),
            )
            sold_count = first_present(item.get("competitor_sold"), item.get("sold_count"))
            if sold_count is not None:
                sold_count = normalize_sold_count(str(sold_count))

            competitor.scrape_run_id = scrape_run.id
            competitor.competitor_title = title
            fresh_values = {
                "competitor_description": item.get("product_description") or item.get("competitor_description"),
                "competitor_category": item.get("product_category") or item.get("competitor_category"),
                "competitor_brand": item.get("product_brand") or item.get("competitor_brand"),
                "competitor_attributes": item.get("product_attributes") or item.get("competitor_attributes"),
                "competitor_price": observation.price,
                "original_price": self._to_decimal(item.get("original_price")),
                "discount_percentage": self._to_int(item.get("discount_percentage"), maximum=100),
                "competitor_rating": observation.rating,
                "rating_count": observation.review_count,
                "competitor_sold": sold_count,
                "competitor_store": store,
                "stock_status": raw_stock if normalize_stock_status(raw_stock) != "UNKNOWN" else None,
                "product_url": product_url,
                "image_url": item.get("image_url") or item.get("product_image_url"),
            }
            if fresh_values["competitor_attributes"] and competitor.competitor_attributes:
                fresh_values["competitor_attributes"] = {
                    **competitor.competitor_attributes, **fresh_values["competitor_attributes"],
                }
            for field, value in fresh_values.items():
                if value is not None and value != "" and value != {}:
                    setattr(competitor, field, value)
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
            competitor.search_position = self._to_int(item.get("search_position"))
            observed[competitor] = observation

        if not observed:
            return [], {}

        self._db.flush()  # ensures IDs are generated
        self._db.add_all([
            PriceHistory(
                competitor_id=competitor.id,
                observed_price=observation.price,
                observed_at=observation.price_observed_at or observed_timestamp,
            )
            for competitor, observation in observed.items()
            if observation.price is not None
        ])
        return list(observed), {competitor.id: observation for competitor, observation in observed.items()}

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
            price = Decimal(str(value))
            if price.is_finite() and 0 <= price <= Decimal("9999999999.99"):
                return price
            return None
        except (InvalidOperation, ValueError, TypeError):
            return None

    @staticmethod
    def _to_int(value: Any, *, maximum: int = 2_147_483_647) -> int | None:
        if value is None or value == "":
            return None
        try:
            number = int(value)
            return number if 0 <= number <= maximum else None
        except (ValueError, TypeError, OverflowError):
            return None

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            number = float(value)
            return number if isfinite(number) else None
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
