from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.competitor_ranking import CompetitorRanking
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.product import Product
from app.models.scrape_run import ScrapeRun


class CompetitorRankingRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_completed_run(self, scrape_run_id: UUID) -> ScrapeRun | None:
        statement = select(ScrapeRun).where(ScrapeRun.id == scrape_run_id, ScrapeRun.status == "COMPLETED")
        return self._db.execute(statement).scalar_one_or_none()

    def snapshots_for_run(self, scrape_run_id: UUID) -> list[CompetitorSnapshot]:
        statement = (
            select(CompetitorSnapshot)
            .where(CompetitorSnapshot.scrape_run_id == scrape_run_id)
            .order_by(CompetitorSnapshot.competitor_id.asc(), CompetitorSnapshot.captured_at.desc())
        )
        return list(self._db.execute(statement).scalars().all())

    def existing_competitor_ids(self, *, scrape_run_id: UUID, formula_version: str) -> set[UUID]:
        statement = select(CompetitorRanking.competitor_id).where(
            CompetitorRanking.scrape_run_id == scrape_run_id,
            CompetitorRanking.formula_version == formula_version,
        )
        return set(self._db.execute(statement).scalars().all())

    def add_all(self, rankings: list[CompetitorRanking]) -> None:
        if rankings:
            self._db.add_all(rankings)

    def latest_run_id_for_product(self, *, seller_id: UUID, product_id: UUID, formula_version: str) -> UUID | None:
        statement = (
            select(CompetitorRanking.scrape_run_id)
            .where(
                CompetitorRanking.seller_id == seller_id,
                CompetitorRanking.product_id == product_id,
                CompetitorRanking.formula_version == formula_version,
            )
            .order_by(CompetitorRanking.calculated_at.desc(), CompetitorRanking.scrape_run_id.desc())
            .limit(1)
        )
        return self._db.execute(statement).scalar_one_or_none()

    def list_for_run(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        scrape_run_id: UUID,
        formula_version: str,
        limit: int,
        offset: int,
    ) -> tuple[list[CompetitorRanking], int]:
        statement = select(CompetitorRanking).where(
            CompetitorRanking.seller_id == seller_id,
            CompetitorRanking.product_id == product_id,
            CompetitorRanking.scrape_run_id == scrape_run_id,
            CompetitorRanking.formula_version == formula_version,
        )
        total = self._db.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
        rows = self._db.execute(
            statement.order_by(CompetitorRanking.market_rank.asc(), CompetitorRanking.competitor_id.asc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
        return list(rows), total

    def history_for_product(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        formula_version: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[CompetitorRanking], int]:
        statement = select(CompetitorRanking).where(
            CompetitorRanking.seller_id == seller_id,
            CompetitorRanking.product_id == product_id,
        )
        if formula_version:
            statement = statement.where(CompetitorRanking.formula_version == formula_version)
        total = self._db.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
        rows = self._db.execute(
            statement.order_by(
                CompetitorRanking.calculated_at.desc(),
                CompetitorRanking.market_rank.asc(),
                CompetitorRanking.competitor_id.asc(),
            )
            .limit(limit)
            .offset(offset)
        ).scalars().all()
        return list(rows), total

    def history_for_competitor(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        competitor_id: UUID,
        formula_version: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[CompetitorRanking], int]:
        statement = select(CompetitorRanking).where(
            CompetitorRanking.seller_id == seller_id,
            CompetitorRanking.product_id == product_id,
            CompetitorRanking.competitor_id == competitor_id,
        )
        if formula_version:
            statement = statement.where(CompetitorRanking.formula_version == formula_version)
        total = self._db.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
        rows = self._db.execute(
            statement.order_by(CompetitorRanking.calculated_at.asc(), CompetitorRanking.id.asc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
        return list(rows), total

    def product_for_seller(self, *, seller_id: UUID, product_id: UUID) -> Product | None:
        statement = select(Product).where(Product.id == product_id, Product.seller_id == seller_id)
        return self._db.execute(statement).scalar_one_or_none()
