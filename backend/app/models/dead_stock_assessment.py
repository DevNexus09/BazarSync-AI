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
    from app.models.inventory_aging import InventoryAgingSnapshot
    from app.models.inventory_history import InventoryHistory
    from app.models.product import Product
    from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryRecommendation
    from app.models.sales_velocity import SalesVelocity
    from app.models.seller import Seller


class DeadStockClassification(str, Enum):
    HEALTHY = "HEALTHY"
    SLOW_MOVING = "SLOW_MOVING"
    AT_RISK = "AT_RISK"
    DEAD_STOCK = "DEAD_STOCK"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class DeadStockDataStatus(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    LIMITED = "LIMITED"
    INSUFFICIENT = "INSUFFICIENT"


class DeadStockNoSalesState(str, Enum):
    NO_SALES_WITHIN_THRESHOLD = "NO_SALES_WITHIN_THRESHOLD"
    NEVER_SOLD = "NEVER_SOLD"
    SALES_DATA_INSUFFICIENT = "SALES_DATA_INSUFFICIENT"
    RECENT_SALE = "RECENT_SALE"
    PRODUCT_TOO_NEW = "PRODUCT_TOO_NEW"


class DeadStockInventoryAgeState(str, Enum):
    AGE_THRESHOLD_EXCEEDED = "AGE_THRESHOLD_EXCEEDED"
    AGE_BELOW_THRESHOLD = "AGE_BELOW_THRESHOLD"
    AGE_ESTIMATED = "AGE_ESTIMATED"
    AGE_DATA_UNAVAILABLE = "AGE_DATA_UNAVAILABLE"


class DeadStockVisibilityStatus(str, Enum):
    LOW_VISIBILITY = "LOW_VISIBILITY"
    NORMAL_VISIBILITY = "NORMAL_VISIBILITY"
    VISIBILITY_DATA_LIMITED = "VISIBILITY_DATA_LIMITED"
    VISIBILITY_DATA_UNAVAILABLE = "VISIBILITY_DATA_UNAVAILABLE"


class DeadStockRiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DeadStockAssessment(Base):
    __tablename__ = "dead_stock_assessments"
    __table_args__ = (
        UniqueConstraint("product_id", "as_of_date", "calculation_version", name="uq_dead_stock_product_date_version"),
        CheckConstraint("eligible_quantity >= 0", name="ck_dead_stock_eligible_nonnegative"),
        CheckConstraint("days_since_last_sale IS NULL OR days_since_last_sale >= 0", name="ck_dead_stock_days_since_sale_nonnegative"),
        CheckConstraint("inventory_age_days IS NULL OR inventory_age_days >= 0", name="ck_dead_stock_inventory_age_nonnegative"),
        CheckConstraint("visibility_score IS NULL OR (visibility_score >= 0 AND visibility_score <= 100)", name="ck_dead_stock_visibility_score_range"),
        CheckConstraint("risk_score >= 0 AND risk_score <= 100", name="ck_dead_stock_risk_score_range"),
        CheckConstraint("confidence_score >= 0 AND confidence_score <= 100", name="ck_dead_stock_confidence_range"),
        Index("ix_dead_stock_seller_classification", "seller_id", "classification"),
        Index("ix_dead_stock_seller_risk_level", "seller_id", "risk_level"),
        Index("ix_dead_stock_product_as_of_date", "product_id", "as_of_date"),
        Index("ix_dead_stock_visibility_status", "visibility_status"),
        Index("ix_dead_stock_data_status", "data_status"),
        Index("ix_dead_stock_assessed_at", "assessed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    inventory_aging_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("inventory_aging_snapshots.id", ondelete="SET NULL"), nullable=True)
    inventory_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("inventory_history.id", ondelete="SET NULL"), nullable=True)
    sales_velocity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sales_velocity.id", ondelete="SET NULL"), nullable=True)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    classification: Mapped[DeadStockClassification] = mapped_column(SAEnum(DeadStockClassification, name="dead_stock_classification"), nullable=False)
    eligible_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    days_since_last_sale: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_sale_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    inventory_age_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inventory_age_is_estimated: Mapped[bool] = mapped_column(nullable=False, default=False)
    no_sales_state: Mapped[DeadStockNoSalesState] = mapped_column(SAEnum(DeadStockNoSalesState, name="dead_stock_no_sales_state"), nullable=False)
    inventory_age_state: Mapped[DeadStockInventoryAgeState] = mapped_column(SAEnum(DeadStockInventoryAgeState, name="dead_stock_inventory_age_state"), nullable=False)
    visibility_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    visibility_status: Mapped[DeadStockVisibilityStatus] = mapped_column(SAEnum(DeadStockVisibilityStatus, name="dead_stock_visibility_status"), nullable=False)
    risk_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    risk_level: Mapped[DeadStockRiskLevel] = mapped_column(SAEnum(DeadStockRiskLevel, name="dead_stock_risk_level"), nullable=False)
    rule_results: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    triggered_rules: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    data_status: Mapped[DeadStockDataStatus] = mapped_column(SAEnum(DeadStockDataStatus, name="dead_stock_data_status"), nullable=False)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    calculation_version: Mapped[str] = mapped_column(String(20), nullable=False)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship(back_populates="dead_stock_assessments")
    product: Mapped["Product"] = relationship(back_populates="dead_stock_assessments")
    inventory_aging: Mapped["InventoryAgingSnapshot | None"] = relationship()
    inventory_snapshot: Mapped["InventoryHistory | None"] = relationship()
    sales_velocity: Mapped["SalesVelocity | None"] = relationship()
    recovery_recommendations: Mapped[list["DeadStockRecoveryRecommendation"]] = relationship(
        back_populates="dead_stock_assessment",
        cascade="all, delete-orphan",
    )

    @property
    def component_scores(self) -> dict[str, Any]:
        return self.rule_results.get("risk_component_scores", {})

    @property
    def explanation(self) -> str:
        return self.rule_results.get("risk_explanation", "")

    @property
    def formula_version(self) -> str:
        return self.calculation_version
