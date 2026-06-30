from __future__ import annotations

from datetime import datetime
from typing import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.competitor import Competitor
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.product import Product
from app.models.scrape_run import ScrapeRun


class CompetitorSnapshotRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def add_all(self, snapshots: Sequence[CompetitorSnapshot]) -> None:
        if snapshots:
            self._db.add_all(snapshots)

    def count_for_run(self, scrape_run_id: UUID) -> int:
        statement = select(func.count()).select_from(CompetitorSnapshot).where(
            CompetitorSnapshot.scrape_run_id == scrape_run_id
        )
        return self._db.execute(statement).scalar_one()

    def list_for_run(self, *, seller_id: UUID, scrape_run_id: UUID) -> list[CompetitorSnapshot]:
        statement = (
            select(CompetitorSnapshot)
            .join(ScrapeRun, CompetitorSnapshot.scrape_run_id == ScrapeRun.id)
            .where(
                ScrapeRun.id == scrape_run_id,
                ScrapeRun.seller_id == seller_id,
            )
            .order_by(CompetitorSnapshot.captured_at.asc(), CompetitorSnapshot.id.asc())
        )
        return list(self._db.execute(statement).scalars().all())

    def latest_for_competitor(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        competitor_id: UUID,
    ) -> CompetitorSnapshot | None:
        statement = self._base_competitor_scope(seller_id, product_id, competitor_id).order_by(
            CompetitorSnapshot.captured_at.desc(),
            CompetitorSnapshot.id.desc(),
        )
        return self._db.execute(statement.limit(1)).scalar_one_or_none()

    def previous_for_competitor(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        competitor_id: UUID,
        before_captured_at: datetime,
        before_snapshot_id: UUID,
    ) -> CompetitorSnapshot | None:
        statement = self._base_competitor_scope(seller_id, product_id, competitor_id).where(
            (CompetitorSnapshot.captured_at < before_captured_at)
            | (
                (CompetitorSnapshot.captured_at == before_captured_at)
                & (CompetitorSnapshot.id < before_snapshot_id)
            )
        )
        statement = statement.order_by(CompetitorSnapshot.captured_at.desc(), CompetitorSnapshot.id.desc())
        return self._db.execute(statement.limit(1)).scalar_one_or_none()

    def timeline(
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
        statement = self._base_competitor_scope(seller_id, product_id, competitor_id)
        if from_at is not None:
            statement = statement.where(CompetitorSnapshot.captured_at >= from_at)
        if to_at is not None:
            statement = statement.where(CompetitorSnapshot.captured_at <= to_at)

        total = self._db.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
        if order == "desc":
            statement = statement.order_by(CompetitorSnapshot.captured_at.desc(), CompetitorSnapshot.id.desc())
        else:
            statement = statement.order_by(CompetitorSnapshot.captured_at.asc(), CompetitorSnapshot.id.asc())

        rows = self._db.execute(statement.limit(limit).offset(offset)).scalars().all()
        return list(rows), total

    def latest_for_product(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[CompetitorSnapshot], int]:
        latest_ids = (
            select(
                CompetitorSnapshot.id,
                func.row_number()
                .over(
                    partition_by=CompetitorSnapshot.competitor_id,
                    order_by=(CompetitorSnapshot.captured_at.desc(), CompetitorSnapshot.id.desc()),
                )
                .label("rn"),
            )
            .join(Product, CompetitorSnapshot.product_id == Product.id)
            .where(
                Product.id == product_id,
                Product.seller_id == seller_id,
            )
            .subquery()
        )
        base = (
            select(CompetitorSnapshot)
            .join(latest_ids, CompetitorSnapshot.id == latest_ids.c.id)
            .where(latest_ids.c.rn == 1)
        )
        total = self._db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
        rows = self._db.execute(
            base.order_by(CompetitorSnapshot.captured_at.desc(), CompetitorSnapshot.id.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
        return list(rows), total

    def _base_competitor_scope(
        self,
        seller_id: UUID,
        product_id: UUID,
        competitor_id: UUID,
    ):
        return (
            select(CompetitorSnapshot)
            .join(Product, CompetitorSnapshot.product_id == Product.id)
            .join(Competitor, CompetitorSnapshot.competitor_id == Competitor.id)
            .where(
                Product.id == product_id,
                Product.seller_id == seller_id,
                Competitor.product_id == product_id,
                Competitor.id == competitor_id,
            )
        )


class ScrapeRunRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_for_seller(self, *, seller_id: UUID, scrape_run_id: UUID) -> ScrapeRun | None:
        statement = select(ScrapeRun).where(
            ScrapeRun.id == scrape_run_id,
            ScrapeRun.seller_id == seller_id,
        )
        return self._db.execute(statement).scalar_one_or_none()

    def get_by_run_key(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        marketplace: str,
        run_key: str,
        for_update: bool = False,
    ) -> ScrapeRun | None:
        statement = select(ScrapeRun).where(
            ScrapeRun.seller_id == seller_id,
            ScrapeRun.product_id == product_id,
            ScrapeRun.marketplace == marketplace,
            ScrapeRun.run_key == run_key,
        )
        if for_update:
            statement = statement.with_for_update()
        return self._db.execute(statement).scalar_one_or_none()

    def completed_exists(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        marketplace: str,
        run_key: str,
    ) -> bool:
        statement = select(ScrapeRun.id).where(
            ScrapeRun.seller_id == seller_id,
            ScrapeRun.product_id == product_id,
            ScrapeRun.marketplace == marketplace,
            ScrapeRun.run_key == run_key,
            ScrapeRun.status == "COMPLETED",
        )
        return self._db.execute(statement.limit(1)).scalar_one_or_none() is not None

    def last_successful_for_product(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        marketplace: str | None = None,
    ) -> ScrapeRun | None:
        statement = select(ScrapeRun).where(
            ScrapeRun.seller_id == seller_id,
            ScrapeRun.product_id == product_id,
            ScrapeRun.status == "COMPLETED",
        )
        if marketplace:
            statement = statement.where(ScrapeRun.marketplace == marketplace)
        statement = statement.order_by(
            ScrapeRun.completed_at.desc().nullslast(),
            ScrapeRun.finished_at.desc().nullslast(),
            ScrapeRun.created_at.desc(),
        )
        return self._db.execute(statement.limit(1)).scalar_one_or_none()

    def recent_for_product(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        status: str | None,
        marketplace: str | None,
        from_at: datetime | None,
        to_at: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ScrapeRun], int]:
        statement = select(ScrapeRun).where(
            ScrapeRun.seller_id == seller_id,
            ScrapeRun.product_id == product_id,
        )
        if status:
            statement = statement.where(ScrapeRun.status == status)
        if marketplace:
            statement = statement.where(ScrapeRun.marketplace == marketplace)
        if from_at:
            statement = statement.where(ScrapeRun.created_at >= from_at)
        if to_at:
            statement = statement.where(ScrapeRun.created_at <= to_at)

        total = self._db.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
        rows = self._db.execute(
            statement.order_by(ScrapeRun.created_at.desc(), ScrapeRun.id.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
        return list(rows), total
