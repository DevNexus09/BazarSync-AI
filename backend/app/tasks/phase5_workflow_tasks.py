from __future__ import annotations

import hashlib
import logging
from uuid import UUID

from celery.exceptions import Ignore
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.async_runner import run_async
from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.competitor_event import CompetitorEvent
from app.models.competitor_ranking import CompetitorRanking
from app.models.market_opportunity import MarketOpportunity
from app.models.scrape_run import ScrapeRun
from app.services.competitor_event_service import CompetitorEventService
from app.services.competitor_ranking_service import CompetitorRankingService
from app.services.market_opportunity_service import MarketOpportunityService
from app.services.phase5_realtime_service import Phase5RealtimePublisher
from app.websocket.socket_events import RealtimeEventType

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="phase5.run_analysis_workflow",
    autoretry_for=(SQLAlchemyError, RuntimeError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def run_phase5_analysis_workflow_task(self, scrape_run_id: str) -> dict[str, int | str | None]:
    try:
        run_uuid = UUID(scrape_run_id)
    except ValueError as exc:
        logger.warning("Invalid scrape_run_id for phase5 workflow: %s", scrape_run_id)
        raise Ignore() from exc

    session = SessionLocal()
    lock_id: int | None = None
    try:
        lock_id = _lock_id(f"phase5-workflow:{run_uuid}")
        if not _try_advisory_lock(session, lock_id):
            logger.info("phase5_workflow_duplicate_skipped scrape_run_id=%s reason=locked", run_uuid)
            return {"scrape_run_id": scrape_run_id, "skipped_reason": "locked", "events": 0, "rankings": 0, "opportunities": 0}

        scrape_run = session.get(ScrapeRun, run_uuid)
        if not scrape_run or scrape_run.status != "COMPLETED":
            logger.info(
                "phase5_workflow_skipped scrape_run_id=%s reason=not_completed status=%s",
                run_uuid,
                scrape_run.status if scrape_run else None,
            )
            return {"scrape_run_id": scrape_run_id, "skipped_reason": "not_completed", "events": 0, "rankings": 0, "opportunities": 0}

        event_result = CompetitorEventService(session, log=logger).generate_for_scrape_run(run_uuid)
        ranking_result = CompetitorRankingService(session, log=logger).calculate_for_scrape_run(run_uuid)
        opportunity_result = MarketOpportunityService(session, log=logger).generate_for_scrape_run(run_uuid)

        publish_counts = run_async(_publish_phase5_updates(run_uuid))
        logger.info(
            "phase5_workflow_complete scrape_run_id=%s events=%s rankings=%s opportunities=%s published=%s",
            run_uuid,
            event_result.generated_count,
            ranking_result.created_count,
            opportunity_result.created_count,
            publish_counts,
        )
        return {
            "scrape_run_id": str(run_uuid),
            "skipped_reason": None,
            "events": event_result.generated_count,
            "rankings": ranking_result.created_count,
            "opportunities": opportunity_result.created_count,
            "published": publish_counts,
        }
    finally:
        if lock_id is not None:
            _release_advisory_lock(session, lock_id)
        session.close()


async def _publish_phase5_updates(scrape_run_id: UUID) -> int:
    session = SessionLocal()
    publisher = Phase5RealtimePublisher(logger)
    published = 0
    try:
        scrape_run = session.get(ScrapeRun, scrape_run_id)
        if not scrape_run:
            return 0
        seller_id = scrape_run.seller_id
        product_id = scrape_run.product_id
        snapshot_count = scrape_run.snapshot_count or 0
        if await publisher.publish(
            event=RealtimeEventType.COMPETITOR_SNAPSHOT_CREATED,
            seller_id=seller_id,
            product_id=product_id,
            data={"scrape_run_id": str(scrape_run.id), "snapshot_count": snapshot_count},
            occurred_at=scrape_run.completed_at or scrape_run.finished_at or scrape_run.created_at,
        ):
            published += 1

        event_count = session.execute(select(func.count()).select_from(CompetitorEvent).where(CompetitorEvent.scrape_run_id == scrape_run_id)).scalar_one()
        if await publisher.publish(
            event=RealtimeEventType.COMPETITOR_EVENT_CREATED,
            seller_id=seller_id,
            product_id=product_id,
            data={"scrape_run_id": str(scrape_run.id), "event_count": event_count},
        ):
            published += 1

        ranking_count = session.execute(select(func.count()).select_from(CompetitorRanking).where(CompetitorRanking.scrape_run_id == scrape_run_id)).scalar_one()
        if await publisher.publish(
            event=RealtimeEventType.COMPETITOR_RANKINGS_UPDATED,
            seller_id=seller_id,
            product_id=product_id,
            data={"scrape_run_id": str(scrape_run.id), "ranking_count": ranking_count},
        ):
            published += 1

        opportunity_count = session.execute(select(func.count()).select_from(MarketOpportunity).where(MarketOpportunity.scrape_run_id == scrape_run_id)).scalar_one()
        if await publisher.publish(
            event=RealtimeEventType.MARKET_OPPORTUNITY_CREATED,
            seller_id=seller_id,
            product_id=product_id,
            data={"scrape_run_id": str(scrape_run.id), "opportunity_count": opportunity_count},
        ):
            published += 1

        if await publisher.publish(
            event=RealtimeEventType.COMPETITOR_SUMMARY_UPDATED,
            seller_id=seller_id,
            product_id=product_id,
            data={"scrape_run_id": str(scrape_run.id)},
        ):
            published += 1
        return published
    finally:
        session.close()


def _lock_id(key: str) -> int:
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:15], 16)


def _try_advisory_lock(session, lock_id: int) -> bool:
    try:
        return bool(session.execute(select(func.pg_try_advisory_lock(lock_id))).scalar_one())
    except SQLAlchemyError:
        session.rollback()
        return True


def _release_advisory_lock(session, lock_id: int) -> None:
    try:
        session.execute(select(func.pg_advisory_unlock(lock_id))).scalar_one_or_none()
    except SQLAlchemyError:
        session.rollback()
