"""Deterministic urgency rules and scoring engine.

This module turns competitor intelligence, AI signals, and inventory risk into
explainable, production-ready urgency decisions.

Example usage:
    payload = {
        "product_id": "DBL200",
        "seller_id": "SELLER-42",
        "seller_price": 450,
        "recommended_price": 430,
        "seller_stock": 12,
        "supplier_lead_time_days": 7,
        "minimum_margin_percent": 12,
        "cost_price": 320,
        "competitors": [
            {"price": 420, "stock_status": "in_stock"},
            {"price": 410, "stock_status": "out_of_stock"},
            {"price": 415, "stock_status": "out_of_stock"},
        ],
        "opportunity_score": 0.78,
        "demand_indicator": 0.7,
        "inventory_turnover_days": 8,
        "ai_recommendation": {"action": "PRICE_LOWER", "confidence": 0.71},
    }

    engine = UrgencyEngine()
    result = engine.evaluate(payload)
    print(result.to_dict())

Sample output (abbreviated):
    {
        "urgency_score": 74,
        "urgency_level": "HIGH",
        "action_type": "PRICE_LOWER",
        "confidence": "MEDIUM",
        "stock_risk_level": "MEDIUM",
        "revenue_opportunity": 3654.0,
        "market_opportunity_score": 71,
        "reasoning_summary": "High urgency driven by competitor undercut and ...",
        "triggered_rules": ["COMPETITOR_OUT_OF_STOCK", "PRICE_GAP_THRESHOLD"],
    }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
import logging
import os
import time
from typing import Any, Iterable, Mapping, Protocol, Sequence, TYPE_CHECKING

from app.analytics.metrics import (
    clamp,
    compute_competitor_price_stats,
    compute_price_gap_percent,
    normalize_stock_status,
    safe_divide,
    score_market_position,
    score_pricing_pressure,
    score_stock_risk,
)

ActionType = str
ConfidenceLevel = str
StockRiskLevel = str
UrgencyLevel = str

if TYPE_CHECKING:
    from app.recommendations.opportunity_calculator import OpportunityCalculator


class UrgencyEngineError(Exception):
    """Base error for the urgency engine."""


class InvalidUrgencyInputError(UrgencyEngineError):
    """Raised when required inputs are missing or malformed."""


class MarketDataQualityError(UrgencyEngineError):
    """Raised when market data is too inconsistent for scoring."""


@dataclass(frozen=True)
class UrgencyThresholds:
    low_max: int = 30
    medium_max: int = 60
    high_max: int = 80
    critical_max: int = 100
    price_gap_threshold_percent: float = 6.0
    aggressive_competitor_gap_percent: float = 10.0
    low_margin_threshold_percent: float = 8.0
    market_opportunity_threshold: float = 0.65
    high_demand_threshold: float = 0.7
    competitor_oos_ratio_threshold: float = 0.5
    lead_time_risk_days: int = 10
    stockout_days_threshold: int = 5
    stock_warning_units: int = 10
    inventory_depletion_days: int = 7
    inventory_turnover_threshold_days: int = 10
    min_competitor_count: int = 2


@dataclass(frozen=True)
class ConfidenceConfig:
    rules_for_high_confidence: int = 4
    min_data_completeness: float = 0.6
    competitor_variance_reference: float = 0.15
    max_recommendation_delta_percent: float = 20.0
    price_signal_reference_percent: float = 15.0
    high_confidence_threshold: float = 0.7
    medium_confidence_threshold: float = 0.45
    weight_rules: float = 0.25
    weight_data: float = 0.25
    weight_competitor_consistency: float = 0.2
    weight_recommendation_stability: float = 0.15
    weight_pricing_signal: float = 0.15


@dataclass(frozen=True)
class ScoringWeights:
    stock_pressure: float = 0.2
    competitor_pressure: float = 0.15
    market_opportunity: float = 0.15
    price_competitiveness: float = 0.15
    margin_safety: float = 0.1
    demand_signal: float = 0.15
    lead_time_risk: float = 0.1


@dataclass(frozen=True)
class OpportunityConfig:
    demand_window_days: int = 7
    base_daily_demand: float = 1.0
    opportunity_multiplier: float = 0.6
    out_of_stock_multiplier: float = 0.5
    demand_multiplier: float = 0.4
    capture_rate: float = 0.6
    profit_multiplier: float = 1.0
    max_demand_boost: float = 2.5


@dataclass(frozen=True)
class AlertConfig:
    notify_min_urgency_level: UrgencyLevel = "MEDIUM"
    notify_min_score: int = 50


@dataclass(frozen=True)
class UrgencyEngineConfig:
    thresholds: UrgencyThresholds = field(default_factory=UrgencyThresholds)
    confidence: ConfidenceConfig = field(default_factory=ConfidenceConfig)
    weights: ScoringWeights = field(default_factory=ScoringWeights)
    opportunity: OpportunityConfig = field(default_factory=OpportunityConfig)
    alerts: AlertConfig = field(default_factory=AlertConfig)

    @classmethod
    def from_env(cls) -> "UrgencyEngineConfig":
        thresholds = UrgencyThresholds(
            low_max=_get_env_int("BAZARSYNC_URGENCY_LOW_MAX", 30),
            medium_max=_get_env_int("BAZARSYNC_URGENCY_MEDIUM_MAX", 60),
            high_max=_get_env_int("BAZARSYNC_URGENCY_HIGH_MAX", 80),
            critical_max=_get_env_int("BAZARSYNC_URGENCY_CRITICAL_MAX", 100),
            price_gap_threshold_percent=_get_env_float(
                "BAZARSYNC_PRICE_GAP_THRESHOLD", 6.0
            ),
            aggressive_competitor_gap_percent=_get_env_float(
                "BAZARSYNC_AGGRESSIVE_PRICE_GAP", 10.0
            ),
            low_margin_threshold_percent=_get_env_float(
                "BAZARSYNC_LOW_MARGIN_THRESHOLD", 8.0
            ),
            market_opportunity_threshold=_get_env_float(
                "BAZARSYNC_MARKET_OPPORTUNITY_THRESHOLD", 0.65
            ),
            high_demand_threshold=_get_env_float(
                "BAZARSYNC_HIGH_DEMAND_THRESHOLD", 0.7
            ),
            competitor_oos_ratio_threshold=_get_env_float(
                "BAZARSYNC_OOS_RATIO_THRESHOLD", 0.5
            ),
            lead_time_risk_days=_get_env_int("BAZARSYNC_LEAD_TIME_RISK_DAYS", 10),
            stockout_days_threshold=_get_env_int(
                "BAZARSYNC_STOCKOUT_DAYS_THRESHOLD", 5
            ),
            stock_warning_units=_get_env_int("BAZARSYNC_STOCK_WARNING_UNITS", 10),
            inventory_depletion_days=_get_env_int(
                "BAZARSYNC_INVENTORY_DEPLETION_DAYS", 7
            ),
            inventory_turnover_threshold_days=_get_env_int(
                "BAZARSYNC_INVENTORY_TURNOVER_DAYS", 10
            ),
            min_competitor_count=_get_env_int("BAZARSYNC_MIN_COMPETITOR_COUNT", 2),
        )

        confidence = ConfidenceConfig(
            rules_for_high_confidence=_get_env_int(
                "BAZARSYNC_CONF_RULES_HIGH", 4
            ),
            min_data_completeness=_get_env_float(
                "BAZARSYNC_CONF_MIN_COMPLETENESS", 0.6
            ),
            competitor_variance_reference=_get_env_float(
                "BAZARSYNC_CONF_COMP_VAR_REF", 0.15
            ),
            max_recommendation_delta_percent=_get_env_float(
                "BAZARSYNC_CONF_MAX_RECO_DELTA", 20.0
            ),
            price_signal_reference_percent=_get_env_float(
                "BAZARSYNC_CONF_PRICE_SIGNAL_REF", 15.0
            ),
            high_confidence_threshold=_get_env_float(
                "BAZARSYNC_CONF_HIGH_THRESHOLD", 0.7
            ),
            medium_confidence_threshold=_get_env_float(
                "BAZARSYNC_CONF_MED_THRESHOLD", 0.45
            ),
        )

        weights = ScoringWeights(
            stock_pressure=_get_env_float("BAZARSYNC_WEIGHT_STOCK", 0.2),
            competitor_pressure=_get_env_float("BAZARSYNC_WEIGHT_COMPETITOR", 0.15),
            market_opportunity=_get_env_float("BAZARSYNC_WEIGHT_OPPORTUNITY", 0.15),
            price_competitiveness=_get_env_float("BAZARSYNC_WEIGHT_PRICE", 0.15),
            margin_safety=_get_env_float("BAZARSYNC_WEIGHT_MARGIN", 0.1),
            demand_signal=_get_env_float("BAZARSYNC_WEIGHT_DEMAND", 0.15),
            lead_time_risk=_get_env_float("BAZARSYNC_WEIGHT_LEADTIME", 0.1),
        )

        opportunity = OpportunityConfig(
            demand_window_days=_get_env_int("BAZARSYNC_OPP_WINDOW_DAYS", 7),
            base_daily_demand=_get_env_float("BAZARSYNC_OPP_BASE_DEMAND", 1.0),
            opportunity_multiplier=_get_env_float(
                "BAZARSYNC_OPP_MULTIPLIER", 0.6
            ),
            out_of_stock_multiplier=_get_env_float(
                "BAZARSYNC_OPP_OOS_MULTIPLIER", 0.5
            ),
            demand_multiplier=_get_env_float("BAZARSYNC_OPP_DEMAND_MULTIPLIER", 0.4),
            capture_rate=_get_env_float("BAZARSYNC_OPP_CAPTURE_RATE", 0.6),
            profit_multiplier=_get_env_float("BAZARSYNC_OPP_PROFIT_MULTIPLIER", 1.0),
            max_demand_boost=_get_env_float("BAZARSYNC_OPP_MAX_BOOST", 2.5),
        )

        alerts = AlertConfig(
            notify_min_urgency_level=os.getenv(
                "BAZARSYNC_ALERT_MIN_LEVEL", "MEDIUM"
            ).upper(),
            notify_min_score=_get_env_int("BAZARSYNC_ALERT_MIN_SCORE", 50),
        )

        return cls(
            thresholds=thresholds,
            confidence=confidence,
            weights=weights,
            opportunity=opportunity,
            alerts=alerts,
        )


@dataclass(frozen=True)
class UrgencyInput:
    product_id: str
    seller_id: str
    seller_price: float
    seller_stock: int
    supplier_lead_time_days: int
    minimum_margin_percent: float
    cost_price: float | None = None
    recommended_price: float | None = None
    competitor_prices: list[float] = field(default_factory=list)
    competitor_stock_statuses: list[str] = field(default_factory=list)
    competitor_oos_count: int | None = None
    opportunity_score: float | None = None
    demand_indicator: float | None = None
    inventory_turnover_days: float | None = None
    historical_prices: list[float] = field(default_factory=list)
    ai_action: ActionType | None = None
    ai_confidence: float | None = None

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        config: UrgencyEngineConfig,
        logger: logging.Logger,
    ) -> tuple["UrgencyInput", "DataQualityReport"]:
        if not isinstance(payload, Mapping):
            raise InvalidUrgencyInputError("Urgency input must be a mapping.")

        product_id = _string_value(payload, "product_id", fallback="sku") or "UNKNOWN"
        seller_id = _string_value(payload, "seller_id", fallback="merchant_id") or "UNKNOWN"

        seller_price_value = _value_with_fallback(
            payload, "seller_price", "current_seller_price", "current_price"
        )
        seller_stock_value = _value_with_fallback(
            payload, "seller_stock", "stock_quantity", "inventory_count"
        )
        lead_time_value = _value_with_fallback(
            payload, "supplier_lead_time_days", "supplier_lead_time", "lead_time_days"
        )
        missing_required = [
            name
            for name, value in {
                "seller_price": seller_price_value,
                "seller_stock": seller_stock_value,
                "supplier_lead_time_days": lead_time_value,
            }.items()
            if value is None
        ]
        if missing_required:
            raise InvalidUrgencyInputError(
                f"Missing required fields: {', '.join(missing_required)}."
            )

        seller_price = _require_float_value("seller_price", seller_price_value, positive=True)
        seller_stock = _require_int_value("seller_stock", seller_stock_value, non_negative=True)
        supplier_lead_time_days = _require_int_value(
            "supplier_lead_time_days", lead_time_value, non_negative=True
        )
        minimum_margin_percent = _optional_float(
            _value_with_fallback(
                payload, "minimum_margin_percent", "minimum_margin", "profit_margin_threshold"
            ),
            non_negative=True,
        )
        if minimum_margin_percent is None:
            minimum_margin_percent = config.thresholds.low_margin_threshold_percent
            logger.info(
                "urgency_input_default_margin minimum_margin_percent=%s product_id=%s",
                minimum_margin_percent,
                product_id,
            )

        cost_price = _optional_float(
            _value_with_fallback(payload, "cost_price", "seller_cost", "unit_cost"),
            non_negative=True,
        )
        recommended_price = _optional_float(
            _value_with_fallback(payload, "recommended_price", "ai_recommended_price"),
            positive=True,
        )

        competitor_prices, competitor_statuses = _parse_competitor_payload(
            payload.get("competitors"),
            payload.get("competitor_prices"),
            payload.get("competitor_stock_statuses"),
        )
        competitor_oos_count = _optional_int(
            _value_with_fallback(
                payload, "competitor_oos_count", "competitor_out_of_stock_count"
            ),
            non_negative=True,
        )

        ai_action = _string_value(payload, "ai_action")
        ai_confidence = _optional_float(payload.get("ai_confidence"), non_negative=True)
        ai_reco = payload.get("ai_recommendation")
        if isinstance(ai_reco, Mapping):
            ai_action = _string_value(ai_reco, "action") or ai_action
            ai_confidence = _optional_float(ai_reco.get("confidence"), non_negative=True)

        opportunity_score = _optional_float(
            payload.get("opportunity_score"), min_value=0.0, max_value=1.0
        )
        demand_indicator = _optional_float(
            payload.get("demand_indicator"), min_value=0.0, max_value=1.0
        )
        inventory_turnover_days = _optional_float(
            payload.get("inventory_turnover_days"), non_negative=True
        )
        historical_prices = _parse_float_list(payload.get("historical_prices"))

        optional_fields = {
            "minimum_margin_percent": minimum_margin_percent,
            "cost_price": cost_price,
            "recommended_price": recommended_price,
            "competitor_prices": competitor_prices or None,
            "opportunity_score": opportunity_score,
            "demand_indicator": demand_indicator,
            "inventory_turnover_days": inventory_turnover_days,
            "historical_prices": historical_prices or None,
            "competitor_oos_count": competitor_oos_count,
        }
        quality = DataQualityReport.from_fields(optional_fields)

        return (
            cls(
                product_id=product_id,
                seller_id=seller_id,
                seller_price=seller_price,
                seller_stock=seller_stock,
                supplier_lead_time_days=supplier_lead_time_days,
                minimum_margin_percent=minimum_margin_percent,
                cost_price=cost_price,
                recommended_price=recommended_price,
                competitor_prices=competitor_prices,
                competitor_stock_statuses=competitor_statuses,
                competitor_oos_count=competitor_oos_count,
                opportunity_score=opportunity_score,
                demand_indicator=demand_indicator,
                inventory_turnover_days=inventory_turnover_days,
                historical_prices=historical_prices,
                ai_action=ai_action,
                ai_confidence=ai_confidence,
            ),
            quality,
        )


@dataclass(frozen=True)
class DerivedMetrics:
    competitor_count: int
    competitor_oos_ratio: float
    competitor_median_price: float | None
    competitor_min_price: float | None
    competitor_std_dev: float | None
    price_gap_percent: float | None
    recommended_gap_percent: float | None
    margin_percent: float | None
    estimated_days_left: float
    market_position_score: float
    pricing_pressure_score: float
    competitor_consistency_score: float


@dataclass(frozen=True)
class DataQualityReport:
    completeness_score: float
    missing_fields: list[str] = field(default_factory=list)

    @classmethod
    def from_fields(cls, fields: Mapping[str, Any]) -> "DataQualityReport":
        missing = [key for key, value in fields.items() if value is None]
        completeness = safe_divide(
            float(len(fields) - len(missing)), float(len(fields)), default=0.0
        )
        return cls(completeness_score=round(completeness, 2), missing_fields=missing)


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    title: str
    triggered: bool
    severity: float
    summary: str
    action_hint: ActionType | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "triggered": self.triggered,
            "severity": round(self.severity, 2),
            "summary": self.summary,
            "action_hint": self.action_hint,
        }


@dataclass(frozen=True)
class UrgencyResult:
    urgency_score: int
    urgency_level: UrgencyLevel
    action_type: ActionType
    confidence: ConfidenceLevel
    confidence_score: float
    revenue_opportunity: float
    stock_risk_level: StockRiskLevel
    reasoning_summary: str
    triggered_rules: list[str]
    market_opportunity_score: int
    rule_results: list[RuleResult] = field(default_factory=list)
    data_quality: DataQualityReport | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "urgency_score": self.urgency_score,
            "urgency_level": self.urgency_level,
            "action_type": self.action_type,
            "confidence": self.confidence,
            "confidence_score": round(self.confidence_score, 2),
            "revenue_opportunity": round(self.revenue_opportunity, 2),
            "stock_risk_level": self.stock_risk_level,
            "reasoning_summary": self.reasoning_summary,
            "triggered_rules": self.triggered_rules,
            "market_opportunity_score": self.market_opportunity_score,
            "rule_results": [rule.to_dict() for rule in self.rule_results],
            "data_quality": {
                "completeness_score": self.data_quality.completeness_score,
                "missing_fields": self.data_quality.missing_fields,
            }
            if self.data_quality
            else None,
            "diagnostics": self.diagnostics,
        }


@dataclass(frozen=True)
class RuleContext:
    payload: UrgencyInput
    derived: DerivedMetrics
    config: UrgencyEngineConfig


class UrgencyRule(Protocol):
    rule_id: str
    title: str

    def evaluate(self, context: RuleContext) -> RuleResult:
        ...


class CompetitorOutOfStockRule:
    rule_id = "COMPETITOR_OUT_OF_STOCK"
    title = "Competitor stockouts detected"

    def evaluate(self, context: RuleContext) -> RuleResult:
        ratio = context.derived.competitor_oos_ratio
        triggered = ratio >= context.config.thresholds.competitor_oos_ratio_threshold
        severity = clamp(ratio, 0.0, 1.0)
        summary = (
            f"{int(ratio * 100)}% competitors out of stock"
            if triggered
            else "Competitor stock levels stable"
        )
        return RuleResult(
            rule_id=self.rule_id,
            title=self.title,
            triggered=triggered,
            severity=severity,
            summary=summary,
            action_hint="PRICE_RAISE" if triggered else None,
        )


class SellerStockoutRiskRule:
    rule_id = "SELLER_STOCKOUT_RISK"
    title = "Seller stockout risk"

    def evaluate(self, context: RuleContext) -> RuleResult:
        days_left = context.derived.estimated_days_left
        stock_warning = context.payload.seller_stock <= context.config.thresholds.stock_warning_units
        triggered = (
            days_left <= context.config.thresholds.stockout_days_threshold or stock_warning
        )
        severity = clamp(
            1.0
            - safe_divide(
                days_left, context.config.thresholds.stockout_days_threshold, default=1.0
            ),
            0.0,
            1.0,
        )
        summary = (
            f"Stock risk: {days_left:.1f} days left"
            if triggered
            else "Stock level within safe range"
        )
        action_hint = "REORDER" if days_left <= context.payload.supplier_lead_time_days else "STOCK_WARNING"
        return RuleResult(
            rule_id=self.rule_id,
            title=self.title,
            triggered=triggered,
            severity=severity,
            summary=summary,
            action_hint=action_hint if triggered else None,
        )


class PriceGapThresholdRule:
    rule_id = "PRICE_GAP_THRESHOLD"
    title = "Price gap exceeds threshold"

    def evaluate(self, context: RuleContext) -> RuleResult:
        gap = context.derived.price_gap_percent
        triggered = gap is not None and gap >= context.config.thresholds.price_gap_threshold_percent
        severity = clamp(
            safe_divide(gap or 0.0, context.config.thresholds.aggressive_competitor_gap_percent, default=0.0),
            0.0,
            1.0,
        )
        summary = (
            f"Seller price {gap:.1f}% above market median"
            if triggered and gap is not None
            else "Price gap within acceptable range"
        )
        return RuleResult(
            rule_id=self.rule_id,
            title=self.title,
            triggered=triggered,
            severity=severity,
            summary=summary,
            action_hint="PRICE_LOWER" if triggered else None,
        )


class LowMarginRiskRule:
    rule_id = "LOW_MARGIN_RISK"
    title = "Margin risk below threshold"

    def evaluate(self, context: RuleContext) -> RuleResult:
        margin = context.derived.margin_percent
        threshold = context.payload.minimum_margin_percent
        triggered = margin is not None and margin < threshold
        severity = clamp(
            safe_divide(threshold - (margin or 0.0), threshold, default=0.0), 0.0, 1.0
        )
        summary = (
            f"Margin {margin:.1f}% below minimum {threshold:.1f}%"
            if triggered and margin is not None
            else "Margin within safe bounds"
        )
        return RuleResult(
            rule_id=self.rule_id,
            title=self.title,
            triggered=triggered,
            severity=severity,
            summary=summary,
            action_hint="HOLD" if triggered else None,
        )


class MarketOpportunityRule:
    rule_id = "MARKET_OPPORTUNITY"
    title = "Market opportunity detected"

    def evaluate(self, context: RuleContext) -> RuleResult:
        score = context.payload.opportunity_score or 0.0
        oos_ratio = context.derived.competitor_oos_ratio
        triggered = (
            score >= context.config.thresholds.market_opportunity_threshold
            and oos_ratio >= context.config.thresholds.competitor_oos_ratio_threshold
        )
        severity = clamp((score + oos_ratio) / 2.0, 0.0, 1.0)
        summary = (
            f"Opportunity score {score:.2f} with {int(oos_ratio * 100)}% competitor OOS"
            if triggered
            else "Market opportunity below threshold"
        )
        return RuleResult(
            rule_id=self.rule_id,
            title=self.title,
            triggered=triggered,
            severity=severity,
            summary=summary,
            action_hint="OPPORTUNITY_CAPTURE" if triggered else None,
        )


class AggressiveCompetitorPricingRule:
    rule_id = "AGGRESSIVE_COMPETITOR_PRICING"
    title = "Aggressive competitor pricing detected"

    def evaluate(self, context: RuleContext) -> RuleResult:
        min_price = context.derived.competitor_min_price
        if min_price is None:
            return RuleResult(
                rule_id=self.rule_id,
                title=self.title,
                triggered=False,
                severity=0.0,
                summary="No competitor price baseline",
            )
        gap_percent = compute_price_gap_percent(context.payload.seller_price, min_price)
        triggered = (
            gap_percent is not None
            and gap_percent >= context.config.thresholds.aggressive_competitor_gap_percent
        )
        severity = clamp(
            safe_divide(
                gap_percent or 0.0, context.config.thresholds.aggressive_competitor_gap_percent, default=0.0
            ),
            0.0,
            1.0,
        )
        summary = (
            f"Competitor undercuts by {gap_percent:.1f}%"
            if triggered and gap_percent is not None
            else "Competitor pricing within range"
        )
        return RuleResult(
            rule_id=self.rule_id,
            title=self.title,
            triggered=triggered,
            severity=severity,
            summary=summary,
            action_hint="PRICE_LOWER" if triggered else None,
        )


class HighDemandOpportunityRule:
    rule_id = "HIGH_DEMAND_SIGNAL"
    title = "High demand signal detected"

    def evaluate(self, context: RuleContext) -> RuleResult:
        demand = context.payload.demand_indicator or 0.0
        triggered = demand >= context.config.thresholds.high_demand_threshold
        severity = clamp(demand, 0.0, 1.0)
        summary = (
            f"Demand index {demand:.2f} indicates surge"
            if triggered
            else "Demand within normal range"
        )
        return RuleResult(
            rule_id=self.rule_id,
            title=self.title,
            triggered=triggered,
            severity=severity,
            summary=summary,
            action_hint="OPPORTUNITY_CAPTURE" if triggered else None,
        )


class SupplierLeadTimeRiskRule:
    rule_id = "SUPPLIER_LEAD_TIME_RISK"
    title = "Supplier lead time risk"

    def evaluate(self, context: RuleContext) -> RuleResult:
        lead_time = context.payload.supplier_lead_time_days
        days_left = context.derived.estimated_days_left
        triggered = (
            lead_time >= context.config.thresholds.lead_time_risk_days
            or lead_time >= days_left
        )
        severity = clamp(
            safe_divide(
                lead_time, max(context.config.thresholds.lead_time_risk_days, 1), default=0.0
            ),
            0.0,
            1.0,
        )
        summary = (
            f"Lead time {lead_time} days risks stock gap"
            if triggered
            else "Lead time within acceptable range"
        )
        return RuleResult(
            rule_id=self.rule_id,
            title=self.title,
            triggered=triggered,
            severity=severity,
            summary=summary,
            action_hint="REORDER" if triggered else None,
        )


class InventoryDepletionRule:
    rule_id = "INVENTORY_DEPLETION_PREDICTION"
    title = "Inventory depletion predicted"

    def evaluate(self, context: RuleContext) -> RuleResult:
        days_left = context.derived.estimated_days_left
        turnover_days = context.payload.inventory_turnover_days
        threshold = context.config.thresholds.inventory_depletion_days
        turnover_triggered = (
            turnover_days is not None
            and turnover_days <= context.config.thresholds.inventory_turnover_threshold_days
        )
        triggered = days_left <= threshold or turnover_triggered
        severity = clamp(
            safe_divide(threshold - days_left, threshold, default=0.0), 0.0, 1.0
        )
        summary = (
            f"Inventory depletion expected in {days_left:.1f} days"
            if triggered
            else "Inventory horizon stable"
        )
        return RuleResult(
            rule_id=self.rule_id,
            title=self.title,
            triggered=triggered,
            severity=severity,
            summary=summary,
            action_hint="REORDER" if triggered else None,
        )


class ProfitProtectionRule:
    rule_id = "PROFIT_PROTECTION"
    title = "Profit protection required"

    def evaluate(self, context: RuleContext) -> RuleResult:
        recommended_price = context.payload.recommended_price
        cost_price = context.payload.cost_price
        if recommended_price is None or cost_price is None:
            return RuleResult(
                rule_id=self.rule_id,
                title=self.title,
                triggered=False,
                severity=0.0,
                summary="Profit protection not evaluated",
            )
        margin = _calculate_margin_percent(recommended_price, cost_price)
        threshold = context.payload.minimum_margin_percent
        triggered = margin < threshold
        severity = clamp(
            safe_divide(threshold - margin, threshold, default=0.0), 0.0, 1.0
        )
        summary = (
            f"Recommended price margin {margin:.1f}% below minimum {threshold:.1f}%"
            if triggered
            else "Recommended price preserves margin"
        )
        return RuleResult(
            rule_id=self.rule_id,
            title=self.title,
            triggered=triggered,
            severity=severity,
            summary=summary,
            action_hint="HOLD" if triggered else None,
        )


RULE_SET: list[UrgencyRule] = [
    CompetitorOutOfStockRule(),
    SellerStockoutRiskRule(),
    PriceGapThresholdRule(),
    LowMarginRiskRule(),
    MarketOpportunityRule(),
    AggressiveCompetitorPricingRule(),
    HighDemandOpportunityRule(),
    SupplierLeadTimeRiskRule(),
    InventoryDepletionRule(),
    ProfitProtectionRule(),
]

# Example inputs/expected outputs for unit testing.
EXAMPLE_INPUT: dict[str, Any] = {
    "product_id": "DBL200",
    "seller_id": "SELLER-42",
    "seller_price": 450,
    "recommended_price": 430,
    "seller_stock": 12,
    "supplier_lead_time_days": 7,
    "minimum_margin_percent": 12,
    "cost_price": 320,
    "competitors": [
        {"price": 420, "stock_status": "in_stock"},
        {"price": 410, "stock_status": "out_of_stock"},
        {"price": 415, "stock_status": "out_of_stock"},
    ],
    "opportunity_score": 0.78,
    "demand_indicator": 0.7,
    "inventory_turnover_days": 8,
    "ai_recommendation": {"action": "PRICE_LOWER", "confidence": 0.71},
}

EXAMPLE_EXPECTED_OUTPUT: dict[str, Any] = {
    "urgency_level": "HIGH",
    "action_type": "PRICE_LOWER",
    "confidence": "MEDIUM",
}

EXAMPLE_RULE_EVALUATIONS: list[str] = [
    "COMPETITOR_OUT_OF_STOCK",
    "PRICE_GAP_THRESHOLD",
    "HIGH_DEMAND_SIGNAL",
]


class UrgencyEngine:
    """Deterministic urgency engine for competitor intelligence."""

    def __init__(
        self,
        config: UrgencyEngineConfig | None = None,
        *,
        rules: Sequence[UrgencyRule] | None = None,
        logger: logging.Logger | None = None,
        opportunity_calculator: "OpportunityCalculator | None" = None,
    ) -> None:
        self._config = config or UrgencyEngineConfig.from_env()
        self._rules = list(rules) if rules is not None else list(RULE_SET)
        self._logger = logger or logging.getLogger(__name__)
        self._opportunity_calculator = opportunity_calculator

    def evaluate(self, payload: Mapping[str, Any]) -> UrgencyResult:
        start = time.monotonic()
        input_data, quality = UrgencyInput.from_payload(
            payload, config=self._config, logger=self._logger
        )
        derived = self._derive_metrics(input_data)
        if derived.competitor_count < self._config.thresholds.min_competitor_count:
            self._logger.warning(
                "urgency_competitor_data_sparse product_id=%s count=%s",
                input_data.product_id,
                derived.competitor_count,
            )
        context = RuleContext(payload=input_data, derived=derived, config=self._config)
        rule_results = [rule.evaluate(context) for rule in self._rules]
        triggered_rules = [rule.rule_id for rule in rule_results if rule.triggered]
        self._log_event(
            "urgency_rule_evaluation",
            product_id=input_data.product_id,
            seller_id=input_data.seller_id,
            triggered_rules=",".join(triggered_rules),
            competitor_count=derived.competitor_count,
            competitor_oos_ratio=round(derived.competitor_oos_ratio, 2),
        )

        urgency_score = self._compute_urgency_score(input_data, derived, rule_results)
        urgency_level = self._resolve_urgency_level(urgency_score)
        stock_risk_level = self._resolve_stock_risk_level(derived)
        action_type = self._determine_action(input_data, derived, rule_results)
        confidence_score, confidence_level = self._compute_confidence(
            input_data, derived, rule_results, quality
        )
        market_opportunity_score = self._compute_market_opportunity_score(input_data, derived)
        revenue_opportunity = self._compute_revenue_opportunity(input_data, derived)
        reasoning_summary = self._build_reasoning_summary(
            urgency_level, rule_results, derived
        )

        duration_ms = int((time.monotonic() - start) * 1000)
        self._log_event(
            "urgency_engine_complete",
            product_id=input_data.product_id,
            seller_id=input_data.seller_id,
            urgency_score=urgency_score,
            urgency_level=urgency_level,
            action_type=action_type,
            confidence=confidence_level,
            triggered_rules=len(triggered_rules),
            duration_ms=duration_ms,
        )

        diagnostics = {
            "price_gap_percent": _round_or_none(derived.price_gap_percent),
            "margin_percent": _round_or_none(derived.margin_percent),
            "estimated_days_left": round(derived.estimated_days_left, 2),
            "competitor_oos_ratio": round(derived.competitor_oos_ratio, 2),
        }

        return UrgencyResult(
            urgency_score=urgency_score,
            urgency_level=urgency_level,
            action_type=action_type,
            confidence=confidence_level,
            confidence_score=confidence_score,
            revenue_opportunity=revenue_opportunity,
            stock_risk_level=stock_risk_level,
            reasoning_summary=reasoning_summary,
            triggered_rules=triggered_rules,
            market_opportunity_score=market_opportunity_score,
            rule_results=rule_results,
            data_quality=quality,
            diagnostics=diagnostics,
        )

    async def evaluate_async(self, payload: Mapping[str, Any]) -> UrgencyResult:
        return self.evaluate(payload)

    def _derive_metrics(self, payload: UrgencyInput) -> DerivedMetrics:
        competitor_stats = compute_competitor_price_stats(payload.competitor_prices)
        competitor_count = len(payload.competitor_prices)
        competitor_median = competitor_stats["median"]
        competitor_min = competitor_stats["min"]
        competitor_std_dev = competitor_stats["std_dev"]
        price_gap = compute_price_gap_percent(payload.seller_price, competitor_median)
        recommended_gap = compute_price_gap_percent(
            payload.seller_price, payload.recommended_price
        )

        oos_ratio = self._compute_oos_ratio(payload, competitor_count)
        margin_percent = (
            _calculate_margin_percent(payload.seller_price, payload.cost_price)
            if payload.cost_price is not None
            else None
        )
        estimated_days_left = self._estimate_days_left(payload)
        market_position_score = score_market_position(price_gap)
        pricing_pressure = score_pricing_pressure(
            price_gap, self._config.confidence.price_signal_reference_percent
        )
        consistency_score = self._compute_competitor_consistency(
            competitor_median, competitor_std_dev
        )

        return DerivedMetrics(
            competitor_count=competitor_count,
            competitor_oos_ratio=oos_ratio,
            competitor_median_price=competitor_median,
            competitor_min_price=competitor_min,
            competitor_std_dev=competitor_std_dev,
            price_gap_percent=price_gap,
            recommended_gap_percent=recommended_gap,
            margin_percent=margin_percent,
            estimated_days_left=estimated_days_left,
            market_position_score=market_position_score,
            pricing_pressure_score=pricing_pressure,
            competitor_consistency_score=consistency_score,
        )

    def _compute_oos_ratio(self, payload: UrgencyInput, competitor_count: int) -> float:
        if competitor_count == 0:
            return 0.0
        if payload.competitor_oos_count is not None:
            return clamp(
                safe_divide(payload.competitor_oos_count, competitor_count, default=0.0),
                0.0,
                1.0,
            )
        if not payload.competitor_stock_statuses:
            return 0.0
        oos_count = sum(
            1
            for status in payload.competitor_stock_statuses
            if normalize_stock_status(status) == "out_of_stock"
        )
        return clamp(safe_divide(oos_count, competitor_count, default=0.0), 0.0, 1.0)

    def _estimate_days_left(self, payload: UrgencyInput) -> float:
        if payload.seller_stock <= 0:
            return 0.0
        if payload.inventory_turnover_days is not None:
            return max(payload.inventory_turnover_days, 0.0)
        demand_indicator = payload.demand_indicator or 0.3
        base_velocity = 1.0 + demand_indicator
        return payload.seller_stock / max(base_velocity, 0.1)

    def _compute_competitor_consistency(
        self, competitor_median: float | None, std_dev: float | None
    ) -> float:
        if competitor_median is None or competitor_median <= 0 or std_dev is None:
            return 0.5
        coefficient = safe_divide(std_dev, competitor_median, default=1.0)
        return clamp(
            1.0 - safe_divide(coefficient, self._config.confidence.competitor_variance_reference, default=1.0),
            0.0,
            1.0,
        )

    def _compute_urgency_score(
        self,
        payload: UrgencyInput,
        derived: DerivedMetrics,
        rules: Sequence[RuleResult],
    ) -> int:
        thresholds = self._config.thresholds
        weights = self._config.weights

        stock_pressure = score_stock_risk(
            derived.estimated_days_left,
            payload.supplier_lead_time_days,
            thresholds.stockout_days_threshold,
        )
        competitor_pressure = derived.pricing_pressure_score
        market_opportunity = clamp(
            (payload.opportunity_score or 0.0) * 0.6
            + derived.competitor_oos_ratio * 0.4,
            0.0,
            1.0,
        )
        price_competitiveness = 1.0 - derived.market_position_score
        margin_safety = clamp(
            safe_divide(
                thresholds.low_margin_threshold_percent - (derived.margin_percent or thresholds.low_margin_threshold_percent),
                thresholds.low_margin_threshold_percent,
                default=0.0,
            ),
            0.0,
            1.0,
        )
        demand_signal = payload.demand_indicator or 0.3
        lead_time_risk = clamp(
            safe_divide(payload.supplier_lead_time_days, thresholds.lead_time_risk_days, default=0.0),
            0.0,
            1.0,
        )

        weighted_score = (
            stock_pressure * weights.stock_pressure
            + competitor_pressure * weights.competitor_pressure
            + market_opportunity * weights.market_opportunity
            + price_competitiveness * weights.price_competitiveness
            + margin_safety * weights.margin_safety
            + demand_signal * weights.demand_signal
            + lead_time_risk * weights.lead_time_risk
        )
        rule_boost = clamp(
            safe_divide(sum(rule.severity for rule in rules if rule.triggered), 5.0, default=0.0),
            0.0,
            0.15,
        )
        urgency_score = int(round(clamp(weighted_score + rule_boost, 0.0, 1.0) * 100))
        return min(urgency_score, thresholds.critical_max)

    def _resolve_urgency_level(self, score: int) -> UrgencyLevel:
        thresholds = self._config.thresholds
        if score <= thresholds.low_max:
            return "LOW"
        if score <= thresholds.medium_max:
            return "MEDIUM"
        if score <= thresholds.high_max:
            return "HIGH"
        return "CRITICAL"

    def _resolve_stock_risk_level(self, derived: DerivedMetrics) -> StockRiskLevel:
        days_left = derived.estimated_days_left
        if days_left <= 0:
            return "CRITICAL"
        if days_left <= self._config.thresholds.stockout_days_threshold:
            return "HIGH"
        if days_left <= self._config.thresholds.inventory_depletion_days:
            return "MEDIUM"
        return "LOW"

    def _determine_action(
        self,
        payload: UrgencyInput,
        derived: DerivedMetrics,
        rules: Sequence[RuleResult],
    ) -> ActionType:
        rule_actions = [rule.action_hint for rule in rules if rule.triggered and rule.action_hint]

        # Priority order keeps decisions deterministic.
        priority = [
            "REORDER",
            "STOCK_WARNING",
            "PRICE_LOWER",
            "PRICE_RAISE",
            "OPPORTUNITY_CAPTURE",
            "HOLD",
        ]
        for action in priority:
            if action in rule_actions:
                if action == "PRICE_LOWER" and not self._is_margin_safe(payload, derived):
                    return "HOLD"
                return action

        if payload.ai_action and payload.ai_action in priority:
            return payload.ai_action

        return "HOLD"

    def _is_margin_safe(self, payload: UrgencyInput, derived: DerivedMetrics) -> bool:
        if derived.margin_percent is None:
            return True
        return derived.margin_percent >= payload.minimum_margin_percent

    def _compute_confidence(
        self,
        payload: UrgencyInput,
        derived: DerivedMetrics,
        rules: Sequence[RuleResult],
        quality: DataQualityReport,
    ) -> tuple[float, ConfidenceLevel]:
        config = self._config.confidence
        triggered = sum(1 for rule in rules if rule.triggered)
        rule_score = clamp(
            safe_divide(triggered, config.rules_for_high_confidence, default=0.0),
            0.0,
            1.0,
        )
        data_score = clamp(quality.completeness_score, 0.0, 1.0)
        competitor_score = derived.competitor_consistency_score
        recommendation_score = self._recommendation_stability_score(payload)
        pricing_signal_score = clamp(
            safe_divide(abs(derived.price_gap_percent or 0.0), config.price_signal_reference_percent, default=0.0),
            0.0,
            1.0,
        )

        weighted = (
            rule_score * config.weight_rules
            + data_score * config.weight_data
            + competitor_score * config.weight_competitor_consistency
            + recommendation_score * config.weight_recommendation_stability
            + pricing_signal_score * config.weight_pricing_signal
        )
        weighted = clamp(weighted, 0.0, 1.0)
        if quality.completeness_score < config.min_data_completeness:
            weighted *= safe_divide(
                quality.completeness_score,
                config.min_data_completeness,
                default=0.5,
            )

        if weighted >= config.high_confidence_threshold:
            return round(weighted, 2), "HIGH"
        if weighted >= config.medium_confidence_threshold:
            return round(weighted, 2), "MEDIUM"
        return round(weighted, 2), "LOW"

    def _recommendation_stability_score(self, payload: UrgencyInput) -> float:
        if payload.recommended_price is None:
            return 0.5
        delta_percent = abs(payload.recommended_price - payload.seller_price) / payload.seller_price * 100.0
        return clamp(
            1.0 - safe_divide(delta_percent, self._config.confidence.max_recommendation_delta_percent, default=1.0),
            0.0,
            1.0,
        )

    def _compute_market_opportunity_score(
        self, payload: UrgencyInput, derived: DerivedMetrics
    ) -> int:
        opportunity = payload.opportunity_score or 0.0
        demand = payload.demand_indicator or 0.0
        score = clamp(
            (opportunity * 0.4) + (demand * 0.3) + (derived.competitor_oos_ratio * 0.3),
            0.0,
            1.0,
        )
        return int(round(score * 100))

    def _compute_revenue_opportunity(
        self, payload: UrgencyInput, derived: DerivedMetrics
    ) -> float:
        from app.recommendations.opportunity_calculator import (
            OpportunityCalculationError,
            OpportunityCalculator,
            OpportunityInput,
        )

        calculator = self._opportunity_calculator or OpportunityCalculator(
            config=self._config.opportunity, logger=self._logger
        )
        opportunity_input = OpportunityInput(
            seller_price=payload.seller_price,
            recommended_price=payload.recommended_price,
            current_stock=payload.seller_stock,
            margin_percent=derived.margin_percent or 0.0,
            opportunity_score=payload.opportunity_score or 0.0,
            demand_indicator=payload.demand_indicator or 0.0,
            competitor_oos_ratio=derived.competitor_oos_ratio,
            inventory_turnover_days=payload.inventory_turnover_days,
        )
        try:
            result = calculator.calculate(opportunity_input)
        except OpportunityCalculationError as exc:
            self._logger.warning(
                "urgency_opportunity_error product_id=%s error=%s",
                payload.product_id,
                exc,
            )
            return 0.0
        self._logger.info(
            "urgency_opportunity_complete product_id=%s revenue=%s",
            payload.product_id,
            round(result.additional_revenue, 2),
        )
        return result.additional_revenue

    def _build_reasoning_summary(
        self,
        urgency_level: UrgencyLevel,
        rules: Sequence[RuleResult],
        derived: DerivedMetrics,
    ) -> str:
        triggered = [rule for rule in rules if rule.triggered]
        if not triggered:
            return "No critical market or inventory risks detected."

        top = sorted(triggered, key=lambda rule: rule.severity, reverse=True)[:3]
        summary_parts = [rule.summary for rule in top]
        if derived.price_gap_percent is not None:
            summary_parts.append(f"Price gap {derived.price_gap_percent:.1f}% vs market.")
        return f"{urgency_level} urgency: " + " ".join(summary_parts)

    def _log_event(self, event: str, **fields: Any) -> None:
        safe_fields = {key: value for key, value in fields.items() if value is not None}
        payload = " ".join(f"{key}={value}" for key, value in safe_fields.items())
        self._logger.info(f"{event} {payload}".strip())


def _parse_competitor_payload(
    competitors: Any,
    competitor_prices: Any,
    competitor_statuses: Any,
) -> tuple[list[float], list[str]]:
    prices: list[float] = []
    statuses: list[str] = []
    if isinstance(competitors, Iterable) and not isinstance(competitors, (str, bytes, Mapping)):
        for entry in competitors:
            if not isinstance(entry, Mapping):
                continue
            price = _optional_float(entry.get("price") or entry.get("competitor_price"), positive=True)
            if price is not None:
                prices.append(price)
            status = _string_value(entry, "stock_status", fallback="availability")
            if status:
                statuses.append(status)
    if isinstance(competitor_prices, Sequence) and not isinstance(competitor_prices, (str, bytes)):
        prices.extend(_parse_float_list(competitor_prices))
    if isinstance(competitor_statuses, Sequence) and not isinstance(
        competitor_statuses, (str, bytes)
    ):
        statuses.extend([status for status in competitor_statuses if isinstance(status, str)])
    return prices, statuses


def _parse_float_list(value: Any) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    parsed: list[float] = []
    for item in value:
        parsed_value = _optional_float(item, non_negative=True)
        if parsed_value is not None:
            parsed.append(parsed_value)
    return parsed


def _calculate_margin_percent(selling_price: float, cost_price: float) -> float:
    if selling_price <= 0:
        return 0.0
    return ((selling_price - cost_price) / selling_price) * 100.0


def _round_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 2)


def _require_float(
    payload: Mapping[str, Any],
    field: str,
    *,
    positive: bool = False,
    non_negative: bool = False,
) -> float:
    value = payload.get(field)
    if value is None or isinstance(value, bool):
        raise InvalidUrgencyInputError(f"{field} is required and must be a number.")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidUrgencyInputError(f"{field} must be a number.") from exc
    if not isfinite(numeric):
        raise InvalidUrgencyInputError(f"{field} must be finite.")
    if positive and numeric <= 0:
        raise InvalidUrgencyInputError(f"{field} must be greater than 0.")
    if non_negative and numeric < 0:
        raise InvalidUrgencyInputError(f"{field} cannot be negative.")
    return numeric


def _require_float_value(
    field: str,
    value: Any,
    *,
    positive: bool = False,
    non_negative: bool = False,
) -> float:
    if value is None or isinstance(value, bool):
        raise InvalidUrgencyInputError(f"{field} is required and must be a number.")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidUrgencyInputError(f"{field} must be a number.") from exc
    if not isfinite(numeric):
        raise InvalidUrgencyInputError(f"{field} must be finite.")
    if positive and numeric <= 0:
        raise InvalidUrgencyInputError(f"{field} must be greater than 0.")
    if non_negative and numeric < 0:
        raise InvalidUrgencyInputError(f"{field} cannot be negative.")
    return numeric


def _require_int(
    payload: Mapping[str, Any],
    field: str,
    *,
    non_negative: bool = False,
) -> int:
    value = payload.get(field)
    if value is None or isinstance(value, bool):
        raise InvalidUrgencyInputError(f"{field} is required and must be an integer.")
    try:
        numeric = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidUrgencyInputError(f"{field} must be an integer.") from exc
    if non_negative and numeric < 0:
        raise InvalidUrgencyInputError(f"{field} cannot be negative.")
    return numeric


def _require_int_value(
    field: str,
    value: Any,
    *,
    non_negative: bool = False,
) -> int:
    if value is None or isinstance(value, bool):
        raise InvalidUrgencyInputError(f"{field} is required and must be an integer.")
    try:
        numeric = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidUrgencyInputError(f"{field} must be an integer.") from exc
    if non_negative and numeric < 0:
        raise InvalidUrgencyInputError(f"{field} cannot be negative.")
    return numeric


def _optional_float(
    value: Any,
    *,
    positive: bool = False,
    non_negative: bool = False,
    min_value: float | None = None,
    max_value: float | None = None,
) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(numeric):
        return None
    if positive and numeric <= 0:
        return None
    if non_negative and numeric < 0:
        return None
    if min_value is not None and numeric < min_value:
        return None
    if max_value is not None and numeric > max_value:
        return None
    return numeric


def _optional_int(value: Any, *, non_negative: bool = False) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return None
    if non_negative and numeric < 0:
        return None
    return numeric


def _string_value(
    payload: Mapping[str, Any],
    field: str,
    *,
    fallback: str | None = None,
) -> str | None:
    value = payload.get(field)
    if value is None and fallback:
        value = payload.get(fallback)
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    return None


def _value_with_fallback(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload.get(key) is not None:
            return payload.get(key)
    return None


def _get_env_float(key: str, default: float) -> float:
    value = os.getenv(key)
    if value is None:
        return default
    try:
        numeric = float(value)
    except ValueError:
        return default
    return numeric


def _get_env_int(key: str, default: int) -> int:
    value = os.getenv(key)
    if value is None:
        return default
    try:
        numeric = int(value)
    except ValueError:
        return default
    return numeric


if __name__ == "__main__":
    sample_payload = {
        "product_id": "DBL200",
        "seller_id": "SELLER-42",
        "seller_price": 450,
        "recommended_price": 430,
        "seller_stock": 12,
        "supplier_lead_time_days": 7,
        "minimum_margin_percent": 12,
        "cost_price": 320,
        "competitors": [
            {"price": 420, "stock_status": "in_stock"},
            {"price": 410, "stock_status": "out_of_stock"},
            {"price": 415, "stock_status": "out_of_stock"},
        ],
        "opportunity_score": 0.78,
        "demand_indicator": 0.7,
        "inventory_turnover_days": 8,
        "ai_recommendation": {"action": "PRICE_LOWER", "confidence": 0.71},
    }

    engine = UrgencyEngine()
    output = engine.evaluate(sample_payload)
    print(output.to_dict())
