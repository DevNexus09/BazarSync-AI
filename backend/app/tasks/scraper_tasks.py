from __future__ import annotations

import hashlib
import logging
import time
from contextlib import nullcontext
from datetime import datetime, timezone
from uuid import UUID

from celery import Task
from celery.exceptions import Ignore, Reject
from celery.utils.time import get_exponential_backoff_interval
from kombu.exceptions import OperationalError as BrokerError
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError, OperationalError, SQLAlchemyError, TimeoutError as DatabaseTimeout
from sqlalchemy.orm import Session

from app.core.async_runner import run_async
from app.core.celery_app import celery_app
from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.models.product import Product, ProductStatus
from app.models.scrape_run import ScrapeRun
from app.models.seller import Seller
from app.scraper.exceptions import PageLoadError, ScraperError
from app.services.scrape_scheduling import plan_refreshes, refresh_policy
from app.services.scrape_service import (
    ProductAccessError,
    ScrapeEnqueueError,
    ScrapePipelineError,
    ScrapeProductIneligibleError,
    ScrapeProductNotFoundError,
    ScrapeRunNotFoundError,
    ScrapeService,
)

logger = logging.getLogger(__name__)
MAX_RETRIES = 3


@celery_app.task(bind=True, name="scraper.run_manual_scrape", max_retries=MAX_RETRIES)
def run_manual_scrape_task(
    self: Task,
    product_id: str,
    seller_id: str | None = None,
    scrape_run_id: str | None = None,
    threshold: float | None = None,
) -> dict[str, str | int | float]:
    try:
        product_uuid = UUID(product_id)
        seller_uuid = UUID(seller_id) if seller_id else None
        run_uuid = UUID(scrape_run_id) if scrape_run_id else None
    except ValueError as exc:
        logger.warning("Scrape task received an invalid identifier.")
        raise Ignore() from exc

    start = time.monotonic()
    try:
        # Hold the advisory lock on a separate transaction across service commits.
        # PostgreSQL releases it when the connection closes, including after worker loss.
        lock_key = int.from_bytes(hashlib.sha256(f"scrape-delivery:{self.request.id or run_uuid or product_uuid}".encode()).digest()[:8], signed=True)
        with engine.begin() as lock_connection, SessionLocal() as session:
            if not lock_connection.scalar(select(func.pg_try_advisory_xact_lock(lock_key))):
                raise Ignore("Scrape delivery already in progress.")
            return _execute_scrape(self, session, product_uuid, seller_uuid, run_uuid, threshold, start)
    except Ignore:
        raise
    except Exception as exc:
        cause = exc.__cause__ if isinstance(exc, ScrapePipelineError) else exc
        if _is_retryable(cause) and self.request.retries < self.max_retries:
            backoff = get_exponential_backoff_interval(
                factor=1, retries=self.request.retries, maximum=300, full_jitter=True,
            )
            retry_after = cause.retry_after if isinstance(cause, PageLoadError) else 0
            countdown = max(backoff, retry_after)
            logger.warning(
                "Retrying scrape product=%s run=%s retry=%s delay=%s",
                product_uuid, run_uuid, self.request.retries + 1, countdown,
            )
            try:
                raise self.retry(exc=exc, countdown=countdown)
            except Reject as rejected:
                # Celery rejects the original delivery when publishing its retry fails.
                # Mark the run terminal so status polling can surface that broker failure.
                _mark_unhandled_failure(run_uuid, product_uuid, seller_uuid, self.request.id, "SCRAPE_RETRY_ENQUEUE_FAILED")
                raise rejected from exc

        logger.error("Scrape task failed product=%s run=%s failure_code=%s", product_uuid, run_uuid, _failure_code(cause))
        if not isinstance(exc, ScrapePipelineError):
            _mark_unhandled_failure(run_uuid, product_uuid, seller_uuid, self.request.id, _failure_code(cause))
        raise


def _execute_scrape(
    task: Task,
    session: Session,
    product_id: UUID,
    seller_id: UUID | None,
    run_id: UUID | None,
    threshold: float | None,
    start: float,
) -> dict[str, str | int | float]:
    # Wait for a concurrent enqueue transaction to commit before reading its run.
    product = session.execute(
        select(Product).where(Product.id == product_id).with_for_update()
    ).scalar_one_or_none()
    if product is None or (seller_id is not None and product.seller_id != seller_id):
        raise Ignore("Product or seller mismatch.")
    # Before this release Beat sent product/seller arguments without a run ID.
    if run_id is None:
        if product.status != ProductStatus.ACTIVE:
            raise Ignore("Product is ineligible for scheduled scraping.")
        other_active_run = session.scalar(
            select(ScrapeRun.id).where(
                ScrapeRun.product_id == product.id,
                ScrapeRun.seller_id == product.seller_id,
                ScrapeRun.status.in_(("PENDING", "RUNNING")),
                ScrapeRun.celery_task_id != task.request.id,
            ).limit(1)
        )
        if other_active_run is not None:
            raise Ignore("A newer scrape is already active.")
    seller = session.get(Seller, product.seller_id)
    if seller is None:
        raise Ignore("Seller no longer exists.")

    service = ScrapeService(session)
    try:
        response = run_async(
            service.run_manual_scrape(
                seller=seller,
                product_id=product_id,
                threshold=threshold,
                scrape_run_id=run_id,
                run_key=f"celery:{task.request.id}",
                task_id=task.request.id,
                retry_count=task.request.retries,
            )
        )
    except (ScrapeProductNotFoundError, ProductAccessError, ScrapeRunNotFoundError) as exc:
        raise Ignore() from exc
    except ScrapeProductIneligibleError as exc:
        if run_id is not None:
            service.mark_run_failed(run_id, "PRODUCT_INELIGIBLE")
        raise Ignore() from exc
    except ScrapePipelineError as exc:
        if not _is_retryable(exc.__cause__) or task.request.retries >= task.max_retries:
            service.mark_run_failed(exc.scrape_run_id, _failure_code(exc.__cause__))
        raise

    # A retry or redelivery after completion reuses the same run and can dispatch Phase 5 again.
    celery_app.send_task("phase5.run_analysis_workflow", args=[str(response.scrape_run_id)], retry=False)
    duration = round(time.monotonic() - start, 2)
    logger.info(
        "Scrape task completed product=%s run=%s matched=%s duration=%.2fs",
        product_id, response.scrape_run_id, response.matched_results, duration,
    )
    return {
        "scrape_run_id": str(response.scrape_run_id),
        "product_id": str(product_id),
        "matched_results": response.matched_results,
        "processing_time_seconds": duration,
    }


def _is_retryable(exc: BaseException | None) -> bool:
    if isinstance(exc, (PageLoadError, BrokerError, DatabaseTimeout)):
        return True
    if isinstance(exc, DBAPIError):
        sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
        if exc.connection_invalidated or (sqlstate is None and isinstance(exc, OperationalError)):
            return True
        return isinstance(sqlstate, str) and (
            sqlstate.startswith("08") or sqlstate in {"40001", "40P01", "55P03", "57P01", "57P03", "53300"}
        )
    return False


def _failure_code(exc: BaseException | None) -> str:
    if isinstance(exc, ScraperError):
        return exc.failure_code
    if isinstance(exc, SQLAlchemyError):
        return "SCRAPE_DATABASE_ERROR"
    return "SCRAPE_FAILED"


def _mark_unhandled_failure(
    run_id: UUID | None, product_id: UUID, seller_id: UUID | None, task_id: str, code: str,
) -> None:
    try:
        with SessionLocal() as session:
            scope = select(ScrapeRun).join(
                Product, (Product.id == ScrapeRun.product_id) & (Product.seller_id == ScrapeRun.seller_id)
            ).where(ScrapeRun.product_id == product_id, ScrapeRun.celery_task_id == task_id)
            if seller_id is not None:
                scope = scope.where(ScrapeRun.seller_id == seller_id)
            if run_id is not None:
                scope = scope.where(ScrapeRun.id == run_id)
            run = session.execute(scope.with_for_update(of=ScrapeRun)).scalar_one_or_none()
            if run is not None:
                ScrapeService(session).mark_run_failed(run.id, code)
    except SQLAlchemyError as exc:
        logger.error("scrape_failure_persist_failed product=%s run=%s error_type=%s", product_id, run_id, type(exc).__name__)


def _schedule_eligible_products(task_id: str, *, adaptive_only: bool = False) -> dict[str, int]:
    if not settings.daraz_scraping_authorized:
        logger.info("Periodic Daraz scraping skipped because acquisition is not authorized.")
        return {"scheduled": 0}

    policy = refresh_policy()
    if adaptive_only and policy is None:
        return {"scheduled": 0}

    # Keep the planner lock through each committed enqueue, across Beat processes.
    with (engine.begin() if policy else nullcontext()) as lock, SessionLocal() as session:
        if lock is not None and not lock.scalar(select(func.pg_try_advisory_xact_lock(487231974))):
            return {"scheduled": 0}
        if policy is None:
            rows = [(product_id, seller_id, None) for product_id, seller_id in session.execute(
                select(Product.id, Product.seller_id).where(Product.status == ProductStatus.ACTIVE)
            )]
        else:
            rows = [
                (candidate.product_id, candidate.seller_id, candidate.last_attempt)
                for candidate in plan_refreshes(session, policy, datetime.now(timezone.utc))
            ]
        service = ScrapeService(session)
        scheduled = 0
        failed = 0
        for product_id, seller_id, last_attempt in rows:
            try:
                _, _, queued = service.enqueue_scrape(
                    seller_id=seller_id, product_id=product_id, schedule_key=f"scheduled:{task_id}",
                    scheduled_history=(last_attempt,) if policy is not None else None,
                )
                scheduled += int(queued)
            except (ScrapeProductNotFoundError, ProductAccessError, ScrapeProductIneligibleError):
                session.rollback()
            except ScrapeEnqueueError:
                failed += 1
        logger.info("Scheduled %s periodic scrape jobs. Enqueue failures: %s.", scheduled, failed)
        if failed:
            raise ScrapeEnqueueError(f"Failed to enqueue {failed} periodic scrape jobs.")
        return {"scheduled": scheduled}


@celery_app.task(
    bind=True,
    name="scraper.run_periodic_scrape",
    autoretry_for=(SQLAlchemyError,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=MAX_RETRIES,
)
def run_periodic_scrape(self: Task) -> dict[str, int]:
    return _schedule_eligible_products(self.request.id)


@celery_app.task(
    bind=True,
    name="scraper.run_nightly_refresh",
    autoretry_for=(SQLAlchemyError,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=2,
)
def run_nightly_refresh(self: Task) -> dict[str, int]:
    return _schedule_eligible_products(self.request.id)


@celery_app.task(
    bind=True, name="scraper.run_adaptive_refresh",
    autoretry_for=(SQLAlchemyError,), retry_backoff=True, retry_backoff_max=300, retry_jitter=True, max_retries=3,
)
def run_adaptive_refresh(self: Task) -> dict[str, int]:
    return _schedule_eligible_products(self.request.id, adaptive_only=True)
