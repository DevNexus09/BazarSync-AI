from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.dead_stock_assessment import DeadStockAssessment
from app.models.dead_stock_capital_recovery import DeadStockCapitalRecoveryEstimate
from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryRecommendation
from app.models.demand_elasticity_estimate import DemandElasticityEstimate
from app.models.product import Product


class DeadStockCapitalRecoveryRepository:
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

    def latest_recovery_recommendation(self, *, seller_id: UUID, product_id: UUID) -> DeadStockRecoveryRecommendation | None:
        return self._db.execute(
            select(DeadStockRecoveryRecommendation)
            .where(DeadStockRecoveryRecommendation.seller_id == seller_id, DeadStockRecoveryRecommendation.product_id == product_id)
            .order_by(DeadStockRecoveryRecommendation.generated_at.desc(), DeadStockRecoveryRecommendation.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def latest_demand_estimate(self, *, seller_id: UUID, product_id: UUID) -> DemandElasticityEstimate | None:
        return self._db.execute(
            select(DemandElasticityEstimate)
            .where(DemandElasticityEstimate.seller_id == seller_id, DemandElasticityEstimate.product_id == product_id)
            .order_by(DemandElasticityEstimate.calculated_at.desc(), DemandElasticityEstimate.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def promotion_history_for_product(self, *, seller_id: UUID, product_id: UUID) -> list[dict]:
        del seller_id, product_id
        return []

    def category_promotion_history(self, *, seller_id: UUID, category: str | None) -> list[dict]:
        del seller_id, category
        return []

    def add(self, estimate: DeadStockCapitalRecoveryEstimate) -> DeadStockCapitalRecoveryEstimate:
        existing = self.get_for_recommendation(
            recovery_recommendation_id=estimate.recovery_recommendation_id,
            calculation_version=estimate.calculation_version,
        )
        if existing:
            return existing
        self._db.add(estimate)
        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            existing = self.get_for_recommendation(
                recovery_recommendation_id=estimate.recovery_recommendation_id,
                calculation_version=estimate.calculation_version,
            )
            if existing:
                return existing
            raise
        self._db.refresh(estimate)
        return estimate

    def get_for_recommendation(
        self,
        *,
        recovery_recommendation_id: UUID | None,
        calculation_version: str,
    ) -> DeadStockCapitalRecoveryEstimate | None:
        if recovery_recommendation_id is None:
            return None
        return self._db.execute(
            select(DeadStockCapitalRecoveryEstimate).where(
                DeadStockCapitalRecoveryEstimate.recovery_recommendation_id == recovery_recommendation_id,
                DeadStockCapitalRecoveryEstimate.calculation_version == calculation_version,
            )
        ).scalar_one_or_none()

    def latest_estimate(self, *, seller_id: UUID, product_id: UUID) -> DeadStockCapitalRecoveryEstimate | None:
        return self._db.execute(
            select(DeadStockCapitalRecoveryEstimate)
            .where(DeadStockCapitalRecoveryEstimate.seller_id == seller_id, DeadStockCapitalRecoveryEstimate.product_id == product_id)
            .order_by(DeadStockCapitalRecoveryEstimate.calculated_at.desc(), DeadStockCapitalRecoveryEstimate.id.desc())
            .limit(1)
        ).scalar_one_or_none()
