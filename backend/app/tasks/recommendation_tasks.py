from __future__ import annotations

import logging
import time
from uuid import UUID

from celery.exceptions import Ignore
from sqlalchemy.exc import SQLAlchemyError

from app.core.async_runner import run_async
from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.product import Product
from app.models.seller import Seller
from app.services.recommendation_service import (
    AIRecommendationError,
    AnalyticsExecutionError,
    CompetitorDataNotFoundError,
    ProductNotFoundError,
    RecommendationPersistenceError,
    RecommendationService,
)

logger = logging.getLogger(__name__)


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
        run_async(
            service.generate_recommendation(
                seller_id=seller.id,
                product_id=product_uuid,
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
