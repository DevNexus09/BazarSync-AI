"""Recommendation Context Builder.

This module bridges deterministic analytics and the AI explanation layer.
Analytics metrics are validated and normalized here so the LLM receives only
clean, prompt-safe, structured data. No business metrics are calculated here.

Example usage:
    product = {
        "id": "DBL200",
        "title": "Dove Body Lotion 200ml",
        "selling_price": 450,
        "cost_price": 320,
        "stock_quantity": 20,
        "supplier_lead_time": 7,
        "minimum_margin": 15,
    }

    competitors = [
        {"competitor_price": 430, "stock_status": "in_stock"},
        {"competitor_price": 420, "stock_status": "out_of_stock"},
    ]

    analytics = {
        "action": "LOWER",
        "confidence": 0.82,
        "competitor_min_price": 420,
        "competitor_median_price": 435,
        "estimated_margin_percent": 18,
        "estimated_days_of_stock_left": 6,
        "out_of_stock_competitor_count": 2,
        "pricing_pressure_score": 0.75,
        "stock_risk_score": 0.64,
    }

    builder = RecommendationContextBuilder()
    context = builder.build_context(product, competitors, analytics)
    print(context.to_dict())

Sample output:
    {
        "sku": "DBL200",
        "product_title": "Dove Body Lotion 200ml",
        "seller_price": 450.0,
        "seller_cost": 320.0,
        "seller_stock": 20,
        "competitor_min_price": 420.0,
        "competitor_median_price": 435.0,
        "competitors_oos": 2,
        "margin_after_fees": 18.0,
        "margin_floor": 15.0,
        "days_of_stock_left": 6.0,
        "supplier_lead_time": 7,
        "pricing_pressure_score": 0.75,
        "stock_risk_score": 0.64,
        "recommended_action": "LOWER",
        "recommendation_confidence": 0.82,
    }
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from math import isfinite
import logging
from typing import Any, Mapping, Sequence

from app.analytics.metrics import normalize_stock_status


class RecommendationBuilderError(Exception):
    """Base class for recommendation builder errors."""


class InvalidAnalyticsDataError(RecommendationBuilderError):
    """Raised when analytics output is missing or malformed."""


class MissingCompetitorDataError(RecommendationBuilderError):
    """Raised when competitor data is required but unavailable."""


class InvalidProductDataError(RecommendationBuilderError):
    """Raised when product payload is missing or malformed."""


ALLOWED_ACTIONS = {"LOWER", "RAISE", "HOLD", "REORDER"}


@dataclass(frozen=True)
class ProductData:
    sku: str
    title: str
    selling_price: float
    cost_price: float
    stock_quantity: int
    supplier_lead_time: int
    minimum_margin: float


@dataclass(frozen=True)
class CompetitorData:
    price: float
    stock_status: str | None = None


@dataclass(frozen=True)
class AnalyticsData:
    action: str
    confidence: float
    competitor_min_price: float | None
    competitor_median_price: float | None
    estimated_margin_percent: float
    estimated_days_of_stock_left: float
    out_of_stock_competitor_count: int
    pricing_pressure_score: float
    stock_risk_score: float


@dataclass(frozen=True)
class RecommendationContext:
    sku: str
    product_title: str
    seller_price: float
    seller_cost: float
    seller_stock: int
    competitor_min_price: float | None
    competitor_median_price: float | None
    competitors_oos: int
    margin_after_fees: float
    margin_floor: float
    days_of_stock_left: float
    supplier_lead_time: int
    pricing_pressure_score: float
    stock_risk_score: float
    recommended_action: str
    recommendation_confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "sku": self.sku,
            "product_title": self.product_title,
            "seller_price": self.seller_price,
            "seller_cost": self.seller_cost,
            "seller_stock": self.seller_stock,
            "competitor_min_price": self.competitor_min_price,
            "competitor_median_price": self.competitor_median_price,
            "competitors_oos": self.competitors_oos,
            "margin_after_fees": self.margin_after_fees,
            "margin_floor": self.margin_floor,
            "days_of_stock_left": self.days_of_stock_left,
            "supplier_lead_time": self.supplier_lead_time,
            "pricing_pressure_score": self.pricing_pressure_score,
            "stock_risk_score": self.stock_risk_score,
            "recommended_action": self.recommended_action,
            "recommendation_confidence": self.recommendation_confidence,
        }


class RecommendationContextBuilder:
    """Builds a prompt-safe analytics context for the AI layer."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(__name__)

    # ------------------------
    # Validation / normalization
    # ------------------------

    def validate_product_data(self, payload: Mapping[str, Any]) -> ProductData:
        if not isinstance(payload, Mapping):
            raise InvalidProductDataError("Product payload must be a mapping.")

        sku = _require_string(
            payload, "sku", fallback_key="id", error_cls=InvalidProductDataError
        )
        title = _require_string(payload, "title", error_cls=InvalidProductDataError)
        selling_price = _require_float(
            payload, "selling_price", positive=True, error_cls=InvalidProductDataError
        )
        cost_price = _require_float(
            payload, "cost_price", non_negative=True, error_cls=InvalidProductDataError
        )
        stock_quantity = _require_int(
            payload, "stock_quantity", non_negative=True, error_cls=InvalidProductDataError
        )
        supplier_lead_time = _require_int(
            payload, "supplier_lead_time", positive=True, error_cls=InvalidProductDataError
        )
        minimum_margin = _require_float(
            payload, "minimum_margin", non_negative=True, error_cls=InvalidProductDataError
        )

        return ProductData(
            sku=sku,
            title=title,
            selling_price=_round_decimal(selling_price),
            cost_price=_round_decimal(cost_price),
            stock_quantity=stock_quantity,
            supplier_lead_time=supplier_lead_time,
            minimum_margin=_round_decimal(minimum_margin),
        )

    def validate_analytics_data(
        self, payload: Mapping[str, Any], *, competitor_count: int
    ) -> AnalyticsData:
        if not isinstance(payload, Mapping):
            raise InvalidAnalyticsDataError("Analytics payload must be a mapping.")

        missing = [key for key in _required_analytics_keys() if key not in payload]
        if missing:
            raise InvalidAnalyticsDataError(
                f"Missing analytics fields: {', '.join(missing)}."
            )

        action = _require_string(payload, "action", error_cls=InvalidAnalyticsDataError).upper()
        if action not in ALLOWED_ACTIONS:
            raise InvalidAnalyticsDataError(
                f"Unknown recommendation action '{action}'."
            )

        confidence = _require_float(
            payload,
            "confidence",
            min_value=0.0,
            max_value=1.0,
            error_cls=InvalidAnalyticsDataError,
        )
        raw_competitor_min = payload.get("competitor_min_price")
        raw_competitor_median = payload.get("competitor_median_price")
        competitor_min_price = _optional_float(
            raw_competitor_min,
            positive=True,
            error_cls=InvalidAnalyticsDataError,
        )
        competitor_median_price = _optional_float(
            raw_competitor_median,
            positive=True,
            error_cls=InvalidAnalyticsDataError,
        )
        estimated_margin_percent = _require_float(
            payload,
            "estimated_margin_percent",
            non_negative=True,
            error_cls=InvalidAnalyticsDataError,
        )
        estimated_days_of_stock_left = _require_float(
            payload,
            "estimated_days_of_stock_left",
            non_negative=True,
            error_cls=InvalidAnalyticsDataError,
        )
        out_of_stock_competitor_count = _require_int(
            payload,
            "out_of_stock_competitor_count",
            non_negative=True,
            error_cls=InvalidAnalyticsDataError,
        )
        pricing_pressure_score = _require_float(
            payload,
            "pricing_pressure_score",
            min_value=0.0,
            max_value=1.0,
            error_cls=InvalidAnalyticsDataError,
        )
        stock_risk_score = _require_float(
            payload,
            "stock_risk_score",
            min_value=0.0,
            max_value=1.0,
            error_cls=InvalidAnalyticsDataError,
        )

        if raw_competitor_min is not None and competitor_min_price is None:
            raise InvalidAnalyticsDataError(
                "competitor_min_price must be a positive number or null."
            )
        if raw_competitor_median is not None and competitor_median_price is None:
            raise InvalidAnalyticsDataError(
                "competitor_median_price must be a positive number or null."
            )
        if competitor_count > 0 and (
            competitor_min_price is None or competitor_median_price is None
        ):
            raise InvalidAnalyticsDataError(
                "Competitor price metrics cannot be null when competitors exist."
            )

        return AnalyticsData(
            action=action,
            confidence=_round_decimal(confidence, digits=2),
            competitor_min_price=_round_decimal(competitor_min_price)
            if competitor_min_price is not None
            else None,
            competitor_median_price=_round_decimal(competitor_median_price)
            if competitor_median_price is not None
            else None,
            estimated_margin_percent=_round_decimal(estimated_margin_percent),
            estimated_days_of_stock_left=_round_decimal(estimated_days_of_stock_left),
            out_of_stock_competitor_count=out_of_stock_competitor_count,
            pricing_pressure_score=_round_decimal(pricing_pressure_score, digits=2),
            stock_risk_score=_round_decimal(stock_risk_score, digits=2),
        )

    def normalize_competitor_data(
        self,
        competitors: Sequence[Mapping[str, Any]] | None,
        *,
        require_competitors: bool = False,
    ) -> list[CompetitorData]:
        if competitors is None:
            if require_competitors:
                raise MissingCompetitorDataError("Competitor data is required.")
            self._logger.warning("Competitor data missing; continuing with analytics.")
            return []
        if not isinstance(competitors, Sequence) or isinstance(competitors, (str, bytes)):
            raise MissingCompetitorDataError("Competitor data must be a list.")

        normalized: list[CompetitorData] = []
        for entry in competitors:
            if not isinstance(entry, Mapping):
                self._logger.warning("Skipping malformed competitor entry.")
                continue

            price = _optional_float(
                entry.get("competitor_price"),
                positive=True,
                error_cls=InvalidProductDataError,
            )
            if price is None:
                self._logger.warning("Skipping competitor entry with invalid price.")
                continue

            status = normalize_stock_status(
                _optional_string(entry.get("stock_status"))
                or _optional_string(entry.get("availability"))
            )
            normalized.append(CompetitorData(price=_round_decimal(price), stock_status=status))

        if require_competitors and not normalized:
            raise MissingCompetitorDataError("No valid competitor records provided.")

        return normalized

    # ------------------------
    # Context construction
    # ------------------------

    def build_context(
        self,
        product: Mapping[str, Any],
        competitors: Sequence[Mapping[str, Any]] | None,
        analytics: Mapping[str, Any],
        *,
        require_competitors: bool = False,
    ) -> RecommendationContext:
        product_data = self.validate_product_data(product)
        competitor_data = self.normalize_competitor_data(
            competitors, require_competitors=require_competitors
        )
        analytics_data = self.validate_analytics_data(
            analytics, competitor_count=len(competitor_data)
        )

        competitors_oos = _resolve_oos_count(
            competitor_data, analytics_data.out_of_stock_competitor_count
        )

        return RecommendationContext(
            sku=product_data.sku,
            product_title=product_data.title,
            seller_price=product_data.selling_price,
            seller_cost=product_data.cost_price,
            seller_stock=product_data.stock_quantity,
            competitor_min_price=analytics_data.competitor_min_price,
            competitor_median_price=analytics_data.competitor_median_price,
            competitors_oos=competitors_oos,
            margin_after_fees=analytics_data.estimated_margin_percent,
            margin_floor=product_data.minimum_margin,
            days_of_stock_left=analytics_data.estimated_days_of_stock_left,
            supplier_lead_time=product_data.supplier_lead_time,
            pricing_pressure_score=analytics_data.pricing_pressure_score,
            stock_risk_score=analytics_data.stock_risk_score,
            recommended_action=analytics_data.action,
            recommendation_confidence=analytics_data.confidence,
        )

    def generate_context_summary(self, context: RecommendationContext) -> str:
        """Generate a concise, deterministic summary for logging/monitoring."""
        return (
            f"{context.recommended_action} (conf {context.recommendation_confidence:.2f}) "
            f"price={context.seller_price:.2f}, median={_format_optional(context.competitor_median_price)}, "
            f"stock={context.seller_stock}, days_left={context.days_of_stock_left:.1f}"
        )


def _required_analytics_keys() -> list[str]:
    return [
        "action",
        "confidence",
        "competitor_min_price",
        "competitor_median_price",
        "estimated_margin_percent",
        "estimated_days_of_stock_left",
        "out_of_stock_competitor_count",
        "pricing_pressure_score",
        "stock_risk_score",
    ]


def _round_decimal(value: float, *, digits: int = 2) -> float:
    quant = Decimal("1").scaleb(-digits)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def _format_optional(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


def _require_string(
    payload: Mapping[str, Any],
    key: str,
    *,
    fallback_key: str | None = None,
    error_cls: type[RecommendationBuilderError] = InvalidProductDataError,
) -> str:
    value = payload.get(key)
    if value is None and fallback_key:
        value = payload.get(fallback_key)
    if not isinstance(value, str) or not value.strip():
        raise error_cls(f"{key} is required and must be a string.")
    return value.strip()


def _require_float(
    payload: Mapping[str, Any],
    key: str,
    *,
    positive: bool = False,
    non_negative: bool = False,
    min_value: float | None = None,
    max_value: float | None = None,
    error_cls: type[RecommendationBuilderError] = InvalidProductDataError,
) -> float:
    value = payload.get(key)
    if value is None or isinstance(value, bool):
        raise error_cls(f"{key} is required and must be a number.")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise error_cls(f"{key} must be a number.") from exc

    _validate_numeric_range(
        numeric,
        key,
        positive=positive,
        non_negative=non_negative,
        min_value=min_value,
        max_value=max_value,
        error_cls=error_cls,
    )
    return numeric


def _require_int(
    payload: Mapping[str, Any],
    key: str,
    *,
    non_negative: bool = False,
    positive: bool = False,
    error_cls: type[RecommendationBuilderError] = InvalidProductDataError,
) -> int:
    value = payload.get(key)
    if value is None or isinstance(value, bool):
        raise error_cls(f"{key} is required and must be an integer.")
    try:
        numeric = int(value)
    except (TypeError, ValueError) as exc:
        raise error_cls(f"{key} must be an integer.") from exc

    if positive and numeric <= 0:
        raise error_cls(f"{key} must be greater than 0.")
    if non_negative and numeric < 0:
        raise error_cls(f"{key} cannot be negative.")
    return numeric


def _optional_float(
    value: Any,
    *,
    positive: bool = False,
    non_negative: bool = False,
    min_value: float | None = None,
    max_value: float | None = None,
    error_cls: type[RecommendationBuilderError] = InvalidProductDataError,
) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None

    try:
        _validate_numeric_range(
            numeric,
            "value",
            positive=positive,
            non_negative=non_negative,
            min_value=min_value,
            max_value=max_value,
            error_cls=error_cls,
        )
    except RecommendationBuilderError:
        return None
    return numeric


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    return None


def _validate_numeric_range(
    numeric: float,
    field: str,
    *,
    positive: bool = False,
    non_negative: bool = False,
    min_value: float | None = None,
    max_value: float | None = None,
    error_cls: type[RecommendationBuilderError] = InvalidAnalyticsDataError,
) -> None:
    if not isfinite(numeric):
        raise error_cls(f"{field} must be a finite number.")
    if positive and numeric <= 0:
        raise error_cls(f"{field} must be greater than 0.")
    if non_negative and numeric < 0:
        raise error_cls(f"{field} cannot be negative.")
    if min_value is not None and numeric < min_value:
        raise error_cls(f"{field} must be >= {min_value}.")
    if max_value is not None and numeric > max_value:
        raise error_cls(f"{field} must be <= {max_value}.")


def _resolve_oos_count(
    competitors: Sequence[CompetitorData], analytics_oos: int
) -> int:
    if not competitors:
        return analytics_oos
    oos_count = sum(1 for competitor in competitors if competitor.stock_status == "out_of_stock")
    return max(oos_count, analytics_oos)
