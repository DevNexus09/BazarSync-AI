"""Read-only, seller-scoped pricing overview: latest analytics snapshot and latest
dynamic pricing recommendation per product, in one call instead of N per product."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dynamic_pricing_recommendation import (
    DynamicPricingAction,
    DynamicPricingRecommendation,
    DynamicPricingRecommendationStatus,
)
from app.models.pricing_policy import PricingPolicy
from app.models.pricing_analytics_snapshot import PricingAnalyticsDataStatus, PricingAnalyticsSnapshot
from app.models.product import Product, ProductStatus
from app.schemas.pricing_overview import (
    MarketPosition,
    PricingOverviewRecommendation,
    PricingOverviewResponse,
    PricingOverviewRow,
    PricingOverviewSummary,
)

# Within ±2% of the competitor median counts as "at market".
POSITION_TOLERANCE_RATE = Decimal("0.02")
MARKETPLACE = "Daraz Bangladesh"
HIDDEN_PRODUCT_STATUSES = (ProductStatus.ARCHIVED, ProductStatus.DISCONTINUED)
RATE_QUANT = Decimal("0.0001")


@dataclass(frozen=True)
class ProductRow:
    id: UUID
    title: str
    sku: str | None
    category: str | None
    selling_price: Decimal


@dataclass(frozen=True)
class SnapshotRow:
    id: UUID
    product_id: UUID
    competitor_median_price: Decimal | None
    competitor_count: int
    minimum_safe_price: Decimal | None
    data_status: PricingAnalyticsDataStatus
    calculated_at: datetime


@dataclass(frozen=True)
class RecommendationRow:
    id: UUID
    product_id: UUID
    action: DynamicPricingAction
    recommended_price: Decimal
    recommendation_status: DynamicPricingRecommendationStatus
    confidence_score: Decimal
    profit_impact: Decimal | None
    generated_at: datetime
    expires_at: datetime | None


class PricingOverviewRepositoryProtocol(Protocol):
    def products(self, *, seller_id: UUID) -> list[ProductRow]: ...

    def latest_snapshots(self, *, seller_id: UUID) -> list[SnapshotRow]: ...

    def latest_recommendations(self, *, seller_id: UUID) -> list[RecommendationRow]: ...

    def products_with_pricing_policy(self, *, seller_id: UUID, as_of: datetime) -> set[UUID]: ...


class PricingOverviewRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def products(self, *, seller_id: UUID) -> list[ProductRow]:
        rows = self._db.execute(
            select(Product.id, Product.title, Product.sku, Product.category, Product.selling_price)
            .where(Product.seller_id == seller_id, Product.status.not_in(HIDDEN_PRODUCT_STATUSES))
            .order_by(Product.title.asc(), Product.id.asc())
        ).all()
        return [ProductRow(row.id, row.title, row.sku, row.category, Decimal(row.selling_price)) for row in rows]

    def latest_snapshots(self, *, seller_id: UUID) -> list[SnapshotRow]:
        model = PricingAnalyticsSnapshot
        rows = self._db.execute(
            select(
                model.id,
                model.product_id,
                model.competitor_median_price,
                model.competitor_count,
                model.minimum_safe_price,
                model.data_status,
                model.calculated_at,
            )
            .where(model.seller_id == seller_id)
            .distinct(model.product_id)
            .order_by(model.product_id, model.calculated_at.desc(), model.created_at.desc())
        ).all()
        return [SnapshotRow(*row) for row in rows]

    def latest_recommendations(self, *, seller_id: UUID) -> list[RecommendationRow]:
        model = DynamicPricingRecommendation
        rows = self._db.execute(
            select(
                model.id,
                model.product_id,
                model.action,
                model.recommended_price,
                model.recommendation_status,
                model.confidence_score,
                model.profit_impact,
                model.generated_at,
                model.expires_at,
            )
            .where(model.seller_id == seller_id)
            .distinct(model.product_id)
            .order_by(model.product_id, model.generated_at.desc(), model.created_at.desc())
        ).all()
        return [RecommendationRow(*row) for row in rows]


    def products_with_pricing_policy(self, *, seller_id: UUID, as_of: datetime) -> set[UUID]:
        # Same rule as PricingPolicyService._active_policy; without one the default policy applies.
        rows = self._db.execute(
            select(PricingPolicy.product_id).where(
                PricingPolicy.seller_id == seller_id,
                PricingPolicy.marketplace == MARKETPLACE,
                PricingPolicy.is_active.is_(True),
                PricingPolicy.effective_from <= as_of,
                PricingPolicy.effective_to.is_(None) | (PricingPolicy.effective_to > as_of),
            )
        ).scalars()
        return set(rows)


class PricingOverviewService:
    def __init__(
        self,
        db: Session | None = None,
        *,
        repository: PricingOverviewRepositoryProtocol | None = None,
    ) -> None:
        if repository is None and db is None:
            raise ValueError("Either db or repository is required.")
        self._repository = repository or PricingOverviewRepository(db)  # type: ignore[arg-type]

    def overview(
        self, *, seller_id: UUID, limit: int, offset: int, now: datetime | None = None
    ) -> PricingOverviewResponse:
        # shortcut: loads every product of the seller to build the summary; fine for catalogues
        # in the low thousands, move counts into SQL if a seller grows past that.
        products = self._repository.products(seller_id=seller_id)
        snapshots = {row.product_id: row for row in self._repository.latest_snapshots(seller_id=seller_id)}
        recommendations = {row.product_id: row for row in self._repository.latest_recommendations(seller_id=seller_id)}
        timestamp = now or datetime.now(timezone.utc)
        with_policy = self._repository.products_with_pricing_policy(seller_id=seller_id, as_of=timestamp)
        rows = [
            build_row(product, snapshots.get(product.id), recommendations.get(product.id), timestamp, product.id in with_policy)
            for product in products
        ]
        return PricingOverviewResponse(
            items=rows[offset : offset + limit],
            total=len(rows),
            limit=limit,
            offset=offset,
            summary=build_summary(rows),
        )


def build_row(
    product: ProductRow,
    snapshot: SnapshotRow | None,
    recommendation: RecommendationRow | None,
    now: datetime,
    has_pricing_policy: bool = False,
) -> PricingOverviewRow:
    median = Decimal(snapshot.competitor_median_price) if snapshot and snapshot.competitor_median_price else None
    rate = ((product.selling_price - median) / median).quantize(RATE_QUANT, rounding=ROUND_HALF_UP) if median else None
    minimum_safe = Decimal(snapshot.minimum_safe_price) if snapshot and snapshot.minimum_safe_price is not None else None
    return PricingOverviewRow(
        product_id=product.id,
        title=product.title,
        sku=product.sku,
        category=product.category,
        current_price=product.selling_price,
        analytics_id=snapshot.id if snapshot else None,
        analytics_calculated_at=snapshot.calculated_at if snapshot else None,
        data_status=snapshot.data_status if snapshot else None,
        market_median_price=median,
        competitor_count=snapshot.competitor_count if snapshot else 0,
        price_vs_median_rate=rate,
        position=market_position(rate),
        minimum_safe_price=minimum_safe,
        margin_at_risk=minimum_safe is not None and product.selling_price < minimum_safe,
        has_pricing_policy=has_pricing_policy,
        recommendation=_recommendation(recommendation, now) if recommendation else None,
    )


def market_position(rate: Decimal | None) -> MarketPosition:
    if rate is None:
        return MarketPosition.NO_MARKET_DATA
    if rate > POSITION_TOLERANCE_RATE:
        return MarketPosition.ABOVE_MARKET
    if rate < -POSITION_TOLERANCE_RATE:
        return MarketPosition.BELOW_MARKET
    return MarketPosition.AT_MARKET


def _recommendation(row: RecommendationRow, now: datetime) -> PricingOverviewRecommendation:
    expired = row.expires_at is not None and row.expires_at <= now
    return PricingOverviewRecommendation(
        id=row.id,
        action=row.action,
        recommended_price=row.recommended_price,
        recommendation_status=row.recommendation_status,
        confidence_score=row.confidence_score,
        profit_impact=row.profit_impact,
        generated_at=row.generated_at,
        expires_at=row.expires_at,
        is_actionable=(
            row.recommendation_status == DynamicPricingRecommendationStatus.OPEN
            and row.action != DynamicPricingAction.HOLD
            and not expired
        ),
    )


def build_summary(rows: list[PricingOverviewRow]) -> PricingOverviewSummary:
    calculated = [row.analytics_calculated_at for row in rows if row.analytics_calculated_at]
    return PricingOverviewSummary(
        product_count=len(rows),
        priced_above_market=sum(row.position == MarketPosition.ABOVE_MARKET for row in rows),
        priced_below_market=sum(row.position == MarketPosition.BELOW_MARKET for row in rows),
        margin_at_risk=sum(row.margin_at_risk for row in rows),
        recommendations_waiting=sum(bool(row.recommendation and row.recommendation.is_actionable) for row in rows),
        without_analytics=sum(row.analytics_id is None for row in rows),
        products_with_pricing_policy=sum(row.has_pricing_policy for row in rows),
        products_with_competitor_data=sum(row.competitor_count > 0 for row in rows),
        last_calculated_at=max(calculated) if calculated else None,
        position_tolerance_rate=POSITION_TOLERANCE_RATE,
    )
