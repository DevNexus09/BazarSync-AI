"""Validated inputs shared by the recommendation engines."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.schemas.pricing_policy import (
    MarketplaceFeePolicyResponse,
    PricingPolicyResponse,
)
from app.services.recommendation_evidence_service import RecommendationEvidence

Nonnegative = Annotated[Decimal, Field(ge=0)]
Units = Annotated[int, Field(ge=0, strict=True)]
DemandStatus = Literal["OBSERVED", "ESTIMATED_FROM_RECORDED_SALES", "INSUFFICIENT"]


class DecisionInventory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: UUID
    captured_at: AwareDatetime
    on_hand_units: Units
    reserved_units: Units
    available_units: Units

    @model_validator(mode="after")
    def check_availability(self) -> Self:
        if self.available_units != max(0, self.on_hand_units - self.reserved_units):
            raise ValueError("Available units must account for reservations.")
        return self


class DecisionSales(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    through: date
    version: str
    status: DemandStatus
    rate: Nonnegative | None
    coverage_id: UUID | None
    valid_records: Units
    sample_days: Units
    window_days: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def check_rate(self) -> Self:
        if (self.rate is None) != (self.status == "INSUFFICIENT"):
            raise ValueError(
                "Demand rate availability must match sales evidence status."
            )
        if self.status == "OBSERVED" and self.coverage_id is None:
            raise ValueError("Observed demand requires coverage.")
        return self


class RecommendationDecisionContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    seller_id: UUID
    product_id: UUID
    evaluated_at: AwareDatetime
    business_date: date
    product_updated_at: AwareDatetime | None
    current_price: Nonnegative | None
    unit_cost: Nonnegative | None
    on_hand_units: Units | None
    supplier_lead_time_days: Annotated[int, Field(gt=0)] | None
    policy: PricingPolicyResponse | None
    effective_fees: MarketplaceFeePolicyResponse | None
    inventory: DecisionInventory | None
    sales: DecisionSales
    competitors: RecommendationEvidence
    validated_competitor_price_count: Units
    quality_flags: tuple[str, ...]
    elasticity_estimate_id: UUID | None
    elasticity_observation_end: date | None
    dead_stock_assessment_id: UUID | None
    dead_stock_assessed_at: AwareDatetime | None

    @model_validator(mode="after")
    def check_scope(self) -> Self:
        scope = (self.seller_id, self.product_id)
        if (self.competitors.seller_id, self.competitors.product_id) != scope:
            raise ValueError("Competitor evidence must match the decision scope.")
        if self.sales.through >= self.business_date:
            raise ValueError("Decision sales must use completed business days.")
        if self.policy and (self.policy.seller_id, self.policy.product_id) != scope:
            raise ValueError("Pricing policy must match the decision scope.")
        if self.effective_fees and (
            self.effective_fees.seller_id != self.seller_id
            or self.effective_fees.product_id not in (None, self.product_id)
            or self.policy is None
            or self.effective_fees.marketplace != self.policy.marketplace
            or self.effective_fees.is_default
        ):
            raise ValueError("Effective fees must match the decision scope and policy.")
        if self.inventory and self.inventory.on_hand_units != self.on_hand_units:
            raise ValueError(
                "Inventory evidence must agree with recorded on-hand stock."
            )
        return self
