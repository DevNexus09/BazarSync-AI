from __future__ import annotations

"""Recommendation persistence model.

Example usage:
    recommendation = Recommendation(
        product_id=product.id,
        action=RecommendationAction.LOWER,
        confidence=RecommendationConfidence.HIGH,
        reasoning_bn="Competitor median price আপনার দামের চেয়ে কম...",
        revenue_opportunity=Decimal("0.00"),
        recommendation_context={
            "competitor_median_price": 420,
            "pricing_pressure_score": 0.74,
            "stock_risk_score": 0.41,
            "days_of_stock_left": 6,
        },
    )

Example stored context:
    {
        "competitor_median_price": 420,
        "pricing_pressure_score": 0.74,
        "stock_risk_score": 0.41,
        "days_of_stock_left": 6
    }
"""

from datetime import datetime
import uuid
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.alert import Alert


class RecommendationAction(str, Enum):
    LOWER = "LOWER"
    RAISE = "RAISE"
    HOLD = "HOLD"
    REORDER = "REORDER"


class RecommendationConfidence(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Recommendation(Base):
    """Stores AI recommendations with analytics context snapshots."""

    __tablename__ = "recommendations"
    __table_args__ = (
        Index("ix_recommendations_product_id", "product_id"),
        Index("ix_recommendations_action", "action"),
        Index("ix_recommendations_confidence", "confidence"),
        Index("ix_recommendations_created_at", "created_at"),
        Index("ix_recommendations_product_created_at", "product_id", "created_at"),
        CheckConstraint(
            "suggested_price_min IS NULL OR suggested_price_max IS NULL OR "
            "suggested_price_min <= suggested_price_max",
            name="ck_recommendations_price_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        index=True,
        default=uuid.uuid4,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    action: Mapped[RecommendationAction] = mapped_column(
        SAEnum(RecommendationAction, name="recommendation_action"),
        default=RecommendationAction.HOLD,
        nullable=False,
    )
    confidence: Mapped[RecommendationConfidence] = mapped_column(
        SAEnum(RecommendationConfidence, name="recommendation_confidence"),
        nullable=False,
    )
    reasoning_bn: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_price_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    suggested_price_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    revenue_opportunity: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0",
    )
    recommendation_context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    product: Mapped["Product"] = relationship(back_populates="recommendations")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="recommendation")

    @validates("reasoning_bn")
    def _validate_reasoning(self, _: str, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("reasoning_bn cannot be empty.")
        return value.strip()

    @validates("revenue_opportunity")
    def _validate_revenue(self, _: str, value: Decimal) -> Decimal:
        if value is None:
            return Decimal("0.00")
        if value < 0:
            raise ValueError("revenue_opportunity cannot be negative.")
        return value

    @validates("suggested_price_min", "suggested_price_max")
    def _validate_suggested_price(self, key: str, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        if value < 0:
            raise ValueError(f"{key} cannot be negative.")
        other = (
            self.suggested_price_max
            if key == "suggested_price_min"
            else self.suggested_price_min
        )
        if other is not None:
            if key == "suggested_price_min" and value > other:
                raise ValueError("suggested_price_min cannot exceed suggested_price_max.")
            if key == "suggested_price_max" and other > value:
                raise ValueError("suggested_price_max cannot be below suggested_price_min.")
        return value

    @validates("recommendation_context")
    def _validate_context(self, _: str, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict) or not value:
            raise ValueError("recommendation_context must be a non-empty JSON object.")
        return value

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API responses or auditing."""
        return {
            "id": str(self.id),
            "product_id": str(self.product_id),
            "action": self.action.value,
            "confidence": self.confidence.value,
            "reasoning_bn": self.reasoning_bn,
            "suggested_price_min": _decimal_to_float(self.suggested_price_min),
            "suggested_price_max": _decimal_to_float(self.suggested_price_max),
            "revenue_opportunity": _decimal_to_float(self.revenue_opportunity),
            "recommendation_context": self.recommendation_context,
            "created_at": self.created_at.isoformat(),
        }

    def summary(self) -> str:
        return (
            f"{self.action.value} ({self.confidence.value}) for product {self.product_id}"
        )

    def is_price_recommendation(self) -> bool:
        return self.action in {
            RecommendationAction.LOWER,
            RecommendationAction.RAISE,
            RecommendationAction.HOLD,
        }

    def is_stock_recommendation(self) -> bool:
        return self.action == RecommendationAction.REORDER


def _decimal_to_float(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)
