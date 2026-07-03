from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, DateTime, Enum as SAEnum, ForeignKey, Index, Numeric, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.demand_elasticity_estimate import DemandEstimationMethod
from app.models.pricing_policy import PricingObjective

if TYPE_CHECKING:
    from app.models.demand_elasticity_estimate import DemandElasticityEstimate
    from app.models.pricing_analytics_snapshot import PricingAnalyticsSnapshot
    from app.models.product import Product
    from app.models.seller import Seller


class DynamicPricingAction(str, Enum):
    PRICE_LOWER = "PRICE_LOWER"
    PRICE_RAISE = "PRICE_RAISE"
    HOLD = "HOLD"


class DynamicPricingRecommendationStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISMISSED = "DISMISSED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class DynamicPricingRecommendation(Base):
    __tablename__ = "dynamic_pricing_recommendations"
    __table_args__ = (
        UniqueConstraint(
            "seller_id",
            "product_id",
            "pricing_analytics_id",
            "objective",
            "formula_version",
            name="uq_dynamic_pricing_recommendation_snapshot_objective",
        ),
        CheckConstraint("current_price >= 0", name="ck_dynamic_pricing_current_price_nonnegative"),
        CheckConstraint("recommended_price >= 0", name="ck_dynamic_pricing_recommended_price_nonnegative"),
        CheckConstraint("minimum_safe_price IS NULL OR minimum_safe_price >= 0", name="ck_dynamic_pricing_safe_price_nonnegative"),
        CheckConstraint("expected_units IS NULL OR expected_units >= 0", name="ck_dynamic_pricing_expected_units_nonnegative"),
        CheckConstraint("expected_revenue IS NULL OR expected_revenue >= 0", name="ck_dynamic_pricing_expected_revenue_nonnegative"),
        CheckConstraint("baseline_expected_revenue IS NULL OR baseline_expected_revenue >= 0", name="ck_dynamic_pricing_baseline_revenue_nonnegative"),
        CheckConstraint("confidence_score >= 0 AND confidence_score <= 100", name="ck_dynamic_pricing_confidence_range"),
        Index("ix_dynamic_pricing_product_generated", "product_id", "generated_at"),
        Index("ix_dynamic_pricing_seller_status", "seller_id", "recommendation_status"),
        Index(
            "uq_dynamic_pricing_active_product_objective",
            "seller_id",
            "product_id",
            "objective",
            "formula_version",
            unique=True,
            postgresql_where=text("recommendation_status = 'OPEN'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    pricing_analytics_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("pricing_analytics_snapshots.id", ondelete="RESTRICT"), nullable=False)
    elasticity_estimate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("demand_elasticity_estimates.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[DynamicPricingAction] = mapped_column(SAEnum(DynamicPricingAction, name="dynamic_pricing_action"), nullable=False)
    current_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    recommended_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    minimum_safe_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    expected_units: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    expected_revenue: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    expected_profit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    baseline_expected_revenue: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    baseline_expected_profit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    revenue_impact: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    profit_impact: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    margin_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    estimation_method: Mapped[DemandEstimationMethod] = mapped_column(SAEnum(DemandEstimationMethod, name="demand_estimation_method"), nullable=False)
    recommendation_status: Mapped[DynamicPricingRecommendationStatus] = mapped_column(SAEnum(DynamicPricingRecommendationStatus, name="dynamic_pricing_recommendation_status"), nullable=False)
    objective: Mapped[PricingObjective] = mapped_column(SAEnum(PricingObjective, name="pricing_objective"), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    formula_version: Mapped[str] = mapped_column(String(40), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship(back_populates="dynamic_pricing_recommendations")
    product: Mapped["Product"] = relationship(back_populates="dynamic_pricing_recommendations")
    pricing_analytics: Mapped["PricingAnalyticsSnapshot"] = relationship()
    elasticity_estimate: Mapped["DemandElasticityEstimate | None"] = relationship()
