from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.seller import Seller


class PromotionPlanStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXECUTION_NOT_IMPLEMENTED = "EXECUTION_NOT_IMPLEMENTED"


class PromotionResultStatus(str, Enum):
    CALCULATED = "CALCULATED"
    PARTIAL = "PARTIAL"
    MISSING_DATA = "MISSING_DATA"
    FAILED = "FAILED"


class PromotionPlan(Base):
    __tablename__ = "promotion_plans"
    __table_args__ = (
        Index("ix_promotion_plans_seller_id", "seller_id"),
        Index("ix_promotion_plans_product_id", "product_id"),
        Index("ix_promotion_plans_marketplace", "marketplace"),
        Index("ix_promotion_plans_status", "status"),
        Index("ix_promotion_plans_planned_start_at", "planned_start_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    marketplace: Mapped[str | None] = mapped_column(String(120), nullable=True)
    promotion_type: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_discount_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    proposed_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    planned_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    planned_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[PromotionPlanStatus] = mapped_column(
        SAEnum(PromotionPlanStatus, name="promotion_plan_status"),
        nullable=False,
        default=PromotionPlanStatus.PROPOSED,
        server_default=PromotionPlanStatus.PROPOSED.value,
    )
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="UNKNOWN", server_default="UNKNOWN")
    created_from_recommendation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_from_copilot_proposal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    safety_checks_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    expected_impact_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship(back_populates="promotion_plans")
    product: Mapped["Product | None"] = relationship(back_populates="promotion_plans")
    results: Mapped[list["PromotionResult"]] = relationship(back_populates="promotion_plan")


class PromotionResult(Base):
    __tablename__ = "promotion_results"
    __table_args__ = (
        Index("ix_promotion_results_seller_id", "seller_id"),
        Index("ix_promotion_results_product_id", "product_id"),
        Index("ix_promotion_results_promotion_plan_id", "promotion_plan_id"),
        Index("ix_promotion_results_marketplace", "marketplace"),
        Index("ix_promotion_results_started_at", "started_at"),
        Index("ix_promotion_results_ended_at", "ended_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False)
    promotion_plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("promotion_plans.id", ondelete="SET NULL"), nullable=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    marketplace: Mapped[str | None] = mapped_column(String(120), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    units_sold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gross_revenue: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    estimated_profit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    spend: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    discount_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    roi: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    result_status: Mapped[PromotionResultStatus] = mapped_column(
        SAEnum(PromotionResultStatus, name="promotion_result_status"),
        nullable=False,
        default=PromotionResultStatus.MISSING_DATA,
        server_default=PromotionResultStatus.MISSING_DATA.value,
    )
    evidence_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    missing_data_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship(back_populates="promotion_results")
    product: Mapped["Product | None"] = relationship(back_populates="promotion_results")
    promotion_plan: Mapped["PromotionPlan | None"] = relationship(back_populates="results")
