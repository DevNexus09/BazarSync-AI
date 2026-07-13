from __future__ import annotations

from datetime import datetime
from enum import Enum
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum as SAEnum, ForeignKey, ForeignKeyConstraint, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.competitor import Competitor
    from app.models.demand_elasticity_estimate import DemandElasticityEstimate
    from app.models.dead_stock_assessment import DeadStockAssessment
    from app.models.dead_stock_capital_recovery import DeadStockCapitalRecoveryEstimate
    from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryRecommendation
    from app.models.dynamic_pricing_recommendation import DynamicPricingRecommendation
    from app.models.competitor_event import CompetitorEvent
    from app.models.competitor_ranking import CompetitorRanking
    from app.models.market_opportunity import MarketOpportunity
    from app.models.marketplace_fee_policy import MarketplaceFeePolicy
    from app.models.competitor_snapshot import CompetitorSnapshot
    from app.models.pricing_policy import PricingPolicy
    from app.models.product_visibility_metric import ProductVisibilityMetric
    from app.models.pricing_analytics_snapshot import PricingAnalyticsSnapshot
    from app.models.product_price_history import ProductPriceHistory
    from app.models.promotion import PromotionPlan, PromotionResult
    from app.models.inventory_history import InventoryHistory
    from app.models.inventory_stock_in import InventoryStockIn
    from app.models.inventory_aging import InventoryAgingSnapshot
    from app.models.inventory_risk import InventoryRiskAssessment
    from app.models.scrape_run import ScrapeRun
    from app.models.recommendation import Recommendation
    from app.models.reorder_recommendation import ReorderRecommendation
    from app.models.sales_record import SalesRecord
    from app.models.sales_data_coverage import SalesDataCoverage
    from app.models.sales_velocity import SalesVelocity
    from app.models.stockout_prediction import StockoutPrediction
    from app.models.alert import Alert
    from app.models.seller import Seller
    from app.models.telegram_inventory_alert import TelegramInventoryAlert
    from app.models.rag_memory import RagMemoryChunk, RagMemoryDocument


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DRAFT = "DRAFT"
    ARCHIVED = "ARCHIVED"
    DISCONTINUED = "DISCONTINUED"


class ProductMarketplaceListingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DRAFT = "DRAFT"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    ARCHIVED = "ARCHIVED"
    UNKNOWN = "UNKNOWN"


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        Index("ix_products_category", "category"),
        Index("ix_products_status", "status"),
        Index("ix_products_searchable_text", "searchable_text"),
        UniqueConstraint("seller_id", "sku", name="uq_products_seller_sku"),
        UniqueConstraint("id", "seller_id", name="uq_products_id_seller_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        index=True,
        default=uuid.uuid4,
    )
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sellers.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[ProductStatus] = mapped_column(
        SAEnum(ProductStatus, name="product_status"),
        nullable=False,
        default=ProductStatus.ACTIVE,
        server_default=ProductStatus.ACTIVE.value,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    specifications: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    searchable_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    selling_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    stock_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    supplier_lead_time: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_margin: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    seller: Mapped["Seller"] = relationship(back_populates="products")
    scrape_runs: Mapped[list["ScrapeRun"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    competitors: Mapped[list["Competitor"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    competitor_snapshots: Mapped[list["CompetitorSnapshot"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    recommendations: Mapped[list["Recommendation"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    competitor_events: Mapped[list["CompetitorEvent"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    competitor_rankings: Mapped[list["CompetitorRanking"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    market_opportunities: Mapped[list["MarketOpportunity"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    inventory_history: Mapped[list["InventoryHistory"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    inventory_stock_ins: Mapped[list["InventoryStockIn"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    inventory_aging_snapshots: Mapped[list["InventoryAgingSnapshot"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    dead_stock_assessments: Mapped[list["DeadStockAssessment"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    dead_stock_recovery_recommendations: Mapped[list["DeadStockRecoveryRecommendation"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    dead_stock_capital_recovery_estimates: Mapped[list["DeadStockCapitalRecoveryEstimate"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    sales_records: Mapped[list["SalesRecord"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    sales_data_coverage: Mapped[list["SalesDataCoverage"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    sales_velocity: Mapped[list["SalesVelocity"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    stockout_predictions: Mapped[list["StockoutPrediction"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    reorder_recommendations: Mapped[list["ReorderRecommendation"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    inventory_risk_assessments: Mapped[list["InventoryRiskAssessment"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    telegram_inventory_alerts: Mapped[list["TelegramInventoryAlert"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    pricing_policies: Mapped[list["PricingPolicy"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    visibility_metrics: Mapped[list["ProductVisibilityMetric"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    marketplace_fee_policies: Mapped[list["MarketplaceFeePolicy"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    pricing_analytics_snapshots: Mapped[list["PricingAnalyticsSnapshot"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    demand_elasticity_estimates: Mapped[list["DemandElasticityEstimate"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    dynamic_pricing_recommendations: Mapped[list["DynamicPricingRecommendation"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    rag_memory_documents: Mapped[list["RagMemoryDocument"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    rag_memory_chunks: Mapped[list["RagMemoryChunk"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    marketplace_listings: Mapped[list["ProductMarketplaceListing"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        overlaps="seller,product_marketplace_listings",
    )
    price_history: Mapped[list["ProductPriceHistory"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    promotion_plans: Mapped[list["PromotionPlan"]] = relationship(
        back_populates="product",
    )
    promotion_results: Mapped[list["PromotionResult"]] = relationship(
        back_populates="product",
    )

    @property
    def pricing_warning(self) -> str | None:
        if self.selling_price < self.cost_price:
            return "Selling price is below cost price."
        return None


class ProductMarketplaceListing(Base):
    __tablename__ = "product_marketplace_listings"
    __table_args__ = (
        CheckConstraint("selling_price IS NULL OR selling_price >= 0", name="ck_product_marketplace_listings_selling_price_nonnegative"),
        CheckConstraint("previous_selling_price IS NULL OR previous_selling_price >= 0", name="ck_product_marketplace_listings_previous_price_nonnegative"),
        CheckConstraint("selling_price IS NULL OR currency IS NOT NULL", name="ck_product_marketplace_listings_currency_when_price"),
        UniqueConstraint("seller_id", "marketplace", "marketplace_listing_id", name="uq_product_marketplace_listings_seller_marketplace_external_id"),
        ForeignKeyConstraint(["product_id", "seller_id"], ["products.id", "products.seller_id"], ondelete="CASCADE", name="fk_product_marketplace_listings_product_seller"),
        Index("ix_product_marketplace_listings_seller_id", "seller_id"),
        Index("ix_product_marketplace_listings_product_id", "product_id"),
        Index("ix_product_marketplace_listings_marketplace", "marketplace"),
        Index("ix_product_marketplace_listings_listing_status", "listing_status"),
        Index("ix_product_marketplace_listings_seller_marketplace_status", "seller_id", "marketplace", "listing_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sellers.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    marketplace: Mapped[str] = mapped_column(String(120), nullable=False)
    marketplace_listing_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    listing_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    listing_status: Mapped[ProductMarketplaceListingStatus] = mapped_column(
        SAEnum(ProductMarketplaceListingStatus, name="product_marketplace_listing_status"),
        nullable=False,
        default=ProductMarketplaceListingStatus.UNKNOWN,
        server_default=ProductMarketplaceListingStatus.UNKNOWN.value,
    )
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    selling_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    previous_selling_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    category_on_marketplace: Mapped[str | None] = mapped_column(String(160), nullable=True)
    title_on_marketplace: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    seller: Mapped["Seller"] = relationship(back_populates="product_marketplace_listings", overlaps="marketplace_listings,product")
    product: Mapped["Product"] = relationship(back_populates="marketplace_listings", overlaps="seller,product_marketplace_listings")
    price_history: Mapped[list["ProductPriceHistory"]] = relationship(back_populates="listing")
