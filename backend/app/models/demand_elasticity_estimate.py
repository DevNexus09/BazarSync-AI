from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, Date, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.seller import Seller


class DemandEstimationMethod(str, Enum):
    HISTORICAL_ELASTICITY = "HISTORICAL_ELASTICITY"
    CATEGORY_PRIOR = "CATEGORY_PRIOR"
    CONSERVATIVE_HEURISTIC = "CONSERVATIVE_HEURISTIC"
    POOLED_CATEGORY = "POOLED_CATEGORY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class DemandEstimateDataStatus(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    LIMITED = "LIMITED"
    INSUFFICIENT = "INSUFFICIENT"
    STALE = "STALE"


class DemandElasticityEstimate(Base):
    __tablename__ = "demand_elasticity_estimates"
    __table_args__ = (
        UniqueConstraint("seller_id", "product_id", "observation_end", "calculation_version", name="uq_demand_elasticity_scope_end_version"),
        CheckConstraint("sample_count >= 0", name="ck_demand_elasticity_sample_count_nonnegative"),
        CheckConstraint("baseline_units IS NULL OR baseline_units >= 0", name="ck_demand_elasticity_baseline_nonnegative"),
        CheckConstraint("confidence >= 0 AND confidence <= 100", name="ck_demand_elasticity_confidence_range"),
        Index("ix_demand_elasticity_product_calculated", "product_id", "calculated_at"),
        Index("ix_demand_elasticity_seller_calculated", "seller_id", "calculated_at"),
        Index("ix_demand_elasticity_method_calculated", "estimation_method", "calculated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    estimation_method: Mapped[DemandEstimationMethod] = mapped_column(SAEnum(DemandEstimationMethod, name="demand_estimation_method"), nullable=False)
    elasticity: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_units: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    observation_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    observation_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    quality_metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    data_status: Mapped[DemandEstimateDataStatus] = mapped_column(SAEnum(DemandEstimateDataStatus, name="demand_estimate_data_status"), nullable=False)
    calculation_version: Mapped[str] = mapped_column(String(40), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship(back_populates="demand_elasticity_estimates")
    product: Mapped["Product"] = relationship(back_populates="demand_elasticity_estimates")
