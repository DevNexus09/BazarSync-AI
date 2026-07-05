from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.dead_stock_assessment import DeadStockAssessment
    from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryRecommendation
    from app.models.product import Product
    from app.models.seller import Seller


class CapitalRecoveryEstimationMethod(str, Enum):
    HISTORICAL_DEMAND_RESPONSE = "HISTORICAL_DEMAND_RESPONSE"
    PRODUCT_PROMOTION_HISTORY = "PRODUCT_PROMOTION_HISTORY"
    CATEGORY_PROMOTION_HISTORY = "CATEGORY_PROMOTION_HISTORY"
    CONSERVATIVE_HEURISTIC = "CONSERVATIVE_HEURISTIC"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class CapitalRecoveryEstimateStatus(str, Enum):
    CALCULATED = "CALCULATED"
    HEURISTIC = "HEURISTIC"
    LIMITED_DATA = "LIMITED_DATA"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    BLOCKED_BY_MARGIN_POLICY = "BLOCKED_BY_MARGIN_POLICY"


class DeadStockCapitalRecoveryEstimate(Base):
    __tablename__ = "dead_stock_capital_recovery_estimates"
    __table_args__ = (
        UniqueConstraint(
            "recovery_recommendation_id",
            "calculation_version",
            name="uq_capital_recovery_recommendation_version",
        ),
        CheckConstraint("eligible_quantity >= 0", name="ck_capital_recovery_eligible_quantity"),
        CheckConstraint("unit_cost IS NULL OR unit_cost >= 0", name="ck_capital_recovery_unit_cost"),
        CheckConstraint("locked_capital IS NULL OR locked_capital >= 0", name="ck_capital_recovery_locked"),
        CheckConstraint("candidate_price IS NULL OR candidate_price >= 0", name="ck_capital_recovery_candidate_price"),
        CheckConstraint("expected_units_low IS NULL OR expected_units_low >= 0", name="ck_capital_recovery_low_units"),
        CheckConstraint("expected_units IS NULL OR expected_units >= 0", name="ck_capital_recovery_units"),
        CheckConstraint("expected_units_high IS NULL OR expected_units_high >= 0", name="ck_capital_recovery_high_units"),
        CheckConstraint("gross_recovered_cash_low IS NULL OR gross_recovered_cash_low >= 0", name="ck_capital_recovery_gross_low"),
        CheckConstraint("gross_recovered_cash IS NULL OR gross_recovered_cash >= 0", name="ck_capital_recovery_gross"),
        CheckConstraint("gross_recovered_cash_high IS NULL OR gross_recovered_cash_high >= 0", name="ck_capital_recovery_gross_high"),
        CheckConstraint("remaining_locked_capital IS NULL OR remaining_locked_capital >= 0", name="ck_capital_recovery_remaining"),
        CheckConstraint("capital_recovery_ratio IS NULL OR capital_recovery_ratio <= 1", name="ck_capital_recovery_ratio"),
        CheckConstraint("confidence_score >= 0 AND confidence_score <= 100", name="ck_capital_recovery_confidence"),
        Index("ix_capital_recovery_seller_product_calculated", "seller_id", "product_id", "calculated_at"),
        Index("ix_capital_recovery_status", "estimate_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    dead_stock_assessment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("dead_stock_assessments.id", ondelete="SET NULL"), nullable=True)
    recovery_recommendation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("dead_stock_recovery_recommendations.id", ondelete="SET NULL"), nullable=True)
    eligible_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    locked_capital: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    candidate_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    expected_units_low: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    expected_units: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    expected_units_high: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    gross_recovered_cash_low: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    gross_recovered_cash: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    gross_recovered_cash_high: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    net_cash_recovered: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    contribution_recovered: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    cost_basis_recovered: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    remaining_locked_capital: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    capital_recovery_ratio: Mapped[Decimal | None] = mapped_column(Numeric(7, 6), nullable=True)
    estimation_method: Mapped[CapitalRecoveryEstimationMethod] = mapped_column(SAEnum(CapitalRecoveryEstimationMethod, name="capital_recovery_estimation_method"), nullable=False)
    estimate_status: Mapped[CapitalRecoveryEstimateStatus] = mapped_column(SAEnum(CapitalRecoveryEstimateStatus, name="capital_recovery_estimate_status"), nullable=False)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    calculation_version: Mapped[str] = mapped_column(String(20), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship(back_populates="dead_stock_capital_recovery_estimates")
    product: Mapped["Product"] = relationship(back_populates="dead_stock_capital_recovery_estimates")
    dead_stock_assessment: Mapped["DeadStockAssessment | None"] = relationship()
    recovery_recommendation: Mapped["DeadStockRecoveryRecommendation | None"] = relationship()
