from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import logging
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.competitor_event import CompetitorEvent, CompetitorEventSeverity, CompetitorEventType
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.rag_memory import RagMemorySourceType
from app.models.scrape_run import ScrapeRun
from app.repositories.competitor_event_repository import (
    CompetitorEventRepository,
    CompetitorEventSnapshotRepository,
)
from app.services.rag_index_outbox_service import RagIndexOutboxService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompetitorEventConfig:
    min_price_change_absolute: Decimal
    min_price_change_percent: Decimal
    removal_consecutive_run_threshold: int

    @classmethod
    def from_settings(cls) -> "CompetitorEventConfig":
        return cls(
            min_price_change_absolute=Decimal(str(settings.competitor_event_min_price_change_absolute)),
            min_price_change_percent=Decimal(str(settings.competitor_event_min_price_change_percent)),
            removal_consecutive_run_threshold=max(1, settings.competitor_removal_consecutive_run_threshold),
        )


@dataclass(frozen=True)
class EventGenerationResult:
    scrape_run_id: UUID
    generated_count: int
    skipped_duplicate_count: int
    skipped_reason: str | None = None


class CompetitorEventService:
    def __init__(
        self,
        db: Session,
        *,
        config: CompetitorEventConfig | None = None,
        log: logging.Logger | None = None,
    ) -> None:
        self._db = db
        self._config = config or CompetitorEventConfig.from_settings()
        self._events = CompetitorEventRepository(db)
        self._snapshots = CompetitorEventSnapshotRepository(db)
        self._log = log or logger

    def generate_for_scrape_run(self, scrape_run_id: UUID) -> EventGenerationResult:
        scrape_run = self._snapshots.get_completed_run(scrape_run_id)
        if scrape_run is None:
            return EventGenerationResult(
                scrape_run_id=scrape_run_id,
                generated_count=0,
                skipped_duplicate_count=0,
                skipped_reason="not_completed",
            )

        previous_run = self._snapshots.previous_completed_run(scrape_run)
        current_map = self._snapshots.snapshots_by_run([scrape_run.id]).get(scrape_run.id, {})
        if previous_run is None:
            self._log.info(
                "Competitor event baseline established scrape_run_id=%s product_id=%s snapshots=%s",
                scrape_run.id,
                scrape_run.product_id,
                len(current_map),
            )
            return EventGenerationResult(scrape_run.id, 0, 0, "baseline")

        previous_map = self._snapshots.snapshots_by_run([previous_run.id]).get(previous_run.id, {})
        detected_at = _ensure_utc(scrape_run.completed_at or scrape_run.finished_at or scrape_run.created_at)
        candidates: list[CompetitorEvent] = []
        candidates.extend(self._price_and_stock_events(scrape_run, previous_map, current_map, detected_at))
        candidates.extend(self._new_competitor_events(scrape_run, previous_map, current_map, detected_at))
        candidates.extend(self._removed_competitor_events(scrape_run, detected_at))

        dedupe_keys = [event.dedupe_key for event in candidates]
        existing = self._events.existing_dedupe_keys(dedupe_keys)
        new_events = [event for event in candidates if event.dedupe_key not in existing]
        self._events.add_all(new_events)
        try:
            if hasattr(self._db, "flush"):
                self._db.flush()
                outbox = RagIndexOutboxService(self._db)
                for event in new_events:
                    outbox.enqueue_upsert(
                        seller_id=event.seller_id,
                        source_type=RagMemorySourceType.COMPETITOR_HISTORY,
                        source_id=str(event.id),
                        product_id=event.product_id,
                        source_updated_at=event.detected_at,
                    )
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            remaining = [
                event for event in new_events if event.dedupe_key not in self._events.existing_dedupe_keys([event.dedupe_key])
            ]
            if remaining:
                self._events.add_all(remaining)
                self._db.commit()
            new_events = remaining

        skipped = len(candidates) - len(new_events)
        self._log.info(
            "Competitor events generated scrape_run_id=%s product_id=%s candidates=%s created=%s duplicates=%s",
            scrape_run.id,
            scrape_run.product_id,
            len(candidates),
            len(new_events),
            skipped,
        )
        return EventGenerationResult(scrape_run.id, len(new_events), skipped)

    def _price_and_stock_events(
        self,
        scrape_run: ScrapeRun,
        previous_map: dict[UUID, CompetitorSnapshot],
        current_map: dict[UUID, CompetitorSnapshot],
        detected_at: datetime,
    ) -> list[CompetitorEvent]:
        events: list[CompetitorEvent] = []
        for competitor_id in sorted(set(previous_map) & set(current_map), key=str):
            previous = previous_map[competitor_id]
            current = current_map[competitor_id]
            events.extend(self._price_events(scrape_run, previous, current, detected_at))
            stock_event = self._stock_event(scrape_run, previous, current, detected_at)
            if stock_event:
                events.append(stock_event)
        return events

    def _price_events(
        self,
        scrape_run: ScrapeRun,
        previous: CompetitorSnapshot,
        current: CompetitorSnapshot,
        detected_at: datetime,
    ) -> list[CompetitorEvent]:
        if previous.price is None or current.price is None or previous.price <= 0:
            return []
        if current.price == previous.price:
            return []

        amount = (current.price - previous.price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        percent = ((amount / previous.price) * Decimal("100")).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        if abs(amount) < self._config.min_price_change_absolute and abs(percent) < self._config.min_price_change_percent:
            return []

        event_type = (
            CompetitorEventType.PRICE_DROP
            if current.price < previous.price
            else CompetitorEventType.PRICE_RISE
        )
        return [
            self._event(
                scrape_run=scrape_run,
                competitor_id=current.competitor_id,
                previous_snapshot_id=previous.id,
                current_snapshot_id=current.id,
                event_type=event_type,
                old_value={"price": str(previous.price), "currency": previous.currency},
                new_value={"price": str(current.price), "currency": current.currency},
                price_change_amount=abs(amount),
                price_change_percent=abs(percent),
                severity=_price_severity(abs(percent)),
                detected_at=detected_at,
                dedupe_parts=[event_type.value, str(scrape_run.id), str(current.competitor_id), str(current.id)],
            )
        ]

    def _stock_event(
        self,
        scrape_run: ScrapeRun,
        previous: CompetitorSnapshot,
        current: CompetitorSnapshot,
        detected_at: datetime,
    ) -> CompetitorEvent | None:
        if previous.stock_status == "IN_STOCK" and current.stock_status == "OUT_OF_STOCK":
            event_type = CompetitorEventType.OUT_OF_STOCK
            severity = CompetitorEventSeverity.HIGH
        elif previous.stock_status == "OUT_OF_STOCK" and current.stock_status == "IN_STOCK":
            event_type = CompetitorEventType.BACK_IN_STOCK
            severity = CompetitorEventSeverity.MEDIUM
        else:
            return None

        return self._event(
            scrape_run=scrape_run,
            competitor_id=current.competitor_id,
            previous_snapshot_id=previous.id,
            current_snapshot_id=current.id,
            event_type=event_type,
            old_value={"stock_status": previous.stock_status},
            new_value={"stock_status": current.stock_status},
            price_change_amount=None,
            price_change_percent=None,
            severity=severity,
            detected_at=detected_at,
            dedupe_parts=[event_type.value, str(scrape_run.id), str(current.competitor_id), str(current.id)],
        )

    def _new_competitor_events(
        self,
        scrape_run: ScrapeRun,
        previous_map: dict[UUID, CompetitorSnapshot],
        current_map: dict[UUID, CompetitorSnapshot],
        detected_at: datetime,
    ) -> list[CompetitorEvent]:
        events: list[CompetitorEvent] = []
        for competitor_id in sorted(set(current_map) - set(previous_map), key=str):
            current = current_map[competitor_id]
            events.append(
                self._event(
                    scrape_run=scrape_run,
                    competitor_id=competitor_id,
                    previous_snapshot_id=None,
                    current_snapshot_id=current.id,
                    event_type=CompetitorEventType.NEW_COMPETITOR,
                    old_value=None,
                    new_value={"price": str(current.price) if current.price is not None else None, "stock_status": current.stock_status},
                    price_change_amount=None,
                    price_change_percent=None,
                    severity=CompetitorEventSeverity.MEDIUM,
                    detected_at=detected_at,
                    dedupe_parts=[CompetitorEventType.NEW_COMPETITOR.value, str(scrape_run.product_id), str(competitor_id)],
                )
            )
        return events

    def _removed_competitor_events(self, scrape_run: ScrapeRun, detected_at: datetime) -> list[CompetitorEvent]:
        threshold = self._config.removal_consecutive_run_threshold
        recent_runs = self._snapshots.recent_completed_runs(scrape_run, limit=threshold)
        if len(recent_runs) < threshold:
            return []

        recent_maps = self._snapshots.snapshots_by_run([run.id for run in recent_runs])
        absent_in_recent = None
        for run in recent_runs:
            run_competitors = set(recent_maps.get(run.id, {}))
            absent_in_recent = (
                set(self._snapshots.historical_competitor_ids_before(scrape_run))
                if absent_in_recent is None
                else absent_in_recent
            )
            absent_in_recent -= run_competitors

        events: list[CompetitorEvent] = []
        for competitor_id in sorted(absent_in_recent or set(), key=str):
            if self._events.has_removal_event(product_id=scrape_run.product_id, competitor_id=competitor_id):
                continue
            events.append(
                self._event(
                    scrape_run=scrape_run,
                    competitor_id=competitor_id,
                    previous_snapshot_id=None,
                    current_snapshot_id=None,
                    event_type=CompetitorEventType.COMPETITOR_REMOVED,
                    old_value={"present": True},
                    new_value={"present": False},
                    price_change_amount=None,
                    price_change_percent=None,
                    severity=CompetitorEventSeverity.HIGH,
                    detected_at=detected_at,
                    dedupe_parts=[CompetitorEventType.COMPETITOR_REMOVED.value, str(scrape_run.product_id), str(competitor_id)],
                    metadata={"absent_completed_runs": threshold},
                )
            )
        return events

    def _event(
        self,
        *,
        scrape_run: ScrapeRun,
        competitor_id: UUID,
        previous_snapshot_id: UUID | None,
        current_snapshot_id: UUID | None,
        event_type: CompetitorEventType,
        old_value: dict | None,
        new_value: dict | None,
        price_change_amount: Decimal | None,
        price_change_percent: Decimal | None,
        severity: CompetitorEventSeverity,
        detected_at: datetime,
        dedupe_parts: list[str],
        metadata: dict | None = None,
    ) -> CompetitorEvent:
        return CompetitorEvent(
            seller_id=scrape_run.seller_id,
            product_id=scrape_run.product_id,
            competitor_id=competitor_id,
            scrape_run_id=scrape_run.id,
            previous_snapshot_id=previous_snapshot_id,
            current_snapshot_id=current_snapshot_id,
            event_type=event_type,
            old_value=old_value,
            new_value=new_value,
            price_change_amount=price_change_amount,
            price_change_percent=price_change_percent,
            severity=severity,
            dedupe_key=":".join(dedupe_parts),
            detected_at=detected_at,
            event_metadata=metadata,
        )


def _price_severity(percent: Decimal) -> CompetitorEventSeverity:
    if percent >= Decimal("25"):
        return CompetitorEventSeverity.CRITICAL
    if percent >= Decimal("10"):
        return CompetitorEventSeverity.HIGH
    if percent >= Decimal("5"):
        return CompetitorEventSeverity.MEDIUM
    return CompetitorEventSeverity.LOW


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
