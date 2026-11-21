"""Project seller-visible fields from the already authorized, persisted decision."""

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from app.models.recommendation import Recommendation
from app.schemas.recommendation import (
    DashboardForecast,
    DashboardPriceCandidate,
    DashboardReorder,
    DashboardSupportingAction,
    RecommendationDashboardEvidence,
)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _codes(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        code
        for code in value
        if isinstance(code, str)
        and len(code) <= 80
        and code.isascii()
        and code.replace("_", "").isalnum()
        and code.isupper()
    ]


def _add_forecast(
    points: dict[int, DashboardForecast], envelope: Mapping, candidate: Mapping
) -> None:
    point = _mapping(envelope.get("forecast"))
    if (
        envelope.get("source") not in ("active", "previous")
        or point.get("model_name") != "catboost"
        or point.get("product_id") != candidate.get("product_id")
        or point.get("seller_id") != candidate.get("seller_id")
        or point.get("horizon_days") not in (7, 14, 30)
        or point.get("horizon_days") in points
    ):
        return
    try:
        forecast = DashboardForecast.model_validate(
            {
                "horizon_days": point["horizon_days"],
                "expected_units": point.get("expected_units"),
                "method": point["model_name"],
                "version": point.get("model_version"),
                "source": envelope["source"],
                "data_cutoff": point.get("data_cutoff"),
                "uncertainty": _mapping(point.get("prediction_interval")).get(
                    "status", "uncalibrated"
                ),
            }
        )
    except ValidationError:
        return
    points[forecast.horizon_days] = forecast


def _validated_reorder_bound(snapshot: Mapping) -> object:
    uncertainty = _mapping(snapshot.get("uncertainty"))
    if uncertainty.get("status") == "validated_lead_time_upper_bound":
        return uncertainty.get("upper_lead_time_demand_units")
    return None


def build_dashboard_evidence(
    row: Recommendation,
) -> RecommendationDashboardEvidence | None:
    payload = _mapping(row.recommendation_context)
    analytics = _mapping(payload.get("analytics"))
    market = _mapping(payload.get("competitor_evidence"))
    assessment = _mapping(payload.get("evidence_assessment"))
    decision = _mapping(payload.get("decision_orchestration"))
    explanation = _mapping(_mapping(payload.get("explanation")).get("evidence"))
    if not (decision or assessment or explanation):
        return None

    inputs = _mapping(decision.get("inputs"))
    sales = _mapping(inputs.get("sales"))
    inventory = _mapping(inputs.get("inventory"))
    if sales.get("status") == "INSUFFICIENT":
        sales = {}
        sales_reasons = ["SALES_HISTORY_UNAVAILABLE"]
    else:
        sales_reasons = []
    reasons = list(
        dict.fromkeys(
            _codes(analytics.get("reason_codes"))
            + _codes(decision.get("reason_codes"))
            + _codes(assessment.get("reason_codes"))
            + _codes(explanation.get("missing_evidence"))
            + sales_reasons
        )
    )
    guard = _mapping(payload.get("margin_guard"))
    blocked = (
        guard.get("is_allowed") is False
        or _mapping(explanation.get("margin_guard")).get("status") == "blocked"
        or "MARGIN_GUARD_BLOCKED" in reasons
        or "MARGIN_GUARD_BLOCKED_PRICE_RECOMMENDATION" in reasons
    )

    points: dict[int, DashboardForecast] = {}
    supporting = [
        DashboardSupportingAction(action="HOLD", source="base_price")
        for advice in decision.get("supporting_advice", [])
        if _mapping(advice).get("reason_code") == "KEEP_PRICE_WHILE_REPLENISHING"
    ]
    prices = []
    reorder = None
    primary_id = decision.get("primary_candidate_id")
    support_ids = decision.get("supporting_candidate_ids", [])
    for item in decision.get("evaluations", []):
        evaluation = _mapping(item)
        candidate = _mapping(evaluation.get("candidate"))
        if (
            not candidate
            or candidate.get("product_id") != str(row.product_id)
            or candidate.get("seller_id") != inputs.get("seller_id")
        ):
            continue
        blocked = (
            blocked
            or _mapping(evaluation.get("final_margin_guard")).get("is_allowed") is False
        )
        candidate_id = candidate.get("candidate_id")
        engine = candidate.get("source_engine")
        params = _mapping(candidate.get("proposed_parameters"))
        snapshot = _mapping(_mapping(candidate.get("evidence")).get("snapshot"))
        if candidate_id in support_ids:
            supporting.append(
                DashboardSupportingAction.model_validate(
                    {
                        "action": params.get("action")
                        if engine == "dead_stock_recovery"
                        else candidate.get("action_type"),
                        "source": engine,
                    }
                )
            )
        if engine == "dynamic_pricing":
            baseline = _mapping(snapshot.get("baseline_demand_forecast"))
            if baseline.get("status") == "AVAILABLE":
                _add_forecast(points, baseline, candidate)
            for value in snapshot.get("candidates", []):
                price = _mapping(value)
                if not isinstance(price.get("is_allowed"), bool):
                    continue
                try:
                    projected = DashboardPriceCandidate.model_validate(
                        {
                            "price": price.get("candidate_price"),
                            "constraints_passed": price["is_allowed"],
                            "price_change_eligible": price.get(
                                "eligible_for_price_change"
                            ),
                            "rejection_reasons": _codes(price.get("rejection_reasons")),
                        }
                    )
                except ValidationError:
                    continue
                prices.append(projected)
        elif engine == "reorder":
            if snapshot.get("demand_source") == "approved_forecast":
                _add_forecast(points, _mapping(snapshot.get("forecast")), candidate)
            if candidate_id and (
                candidate_id == primary_id or candidate_id in support_ids
            ):
                demand_source = snapshot.get("demand_source")
                reorder = DashboardReorder.model_validate(
                    {
                        "quantity": params.get("quantity"),
                        "deadline": params.get("deadline"),
                        "reorder_point": snapshot.get("reorder_point"),
                        "lead_time_demand": snapshot.get("lead_time_demand"),
                        "demand_source": demand_source
                        if demand_source
                        in ("approved_forecast", "recorded_sales_velocity")
                        else None,
                        "uncertainty": _mapping(snapshot.get("uncertainty")).get(
                            "status"
                        ),
                        "validated_demand_upper_bound": _validated_reorder_bound(
                            snapshot
                        ),
                    }
                )
        elif engine == "dead_stock_recovery":
            baseline = _mapping(_mapping(snapshot.get("inputs")).get("baseline_demand"))
            if baseline.get("status") == "APPROVED_BASELINE_ONLY":
                _add_forecast(points, baseline, candidate)

    if {"PRODUCT_INPUTS_CHANGED", "INVENTORY_EVIDENCE_CHANGED"}.intersection(reasons):
        inventory = {}
    metrics = _mapping(explanation.get("metrics"))
    rate = _mapping(metrics.get("daily_sales_rate"))
    stock = _mapping(metrics.get("available_units"))
    return RecommendationDashboardEvidence(
        competitor_observed_at=explanation.get("market_observed_at")
        or market.get("latest_observation_at"),
        competitor_freshness=market.get("freshness_status"),
        inventory_observed_at=explanation.get("inventory_observed_at")
        or inventory.get("captured_at"),
        available_units=stock.get("value")
        if explanation
        else inventory.get("available_units"),
        sales_through=explanation.get("sales_through")
        if explanation
        else sales.get("through"),
        daily_sales_rate=rate.get("value") if explanation else sales.get("rate"),
        sales_rate_observed=rate.get("provenance") == "verified"
        if explanation
        else sales.get("status") == "OBSERVED",
        target_price=row.suggested_price_min
        if row.action.value in {"LOWER", "RAISE"}
        else None,
        reason_codes=reasons,
        insufficient_evidence=row.action.value == "HOLD"
        and (
            "INSUFFICIENT_ACTION_EVIDENCE" in reasons
            or (
                "NO_SUPPORTED_ACTION" in reasons
                and any(code.endswith("INSUFFICIENT_EVIDENCE") for code in reasons)
            )
        ),
        price_blocked=row.action.value == "HOLD" and blocked,
        forecasts=sorted(points.values(), key=lambda point: point.horizon_days),
        supporting_actions=supporting,
        pricing_candidates=prices,
        reorder=reorder,
    )
