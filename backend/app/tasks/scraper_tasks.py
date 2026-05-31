from __future__ import annotations

import asyncio
import logging
import time
from threading import Thread
from uuid import UUID

from celery.exceptions import Ignore
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.product import Product
from app.models.seller import Seller
from app.scraper.exceptions import ScraperError, SimilarityError
from app.services.scrape_service import (
    ProductAccessError,
    ScrapeProductNotFoundError,
    ScrapePipelineError,
    ScrapeRunNotFoundError,
    ScrapeService,
)

logger = logging.getLogger(__name__)


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result_container: dict[str, object] = {}

    def runner() -> None:
        try:
            result_container["result"] = asyncio.run(coro)
        except Exception as error:
            result_container["error"] = error

    thread = Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in result_container:
        raise result_container["error"]
    return result_container.get("result")


@celery_app.task(
    bind=True,
    name="scraper.run_manual_scrape",
    autoretry_for=(ScraperError, SimilarityError, SQLAlchemyError, RuntimeError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def run_manual_scrape_task(
    self,
    product_id: str,
    seller_id: str | None = None,
    scrape_run_id: str | None = None,
    threshold: float | None = None,
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
            logger.warning("Product not found for scrape task: %s", product_id)
            raise Ignore()

        seller_uuid = None
        if seller_id:
            try:
                seller_uuid = UUID(seller_id)
            except ValueError as exc:
                logger.warning("Invalid seller_id provided to task: %s", seller_id)
                raise Ignore() from exc
        if seller_uuid and seller_uuid != product.seller_id:
            logger.warning("Seller/product mismatch in scrape task: %s vs %s", seller_uuid, product.seller_id)
            raise Ignore()

        seller = session.get(Seller, seller_uuid or product.seller_id)
        if not seller:
            logger.warning("Seller not found for scrape task: %s", seller_uuid)
            raise Ignore()

        run_uuid = None
        if scrape_run_id:
            try:
                run_uuid = UUID(scrape_run_id)
            except ValueError as exc:
                logger.warning("Invalid scrape_run_id provided to task: %s", scrape_run_id)
                raise Ignore() from exc

        service = ScrapeService(session)
        response = _run_async(
            service.run_manual_scrape(
                seller=seller,
                product_id=product_uuid,
                threshold=threshold,
                scrape_run_id=run_uuid,
            )
        )

        duration = round(time.monotonic() - start, 2)
        logger.info(
            "Scrape task completed product=%s run=%s matched=%s duration=%.2fs",
            product_id,
            getattr(response, "scrape_run_id", None),
            getattr(response, "matched_results", None),
            duration,
        )
        return {
            "scrape_run_id": str(getattr(response, "scrape_run_id", "")),
            "product_id": product_id,
            "matched_results": getattr(response, "matched_results", 0),
            "processing_time_seconds": duration,
        }
    except (ScrapeProductNotFoundError, ProductAccessError, ScrapeRunNotFoundError) as exc:
        logger.warning("Non-retriable scrape error: %s", exc)
        raise Ignore() from exc
    except ScrapePipelineError as exc:
        logger.exception("Scrape pipeline failed: %s", exc)
        raise
    finally:
        session.close()


@celery_app.task(
    name="scraper.run_periodic_scrape",
    autoretry_for=(SQLAlchemyError, RuntimeError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def run_periodic_scrape() -> dict:
    session = SessionLocal()
    try:
        statement = select(Product.id, Product.seller_id)
        rows = session.execute(statement).all()
        scheduled = 0
        for product_id, seller_id in rows:
            run_manual_scrape_task.delay(str(product_id), str(seller_id))
            scheduled += 1
        logger.info("Scheduled %s periodic scrape jobs.", scheduled)
        return {"scheduled": scheduled}
    finally:
        session.close()


@celery_app.task(
    name="scraper.run_nightly_refresh",
    autoretry_for=(SQLAlchemyError, RuntimeError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=2,
)
def run_nightly_refresh() -> dict:
    return run_periodic_scrape()
