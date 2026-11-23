from __future__ import annotations

import hashlib
import logging
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.celery_app import celery_app
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.seller import Seller
from app.services.recommendation_outcome_service import RecommendationOutcomeService

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="recommendation_outcomes.evaluate",
    autoretry_for=(SQLAlchemyError,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def evaluate_recommendation_outcomes_task(self) -> dict[str, int | str]:
    if not settings.recommendation_outcomes_enabled:
        return {"skipped_reason": "disabled"}
    session = SessionLocal()
    totals = {"sellers": 0, "pricing": 0, "reorder": 0, "locked": 0}
    try:
        for seller_id in list(session.execute(select(Seller.id)).scalars()):
            key = f"recommendation-outcomes:{seller_id}:{date.today()}"
            lock_id = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:15], 16)
            if not session.execute(select(func.pg_try_advisory_xact_lock(lock_id))).scalar_one():
                totals["locked"] += 1
                session.rollback()
                continue
            counts = RecommendationOutcomeService(session).evaluate_seller(seller_id=seller_id)  # commits, releasing the lock
            totals["sellers"] += 1
            totals["pricing"] += counts["pricing"]
            totals["reorder"] += counts["reorder"]
        logger.info("recommendation_outcomes_completed %s", totals)
        return dict(totals)
    finally:
        session.close()
