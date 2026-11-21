"""Scoped facts and deterministic financial scenarios for dead-stock recovery."""

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import os
from threading import BoundedSemaphore
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.product import Product
from app.models.promotion import (
    PromotionPlan,
    PromotionPlanStatus,
    PromotionResult,
    PromotionResultStatus,
)
from app.schemas.forecast_inference import ForecastMode
from app.schemas.statistical_forecast import BaselineConfig
from app.scraper.constants import MARKETPLACE_NAME
from app.services.forecast_inference_service import ForecastInferenceService
from app.services.forecast_snapshot_service import (
    ForecastSnapshotService,
    forecast_read_session,
)
from app.services.historical_dataset_service import BUSINESS_TIMEZONE, DAY, _utc
from app.services.margin_guard import MarginGuardResult

_CAPACITY = BoundedSemaphore(1)
SCENARIO_DAYS = 30


def nonnegative_decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return (
        parsed
        if parsed.is_finite() and 0 <= parsed <= Decimal("9999999999.99")
        else None
    )


def money(amount: Decimal) -> str:
    return str(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def holding_cost(product: Product) -> Decimal | None:
    return nonnegative_decimal(
        (product.specifications or {}).get("holding_cost_bdt_per_unit_per_day")
    )


def cash_scenarios(
    quote: MarginGuardResult,
    *,
    quantity: int,
    holding_per_day: Decimal | None,
    duration_days: int,
    baseline: MarginGuardResult | None = None,
) -> list[dict[str, Any]]:
    fees, unit_cost = quote.fee_breakdown.total_fee_amount, quote.unit_cost
    if not quote.is_allowed or fees is None or unit_cost is None:
        return []
    baseline_fees = (
        baseline.fee_breakdown.total_fee_amount
        if baseline is not None and baseline.is_allowed
        else None
    )
    cases = []
    for sold in sorted({0, min(quantity, 1), quantity}):
        remaining = quantity - sold
        net_cash = (quote.candidate_price - fees) * sold
        contribution = net_cash - unit_cost * sold
        cases.append(
            {
                "assumed_units_sold": sold,
                "remaining_units": remaining,
                "gross_revenue_bdt": money(quote.candidate_price * sold),
                "selling_fees_bdt": money(fees * sold),
                "net_cash_bdt": money(net_cash),
                "contribution_bdt": money(contribution),
                "cost_basis_recovered_bdt": money(min(unit_cost * sold, net_cash)),
                "remaining_inventory_cost_basis_bdt": money(unit_cost * remaining),
                "remaining_holding_cost_bdt": money(
                    holding_per_day * remaining * duration_days
                )
                if holding_per_day is not None
                else None,
                "contribution_change_at_same_quantity_bdt": money(
                    (
                        (quote.candidate_price - fees)
                        - (baseline.candidate_price - baseline_fees)
                    )
                    * sold
                )
                if baseline is not None and baseline_fees is not None
                else None,
            }
        )
    return cases


def promotion_observations(
    records: list[tuple[PromotionResult, PromotionPlan | None]],
    *,
    product: Product,
    at: datetime,
) -> dict[str, Any]:
    records = [
        (row, plan)
        for row, plan in records
        if (row.seller_id, row.product_id) == (product.seller_id, product.id)
    ]
    observed, rejected = [], []
    windows = [
        (_utc(row.started_at), _utc(row.ended_at) if row.ended_at else None)
        for row, _ in records
    ]
    for index, (row, plan) in enumerate(records):
        start, end = windows[index]
        raw = row.evidence_json or {}
        reasons = []
        if row.marketplace != MARKETPLACE_NAME or raw.get("currency") != "BDT":
            reasons.append("PROMOTION_MARKET_OR_CURRENCY_UNVERIFIED")
        if (
            row.result_status != PromotionResultStatus.CALCULATED
            or row.missing_data_json
            or row.units_sold is None
            or row.units_sold < 0
            or nonnegative_decimal(row.gross_revenue) is None
            or any(
                value is not None and nonnegative_decimal(value) is None
                for value in (row.spend, row.discount_cost)
            )
            or (row.units_sold == 0 and row.gross_revenue != 0)
        ):
            reasons.append("PROMOTION_OUTCOME_INCOMPLETE_OR_INVALID")
        if not (
            end is not None
            and start < end <= _utc(row.created_at) <= _utc(row.updated_at) <= at
        ):
            reasons.append("PROMOTION_TIMELINE_INVALID")
        if row.promotion_plan_id is not None and (
            plan is None
            or (plan.seller_id, plan.product_id, plan.marketplace)
            != (product.seller_id, product.id, MARKETPLACE_NAME)
            or plan.status != PromotionPlanStatus.COMPLETED
            or _utc(plan.updated_at) > at
        ):
            reasons.append("PROMOTION_PLAN_SCOPE_OR_STATUS_UNVERIFIED")
        if end is not None and any(
            index != other
            and other_end is not None
            and start < other_end
            and other_start < end
            for other, (other_start, other_end) in enumerate(windows)
        ):
            reasons.append("OVERLAPPING_PROMOTION_WINDOWS")
        if reasons:
            rejected.append({"promotion_result_id": str(row.id), "reasons": reasons})
            continue
        assert end is not None and row.units_sold is not None
        offered = raw.get("offered_quantity")
        sell_through = (
            str(Decimal(row.units_sold) / offered)
            if type(offered) is int
            and 0 < offered <= 2_147_483_647
            and row.units_sold <= offered
            else None
        )
        observed.append(
            {
                "promotion_result_id": str(row.id),
                "linked_promotion_plan_id": str(plan.id) if plan is not None else None,
                "planned_discount_rate": str(plan.proposed_discount_rate)
                if plan is not None and plan.proposed_discount_rate is not None
                else None,
                "started_at": start.isoformat(),
                "ended_at": end.isoformat(),
                "recorded_units": row.units_sold,
                "recorded_gross_revenue_bdt": str(row.gross_revenue),
                "reported_offered_quantity": offered
                if sell_through is not None
                else None,
                "observed_sell_through": sell_through,
            }
        )
    return {
        "observed_outcomes": observed,
        "rejected_outcomes": rejected,
        "response_status": "UNKNOWN",
        "uncontrolled_factors": [
            "seasonality",
            "stockouts",
            "sales_coverage",
            "simultaneous_price_changes",
            "campaign_spend",
            "traffic_and_demand_trends",
        ],
    }


def load_recovery_forecast(
    db: Session | None, product: Product, at: datetime
) -> dict[str, Any]:
    if db is None or os.getenv("FORECAST_ML_MODE") != ForecastMode.ENABLED:
        return {"status": "UNAVAILABLE", "reason": "APPROVED_INFERENCE_UNAVAILABLE"}
    if not _CAPACITY.acquire(blocking=False):
        return {"status": "UNAVAILABLE", "reason": "FORECAST_CAPTURE_BUSY"}
    try:
        day = at.astimezone(BUSINESS_TIMEZONE).date()
        config = BaselineConfig()
        inference = ForecastInferenceService.enabled_runtime(product.seller_id, config)
        with forecast_read_session(db) as read:
            snapshot = ForecastSnapshotService(
                read, authorized_seller_id=product.seller_id
            ).capture(
                product_id=product.id,
                start_date=day - config.lookback_days * DAY,
                end_date=day - DAY,
                as_of=at,
            )
        origin = snapshot.captured_at + timedelta(microseconds=1)
        if (
            not at <= origin <= at + timedelta(seconds=30)
            or origin.astimezone(BUSINESS_TIMEZONE).date() != day
            or snapshot.catalog.base_price != product.selling_price
        ):
            return {
                "status": "UNAVAILABLE",
                "reason": "FORECAST_ORIGIN_OR_PRICE_CHANGED",
            }
        result = inference.forecast(snapshot, forecast_origin=origin, horizon_days=30)
        point = result.forecast
        if (
            result.source not in {"active", "previous"}
            or result.mode != ForecastMode.ENABLED
            or result.selection_reason != "APPROVED_MODEL"
            or point.model_name != "catboost"
            or point.expected_units is None
            or (
                point.seller_id,
                point.product_id,
                point.horizon_days,
                point.forecast_origin,
            )
            != (product.seller_id, product.id, 30, origin)
        ):
            return {"status": "UNAVAILABLE", "reason": result.selection_reason}
        return {
            "status": "APPROVED_BASELINE_ONLY",
            "source": result.source,
            "forecast": point.model_dump(mode="json"),
            "uncertainty": point.prediction_interval.model_dump(mode="json")
            if point.prediction_interval
            else {"status": "uncalibrated", "reason": "MODEL_INTERVAL_UNAVAILABLE"},
        }
    except (SQLAlchemyError, ValueError, PermissionError, LookupError):
        return {"status": "UNAVAILABLE", "reason": "FORECAST_EVIDENCE_UNAVAILABLE"}
    finally:
        _CAPACITY.release()
