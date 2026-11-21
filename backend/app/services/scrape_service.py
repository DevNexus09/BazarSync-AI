from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

from kombu.exceptions import OperationalError as BrokerError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.competitor import Competitor
from app.models.price_history import PriceHistory
from app.models.product import Product, ProductStatus
from app.models.scrape_run import ScrapeRun
from app.models.seller import Seller
from app.schemas.competitor import CompetitorSnapshot
from app.schemas.scrape import ScrapeRunResponse
from app.scraper.constants import MARKETPLACE_NAME, SIMILARITY_THRESHOLD
from app.scraper.exceptions import ParseError, ScraperError, SimilarityError, public_failure_message
from app.scraper.schemas.scraped_product import ObservationProvenance
from app.scraper.services.competitor_service import scrape_daraz_competitors
from app.scraper.similarity import filter_similar_products
from app.scraper.telemetry import ScrapeTelemetry
from app.services.competitor_service import CompetitorService
from app.services.competitor_snapshot_service import CompetitorObservation, CompetitorSnapshotService
from app.services.dashboard.events import DashboardEventEmitter
from app.services.realtime import RealtimeService
from app.websocket.socket_events import CompetitorSnapshot as RealtimeCompetitorSnapshot
from app.websocket.socket_events import CompetitorUpdatedPayload
from app.websocket.socket_manager import get_socket_emitter
from app.websocket.socket_rooms import seller_room

logger = logging.getLogger(__name__)


class ScrapeProductNotFoundError(Exception):
    pass


class ProductAccessError(Exception):
    pass


class ScrapePipelineError(Exception):
    def __init__(self, scrape_run_id: UUID) -> None:
        super().__init__(str(scrape_run_id))
        self.scrape_run_id = scrape_run_id


class ScrapeEnqueueError(Exception):
    pass


class ScrapeProductIneligibleError(Exception):
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
        retry_count: int | None = None,
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
            if scrape_run.celery_task_id and task_id and scrape_run.celery_task_id != task_id:
                raise ProductAccessError("Scrape run belongs to a different task.")
            if scrape_run.status == "COMPLETED":
                return self._completed_response(scrape_run=scrape_run, product=product)
            if scrape_run.status in {"FAILED", "PARTIAL"}:
                raise ScrapeRunNotFoundError("Scrape run is already terminal.")
            if scrape_run.run_key.startswith("scheduled:") and product.status != ProductStatus.ACTIVE:
                raise ScrapeProductIneligibleError("Product is no longer eligible for scheduled scraping.")
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
                return self._completed_response(scrape_run=scrape_run, product=product)
        start = time.monotonic()

        telemetry = ScrapeTelemetry.start(scrape_run.id, product.id, retry_count)
        try:
            telemetry.request_status = "failed"
            scrape_response = await scrape_daraz_competitors(product_title=product.title, seller_id=product.seller_id)
            telemetry.acquired(scrape_response)
            telemetry.matching_status = "failed"
            competitors_raw = [item.model_dump() for item in scrape_response.products]
            competitors_found = len(competitors_raw)

            try:
                filtered = await asyncio.to_thread(
                    filter_similar_products,
                    seller_title=product.title,
                    seller_description=product.description or "",
                    seller_category=product.category,
                    seller_specifications=product.specifications or {},
                    competitors=competitors_raw,
                    threshold=threshold if threshold is not None else SIMILARITY_THRESHOLD,
                )
            except SimilarityError:
                raise
            except Exception as exc:
                raise SimilarityError("Competitor matching failed unexpectedly.") from exc

            telemetry.matching_status = "success"
            telemetry.competitors_matched = len(filtered)
            # Acquisition normally deduplicates URLs. Conflicting duplicate
            # provenance cannot be tied to the listing selected by matching.
            provenance_by_url: dict[str, ObservationProvenance | None] = {}
            for item in scrape_response.products:
                prior = provenance_by_url.setdefault(item.daraz_product_url, item.provenance)
                if prior != item.provenance:
                    provenance_by_url[item.daraz_product_url] = None
            competitor_rows, observations = self._competitor_service.store_competitors(
                scrape_run=scrape_run,
                product=product,
                marketplace=scrape_response.marketplace,
                competitors=filtered,
                observed_at=scrape_response.scraped_at,
                price_observed_at_by_url={
                    url: provenance.price_observed_at
                    for url, provenance in provenance_by_url.items()
                    if provenance is not None and provenance.price_observed_at is not None
                },
                stock_observed_at_by_url={
                    url: provenance.stock_observed_at
                    for url, provenance in provenance_by_url.items()
                    if provenance is not None and provenance.stock_observed_at is not None
                },
            )

            matched_results = len(competitor_rows)
            telemetry.competitors_matched = matched_results
            filtered_results = max(0, competitors_found - matched_results)
            snapshot_service = CompetitorSnapshotService(self._db)
            snapshot_service.record_successful_scrape(
                scrape_run=scrape_run,
                competitors=competitor_rows,
                captured_at=scrape_response.scraped_at,
                discovered_count=competitors_found,
                matched_count=matched_results,
                observations=observations,
            )

            processing_time = time.monotonic() - start
            response = ScrapeRunResponse(
                success=True,
                product_id=product.id,
                product_title=product.title,
                scrape_run_id=scrape_run.id,
                competitors_found=competitors_found,
                matched_results=matched_results,
                filtered_results=filtered_results,
                processing_time_seconds=round(processing_time, 2),
                scraped_at=scrape_response.scraped_at,
                competitors=[
                    CompetitorSnapshot(
                        competitor_title=row.competitor_title,
                        competitor_price=observations[row.id].price,
                        competitor_store=row.competitor_store,
                        similarity_score=row.similarity_score,
                        stock_status=observations[row.id].stock_status,
                        product_url=row.product_url,
                    )
                    for row in competitor_rows
                ],
            )

            self._db.commit()

            try:
                await self._emit_competitor_updated(
                    product=product,
                    competitors=competitor_rows,
                    observations=observations,
                    scraped_at=scrape_response.scraped_at,
                )
            except Exception as exc:
                logger.error("scrape_realtime_failed run=%s error_type=%s", scrape_run.id, type(exc).__name__)
                self._db.rollback()

            return response
        except Exception as exc:
            if isinstance(exc, ParseError):
                telemetry.request_status = "success"
                telemetry.parser_status = "failed"
            telemetry.failure_code = exc.failure_code if isinstance(exc, ScraperError) else "SCRAPE_FAILED"
            self._db.rollback()
            raise ScrapePipelineError(scrape_run.id) from exc
        finally:
            telemetry.emit(time.monotonic() - start)

    def enqueue_scrape(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        threshold: float | None = None,
        schedule_key: str | None = None,
        scheduled_history: tuple[datetime | None] | None = None,
    ) -> tuple[ScrapeRun, Product, bool]:
        from app.core.celery_app import celery_app

        # Serialize admission for this product, including competing Beat and API calls.
        product = self._db.execute(
            select(Product).where(Product.id == product_id).with_for_update()
        ).scalar_one_or_none()
        if product is None:
            raise ScrapeProductNotFoundError("Product not found.")
        if product.seller_id != seller_id:
            raise ProductAccessError("You do not have access to this product.")
        if schedule_key and product.status != ProductStatus.ACTIVE:
            raise ScrapeProductIneligibleError("Product is ineligible for scheduled scraping.")

        scope = select(ScrapeRun).where(
            ScrapeRun.seller_id == seller_id,
            ScrapeRun.product_id == product_id,
            ScrapeRun.marketplace == MARKETPLACE_NAME,
        )
        active = self._db.execute(
            scope.where(
                ScrapeRun.status.in_(("PENDING", "RUNNING")),
                ScrapeRun.celery_task_id.is_not(None),
            )
            .order_by(ScrapeRun.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if active is not None:
            self._db.commit()
            return active, product, False

        if scheduled_history is not None:
            latest_attempt = self._db.scalar(
                scope.with_only_columns(func.max(func.coalesce(
                    ScrapeRun.finished_at, ScrapeRun.completed_at, ScrapeRun.started_at, ScrapeRun.created_at,
                ))).where(ScrapeRun.status.in_(("COMPLETED", "FAILED", "PARTIAL")))
            )
            if latest_attempt != scheduled_history[0]:
                raise ScrapeProductIneligibleError("Scrape history changed during planning.")

        task_id = uuid4()
        run_key = schedule_key or f"manual:{task_id}:{threshold if threshold is not None else SIMILARITY_THRESHOLD}"
        if schedule_key:
            existing = self._db.execute(scope.where(ScrapeRun.run_key == run_key)).scalar_one_or_none()
            if existing is not None:
                self._db.commit()
                return existing, product, False

        scrape_run = ScrapeRun(
            seller_id=seller_id,
            product_id=product.id,
            marketplace=MARKETPLACE_NAME,
            run_key=run_key,
            status="PENDING",
            celery_task_id=str(task_id),
        )
        self._db.add(scrape_run)
        self._db.flush()
        try:
            # The worker takes the same product lock before reading the run.
            # Publishing within this transaction leaves no committed orphan if admission is interrupted.
            celery_app.send_task(
                "scraper.run_manual_scrape",
                args=[str(product.id), str(seller_id), str(scrape_run.id), threshold],
                task_id=str(task_id),
                retry=False,
            )
        except BrokerError as exc:
            logger.error("scrape_enqueue_failed run=%s", scrape_run.id)
            self.mark_run_failed(scrape_run.id, "SCRAPE_ENQUEUE_FAILED")
            raise ScrapeEnqueueError("Failed to enqueue scraper task.") from exc
        self._db.commit()
        return scrape_run, product, True

    @staticmethod
    def run_threshold(scrape_run: ScrapeRun) -> float:
        parts = scrape_run.run_key.split(":")
        if len(parts) == 3 and parts[0] == "manual":
            return float(parts[-1])
        return SIMILARITY_THRESHOLD

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
        if not product or product.seller_id != seller.id:
            raise ScrapeProductNotFoundError("Product not found.")

        return scrape_run, product

    def mark_run_failed(self, scrape_run_id: UUID, code: str) -> None:
        CompetitorSnapshotService(self._db).record_failed_scrape(
            scrape_run_id=scrape_run_id,
            reason=public_failure_message(code),
            failure_code=code,
        )

    @staticmethod
    def _default_run_key(seller_id: UUID, product_id: UUID) -> str:
        return f"manual:{seller_id}:{product_id}:{datetime.now(timezone.utc).isoformat()}"

    def _completed_response(
        self,
        *,
        scrape_run: ScrapeRun,
        product: Product,
    ) -> ScrapeRunResponse:
        found = scrape_run.total_results
        if found is None:
            found = scrape_run.discovered_competitor_count
        found = 0 if found is None else found
        matched = 0 if scrape_run.successful_matches is None else scrape_run.successful_matches
        return ScrapeRunResponse(
            success=True,
            product_id=product.id,
            product_title=product.title,
            scrape_run_id=scrape_run.id,
            competitors_found=found,
            matched_results=matched,
            filtered_results=max(0, found - matched),
            processing_time_seconds=0.0,
            scraped_at=scrape_run.completed_at or scrape_run.finished_at or scrape_run.created_at,
            competitors=[],
        )

    async def _emit_competitor_updated(
        self,
        *,
        product: Product,
        competitors: list[Competitor],
        observations: dict[UUID, CompetitorObservation],
        scraped_at: datetime | None,
    ) -> None:
        realtime = self._resolve_realtime()
        if not realtime:
            return
        if not competitors:
            return
        primary = self._select_primary_competitor(competitors)
        if primary is None or (observed_price := observations[primary.id].price) is None:
            return
        seller_price = float(product.selling_price)
        competitor_price = float(observed_price)
        price_gap = seller_price - competitor_price
        trend = self._resolve_price_trend(primary.id)
        snapshot = RealtimeCompetitorSnapshot(
            id=primary.id,
            product=product.title,
            competitor=primary.competitor_title,
            competitor_price=competitor_price,
            seller_price=seller_price,
            price_gap=price_gap,
            stock_status=observations[primary.id].stock_status or "unknown",
            urgency_score=_compute_competitor_urgency(
                price_gap_percent=_compute_price_gap_percent(seller_price, competitor_price),
                stock_status=observations[primary.id].stock_status,
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
