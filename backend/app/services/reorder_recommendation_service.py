from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from hashlib import sha256
import json
import logging
from typing import Protocol, TypedDict
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.inventory_history import InventoryHistory
from app.models.product import Product
from app.models.reorder_recommendation import (
    FORECAST_REORDER_VERSION,
    ReorderRecommendation,
    ReorderRecommendationAction,
    ReorderRecommendationStatus,
)
from app.models.sales_velocity import SalesVelocity, SalesVelocityDataStatus
from app.models.seller import Seller
from app.models.stockout_prediction import StockoutPrediction
from app.repositories.reorder_recommendation_repository import ReorderRecommendationRepository
from app.services.forecast_reorder_service import (
    MAX_STOCK, REORDER_SPEC_KEYS, ReorderInputs, ReorderPlan, load_reorder_forecast, plan_reorder,
)
from app.services.safety_stock import SafetyStock, product_service_level, variability_safety_stock
from app.services.sales_velocity_service import SalesVelocityCalculation, SalesVelocityService

logger = logging.getLogger(__name__)

# Rows sized with variability safety stock get their own version so they never collide with v1 rows.
VARIABILITY_SAFETY_STOCK_SUFFIX = "+vss"
DemandHistory = tuple[dict[date, int], dict[date, int]]


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
    def daily_demand_history(self, *, seller_id: UUID, product_ids: list[UUID], start: date, end: date) -> dict[UUID, DemandHistory]: ...


class ProductReorderSettings(TypedDict):
    supplier_lead_time_days: int
    supplier_lead_time_defaulted: bool
    safety_buffer_days: int
    review_period_days: int
    minimum_order_quantity: int | None
    pack_size: int | None


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
        self._db = db
        self._forecast_enabled = settings.forecast_aware_reorder_enabled
        self._variability_enabled = settings.variability_safety_stock_enabled
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
        history = self._demand_history(product.seller_id, [product.id], as_of_date).get(product.id)
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
            demand_history=history,
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
                    forecast = self._uses_forecast(batch_seller_id)
                    as_of = as_of_date or (
                        SalesVelocityService.business_date_for_seller(seller, timestamp)
                        if forecast else timestamp.date()
                    )
                    product_ids = [item.id for item in products]
                    inventory = self._repository.latest_inventory_for_products(seller_id=batch_seller_id, product_ids=product_ids, as_of_date=as_of)
                    through = as_of - timedelta(days=1) if forecast else as_of
                    velocities = self._repository.latest_velocity_for_products(seller_id=batch_seller_id, product_ids=product_ids, as_of_date=through)
                    stockouts = {} if forecast else self._repository.latest_stockout_for_products(seller_id=batch_seller_id, product_ids=product_ids, as_of_date=as_of)
                    histories = self._demand_history(batch_seller_id, product_ids, as_of)
                    for product in products:
                        recommendation = self.build_recommendation(
                            product=product,
                            seller=seller,
                            inventory_snapshot=inventory.get(product.id),
                            sales_velocity=velocities.get(product.id),
                            stockout_prediction=stockouts.get(product.id),
                            as_of_date=as_of,
                            generated_at=(
                                datetime.now(timezone.utc)
                                if forecast and generated_at is None else timestamp
                            ),
                            calculation_version=version,
                            demand_history=histories.get(product.id),
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
        sales_velocity: SalesVelocity | SalesVelocityCalculation | None,
        stockout_prediction: StockoutPrediction | None,
        as_of_date: date,
        generated_at: datetime,
        calculation_version: str,
        confirmed_incoming_quantity: int | None = None,
        verified_zero_sales: bool = False,
        demand_history: DemandHistory | None = None,
    ) -> ReorderRecommendation:
        arguments = dict(
            product=product, seller=seller, inventory_snapshot=inventory_snapshot, sales_velocity=sales_velocity,
            stockout_prediction=stockout_prediction, as_of_date=as_of_date, generated_at=generated_at,
            calculation_version=calculation_version, confirmed_incoming_quantity=confirmed_incoming_quantity,
            verified_zero_sales=verified_zero_sales, demand_history=demand_history,
        )
        primary = self._uses_forecast(product.seller_id)
        recommendation = self._build_single(use_forecast=primary, **arguments)  # type: ignore[arg-type]
        if settings.forecast_aware_reorder_shadow_enabled:
            # Shadow only records the other method's advice for comparison; it never changes the decision.
            try:
                shadow = self._build_single(use_forecast=not primary, **arguments)  # type: ignore[arg-type]
                summary: dict[str, object] = _shadow_summary(shadow, forecast=not primary)
            except Exception as exc:  # the shadow must never block the primary advice
                self._log.warning("Reorder shadow failed product_id=%s error=%s", product.id, type(exc).__name__)
                summary = {"method": "forecast_aware" if not primary else "standard", "error": type(exc).__name__}
            recommendation.evidence = {**recommendation.evidence, "shadow": summary}
        return recommendation

    def _build_single(
        self,
        *,
        use_forecast: bool,
        product: Product,
        seller: Seller,
        inventory_snapshot: InventoryHistory | None,
        sales_velocity: SalesVelocity | SalesVelocityCalculation | None,
        stockout_prediction: StockoutPrediction | None,
        as_of_date: date,
        generated_at: datetime,
        calculation_version: str,
        confirmed_incoming_quantity: int | None = None,
        verified_zero_sales: bool = False,
        demand_history: DemandHistory | None = None,
    ) -> ReorderRecommendation:
        settings_snapshot = self._product_reorder_settings(product)
        if use_forecast:
            return self._build_forecast_recommendation(
                product=product, seller=seller, inventory=inventory_snapshot,
                velocity=sales_velocity, calculation_version=calculation_version,
                inputs=ReorderInputs(
                    lead_days=_positive_int(product.supplier_lead_time),
                    review_days=settings_snapshot["review_period_days"],
                    buffer_days=settings_snapshot["safety_buffer_days"],
                    minimum_order=settings_snapshot["minimum_order_quantity"],
                    pack_size=settings_snapshot["pack_size"],
                    business_date=as_of_date,
                    evaluated_at=_ensure_utc(generated_at),
                    confirmed_incoming=confirmed_incoming_quantity,
                    verified_zero_sales=verified_zero_sales,
                ),
            )
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

        safety = None
        if self._variability_enabled:
            calculation_version = f"{calculation_version}{VARIABILITY_SAFETY_STOCK_SUFFIX}"
            if demand_history is None:
                safety = SafetyStock("history_unavailable")
            else:
                units_by_day, available_by_day = demand_history
                safety = variability_safety_stock(
                    units_by_day=units_by_day,
                    available_by_day=available_by_day,
                    start=as_of_date - timedelta(days=settings.reorder_safety_stock_history_days - 1),
                    end=as_of_date,
                    lead_time_days=lead_time,
                    service_level=product_service_level(getattr(product, "specifications", None), settings.reorder_safety_stock_service_level),
                    min_days=settings.reorder_safety_stock_min_days,
                )
        if safety is not None and safety.status == "ok" and safety.units is not None:
            safety_stock = Decimal(safety.units)
            reorder_point = _ceil_decimal(rate * Decimal(lead_time)) + safety.units
            target_stock = _ceil_decimal(rate * Decimal(lead_time + review_days)) + safety.units
        else:
            safety_stock = rate * Decimal(safety_days)
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
            "safety_stock": str(safety_stock.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
            "safety_stock_method": "variability" if safety is not None and safety.status == "ok" else "buffer_days",
            **(safety.evidence() if safety is not None else {}),
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

    def _build_forecast_recommendation(
        self,
        *,
        product: Product,
        seller: Seller,
        inventory: InventoryHistory | None,
        velocity: SalesVelocity | SalesVelocityCalculation | None,
        inputs: ReorderInputs,
        calculation_version: str,
    ) -> ReorderRecommendation:
        scope = (product.seller_id, product.id)
        if seller.id != product.seller_id or any(
            (item.seller_id, item.product_id) != scope
            for item in (inventory, velocity) if item is not None
        ):
            raise ValueError("Reorder inputs outside authorized seller and product scope.")
        forecast, reason = load_reorder_forecast(
            self._db, seller_id=scope[0], product_id=scope[1], inputs=inputs,
        )
        plan = plan_reorder(
            product=product, inventory=inventory, velocity=velocity, inputs=inputs,
            forecast=forecast, forecast_reason=reason,
        )
        if plan.insufficient_reason:
            explanation = "Inventory, supplier, or demand evidence is insufficient for an actionable reorder plan."
        elif plan.quantity:
            explanation = "Available stock is expected to reach the reorder point within the planning horizon."
        elif "CHECK_EXISTING_RECEIPTS_BEFORE_ORDERING" in plan.evidence["reason_codes"]:
            explanation = "Review the timing of existing confirmed receipts before ordering additional units."
        elif "REORDER_CONSTRAINED_BY_CAPACITY_OR_BUDGET" in plan.evidence["reason_codes"]:
            explanation = "Available capacity or budget cannot support an order that meets the supplier terms."
        else:
            explanation = "No additional order is recommended within the planning horizon."
        version = _forecast_plan_version(product, inventory, velocity, inputs, calculation_version, plan)
        return ReorderRecommendation(
            seller_id=scope[0], product_id=scope[1],
            inventory_snapshot_id=inventory.id if inventory is not None else None,
            sales_velocity_id=velocity.id if isinstance(velocity, SalesVelocity) else None,
            as_of_date=inputs.business_date,
            action=ReorderRecommendationAction.REORDER if plan.quantity else ReorderRecommendationAction.HOLD,
            recommended_quantity=plan.quantity,
            reorder_deadline=plan.deadline,
            supplier_lead_time_days=inputs.lead_days or 0,
            safety_buffer_days=min(MAX_STOCK, inputs.buffer_days),
            review_period_days=min(MAX_STOCK, inputs.review_days),
            reorder_point=plan.reorder_point,
            target_stock=plan.target_stock,
            inventory_position=plan.inventory_position,
            daily_sales_rate=plan.rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            confidence_score=Decimal("0") if plan.insufficient_reason else (
                Decimal("60") if plan.evidence["uncertainty"]["status"] == "validated_lead_time_upper_bound"
                else min(Decimal("50"), velocity.confidence_score) if velocity else Decimal("45")
            ),
            recommendation_status=(
                ReorderRecommendationStatus.INSUFFICIENT_DATA
                if plan.insufficient_reason else ReorderRecommendationStatus.OPEN
            ),
            explanation=explanation,
            evidence={**plan.evidence, "calculation_version": version, "planning_method": FORECAST_REORDER_VERSION},
            calculation_version=version,
            generated_at=inputs.evaluated_at,
        )

    def _uses_forecast(self, seller_id: UUID) -> bool:
        """Forecast-aware planning when the flag is on and the seller is allow-listed (an empty list means all)."""
        if not self._forecast_enabled:
            return False
        allowed = forecast_reorder_allowlist()
        return not allowed or str(seller_id).lower() in allowed

    def _demand_history(self, seller_id: UUID, product_ids: list[UUID], as_of_date: date) -> dict[UUID, DemandHistory]:
        if not self._variability_enabled or (self._uses_forecast(seller_id) and not settings.forecast_aware_reorder_shadow_enabled):
            return {}
        return self._repository.daily_demand_history(
            seller_id=seller_id,
            product_ids=product_ids,
            start=as_of_date - timedelta(days=settings.reorder_safety_stock_history_days - 1),
            end=as_of_date,
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
        if status == ReorderRecommendationStatus.ORDERED and getattr(recommendation, "ordered_at", None) is None:
            recommendation.ordered_at = datetime.now(timezone.utc)
        return self._repository.save_status(recommendation)

    def _product_reorder_settings(self, product: Product) -> ProductReorderSettings:
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


def _forecast_plan_version(
    product: Product,
    inventory: InventoryHistory | None,
    velocity: SalesVelocity | SalesVelocityCalculation | None,
    inputs: ReorderInputs,
    base_version: str,
    plan: ReorderPlan,
) -> str:
    # The existing uniqueness key includes the version. Keep replay stable
    # while allowing new advice after material changes to inputs on the same day.
    specs = product.specifications or {}
    material = (
        # Capture timestamps vary between retries. The accepted model and actual
        # planning outputs determine whether the persisted advice is reusable.
        plan.evidence["demand_source"], plan.evidence["forecast_version"],
        plan.evidence["lead_time_demand"], plan.evidence["uncertainty"],
        plan.quantity, plan.reorder_point, plan.target_stock, plan.insufficient_reason,
        base_version, product.updated_at, product.stock_quantity, product.cost_price,
        inputs.lead_days, inputs.review_days, inputs.buffer_days, inputs.minimum_order,
        inputs.pack_size, inputs.confirmed_incoming, inputs.verified_zero_sales,
        settings.reorder_target_service_level, settings.reorder_maximum_recommendation_horizon_days,
        {key: specs.get(key) for key in REORDER_SPEC_KEYS | {"minimum_order_quantity", "moq", "pack_size", "case_size"}},
        (inventory.id, inventory.captured_at, inventory.quantity_reserved) if inventory is not None else None,
        (velocity.as_of_date, velocity.calculation_version, velocity.daily_sales_rate, velocity.net_units_sold) if velocity is not None else None,
    )
    digest = sha256(json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()
    return f"fr-v1-{digest[:14]}"


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


def forecast_reorder_allowlist() -> set[str]:
    return {item.strip().lower() for item in settings.forecast_aware_reorder_seller_allowlist.split(",") if item.strip()}


def _shadow_summary(recommendation: ReorderRecommendation, *, forecast: bool) -> dict[str, object]:
    return {
        "method": "forecast_aware" if forecast else "standard",
        "action": recommendation.action.value,
        "status": recommendation.recommendation_status.value,
        "recommended_quantity": recommendation.recommended_quantity,
        "reorder_point": recommendation.reorder_point,
        "reorder_deadline": recommendation.reorder_deadline.isoformat() if recommendation.reorder_deadline else None,
        "calculation_version": recommendation.calculation_version,
    }


def summarize_shadow(recommendations: list[ReorderRecommendation]) -> dict[str, object]:
    """Agreement between primary advice and its recorded shadow, for the rollout decision."""
    compared = [row for row in recommendations if isinstance((row.evidence or {}).get("shadow"), dict) and "error" not in row.evidence["shadow"]]
    failed = sum(1 for row in recommendations if isinstance((row.evidence or {}).get("shadow"), dict) and "error" in row.evidence["shadow"])
    same_action = sum(1 for row in compared if row.evidence["shadow"]["action"] == row.action.value)
    gaps = [abs(int(row.evidence["shadow"]["recommended_quantity"] or 0) - int(row.recommended_quantity or 0)) for row in compared]
    return {
        "recommendations": len(recommendations),
        "compared": len(compared),
        "shadow_failures": failed,
        "same_action_rate": round(same_action / len(compared), 4) if compared else None,
        "mean_quantity_gap": round(sum(gaps) / len(gaps), 2) if gaps else None,
        "primary_reorders_only": sum(1 for row in compared if row.action.value == "REORDER" and row.evidence["shadow"]["action"] != "REORDER"),
        "shadow_reorders_only": sum(1 for row in compared if row.action.value != "REORDER" and row.evidence["shadow"]["action"] == "REORDER"),
    }
