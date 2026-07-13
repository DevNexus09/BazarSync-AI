from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID
from uuid import uuid4

from celery import chain
from celery.exceptions import Ignore
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.celery_app import celery_app
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.dead_stock_assessment import DeadStockAssessment, DeadStockClassification, DeadStockRiskLevel
from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryAction
from app.models.product import Product
from app.models.rag_memory import RagMemorySourceType
from app.models.telegram_inventory_alert import TelegramInventoryAlert, TelegramInventoryAlertStatus, TelegramInventoryAlertType
from app.repositories.dead_stock_capital_recovery_repository import DeadStockCapitalRecoveryRepository
from app.repositories.dead_stock_recovery_repository import DeadStockRecoveryRepository
from app.repositories.telegram_inventory_alert_repository import TelegramInventoryAlertRepository
from app.services.dead_stock_capital_recovery_service import DeadStockCapitalRecoveryService
from app.services.dead_stock_dashboard_service import DeadStockDashboardService
from app.services.dead_stock_recovery_service import DeadStockRecoveryService
from app.services.rag_index_outbox_service import RagIndexOutboxService
from app.tasks.dead_stock_tasks import assess_dead_stock_task
from app.tasks.inventory_aging_tasks import calculate_inventory_aging_task
from app.tasks.inventory_history_tasks import capture_daily_inventory_snapshots_task
from app.tasks.sales_velocity_tasks import calculate_daily_sales_velocity_task
from app.tasks.telegram_inventory_alert_tasks import enqueue_due_telegram_inventory_alerts_task

logger = logging.getLogger(__name__)

RECALCULATION_REASONS = {
    "inventory_receipt",
    "inventory_adjustment",
    "completed_sale",
    "return",
    "product_cost_update",
    "marketplace_fee_update",
    "pricing_policy_update",
    "visibility_metric_update",
    "recommendation_acknowledged",
    "recommendation_dismissed",
}

_LAST_ENQUEUED_AT: dict[tuple[str, str], datetime] = {}


@celery_app.task(name="dead_stock.daily_workflow")
def run_daily_dead_stock_workflow(
    *,
    batch_size: int = 500,
    as_of_date: str | None = None,
    seller_id: str | None = None,
) -> dict[str, str | None]:
    _validate_scope(seller_id=seller_id, product_id=None, as_of_date=as_of_date)
    workflow = _phase9_workflow_chain(
        batch_size=batch_size,
        as_of_date=as_of_date,
        seller_id=seller_id,
        product_id=None,
    )
    result = workflow.apply_async()
    logger.info(
        "dead_stock_daily_workflow_enqueued workflow_id=%s seller_id=%s as_of_date=%s",
        result.id,
        seller_id,
        as_of_date,
    )
    return {"workflow_id": result.id, "seller_id": seller_id, "as_of_date": as_of_date}


@celery_app.task(name="dead_stock.recalculate_product_workflow")
def recalculate_product_dead_stock_workflow_task(
    *,
    seller_id: str,
    product_id: str,
    batch_size: int = 1,
    as_of_date: str | None = None,
    reason: str | None = None,
) -> dict[str, str | None]:
    _validate_scope(seller_id=seller_id, product_id=product_id, as_of_date=as_of_date)
    if reason and reason not in RECALCULATION_REASONS:
        logger.info(
            "dead_stock_recalculation_ignored seller_id=%s product_id=%s reason=%s",
            seller_id,
            product_id,
            reason,
        )
        return {"workflow_id": None, "seller_id": seller_id, "product_id": product_id, "reason": reason}
    workflow = _phase9_workflow_chain(
        batch_size=batch_size,
        as_of_date=as_of_date,
        seller_id=seller_id,
        product_id=product_id,
    )
    result = workflow.apply_async()
    logger.info(
        "dead_stock_product_workflow_enqueued workflow_id=%s seller_id=%s product_id=%s reason=%s",
        result.id,
        seller_id,
        product_id,
        reason,
    )
    return {"workflow_id": result.id, "seller_id": seller_id, "product_id": product_id, "reason": reason}


@celery_app.task(
    bind=True,
    name="dead_stock.generate_recovery_recommendations_batch",
    autoretry_for=(SQLAlchemyError, RuntimeError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def generate_dead_stock_recovery_recommendations_batch_task(
    self,
    *,
    batch_size: int = 500,
    seller_id: str | None = None,
    product_id: str | None = None,
) -> dict[str, int | str | None]:
    del self
    seller_uuid, product_uuid, _ = _parse_scope(seller_id=seller_id, product_id=product_id, as_of_date=None)
    session = SessionLocal()
    created = skipped = failed = 0
    try:
        service = DeadStockRecoveryService(session)
        readiness_repo = DeadStockRecoveryRepository(session)
        for current_seller_id, current_product_id in _iter_recovery_product_ids(
            session,
            batch_size=batch_size,
            seller_id=seller_uuid,
            product_id=product_uuid,
        ):
            try:
                if readiness_repo.latest_assessment(seller_id=current_seller_id, product_id=current_product_id) is None:
                    skipped += 1
                    continue
                _, was_created = service.generate_for_product(
                    seller_id=current_seller_id,
                    product_id=current_product_id,
                )
                created += int(was_created)
                skipped += int(not was_created)
            except Exception:
                failed += 1
                session.rollback()
                logger.warning(
                    "dead_stock_recovery_generation_failed seller_id=%s product_id=%s",
                    current_seller_id,
                    current_product_id,
                    exc_info=True,
                )
        logger.info(
            "dead_stock_recovery_generation_batch_completed created=%s skipped=%s failed=%s seller_id=%s product_id=%s",
            created,
            skipped,
            failed,
            seller_id,
            product_id,
        )
        return {"created_count": created, "skipped_count": skipped, "failed_count": failed, "seller_id": seller_id, "product_id": product_id}
    finally:
        session.close()


@celery_app.task(
    bind=True,
    name="dead_stock.estimate_capital_recovery_batch",
    autoretry_for=(SQLAlchemyError, RuntimeError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def estimate_dead_stock_capital_recovery_batch_task(
    self,
    *,
    batch_size: int = 500,
    seller_id: str | None = None,
    product_id: str | None = None,
) -> dict[str, int | str | None]:
    del self
    seller_uuid, product_uuid, _ = _parse_scope(seller_id=seller_id, product_id=product_id, as_of_date=None)
    session = SessionLocal()
    created = skipped = failed = 0
    try:
        service = DeadStockCapitalRecoveryService(session)
        for current_seller_id, current_product_id in _iter_recovery_product_ids(
            session,
            batch_size=batch_size,
            seller_id=seller_uuid,
            product_id=product_uuid,
        ):
            try:
                existing = service.latest_estimate(seller_id=current_seller_id, product_id=current_product_id)
                latest_recommendation = service.latest_recovery_recommendation(
                    seller_id=current_seller_id,
                    product_id=current_product_id,
                )
                if latest_recommendation is None:
                    skipped += 1
                    continue
                if (
                    existing is not None
                    and existing.recovery_recommendation_id == latest_recommendation.id
                    and existing.calculation_version == settings.dead_stock_capital_recovery_formula_version
                ):
                    skipped += 1
                    continue
                service.estimate_for_product(seller_id=current_seller_id, product_id=current_product_id)
                created += 1
            except Exception:
                failed += 1
                session.rollback()
                logger.warning(
                    "dead_stock_capital_recovery_estimation_failed seller_id=%s product_id=%s",
                    current_seller_id,
                    current_product_id,
                    exc_info=True,
                )
        logger.info(
            "dead_stock_capital_recovery_batch_completed created=%s skipped=%s failed=%s seller_id=%s product_id=%s",
            created,
            skipped,
            failed,
            seller_id,
            product_id,
        )
        return {"created_count": created, "skipped_count": skipped, "failed_count": failed, "seller_id": seller_id, "product_id": product_id}
    finally:
        session.close()


@celery_app.task(name="dead_stock.refresh_dashboard")
def refresh_dead_stock_dashboard_task(
    *,
    seller_id: str | None = None,
    product_id: str | None = None,
) -> dict[str, int | str | None]:
    seller_uuid, product_uuid, _ = _parse_scope(seller_id=seller_id, product_id=product_id, as_of_date=None)
    del product_uuid
    session = SessionLocal()
    refreshed = failed = 0
    try:
        service = DeadStockDashboardService(session)
        seller_ids = [seller_uuid] if seller_uuid else _seller_ids_with_inventory(session)
        for current_seller_id in seller_ids:
            try:
                service.summary(seller_id=current_seller_id)
                refreshed += 1
            except Exception:
                failed += 1
                session.rollback()
                logger.warning(
                    "dead_stock_dashboard_refresh_failed seller_id=%s",
                    current_seller_id,
                    exc_info=True,
                )
        logger.info(
            "dead_stock_dashboard_refresh_completed refreshed=%s failed=%s seller_id=%s product_id=%s",
            refreshed,
            failed,
            seller_id,
            product_id,
        )
        return {"refreshed_count": refreshed, "failed_count": failed, "seller_id": seller_id, "product_id": product_id}
    finally:
        session.close()


@celery_app.task(name="dead_stock.generate_phase9_alerts")
def generate_dead_stock_phase9_alerts_task(
    *,
    seller_id: str | None = None,
    product_id: str | None = None,
) -> dict[str, int | str | None]:
    seller_uuid, product_uuid, _ = _parse_scope(seller_id=seller_id, product_id=product_id, as_of_date=None)
    if not settings.dead_stock_alerts_enabled:
        logger.info(
            "dead_stock_phase9_alerts_skipped reason=disabled seller_id=%s product_id=%s",
            seller_id,
            product_id,
        )
        return {"created_count": 0, "skipped_count": 1, "failed_count": 0, "seller_id": seller_id, "product_id": product_id}
    session = SessionLocal()
    created = skipped = failed = 0
    try:
        recovery_repo = DeadStockRecoveryRepository(session)
        capital_repo = DeadStockCapitalRecoveryRepository(session)
        alert_repo = TelegramInventoryAlertRepository(session)
        for current_seller_id, current_product_id in _iter_recovery_product_ids(
            session,
            batch_size=500,
            seller_id=seller_uuid,
            product_id=product_uuid,
        ):
            try:
                connection = alert_repo.get_connection(current_seller_id)
                if not connection or not connection.is_connected or not connection.telegram_chat_id:
                    skipped += 1
                    continue
                product = recovery_repo.product(seller_id=current_seller_id, product_id=current_product_id)
                assessment = recovery_repo.latest_assessment(seller_id=current_seller_id, product_id=current_product_id)
                if product is None or assessment is None:
                    skipped += 1
                    continue
                previous = _previous_dead_stock_assessment(session, assessment)
                recommendation = recovery_repo.latest_recommendation(seller_id=current_seller_id, product_id=current_product_id)
                capital = capital_repo.latest_estimate(seller_id=current_seller_id, product_id=current_product_id)
                for alert in _phase9_alert_candidates(
                    product=product,
                    assessment=assessment,
                    previous=previous,
                    recommendation=recommendation,
                    capital=capital,
                    alert_repo=alert_repo,
                ):
                    saved, was_created = alert_repo.add_idempotent(alert)
                    if was_created:
                        RagIndexOutboxService(session).enqueue_upsert(
                            seller_id=saved.seller_id,
                            source_type=RagMemorySourceType.ALERT,
                            source_id=str(saved.id),
                            product_id=saved.product_id,
                            source_updated_at=saved.created_at,
                        )
                        session.commit()
                    del saved
                    created += int(was_created)
                    skipped += int(not was_created)
            except Exception:
                failed += 1
                session.rollback()
                logger.warning(
                    "dead_stock_phase9_alert_generation_failed seller_id=%s product_id=%s",
                    current_seller_id,
                    current_product_id,
                    exc_info=True,
                )
        logger.info(
            "dead_stock_phase9_alert_generation_completed created=%s skipped=%s failed=%s seller_id=%s product_id=%s",
            created,
            skipped,
            failed,
            seller_id,
            product_id,
        )
        return {"created_count": created, "skipped_count": skipped, "failed_count": failed, "seller_id": seller_id, "product_id": product_id}
    finally:
        session.close()


def enqueue_dead_stock_recalculation(
    *,
    seller_id: UUID,
    product_id: UUID,
    reason: str,
) -> bool:
    if reason not in RECALCULATION_REASONS:
        logger.info(
            "dead_stock_recalculation_not_relevant seller_id=%s product_id=%s reason=%s",
            seller_id,
            product_id,
            reason,
        )
        return False
    now = datetime.now(timezone.utc)
    key = (str(seller_id), str(product_id))
    previous = _LAST_ENQUEUED_AT.get(key)
    if previous and previous > now - timedelta(seconds=settings.dead_stock_workflow_debounce_seconds):
        logger.info(
            "dead_stock_recalculation_debounced seller_id=%s product_id=%s reason=%s",
            seller_id,
            product_id,
            reason,
        )
        return False
    _LAST_ENQUEUED_AT[key] = now
    try:
        recalculate_product_dead_stock_workflow_task.delay(
            seller_id=str(seller_id),
            product_id=str(product_id),
            reason=reason,
        )
        return True
    except Exception:
        logger.warning(
            "dead_stock_recalculation_enqueue_failed seller_id=%s product_id=%s reason=%s",
            seller_id,
            product_id,
            reason,
            exc_info=True,
        )
        return False


def _phase9_workflow_chain(
    *,
    batch_size: int,
    as_of_date: str | None,
    seller_id: str | None,
    product_id: str | None,
):
    kwargs = {"batch_size": batch_size, "seller_id": seller_id, "product_id": product_id}
    dated_kwargs = {**kwargs, "as_of_date": as_of_date}
    return chain(
        capture_daily_inventory_snapshots_task.si(**kwargs),
        calculate_inventory_aging_task.si(**dated_kwargs),
        calculate_daily_sales_velocity_task.si(**dated_kwargs),
        assess_dead_stock_task.si(**dated_kwargs),
        generate_dead_stock_recovery_recommendations_batch_task.si(**kwargs),
        estimate_dead_stock_capital_recovery_batch_task.si(**kwargs),
        refresh_dead_stock_dashboard_task.si(seller_id=seller_id, product_id=product_id),
        generate_dead_stock_phase9_alerts_task.si(seller_id=seller_id, product_id=product_id),
        enqueue_due_telegram_inventory_alerts_task.si(),
    )


def _iter_recovery_product_ids(
    session,
    *,
    batch_size: int,
    seller_id: UUID | None,
    product_id: UUID | None,
):
    offset = 0
    while True:
        statement = (
            select(Product.seller_id, Product.id)
            .where(Product.stock_quantity > 0)
            .order_by(Product.created_at.asc(), Product.id.asc())
            .limit(batch_size)
            .offset(offset)
        )
        if seller_id:
            statement = statement.where(Product.seller_id == seller_id)
        if product_id:
            statement = statement.where(Product.id == product_id)
        rows = session.execute(statement).all()
        if not rows:
            break
        for row in rows:
            yield row.seller_id, row.id
        offset += batch_size


def _seller_ids_with_inventory(session) -> list[UUID]:
    rows = session.execute(
        select(Product.seller_id)
        .where(Product.stock_quantity > 0)
        .distinct()
        .order_by(Product.seller_id.asc())
    ).all()
    return [row.seller_id for row in rows]


def _previous_dead_stock_assessment(session, assessment: DeadStockAssessment) -> DeadStockAssessment | None:
    return session.execute(
        select(DeadStockAssessment)
        .where(
            DeadStockAssessment.seller_id == assessment.seller_id,
            DeadStockAssessment.product_id == assessment.product_id,
            DeadStockAssessment.id != assessment.id,
        )
        .order_by(
            DeadStockAssessment.as_of_date.desc(),
            DeadStockAssessment.assessed_at.desc(),
            DeadStockAssessment.id.desc(),
        )
        .limit(1)
    ).scalar_one_or_none()


def _phase9_alert_candidates(
    *,
    product,
    assessment: DeadStockAssessment,
    previous: DeadStockAssessment | None,
    recommendation,
    capital,
    alert_repo: TelegramInventoryAlertRepository,
) -> list[TelegramInventoryAlert]:
    candidates: list[TelegramInventoryAlertType] = []
    if assessment.classification == DeadStockClassification.DEAD_STOCK and getattr(previous, "classification", None) != DeadStockClassification.DEAD_STOCK:
        candidates.append(TelegramInventoryAlertType.DEAD_STOCK_CLASSIFIED)
    if assessment.risk_level == DeadStockRiskLevel.CRITICAL and getattr(previous, "risk_level", None) != DeadStockRiskLevel.CRITICAL:
        candidates.append(TelegramInventoryAlertType.DEAD_STOCK_CRITICAL_RISK)
    locked_capital = _decimal_or_none(getattr(capital, "locked_capital", None))
    if locked_capital is not None and locked_capital >= Decimal(str(settings.dead_stock_alert_locked_capital_threshold)):
        candidates.append(TelegramInventoryAlertType.DEAD_STOCK_LOCKED_CAPITAL)
    if recommendation and getattr(recommendation, "primary_action", None) not in {DeadStockRecoveryAction.HOLD, DeadStockRecoveryAction.MANUAL_REVIEW}:
        candidates.append(TelegramInventoryAlertType.DEAD_STOCK_RECOVERY_AVAILABLE)
    age = getattr(assessment, "inventory_age_days", None)
    if (
        assessment.classification == DeadStockClassification.DEAD_STOCK
        and age is not None
        and age >= settings.dead_stock_inventory_age_threshold_days + settings.dead_stock_alert_additional_age_days
    ):
        candidates.append(TelegramInventoryAlertType.DEAD_STOCK_AGED)

    alerts: list[TelegramInventoryAlert] = []
    for alert_type in candidates:
        if _phase9_alert_in_cooldown(alert_repo, assessment=assessment, alert_type=alert_type):
            continue
        metadata = _phase9_alert_metadata(
            assessment=assessment,
            previous=previous,
            recommendation=recommendation,
            capital=capital,
            alert_type=alert_type,
        )
        alerts.append(
            TelegramInventoryAlert(
                id=uuid4(),
                seller_id=assessment.seller_id,
                product_id=assessment.product_id,
                risk_assessment_id=None,
                reorder_recommendation_id=None,
                alert_type=alert_type,
                dedupe_key=_phase9_alert_dedupe_key(assessment=assessment, recommendation=recommendation, alert_type=alert_type, metadata=metadata),
                status=TelegramInventoryAlertStatus.PENDING,
                alert_metadata=metadata,
                message_text=_phase9_alert_message(product=product, assessment=assessment, recommendation=recommendation, capital=capital),
            )
        )
    return alerts


def _phase9_alert_in_cooldown(
    alert_repo: TelegramInventoryAlertRepository,
    *,
    assessment: DeadStockAssessment,
    alert_type: TelegramInventoryAlertType,
) -> bool:
    recent = alert_repo.latest_sent(
        seller_id=assessment.seller_id,
        product_id=assessment.product_id,
        alert_type=alert_type,
    )
    if not recent or not recent.sent_at:
        return False
    return recent.sent_at > datetime.now(timezone.utc) - timedelta(hours=settings.dead_stock_alert_cooldown_hours)


def _phase9_alert_metadata(*, assessment: DeadStockAssessment, previous, recommendation, capital, alert_type: TelegramInventoryAlertType) -> dict[str, str | None]:
    return {
        "phase": "9",
        "alert_type": alert_type.value,
        "classification": getattr(assessment.classification, "value", str(assessment.classification)),
        "previous_classification": getattr(getattr(previous, "classification", None), "value", None),
        "risk_level": getattr(assessment.risk_level, "value", str(assessment.risk_level)),
        "previous_risk_level": getattr(getattr(previous, "risk_level", None), "value", None),
        "as_of_date": assessment.as_of_date.isoformat(),
        "calculation_version": assessment.calculation_version,
        "dead_stock_assessment_id": str(assessment.id),
        "recovery_recommendation_id": str(getattr(recommendation, "id", "")) if recommendation else None,
        "capital_recovery_estimate_id": str(getattr(capital, "id", "")) if capital else None,
        "locked_capital": str(getattr(capital, "locked_capital", "")) if capital else None,
        "estimated_recovered_cash": str(getattr(capital, "gross_recovered_cash", "")) if capital else None,
    }


def _phase9_alert_dedupe_key(*, assessment: DeadStockAssessment, recommendation, alert_type: TelegramInventoryAlertType, metadata: dict[str, str | None]) -> str:
    if alert_type == TelegramInventoryAlertType.DEAD_STOCK_RECOVERY_AVAILABLE:
        changing_part = metadata.get("recovery_recommendation_id") or "none"
    elif alert_type == TelegramInventoryAlertType.DEAD_STOCK_LOCKED_CAPITAL:
        changing_part = str(settings.dead_stock_alert_locked_capital_threshold)
    elif alert_type == TelegramInventoryAlertType.DEAD_STOCK_AGED:
        changing_part = str(settings.dead_stock_inventory_age_threshold_days + settings.dead_stock_alert_additional_age_days)
    else:
        changing_part = assessment.calculation_version
    del recommendation
    return f"{assessment.seller_id}:{assessment.product_id}:{alert_type.value}:{changing_part}"


def _phase9_alert_message(*, product, assessment: DeadStockAssessment, recommendation, capital) -> str:
    currency = (getattr(capital, "evidence", None) or {}).get("currency", settings.dead_stock_capital_recovery_currency) if capital else settings.dead_stock_capital_recovery_currency
    locked = _money_label(getattr(capital, "locked_capital", None), currency)
    recovered = _money_label(getattr(capital, "gross_recovered_cash", None), currency)
    action = getattr(getattr(recommendation, "primary_action", None), "value", None) or "Manual review"
    return "\n".join(
        [
            "Dead Stock Alert",
            "",
            f"Product: {getattr(product, 'title', 'Product')}",
            f"Available Stock: {getattr(product, 'stock_quantity', 0)} units",
            f"Inventory Age: {getattr(assessment, 'inventory_age_days', None) or 'Unknown'} days",
            f"Last Sale: {getattr(assessment, 'days_since_last_sale', None) or 'Unknown'} days ago",
            f"Locked Capital: {locked} estimate",
            f"Risk: {getattr(assessment.risk_level, 'value', assessment.risk_level)}",
            "",
            f"Recommended Action: {action}",
            f"Suggested Recovery: {recovered} estimated cash recovery",
        ]
    )


def _money_label(value, currency: str) -> str:
    amount = _decimal_or_none(value)
    if amount is None:
        return "Unavailable"
    return f"{currency} {amount.quantize(Decimal('0.01'))}"


def _decimal_or_none(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _parse_scope(*, seller_id: str | None, product_id: str | None, as_of_date: str | None):
    try:
        seller_uuid = UUID(seller_id) if seller_id else None
        product_uuid = UUID(product_id) if product_id else None
        as_of = date.fromisoformat(as_of_date) if as_of_date else None
        return seller_uuid, product_uuid, as_of
    except ValueError as exc:
        logger.warning(
            "invalid_dead_stock_workflow_scope seller_id=%s product_id=%s as_of_date=%s",
            seller_id,
            product_id,
            as_of_date,
        )
        raise Ignore() from exc


def _validate_scope(*, seller_id: str | None, product_id: str | None, as_of_date: str | None) -> None:
    _parse_scope(seller_id=seller_id, product_id=product_id, as_of_date=as_of_date)
