"""Internal recommendation proposals projected from specialized engines."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    model_validator,
)

from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryAction
from app.models.recommendation import RecommendationAction

# Both price-producing engines currently use MarginGuard for Daraz Bangladesh.
Currency = Literal["BDT"]
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
MAX_PERSISTED_PRICE = Decimal("9999999999.99")
Price = Annotated[Decimal, Field(gt=0, decimal_places=2)]
Quantity = Annotated[int, Field(strict=True, ge=0)]


class CandidateEngine(str, Enum):
    DYNAMIC_PRICING = "dynamic_pricing"
    REORDER = "reorder"
    DEAD_STOCK_RECOVERY = "dead_stock_recovery"


class CandidateStatus(str, Enum):
    GENERATED = "generated"
    ELIGIBLE = "eligible"
    REJECTED = "rejected"
    SELECTED = "selected"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class EvidenceSource(str, Enum):
    PRICING_ANALYTICS = "pricing_analytics"
    ELASTICITY_ESTIMATE = "elasticity_estimate"
    INVENTORY_SNAPSHOT = "inventory_snapshot"
    SALES_VELOCITY = "sales_velocity"
    STOCKOUT_PREDICTION = "stockout_prediction"
    DEAD_STOCK_ASSESSMENT = "dead_stock_assessment"


class _InternalSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class CandidateEvidence(_InternalSchema):
    record_id: UUID | None = None
    inputs: dict[EvidenceSource, UUID] = Field(default_factory=dict)
    snapshot: dict[str, JsonValue] = Field(min_length=1)


class PricingParameters(_InternalSchema):
    current_price: Decimal = Field(ge=0, decimal_places=2)
    target_price: Price | None = None
    currency: Currency


class ReorderParameters(_InternalSchema):
    quantity: Quantity | None
    deadline: date | None = None


class RecoveryParameters(_InternalSchema):
    action: DeadStockRecoveryAction
    secondary_actions: tuple[DeadStockRecoveryAction, ...] = ()
    promotional_price: Price | None = None
    currency: Currency | None = None
    discount_rate: Decimal | None = Field(default=None, ge=0, lt=1)
    duration_days: int | None = Field(default=None, strict=True, gt=0)
    quantity: Quantity | None = None

    @model_validator(mode="after")
    def check_recovery_action(self) -> Self:
        priced = self.action in {
            DeadStockRecoveryAction.DISCOUNT,
            DeadStockRecoveryAction.FLASH_SALE,
        }
        has_price_terms = [
            value is not None
            for value in (self.promotional_price, self.currency, self.discount_rate)
        ]
        if (priced and not all(has_price_terms)) or (
            not priced and any(has_price_terms)
        ):
            raise ValueError(
                "Only a discount or flash sale requires price, currency and discount rate."
            )
        if (self.action == DeadStockRecoveryAction.FLASH_SALE) != (
            self.duration_days is not None
        ):
            raise ValueError("Only a flash sale requires a campaign duration.")
        if (priced or self.action == DeadStockRecoveryAction.BUNDLE) != (
            self.quantity is not None
        ):
            raise ValueError(
                "Only a discount, flash sale or bundle requires a recovery quantity."
            )
        return self


class FinancialImpact(_InternalSchema):
    currency: Currency
    revenue_delta: Decimal | None = Field(default=None, decimal_places=2)
    profit_delta: Decimal | None = Field(default=None, decimal_places=2)

    @model_validator(mode="after")
    def require_estimate(self) -> Self:
        if self.revenue_delta is None and self.profit_delta is None:
            raise ValueError("Supply at least one estimate or omit financial impact.")
        return self


class ForecastInterval(_InternalSchema):
    kind: Literal["sensitivity_band", "prediction_interval"]
    metric: Literal["demand_units", "profit_delta_bdt"]
    lower: Decimal
    central: Decimal
    upper: Decimal
    coverage_probability: Decimal | None = Field(default=None, gt=0, lt=1)

    @model_validator(mode="after")
    def check_bounds(self) -> Self:
        if not self.lower <= self.central <= self.upper:
            raise ValueError("Forecast bounds must contain the central estimate.")
        if self.metric == "demand_units" and self.lower < 0:
            raise ValueError("Demand forecasts require nonnegative units.")
        if self.kind == "sensitivity_band" and self.coverage_probability is not None:
            raise ValueError("Sensitivity bands cannot claim coverage probability.")
        return self


class ForecastRisk(_InternalSchema):
    source: NonBlank
    calculation_version: NonBlank
    horizon_days: int = Field(gt=0, strict=True)
    interval: ForecastInterval | None = None
    adverse_outcome_probability: Decimal | None = Field(default=None, ge=0, le=1)
    adverse_outcome: NonBlank | None = None

    @model_validator(mode="after")
    def check_risk(self) -> Self:
        if self.interval is None and self.adverse_outcome_probability is None:
            raise ValueError(
                "Supply a forecast interval or an adverse outcome probability."
            )
        if (self.adverse_outcome_probability is None) != (self.adverse_outcome is None):
            raise ValueError(
                "An adverse outcome and its probability must be supplied together."
            )
        return self


class RecommendationCandidate(_InternalSchema):
    candidate_id: UUID
    seller_id: UUID
    product_id: UUID
    source_engine: CandidateEngine
    action_type: RecommendationAction
    proposed_parameters: PricingParameters | ReorderParameters | RecoveryParameters
    evidence: CandidateEvidence
    estimated_financial_impact: FinancialImpact | None = None
    forecast_risk: ForecastRisk | None = None
    confidence: Decimal | None = Field(default=None, ge=0, le=100)
    calculation_version: NonBlank
    generated_at: datetime
    as_of_date: date | None = None
    expires_at: datetime | None = None
    evaluation_status: CandidateStatus = CandidateStatus.GENERATED
    rejection_reasons: tuple[NonBlank, ...] = ()

    @model_validator(mode="after")
    def check_candidate(self) -> Self:
        if (self.evaluation_status == CandidateStatus.REJECTED) != bool(
            self.rejection_reasons
        ):
            raise ValueError("Rejected candidates require rejection reasons.")
        params = self.proposed_parameters
        if isinstance(params, PricingParameters):
            self._check_pricing(params)
        elif isinstance(params, ReorderParameters):
            if self.source_engine != CandidateEngine.REORDER:
                raise ValueError("Reorder parameters require the reorder engine.")
            if self.action_type == RecommendationAction.REORDER:
                if not params.quantity:
                    raise ValueError("REORDER requires a positive whole-unit quantity.")
            elif (
                self.action_type != RecommendationAction.HOLD
                or params.quantity not in (0, None)
            ):
                raise ValueError("The reorder engine can only propose REORDER or HOLD.")
        elif (
            self.source_engine != CandidateEngine.DEAD_STOCK_RECOVERY
            or self.action_type != RecommendationAction.HOLD
        ):
            raise ValueError(
                "Recovery proposals must use HOLD and carry a specialized action."
            )
        if self.estimated_financial_impact is not None and not isinstance(
            params, PricingParameters
        ):
            raise ValueError(
                "Only dynamic pricing supplies incremental financial estimates."
            )
        return self

    def _check_pricing(self, params: PricingParameters) -> None:
        if self.source_engine != CandidateEngine.DYNAMIC_PRICING:
            raise ValueError("Pricing parameters require the dynamic pricing engine.")
        if (
            self.action_type == RecommendationAction.HOLD
            and params.target_price is None
        ):
            if self.estimated_financial_impact is not None:
                raise ValueError("Price impact requires a target price.")
            return
        if params.target_price is not None:
            if (
                self.action_type == RecommendationAction.LOWER
                and params.target_price < params.current_price
            ):
                return
            if (
                self.action_type == RecommendationAction.RAISE
                and params.target_price > params.current_price
            ):
                return
        raise ValueError(
            "Pricing requires a directional target for LOWER or RAISE, or no target for HOLD."
        )
