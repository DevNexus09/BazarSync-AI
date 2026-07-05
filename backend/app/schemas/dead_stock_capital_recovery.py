from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.dead_stock_capital_recovery import CapitalRecoveryEstimationMethod, CapitalRecoveryEstimateStatus
from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryAction


class PotentialRecoveredCash(BaseModel):
    low: Decimal | None
    central: Decimal | None
    high: Decimal | None


class DeadStockCapitalRecoveryEstimateResponse(BaseModel):
    id: UUID | None = None
    seller_id: UUID
    product_id: UUID
    dead_stock_assessment_id: UUID | None
    recovery_recommendation_id: UUID | None
    eligible_quantity: int = Field(..., ge=0)
    unit_cost: Decimal | None
    locked_capital: Decimal | None
    currency: str
    recommended_action: str | None
    candidate_price: Decimal | None
    expected_units_low: Decimal | None
    expected_units: Decimal | None
    expected_units_high: Decimal | None
    potential_recovered_cash: PotentialRecoveredCash
    gross_recovered_cash_low: Decimal | None
    gross_recovered_cash: Decimal | None
    gross_recovered_cash_high: Decimal | None
    net_cash_recovered: Decimal | None
    contribution_recovered: Decimal | None
    cost_basis_recovered: Decimal | None
    remaining_locked_capital: Decimal | None
    capital_recovery_ratio: Decimal | None
    estimation_method: CapitalRecoveryEstimationMethod
    estimate_status: CapitalRecoveryEstimateStatus
    confidence_score: Decimal = Field(..., ge=0, le=100)
    evidence: dict[str, Any]
    calculation_version: str
    calculated_at: datetime
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def add_derived_fields(cls, value):
        if not isinstance(value, dict):
            evidence = getattr(value, "evidence", {}) or {}
            return {
                **{name: getattr(value, name, None) for name in cls.model_fields if name not in {"currency", "recommended_action", "potential_recovered_cash"}},
                "currency": evidence.get("currency", "BDT"),
                "recommended_action": evidence.get("recommended_action"),
                "potential_recovered_cash": {
                    "low": getattr(value, "gross_recovered_cash_low", None),
                    "central": getattr(value, "gross_recovered_cash", None),
                    "high": getattr(value, "gross_recovered_cash_high", None),
                },
            }
        value = dict(value)
        value.setdefault("currency", (value.get("evidence") or {}).get("currency", "BDT"))
        value.setdefault("recommended_action", (value.get("evidence") or {}).get("recommended_action"))
        value.setdefault(
            "potential_recovered_cash",
            {
                "low": value.get("gross_recovered_cash_low"),
                "central": value.get("gross_recovered_cash"),
                "high": value.get("gross_recovered_cash_high"),
            },
        )
        return value


class LatestDeadStockCapitalRecoveryEstimateResponse(BaseModel):
    item: DeadStockCapitalRecoveryEstimateResponse | None


class DeadStockRecoverySimulationRequest(BaseModel):
    action: DeadStockRecoveryAction
    candidate_discount: Decimal | None = Field(None, ge=0, lt=1)
    candidate_price: Decimal | None = Field(None, ge=0)
    duration_days: int | None = Field(None, gt=0, le=365)
    eligible_quantity: int | None = Field(None, ge=0)

    @model_validator(mode="after")
    def validate_price_inputs(self):
        if self.candidate_discount is not None and self.candidate_price is not None:
            raise ValueError("Provide candidate_discount or candidate_price, not both.")
        return self
