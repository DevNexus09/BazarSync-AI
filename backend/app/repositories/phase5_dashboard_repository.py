from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.competitor import Competitor
from app.models.competitor_event import CompetitorEvent
from app.models.competitor_ranking import CompetitorRanking
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.market_opportunity import MarketOpportunity
from app.models.product import Product
from app.models.scrape_run import ScrapeRun


class Phase5DashboardRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def summary(self, *, seller_id: UUID, product_id: UUID | None, window_hours: int) -> dict:
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(hours=window_hours)
        latest_run = self._latest_completed_run(seller_id=seller_id, product_id=product_id)
        competitor_count = 0
        if latest_run:
            competitor_count = self._db.execute(
                select(func.count()).select_from(Competitor).where(Competitor.scrape_run_id == latest_run.id)
            ).scalar_one()

        event_scope = select(CompetitorEvent).where(
            CompetitorEvent.seller_id == seller_id,
            CompetitorEvent.detected_at >= window_start,
        )
        if product_id:
            event_scope = event_scope.where(CompetitorEvent.product_id == product_id)
        price_drop_count = self._db.execute(
            select(func.count()).select_from(event_scope.where(CompetitorEvent.event_type == "PRICE_DROP").subquery())
        ).scalar_one()
        stockout_count = self._db.execute(
            select(func.count()).select_from(event_scope.where(CompetitorEvent.event_type == "OUT_OF_STOCK").subquery())
        ).scalar_one()

        opportunity_scope = select(MarketOpportunity).where(
            MarketOpportunity.seller_id == seller_id,
            MarketOpportunity.status == "OPEN",
        )
        if product_id:
            opportunity_scope = opportunity_scope.where(MarketOpportunity.product_id == product_id)
        open_opportunity_count = self._db.execute(
            select(func.count()).select_from(opportunity_scope.subquery())
        ).scalar_one()

        last_updated_candidates = [
            latest_run.completed_at if latest_run else None,
            self._max_event_time(seller_id=seller_id, product_id=product_id),
            self._max_opportunity_time(seller_id=seller_id, product_id=product_id),
        ]
        last_updated_at = max([item for item in last_updated_candidates if item is not None], default=None)
        return {
            "competitor_count": competitor_count,
            "price_drop_count": price_drop_count,
            "stockout_count": stockout_count,
            "open_opportunity_count": open_opportunity_count,
            "last_updated_at": last_updated_at,
            "window_hours": window_hours,
            "window_start": window_start,
            "window_end": now,
            "competitor_count_scope": "latest_completed_scrape_run",
            "event_count_scope": "recent_window",
            "opportunity_count_scope": "currently_open",
        }

    def price_changes(self, *, seller_id: UUID, product_id: UUID | None, window_hours: int, limit: int, offset: int):
        return self._event_feed(
            seller_id=seller_id,
            product_id=product_id,
            window_hours=window_hours,
            event_types=["PRICE_DROP", "PRICE_RISE"],
            limit=limit,
            offset=offset,
        )

    def activity_feed(self, *, seller_id: UUID, product_id: UUID | None, window_hours: int, limit: int, offset: int):
        return self._event_feed(
            seller_id=seller_id,
            product_id=product_id,
            window_hours=window_hours,
            event_types=None,
            limit=limit,
            offset=offset,
        )

    def opportunity_feed(self, *, seller_id: UUID, product_id: UUID | None, limit: int, offset: int):
        stmt = (
            select(MarketOpportunity, Product.title.label("product_title"))
            .join(Product, MarketOpportunity.product_id == Product.id)
            .where(MarketOpportunity.seller_id == seller_id)
        )
        if product_id:
            stmt = stmt.where(MarketOpportunity.product_id == product_id)
        total = self._db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
        rows = self._db.execute(
            stmt.order_by(MarketOpportunity.detected_at.desc(), MarketOpportunity.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return rows, total

    def top_competitors(self, *, seller_id: UUID, product_id: UUID | None, limit: int):
        latest_run = self._latest_completed_run(seller_id=seller_id, product_id=product_id)
        if not latest_run:
            return [], 0
        stmt = (
            select(
                CompetitorRanking,
                Product.title.label("product_title"),
                Competitor.competitor_title.label("competitor_title"),
                Competitor.competitor_store.label("competitor_store"),
                CompetitorSnapshot.price.label("price"),
                CompetitorSnapshot.rating.label("rating"),
                CompetitorSnapshot.review_count.label("review_count"),
                CompetitorSnapshot.stock_status.label("stock_status"),
                CompetitorSnapshot.source_url.label("source_url"),
            )
            .join(Product, CompetitorRanking.product_id == Product.id)
            .join(Competitor, CompetitorRanking.competitor_id == Competitor.id)
            .join(
                CompetitorSnapshot,
                (CompetitorSnapshot.scrape_run_id == CompetitorRanking.scrape_run_id)
                & (CompetitorSnapshot.competitor_id == CompetitorRanking.competitor_id)
                & (CompetitorSnapshot.product_id == CompetitorRanking.product_id),
            )
            .where(
                CompetitorRanking.seller_id == seller_id,
                CompetitorRanking.scrape_run_id == latest_run.id,
            )
        )
        if product_id:
            stmt = stmt.where(CompetitorRanking.product_id == product_id)
        total = self._db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
        rows = self._db.execute(
            stmt.order_by(
                CompetitorRanking.market_rank.asc(),
                CompetitorRanking.total_score.desc(),
                CompetitorRanking.competitor_id.asc(),
            ).limit(limit)
        ).all()
        return rows, total

    def _event_feed(self, *, seller_id: UUID, product_id: UUID | None, window_hours: int, event_types: list[str] | None, limit: int, offset: int):
        window_start = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        stmt = (
            select(
                CompetitorEvent,
                Product.title.label("product_title"),
                Competitor.competitor_title.label("competitor_title"),
            )
            .join(Product, CompetitorEvent.product_id == Product.id)
            .join(Competitor, CompetitorEvent.competitor_id == Competitor.id)
            .where(
                CompetitorEvent.seller_id == seller_id,
                CompetitorEvent.detected_at >= window_start,
            )
        )
        if product_id:
            stmt = stmt.where(CompetitorEvent.product_id == product_id)
        if event_types:
            stmt = stmt.where(CompetitorEvent.event_type.in_(event_types))
        total = self._db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
        rows = self._db.execute(
            stmt.order_by(CompetitorEvent.detected_at.desc(), CompetitorEvent.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return rows, total

    def _latest_completed_run(self, *, seller_id: UUID, product_id: UUID | None) -> ScrapeRun | None:
        stmt = select(ScrapeRun).where(ScrapeRun.seller_id == seller_id, ScrapeRun.status == "COMPLETED")
        if product_id:
            stmt = stmt.where(ScrapeRun.product_id == product_id)
        return self._db.execute(
            stmt.order_by(ScrapeRun.completed_at.desc().nullslast(), ScrapeRun.created_at.desc()).limit(1)
        ).scalar_one_or_none()

    def _max_event_time(self, *, seller_id: UUID, product_id: UUID | None):
        stmt = select(func.max(CompetitorEvent.detected_at)).where(CompetitorEvent.seller_id == seller_id)
        if product_id:
            stmt = stmt.where(CompetitorEvent.product_id == product_id)
        return self._db.execute(stmt).scalar_one()

    def _max_opportunity_time(self, *, seller_id: UUID, product_id: UUID | None):
        stmt = select(func.max(MarketOpportunity.detected_at)).where(MarketOpportunity.seller_id == seller_id)
        if product_id:
            stmt = stmt.where(MarketOpportunity.product_id == product_id)
        return self._db.execute(stmt).scalar_one()
