from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models.inventory_risk import InventoryRiskAssessment
from app.models.product import Product
from app.models.telegram_connection import SellerTelegramConnection
from app.models.telegram_inventory_alert import (
    TelegramInventoryAlert,
    TelegramInventoryAlertStatus,
    TelegramInventoryAlertType,
)


class TelegramInventoryAlertRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_risk_with_context(self, risk_assessment_id: UUID) -> InventoryRiskAssessment | None:
        statement = (
            select(InventoryRiskAssessment)
            .where(InventoryRiskAssessment.id == risk_assessment_id)
            .options(
                selectinload(InventoryRiskAssessment.product),
                selectinload(InventoryRiskAssessment.stockout_prediction),
                selectinload(InventoryRiskAssessment.reorder_recommendation),
            )
        )
        return self._db.execute(statement).scalar_one_or_none()

    def previous_risk(self, assessment: InventoryRiskAssessment) -> InventoryRiskAssessment | None:
        statement = (
            select(InventoryRiskAssessment)
            .where(
                InventoryRiskAssessment.seller_id == assessment.seller_id,
                InventoryRiskAssessment.product_id == assessment.product_id,
                InventoryRiskAssessment.calculation_version == assessment.calculation_version,
                InventoryRiskAssessment.as_of_date < assessment.as_of_date,
            )
            .order_by(
                InventoryRiskAssessment.as_of_date.desc(),
                InventoryRiskAssessment.assessed_at.desc(),
            )
            .limit(1)
            .options(selectinload(InventoryRiskAssessment.stockout_prediction))
        )
        return self._db.execute(statement).scalar_one_or_none()

    def add_idempotent(self, alert: TelegramInventoryAlert) -> tuple[TelegramInventoryAlert, bool]:
        existing = self.get_by_dedupe_key(alert.dedupe_key)
        if existing:
            return existing, False
        self._db.add(alert)
        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            existing = self.get_by_dedupe_key(alert.dedupe_key)
            if existing:
                return existing, False
            raise
        self._db.refresh(alert)
        return alert, True

    def get_by_dedupe_key(self, dedupe_key: str) -> TelegramInventoryAlert | None:
        return self._db.execute(
            select(TelegramInventoryAlert).where(TelegramInventoryAlert.dedupe_key == dedupe_key)
        ).scalar_one_or_none()

    def latest_sent(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        alert_type: TelegramInventoryAlertType,
        risk_level: str | None = None,
    ) -> TelegramInventoryAlert | None:
        statement = (
            select(TelegramInventoryAlert)
            .where(
                TelegramInventoryAlert.seller_id == seller_id,
                TelegramInventoryAlert.product_id == product_id,
                TelegramInventoryAlert.alert_type == alert_type,
                TelegramInventoryAlert.status == TelegramInventoryAlertStatus.SENT,
            )
            .order_by(TelegramInventoryAlert.sent_at.desc().nullslast(), TelegramInventoryAlert.created_at.desc())
            .limit(1)
        )
        if risk_level:
            statement = statement.where(
                TelegramInventoryAlert.alert_metadata["risk_level"].astext == risk_level
            )
        return self._db.execute(statement).scalar_one_or_none()

    def get_alert_for_delivery(self, alert_id: UUID) -> TelegramInventoryAlert | None:
        statement = (
            select(TelegramInventoryAlert)
            .where(TelegramInventoryAlert.id == alert_id)
            .options(
                selectinload(TelegramInventoryAlert.product),
                selectinload(TelegramInventoryAlert.risk_assessment).selectinload(InventoryRiskAssessment.stockout_prediction),
                selectinload(TelegramInventoryAlert.reorder_recommendation),
            )
        )
        return self._db.execute(statement).scalar_one_or_none()

    def due_alerts(self, *, limit: int = 100) -> list[TelegramInventoryAlert]:
        now = datetime.now(timezone.utc)
        statement = (
            select(TelegramInventoryAlert)
            .where(
                TelegramInventoryAlert.status.in_(
                    [TelegramInventoryAlertStatus.PENDING, TelegramInventoryAlertStatus.FAILED]
                ),
                (TelegramInventoryAlert.next_attempt_at.is_(None))
                | (TelegramInventoryAlert.next_attempt_at <= now),
            )
            .order_by(TelegramInventoryAlert.created_at.asc(), TelegramInventoryAlert.id.asc())
            .limit(limit)
        )
        return list(self._db.execute(statement).scalars().all())

    def get_connection(self, seller_id: UUID) -> SellerTelegramConnection | None:
        return self._db.execute(
            select(SellerTelegramConnection).where(SellerTelegramConnection.seller_id == seller_id)
        ).scalar_one_or_none()

    def mark_sending(self, alert: TelegramInventoryAlert) -> bool:
        result = self._db.execute(
            update(TelegramInventoryAlert)
            .where(
                TelegramInventoryAlert.id == alert.id,
                TelegramInventoryAlert.status.in_(
                    [TelegramInventoryAlertStatus.PENDING, TelegramInventoryAlertStatus.FAILED]
                ),
            )
            .values(
                status=TelegramInventoryAlertStatus.SENDING,
                attempt_count=TelegramInventoryAlert.attempt_count + 1,
                failure_code=None,
            )
        )
        if result.rowcount != 1:
            self._db.rollback()
            return False
        self._db.commit()
        self._db.refresh(alert)
        return True

    def mark_sent(self, alert: TelegramInventoryAlert, *, sent_at: datetime) -> None:
        alert.status = TelegramInventoryAlertStatus.SENT
        alert.sent_at = sent_at
        alert.next_attempt_at = None
        alert.failure_code = None
        connection = self.get_connection(alert.seller_id)
        if connection:
            connection.last_alert_sent_at = sent_at
        self._db.commit()

    def mark_failed(
        self,
        alert: TelegramInventoryAlert,
        *,
        failure_code: str,
        next_attempt_at: datetime | None,
        terminal: bool,
    ) -> None:
        alert.status = TelegramInventoryAlertStatus.CANCELLED if terminal else TelegramInventoryAlertStatus.FAILED
        alert.failure_code = failure_code
        alert.next_attempt_at = next_attempt_at
        self._db.commit()

    def list_for_seller(self, *, seller_id: UUID, limit: int = 50) -> list[TelegramInventoryAlert]:
        statement = (
            select(TelegramInventoryAlert)
            .join(Product, TelegramInventoryAlert.product_id == Product.id)
            .where(TelegramInventoryAlert.seller_id == seller_id, Product.seller_id == seller_id)
            .order_by(TelegramInventoryAlert.created_at.desc())
            .limit(limit)
        )
        return list(self._db.execute(statement).scalars().all())
