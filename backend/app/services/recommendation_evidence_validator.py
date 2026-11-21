from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from statistics import median
from typing import Any, Mapping
from uuid import UUID

from app.analytics.metrics import (
    PricingConfig,
    compute_availability_counts,
    score_pricing_pressure,
)
from app.core.config import settings
from app.models.product import Product
from app.models.recommendation import RecommendationAction, RecommendationConfidence
from app.services.forecast_source_policy import MIN_MATCH as MIN_MATCH
from app.services.margin_guard import MarginGuard, MarginGuardResult
from app.scraper.constants import MARKETPLACE_NAME
from app.services.recommendation_evidence_service import (
    FieldEvidence,
    Freshness,
    MarketCompetitor,
    RecommendationEvidence,
)

STRONG_MATCH = 0.88
MIN_HIGH_PRICES = 3
HIGH_COVERAGE = 0.8
PRICE_ACTIONS = {RecommendationAction.LOWER, RecommendationAction.RAISE}


class InvalidRecommendationEvidence(ValueError):
    pass


@dataclass(frozen=True)
class EvidenceAssessment:
    action: RecommendationAction
    confidence: RecommendationConfidence
    candidate_price: Decimal | None
    reason_codes: tuple[str, ...]
    metrics: dict[str, Any]
    guard: dict[str, Any]
    market_metrics: dict[str, Any]

    def to_context(self) -> dict[str, Any]:
        return {
            "version": 1,
            "validated_action": self.action.value,
            "confidence": self.confidence.value,
            "reason_codes": list(self.reason_codes),
            **self.metrics,
        }


class RecommendationEvidenceValidator:
    def __init__(self, guard: MarginGuard) -> None:
        self.guard = guard

    def market(
        self,
        product: Product,
        evidence: RecommendationEvidence,
        now: datetime,
    ) -> list[MarketCompetitor]:
        self._verify_scope(product, evidence)
        if now.utcoffset() is None:
            raise InvalidRecommendationEvidence(
                "Assessment time must include a timezone."
            )
        market: list[MarketCompetitor] = []
        seen: set[UUID] = set()
        for row in evidence.observations:
            price = _decimal(row.price)
            if (
                row.match_score is None
                or not MIN_MATCH <= row.match_score <= 1
                or price is None
                or price <= 0
                or row.competitor_id in seen
                or not _fresh(row.price_evidence, now, evidence.price_max_age)
            ):
                continue
            seen.add(row.competitor_id)
            stock = (
                row.stock_status
                if row.stock_status in {"IN_STOCK", "OUT_OF_STOCK"}
                and _fresh(row.stock_evidence, now, evidence.stock_max_age)
                else None
            )
            market.append(
                {"price": price, "competitor_price": price, "stock_status": stock}
            )
        return market

    def assess(
        self,
        product: Product,
        evidence: RecommendationEvidence,
        analytics: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> EvidenceAssessment:
        at = now or datetime.now(timezone.utc)
        market = self.market(product, evidence, at)
        validate_finite_json(analytics)
        action = RecommendationAction(analytics["action"])
        proposed = action
        reasons = list(analytics["reason_codes"])
        signal = _decimal(
            analytics.get("action_signal_strength", analytics.get("confidence"))
        )
        if signal is None or not 0 <= signal <= 1:
            raise InvalidRecommendationEvidence("Invalid action signal.")
        inventory = analytics["inventory_evidence"]
        demand = inventory.get("demand_status")
        rate = _decimal(inventory.get("daily_net_sales_rate"))
        plan = inventory.get("reorder") or {}
        captured_at = inventory.get("inventory_captured_at")
        inventory_fresh = False
        if isinstance(captured_at, str):
            captured = datetime.fromisoformat(captured_at)
            inventory_fresh = captured.utcoffset() is not None and timedelta(
                0
            ) <= at - captured <= timedelta(
                hours=settings.recommendation_inventory_max_age_hours,
            )
        inventory_fresh = inventory_fresh and inventory.get("on_hand_units") == product.stock_quantity
        supported_reorder = (
            inventory_fresh
            and bool(inventory.get("inventory_snapshot_id"))
            and inventory.get("available_units") is not None
            and inventory.get("supplier_lead_time_days", 0)
            == product.supplier_lead_time
            and (product.supplier_lead_time or 0) > 0
            and rate is not None
            and rate > 0
            and demand in {"OBSERVED", "ESTIMATED_FROM_RECORDED_SALES"}
            and plan.get("dedicated_action") == "REORDER"
            and plan.get("recommended_quantity", 0) > 0
            and not plan.get("insufficient_reason")
        )
        fresh_prices = sum(
            _fresh(row.price_evidence, at, evidence.price_max_age)
            for row in evidence.observations
        )
        eligible_count = len(market)
        known_stock = sum(item["stock_status"] is not None for item in market)
        market_midpoint = median(item["price"] for item in market) if market else None
        current = _decimal(product.selling_price)
        gap = (
            (current - market_midpoint) * 100 / market_midpoint
            if current is not None and current > 0 and market_midpoint
            else None
        )
        counts = compute_availability_counts(item["stock_status"] for item in market)
        config = PricingConfig()
        total = len(evidence.observations)
        coverage = eligible_count / total if total else 0.0
        strong_matches = len(
            {
                row.competitor_id
                for row in evidence.observations
                if row.match_score is not None
                and STRONG_MATCH <= row.match_score <= 1
                and _fresh(row.price_evidence, at, evidence.price_max_age)
                and (_decimal(row.price) or Decimal(0)) > 0
            }
        )
        if any(
            field.status == Freshness.STALE
            or (field.status == Freshness.FRESH and not _fresh(field, at, max_age))
            for row in evidence.observations
            for field, max_age in (
                (row.price_evidence, evidence.price_max_age),
                (row.stock_evidence, evidence.stock_max_age),
            )
        ):
            reasons.append("STALE_COMPETITOR_DATA")
        if not known_stock:
            reasons.append("UNKNOWN_MARKET_AVAILABILITY")
        if eligible_count < fresh_prices:
            reasons.append("COMPETITOR_MATCH_QUALITY_INSUFFICIENT")
        if demand == "INSUFFICIENT":
            reasons.append("INSUFFICIENT_SALES_HISTORY")
        reasons.append("MODEL_UNAVAILABLE")

        pricing = analytics["pricing_evidence"]
        prior_guard = pricing.get("candidate_guard") or {}
        guard_evidence = dict(prior_guard)
        candidate = _decimal(analytics.get("candidate_price"))
        if analytics.get("candidate_price") is not None and candidate is None:
            raise InvalidRecommendationEvidence("Invalid candidate price.")
        if action in PRICE_ACTIONS:
            eligible = (
                current is not None
                and current > 0
                and candidate is not None
                and candidate > 0
                and eligible_count >= config.min_competitor_count
                and market_midpoint is not None
            )
            # The current engine has no positive price-response evidence for RAISE.
            if (
                action == RecommendationAction.LOWER
                and eligible
                and current is not None
                and candidate is not None
                and market_midpoint is not None
                and candidate < current
                and candidate <= market_midpoint
                and gap is not None
                and gap >= Decimal(str(config.price_undercut_threshold_percent))
                and market_midpoint
                == _decimal(analytics.get("competitor_median_price"))
            ):
                result = self.guard.validate_candidate(
                    seller_id=product.seller_id,
                    product=product,
                    candidate_price=candidate,
                    marketplace=MARKETPLACE_NAME,
                )
                guard_evidence = result.to_evidence()
                _validate_guard_money(result)
                if (
                    not result.is_allowed
                    or result.candidate_price != candidate
                    or result.minimum_safe_price is None
                    or candidate < result.minimum_safe_price
                    or result.minimum_safe_price < 0
                    or result.policy_version is None
                ):
                    action = RecommendationAction.HOLD
                    reasons.append("MARGIN_GUARD_BLOCKED")
            else:
                action = RecommendationAction.HOLD
                if proposed == RecommendationAction.RAISE:
                    reasons.append("NO_PRICE_RESPONSE_EVIDENCE")
        elif action == RecommendationAction.REORDER and not supported_reorder:
            action = RecommendationAction.HOLD

        if "MISSING_FEE_DATA" in (
            *reasons,
            *guard_evidence.get("rejection_reasons", ()),
        ):
            reasons.append("MISSING_FEE_POLICY")
        if "MARGIN_GUARD_BLOCKED_PRICE_RECOMMENDATION" in reasons:
            reasons.append("MARGIN_GUARD_BLOCKED")
        if (
            action != proposed
            or (
                action == RecommendationAction.HOLD
                and any(
                    code in reasons
                    for code in (
                        "MARGIN_GUARD_BLOCKED",
                        "INSUFFICIENT_SALES_HISTORY",
                        "STALE_COMPETITOR_DATA",
                        "MISSING_FEE_POLICY",
                        "MISSING_OR_STALE_INVENTORY_SNAPSHOT",
                        "MISSING_SUPPLIER_LEAD_TIME",
                    )
                )
            )
            or (
                action == RecommendationAction.HOLD
                and eligible_count < config.min_competitor_count
            )
        ):
            reasons.append("INSUFFICIENT_ACTION_EVIDENCE")

        confidence = RecommendationConfidence.LOW
        high_support = (
            demand == "OBSERVED" and bool(inventory.get("coverage_id"))
            if action == RecommendationAction.REORDER
            else strong_matches >= MIN_HIGH_PRICES
            and coverage >= HIGH_COVERAGE
            and known_stock == eligible_count
            and not evidence.quality_flags
        )
        if action != RecommendationAction.HOLD:
            if high_support and signal >= Decimal("0.75"):
                confidence = RecommendationConfidence.HIGH
            elif signal >= Decimal("0.50"):
                confidence = RecommendationConfidence.MEDIUM
        validate_finite_json(guard_evidence)
        guard_evidence.update(
            requested_action=proposed.value,
            final_action=action.value,
            fail_closed=action != proposed or "MARGIN_GUARD_BLOCKED" in reasons,
        )
        return EvidenceAssessment(
            action,
            confidence,
            candidate if action in PRICE_ACTIONS else None,
            tuple(dict.fromkeys(reasons)),
            {
                "assessed_at": at.isoformat(),
                "proposed_action": proposed.value,
                "action_signal_strength": str(signal),
                "data_completeness": {
                    "snapshot_count": total,
                    "eligible_price_count": eligible_count,
                    "known_stock_count": known_stock,
                    "eligible_price_fraction": coverage,
                    "demand_status": demand,
                },
                "data_freshness": {
                    "fresh_price_count": fresh_prices,
                    "inventory_fresh": inventory_fresh,
                },
                "evidence_reliability": {
                    "strong_match_count": strong_matches,
                    "reorder_supported": supported_reorder,
                    "high_quality_support": high_support
                    if action != RecommendationAction.HOLD
                    else False,
                },
                "predictive_uncertainty": None,
            },
            guard_evidence,
            {
                "competitor_median_price": str(market_midpoint)
                if market_midpoint is not None
                else None,
                "price_gap_percent": float(gap) if gap is not None else None,
                "pricing_pressure_score": round(
                    score_pricing_pressure(
                        float(gap) if gap is not None else None,
                        config.pricing_pressure_reference_percent,
                    ),
                    2,
                ),
                "out_of_stock_competitor_count": int(counts["out_of_stock"])
                if known_stock
                else None,
                "competitor_availability_ratio": float(counts["ratio"])
                if known_stock
                else None,
                "estimated_days_of_stock_left": analytics.get(
                    "estimated_days_of_stock_left"
                )
                if inventory_fresh
                else None,
                "stock_risk_score": analytics.get("stock_risk_score")
                if inventory_fresh
                else None,
                "urgency_score": analytics.get("urgency_score")
                if inventory_fresh
                else None,
            },
        )

    @staticmethod
    def _verify_scope(product: Product, evidence: RecommendationEvidence) -> None:
        if (evidence.seller_id, evidence.product_id) != (product.seller_id, product.id):
            raise InvalidRecommendationEvidence(
                "Evidence belongs to a different seller or product."
            )
        if evidence.observations and evidence.scrape_run_id is None:
            raise InvalidRecommendationEvidence(
                "Observations require a source scrape run."
            )


def _fresh(field: FieldEvidence, now: datetime, max_age: timedelta) -> bool:
    return (
        field.status == Freshness.FRESH
        and field.observed_at is not None
        and field.observed_at.utcoffset() is not None
        and timedelta(0) <= now - field.observed_at <= max_age
    )


def _decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _validate_guard_money(result: MarginGuardResult) -> None:
    for value in (
        result.candidate_price,
        result.minimum_safe_price,
        result.unit_profit,
        result.margin_rate,
    ):
        if value is not None and not value.is_finite():
            raise InvalidRecommendationEvidence(
                "MarginGuard produced a non-finite amount."
            )
    validate_finite_json(result.to_evidence())


def validate_finite_json(value: Any, key: str = "") -> None:
    if isinstance(value, Mapping):
        for name, nested in value.items():
            validate_finite_json(nested, str(name))
    elif isinstance(value, (tuple, list)):
        for nested in value:
            validate_finite_json(nested, key)
    elif isinstance(value, (float, Decimal)) and _decimal(value) is None:
        raise InvalidRecommendationEvidence("Non-finite numeric recommendation output.")
    elif value is not None and key in MONETARY_KEYS and _decimal(value) is None:
        raise InvalidRecommendationEvidence("Invalid monetary recommendation output.")


MONETARY_KEYS = {
    "candidate_price",
    "minimum_safe_price",
    "competitor_median_price",
    "competitor_min_price",
    "competitor_max_price",
    "competitor_average_price",
    "seller_price",
    "seller_cost",
    "gross_revenue_per_unit",
    "gross_margin_per_unit",
    "contribution_margin_per_unit",
    "contribution_margin_rate",
    "estimated_profit",
    "unit_profit",
    "margin_rate",
    "minimum_required_margin",
    "minimum_required_unit_profit",
    "revenue_opportunity",
    "unit_cost",
    "fixed_fees",
    "fixed_fee_amount",
    "other_variable_cost",
    "total_fee_amount",
    "percentage_commission_amount",
    "payment_fee_amount",
    "percentage_fee_rate",
}
