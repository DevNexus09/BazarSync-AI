from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class DeadStockReadinessStatus(str, Enum):
    OK = "OK"
    MISSING = "MISSING"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"
    INSUFFICIENT = "INSUFFICIENT"
    PENDING_CALCULATION = "PENDING_CALCULATION"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    OPTIONAL = "OPTIONAL"
    ERROR = "ERROR"


class DeadStockReadinessCheck(BaseModel):
    status: DeadStockReadinessStatus
    reason_code: str | None = None
    message: str
    blocking: bool
    current_value: Any = None
    next_action: str | None = None
    href: str | None = None


class DeadStockReadinessNextAction(BaseModel):
    key: str
    label: str
    description: str
    href: str | None = None
    implemented: bool
    priority: int


class DeadStockReadinessResponse(BaseModel):
    product_id: UUID
    product_name: str
    ready: bool
    can_classify_dead_stock: bool
    can_score_risk: bool
    can_estimate_locked_capital: bool
    can_generate_recovery_recommendation: bool
    can_estimate_potential_recovery: bool
    checks: dict[str, DeadStockReadinessCheck]
    blocking_reasons: list[str]
    non_blocking_reasons: list[str]
    next_actions: list[DeadStockReadinessNextAction]
    recommended_setup_order: list[str]
    last_checked_at: datetime


class DeadStockRecalculationResponse(BaseModel):
    product_id: UUID
    enqueued: bool
    message: str
    readiness: DeadStockReadinessResponse
