from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.competitor_event import CompetitorEvent
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.product import Product
from app.models.scrape_run import ScrapeRun


class CompetitorEventRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def add_all(self, events: list[CompetitorEvent]) -> None:
        if events:
            self._db.add_all(events)

    def existing_dedupe_keys(self, dedupe_keys: list[str]) -> set[str]:
        if not dedupe_keys:
            return set()
        statement = select(CompetitorEvent.dedupe_key).where(CompetitorEvent.dedupe_key.in_(dedupe_keys))
        return set(self._db.execute(statement).scalars().all())

    def has_removal_event(self, *, product_id: UUID, competitor_id: UUID) -> bool:
        statement = select(CompetitorEvent.id).where(
            CompetitorEvent.product_id == product_id,
            CompetitorEvent.competitor_id == competitor_id,
            CompetitorEvent.event_type == "COMPETITOR_REMOVED",
        )
        return self._db.execute(statement.limit(1)).scalar_one_or_none() is not None

    def list_events(
        self,
        *,
        seller_id: UUID,
        product_id: UUID | None,
        competitor_id: UUID | None,
        event_type: str | None,
        severity: str | None,
        from_at: datetime | None,
        to_at: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[CompetitorEvent], int]:
        statement = select(CompetitorEvent).where(CompetitorEvent.seller_id == seller_id)
        if product_id:
            statement = statement.where(CompetitorEvent.product_id == product_id)
        if competitor_id:
            statement = statement.where(CompetitorEvent.competitor_id == competitor_id)
        if event_type:
            statement = statement.where(CompetitorEvent.event_type == event_type)
        if severity:
            statement = statement.where(CompetitorEvent.severity == severity)
        if from_at:
            statement = statement.where(CompetitorEvent.detected_at >= from_at)
        if to_at:
            statement = statement.where(CompetitorEvent.detected_at <= to_at)

        total = self._db.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
        rows = self._db.execute(
            statement.order_by(CompetitorEvent.detected_at.desc(), CompetitorEvent.id.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
        return list(rows), total


class CompetitorEventSnapshotRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_completed_run(self, scrape_run_id: UUID) -> ScrapeRun | None:
        statement = select(ScrapeRun).where(
            ScrapeRun.id == scrape_run_id,
            ScrapeRun.status == "COMPLETED",
        )
        return self._db.execute(statement).scalar_one_or_none()

    def previous_completed_run(self, current_run: ScrapeRun) -> ScrapeRun | None:
        marker = current_run.completed_at or current_run.finished_at or current_run.created_at
        statement = (
            select(ScrapeRun)
            .where(
                ScrapeRun.seller_id == current_run.seller_id,
                ScrapeRun.product_id == current_run.product_id,
                ScrapeRun.marketplace == current_run.marketplace,
                ScrapeRun.status == "COMPLETED",
                ScrapeRun.id != current_run.id,
                ScrapeRun.created_at <= marker,
            )
            .order_by(
                ScrapeRun.completed_at.desc().nullslast(),
                ScrapeRun.finished_at.desc().nullslast(),
                ScrapeRun.created_at.desc(),
                ScrapeRun.id.desc(),
            )
            .limit(1)
        )
        return self._db.execute(statement).scalar_one_or_none()

    def recent_completed_runs(self, current_run: ScrapeRun, *, limit: int) -> list[ScrapeRun]:
        marker = current_run.completed_at or current_run.finished_at or current_run.created_at
        statement = (
            select(ScrapeRun)
            .where(
                ScrapeRun.seller_id == current_run.seller_id,
                ScrapeRun.product_id == current_run.product_id,
                ScrapeRun.marketplace == current_run.marketplace,
                ScrapeRun.status == "COMPLETED",
                ScrapeRun.created_at <= marker,
            )
            .order_by(
                ScrapeRun.completed_at.desc().nullslast(),
                ScrapeRun.finished_at.desc().nullslast(),
                ScrapeRun.created_at.desc(),
                ScrapeRun.id.desc(),
            )
            .limit(limit)
        )
        return list(self._db.execute(statement).scalars().all())

    def snapshots_by_run(self, scrape_run_ids: list[UUID]) -> dict[UUID, dict[UUID, CompetitorSnapshot]]:
        if not scrape_run_ids:
            return {}
        statement = select(CompetitorSnapshot).where(CompetitorSnapshot.scrape_run_id.in_(scrape_run_ids))
        by_run: dict[UUID, dict[UUID, CompetitorSnapshot]] = {}
        for snapshot in self._db.execute(statement).scalars().all():
            by_run.setdefault(snapshot.scrape_run_id, {})[snapshot.competitor_id] = snapshot
        return by_run

    def historical_competitor_ids_before(self, current_run: ScrapeRun) -> set[UUID]:
        marker = current_run.completed_at or current_run.finished_at or current_run.created_at
        statement = (
            select(CompetitorSnapshot.competitor_id)
            .join(ScrapeRun, CompetitorSnapshot.scrape_run_id == ScrapeRun.id)
            .join(Product, CompetitorSnapshot.product_id == Product.id)
            .where(
                ScrapeRun.seller_id == current_run.seller_id,
                ScrapeRun.product_id == current_run.product_id,
                ScrapeRun.marketplace == current_run.marketplace,
                ScrapeRun.status == "COMPLETED",
                ScrapeRun.id != current_run.id,
                ScrapeRun.created_at < marker,
            )
            .distinct()
        )
        return set(self._db.execute(statement).scalars().all())
