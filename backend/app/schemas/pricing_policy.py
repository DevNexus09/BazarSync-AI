from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.pricing_policy import PricingObjective

Money = Annotated[Decimal, Field(max_digits=12, decimal_places=2, ge=0)]
Rate = Annotated[Decimal, Field(ge=0, lt=1)]


class PricingPolicyUpsert(BaseModel):
    marketplace: str = Field(default="Daraz Bangladesh", min_length=1, max_length=120)
    currency: str = Field(default="BDT", min_length=3, max_length=3)
    minimum_margin_rate: Rate | None = None
    minimum_unit_profit: Money = Decimal("0.00")
    maximum_price_decrease_rate: Rate | None = None
    maximum_price_increase_rate: Decimal | None = Field(default=None, ge=0)
    minimum_allowed_price: Money | None = None
    maximum_allowed_price: Money | None = None
    price_increment: Money = Decimal("1.00")
    recommendation_cooldown_hours: int = Field(default=24, ge=0)
    objective: PricingObjective = PricingObjective.MAXIMIZE_EXPECTED_PROFIT
    is_active: bool = True
    effective_from: datetime | None = None
    effective_to: datetime | None = None


class PricingPolicyResponse(PricingPolicyUpsert):
    id: UUID | None
    seller_id: UUID
    product_id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None
    is_default: bool = False

    model_config = ConfigDict(from_attributes=True)


class MarketplaceFeePolicyUpsert(BaseModel):
    product_id: UUID | None = None
    marketplace: str = Field(default="Daraz Bangladesh", min_length=1, max_length=120)
    category: str | None = Field(default=None, max_length=120)
    currency: str = Field(default="BDT", min_length=3, max_length=3)
    percentage_commission_rate: Rate = Decimal("0.000000")
    payment_fee_rate: Rate = Decimal("0.000000")
    fixed_per_order_fee: Money = Decimal("0.00")
    fixed_per_unit_fee: Money = Decimal("0.00")
    fulfilment_fee: Money = Decimal("0.00")
    shipping_subsidy: Money = Decimal("0.00")
    other_variable_cost: Money = Decimal("0.00")
    source: str = Field(default="MANUAL", min_length=1, max_length=120)
    version: str = Field(default="v1", min_length=1, max_length=40)
    is_active: bool = True
    effective_from: datetime | None = None
    effective_to: datetime | None = None


class MarketplaceFeePolicyExpire(BaseModel):
    effective_to: datetime


class MarketplaceFeePolicyResponse(MarketplaceFeePolicyUpsert):
    id: UUID | None
    seller_id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None
    is_default: bool = False
    scope: str = "seller"

    model_config = ConfigDict(from_attributes=True)


class MarketplaceFeePolicyListResponse(BaseModel):
    items: list[MarketplaceFeePolicyResponse]
    total: int


class FeeBreakdownResponse(BaseModel):
    price: Decimal
    percentage_commission_amount: Decimal
    payment_fee_amount: Decimal
    fixed_per_order_fee: Decimal
    fixed_per_unit_fee: Decimal
    fulfilment_fee: Decimal
    shipping_subsidy: Decimal
    other_variable_cost: Decimal
    total_fee_amount: Decimal


class MinimumSafePricePreviewRequest(BaseModel):
    candidate_price: Money | None = None
    marketplace: str = Field(default="Daraz Bangladesh", min_length=1, max_length=120)
    as_of: datetime | None = None


class MinimumSafePricePreviewResponse(BaseModel):
    product_id: UUID
    marketplace: str
    currency: str
    unit_cost: Decimal
    current_price: Decimal
    minimum_margin_rate: Decimal
    minimum_unit_profit: Decimal
    percentage_fee_rate: Decimal
    fixed_costs: Decimal
    minimum_safe_price: Decimal
    candidate_price: Decimal | None
    candidate_valid: bool | None
    candidate_reasons: list[str]
    unit_profit: Decimal | None
    margin_rate: Decimal | None
    fee_breakdown: FeeBreakdownResponse | None
    formula_version: str = "pricing_policy_v1"
