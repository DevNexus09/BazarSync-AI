from __future__ import annotations

import hashlib
import logging
from uuid import UUID

from celery.exceptions import Ignore
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.competitor_ranking_service import CompetitorRankingService

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="competitor_rankings.calculate_for_scrape_run",
    autoretry_for=(SQLAlchemyError, RuntimeError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def calculate_competitor_rankings_task(self, scrape_run_id: str) -> dict[str, str | int | None]:
    try:
        run_uuid = UUID(scrape_run_id)
    except ValueError as exc:
        logger.warning("Invalid scrape_run_id for competitor ranking calculation: %s", scrape_run_id)
        raise Ignore() from exc

    session = SessionLocal()
    try:
        if not _try_advisory_lock(session, f"competitor-rankings:{run_uuid}"):
            logger.info("Competitor ranking lock contention scrape_run_id=%s", run_uuid)
            return {
                "scrape_run_id": scrape_run_id,
                "created_count": 0,
                "skipped_existing_count": 0,
                "excluded_count": 0,
                "skipped_reason": "locked",
            }

        result = CompetitorRankingService(session, log=logger).calculate_for_scrape_run(run_uuid)
        return {
            "scrape_run_id": str(result.scrape_run_id),
            "formula_version": result.formula_version,
            "created_count": result.created_count,
            "skipped_existing_count": result.skipped_existing_count,
            "excluded_count": result.excluded_count,
            "skipped_reason": result.skipped_reason,
        }
    finally:
        session.close()


def _try_advisory_lock(session, key: str) -> bool:
    lock_id = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:15], 16)
    try:
        return bool(session.execute(select(func.pg_try_advisory_xact_lock(lock_id))).scalar_one())
    except SQLAlchemyError:
        session.rollback()
        return True
