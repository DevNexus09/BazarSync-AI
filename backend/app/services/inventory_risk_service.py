from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import logging
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.inventory_risk import InventoryRiskAssessment, InventoryRiskDataStatus, InventoryRiskLevel
from app.models.product import Product
from app.models.reorder_recommendation import FORECAST_REORDER_VERSION, ReorderRecommendation
from app.models.seller import Seller
from app.models.stockout_prediction import StockoutPrediction, StockoutPredictionStatus
from app.repositories.inventory_risk_repository import InventoryRiskRepository

logger = logging.getLogger(__name__)


class InventoryRiskRepositoryProtocol(Protocol):
    def iter_product_batches(self, *, batch_size: int, seller_id: UUID | None = None, product_id: UUID | None = None): ...
    def latest_stockout_for_products(self, *, seller_id: UUID, product_ids: list[UUID], as_of_date: date) -> dict[UUID, StockoutPrediction]: ...
    def latest_reorder_for_products(self, *, seller_id: UUID, product_ids: list[UUID], as_of_date: date) -> dict[UUID, ReorderRecommendation]: ...
    def add_idempotent(self, assessment: InventoryRiskAssessment) -> tuple[InventoryRiskAssessment, bool]: ...
    def latest(self, *, seller_id: UUID, product_id: UUID, calculation_version: str | None) -> InventoryRiskAssessment | None: ...
    def history(self, *, seller_id: UUID, product_id: UUID, from_date: date | None, to_date: date | None, calculation_version: str | None, order: str, limit: int, offset: int) -> tuple[list[InventoryRiskAssessment], int]: ...
    def list_current(self, *, seller_id: UUID, risk_level: InventoryRiskLevel | None, product_id: UUID | None, category: str | None, from_date: date | None, to_date: date | None, open_reorder_required: bool | None, limit: int, offset: int) -> tuple[list[InventoryRiskAssessment], int]: ...


@dataclass(frozen=True)
class InventoryRiskBatchResult:
    created_count: int
    skipped_count: int
    failed_count: int
    insufficient_data_count: int
    created_assessment_ids: list[str] | None = None


class InventoryRiskService:
    def __init__(self, db: Session | None = None, *, repository: InventoryRiskRepositoryProtocol | None = None, calculation_version: str | None = None, log: logging.Logger | None = None) -> None:
        if repository is None and db is None:
            raise ValueError("Either db or repository is required.")
        self._repository = repository or InventoryRiskRepository(db)  # type: ignore[arg-type]
        self._calculation_version = calculation_version or settings.inventory_risk_calculation_version
        self._log = log or logger

    def assess_for_product(self, *, product: Product, seller: Seller, stockout_prediction: StockoutPrediction | None, reorder_recommendation: ReorderRecommendation | None, as_of_date: date, assessed_at: datetime | None = None, calculation_version: str | None = None):
        assessment = self.build_assessment(
            product=product,
            seller=seller,
            stockout_prediction=stockout_prediction,
            reorder_recommendation=reorder_recommendation,
            as_of_date=as_of_date,
            assessed_at=_ensure_utc(assessed_at or datetime.now(timezone.utc)),
            calculation_version=calculation_version or self._calculation_version,
        )
        return self._repository.add_idempotent(assessment)

    def assess_for_batch(self, *, batch_size: int = 500, as_of_date: date | None = None, assessed_at: datetime | None = None, calculation_version: str | None = None, seller_id: UUID | None = None, product_id: UUID | None = None) -> InventoryRiskBatchResult:
        timestamp = _ensure_utc(assessed_at or datetime.now(timezone.utc))
        version = calculation_version or self._calculation_version
        created = skipped = failed = insufficient = 0
        created_ids: list[str] = []
        for batch in self._repository.iter_product_batches(batch_size=batch_size, seller_id=seller_id, product_id=product_id):
            products_by_seller: dict[UUID, tuple[Seller, list[Product]]] = {}
            for product, seller in batch:
                products_by_seller.setdefault(product.seller_id, (seller, []))[1].append(product)
            for batch_seller_id, (seller, products) in products_by_seller.items():
                try:
                    as_of = as_of_date or timestamp.date()
                    product_ids = [item.id for item in products]
                    stockouts = self._repository.latest_stockout_for_products(seller_id=batch_seller_id, product_ids=product_ids, as_of_date=as_of)
                    reorders = self._repository.latest_reorder_for_products(seller_id=batch_seller_id, product_ids=product_ids, as_of_date=as_of)
                    for product in products:
                        assessment = self.build_assessment(
                            product=product,
                            seller=seller,
                            stockout_prediction=stockouts.get(product.id),
                            reorder_recommendation=reorders.get(product.id),
                            as_of_date=as_of,
                            assessed_at=timestamp,
                            calculation_version=version,
                        )
                        saved, was_created = self._repository.add_idempotent(assessment)
                        created += int(was_created)
                        skipped += int(not was_created)
                        if was_created:
                            created_ids.append(str(saved.id))
                        insufficient += int(saved.data_status == InventoryRiskDataStatus.INSUFFICIENT)
                except Exception:
                    failed += len(products)
                    self._log.exception("Inventory risk batch failed seller_id=%s product_count=%s", batch_seller_id, len(products))
        self._log.info("Inventory risk assessment completed created=%s skipped=%s failed=%s insufficient=%s version=%s", created, skipped, failed, insufficient, version)
        return InventoryRiskBatchResult(created, skipped, failed, insufficient, created_ids)

    def build_assessment(self, *, product: Product, seller: Seller, stockout_prediction: StockoutPrediction | None, reorder_recommendation: ReorderRecommendation | None, as_of_date: date, assessed_at: datetime, calculation_version: str) -> InventoryRiskAssessment:
        del seller
        if (
            reorder_recommendation is not None and reorder_recommendation.id is not None
            and (getattr(reorder_recommendation, "evidence", None) or {}).get("planning_method") == FORECAST_REORDER_VERSION
        ):
            # Recalculate the dashboard risk when fresh supplier terms produced
            # a different reorder row on the same date.
            material = f"{calculation_version}:{reorder_recommendation.id}".encode()
            calculation_version = f"reorder-{sha256(material).hexdigest()[:12]}"
        lead_time = int(getattr(reorder_recommendation, "supplier_lead_time_days", getattr(product, "supplier_lead_time", 0) or settings.reorder_default_supplier_lead_time_days) or 0)
        safety_days = int(getattr(reorder_recommendation, "safety_buffer_days", settings.reorder_default_safety_buffer_days) or 0)
        review_days = int(getattr(reorder_recommendation, "review_period_days", settings.inventory_risk_medium_review_horizon_days) or settings.inventory_risk_medium_review_horizon_days)
        required_coverage = Decimal(lead_time + safety_days)
        days_remaining = _decimal_or_none(getattr(stockout_prediction, "days_remaining", None))
        inventory_position = int(getattr(stockout_prediction, "inventory_position", getattr(product, "stock_quantity", 0) or 0))
        prediction_status = getattr(stockout_prediction, "prediction_status", None)
        predicted_date = getattr(stockout_prediction, "predicted_stockout_date", None)
        reorder_deadline = getattr(reorder_recommendation, "reorder_deadline", None)
        coverage_gap = required_coverage - days_remaining if days_remaining is not None else None

        if stockout_prediction is None or prediction_status == StockoutPredictionStatus.INSUFFICIENT_DATA:
            data_status = InventoryRiskDataStatus.INSUFFICIENT
            level = None
        elif _is_stale(stockout_prediction, as_of_date):
            data_status = InventoryRiskDataStatus.LIMITED
            level = self._classify(inventory_position, days_remaining, required_coverage, Decimal(lead_time), Decimal(review_days), predicted_date, reorder_deadline, as_of_date, limited=True)
        else:
            data_status = InventoryRiskDataStatus.SUFFICIENT
            level = self._classify(inventory_position, days_remaining, required_coverage, Decimal(lead_time), Decimal(review_days), predicted_date, reorder_deadline, as_of_date, limited=False)

        factors = self._factors(
            product=product,
            stockout_prediction=stockout_prediction,
            reorder_recommendation=reorder_recommendation,
            required_coverage=required_coverage,
            coverage_gap=coverage_gap,
            data_status=data_status,
        )
        score = self._score(factors=factors, data_status=data_status, level=level)
        confidence = self._confidence(stockout_prediction, reorder_recommendation, data_status)
        return InventoryRiskAssessment(
            seller_id=product.seller_id,
            product_id=product.id,
            stockout_prediction_id=getattr(stockout_prediction, "id", None),
            reorder_recommendation_id=getattr(reorder_recommendation, "id", None),
            as_of_date=as_of_date,
            risk_score=score,
            risk_level=level,
            coverage_gap_days=coverage_gap.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP) if coverage_gap is not None else None,
            data_status=data_status,
            confidence_score=confidence,
            factors=factors,
            calculation_version=calculation_version,
            assessed_at=assessed_at,
        )

    def latest_risk(self, *, seller_id: UUID, product_id: UUID, calculation_version: str | None = None):
        return self._repository.latest(seller_id=seller_id, product_id=product_id, calculation_version=calculation_version)

    def risk_history(self, *, seller_id: UUID, product_id: UUID, from_date: date | None, to_date: date | None, calculation_version: str | None, order: str, limit: int, offset: int):
        return self._repository.history(seller_id=seller_id, product_id=product_id, from_date=from_date, to_date=to_date, calculation_version=calculation_version, order=order, limit=limit, offset=offset)

    def list_risks(self, *, seller_id: UUID, risk_level: InventoryRiskLevel | None, product_id: UUID | None, category: str | None, from_date: date | None, to_date: date | None, open_reorder_required: bool | None, limit: int, offset: int):
        return self._repository.list_current(seller_id=seller_id, risk_level=risk_level, product_id=product_id, category=category, from_date=from_date, to_date=to_date, open_reorder_required=open_reorder_required, limit=limit, offset=offset)

    @staticmethod
    def _classify(inventory_position: int, days_remaining: Decimal | None, required_coverage: Decimal, lead_time_days: Decimal, review_days: Decimal, predicted_date: date | None, reorder_deadline: date | None, as_of_date: date, *, limited: bool) -> InventoryRiskLevel:
        if inventory_position <= 0:
            return InventoryRiskLevel.CRITICAL
        if days_remaining is None:
            return InventoryRiskLevel.HIGH if limited else InventoryRiskLevel.MEDIUM
        supplier_deadline = as_of_date + timedelta(days=int(lead_time_days))
        coverage_gap = required_coverage - days_remaining
        if predicted_date and predicted_date < supplier_deadline:
            return InventoryRiskLevel.CRITICAL
        if reorder_deadline and reorder_deadline <= as_of_date and coverage_gap >= Decimal(str(settings.inventory_risk_significant_coverage_gap_days)):
            return InventoryRiskLevel.CRITICAL
        if days_remaining <= required_coverage:
            return InventoryRiskLevel.HIGH
        if days_remaining <= required_coverage + review_days:
            return InventoryRiskLevel.MEDIUM
        return InventoryRiskLevel.LOW

    @staticmethod
    def _factors(*, product: Product, stockout_prediction: StockoutPrediction | None, reorder_recommendation: ReorderRecommendation | None, required_coverage: Decimal, coverage_gap: Decimal | None, data_status: InventoryRiskDataStatus) -> dict:
        return {
            "days_remaining": str(getattr(stockout_prediction, "days_remaining", "")) if stockout_prediction else None,
            "supplier_lead_time_days": getattr(reorder_recommendation, "supplier_lead_time_days", getattr(product, "supplier_lead_time", None)),
            "safety_buffer_days": getattr(reorder_recommendation, "safety_buffer_days", settings.reorder_default_safety_buffer_days),
            "required_coverage_days": str(required_coverage),
            "coverage_gap_days": str(coverage_gap) if coverage_gap is not None else None,
            "current_stock": getattr(stockout_prediction, "quantity_on_hand", getattr(product, "stock_quantity", None)),
            "inventory_position": getattr(stockout_prediction, "inventory_position", getattr(product, "stock_quantity", None)),
            "sales_velocity_confidence": getattr(stockout_prediction, "calculation_metadata", {}).get("sales_velocity_confidence") if stockout_prediction else None,
            "prediction_confidence": str(getattr(stockout_prediction, "confidence_score", "")) if stockout_prediction else None,
            "reorder_deadline": getattr(reorder_recommendation, "reorder_deadline", None).isoformat() if getattr(reorder_recommendation, "reorder_deadline", None) else None,
            "existing_stockout_state": getattr(getattr(stockout_prediction, "prediction_status", None), "value", None),
            "data_status": data_status.value,
            "score_formula": "40% coverage gap + 25% stock state + 20% reorder urgency + 10% confidence risk + 5% inventory freshness",
            "formula_version": settings.inventory_risk_calculation_version,
            "reorder_action": getattr(getattr(reorder_recommendation, "action", None), "value", None),
            "reorder_status": getattr(getattr(reorder_recommendation, "recommendation_status", None), "value", None),
        }

    @staticmethod
    def _score(*, factors: dict, data_status: InventoryRiskDataStatus, level: InventoryRiskLevel | None) -> Decimal:
        if data_status == InventoryRiskDataStatus.INSUFFICIENT:
            return Decimal("50.00")
        required = Decimal(str(factors["required_coverage_days"]))
        gap = Decimal(str(factors["coverage_gap_days"] or "0"))
        inv_position = Decimal(str(factors["inventory_position"] or "0"))
        coverage_component = _clamp((gap / max(required, Decimal("1"))) * Decimal("100"), Decimal("0"), Decimal("100")) * Decimal("0.40")
        stock_component = (Decimal("100") if inv_position <= 0 else _clamp((Decimal("1") - (inv_position / max(required, Decimal("1")))) * Decimal("100"), Decimal("0"), Decimal("100"))) * Decimal("0.25")
        urgency_component = Decimal("100") * Decimal("0.20") if factors.get("reorder_deadline") else Decimal("0")
        prediction_conf = Decimal(str(factors.get("prediction_confidence") or "0"))
        confidence_component = (Decimal("100") - prediction_conf) * Decimal("0.10")
        freshness_component = (Decimal("50") if data_status == InventoryRiskDataStatus.LIMITED else Decimal("0")) * Decimal("0.05")
        score = coverage_component + stock_component + urgency_component + confidence_component + freshness_component
        floor_by_level = {InventoryRiskLevel.CRITICAL: Decimal("85"), InventoryRiskLevel.HIGH: Decimal("70"), InventoryRiskLevel.MEDIUM: Decimal("40"), InventoryRiskLevel.LOW: Decimal("0")}
        if level:
            score = max(score, floor_by_level[level])
        return _clamp(score, Decimal("0"), Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def _confidence(stockout_prediction: StockoutPrediction | None, reorder_recommendation: ReorderRecommendation | None, data_status: InventoryRiskDataStatus) -> Decimal:
        prediction_confidence = Decimal(str(getattr(stockout_prediction, "confidence_score", Decimal("0")) or Decimal("0")))
        reorder_confidence = Decimal(str(getattr(reorder_recommendation, "confidence_score", Decimal("0")) or Decimal("0")))
        score = prediction_confidence * Decimal("0.65") + reorder_confidence * Decimal("0.35")
        if data_status == InventoryRiskDataStatus.INSUFFICIENT:
            score = min(score, Decimal("35"))
        elif data_status == InventoryRiskDataStatus.LIMITED:
            score = min(score, Decimal("70"))
        return _clamp(score, Decimal("0"), Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _is_stale(stockout_prediction: StockoutPrediction, as_of_date: date) -> bool:
    metadata = getattr(stockout_prediction, "calculation_metadata", None) or {}
    value = metadata.get("inventory_snapshot_date")
    if not value:
        return False
    try:
        snapshot_date = date.fromisoformat(value)
    except ValueError:
        return True
    return (as_of_date - snapshot_date).days > settings.inventory_risk_stale_inventory_days


def _decimal_or_none(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _clamp(value: Decimal, minimum: Decimal, maximum: Decimal) -> Decimal:
    return max(minimum, min(value, maximum))


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
