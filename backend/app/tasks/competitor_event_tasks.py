from __future__ import annotations

import hashlib
import logging
from uuid import UUID

from celery.exceptions import Ignore
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.competitor_event_service import CompetitorEventService

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="competitor_events.generate_for_scrape_run",
    autoretry_for=(SQLAlchemyError, RuntimeError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def generate_competitor_events_task(self, scrape_run_id: str) -> dict[str, str | int | None]:
    try:
        run_uuid = UUID(scrape_run_id)
    except ValueError as exc:
        logger.warning("Invalid scrape_run_id for competitor event generation: %s", scrape_run_id)
        raise Ignore() from exc

    session = SessionLocal()
    try:
        if not _try_advisory_lock(session, f"competitor-events:{run_uuid}"):
            logger.info("Competitor event generation lock contention scrape_run_id=%s", run_uuid)
            return {
                "scrape_run_id": scrape_run_id,
                "generated_count": 0,
                "skipped_duplicate_count": 0,
                "skipped_reason": "locked",
            }

        service = CompetitorEventService(session, log=logger)
        result = service.generate_for_scrape_run(run_uuid)
        return {
            "scrape_run_id": str(result.scrape_run_id),
            "generated_count": result.generated_count,
            "skipped_duplicate_count": result.skipped_duplicate_count,
            "skipped_reason": result.skipped_reason,
        }
    finally:
        session.close()


def _try_advisory_lock(session, key: str) -> bool:
    lock_id = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:15], 16)
    try:
        statement = select(func.pg_try_advisory_xact_lock(lock_id))
        return bool(session.execute(statement).scalar_one())
    except SQLAlchemyError:
        session.rollback()
        return True
