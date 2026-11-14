from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import logging
from typing import Iterable
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.competitor import Competitor
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.scrape_run import ScrapeRun
from app.repositories.competitor_snapshot_repository import (
    CompetitorSnapshotRepository,
    ScrapeRunRepository,
)

from app.scraper.utils import normalize_stock_status as normalize_stock_status

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"COMPLETED", "FAILED", "PARTIAL"}
VALID_TRANSITIONS = {
    "PENDING": {"RUNNING", "FAILED"},
    "RUNNING": {"COMPLETED", "FAILED", "PARTIAL"},
}


class InvalidScrapeRunTransitionError(Exception):
    pass


@dataclass(frozen=True)
class ScrapeRunResult:
    scrape_run: ScrapeRun
    created: bool
    already_completed: bool = False


@dataclass(frozen=True)
class CompetitorObservation:
    price: Decimal | None
    rating: float | None
    review_count: int | None
    stock_status: str | None


class CompetitorSnapshotService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._runs = ScrapeRunRepository(db)
        self._snapshots = CompetitorSnapshotRepository(db)

    def start_scrape_run(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        marketplace: str,
        run_key: str,
        task_id: str | None = None,
    ) -> ScrapeRunResult:
        scrape_run = self._runs.get_by_run_key(
            seller_id=seller_id,
            product_id=product_id,
            marketplace=marketplace,
            run_key=run_key,
            for_update=True,
        )
        if scrape_run:
            if scrape_run.status == "COMPLETED":
                return ScrapeRunResult(scrape_run=scrape_run, created=False, already_completed=True)
            self.transition_to_running(scrape_run, task_id=task_id)
            self._db.flush()
            return ScrapeRunResult(scrape_run=scrape_run, created=False)

        scrape_run = ScrapeRun(
            seller_id=seller_id,
            product_id=product_id,
            marketplace=marketplace,
            run_key=run_key,
            status="PENDING",
            celery_task_id=task_id,
        )
        self._db.add(scrape_run)
        try:
            self._db.flush()
        except IntegrityError:
            self._db.rollback()
            scrape_run = self._runs.get_by_run_key(
                seller_id=seller_id,
                product_id=product_id,
                marketplace=marketplace,
                run_key=run_key,
                for_update=True,
            )
            if scrape_run is None:
                raise
            if scrape_run.status == "COMPLETED":
                return ScrapeRunResult(scrape_run=scrape_run, created=False, already_completed=True)
            self.transition_to_running(scrape_run, task_id=task_id)
            self._db.flush()
            return ScrapeRunResult(scrape_run=scrape_run, created=False)

        self.transition_to_running(scrape_run, task_id=task_id)
        self._db.flush()
        logger.info(
            "scrape_run_started scrape_run_id=%s seller_id=%s product_id=%s marketplace=%s run_key=%s",
            scrape_run.id,
            seller_id,
            product_id,
            marketplace,
            run_key,
        )
        return ScrapeRunResult(scrape_run=scrape_run, created=True)

    def transition_to_running(self, scrape_run: ScrapeRun, *, task_id: str | None = None) -> None:
        if scrape_run.status == "RUNNING":
            if task_id:
                scrape_run.celery_task_id = task_id
            return
        self._transition(scrape_run, "RUNNING")
        scrape_run.started_at = utc_now()
        scrape_run.failed_at = None
        scrape_run.failure_code = None
        scrape_run.error_message = None
        if task_id:
            scrape_run.celery_task_id = task_id

    def record_successful_scrape(
        self,
        *,
        scrape_run: ScrapeRun,
        competitors: Iterable[Competitor],
        captured_at: datetime,
        discovered_count: int,
        matched_count: int,
        observations: dict[UUID, CompetitorObservation] | None = None,
    ) -> list[CompetitorSnapshot]:
        snapshots = self._build_snapshots(
            scrape_run=scrape_run,
            competitors=competitors,
            captured_at=captured_at,
            observations=observations,
        )
        self._snapshots.add_all(snapshots)
        self._db.flush()
        snapshot_count = self._snapshots.count_for_run(scrape_run.id)
        scrape_run.discovered_competitor_count = discovered_count
        scrape_run.snapshot_count = snapshot_count
        scrape_run.total_results = discovered_count
        scrape_run.successful_matches = matched_count
        completed_at = utc_now()
        scrape_run.completed_at = completed_at
        scrape_run.finished_at = completed_at
        self._transition(scrape_run, "COMPLETED")
        logger.info(
            "snapshots_created scrape_run_id=%s seller_id=%s product_id=%s snapshot_count=%s",
            scrape_run.id,
            scrape_run.seller_id,
            scrape_run.product_id,
            snapshot_count,
        )
        logger.info(
            "scrape_run_completed scrape_run_id=%s seller_id=%s product_id=%s discovered=%s matched=%s",
            scrape_run.id,
            scrape_run.seller_id,
            scrape_run.product_id,
            discovered_count,
            matched_count,
        )
        return snapshots

    def record_partial_scrape(
        self,
        *,
        scrape_run: ScrapeRun,
        competitors: Iterable[Competitor],
        captured_at: datetime,
        discovered_count: int,
        matched_count: int,
        reason: str,
    ) -> list[CompetitorSnapshot]:
        snapshots = self._build_snapshots(
            scrape_run=scrape_run,
            competitors=competitors,
            captured_at=captured_at,
        )
        self._snapshots.add_all(snapshots)
        self._db.flush()
        now = utc_now()
        scrape_run.discovered_competitor_count = discovered_count
        scrape_run.snapshot_count = self._snapshots.count_for_run(scrape_run.id)
        scrape_run.total_results = discovered_count
        scrape_run.successful_matches = matched_count
        scrape_run.error_message = _sanitize_failure_message(reason)
        scrape_run.failure_code = "PARTIAL_SCRAPE"
        scrape_run.finished_at = now
        self._transition(scrape_run, "PARTIAL")
        logger.info(
            "scrape_run_partial scrape_run_id=%s seller_id=%s product_id=%s discovered=%s matched=%s snapshot_count=%s",
            scrape_run.id,
            scrape_run.seller_id,
            scrape_run.product_id,
            discovered_count,
            matched_count,
            scrape_run.snapshot_count,
        )
        return snapshots

    def record_failed_scrape(
        self,
        *,
        scrape_run_id: UUID,
        reason: str,
        failure_code: str = "SCRAPE_FAILED",
    ) -> None:
        scrape_run = self._db.get(ScrapeRun, scrape_run_id)
        if not scrape_run or scrape_run.status in TERMINAL_STATUSES:
            return
        now = utc_now()
        scrape_run.error_message = _sanitize_failure_message(reason)
        scrape_run.failure_code = failure_code[:120]
        scrape_run.failed_at = now
        scrape_run.finished_at = now
        self._transition(scrape_run, "FAILED")
        self._db.commit()
        logger.warning(
            "scrape_run_failed scrape_run_id=%s seller_id=%s product_id=%s failure_code=%s",
            scrape_run.id,
            scrape_run.seller_id,
            scrape_run.product_id,
            scrape_run.failure_code,
        )

    def get_latest_product_snapshots(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[CompetitorSnapshot], int]:
        return self._snapshots.latest_for_product(
            seller_id=seller_id,
            product_id=product_id,
            limit=limit,
            offset=offset,
        )

    def get_competitor_timeline(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        competitor_id: UUID,
        from_at: datetime | None,
        to_at: datetime | None,
        order: str,
        limit: int,
        offset: int,
    ) -> tuple[list[CompetitorSnapshot], int]:
        return self._snapshots.timeline(
            seller_id=seller_id,
            product_id=product_id,
            competitor_id=competitor_id,
            from_at=from_at,
            to_at=to_at,
            order=order,
            limit=limit,
            offset=offset,
        )

    def _build_snapshots(
        self,
        *,
        scrape_run: ScrapeRun,
        competitors: Iterable[Competitor],
        captured_at: datetime,
        observations: dict[UUID, CompetitorObservation] | None = None,
    ) -> list[CompetitorSnapshot]:
        normalized_captured_at = ensure_utc(captured_at)
        snapshots: list[CompetitorSnapshot] = []
        for competitor in competitors:
            if competitor.product_id != scrape_run.product_id:
                raise ValueError("Competitor does not belong to the scrape product.")
            observation = observations[competitor.id] if observations is not None else CompetitorObservation(
                price=competitor.competitor_price,
                rating=competitor.competitor_rating,
                review_count=competitor.rating_count,
                stock_status=competitor.stock_status,
            )
            price = _nonnegative_decimal(observation.price, "price")
            rating = _rating_decimal(observation.rating)
            review_count = _nonnegative_int(observation.review_count, "review_count")
            stock_status = normalize_stock_status(observation.stock_status)
            external_listing_id = competitor.product_url or str(competitor.id)
            content_hash = _content_hash(
                competitor_id=competitor.id,
                product_id=competitor.product_id,
                price=price,
                rating=rating,
                review_count=review_count,
                stock_status=stock_status,
                external_listing_id=external_listing_id,
            )
            snapshots.append(
                CompetitorSnapshot(
                    scrape_run_id=scrape_run.id,
                    competitor_id=competitor.id,
                    product_id=competitor.product_id,
                    price=price,
                    currency="BDT",
                    rating=rating,
                    review_count=review_count,
                    stock_status=stock_status,
                    raw_stock_text=observation.stock_status,
                    source_url=competitor.product_url,
                    external_listing_id=external_listing_id,
                    content_hash=content_hash,
                    captured_at=normalized_captured_at,
                )
            )
        return snapshots

    @staticmethod
    def _transition(scrape_run: ScrapeRun, next_status: str) -> None:
        if scrape_run.status == next_status:
            return
        if scrape_run.status in TERMINAL_STATUSES:
            raise InvalidScrapeRunTransitionError(
                f"Cannot transition terminal scrape run {scrape_run.id} from {scrape_run.status} to {next_status}."
            )
        allowed = VALID_TRANSITIONS.get(scrape_run.status, set())
        if next_status not in allowed:
            raise InvalidScrapeRunTransitionError(
                f"Invalid scrape run transition from {scrape_run.status} to {next_status}."
            )
        scrape_run.status = next_status


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime | None) -> datetime:
    if value is None:
        return utc_now()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _nonnegative_decimal(value: Decimal | int | float | str | None, field_name: str) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid {field_name}.") from exc
    if decimal_value < 0:
        raise ValueError(f"{field_name} cannot be negative.")
    return decimal_value


def _rating_decimal(value: Decimal | int | float | str | None) -> Decimal | None:
    rating = _nonnegative_decimal(value, "rating")
    if rating is not None and rating > Decimal("5"):
        raise ValueError("rating must be between 0 and 5.")
    return rating


def _nonnegative_int(value: int | str | None, field_name: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        int_value = int(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid {field_name}.") from exc
    if int_value < 0:
        raise ValueError(f"{field_name} cannot be negative.")
    return int_value


def _content_hash(
    *,
    competitor_id: UUID,
    product_id: UUID,
    price: Decimal | None,
    rating: Decimal | None,
    review_count: int | None,
    stock_status: str,
    external_listing_id: str | None,
) -> str:
    payload = "|".join(
        [
            str(competitor_id),
            str(product_id),
            str(price) if price is not None else "",
            str(rating) if rating is not None else "",
            str(review_count) if review_count is not None else "",
            stock_status,
            external_listing_id or "",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sanitize_failure_message(message: str) -> str:
    sanitized = " ".join(message.split())
    return sanitized[:1000]
