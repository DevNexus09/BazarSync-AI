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
    from app.models.inventory_history import InventoryHistory
    from app.models.marketplace_fee_policy import MarketplaceFeePolicy
    from app.models.product import Product
    from app.models.sales_velocity import SalesVelocity
    from app.models.scrape_run import ScrapeRun
    from app.models.seller import Seller


class PricingAnalyticsDataStatus(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    LIMITED = "LIMITED"
    INSUFFICIENT = "INSUFFICIENT"
    STALE = "STALE"


class PricingAnalyticsSnapshot(Base):
    __tablename__ = "pricing_analytics_snapshots"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_pricing_analytics_dedupe_key"),
        CheckConstraint("current_price >= 0", name="ck_pricing_analytics_current_price_nonnegative"),
        CheckConstraint("unit_cost >= 0", name="ck_pricing_analytics_unit_cost_nonnegative"),
        CheckConstraint("percentage_fee_rate >= 0 AND percentage_fee_rate < 1", name="ck_pricing_analytics_fee_rate"),
        CheckConstraint("fixed_fee_amount >= 0", name="ck_pricing_analytics_fixed_fee_nonnegative"),
        CheckConstraint("minimum_safe_price >= 0", name="ck_pricing_analytics_minimum_safe_price_nonnegative"),
        CheckConstraint("competitor_count >= 0", name="ck_pricing_analytics_competitor_count_nonnegative"),
        CheckConstraint("in_stock_competitor_count >= 0", name="ck_pricing_analytics_in_stock_count_nonnegative"),
        CheckConstraint("demand_score IS NULL OR (demand_score >= 0 AND demand_score <= 100)", name="ck_pricing_analytics_demand_score_range"),
        CheckConstraint("confidence_score >= 0 AND confidence_score <= 100", name="ck_pricing_analytics_confidence_range"),
        CheckConstraint("seller_price_percentile IS NULL OR (seller_price_percentile >= 0 AND seller_price_percentile <= 100)", name="ck_pricing_analytics_percentile_range"),
        Index("ix_pricing_analytics_product_calculated", "product_id", "calculated_at"),
        Index("ix_pricing_analytics_seller_calculated", "seller_id", "calculated_at"),
        Index("ix_pricing_analytics_status_calculated", "data_status", "calculated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    competitor_scrape_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("scrape_runs.id", ondelete="SET NULL"), nullable=True)
    inventory_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("inventory_history.id", ondelete="SET NULL"), nullable=True)
    sales_velocity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sales_velocity.id", ondelete="SET NULL"), nullable=True)
    fee_policy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("marketplace_fee_policies.id", ondelete="SET NULL"), nullable=True)
    current_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    percentage_fee_rate: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    fixed_fee_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    current_unit_profit: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    current_margin_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)
    minimum_safe_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    competitor_min_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    competitor_q1_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    competitor_mean_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    competitor_median_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    competitor_q3_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    competitor_max_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    weighted_market_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    seller_price_difference_from_median: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    seller_price_percentile: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    competitor_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    in_stock_competitor_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inventory_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inventory_risk_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    daily_sales_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    recent_net_sales: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_age_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    promotion_state: Mapped[str | None] = mapped_column(String(80), nullable=True)
    demand_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    demand_data_status: Mapped[PricingAnalyticsDataStatus] = mapped_column(SAEnum(PricingAnalyticsDataStatus, name="pricing_analytics_data_status"), nullable=False)
    data_status: Mapped[PricingAnalyticsDataStatus] = mapped_column(SAEnum(PricingAnalyticsDataStatus, name="pricing_analytics_data_status"), nullable=False)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    calculation_version: Mapped[str] = mapped_column(String(40), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship(back_populates="pricing_analytics_snapshots")
    product: Mapped["Product"] = relationship(back_populates="pricing_analytics_snapshots")
    competitor_scrape_run: Mapped["ScrapeRun | None"] = relationship()
    inventory_snapshot: Mapped["InventoryHistory | None"] = relationship()
    sales_velocity: Mapped["SalesVelocity | None"] = relationship()
    fee_policy: Mapped["MarketplaceFeePolicy | None"] = relationship()
