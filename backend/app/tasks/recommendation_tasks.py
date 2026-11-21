from __future__ import annotations

import logging
import asyncio
import time
from uuid import UUID

from celery.exceptions import Ignore
from sqlalchemy.exc import DBAPIError, OperationalError, SQLAlchemyError, TimeoutError as DatabaseTimeout

from app.core.async_runner import run_async
from app.ai.recommendation_generator import InvalidAIResponseError, RecommendationValidationError
from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.product import Product
from app.models.seller import Seller
from app.services.recommendation_jobs import ATTEMPT_TIMEOUT, JOB_TASK, RecommendationJobs
from app.services.recommendation_service import (
    AIRecommendationError,
    AnalyticsExecutionError,
    CompetitorDataNotFoundError,
    ProductNotFoundError,
    RecommendationAttemptLostError,
    RecommendationPersistenceError,
    RecommendationService,
)

logger = logging.getLogger(__name__)


@celery_app.task(name=JOB_TASK, ignore_result=True, time_limit=150)
def run_recommendation_job(job_id: str) -> None:
    with SessionLocal() as session:
        jobs = RecommendationJobs(session)
        attempt = jobs.claim(UUID(job_id))
        if attempt is None:
            return
        logger.info("recommendation_job_running job_id=%s attempt=%s", attempt.job_id, attempt.number)

        async def generate() -> None:
            async with asyncio.timeout(ATTEMPT_TIMEOUT):
                await RecommendationService(session).generate_recommendation(
                    seller_id=attempt.seller_id, product_id=attempt.product_id,
                    scrape_run_id=attempt.scrape_run_id, attempt=attempt,
                )

        try:
            run_async(generate())
        except RecommendationAttemptLostError:
            logger.info("recommendation_job_attempt_superseded job_id=%s attempt=%s", attempt.job_id, attempt.number)
        except (ProductNotFoundError, CompetitorDataNotFoundError, AnalyticsExecutionError) as exc:
            jobs.record_failure(attempt, exc.error_code, transient=False)
        except AIRecommendationError as exc:
            cause = exc.__cause__
            transient = not isinstance(cause, (InvalidAIResponseError, RecommendationValidationError)) and bool(
                getattr(cause, "retryable", False)
            )
            jobs.record_failure(attempt, exc.error_code, transient=transient)
        except TimeoutError:
            jobs.record_failure(attempt, "ai_generation_failed", transient=True)
        except (RecommendationPersistenceError, SQLAlchemyError) as exc:
            source = exc.__cause__ if isinstance(exc, RecommendationPersistenceError) else exc
            transient = isinstance(source, (OperationalError, DatabaseTimeout)) or (
                isinstance(source, DBAPIError) and source.connection_invalidated
            )
            jobs.record_failure(attempt, "storage_unavailable", transient=transient)
        except Exception:
            logger.exception("recommendation_job_failed job_id=%s", attempt.job_id)
            jobs.record_failure(attempt, "generation_failed", transient=False)


@celery_app.task(name="analytics.recover_recommendation_jobs", ignore_result=True, time_limit=25)
def recover_recommendation_jobs() -> int:
    with SessionLocal() as session:
        return RecommendationJobs(session).recover()


@celery_app.task(
    bind=True,
    name="analytics.generate_ai_recommendation",
    autoretry_for=(AIRecommendationError, RecommendationPersistenceError, SQLAlchemyError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=2,
)
def generate_ai_recommendation_task(
    self,
    product_id: str,
    seller_id: str | None = None,
    *,
    scrape_run_id: str | None = None,
) -> dict:
    start = time.monotonic()
    session = SessionLocal()
    try:
        try:
            product_uuid = UUID(product_id)
        except ValueError as exc:
            logger.warning("Invalid product_id provided to task: %s", product_id)
            raise Ignore() from exc

        product = session.get(Product, product_uuid)
        if not product:
            logger.warning("Product not found for recommendation task: %s", product_id)
            raise Ignore()

        seller_uuid = None
        if seller_id:
            try:
                seller_uuid = UUID(seller_id)
            except ValueError as exc:
                logger.warning("Invalid seller_id provided to task: %s", seller_id)
                raise Ignore() from exc
        if seller_uuid and seller_uuid != product.seller_id:
            logger.warning(
                "Seller/product mismatch in recommendation task: %s vs %s",
                seller_uuid,
                product.seller_id,
            )
            raise Ignore()

        seller = session.get(Seller, seller_uuid or product.seller_id)
        if not seller:
            logger.warning("Seller not found for recommendation task: %s", seller_uuid)
            raise Ignore()

        service = RecommendationService(session)
        try:
            run_uuid = UUID(scrape_run_id) if scrape_run_id is not None else None
        except ValueError as exc:
            logger.warning("Invalid scrape_run_id provided to recommendation task.")
            raise Ignore() from exc
        run_async(
            service.generate_recommendation(
                seller_id=seller.id,
                product_id=product_uuid,
                scrape_run_id=run_uuid,
                legacy_delivery=True,
            )
        )

        duration = round(time.monotonic() - start, 2)
        logger.info(
            "Recommendation task completed product=%s duration=%.2fs",
            product_id,
            duration,
        )
        return {"product_id": product_id, "processing_time_seconds": duration}
    except (ProductNotFoundError, CompetitorDataNotFoundError, AnalyticsExecutionError) as exc:
        logger.warning("Non-retriable recommendation error: %s", exc)
        raise Ignore() from exc
    except AIRecommendationError as exc:
        logger.exception("AI recommendation failed: %s", exc)
        raise
    except RecommendationPersistenceError as exc:
        logger.exception("Recommendation persistence failed: %s", exc)
        raise
    finally:
        session.close()
