from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any, TypedDict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.competitor import Competitor
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.price_history import PriceHistory
from app.models.product import Product
from app.models.scrape_run import ScrapeRun
from app.scraper.constants import MARKETPLACE_NAME
from app.scraper.utils import normalize_stock_status


class Freshness(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    HISTORICAL = "HISTORICAL"
    CARRIED_FORWARD = "CARRIED_FORWARD"
    MISSING = "MISSING"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


class MarketCompetitor(TypedDict):
    price: Decimal
    competitor_price: Decimal
    stock_status: str | None


@dataclass(frozen=True)
class FieldEvidence:
    status: Freshness
    observed_at: datetime | None = None
    reason: str | None = None

    def to_context(self) -> dict[str, str | None]:
        return {
            "status": self.status.value,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CompetitorEvidence:
    snapshot_id: UUID
    competitor_id: UUID
    price: Decimal | None
    stock_status: str
    price_evidence: FieldEvidence
    stock_evidence: FieldEvidence
    match_score: float | None = None


@dataclass(frozen=True)
class RecommendationEvidence:
    seller_id: UUID
    product_id: UUID
    scrape_run_id: UUID | None
    evaluated_at: datetime
    price_max_age: timedelta
    stock_max_age: timedelta
    observations: tuple[CompetitorEvidence, ...] = ()
    quality_flags: tuple[str, ...] = ()

    @property
    def market_competitors(self) -> list[MarketCompetitor]:
        # Both engines expect a price per entry. A stock classification only
        # accompanies the eligible price from that same listing and run.
        return [
            {
                "price": row.price,
                "competitor_price": row.price,
                "stock_status": row.stock_status
                if row.stock_evidence.status == Freshness.FRESH
                else None,
            }
            for row in self.observations
            if row.price is not None and row.price_evidence.status == Freshness.FRESH
        ]

    def to_context(self) -> dict[str, Any]:
        fields = [
            (row, name, evidence)
            for row in self.observations
            for name, evidence in (
                ("price", row.price_evidence),
                ("stock_status", row.stock_evidence),
            )
        ]
        observed_times = [
            evidence.observed_at
            for _, _, evidence in fields
            if evidence.status in {Freshness.FRESH, Freshness.STALE}
            and evidence.observed_at is not None
        ]
        latest = max(observed_times, default=None)
        rejected = [
            {
                "snapshot_id": str(row.snapshot_id),
                "field": name,
                **evidence.to_context(),
            }
            for row, name, evidence in fields
            if evidence.status != Freshness.FRESH
        ]
        market = self.market_competitors
        missing_fields = {
            name for _, name, evidence in fields if evidence.status != Freshness.FRESH
        }
        if not fields:
            missing_fields.update(("price", "stock_status"))
        statuses = {evidence.status for _, _, evidence in fields}
        if Freshness.FRESH in statuses:
            freshness = "PARTIAL" if rejected else "FRESH"
        elif Freshness.UNKNOWN in statuses:
            freshness = "UNKNOWN"
        elif Freshness.STALE in statuses:
            freshness = "STALE"
        else:
            freshness = "UNAVAILABLE"
        return {
            "version": 1,
            "seller_id": str(self.seller_id),
            "product_id": str(self.product_id),
            "scrape_run_id": str(self.scrape_run_id) if self.scrape_run_id else None,
            "evaluated_at": self.evaluated_at.isoformat(),
            "latest_observation_at": latest.isoformat() if latest else None,
            "freshness_status": freshness,
            "price_max_age_seconds": int(self.price_max_age.total_seconds()),
            "stock_max_age_seconds": int(self.stock_max_age.total_seconds()),
            "competitor_coverage": {
                "snapshots": len(self.observations),
                "fresh_prices": len(market),
                "fresh_stock": sum(
                    row.stock_evidence.status == Freshness.FRESH
                    for row in self.observations
                ),
                "fresh_stock_with_price": sum(
                    row["stock_status"] is not None for row in market
                ),
            },
            "missing_fields": sorted(missing_fields),
            "rejected_observations": rejected,
            "quality_flags": sorted(
                set(self.quality_flags)
                | {status.value for status in statuses - {Freshness.FRESH}}
            ),
            "observations": [
                {
                    "snapshot_id": str(row.snapshot_id),
                    "competitor_id": str(row.competitor_id),
                    "match_score": row.match_score if row.match_score is not None and 0 <= row.match_score <= 1 else None,
                    "observed_price": str(row.price)
                    if row.price_evidence.status == Freshness.FRESH
                    else None,
                    "observed_stock_status": row.stock_status
                    if row.stock_evidence.status == Freshness.FRESH
                    else None,
                    "price": row.price_evidence.to_context(),
                    "stock_status": row.stock_evidence.to_context(),
                }
                for row in self.observations
            ],
        }


class RecommendationEvidenceService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def completed_run(
        self, *, seller_id: UUID, product_id: UUID, scrape_run_id: UUID | None = None,
    ) -> ScrapeRun | None:
        run_query = (
            select(ScrapeRun)
            .join(Product, Product.id == ScrapeRun.product_id)
            .where(
                Product.id == product_id,
                Product.seller_id == seller_id,
                ScrapeRun.seller_id == seller_id,
                ScrapeRun.marketplace == MARKETPLACE_NAME,
                ScrapeRun.status.in_(("COMPLETED", "completed")),
            )
        )
        if scrape_run_id is not None:
            run_query = run_query.where(ScrapeRun.id == scrape_run_id)
        return self._db.scalars(
            run_query.order_by(
                ScrapeRun.finished_at.desc().nullslast(),
                ScrapeRun.created_at.desc(),
                ScrapeRun.id.desc(),
            ).limit(1)
        ).first()

    def collect(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        scrape_run_id: UUID | None = None,
        now: datetime | None = None,
    ) -> RecommendationEvidence:
        timestamp = _aware_utc(now)
        if now is not None and timestamp is None:
            raise ValueError("Evidence evaluation time must be timezone-aware.")
        price_max_age = timedelta(hours=settings.recommendation_price_max_age_hours)
        stock_max_age = timedelta(hours=settings.recommendation_stock_max_age_hours)
        run = self.completed_run(seller_id=seller_id, product_id=product_id, scrape_run_id=scrape_run_id)
        evaluated_at = timestamp or datetime.now(timezone.utc)
        if run is None:
            return RecommendationEvidence(
                seller_id,
                product_id,
                None,
                evaluated_at,
                price_max_age,
                stock_max_age,
                quality_flags=("NO_COMPLETED_SCRAPE",),
            )
        if run.successful_matches == 0:
            return RecommendationEvidence(
                seller_id,
                product_id,
                run.id,
                evaluated_at,
                price_max_age,
                stock_max_age,
                quality_flags=("NO_MATCHES",),
            )

        rows = self._db.execute(
            select(
                CompetitorSnapshot,
                Competitor.scrape_run_id,
                Competitor.competitor_price,
                Competitor.stock_status,
            )
            .join(Competitor, Competitor.id == CompetitorSnapshot.competitor_id)
            .where(
                CompetitorSnapshot.scrape_run_id == run.id,
                CompetitorSnapshot.product_id == product_id,
                Competitor.product_id == product_id,
                Competitor.marketplace == run.marketplace,
            )
            .order_by(CompetitorSnapshot.id)
        ).all()
        started = _aware_utc(run.started_at)
        finished = _aware_utc(run.finished_at or run.completed_at)
        historical_prices = self._competitors_with_price_history(
            [snapshot.competitor_id for snapshot, *_ in rows if snapshot.price is None],
            started,
        )
        observations = tuple(
            CompetitorEvidence(
                snapshot_id=snapshot.id,
                competitor_id=snapshot.competitor_id,
                price=snapshot.price,
                stock_status=snapshot.stock_status,
                match_score=snapshot.match_score,
                price_evidence=_price_evidence(
                    snapshot,
                    retained=latest_run_id == run.id and _positive_price(latest_price),
                    has_history=snapshot.competitor_id in historical_prices,
                    started=started,
                    finished=finished,
                    now=evaluated_at,
                    max_age=price_max_age,
                ),
                stock_evidence=_stock_evidence(
                    snapshot,
                    retained=latest_run_id == run.id
                    and latest_stock not in (None, "", "UNKNOWN")
                    and normalize_stock_status(latest_stock) != "UNKNOWN",
                    started=started,
                    finished=finished,
                    now=evaluated_at,
                    max_age=stock_max_age,
                ),
            )
            for snapshot, latest_run_id, latest_price, latest_stock in rows
        )
        flags = []
        if not observations:
            flags.append("NO_SNAPSHOTS")
        if run.successful_matches is not None and run.successful_matches != len(
            observations
        ):
            flags.append("SNAPSHOT_COVERAGE_MISMATCH")
        return RecommendationEvidence(
            seller_id,
            product_id,
            run.id,
            evaluated_at,
            price_max_age,
            stock_max_age,
            observations,
            tuple(flags),
        )

    def _competitors_with_price_history(
        self, competitor_ids: list[UUID], before: datetime | None
    ) -> set[UUID]:
        if not competitor_ids or before is None:
            return set()
        # History has no run FK and some older writers used scrape capture as
        # its timestamp. Use it only to identify earlier records for this listing.
        return set(
            self._db.scalars(
                select(PriceHistory.competitor_id)
                .where(
                    PriceHistory.competitor_id.in_(competitor_ids),
                    PriceHistory.observed_at < before,
                    PriceHistory.observed_price > 0,
                    PriceHistory.observed_price != Decimal("NaN"),
                )
                .distinct()
            )
        )


def _positive_price(value: Decimal | None) -> bool:
    return value is not None and value.is_finite() and value > 0


def _price_evidence(
    snapshot: CompetitorSnapshot,
    *,
    retained: bool,
    has_history: bool,
    started: datetime | None,
    finished: datetime | None,
    now: datetime,
    max_age: timedelta,
) -> FieldEvidence:
    if snapshot.price is None:
        if retained:
            return FieldEvidence(
                Freshness.CARRIED_FORWARD, reason="MUTABLE_PRICE_RETAINED"
            )
        if has_history:
            return FieldEvidence(Freshness.HISTORICAL, reason="EARLIER_PRICE_HISTORY")
        return FieldEvidence(Freshness.MISSING, reason="NO_OBSERVED_PRICE")
    if not _positive_price(snapshot.price) or snapshot.currency != "BDT":
        return FieldEvidence(Freshness.INVALID, reason="INVALID_PRICE_OR_CURRENCY")
    return _classify_time(
        snapshot.price_observed_at,
        snapshot.captured_at,
        started,
        finished,
        now,
        max_age,
    )


def _stock_evidence(
    snapshot: CompetitorSnapshot,
    *,
    retained: bool,
    started: datetime | None,
    finished: datetime | None,
    now: datetime,
    max_age: timedelta,
) -> FieldEvidence:
    if snapshot.stock_status in (None, "", "UNKNOWN"):
        if snapshot.raw_stock_text and snapshot.raw_stock_text.strip().upper() not in (
            "",
            "UNKNOWN",
        ):
            return FieldEvidence(Freshness.INVALID, reason="UNRECOGNIZED_STOCK_LABEL")
        if retained:
            return FieldEvidence(
                Freshness.CARRIED_FORWARD, reason="MUTABLE_STOCK_RETAINED"
            )
        return FieldEvidence(Freshness.MISSING, reason="NO_OBSERVED_STOCK")
    if snapshot.stock_status not in ("IN_STOCK", "OUT_OF_STOCK"):
        return FieldEvidence(Freshness.INVALID, reason="UNRECOGNIZED_STOCK_LABEL")
    return _classify_time(
        snapshot.stock_observed_at,
        snapshot.captured_at,
        started,
        finished,
        now,
        max_age,
    )


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is not None and value.utcoffset() is not None:
        return value.astimezone(timezone.utc)
    return None


def _classify_time(
    value: datetime | None,
    capture: datetime,
    started: datetime | None,
    finished: datetime | None,
    now: datetime,
    max_age: timedelta,
) -> FieldEvidence:
    observed_at = _aware_utc(value)
    captured_at = _aware_utc(capture)
    if (
        observed_at is None
        or started is None
        or finished is None
        or captured_at is None
    ):
        return FieldEvidence(
            Freshness.UNKNOWN, reason="MISSING_OR_UNVERIFIABLE_TIMESTAMP"
        )
    if not started <= captured_at <= finished <= now or observed_at > captured_at:
        return FieldEvidence(
            Freshness.INVALID, observed_at, "OUTSIDE_VALID_CAPTURE_WINDOW"
        )
    if observed_at < started:
        return FieldEvidence(
            Freshness.CARRIED_FORWARD, observed_at, "OBSERVATION_PREDATES_RUN"
        )
    if now - observed_at > max_age:
        return FieldEvidence(Freshness.STALE, observed_at, "EXCEEDED_FRESHNESS_LIMIT")
    return FieldEvidence(Freshness.FRESH, observed_at)
