from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
import logging
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.inventory_history import InventoryHistory
from app.models.product import Product
from app.models.reorder_recommendation import (
    ReorderRecommendation,
    ReorderRecommendationAction,
    ReorderRecommendationStatus,
)
from app.models.sales_velocity import SalesVelocity, SalesVelocityDataStatus
from app.models.seller import Seller
from app.models.stockout_prediction import StockoutPrediction
from app.repositories.reorder_recommendation_repository import ReorderRecommendationRepository

logger = logging.getLogger(__name__)


class ReorderRecommendationRepositoryProtocol(Protocol):
    def iter_product_batches(self, *, batch_size: int, seller_id: UUID | None = None, product_id: UUID | None = None): ...
    def latest_inventory_for_products(self, *, seller_id: UUID, product_ids: list[UUID], as_of_date: date) -> dict[UUID, InventoryHistory]: ...
    def latest_velocity_for_products(self, *, seller_id: UUID, product_ids: list[UUID], as_of_date: date) -> dict[UUID, SalesVelocity]: ...
    def latest_stockout_for_products(self, *, seller_id: UUID, product_ids: list[UUID], as_of_date: date) -> dict[UUID, StockoutPrediction]: ...
    def add_idempotent(self, recommendation: ReorderRecommendation) -> tuple[ReorderRecommendation, bool]: ...
    def latest(self, *, seller_id: UUID, product_id: UUID, calculation_version: str | None) -> ReorderRecommendation | None: ...
    def history(self, *, seller_id: UUID, product_id: UUID, from_date: date | None, to_date: date | None, calculation_version: str | None, order: str, limit: int, offset: int) -> tuple[list[ReorderRecommendation], int]: ...
    def get_by_id(self, *, seller_id: UUID, recommendation_id: UUID) -> ReorderRecommendation | None: ...
    def save_status(self, recommendation: ReorderRecommendation) -> ReorderRecommendation: ...


@dataclass(frozen=True)
class ReorderRecommendationOutcome:
    recommendation: ReorderRecommendation
    created: bool


@dataclass(frozen=True)
class ReorderRecommendationBatchResult:
    created_count: int
    skipped_count: int
    failed_count: int
    insufficient_data_count: int


class ReorderRecommendationNotFoundError(Exception):
    pass


class ReorderRecommendationService:
    def __init__(
        self,
        db: Session | None = None,
        *,
        repository: ReorderRecommendationRepositoryProtocol | None = None,
        calculation_version: str | None = None,
        log: logging.Logger | None = None,
    ) -> None:
        if repository is None and db is None:
            raise ValueError("Either db or repository is required.")
        self._repository = repository or ReorderRecommendationRepository(db)  # type: ignore[arg-type]
        self._calculation_version = calculation_version or settings.reorder_calculation_version
        self._log = log or logger

    def calculate_for_product(
        self,
        *,
        product: Product,
        seller: Seller,
        inventory_snapshot: InventoryHistory | None,
        sales_velocity: SalesVelocity | None,
        stockout_prediction: StockoutPrediction | None,
        as_of_date: date,
        generated_at: datetime | None = None,
        calculation_version: str | None = None,
        confirmed_incoming_quantity: int | None = None,
    ) -> ReorderRecommendationOutcome:
        recommendation = self.build_recommendation(
            product=product,
            seller=seller,
            inventory_snapshot=inventory_snapshot,
            sales_velocity=sales_velocity,
            stockout_prediction=stockout_prediction,
            as_of_date=as_of_date,
            generated_at=_ensure_utc(generated_at or datetime.now(timezone.utc)),
            calculation_version=calculation_version or self._calculation_version,
            confirmed_incoming_quantity=confirmed_incoming_quantity,
        )
        saved, created = self._repository.add_idempotent(recommendation)
        return ReorderRecommendationOutcome(saved, created)

    def calculate_for_batch(
        self,
        *,
        batch_size: int = 500,
        as_of_date: date | None = None,
        generated_at: datetime | None = None,
        calculation_version: str | None = None,
        seller_id: UUID | None = None,
        product_id: UUID | None = None,
    ) -> ReorderRecommendationBatchResult:
        timestamp = _ensure_utc(generated_at or datetime.now(timezone.utc))
        version = calculation_version or self._calculation_version
        created = skipped = failed = insufficient = 0
        for batch in self._repository.iter_product_batches(batch_size=batch_size, seller_id=seller_id, product_id=product_id):
            products_by_seller: dict[UUID, tuple[Seller, list[Product]]] = {}
            for product, seller in batch:
                products_by_seller.setdefault(product.seller_id, (seller, []))[1].append(product)
            for batch_seller_id, (seller, products) in products_by_seller.items():
                try:
                    as_of = as_of_date or timestamp.date()
                    product_ids = [item.id for item in products]
                    inventory = self._repository.latest_inventory_for_products(seller_id=batch_seller_id, product_ids=product_ids, as_of_date=as_of)
                    velocities = self._repository.latest_velocity_for_products(seller_id=batch_seller_id, product_ids=product_ids, as_of_date=as_of)
                    stockouts = self._repository.latest_stockout_for_products(seller_id=batch_seller_id, product_ids=product_ids, as_of_date=as_of)
                    for product in products:
                        recommendation = self.build_recommendation(
                            product=product,
                            seller=seller,
                            inventory_snapshot=inventory.get(product.id),
                            sales_velocity=velocities.get(product.id),
                            stockout_prediction=stockouts.get(product.id),
                            as_of_date=as_of,
                            generated_at=timestamp,
                            calculation_version=version,
                        )
                        saved, was_created = self._repository.add_idempotent(recommendation)
                        if was_created:
                            created += 1
                        else:
                            skipped += 1
                        if saved.recommendation_status == ReorderRecommendationStatus.INSUFFICIENT_DATA:
                            insufficient += 1
                except Exception:
                    failed += len(products)
                    self._log.exception("Reorder recommendation batch failed seller_id=%s product_count=%s", batch_seller_id, len(products))
        self._log.info("Reorder recommendations completed created=%s skipped=%s failed=%s insufficient=%s version=%s", created, skipped, failed, insufficient, version)
        return ReorderRecommendationBatchResult(created, skipped, failed, insufficient)

    def build_recommendation(
        self,
        *,
        product: Product,
        seller: Seller,
        inventory_snapshot: InventoryHistory | None,
        sales_velocity: SalesVelocity | None,
        stockout_prediction: StockoutPrediction | None,
        as_of_date: date,
        generated_at: datetime,
        calculation_version: str,
        confirmed_incoming_quantity: int | None = None,
    ) -> ReorderRecommendation:
        settings_snapshot = self._product_reorder_settings(product)
        lead_time = settings_snapshot["supplier_lead_time_days"]
        safety_days = settings_snapshot["safety_buffer_days"]
        review_days = settings_snapshot["review_period_days"]
        min_order = settings_snapshot["minimum_order_quantity"]
        pack_size = settings_snapshot["pack_size"]
        lead_time_defaulted = settings_snapshot["supplier_lead_time_defaulted"]

        quantity_on_hand = int(getattr(inventory_snapshot, "quantity_on_hand", product.stock_quantity or 0))
        reserved = int(getattr(inventory_snapshot, "quantity_reserved", 0) or 0)
        snapshot_incoming = int(getattr(inventory_snapshot, "quantity_incoming", 0) or 0)
        confirmed_incoming = (
            max(0, confirmed_incoming_quantity)
            if confirmed_incoming_quantity is not None
            else int(getattr(stockout_prediction, "quantity_incoming", 0) or 0)
        )
        inventory_position = quantity_on_hand + confirmed_incoming - reserved
        rate = Decimal(str(getattr(sales_velocity, "daily_sales_rate", Decimal("0")) or Decimal("0")))

        insufficient_reason: str | None = None
        velocity_confidence = Decimal(str(getattr(sales_velocity, "confidence_score", Decimal("0")) or Decimal("0")))
        if sales_velocity is None:
            insufficient_reason = "missing_sales_velocity"
        elif getattr(sales_velocity, "data_status", None) == SalesVelocityDataStatus.INSUFFICIENT:
            insufficient_reason = "insufficient_sales_velocity"
        elif velocity_confidence < Decimal(str(settings.reorder_minimum_velocity_confidence)):
            insufficient_reason = "velocity_confidence_below_minimum"

        reorder_point = _ceil_decimal(rate * Decimal(lead_time + safety_days))
        target_stock = _ceil_decimal(rate * Decimal(lead_time + safety_days + review_days))
        raw_quantity = max(0, target_stock - inventory_position)
        recommended_quantity = self._adjust_quantity(raw_quantity, min_order=min_order, pack_size=pack_size)
        deadline = self._reorder_deadline(
            as_of_date=as_of_date,
            inventory_position=inventory_position,
            reorder_point=reorder_point,
            daily_sales_rate=rate,
        )
        days_until_deadline = max(0, (deadline - as_of_date).days) if deadline else None
        within_horizon = days_until_deadline is not None and days_until_deadline <= settings.reorder_maximum_recommendation_horizon_days

        if insufficient_reason:
            action = ReorderRecommendationAction.HOLD
            status = ReorderRecommendationStatus.INSUFFICIENT_DATA
            recommended_quantity = 0
            explanation = "Reorder recommendation is unavailable because required demand data is insufficient."
        elif rate <= 0:
            action = ReorderRecommendationAction.HOLD
            status = ReorderRecommendationStatus.OPEN
            recommended_quantity = 0
            explanation = "No recent demand is detected, so no reorder is recommended."
        elif recommended_quantity > 0 and within_horizon:
            action = ReorderRecommendationAction.REORDER
            status = ReorderRecommendationStatus.OPEN
            explanation = "Available stock is expected to fall below the reorder point within the recommendation horizon."
        else:
            action = ReorderRecommendationAction.HOLD
            status = ReorderRecommendationStatus.OPEN
            recommended_quantity = 0
            explanation = "Inventory coverage is adequate for the configured lead time, safety buffer, and review period."

        evidence = {
            "current_stock": quantity_on_hand,
            "reserved_stock": reserved,
            "confirmed_incoming": confirmed_incoming,
            "unconfirmed_snapshot_incoming": snapshot_incoming,
            "inventory_position": inventory_position,
            "daily_sales_rate": str(rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
            "supplier_lead_time_days": lead_time,
            "supplier_lead_time_defaulted": lead_time_defaulted,
            "safety_buffer_days": safety_days,
            "review_period_days": review_days,
            "lead_time_demand": str((rate * Decimal(lead_time)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
            "safety_stock": str((rate * Decimal(safety_days)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
            "reorder_point": reorder_point,
            "target_stock": target_stock,
            "raw_reorder_quantity": raw_quantity,
            "minimum_order_quantity": min_order,
            "pack_size": pack_size,
            "maximum_recommendation_horizon_days": settings.reorder_maximum_recommendation_horizon_days,
            "calculation_version": calculation_version,
            "insufficient_reason": insufficient_reason,
        }
        confidence = self._confidence_score(
            velocity_confidence=velocity_confidence,
            stockout_confidence=Decimal(str(getattr(stockout_prediction, "confidence_score", Decimal("0")) or Decimal("0"))),
            lead_time_defaulted=lead_time_defaulted,
            status=status,
        )
        return ReorderRecommendation(
            seller_id=product.seller_id,
            product_id=product.id,
            inventory_snapshot_id=getattr(inventory_snapshot, "id", None),
            sales_velocity_id=getattr(sales_velocity, "id", None),
            stockout_prediction_id=getattr(stockout_prediction, "id", None),
            as_of_date=as_of_date,
            action=action,
            recommended_quantity=recommended_quantity,
            reorder_deadline=deadline if status != ReorderRecommendationStatus.INSUFFICIENT_DATA else None,
            supplier_lead_time_days=lead_time,
            safety_buffer_days=safety_days,
            review_period_days=review_days,
            reorder_point=reorder_point,
            target_stock=target_stock,
            inventory_position=inventory_position,
            daily_sales_rate=rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            confidence_score=confidence,
            recommendation_status=status,
            explanation=explanation,
            evidence=evidence,
            calculation_version=calculation_version,
            generated_at=generated_at,
        )

    def latest_recommendation(self, *, seller_id: UUID, product_id: UUID, calculation_version: str | None = None) -> ReorderRecommendation | None:
        return self._repository.latest(seller_id=seller_id, product_id=product_id, calculation_version=calculation_version)

    def recommendation_history(self, *, seller_id: UUID, product_id: UUID, from_date: date | None, to_date: date | None, calculation_version: str | None, order: str, limit: int, offset: int):
        return self._repository.history(seller_id=seller_id, product_id=product_id, from_date=from_date, to_date=to_date, calculation_version=calculation_version, order=order, limit=limit, offset=offset)

    def transition_status(self, *, seller_id: UUID, recommendation_id: UUID, status: ReorderRecommendationStatus) -> ReorderRecommendation:
        recommendation = self._repository.get_by_id(seller_id=seller_id, recommendation_id=recommendation_id)
        if recommendation is None:
            raise ReorderRecommendationNotFoundError
        recommendation.recommendation_status = status
        return self._repository.save_status(recommendation)

    def _product_reorder_settings(self, product: Product) -> dict[str, int | bool | None]:
        specs = getattr(product, "specifications", None) or {}
        lead_time = _positive_int(getattr(product, "supplier_lead_time", None))
        lead_time_defaulted = False
        if lead_time is None:
            lead_time = settings.reorder_default_supplier_lead_time_days
            lead_time_defaulted = True
        return {
            "supplier_lead_time_days": lead_time,
            "supplier_lead_time_defaulted": lead_time_defaulted,
            "safety_buffer_days": _positive_int(specs.get("safety_buffer_days")) or settings.reorder_default_safety_buffer_days,
            "review_period_days": _positive_int(specs.get("review_period_days")) or settings.reorder_default_review_period_days,
            "minimum_order_quantity": _positive_int(specs.get("minimum_order_quantity") or specs.get("moq")),
            "pack_size": _positive_int(specs.get("pack_size") or specs.get("case_size")),
        }

    @staticmethod
    def _adjust_quantity(raw_quantity: int, *, min_order: int | None, pack_size: int | None) -> int:
        if raw_quantity <= 0:
            return 0
        quantity = raw_quantity
        if pack_size and pack_size > 0:
            quantity = ((quantity + pack_size - 1) // pack_size) * pack_size
        if min_order and quantity < min_order:
            quantity = min_order
        return max(0, quantity)

    @staticmethod
    def _reorder_deadline(*, as_of_date: date, inventory_position: int, reorder_point: int, daily_sales_rate: Decimal) -> date | None:
        if daily_sales_rate <= 0:
            return None
        if inventory_position <= reorder_point:
            return as_of_date
        days = ((Decimal(inventory_position - reorder_point) / daily_sales_rate).to_integral_value(rounding=ROUND_FLOOR))
        return as_of_date + timedelta(days=int(days))

    @staticmethod
    def _confidence_score(*, velocity_confidence: Decimal, stockout_confidence: Decimal, lead_time_defaulted: bool, status: ReorderRecommendationStatus) -> Decimal:
        score = velocity_confidence * Decimal("0.65") + stockout_confidence * Decimal("0.25") + Decimal("10")
        if lead_time_defaulted:
            score -= Decimal("15")
        if status == ReorderRecommendationStatus.INSUFFICIENT_DATA:
            score = min(score, Decimal("35"))
        return max(Decimal("0"), min(score, Decimal("100"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _ceil_decimal(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def _positive_int(value) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
