from __future__ import annotations

from datetime import datetime, timezone
import time
import asyncio
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.competitor import Competitor
from app.models.price_history import PriceHistory
from app.models.product import Product
from app.models.scrape_run import ScrapeRun
from app.models.seller import Seller
from app.scraper.exceptions import ScraperError, SimilarityError
from app.scraper.services.competitor_service import scrape_daraz_competitors
from app.scraper.similarity import filter_similar_products
from app.scraper.constants import SIMILARITY_THRESHOLD
from app.scraper.constants import MARKETPLACE_NAME
from app.schemas.scrape import ScrapeRunResponse
from app.schemas.competitor import CompetitorSnapshot
from app.services.competitor_snapshot_service import CompetitorSnapshotService, InvalidScrapeRunTransitionError
from app.services.competitor_service import CompetitorService
from app.services.dashboard.events import DashboardEventEmitter
from app.services.realtime import RealtimeService
from app.websocket.socket_events import CompetitorSnapshot as RealtimeCompetitorSnapshot
from app.websocket.socket_events import CompetitorUpdatedPayload
from app.websocket.socket_manager import get_socket_emitter
from app.websocket.socket_rooms import seller_room


class ScrapeProductNotFoundError(Exception):
    pass


class ProductAccessError(Exception):
    pass


class ScrapePipelineError(Exception):
    pass


class ScrapeRunNotFoundError(Exception):
    pass


class ScrapeService:
    def __init__(
        self,
        db: Session,
        *,
        event_emitter: DashboardEventEmitter | None = None,
    ) -> None:
        self._db = db
        self._competitor_service = CompetitorService(db)
        self._event_emitter = event_emitter
        self._realtime: RealtimeService | None = None

    async def run_manual_scrape(
        self,
        *,
        seller: Seller,
        product_id: UUID,
        threshold: float | None = None,
        scrape_run_id: UUID | None = None,
        run_key: str | None = None,
        task_id: str | None = None,
    ) -> ScrapeRunResponse:
        product = self._get_product(product_id)
        if not product:
            raise ScrapeProductNotFoundError("Product not found.")
        if product.seller_id != seller.id:
            raise ProductAccessError("You do not have access to this product.")

        if scrape_run_id:
            scrape_run = self._get_scrape_run(scrape_run_id)
            if not scrape_run:
                raise ScrapeRunNotFoundError("Scrape run not found.")
            if scrape_run.product_id != product.id or scrape_run.seller_id != seller.id:
                raise ProductAccessError("Scrape run does not belong to this product.")
            if scrape_run.status == "COMPLETED":
                return self._completed_response(scrape_run=scrape_run, product=product, start=0.0)
            snapshot_service = CompetitorSnapshotService(self._db)
            snapshot_service.transition_to_running(scrape_run, task_id=task_id)
            self._db.commit()
        else:
            resolved_run_key = run_key or self._default_run_key(seller.id, product.id)
            snapshot_service = CompetitorSnapshotService(self._db)
            result = snapshot_service.start_scrape_run(
                seller_id=seller.id,
                product_id=product.id,
                marketplace=MARKETPLACE_NAME,
                run_key=resolved_run_key,
                task_id=task_id,
            )
            self._db.commit()
            scrape_run = result.scrape_run
            if result.already_completed:
                return self._completed_response(scrape_run=scrape_run, product=product, start=0.0)
        start = time.monotonic()

        try:
            scrape_response = await scrape_daraz_competitors(product_title=product.title)
            competitors_raw = [item.model_dump() for item in scrape_response.products]
            competitors_found = len(competitors_raw)

            filtered = await asyncio.to_thread(
                filter_similar_products,
                seller_title=product.title,
                seller_description=product.description or "",
                seller_category=product.category,
                seller_specifications=product.specifications or {},
                competitors=competitors_raw,
                threshold=threshold if threshold is not None else SIMILARITY_THRESHOLD,
            )
            matched_results = len(filtered)
            filtered_results = max(0, competitors_found - matched_results)

            competitor_rows = self._competitor_service.store_competitors(
                scrape_run=scrape_run,
                product=product,
                marketplace=scrape_response.marketplace,
                competitors=filtered,
                observed_at=scrape_response.scraped_at,
            )

            snapshot_service = CompetitorSnapshotService(self._db)
            snapshot_service.record_successful_scrape(
                scrape_run=scrape_run,
                competitors=competitor_rows,
                captured_at=scrape_response.scraped_at,
                discovered_count=competitors_found,
                matched_count=matched_results,
            )

            self._db.commit()
            self._db.refresh(scrape_run)

            await self._emit_competitor_updated(
                scrape_run=scrape_run,
                product=product,
                competitors=competitor_rows,
                matched_results=matched_results,
                marketplace=scrape_response.marketplace,
                scraped_at=scrape_response.scraped_at,
            )

            processing_time = time.monotonic() - start
            return ScrapeRunResponse(
                success=True,
                product_id=product.id,
                product_title=product.title,
                scrape_run_id=scrape_run.id,
                competitors_found=competitors_found,
                matched_results=matched_results,
                filtered_results=filtered_results,
                processing_time_seconds=round(processing_time, 2),
                scraped_at=scrape_response.scraped_at,
                competitors=[self._to_snapshot(item) for item in filtered],
            )
        except (
            ScraperError,
            SimilarityError,
            SQLAlchemyError,
            RuntimeError,
            ValueError,
            TypeError,
        ) as exc:
            self._db.rollback()
            self._mark_run_failed(scrape_run.id, str(exc))
            raise ScrapePipelineError(str(exc)) from exc

    def create_pending_run(self, *, seller: Seller, product_id: UUID) -> tuple[ScrapeRun, Product]:
        product = self._get_product(product_id)
        if not product:
            raise ScrapeProductNotFoundError("Product not found.")
        if product.seller_id != seller.id:
            raise ProductAccessError("You do not have access to this product.")

        scrape_run = ScrapeRun(
            seller_id=seller.id,
            product_id=product.id,
            marketplace=MARKETPLACE_NAME,
            run_key=self._default_run_key(seller.id, product.id),
            status="PENDING",
        )
        self._db.add(scrape_run)
        self._db.flush()
        scrape_run.run_key = f"manual:{scrape_run.id}"
        self._db.commit()
        self._db.refresh(scrape_run)
        return scrape_run, product

    def _get_product(self, product_id: UUID) -> Product | None:
        return self._db.get(Product, product_id)

    def _get_scrape_run(self, scrape_run_id: UUID) -> ScrapeRun | None:
        return self._db.get(ScrapeRun, scrape_run_id)

    def get_scrape_run_status(
        self,
        *,
        seller: Seller,
        scrape_run_id: UUID,
    ) -> tuple[ScrapeRun, Product]:
        statement = select(ScrapeRun).where(
            ScrapeRun.id == scrape_run_id,
            ScrapeRun.seller_id == seller.id,
        )
        scrape_run = self._db.execute(statement).scalar_one_or_none()
        if not scrape_run:
            raise ScrapeRunNotFoundError("Scrape run not found.")

        product = self._db.get(Product, scrape_run.product_id)
        if not product:
            raise ScrapeProductNotFoundError("Product not found.")

        return scrape_run, product

    def _create_scrape_run(self, seller_id: UUID, product_id: UUID) -> ScrapeRun:
        scrape_run = ScrapeRun(
            seller_id=seller_id,
            product_id=product_id,
            marketplace=MARKETPLACE_NAME,
            run_key=self._default_run_key(seller_id, product_id),
            status="RUNNING",
            started_at=datetime.now(timezone.utc),
        )
        self._db.add(scrape_run)
        self._db.flush()
        scrape_run.run_key = f"manual:{scrape_run.id}"
        self._db.commit()
        self._db.refresh(scrape_run)
        return scrape_run

    def _mark_run_failed(self, scrape_run_id: UUID, message: str) -> None:
        try:
            CompetitorSnapshotService(self._db).record_failed_scrape(
                scrape_run_id=scrape_run_id,
                reason=message,
            )
        except InvalidScrapeRunTransitionError:
            self._db.rollback()

    def mark_run_failed(self, scrape_run_id: UUID, message: str) -> None:
        self._mark_run_failed(scrape_run_id, message)

    @staticmethod
    def _default_run_key(seller_id: UUID, product_id: UUID) -> str:
        return f"manual:{seller_id}:{product_id}:{datetime.now(timezone.utc).isoformat()}"

    def _completed_response(
        self,
        *,
        scrape_run: ScrapeRun,
        product: Product,
        start: float,
    ) -> ScrapeRunResponse:
        processing_time = 0.0 if start == 0.0 else round(time.monotonic() - start, 2)
        return ScrapeRunResponse(
            success=True,
            product_id=product.id,
            product_title=product.title,
            scrape_run_id=scrape_run.id,
            competitors_found=scrape_run.total_results or scrape_run.discovered_competitor_count or 0,
            matched_results=scrape_run.successful_matches or 0,
            filtered_results=max(
                0,
                (scrape_run.total_results or scrape_run.discovered_competitor_count or 0)
                - (scrape_run.successful_matches or 0),
            ),
            processing_time_seconds=processing_time,
            scraped_at=scrape_run.completed_at or scrape_run.finished_at or scrape_run.created_at,
            competitors=[],
        )

    @staticmethod
    def _to_snapshot(item: dict) -> CompetitorSnapshot:
        return CompetitorSnapshot(
            competitor_title=item.get("competitor_title") or item.get("product_title") or "",
            competitor_price=item.get("competitor_price")
            or item.get("product_price"),
            competitor_store=item.get("competitor_store") or item.get("store_name"),
            similarity_score=item.get("similarity_score"),
            stock_status=item.get("stock_status"),
            product_url=item.get("product_url") or item.get("daraz_product_url"),
        )

    async def _emit_competitor_updated(
        self,
        *,
        scrape_run: ScrapeRun,
        product: Product,
        competitors: list[Competitor],
        matched_results: int,
        marketplace: str,
        scraped_at: datetime | None,
    ) -> None:
        realtime = self._resolve_realtime()
        if not realtime:
            return
        if not competitors:
            return
        primary = self._select_primary_competitor(competitors)
        if not primary or primary.competitor_price is None:
            return
        seller_price = float(product.selling_price)
        competitor_price = float(primary.competitor_price)
        price_gap = seller_price - competitor_price
        trend = self._resolve_price_trend(primary.id)
        snapshot = RealtimeCompetitorSnapshot(
            id=primary.id,
            product=product.title,
            competitor=primary.competitor_title,
            competitor_price=competitor_price,
            seller_price=seller_price,
            price_gap=price_gap,
            stock_status=primary.stock_status or "in_stock",
            urgency_score=_compute_competitor_urgency(
                price_gap_percent=_compute_price_gap_percent(seller_price, competitor_price),
                stock_status=primary.stock_status,
            ),
            recommendation_action=_recommendation_action_label(seller_price, competitor_price),
            trend=trend,
            last_updated=primary.updated_at or scraped_at or datetime.now(timezone.utc),
            status="active",
        )
        payload = CompetitorUpdatedPayload(competitor=snapshot)
        await realtime.emit_competitor_updated(
            payload,
            seller_id=product.seller_id,
            product_id=product.id,
            rooms=[seller_room(str(product.seller_id))],
        )

    def _resolve_realtime(self) -> RealtimeService | None:
        if self._realtime is not None:
            return self._realtime
        try:
            emitter = get_socket_emitter()
        except RuntimeError:
            return None
        self._realtime = RealtimeService(emitter)
        return self._realtime

    @staticmethod
    def _select_primary_competitor(competitors: list[Competitor]) -> Competitor | None:
        if not competitors:
            return None
        return max(
            competitors,
            key=lambda item: item.similarity_score or 0.0,
        )

    def _resolve_price_trend(self, competitor_id: UUID) -> str:
        stmt = (
            select(PriceHistory.observed_price)
            .where(PriceHistory.competitor_id == competitor_id)
            .order_by(PriceHistory.observed_at.desc())
            .limit(2)
        )
        prices = self._db.execute(stmt).scalars().all()
        if len(prices) < 2:
            return "flat"
        latest, previous = prices[0], prices[1]
        if latest is None or previous is None:
            return "flat"
        if latest > previous:
            return "up"
        if latest < previous:
            return "down"
        return "flat"


def _compute_price_gap_percent(seller_price: float, competitor_price: float) -> float:
    if competitor_price <= 0:
        return 0.0
    return ((seller_price - competitor_price) / competitor_price) * 100.0


def _compute_competitor_urgency(
    *, price_gap_percent: float, stock_status: str | None
) -> int:
    base = min(abs(price_gap_percent) * 2, 100)
    if stock_status == "out_of_stock":
        return int(max(base, 85))
    if stock_status == "low_stock":
        return int(max(base, 65))
    return int(round(base))


def _recommendation_action_label(seller_price: float, competitor_price: float) -> str:
    if seller_price > competitor_price:
        return "Lower price"
    if seller_price < competitor_price:
        return "Raise price"
    return "Hold"
