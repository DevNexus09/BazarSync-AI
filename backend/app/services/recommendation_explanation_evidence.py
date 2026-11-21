"""Build the explanation input from the final guarded recommendation."""

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Literal

from app.ai.schemas import (
    ALLOWED_ACTIONS,
    CONFIDENCE_LABELS,
    ExplanationEvidence,
    ExplanationMarginGuard,
    ExplanationMetric,
    ExplanationMetricKey,
)
from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryAction
from app.models.product import Product
from app.schemas.recommendation_candidate import RecoveryParameters, ReorderParameters
from app.services.recommendation_selection import RecommendationDecision

_CODE = re.compile(r"[A-Z][A-Z_0-9]{0,63}")
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,79}")
_UNCERTAINTY = {
    "unavailable",
    "uncalibrated",
    "empirical_unvalidated",
    "insufficient_data",
    "validated_lead_time_upper_bound",
    "service_level_unsupported",
    "sensitivity_band",
    "prediction_interval",
}


def _mapping(value: object) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _codes(values: object) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        return ()
    return tuple(
        dict.fromkeys(
            value
            for value in values
            if isinstance(value, str) and _CODE.fullmatch(value)
        )
    )[:24]


def build_explanation_evidence(
    *,
    product: Product,
    action: ALLOWED_ACTIONS,
    confidence: CONFIDENCE_LABELS,
    target_price: Decimal | None,
    analytics: Mapping,
    guard: Mapping,
    decision: RecommendationDecision | None,
    evaluated_at: datetime,
    market_observed_at: datetime | None,
) -> ExplanationEvidence:
    metrics: dict[ExplanationMetricKey, ExplanationMetric] = {}

    def add(
        key: ExplanationMetricKey,
        value: object,
        provenance: Literal["verified", "estimated"] = "verified",
    ) -> None:
        if value is None or isinstance(value, bool):
            return
        try:
            metrics[key] = ExplanationMetric(
                value=Decimal(str(value)), provenance=provenance
            )
        except (ValueError, InvalidOperation):
            return

    add("current_price", product.selling_price)
    add("target_price", target_price)
    add("competitor_median", analytics.get("competitor_median_price"))
    codes = _codes(analytics.get("reason_codes"))
    primary = decision.primary if decision else None
    supports: list[DeadStockRecoveryAction] = []
    inventory_at = None
    sales_through = None
    forecast_version = uncertainty = None
    inventory = _mapping(analytics.get("inventory_evidence"))
    if decision is not None:
        ctx = decision.context
        if ctx.inventory and not {
            "PRODUCT_INPUTS_CHANGED",
            "INVENTORY_EVIDENCE_CHANGED",
        }.intersection(codes):
            add("available_units", ctx.inventory.available_units)
            inventory_at = ctx.inventory.captured_at
        add(
            "daily_sales_rate",
            ctx.sales.rate,
            "verified" if ctx.sales.status == "OBSERVED" else "estimated",
        )
        sales_through = ctx.sales.through if ctx.sales.rate is not None else None
        selected = ((primary,) if primary else ()) + decision.supporting
        for candidate in selected:
            params = candidate.proposed_parameters
            if isinstance(params, RecoveryParameters):
                supports.append(params.action)
            elif (
                candidate is primary
                and isinstance(params, ReorderParameters)
                and action == "REORDER"
            ):
                add("reorder_quantity", params.quantity)
        for candidate in selected:
            snapshot = candidate.evidence.snapshot
            baseline = _mapping(_mapping(snapshot.get("inputs")).get("baseline_demand"))
            forecast_version = snapshot.get("forecast_version") or _mapping(
                baseline.get("forecast")
            ).get("model_version")
            status = _mapping(snapshot.get("uncertainty")).get("status")
            status = status or _mapping(baseline.get("uncertainty")).get("status")
            if baseline.get("status") == "UNAVAILABLE":
                status = "unavailable"
            if isinstance(status, str) and status in _UNCERTAINTY:
                uncertainty = status
            if candidate.forecast_risk is not None:
                forecast_version = (
                    forecast_version or candidate.forecast_risk.calculation_version
                )
                if candidate.forecast_risk.interval is not None:
                    uncertainty = candidate.forecast_risk.interval.kind
            if forecast_version or uncertainty:
                break
        if action == "HOLD" and not primary:
            for item in decision.evaluations:
                if item.guard and item.guard.get("is_allowed") is False:
                    guard = item.guard
                    break
    else:
        if (
            inventory.get("inventory_snapshot_id")
            and inventory.get("on_hand_units") == product.stock_quantity
        ):
            add("available_units", inventory.get("available_units"))
            stamp = inventory.get("inventory_captured_at")
            inventory_at = (
                datetime.fromisoformat(stamp) if isinstance(stamp, str) else None
            )
        demand = inventory.get("demand_status")
        if demand in ("OBSERVED", "ESTIMATED_FROM_RECORDED_SALES"):
            add(
                "daily_sales_rate",
                inventory.get("daily_net_sales_rate"),
                "verified" if demand == "OBSERVED" else "estimated",
            )
            through = inventory.get("through")
            sales_through = (
                date.fromisoformat(through) if isinstance(through, str) else None
            )
        if action == "REORDER":
            add(
                "reorder_quantity",
                _mapping(inventory.get("reorder")).get("recommended_quantity"),
            )
    rejects = _codes(guard.get("rejection_reasons"))
    fee = guard.get("policy_version")
    return ExplanationEvidence(
        action=action,
        confidence=confidence,
        metrics=metrics,
        evaluated_at=evaluated_at,
        inventory_observed_at=inventory_at,
        sales_through=sales_through,
        market_observed_at=market_observed_at
        if "competitor_median" in metrics
        else None,
        reason_codes=codes,
        margin_guard=ExplanationMarginGuard(
            status="blocked"
            if action == "HOLD"
            and (
                bool(rejects)
                or "MARGIN_GUARD_BLOCKED" in codes
                or "MARGIN_GUARD_BLOCKED_PRICE_RECOMMENDATION" in codes
            )
            else "approved"
            if guard.get("is_allowed") is True and target_price is not None
            else "not_evaluated",
            rejection_reasons=rejects,
            fee_policy_version=fee
            if isinstance(fee, str) and _VERSION.fullmatch(fee)
            else None,
        ),
        forecast_version=forecast_version
        if isinstance(forecast_version, str) and _VERSION.fullmatch(forecast_version)
        else None,
        prediction_uncertainty=uncertainty,
        missing_evidence=tuple(
            code
            for key, code in (
                ("competitor_median", "COMPETITOR_PRICE_UNAVAILABLE"),
                ("available_units", "INVENTORY_UNAVAILABLE"),
                ("daily_sales_rate", "SALES_HISTORY_UNAVAILABLE"),
            )
            if key not in metrics
        ),
        supporting_actions=tuple(dict.fromkeys(supports)),
    )
