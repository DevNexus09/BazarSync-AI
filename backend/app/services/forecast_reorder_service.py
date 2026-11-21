"""Use approved lead-time demand and verified inventory for advisory reorder plans."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from threading import BoundedSemaphore
from typing import Any
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.inventory_history import InventoryHistory, InventorySnapshotSource
from app.models.product import Product
from app.models.sales_velocity import SalesVelocity, SalesVelocityDataStatus
from app.schemas.demand_regime import DemandRegime
from app.schemas.forecast_inference import ForecastInferenceResult, ForecastMode
from app.schemas.statistical_forecast import BaselineConfig
from app.services.forecast_backtesting_service import HORIZONS
from app.services.forecast_inference_service import ForecastInferenceService
from app.services.forecast_snapshot_service import (
    ForecastSnapshotService,
    forecast_read_session,
)
from app.services.historical_dataset_service import BUSINESS_TIMEZONE, DAY, _utc
from app.services.sales_velocity_service import SalesVelocityCalculation

MAX_STOCK = 2_147_483_647
MAX_RATE = Decimal("99999999.9999")
REORDER_SPEC_KEYS = {
    "maximum_stock",
    "storage_capacity_units",
    "reorder_budget_bdt",
    "confirmed_incoming_quantity",
    "confirmed_incoming_date",
}
_CAPACITY = BoundedSemaphore(1)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReorderInputs:
    lead_days: int | None
    review_days: int
    buffer_days: int
    minimum_order: int | None
    pack_size: int | None
    business_date: date
    evaluated_at: datetime
    confirmed_incoming: int | None
    verified_zero_sales: bool


@dataclass(frozen=True)
class ReorderPlan:
    quantity: int
    reorder_point: int
    target_stock: int
    inventory_position: int
    rate: Decimal
    deadline: date | None
    evidence: dict[str, Any]
    insufficient_reason: str | None


def load_reorder_forecast(
    db: Session | None, *, seller_id: UUID, product_id: UUID, inputs: ReorderInputs
) -> tuple[ForecastInferenceResult | None, str]:
    lead = next((horizon for horizon in HORIZONS if horizon == inputs.lead_days), None)
    if lead is None:
        return None, "LEAD_TIME_HORIZON_UNSUPPORTED"
    if db is None or os.getenv("FORECAST_ML_MODE") != ForecastMode.ENABLED:
        return None, "APPROVED_INFERENCE_UNAVAILABLE"
    if inputs.evaluated_at.astimezone(BUSINESS_TIMEZONE).date() != inputs.business_date:
        return None, "FORECAST_BUSINESS_DATE_MISMATCH"
    if not _CAPACITY.acquire(blocking=False):
        return None, "FORECAST_CAPTURE_BUSY"
    try:
        config = BaselineConfig()
        inference = ForecastInferenceService.enabled_runtime(seller_id, config)
        with forecast_read_session(db) as read:
            snapshot = ForecastSnapshotService(
                read, authorized_seller_id=seller_id
            ).capture(
                product_id=product_id,
                start_date=inputs.business_date - config.lookback_days * DAY,
                end_date=inputs.business_date - DAY,
                as_of=inputs.evaluated_at,
            )
        origin = snapshot.captured_at + timedelta(microseconds=1)
        if (
            not inputs.evaluated_at
            <= origin
            <= inputs.evaluated_at + timedelta(seconds=30)
            or origin.astimezone(BUSINESS_TIMEZONE).date() != inputs.business_date
        ):
            return None, "FORECAST_ORIGIN_STALE"
        result = inference.forecast(snapshot, forecast_origin=origin, horizon_days=lead)
        return result, result.selection_reason
    except (SQLAlchemyError, ValueError, PermissionError, LookupError) as exc:
        logger.warning("reorder_forecast_unavailable error_type=%s", type(exc).__name__)
        return None, "FORECAST_EVIDENCE_UNAVAILABLE"
    finally:
        _CAPACITY.release()


def approved_reorder_forecast(
    result: ForecastInferenceResult | None,
    *,
    seller_id: UUID,
    product_id: UUID,
    lead_days: int | None,
    business_date: date,
    evaluated_at: datetime,
) -> bool:
    if result is None:
        return False
    point = result.forecast
    return (
        result.mode == ForecastMode.ENABLED
        and result.source in {"active", "previous"}
        and result.selection_reason == "APPROVED_MODEL"
        and result.demand_regime == DemandRegime.REGULAR
        and point.model_name == "catboost"
        and point.expected_units is not None
        and 0 <= point.expected_units <= MAX_STOCK
        and (point.seller_id, point.product_id, point.horizon_days)
        == (seller_id, product_id, lead_days)
        and evaluated_at
        <= point.forecast_origin
        <= evaluated_at + timedelta(seconds=30)
        and point.data_cutoff < point.forecast_origin
        and point.target_start_date == business_date + DAY
        and point.target_end_date == business_date + point.horizon_days * DAY
    )


def plan_reorder(
    *,
    product: Product,
    inventory: InventoryHistory | None,
    velocity: SalesVelocity | SalesVelocityCalculation | None,
    inputs: ReorderInputs,
    forecast: ForecastInferenceResult | None,
    forecast_reason: str,
) -> ReorderPlan:
    specs = product.specifications or {}
    on_hand = (
        inventory.quantity_on_hand if inventory is not None else product.stock_quantity
    )
    reserved = inventory.quantity_reserved if inventory is not None else None
    available = on_hand - reserved if reserved is not None else None
    incoming, eta, incoming_source, inventory_terms_valid = _incoming(specs, inputs)
    position = (available or 0) + incoming
    lead = inputs.lead_days
    if forecast is not None and (
        forecast.forecast.seller_id,
        forecast.forecast.product_id,
        forecast.forecast.horizon_days,
    ) != (product.seller_id, product.id, lead):
        forecast = None
        forecast_reason = "FORECAST_SCOPE_OR_HORIZON_MISMATCH"
    days_to_receipt = (eta - inputs.business_date).days if eta is not None else None
    inbound_before_receipt = (
        incoming
        if days_to_receipt is not None
        and lead is not None
        and 0 <= days_to_receipt < lead
        else 0
    )
    inbound_for_target = (
        0
        if lead is not None
        and days_to_receipt is not None
        and days_to_receipt > lead + inputs.review_days
        else incoming
    )
    reasons: list[str] = []
    if not _inventory_usable(product, inventory, inputs):
        reasons.append("INVENTORY_EVIDENCE_UNAVAILABLE")
    if lead is None:
        reasons.append("SUPPLIER_LEAD_TIME_UNAVAILABLE")
    if not inventory_terms_valid or abs(position) > MAX_STOCK:
        reasons.append("INVALID_CONFIRMED_INCOMING")
    if any(
        not _bounded_int(specs[key])
        for key in ("minimum_order_quantity", "moq", "pack_size", "case_size")
        if specs.get(key) is not None
    ):
        reasons.append("INVALID_SUPPLIER_ORDER_TERMS")
    if incoming and not inbound_before_receipt:
        reasons.append("CONFIRMED_INCOMING_NOT_ASSURED_WITHIN_LEAD_TIME")

    rate: Decimal | None = None
    expected: Decimal | None = None
    validated_upper: Decimal | None = None
    source = "unavailable"
    level = settings.reorder_target_service_level
    uncertainty: dict[str, Any] = {
        "status": "unavailable",
        "stockout_probability": None,
        "target_service_level": str(level),
        "lead_time_uncertainty": "NO_VERIFIED_SUPPLIER_DELIVERY_HISTORY",
    }
    if forecast is not None and approved_reorder_forecast(
        forecast,
        seller_id=product.seller_id,
        product_id=product.id,
        lead_days=lead,
        business_date=inputs.business_date,
        evaluated_at=inputs.evaluated_at,
    ):
        assert lead is not None and forecast.forecast.expected_units is not None
        source = "approved_forecast"
        expected = forecast.forecast.expected_units
        rate = expected / lead
        calibration = forecast.lead_time_calibration
        uncertainty["status"] = "uncalibrated"
        if (
            calibration is not None
            and calibration.product_id == product.id
            and calibration.validation_outcomes_available_at
            < forecast.forecast.forecast_origin
        ):
            lower_coverage = calibration.coverage_lower_bound
            uncertainty.update(calibration.model_dump(mode="json"))
            uncertainty["coverage_lower_bound"] = str(lower_coverage)
            if calibration.nominal_level >= level and lower_coverage >= level:
                validated_upper = expected + calibration.radius_units
                uncertainty["status"] = "validated_lead_time_upper_bound"
            else:
                uncertainty["status"] = "service_level_unsupported"
        uncertainty["upper_lead_time_demand_units"] = (
            str(validated_upper) if validated_upper is not None else None
        )
    elif lead is not None:
        rate = _velocity_rate(velocity, inputs)
        if rate is not None:
            source = "recorded_sales_velocity"
            expected = rate * lead
        else:
            reasons.append("INSUFFICIENT_DEMAND_EVIDENCE")

    # Keep the configured time buffer as a planning floor. A validated bound
    # can add safety stock but is never scaled to a different horizon.
    point = target = raw = quantity = 0
    safety: int | None = None
    sellable_cover: Decimal | None = None
    deadline = None
    insufficiency = next(
        (
            reason
            for reason in reasons
            if reason != "CONFIRMED_INCOMING_NOT_ASSURED_WITHIN_LEAD_TIME"
        ),
        None,
    )
    limits, limit_reason = _order_limits(specs, product.cost_price, on_hand, incoming)
    if limit_reason is not None:
        reasons.append(limit_reason)
        insufficiency = insufficiency or limit_reason
    if (
        expected is not None
        and rate is not None
        and available is not None
        and insufficiency is None
    ):
        protection = max(
            expected + rate * inputs.buffer_days, validated_upper or Decimal(0)
        )
        point = _ceil(protection)
        safety = point - _ceil(expected)
        target = _ceil(protection + rate * inputs.review_days)
        if rate > 0:
            sellable_cover = Decimal(max(0, available)) / rate
        if (
            max(target, inputs.buffer_days, inputs.review_days) > MAX_STOCK
            or rate > MAX_RATE
        ):
            point = target = 0
            insufficiency = "REORDER_PLAN_OUTSIDE_SUPPORTED_RANGE"
            reasons.append(insufficiency)
        elif target > 0:
            # A receipt with no usable date can reduce the purchase quantity, but
            # can't delay the review or certify stock coverage before it arrives.
            deadline = _deadline(inputs.business_date, available, point, rate)
            raw = max(0, target - (available + inbound_for_target))
            quantity = _constrained_quantity(raw, inputs, limits)
            if quantity < raw or (quantity == 0 and raw > 0):
                reasons.append("REORDER_CONSTRAINED_BY_CAPACITY_OR_BUDGET")
            if raw == 0 and available < point and incoming:
                reasons.append("CHECK_EXISTING_RECEIPTS_BEFORE_ORDERING")
            if (
                deadline is None
                or (deadline - inputs.business_date).days
                > settings.reorder_maximum_recommendation_horizon_days
            ):
                quantity = 0

    if available is not None and insufficiency is None and validated_upper is not None:
        uncertainty["stockout_risk"] = (
            "ON_HAND_BELOW_VALIDATED_LEAD_TIME_BOUND"
            if available < validated_upper
            else "ON_HAND_COVERS_VALIDATED_LEAD_TIME_BOUND"
        )
    if source != "approved_forecast":
        reasons.append(
            "FORECAST_SCOPE_OR_HORIZON_MISMATCH"
            if forecast_reason == "APPROVED_MODEL"
            else forecast_reason
        )
    if expected == 0 and validated_upper is None:
        reasons.append("ZERO_ESTIMATED_DEMAND")
    evidence = {
        "planning_date": inputs.business_date.isoformat(),
        "demand_source": source,
        "forecast_reason": forecast_reason,
        "forecast": forecast.model_dump(mode="json")
        if source == "approved_forecast" and forecast
        else None,
        "forecast_version": forecast.forecast.model_version
        if source == "approved_forecast" and forecast
        else None,
        "demand_regime": forecast.demand_regime.value
        if forecast and forecast.demand_regime
        else None,
        "velocity_evidence": (
            {
                "through": velocity.as_of_date.isoformat(),
                "version": velocity.calculation_version,
                "status": velocity.data_status.value,
                "sales_days": velocity.sales_days,
                "window_days": velocity.window_days,
                "verified_zero_sales": inputs.verified_zero_sales,
            }
            if source == "recorded_sales_velocity" and velocity is not None
            else None
        ),
        "current_stock": on_hand,
        "reserved_stock": reserved,
        "available_stock": available,
        "confirmed_incoming": incoming,
        "confirmed_incoming_source": incoming_source,
        "confirmed_incoming_date": eta.isoformat() if eta is not None else None,
        "confirmed_incoming_before_supplier_receipt": inbound_before_receipt,
        "confirmed_incoming_counted_toward_target": inbound_for_target,
        "unconfirmed_snapshot_incoming": inventory.quantity_incoming
        if inventory is not None
        else None,
        "inventory_position": position
        if available is not None and abs(position) <= MAX_STOCK
        else None,
        "backorders": None,
        "supplier_lead_time_days": lead,
        "supplier_lead_time_defaulted": False,
        "lead_time_demand": str(expected) if expected is not None else None,
        "safety_stock": str(safety)
        if safety is not None and insufficiency is None
        else None,
        "review_period_days": inputs.review_days,
        "safety_buffer_days": inputs.buffer_days,
        "on_hand_coverage_days": str(sellable_cover.quantize(Decimal("0.01")))
        if sellable_cover is not None
        else None,
        "daily_sales_rate": str(rate) if rate is not None else None,
        "reorder_point": point if insufficiency is None else None,
        "target_stock": target if insufficiency is None else None,
        "minimum_order_quantity": inputs.minimum_order,
        "pack_size": inputs.pack_size,
        "order_limits": limits,
        "raw_reorder_quantity": raw if insufficiency is None else None,
        "recommended_quantity": quantity,
        "maximum_recommendation_horizon_days": settings.reorder_maximum_recommendation_horizon_days,
        "uncertainty": uncertainty,
        "reason_codes": reasons,
        "insufficient_reason": insufficiency,
    }
    return ReorderPlan(
        quantity,
        point,
        target,
        position if available is not None and abs(position) <= MAX_STOCK else 0,
        rate if rate is not None and rate <= MAX_RATE else Decimal(0),
        deadline,
        evidence,
        insufficiency,
    )


def _incoming(specs: dict, inputs: ReorderInputs) -> tuple[int, date | None, str, bool]:
    explicit = inputs.confirmed_incoming
    units = (
        explicit if explicit is not None else specs.get("confirmed_incoming_quantity")
    )
    source = (
        "explicit_quantity"
        if explicit is not None
        else "seller_declared"
        if units is not None
        else "none"
    )
    if units is None:
        return 0, None, source, True
    quantity = _bounded_int(units)
    eta = None
    if (
        explicit is None
        and quantity
        and specs.get("confirmed_incoming_date") is not None
    ):
        try:
            eta = date.fromisoformat(specs["confirmed_incoming_date"])
        except (TypeError, ValueError):
            return quantity, None, source, False
    return quantity or 0, eta, source, quantity is not None


def _inventory_usable(
    product: Product, inventory: InventoryHistory | None, inputs: ReorderInputs
) -> bool:
    return (
        inventory is not None
        and inventory.source != InventorySnapshotSource.BACKFILL
        and inventory.snapshot_date <= inputs.business_date
        and timedelta(0)
        <= inputs.evaluated_at - _utc(inventory.captured_at)
        <= timedelta(hours=settings.recommendation_inventory_max_age_hours)
        and inventory.quantity_on_hand == product.stock_quantity
        and inventory.quantity_available
        == inventory.quantity_on_hand - inventory.quantity_reserved
    )


def _velocity_rate(
    velocity: SalesVelocity | SalesVelocityCalculation | None, inputs: ReorderInputs
) -> Decimal | None:
    if (
        velocity is None
        or not 1 <= (inputs.business_date - velocity.as_of_date).days <= 2
    ):
        return None
    if (
        isinstance(velocity, SalesVelocity)
        and _utc(velocity.calculated_at) > inputs.evaluated_at
    ):
        return None
    rate = velocity.daily_sales_rate
    if rate == 0 and inputs.verified_zero_sales:
        return rate
    if (
        velocity.data_status == SalesVelocityDataStatus.INSUFFICIENT
        or velocity.confidence_score
        < Decimal(str(settings.reorder_minimum_velocity_confidence))
        or not 0 < rate <= MAX_RATE
    ):
        return None
    return rate


def _order_limits(
    specs: dict, unit_cost: Decimal | None, on_hand: int, incoming: int
) -> tuple[dict[str, Any], str | None]:
    limits: dict[str, Any] = {"max_order_units": MAX_STOCK - on_hand - incoming}
    for key in ("maximum_stock", "storage_capacity_units"):
        if specs.get(key) is not None:
            maximum = _bounded_int(specs[key])
            if maximum is None:
                return limits, "INVALID_REORDER_STOCK_LIMIT"
            limits[key] = maximum
            limits["max_order_units"] = min(
                limits["max_order_units"], maximum - on_hand - incoming
            )
    if specs.get("reorder_budget_bdt") is not None:
        try:
            budget = Decimal(str(specs["reorder_budget_bdt"]))
        except InvalidOperation:
            return limits, "INVALID_REORDER_BUDGET"
        if not budget.is_finite() or not 0 <= budget <= Decimal("999999999999.99"):
            return limits, "INVALID_REORDER_BUDGET"
        if unit_cost is None or not unit_cost.is_finite() or unit_cost <= 0:
            return limits, "REORDER_BUDGET_UNIT_COST_UNAVAILABLE"
        limits.update(
            reorder_budget_bdt=str(budget),
            unit_cost_bdt=str(unit_cost),
            max_order_units=min(limits["max_order_units"], int(budget // unit_cost)),
        )
    limits["max_order_units"] = max(0, limits["max_order_units"])
    return limits, None


def _bounded_int(value: object) -> int | None:
    if type(value) is int:
        result = value
    elif (
        isinstance(value, str)
        and value.isascii()
        and value.isdecimal()
        and len(value) <= 10
    ):
        result = int(value)
    else:
        return None
    return result if 0 <= result <= MAX_STOCK else None


def _ceil(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def _deadline(today: date, available: int, point: int, rate: Decimal) -> date | None:
    if available <= point:
        return today
    if rate <= 0:
        return None
    days = ((available - point) / rate).to_integral_value(rounding=ROUND_FLOOR)
    return (
        today + timedelta(days=int(days)) if days <= (date.max - today).days else None
    )


def _constrained_quantity(
    raw: int, inputs: ReorderInputs, limits: dict[str, Any]
) -> int:
    if raw <= 0:
        return 0
    pack = inputs.pack_size or 1
    min_order = inputs.minimum_order or 1
    required = (max(raw, min_order) + pack - 1) // pack * pack
    capped = min(required, limits["max_order_units"] // pack * pack)
    return capped if capped >= min_order else 0
