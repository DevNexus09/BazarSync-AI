from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.dead_stock_assessment import DeadStockAssessment, DeadStockClassification, DeadStockDataStatus, DeadStockRiskLevel
from app.models.dead_stock_capital_recovery import DeadStockCapitalRecoveryEstimate
from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryAction, DeadStockRecoveryRecommendation
from app.models.inventory_aging import InventoryAgingSnapshot
from app.models.product import Product
from app.models.sales_velocity import SalesVelocity


class DeadStockDashboardRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def product_exists(self, *, seller_id: UUID, product_id: UUID) -> bool:
        return self._db.execute(select(Product.id).where(Product.seller_id == seller_id, Product.id == product_id)).scalar_one_or_none() is not None

    def rows(
        self,
        *,
        seller_id: UUID,
        product_id: UUID | None = None,
        classification: DeadStockClassification | None = None,
        risk_level: DeadStockRiskLevel | None = None,
        category: str | None = None,
        marketplace: str | None = None,
        min_age_days: int | None = None,
        min_locked_capital=None,
        recommendation_action: DeadStockRecoveryAction | None = None,
        data_status: DeadStockDataStatus | None = None,
        sort: str = "risk",
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        del marketplace
        assessment_ids = _latest_ids(
            DeadStockAssessment,
            DeadStockAssessment.as_of_date,
            DeadStockAssessment.assessed_at,
            seller_id=seller_id,
            product_id=product_id,
        )
        recovery_ids = _latest_ids(
            DeadStockRecoveryRecommendation,
            DeadStockRecoveryRecommendation.generated_at,
            DeadStockRecoveryRecommendation.generated_at,
            seller_id=seller_id,
            product_id=product_id,
        )
        capital_ids = _latest_ids(
            DeadStockCapitalRecoveryEstimate,
            DeadStockCapitalRecoveryEstimate.calculated_at,
            DeadStockCapitalRecoveryEstimate.calculated_at,
            seller_id=seller_id,
            product_id=product_id,
        )
        aging_ids = _latest_ids(
            InventoryAgingSnapshot,
            InventoryAgingSnapshot.as_of_date,
            InventoryAgingSnapshot.calculated_at,
            seller_id=seller_id,
            product_id=product_id,
        )
        velocity_ids = _latest_ids(
            SalesVelocity,
            SalesVelocity.as_of_date,
            SalesVelocity.calculated_at,
            seller_id=seller_id,
            product_id=product_id,
        )

        statement = (
            select(Product, DeadStockAssessment, DeadStockRecoveryRecommendation, DeadStockCapitalRecoveryEstimate, InventoryAgingSnapshot, SalesVelocity)
            .outerjoin(
                DeadStockAssessment,
                and_(DeadStockAssessment.product_id == Product.id, DeadStockAssessment.seller_id == seller_id),
            )
            .outerjoin(assessment_ids, and_(DeadStockAssessment.id == assessment_ids.c.id, assessment_ids.c.row_number == 1))
            .outerjoin(
                DeadStockRecoveryRecommendation,
                and_(DeadStockRecoveryRecommendation.product_id == Product.id, DeadStockRecoveryRecommendation.seller_id == seller_id),
            )
            .outerjoin(recovery_ids, and_(DeadStockRecoveryRecommendation.id == recovery_ids.c.id, recovery_ids.c.row_number == 1))
            .outerjoin(
                DeadStockCapitalRecoveryEstimate,
                and_(DeadStockCapitalRecoveryEstimate.product_id == Product.id, DeadStockCapitalRecoveryEstimate.seller_id == seller_id),
            )
            .outerjoin(capital_ids, and_(DeadStockCapitalRecoveryEstimate.id == capital_ids.c.id, capital_ids.c.row_number == 1))
            .outerjoin(InventoryAgingSnapshot, and_(InventoryAgingSnapshot.product_id == Product.id, InventoryAgingSnapshot.seller_id == seller_id))
            .outerjoin(aging_ids, and_(InventoryAgingSnapshot.id == aging_ids.c.id, aging_ids.c.row_number == 1))
            .outerjoin(SalesVelocity, and_(SalesVelocity.product_id == Product.id, SalesVelocity.seller_id == seller_id))
            .outerjoin(velocity_ids, and_(SalesVelocity.id == velocity_ids.c.id, velocity_ids.c.row_number == 1))
            .where(Product.seller_id == seller_id, Product.stock_quantity > 0)
            .where((DeadStockAssessment.id.is_(None)) | (assessment_ids.c.row_number == 1))
            .where((DeadStockRecoveryRecommendation.id.is_(None)) | (recovery_ids.c.row_number == 1))
            .where((DeadStockCapitalRecoveryEstimate.id.is_(None)) | (capital_ids.c.row_number == 1))
            .where((InventoryAgingSnapshot.id.is_(None)) | (aging_ids.c.row_number == 1))
            .where((SalesVelocity.id.is_(None)) | (velocity_ids.c.row_number == 1))
        )
        if product_id:
            statement = statement.where(Product.id == product_id)
        if classification:
            statement = statement.where(DeadStockAssessment.classification == classification)
        if risk_level:
            statement = statement.where(DeadStockAssessment.risk_level == risk_level)
        if category:
            statement = statement.where(Product.category == category)
        if min_age_days is not None:
            statement = statement.where(DeadStockAssessment.inventory_age_days >= min_age_days)
        if min_locked_capital is not None:
            statement = statement.where(DeadStockCapitalRecoveryEstimate.locked_capital >= min_locked_capital)
        if recommendation_action:
            statement = statement.where(DeadStockRecoveryRecommendation.primary_action == recommendation_action)
        if data_status:
            statement = statement.where(DeadStockAssessment.data_status == data_status)

        total = self._db.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
        statement = statement.order_by(*_ordering(sort))
        if limit is not None:
            statement = statement.limit(limit).offset(offset)
        rows = self._db.execute(statement).all()
        return [
            {
                "product": product,
                "assessment": assessment,
                "recommendation": recommendation,
                "capital": capital,
                "aging": aging,
                "velocity": velocity,
            }
            for product, assessment, recommendation, capital, aging, velocity in rows
        ], total

    def product_bundle(self, *, seller_id: UUID, product_id: UUID) -> dict | None:
        rows, _ = self.rows(seller_id=seller_id, product_id=product_id, limit=1, offset=0)
        return next((row for row in rows if row["product"].id == product_id), None)


def _latest_ids(model, date_column, timestamp_column, *, seller_id: UUID, product_id: UUID | None):
    statement = select(
        model.id.label("id"),
        func.row_number().over(
            partition_by=model.product_id,
            order_by=(date_column.desc(), timestamp_column.desc(), model.id.desc()),
        ).label("row_number"),
    ).where(model.seller_id == seller_id)
    if product_id:
        statement = statement.where(model.product_id == product_id)
    return statement.subquery()


def _ordering(sort: str):
    risk_sort = (
        (DeadStockAssessment.risk_level == DeadStockRiskLevel.CRITICAL).desc(),
        (DeadStockAssessment.risk_level == DeadStockRiskLevel.HIGH).desc(),
        (DeadStockAssessment.risk_level == DeadStockRiskLevel.MEDIUM).desc(),
        (DeadStockAssessment.risk_level == DeadStockRiskLevel.LOW).desc(),
    )
    if sort == "age":
        return (DeadStockAssessment.inventory_age_days.desc().nullslast(), *risk_sort, Product.title.asc())
    if sort == "locked_capital":
        return (DeadStockCapitalRecoveryEstimate.locked_capital.desc().nullslast(), *risk_sort, Product.title.asc())
    if sort == "potential_recovery":
        return (DeadStockCapitalRecoveryEstimate.gross_recovered_cash.desc().nullslast(), *risk_sort, Product.title.asc())
    return (*risk_sort, DeadStockAssessment.risk_score.desc().nullslast(), Product.title.asc())
