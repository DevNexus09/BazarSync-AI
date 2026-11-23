from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Protocol
from uuid import UUID, uuid4

from app.core.config import settings
from app.models.inventory_risk import InventoryRiskAssessment, InventoryRiskLevel
from app.models.reorder_recommendation import ReorderRecommendationAction
from app.models.stockout_prediction import StockoutPredictionStatus
from app.models.rag_memory import RagMemorySourceType
from app.models.telegram_inventory_alert import (
    TelegramInventoryAlert,
    TelegramInventoryAlertStatus,
    TelegramInventoryAlertType,
)
from app.repositories.telegram_inventory_alert_repository import TelegramInventoryAlertRepository
from app.services.telegram.inventory_alert_formatter import (
    InventoryAlertMessageContext,
    format_inventory_alert_message,
)
from app.services.telegram.telegram_service import DeliveryStatus, TelegramDeliveryResult, TelegramService
from app.services.rag_index_outbox_service import RagIndexOutboxService

logger = logging.getLogger(__name__)

RISK_ORDER = {
    None: 0,
    InventoryRiskLevel.LOW: 1,
    InventoryRiskLevel.MEDIUM: 2,
    InventoryRiskLevel.HIGH: 3,
    InventoryRiskLevel.CRITICAL: 4,
}


class TelegramInventoryAlertRepositoryProtocol(Protocol):
    def get_risk_with_context(self, risk_assessment_id: UUID) -> InventoryRiskAssessment | None: ...
    def previous_risk(self, assessment: InventoryRiskAssessment) -> InventoryRiskAssessment | None: ...
    def add_idempotent(self, alert: TelegramInventoryAlert) -> tuple[TelegramInventoryAlert, bool]: ...
    def latest_sent(self, *, seller_id: UUID, product_id: UUID, alert_type: TelegramInventoryAlertType, risk_level: str | None = None) -> TelegramInventoryAlert | None: ...
    def get_alert_for_delivery(self, alert_id: UUID) -> TelegramInventoryAlert | None: ...
    def due_alerts(self, *, limit: int = 100) -> list[TelegramInventoryAlert]: ...
    def get_connection(self, seller_id: UUID): ...
    def mark_sending(self, alert: TelegramInventoryAlert) -> bool: ...
    def mark_sent(self, alert: TelegramInventoryAlert, *, sent_at: datetime) -> None: ...
    def mark_failed(self, alert: TelegramInventoryAlert, *, failure_code: str, next_attempt_at: datetime | None, terminal: bool) -> None: ...


@dataclass(frozen=True)
class InventoryAlertGenerationResult:
    created_count: int
    skipped_count: int
    alert_ids: list[str]


@dataclass(frozen=True)
class InventoryAlertDeliveryOutcome:
    alert_id: str
    status: TelegramInventoryAlertStatus
    detail: str | None = None


class TelegramInventoryAlertService:
    def __init__(
        self,
        db=None,
        *,
        repository: TelegramInventoryAlertRepositoryProtocol | None = None,
        telegram_service: TelegramService | None = None,
        log: logging.Logger | None = None,
    ) -> None:
        if repository is None and db is None:
            raise ValueError("Either db or repository is required.")
        self._repository = repository or TelegramInventoryAlertRepository(db)
        self._telegram = telegram_service or TelegramService(logger=log)
        self._log = log or logger

    def generate_for_risk_assessment(self, risk_assessment_id: UUID) -> InventoryAlertGenerationResult:
        assessment = self._repository.get_risk_with_context(risk_assessment_id)
        if not assessment:
            self._log.warning("telegram_inventory_alert_risk_missing risk_assessment_id=%s", risk_assessment_id)
            return InventoryAlertGenerationResult(0, 0, [])
        previous = self._repository.previous_risk(assessment)
        candidates = self._build_candidates(assessment, previous)
        created = skipped = 0
        alert_ids: list[str] = []
        for alert_type in candidates:
            if not self._should_create_alert(assessment, previous, alert_type):
                skipped += 1
                continue
            alert = self._build_alert(assessment, previous, alert_type)
            saved, was_created = self._repository.add_idempotent(alert)
            if was_created and hasattr(self._repository, "_db"):
                RagIndexOutboxService(self._repository._db).enqueue_upsert(
                    seller_id=saved.seller_id,
                    source_type=RagMemorySourceType.ALERT,
                    source_id=str(saved.id),
                    product_id=saved.product_id,
                    source_updated_at=saved.created_at,
                )
                self._repository._db.commit()
            created += int(was_created)
            skipped += int(not was_created)
            alert_ids.append(str(saved.id))
        self._log.info(
            "telegram_inventory_alert_generation risk_assessment_id=%s created=%s skipped=%s",
            risk_assessment_id,
            created,
            skipped,
        )
        return InventoryAlertGenerationResult(created, skipped, alert_ids)

    async def deliver_alert(self, alert_id: UUID) -> InventoryAlertDeliveryOutcome:
        alert = self._repository.get_alert_for_delivery(alert_id)
        if not alert:
            return InventoryAlertDeliveryOutcome(str(alert_id), TelegramInventoryAlertStatus.CANCELLED, "missing_alert")
        if alert.status == TelegramInventoryAlertStatus.SENT:
            return InventoryAlertDeliveryOutcome(str(alert.id), TelegramInventoryAlertStatus.SENT, "already_sent")
        if (alert.attempt_count or 0) >= settings.telegram_inventory_alert_max_attempts:
            self._repository.mark_failed(alert, failure_code="attempt_limit_reached", next_attempt_at=None, terminal=True)
            return InventoryAlertDeliveryOutcome(str(alert.id), TelegramInventoryAlertStatus.CANCELLED, "attempt_limit_reached")

        connection = self._repository.get_connection(alert.seller_id)
        if not connection or not connection.is_connected:
            self._repository.mark_failed(alert, failure_code="telegram_disabled", next_attempt_at=None, terminal=True)
            return InventoryAlertDeliveryOutcome(str(alert.id), TelegramInventoryAlertStatus.CANCELLED, "telegram_disabled")
        if not connection.telegram_chat_id:
            self._repository.mark_failed(alert, failure_code="missing_chat_id", next_attempt_at=None, terminal=True)
            return InventoryAlertDeliveryOutcome(str(alert.id), TelegramInventoryAlertStatus.CANCELLED, "missing_chat_id")
        if not self._repository.mark_sending(alert):
            return InventoryAlertDeliveryOutcome(
                str(alert.id),
                alert.status,
                "already_sent" if alert.status == TelegramInventoryAlertStatus.SENT else "delivery_in_progress",
            )

        message = alert.message_text or self._format_message(alert)
        result = await self._telegram.send_text_message(
            message,
            chat_id=connection.telegram_chat_id,
            prevent_duplicate=True,
            idempotency_key=f"inventory-alert:{alert.dedupe_key}",
            alert_type=alert.alert_type.value,
            product_id=str(alert.product_id),
            recommendation_id=str(alert.reorder_recommendation_id) if alert.reorder_recommendation_id else None,
        )
        return self._apply_delivery_result(alert, result)

    def enqueue_due_deliveries(self, *, limit: int = 100) -> list[str]:
        alerts = self._repository.due_alerts(limit=limit)
        return [str(alert.id) for alert in alerts]

    def _build_candidates(
        self,
        assessment: InventoryRiskAssessment,
        previous: InventoryRiskAssessment | None,
    ) -> list[TelegramInventoryAlertType]:
        candidates: list[TelegramInventoryAlertType] = []
        if assessment.risk_level == InventoryRiskLevel.CRITICAL:
            candidates.append(TelegramInventoryAlertType.CRITICAL_RISK)
        elif assessment.risk_level == InventoryRiskLevel.HIGH:
            candidates.append(TelegramInventoryAlertType.HIGH_RISK)

        if previous and _risk_rank(previous) < RISK_ORDER[InventoryRiskLevel.HIGH] <= _risk_rank(assessment):
            candidates.append(TelegramInventoryAlertType.RISK_ESCALATION)
        if self._is_reorder_deadline_reached(assessment):
            candidates.append(TelegramInventoryAlertType.REORDER_DEADLINE)
        if self._has_material_days_drop(assessment, previous):
            candidates.append(TelegramInventoryAlertType.DAYS_REMAINING_DROP)
        if self._is_out_of_stock(assessment):
            candidates.append(TelegramInventoryAlertType.OUT_OF_STOCK)
        return candidates

    def _should_create_alert(
        self,
        assessment: InventoryRiskAssessment,
        previous: InventoryRiskAssessment | None,
        alert_type: TelegramInventoryAlertType,
    ) -> bool:
        if alert_type in {
            TelegramInventoryAlertType.CRITICAL_RISK,
            TelegramInventoryAlertType.RISK_ESCALATION,
            TelegramInventoryAlertType.REORDER_DEADLINE,
            TelegramInventoryAlertType.DAYS_REMAINING_DROP,
            TelegramInventoryAlertType.OUT_OF_STOCK,
        }:
            return True
        if alert_type == TelegramInventoryAlertType.HIGH_RISK:
            recent = self._repository.latest_sent(
                seller_id=assessment.seller_id,
                product_id=assessment.product_id,
                alert_type=alert_type,
                risk_level=InventoryRiskLevel.HIGH.value,
            )
            if not recent or not recent.sent_at:
                return True
            return recent.sent_at <= _now() - timedelta(hours=settings.telegram_inventory_alert_cooldown_hours)
        return False

    def _build_alert(
        self,
        assessment: InventoryRiskAssessment,
        previous: InventoryRiskAssessment | None,
        alert_type: TelegramInventoryAlertType,
    ) -> TelegramInventoryAlert:
        metadata = self._metadata(assessment, previous, alert_type)
        alert = TelegramInventoryAlert(
            id=uuid4(),
            seller_id=assessment.seller_id,
            product_id=assessment.product_id,
            risk_assessment_id=assessment.id,
            reorder_recommendation_id=assessment.reorder_recommendation_id,
            alert_type=alert_type,
            dedupe_key=self._dedupe_key(assessment, metadata, alert_type),
            status=TelegramInventoryAlertStatus.PENDING,
            alert_metadata=metadata,
            message_text=self._format_message_from_assessment(assessment, alert_type),
        )
        return alert

    def _metadata(
        self,
        assessment: InventoryRiskAssessment,
        previous: InventoryRiskAssessment | None,
        alert_type: TelegramInventoryAlertType,
    ) -> dict[str, str | None]:
        current_days = _days_remaining(assessment)
        previous_days = _days_remaining(previous) if previous else None
        return {
            "risk_level": getattr(assessment.risk_level, "value", None),
            "previous_risk_level": getattr(getattr(previous, "risk_level", None), "value", None),
            "as_of_date": assessment.as_of_date.isoformat(),
            "calculation_version": assessment.calculation_version,
            "current_days_remaining": str(current_days) if current_days is not None else None,
            "previous_days_remaining": str(previous_days) if previous_days is not None else None,
            "alert_type": alert_type.value,
        }

    def _dedupe_key(
        self,
        assessment: InventoryRiskAssessment,
        metadata: dict[str, str | None],
        alert_type: TelegramInventoryAlertType,
    ) -> str:
        recommendation_id = str(assessment.reorder_recommendation_id or "none")
        level = metadata.get("risk_level") or "UNKNOWN"
        version = assessment.calculation_version
        if alert_type == TelegramInventoryAlertType.DAYS_REMAINING_DROP:
            days_bucket = metadata.get("current_days_remaining") or "unknown"
            return f"{assessment.seller_id}:{assessment.product_id}:{alert_type.value}:{level}:{recommendation_id}:{version}:{days_bucket}"
        return f"{assessment.seller_id}:{assessment.product_id}:{alert_type.value}:{level}:{recommendation_id}:{version}"

    def _format_message(self, alert: TelegramInventoryAlert) -> str:
        return self._format_message_from_assessment(alert.risk_assessment, alert.alert_type)

    def _format_message_from_assessment(
        self,
        assessment: InventoryRiskAssessment,
        alert_type: TelegramInventoryAlertType,
    ) -> str:
        product = assessment.product
        prediction = assessment.stockout_prediction
        reorder = assessment.reorder_recommendation
        context = InventoryAlertMessageContext(
            alert_type=alert_type,
            product_name=getattr(product, "title", "Product"),
            current_stock=getattr(prediction, "inventory_position", None),
            daily_sales_rate=getattr(prediction, "daily_sales_rate", None),
            days_remaining=getattr(prediction, "days_remaining", None),
            predicted_stockout_date=getattr(prediction, "predicted_stockout_date", None),
            supplier_lead_time_days=getattr(reorder, "supplier_lead_time_days", None),
            safety_buffer_days=getattr(reorder, "safety_buffer_days", None),
            risk_level=assessment.risk_level,
            recommended_action=getattr(getattr(reorder, "action", None), "value", None),
            recommended_quantity=getattr(reorder, "recommended_quantity", None),
            reorder_deadline=getattr(reorder, "reorder_deadline", None),
            dashboard_url=inventory_dashboard_url(
                settings.inventory_alert_dashboard_base_url,
                product_id=getattr(product, "id", None),
                reorder=getattr(getattr(reorder, "action", None), "value", None) == "REORDER",
            ),
        )
        return format_inventory_alert_message(context)

    def _apply_delivery_result(
        self,
        alert: TelegramInventoryAlert,
        result: TelegramDeliveryResult,
    ) -> InventoryAlertDeliveryOutcome:
        if result.status in {DeliveryStatus.delivered, DeliveryStatus.duplicate}:
            self._repository.mark_sent(alert, sent_at=result.timestamp)
            self._log.info(
                "telegram_inventory_alert_delivery alert_id=%s status=%s",
                alert.id,
                TelegramInventoryAlertStatus.SENT.value,
            )
            return InventoryAlertDeliveryOutcome(str(alert.id), TelegramInventoryAlertStatus.SENT)
        failure_code = _sanitize_failure(result.detail)
        terminal = failure_code in {"invalid_chat", "unauthorized", "payload_invalid"}
        next_attempt = None if terminal else _next_attempt_at(alert.attempt_count)
        self._repository.mark_failed(alert, failure_code=failure_code, next_attempt_at=next_attempt, terminal=terminal)
        self._log.warning(
            "telegram_inventory_alert_delivery_failed alert_id=%s failure_code=%s terminal=%s",
            alert.id,
            failure_code,
            terminal,
        )
        return InventoryAlertDeliveryOutcome(
            str(alert.id),
            TelegramInventoryAlertStatus.CANCELLED if terminal else TelegramInventoryAlertStatus.FAILED,
            failure_code,
        )

    @staticmethod
    def _is_reorder_deadline_reached(assessment: InventoryRiskAssessment) -> bool:
        reorder = assessment.reorder_recommendation
        if not reorder or not reorder.reorder_deadline:
            return False
        action = getattr(reorder, "action", None)
        return action == ReorderRecommendationAction.REORDER and reorder.reorder_deadline <= assessment.as_of_date

    @staticmethod
    def _is_out_of_stock(assessment: InventoryRiskAssessment) -> bool:
        prediction = assessment.stockout_prediction
        if not prediction:
            return False
        return (
            prediction.prediction_status == StockoutPredictionStatus.ALREADY_OUT_OF_STOCK
            or prediction.inventory_position <= 0
        )

    @staticmethod
    def _has_material_days_drop(
        assessment: InventoryRiskAssessment,
        previous: InventoryRiskAssessment | None,
    ) -> bool:
        current_days = _days_remaining(assessment)
        previous_days = _days_remaining(previous) if previous else None
        if current_days is None or previous_days is None:
            return False
        return previous_days - current_days >= Decimal(str(settings.telegram_inventory_alert_material_days_drop))


def _risk_rank(assessment: InventoryRiskAssessment | None) -> int:
    if not assessment:
        return 0
    return RISK_ORDER.get(assessment.risk_level, 0)


def _days_remaining(assessment: InventoryRiskAssessment | None) -> Decimal | None:
    if not assessment or not assessment.stockout_prediction:
        return None
    value = assessment.stockout_prediction.days_remaining
    return Decimal(str(value)) if value is not None else None


def _next_attempt_at(attempt_count: int) -> datetime:
    base = settings.telegram_inventory_alert_initial_backoff_seconds
    maximum = settings.telegram_inventory_alert_max_backoff_seconds
    delay = min(maximum, base * (2 ** max(0, attempt_count - 1)))
    return _now() + timedelta(seconds=delay)


def _sanitize_failure(detail: str | None) -> str:
    normalized = (detail or "").lower()
    if "rate limit" in normalized or "retry" in normalized:
        return "rate_limited"
    if "network" in normalized or "timeout" in normalized or "timed out" in normalized:
        return "temporary_network_failure"
    if "chat" in normalized or "forbidden" in normalized:
        return "invalid_chat"
    if "token" in normalized or "unauthorized" in normalized:
        return "unauthorized"
    if "payload" in normalized or "empty" in normalized:
        return "payload_invalid"
    return "delivery_failed"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def inventory_dashboard_url(base_url: str | None, *, product_id, reorder: bool) -> str | None:
    """Deep link to the product drawer on the inventory page (?tab=&product=)."""
    if not base_url or product_id is None:
        return None
    tab = "reorder" if reorder else "today"
    return f"{base_url.rstrip('/')}/app/inventory-intelligence?tab={tab}&product={product_id}"
