from __future__ import annotations

import logging
from datetime import date
from uuid import UUID

from celery import chain
from celery.exceptions import Ignore

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.inventory_intelligence_service import InventoryIntelligenceService
from app.tasks.inventory_history_tasks import capture_daily_inventory_snapshots_task
from app.tasks.sales_velocity_tasks import calculate_daily_sales_velocity_task
from app.tasks.stockout_prediction_tasks import calculate_stockout_predictions_task
from app.tasks.reorder_recommendation_tasks import calculate_reorder_recommendations_task
from app.tasks.inventory_risk_tasks import calculate_inventory_risks_task
from app.tasks.telegram_inventory_alert_tasks import enqueue_due_telegram_inventory_alerts_task

logger = logging.getLogger(__name__)


@celery_app.task(name="inventory_intelligence.daily_workflow")
def run_daily_inventory_intelligence_workflow(
    *,
    batch_size: int = 500,
    as_of_date: str | None = None,
    seller_id: str | None = None,
) -> dict[str, str | None]:
    _validate_scope(seller_id=seller_id, product_id=None, as_of_date=as_of_date)
    workflow = _workflow_chain(
        batch_size=batch_size,
        as_of_date=as_of_date,
        seller_id=seller_id,
        product_id=None,
    )
    result = workflow.apply_async()
    logger.info(
        "inventory_intelligence_daily_workflow_enqueued workflow_id=%s seller_id=%s as_of_date=%s",
        result.id,
        seller_id,
        as_of_date,
    )
    return {"workflow_id": result.id, "seller_id": seller_id, "as_of_date": as_of_date}


@celery_app.task(name="inventory_intelligence.recalculate_product")
def recalculate_product_inventory_intelligence_task(
    *,
    seller_id: str,
    product_id: str,
    batch_size: int = 1,
    as_of_date: str | None = None,
    reason: str | None = None,
) -> dict[str, str | None]:
    _validate_scope(seller_id=seller_id, product_id=product_id, as_of_date=as_of_date)
    workflow = _workflow_chain(
        batch_size=batch_size,
        as_of_date=as_of_date,
        seller_id=seller_id,
        product_id=product_id,
    )
    result = workflow.apply_async()
    logger.info(
        "inventory_intelligence_product_workflow_enqueued workflow_id=%s seller_id=%s product_id=%s reason=%s",
        result.id,
        seller_id,
        product_id,
        reason,
    )
    return {
        "workflow_id": result.id,
        "seller_id": seller_id,
        "product_id": product_id,
        "as_of_date": as_of_date,
        "reason": reason,
    }


@celery_app.task(name="inventory_intelligence.generate_alerts_for_latest_risks")
def generate_alerts_for_latest_inventory_risks_task(
    *,
    seller_id: str | None = None,
    product_id: str | None = None,
    as_of_date: str | None = None,
) -> dict[str, int | str | None]:
    try:
        seller_uuid = UUID(seller_id) if seller_id else None
        product_uuid = UUID(product_id) if product_id else None
        as_of = date.fromisoformat(as_of_date) if as_of_date else None
    except ValueError as exc:
        logger.warning(
            "Invalid latest-risk alert generation scope seller_id=%s product_id=%s as_of_date=%s",
            seller_id,
            product_id,
            as_of_date,
        )
        raise Ignore() from exc

    session = SessionLocal()
    try:
        result = InventoryIntelligenceService(session).generate_alerts_for_latest_risks(
            seller_id=seller_uuid,
            product_id=product_uuid,
            as_of_date=as_of,
        )
        logger.info(
            "inventory_intelligence_alert_generation_completed seller_id=%s product_id=%s created=%s skipped=%s risks=%s",
            seller_id,
            product_id,
            result["created_count"],
            result["skipped_count"],
            result["risk_count"],
        )
        return {**result, "seller_id": seller_id, "product_id": product_id}
    finally:
        session.close()


def enqueue_product_recalculation(
    *,
    seller_id: UUID,
    product_id: UUID,
    reason: str,
) -> None:
    try:
        recalculate_product_inventory_intelligence_task.delay(
            seller_id=str(seller_id),
            product_id=str(product_id),
            reason=reason,
        )
    except Exception:
        logger.warning(
            "inventory_intelligence_recalculation_enqueue_failed seller_id=%s product_id=%s reason=%s",
            seller_id,
            product_id,
            reason,
            exc_info=True,
        )


def _workflow_chain(
    *,
    batch_size: int,
    as_of_date: str | None,
    seller_id: str | None,
    product_id: str | None,
):
    kwargs = {
        "batch_size": batch_size,
        "seller_id": seller_id,
        "product_id": product_id,
    }
    dated_kwargs = {**kwargs, "as_of_date": as_of_date}
    return chain(
        capture_daily_inventory_snapshots_task.si(**kwargs),
        calculate_daily_sales_velocity_task.si(**dated_kwargs),
        calculate_stockout_predictions_task.si(**dated_kwargs),
        calculate_reorder_recommendations_task.si(**dated_kwargs),
        calculate_inventory_risks_task.si(**dated_kwargs),
        generate_alerts_for_latest_inventory_risks_task.si(
            seller_id=seller_id,
            product_id=product_id,
            as_of_date=as_of_date,
        ),
        enqueue_due_telegram_inventory_alerts_task.si(),
    )


def _validate_scope(*, seller_id: str | None, product_id: str | None, as_of_date: str | None) -> None:
    try:
        if seller_id:
            UUID(seller_id)
        if product_id:
            UUID(product_id)
        if as_of_date:
            date.fromisoformat(as_of_date)
    except ValueError as exc:
        logger.warning(
            "Invalid inventory intelligence workflow scope seller_id=%s product_id=%s as_of_date=%s",
            seller_id,
            product_id,
            as_of_date,
        )
        raise Ignore() from exc
