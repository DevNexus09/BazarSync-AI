from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.competitor_event import CompetitorEvent
from app.models.competitor_ranking import CompetitorRanking
from app.models.market_opportunity import MarketOpportunity
from app.models.product import Product
from app.models.scrape_run import ScrapeRun


class MarketOpportunityRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_completed_run(self, scrape_run_id: UUID) -> ScrapeRun | None:
        return self._db.execute(
            select(ScrapeRun).where(ScrapeRun.id == scrape_run_id, ScrapeRun.status == "COMPLETED")
        ).scalar_one_or_none()

    def trigger_events_for_run(self, scrape_run_id: UUID) -> list[CompetitorEvent]:
        return list(
            self._db.execute(
                select(CompetitorEvent)
                .where(
                    CompetitorEvent.scrape_run_id == scrape_run_id,
                    CompetitorEvent.event_type.in_(["OUT_OF_STOCK", "PRICE_RISE", "COMPETITOR_REMOVED"]),
                )
                .order_by(CompetitorEvent.detected_at.asc(), CompetitorEvent.id.asc())
            ).scalars().all()
        )

    def rankings_for_run(self, scrape_run_id: UUID, formula_version: str) -> dict[UUID, CompetitorRanking]:
        rows = self._db.execute(
            select(CompetitorRanking).where(
                CompetitorRanking.scrape_run_id == scrape_run_id,
                CompetitorRanking.formula_version == formula_version,
            )
        ).scalars().all()
        return {row.competitor_id: row for row in rows}

    def product(self, product_id: UUID) -> Product | None:
        return self._db.get(Product, product_id)

    def existing_trigger_ids(self, trigger_event_ids: list[UUID]) -> set[UUID]:
        if not trigger_event_ids:
            return set()
        return set(
            self._db.execute(
                select(MarketOpportunity.trigger_event_id).where(
                    MarketOpportunity.trigger_event_id.in_(trigger_event_ids)
                )
            ).scalars().all()
        )

    def add_all(self, opportunities: list[MarketOpportunity]) -> None:
        if opportunities:
            self._db.add_all(opportunities)

    def list_opportunities(
        self,
        *,
        seller_id: UUID,
        product_id: UUID | None,
        level: str | None,
        status: str | None,
        recent_closed: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[MarketOpportunity], int]:
        statement = select(MarketOpportunity).where(MarketOpportunity.seller_id == seller_id)
        if product_id:
            statement = statement.where(MarketOpportunity.product_id == product_id)
        if level:
            statement = statement.where(MarketOpportunity.opportunity_level == level)
        if status:
            statement = statement.where(MarketOpportunity.status == status)
        elif recent_closed:
            statement = statement.where(MarketOpportunity.status.in_(["RESOLVED", "EXPIRED", "DISMISSED"]))
        else:
            statement = statement.where(MarketOpportunity.status == "OPEN")

        total = self._db.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
        rows = self._db.execute(
            statement.order_by(MarketOpportunity.detected_at.desc(), MarketOpportunity.id.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
        return list(rows), total

    def get_for_seller(self, *, seller_id: UUID, opportunity_id: UUID) -> MarketOpportunity | None:
        return self._db.execute(
            select(MarketOpportunity).where(
                MarketOpportunity.id == opportunity_id,
                MarketOpportunity.seller_id == seller_id,
            )
        ).scalar_one_or_none()

    def product_for_seller(self, *, seller_id: UUID, product_id: UUID) -> Product | None:
        return self._db.execute(
            select(Product).where(Product.id == product_id, Product.seller_id == seller_id)
        ).scalar_one_or_none()
