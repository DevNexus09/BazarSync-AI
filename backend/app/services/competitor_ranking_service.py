from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import logging
import math
from statistics import median
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.competitor_ranking import CompetitorRanking
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.scrape_run import ScrapeRun
from app.repositories.competitor_ranking_repository import CompetitorRankingRepository

logger = logging.getLogger(__name__)

SCORE_QUANT = Decimal("0.0001")
MONEY_QUANT = Decimal("0.01")


@dataclass(frozen=True)
class RankingWeights:
    price: Decimal
    rating: Decimal
    review: Decimal
    availability: Decimal

    @classmethod
    def from_settings(cls) -> "RankingWeights":
        return cls(
            price=Decimal(str(settings.competitor_ranking_price_weight)),
            rating=Decimal(str(settings.competitor_ranking_rating_weight)),
            review=Decimal(str(settings.competitor_ranking_review_weight)),
            availability=Decimal(str(settings.competitor_ranking_availability_weight)),
        )

    def validate(self) -> None:
        values = [self.price, self.rating, self.review, self.availability]
        if any(value < 0 for value in values):
            raise ValueError("Ranking weights cannot be negative.")
        if sum(values, Decimal("0")) != Decimal("100"):
            raise ValueError("Ranking weights must total 100.")


@dataclass(frozen=True)
class RankingConfig:
    weights: RankingWeights
    formula_version: str

    @classmethod
    def from_settings(cls) -> "RankingConfig":
        return cls(
            weights=RankingWeights.from_settings(),
            formula_version=settings.competitor_ranking_formula_version,
        )

    def validate(self) -> None:
        self.weights.validate()
        if not self.formula_version.strip():
            raise ValueError("Ranking formula version is required.")


@dataclass(frozen=True)
class RankingCalculationResult:
    scrape_run_id: UUID
    formula_version: str
    created_count: int
    skipped_existing_count: int
    excluded_count: int
    skipped_reason: str | None = None


@dataclass(frozen=True)
class RankingDiagnostics:
    formula_version: str
    weights: RankingWeights
    excluded_records: list[dict]


class CompetitorRankingService:
    def __init__(
        self,
        db: Session,
        *,
        config: RankingConfig | None = None,
        log: logging.Logger | None = None,
    ) -> None:
        self._db = db
        self._config = config or RankingConfig.from_settings()
        self._config.validate()
        self._repo = CompetitorRankingRepository(db)
        self._log = log or logger

    def calculate_for_scrape_run(self, scrape_run_id: UUID) -> RankingCalculationResult:
        scrape_run = self._repo.get_completed_run(scrape_run_id)
        if scrape_run is None:
            return RankingCalculationResult(
                scrape_run_id=scrape_run_id,
                formula_version=self._config.formula_version,
                created_count=0,
                skipped_existing_count=0,
                excluded_count=0,
                skipped_reason="not_completed",
            )

        snapshots = self._repo.snapshots_for_run(scrape_run.id)
        rankings, diagnostics = self._calculate_rankings(scrape_run, snapshots)
        existing_ids = self._repo.existing_competitor_ids(
            scrape_run_id=scrape_run.id,
            formula_version=self._config.formula_version,
        )
        new_rankings = [ranking for ranking in rankings if ranking.competitor_id not in existing_ids]
        self._repo.add_all(new_rankings)
        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            existing_ids = self._repo.existing_competitor_ids(
                scrape_run_id=scrape_run.id,
                formula_version=self._config.formula_version,
            )
            new_rankings = [ranking for ranking in rankings if ranking.competitor_id not in existing_ids]
            self._repo.add_all(new_rankings)
            self._db.commit()

        skipped_existing = len(rankings) - len(new_rankings)
        self._log.info(
            "Competitor rankings calculated scrape_run_id=%s product_id=%s formula=%s created=%s existing=%s excluded=%s",
            scrape_run.id,
            scrape_run.product_id,
            self._config.formula_version,
            len(new_rankings),
            skipped_existing,
            len(diagnostics.excluded_records),
        )
        return RankingCalculationResult(
            scrape_run_id=scrape_run.id,
            formula_version=self._config.formula_version,
            created_count=len(new_rankings),
            skipped_existing_count=skipped_existing,
            excluded_count=len(diagnostics.excluded_records),
        )

    def latest_for_product(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[CompetitorRanking], int]:
        run_id = self._repo.latest_run_id_for_product(
            seller_id=seller_id,
            product_id=product_id,
            formula_version=self._config.formula_version,
        )
        if run_id is None:
            return [], 0
        return self._repo.list_for_run(
            seller_id=seller_id,
            product_id=product_id,
            scrape_run_id=run_id,
            formula_version=self._config.formula_version,
            limit=limit,
            offset=offset,
        )

    def history_for_product(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        limit: int,
        offset: int,
        formula_version: str | None = None,
    ) -> tuple[list[CompetitorRanking], int]:
        return self._repo.history_for_product(
            seller_id=seller_id,
            product_id=product_id,
            formula_version=formula_version,
            limit=limit,
            offset=offset,
        )

    def history_for_competitor(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        competitor_id: UUID,
        limit: int,
        offset: int,
        formula_version: str | None = None,
    ) -> tuple[list[CompetitorRanking], int]:
        return self._repo.history_for_competitor(
            seller_id=seller_id,
            product_id=product_id,
            competitor_id=competitor_id,
            formula_version=formula_version,
            limit=limit,
            offset=offset,
        )

    def metadata_for_product(self, *, seller_id: UUID, product_id: UUID) -> dict:
        latest, total = self.latest_for_product(seller_id=seller_id, product_id=product_id, limit=1, offset=0)
        return {
            "formula_version": self._config.formula_version,
            "weights": {
                "price": self._config.weights.price,
                "rating": self._config.weights.rating,
                "review": self._config.weights.review,
                "availability": self._config.weights.availability,
            },
            "latest_scrape_run_id": latest[0].scrape_run_id if latest else None,
            "ranking_count": total,
            "last_calculated_at": latest[0].calculated_at if latest else None,
        }

    def excluded_for_latest_product(self, *, seller_id: UUID, product_id: UUID) -> list[dict]:
        run_id = self._repo.latest_run_id_for_product(
            seller_id=seller_id,
            product_id=product_id,
            formula_version=self._config.formula_version,
        )
        if run_id is None:
            return []
        scrape_run = self._repo.get_completed_run(run_id)
        if scrape_run is None or scrape_run.seller_id != seller_id or scrape_run.product_id != product_id:
            return []
        _rankings, diagnostics = self._calculate_rankings(scrape_run, self._repo.snapshots_for_run(run_id))
        return diagnostics.excluded_records

    def market_position_card(self, *, seller_id: UUID, product_id: UUID) -> dict:
        product = self._repo.product_for_seller(seller_id=seller_id, product_id=product_id)
        rankings, total = self.latest_for_product(seller_id=seller_id, product_id=product_id, limit=10_000, offset=0)
        if product is None or not rankings:
            return {
                "seller_product_price": product.selling_price if product else None,
                "lowest_competitor_price": None,
                "highest_competitor_price": None,
                "median_competitor_price": None,
                "strongest_competitor_id": None,
                "seller_price_difference_from_market_median": None,
                "total_active_competitors": 0,
                "total_in_stock_competitors": 0,
                "ranking_last_updated_at": None,
                "seller_price_rank": None,
            }

        scrape_run_id = rankings[0].scrape_run_id
        snapshots = self._repo.snapshots_for_run(scrape_run_id)
        valid_prices = sorted([snapshot.price for snapshot in snapshots if snapshot.price is not None])
        median_price = _decimal_median(valid_prices)
        seller_price = product.selling_price
        seller_rank = None
        if seller_price is not None and valid_prices:
            seller_rank = 1 + sum(1 for price in valid_prices if price < seller_price)
        return {
            "seller_product_price": seller_price,
            "lowest_competitor_price": valid_prices[0] if valid_prices else None,
            "highest_competitor_price": valid_prices[-1] if valid_prices else None,
            "median_competitor_price": median_price,
            "strongest_competitor_id": rankings[0].competitor_id,
            "seller_price_difference_from_market_median": (
                (seller_price - median_price).quantize(MONEY_QUANT) if median_price is not None else None
            ),
            "total_active_competitors": total,
            "total_in_stock_competitors": sum(1 for snapshot in snapshots if snapshot.stock_status == "IN_STOCK"),
            "ranking_last_updated_at": rankings[0].calculated_at,
            "seller_price_rank": seller_rank,
        }

    def _calculate_rankings(
        self,
        scrape_run: ScrapeRun,
        snapshots: list[CompetitorSnapshot],
    ) -> tuple[list[CompetitorRanking], RankingDiagnostics]:
        latest_by_competitor: dict[UUID, CompetitorSnapshot] = {}
        for snapshot in snapshots:
            existing = latest_by_competitor.get(snapshot.competitor_id)
            if existing is None or (snapshot.captured_at, str(snapshot.id)) > (existing.captured_at, str(existing.id)):
                latest_by_competitor[snapshot.competitor_id] = snapshot

        included: list[CompetitorSnapshot] = []
        excluded: list[dict] = []
        for snapshot in latest_by_competitor.values():
            if snapshot.price is None or snapshot.price < 0:
                excluded.append(
                    {
                        "competitor_id": snapshot.competitor_id,
                        "snapshot_id": snapshot.id,
                        "reason": "missing_or_invalid_price",
                    }
                )
                continue
            included.append(snapshot)

        if not included:
            return [], RankingDiagnostics(self._config.formula_version, self._config.weights, excluded)

        prices = [snapshot.price for snapshot in included if snapshot.price is not None]
        min_price = min(prices)
        max_price = max(prices)
        max_reviews = max((snapshot.review_count or 0) for snapshot in included)
        calculated_at = _ensure_utc(scrape_run.completed_at or scrape_run.finished_at or scrape_run.created_at)

        scored = []
        for snapshot in included:
            price_score = _price_score(snapshot.price, min_price, max_price)
            rating_score = _rating_score(snapshot.rating)
            review_score = _review_score(snapshot.review_count or 0, max_reviews)
            availability_score = _availability_score(snapshot.stock_status)
            total_score = (
                price_score * self._config.weights.price / Decimal("100")
                + rating_score * self._config.weights.rating / Decimal("100")
                + review_score * self._config.weights.review / Decimal("100")
                + availability_score * self._config.weights.availability / Decimal("100")
            ).quantize(SCORE_QUANT, rounding=ROUND_HALF_UP)
            scored.append((snapshot, price_score, rating_score, review_score, availability_score, total_score))

        scored.sort(
            key=lambda item: (
                -item[5],
                -(item[0].rating or Decimal("0")),
                -(item[0].review_count or 0),
                str(item[0].competitor_id),
            )
        )

        rankings = [
            CompetitorRanking(
                seller_id=scrape_run.seller_id,
                product_id=scrape_run.product_id,
                competitor_id=snapshot.competitor_id,
                scrape_run_id=scrape_run.id,
                price_score=price_score,
                rating_score=rating_score,
                review_score=review_score,
                availability_score=availability_score,
                total_score=total_score,
                market_rank=index,
                formula_version=self._config.formula_version,
                calculated_at=calculated_at,
            )
            for index, (snapshot, price_score, rating_score, review_score, availability_score, total_score)
            in enumerate(scored, start=1)
        ]
        return rankings, RankingDiagnostics(self._config.formula_version, self._config.weights, excluded)


def _price_score(price: Decimal, min_price: Decimal, max_price: Decimal) -> Decimal:
    if max_price == min_price:
        return Decimal("100.0000")
    score = Decimal("100") * (max_price - price) / (max_price - min_price)
    return _clamp_score(score)


def _rating_score(rating: Decimal | None) -> Decimal:
    if rating is None:
        return Decimal("0.0000")
    return _clamp_score((rating / Decimal("5")) * Decimal("100"))


def _review_score(review_count: int, max_review_count: int) -> Decimal:
    if max_review_count <= 0:
        return Decimal("0.0000")
    score = Decimal(str(100 * math.log1p(max(review_count, 0)) / math.log1p(max_review_count)))
    return _clamp_score(score)


def _availability_score(stock_status: str) -> Decimal:
    if stock_status == "IN_STOCK":
        return Decimal("100.0000")
    if stock_status == "UNKNOWN":
        return Decimal("50.0000")
    return Decimal("0.0000")


def _clamp_score(value: Decimal) -> Decimal:
    return min(Decimal("100"), max(Decimal("0"), value)).quantize(SCORE_QUANT, rounding=ROUND_HALF_UP)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _decimal_median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return Decimal(str(median(values))).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
