from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Protocol
from uuid import UUID

from app.models.inventory_risk import InventoryRiskDataStatus, InventoryRiskLevel
from app.repositories.inventory_intelligence_repository import InventoryIntelligenceRepository
from app.schemas.inventory_intelligence import (
    InventoryIntelligenceListItem,
    InventoryIntelligenceSummaryResponse,
    ProductInventoryIntelligenceResponse,
)
from app.services.telegram.inventory_alert_service import TelegramInventoryAlertService


class InventoryIntelligenceRepositoryProtocol(Protocol):
    def product_exists(self, *, seller_id: UUID, product_id: UUID) -> bool: ...
    def summary(self, *, seller_id: UUID) -> dict: ...
    def latest_product_bundle(self, *, seller_id: UUID, product_id: UUID) -> dict | None: ...
    def reorder_list(self, *, seller_id: UUID, risk_level: InventoryRiskLevel | None, deadline_from: date | None, deadline_to: date | None, product_id: UUID | None, category: str | None, sort: str, limit: int, offset: int) -> tuple[list[dict], int]: ...
    def risks(self, *, seller_id: UUID, risk_level: InventoryRiskLevel | None, insufficient_data: bool | None, product_id: UUID | None, category: str | None, limit: int, offset: int) -> tuple[list[dict], int]: ...
    def latest_risks_for_scope(self, *, seller_id: UUID | None, product_id: UUID | None, as_of_date: date | None): ...


class InventoryIntelligenceService:
    def __init__(self, db=None, *, repository: InventoryIntelligenceRepositoryProtocol | None = None) -> None:
        if repository is None and db is None:
            raise ValueError("Either db or repository is required.")
        self._repository = repository or InventoryIntelligenceRepository(db)
        self._db = db

    def summary(self, *, seller_id: UUID) -> InventoryIntelligenceSummaryResponse:
        data = self._repository.summary(seller_id=seller_id)
        return InventoryIntelligenceSummaryResponse(
            **data,
            data_freshness_status=_freshness_status(data.get("last_calculation_time")),
        )

    def product_intelligence(self, *, seller_id: UUID, product_id: UUID) -> ProductInventoryIntelligenceResponse | None:
        bundle = self._repository.latest_product_bundle(seller_id=seller_id, product_id=product_id)
        if not bundle:
            return None
        product = bundle["product"]
        inventory = bundle["inventory"]
        velocity = bundle["velocity"]
        prediction = bundle["prediction"]
        reorder = bundle["reorder"]
        risk = bundle["risk"]
        updated_candidates = [
            getattr(inventory, "captured_at", None),
            getattr(velocity, "calculated_at", None),
            getattr(prediction, "calculated_at", None),
            getattr(reorder, "generated_at", None),
            getattr(risk, "assessed_at", None),
        ]
        return ProductInventoryIntelligenceResponse(
            product_id=product.id,
            product_name=product.title,
            category=product.category,
            latest_inventory_snapshot_id=getattr(inventory, "id", None),
            inventory_snapshot_date=getattr(inventory, "snapshot_date", None),
            quantity_on_hand=getattr(inventory, "quantity_on_hand", None),
            quantity_reserved=getattr(inventory, "quantity_reserved", None),
            quantity_available=getattr(inventory, "quantity_available", None),
            quantity_incoming=getattr(inventory, "quantity_incoming", None),
            daily_sales_rate=getattr(velocity, "daily_sales_rate", None),
            velocity_window_days=getattr(velocity, "window_days", None),
            velocity_data_status=getattr(velocity, "data_status", None),
            days_remaining=getattr(prediction, "days_remaining", None),
            predicted_stockout_date=getattr(prediction, "predicted_stockout_date", None),
            stockout_prediction_status=getattr(prediction, "prediction_status", None),
            supplier_lead_time_days=getattr(reorder, "supplier_lead_time_days", getattr(product, "supplier_lead_time", None)),
            safety_buffer_days=getattr(reorder, "safety_buffer_days", None),
            inventory_risk_score=getattr(risk, "risk_score", None),
            risk_level=getattr(risk, "risk_level", None),
            reorder_action=getattr(reorder, "action", None),
            recommended_quantity=getattr(reorder, "recommended_quantity", None),
            reorder_deadline=getattr(reorder, "reorder_deadline", None),
            confidence_score=getattr(risk, "confidence_score", None),
            data_status=getattr(risk, "data_status", None),
            explanation=getattr(reorder, "explanation", None) or getattr(prediction, "explanation", None),
            calculation_version=getattr(risk, "calculation_version", None),
            as_of_date=getattr(risk, "as_of_date", None),
            last_updated_at=max((value for value in updated_candidates if value is not None), default=None),
            metadata=getattr(risk, "factors", None),
        )

    def reorder_list(
        self,
        *,
        seller_id: UUID,
        risk_level: InventoryRiskLevel | None,
        deadline_from: date | None,
        deadline_to: date | None,
        product_id: UUID | None,
        category: str | None,
        sort: str,
        limit: int,
        offset: int,
    ) -> tuple[list[InventoryIntelligenceListItem], int]:
        rows, total = self._repository.reorder_list(
            seller_id=seller_id,
            risk_level=risk_level,
            deadline_from=deadline_from,
            deadline_to=deadline_to,
            product_id=product_id,
            category=category,
            sort=sort,
            limit=limit,
            offset=offset,
        )
        return [_list_item(row) for row in rows], total

    def risks(
        self,
        *,
        seller_id: UUID,
        risk_level: InventoryRiskLevel | None,
        insufficient_data: bool | None,
        product_id: UUID | None,
        category: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[InventoryIntelligenceListItem], int]:
        rows, total = self._repository.risks(
            seller_id=seller_id,
            risk_level=risk_level,
            insufficient_data=insufficient_data,
            product_id=product_id,
            category=category,
            limit=limit,
            offset=offset,
        )
        return [_list_item(row) for row in rows], total

    def generate_alerts_for_latest_risks(
        self,
        *,
        seller_id: UUID | None,
        product_id: UUID | None,
        as_of_date: date | None,
    ) -> dict[str, int]:
        if self._db is None:
            raise ValueError("Database session is required for alert generation.")
        created = skipped = 0
        risks = self._repository.latest_risks_for_scope(
            seller_id=seller_id,
            product_id=product_id,
            as_of_date=as_of_date,
        )
        alert_service = TelegramInventoryAlertService(self._db)
        for risk in risks:
            result = alert_service.generate_for_risk_assessment(risk.id)
            created += result.created_count
            skipped += result.skipped_count
        return {"created_count": created, "skipped_count": skipped, "risk_count": len(risks)}


def _list_item(row: dict) -> InventoryIntelligenceListItem:
    product = row["product"]
    risk = row["risk"]
    reorder = row.get("reorder")
    prediction = row.get("prediction")
    return InventoryIntelligenceListItem(
        product_id=product.id,
        product_name=product.title,
        category=product.category,
        risk_level=getattr(risk, "risk_level", None),
        risk_score=getattr(risk, "risk_score", None),
        data_status=getattr(risk, "data_status", None),
        days_remaining=getattr(prediction, "days_remaining", None),
        predicted_stockout_date=getattr(prediction, "predicted_stockout_date", None),
        reorder_action=getattr(reorder, "action", None),
        recommendation_status=getattr(reorder, "recommendation_status", None),
        recommended_quantity=getattr(reorder, "recommended_quantity", None),
        reorder_deadline=getattr(reorder, "reorder_deadline", None),
        calculation_version=getattr(risk, "calculation_version", None),
        as_of_date=getattr(risk, "as_of_date", None),
        last_updated_at=getattr(risk, "assessed_at", None),
    )


def _freshness_status(last_calculation_time: datetime | None) -> str:
    if last_calculation_time is None:
        return "NO_DATA"
    value = last_calculation_time
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - value.astimezone(timezone.utc)).total_seconds() / 3600
    if age_hours <= 24:
        return "FRESH"
    if age_hours <= 72:
        return "STALE"
    return "VERY_STALE"
