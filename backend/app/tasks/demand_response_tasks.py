from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from uuid import UUID

from celery.exceptions import Ignore
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.celery_app import celery_app
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.seller import Seller
from app.services.pooled_elasticity_service import PooledElasticityService

logger = logging.getLogger(__name__)
# Pooling needs the training window plus the out-of-time holdout.
WINDOW_DAYS = 120


@celery_app.task(
    bind=True,
    name="demand_response.fit_pooled_elasticity",
    autoretry_for=(SQLAlchemyError,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def fit_pooled_elasticity_task(self, *, seller_id: str | None = None) -> dict[str, int | str]:
    if not settings.demand_response_pooling_enabled:
        return {"skipped_reason": "disabled"}
    try:
        seller_uuid = UUID(seller_id) if seller_id else None
    except ValueError as exc:
        raise Ignore() from exc
    as_of = datetime.now(timezone.utc).date()
    session = SessionLocal()
    totals: dict[str, int | str] = {"sellers": 0, "estimates": 0, "locked": 0}
    try:
        seller_ids = [seller_uuid] if seller_uuid else list(session.execute(select(Seller.id)).scalars())
        for current in seller_ids:
            if not _try_lock(session, f"pooled-elasticity:{current}:{as_of}"):
                totals["locked"] = int(totals["locked"]) + 1
                continue
            result = PooledElasticityService(session).fit_for_seller(seller_id=current, as_of_date=as_of, window_days=WINDOW_DAYS)
            totals["sellers"] = int(totals["sellers"]) + 1
            totals["estimates"] = int(totals["estimates"]) + result["estimates"]
            session.commit()  # releases the transaction-scoped advisory lock
        logger.info("pooled_elasticity_completed %s", totals)
        return totals
    finally:
        session.close()


def _try_lock(session, key: str) -> bool:
    lock_id = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:15], 16)
    return bool(session.execute(select(func.pg_try_advisory_xact_lock(lock_id))).scalar_one())
