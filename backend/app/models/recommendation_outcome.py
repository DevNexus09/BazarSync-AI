from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
import uuid

from sqlalchemy import Boolean, Date, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RecommendationOutcomeType(str, Enum):
    PRICING = "PRICING"
    REORDER = "REORDER"
    RECOVERY = "RECOVERY"


class RecommendationOutcomeStatus(str, Enum):
    OBSERVED = "OBSERVED"
    UNAVAILABLE = "UNAVAILABLE"


class RecommendationOutcome(Base):
    """What happened after a seller acted on a recommendation. One row per recommendation and window."""

    __tablename__ = "recommendation_outcomes"
    __table_args__ = (
        UniqueConstraint("recommendation_id", "window_days", name="uq_recommendation_outcomes_recommendation_window"),
        Index("ix_recommendation_outcomes_seller_type_evaluated", "seller_id", "recommendation_type", "evaluated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    recommendation_type: Mapped[RecommendationOutcomeType] = mapped_column(
        SAEnum(RecommendationOutcomeType, name="recommendation_outcome_type"), nullable=False
    )
    # Not a foreign key: it points at a row in the table named by recommendation_type.
    recommendation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_start: Mapped[date] = mapped_column(Date, nullable=False)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    predicted_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    observed_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    observed_status: Mapped[RecommendationOutcomeStatus] = mapped_column(
        SAEnum(RecommendationOutcomeStatus, name="recommendation_outcome_status"), nullable=False
    )
    hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    calculation_version: Mapped[str] = mapped_column(String(40), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
