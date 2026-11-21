from __future__ import annotations

from datetime import date, datetime, timezone
from collections.abc import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.dead_stock_assessment import DeadStockAssessment
from app.models.dead_stock_recovery_recommendation import (
    DeadStockRecoveryRecommendation,
    DeadStockRecoveryRecommendationStatus,
)
from app.models.inventory_aging import InventoryAgingSnapshot
from app.models.product import Product
from app.models.product_visibility_metric import ProductVisibilityMetric
from app.models.promotion import PromotionPlan, PromotionResult
from app.models.sales_velocity import SalesVelocity


class DeadStockRecoveryRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def product(self, *, seller_id: UUID, product_id: UUID) -> Product | None:
        return self._db.execute(
            select(Product).where(Product.seller_id == seller_id, Product.id == product_id)
        ).scalar_one_or_none()

    def latest_assessment(self, *, seller_id: UUID, product_id: UUID) -> DeadStockAssessment | None:
        return self._db.execute(
            select(DeadStockAssessment)
            .where(DeadStockAssessment.seller_id == seller_id, DeadStockAssessment.product_id == product_id)
            .order_by(DeadStockAssessment.as_of_date.desc(), DeadStockAssessment.assessed_at.desc(), DeadStockAssessment.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def latest_aging(self, *, seller_id: UUID, product_id: UUID, as_of_date: date) -> InventoryAgingSnapshot | None:
        return self._db.execute(
            select(InventoryAgingSnapshot)
            .where(
                InventoryAgingSnapshot.seller_id == seller_id,
                InventoryAgingSnapshot.product_id == product_id,
                InventoryAgingSnapshot.as_of_date <= as_of_date,
            )
            .order_by(InventoryAgingSnapshot.as_of_date.desc(), InventoryAgingSnapshot.calculated_at.desc(), InventoryAgingSnapshot.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def latest_velocity(self, *, seller_id: UUID, product_id: UUID, as_of_date: date) -> SalesVelocity | None:
        return self._db.execute(
            select(SalesVelocity)
            .where(
                SalesVelocity.seller_id == seller_id,
                SalesVelocity.product_id == product_id,
                SalesVelocity.as_of_date <= as_of_date,
            )
            .order_by(SalesVelocity.as_of_date.desc(), SalesVelocity.calculated_at.desc(), SalesVelocity.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def companion_products(self, *, seller_id: UUID, product: Product, limit: int = 5) -> list[Product]:
        if not product.category:
            return []
        return list(self._db.execute(
            select(Product)
            .where(
                Product.seller_id == seller_id,
                Product.id != product.id,
                Product.category == product.category,
                Product.stock_quantity > 0,
            )
            .order_by(Product.created_at.desc(), Product.id.desc())
            .limit(limit)
        ).scalars())

    def visibility_for_product(self, *, seller_id: UUID, product_id: UUID, as_of_date: date) -> dict | None:
        from app.services.product_visibility_service import ProductVisibilityService

        row = self._db.execute(
            select(ProductVisibilityMetric)
            .where(
                ProductVisibilityMetric.seller_id == seller_id,
                ProductVisibilityMetric.product_id == product_id,
                ProductVisibilityMetric.metric_date <= as_of_date,
            )
            .order_by(ProductVisibilityMetric.metric_date.desc(), ProductVisibilityMetric.created_at.desc(), ProductVisibilityMetric.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        return ProductVisibilityService.evidence(row) if row else None

    def promotion_history_for_product(self, *, seller_id: UUID, product_id: UUID) -> list[dict]:
        del seller_id, product_id
        return []

    def bundle_compatibility_for_product(self, *, seller_id: UUID, product_id: UUID) -> list[dict]:
        del seller_id, product_id
        return []

    def promotion_observations(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        since: datetime,
        at: datetime,
    ) -> list[tuple[PromotionResult, PromotionPlan | None]]:
        statement = (
            select(PromotionResult, PromotionPlan)
            .outerjoin(
                PromotionPlan,
                (PromotionPlan.id == PromotionResult.promotion_plan_id)
                & (PromotionPlan.seller_id == seller_id)
                & (PromotionPlan.product_id == product_id),
            )
            .where(
                PromotionResult.seller_id == seller_id,
                PromotionResult.product_id == product_id,
                PromotionResult.started_at >= since,
                PromotionResult.created_at <= at,
            )
            .order_by(PromotionResult.started_at.desc(), PromotionResult.id.desc())
            .limit(50)
        )
        return [(result, plan) for result, plan in self._db.execute(statement)]

    def add_idempotent(
        self,
        recommendation: DeadStockRecoveryRecommendation,
        *,
        before_commit: Callable[[DeadStockRecoveryRecommendation], None] | None = None,
    ) -> tuple[DeadStockRecoveryRecommendation, bool]:
        existing = self.get_for_assessment(
            seller_id=recommendation.seller_id,
            assessment_id=recommendation.dead_stock_assessment_id,
            calculation_version=recommendation.calculation_version,
        )
        if existing:
            return existing, False
        self._db.add(recommendation)
        try:
            if before_commit is not None:
                self._db.flush()
                before_commit(recommendation)
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            existing = self.get_for_assessment(
                seller_id=recommendation.seller_id,
                assessment_id=recommendation.dead_stock_assessment_id,
                calculation_version=recommendation.calculation_version,
            )
            if existing:
                return existing, False
            raise
        except Exception:
            self._db.rollback()
            raise
        self._db.refresh(recommendation)
        return recommendation, True

    def latest_recommendation(self, *, seller_id: UUID, product_id: UUID) -> DeadStockRecoveryRecommendation | None:
        return self._db.execute(
            select(DeadStockRecoveryRecommendation)
            .where(DeadStockRecoveryRecommendation.seller_id == seller_id, DeadStockRecoveryRecommendation.product_id == product_id)
            .order_by(DeadStockRecoveryRecommendation.generated_at.desc(), DeadStockRecoveryRecommendation.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def list_recommendations(self, *, seller_id: UUID, product_id: UUID, limit: int, offset: int) -> tuple[list[DeadStockRecoveryRecommendation], int]:
        statement = select(DeadStockRecoveryRecommendation).where(
            DeadStockRecoveryRecommendation.seller_id == seller_id,
            DeadStockRecoveryRecommendation.product_id == product_id,
        )
        total = len(self._db.execute(statement).scalars().all())
        rows = self._db.execute(
            statement.order_by(DeadStockRecoveryRecommendation.generated_at.desc(), DeadStockRecoveryRecommendation.id.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
        return list(rows), total

    def get(self, *, seller_id: UUID, recommendation_id: UUID) -> DeadStockRecoveryRecommendation | None:
        return self._db.execute(
            select(DeadStockRecoveryRecommendation).where(
                DeadStockRecoveryRecommendation.seller_id == seller_id,
                DeadStockRecoveryRecommendation.id == recommendation_id,
            )
        ).scalar_one_or_none()

    def get_for_assessment(self, *, seller_id: UUID, assessment_id: UUID, calculation_version: str) -> DeadStockRecoveryRecommendation | None:
        return self._db.execute(
            select(DeadStockRecoveryRecommendation).where(
                DeadStockRecoveryRecommendation.seller_id == seller_id,
                DeadStockRecoveryRecommendation.dead_stock_assessment_id == assessment_id,
                DeadStockRecoveryRecommendation.calculation_version == calculation_version,
            )
        ).scalar_one_or_none()

    def save(self, recommendation: DeadStockRecoveryRecommendation) -> DeadStockRecoveryRecommendation:
        recommendation.updated_at = datetime.now(timezone.utc)
        self._db.commit()
        self._db.refresh(recommendation)
        return recommendation

    def supersede_open_for_product(self, *, seller_id: UUID, product_id: UUID, except_id: UUID | None = None) -> None:
        rows = self._db.execute(
            select(DeadStockRecoveryRecommendation).where(
                DeadStockRecoveryRecommendation.seller_id == seller_id,
                DeadStockRecoveryRecommendation.product_id == product_id,
                DeadStockRecoveryRecommendation.recommendation_status == DeadStockRecoveryRecommendationStatus.OPEN,
            )
        ).scalars().all()
        for row in rows:
            if except_id is None or row.id != except_id:
                row.recommendation_status = DeadStockRecoveryRecommendationStatus.SUPERSEDED
