from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.models.inventory_history import InventoryHistory
from app.models.inventory_risk import InventoryRiskAssessment, InventoryRiskDataStatus, InventoryRiskLevel
from app.models.product import Product
from app.models.reorder_recommendation import ReorderRecommendation, ReorderRecommendationAction
from app.models.sales_velocity import SalesVelocity
from app.models.stockout_prediction import StockoutPrediction, StockoutPredictionStatus


class InventoryIntelligenceRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def product_exists(self, *, seller_id: UUID, product_id: UUID) -> bool:
        return self._db.execute(
            select(Product.id).where(Product.seller_id == seller_id, Product.id == product_id)
        ).scalar_one_or_none() is not None

    def summary(self, *, seller_id: UUID) -> dict:
        latest_risks = _latest_ids(
            InventoryRiskAssessment,
            InventoryRiskAssessment.as_of_date,
            InventoryRiskAssessment.assessed_at,
        )
        risk_rows = (
            select(InventoryRiskAssessment)
            .join(
                latest_risks,
                and_(InventoryRiskAssessment.id == latest_risks.c.id, latest_risks.c.row_number == 1),
            )
            .where(InventoryRiskAssessment.seller_id == seller_id)
            .subquery()
        )
        latest_reorders = _latest_ids(
            ReorderRecommendation,
            ReorderRecommendation.as_of_date,
            ReorderRecommendation.generated_at,
        )
        reorder_rows = (
            select(ReorderRecommendation)
            .join(
                latest_reorders,
                and_(ReorderRecommendation.id == latest_reorders.c.id, latest_reorders.c.row_number == 1),
            )
            .where(ReorderRecommendation.seller_id == seller_id)
            .subquery()
        )
        latest_predictions = _latest_ids(
            StockoutPrediction,
            StockoutPrediction.as_of_date,
            StockoutPrediction.calculated_at,
        )
        prediction_rows = (
            select(StockoutPrediction)
            .join(
                latest_predictions,
                and_(StockoutPrediction.id == latest_predictions.c.id, latest_predictions.c.row_number == 1),
            )
            .where(StockoutPrediction.seller_id == seller_id)
            .subquery()
        )
        total_products = self._db.scalar(select(func.count()).select_from(Product).where(Product.seller_id == seller_id)) or 0
        risk_counts = self._db.execute(
            select(
                func.count().filter(risk_rows.c.risk_level == InventoryRiskLevel.LOW).label("low"),
                func.count().filter(risk_rows.c.risk_level == InventoryRiskLevel.MEDIUM).label("medium"),
                func.count().filter(risk_rows.c.risk_level == InventoryRiskLevel.HIGH).label("high"),
                func.count().filter(risk_rows.c.risk_level == InventoryRiskLevel.CRITICAL).label("critical"),
                func.count().filter(risk_rows.c.data_status == InventoryRiskDataStatus.INSUFFICIENT).label("insufficient"),
                func.max(risk_rows.c.assessed_at).label("last_risk_at"),
            )
        ).one()
        reorder_required = self._db.scalar(
            select(func.count())
            .select_from(reorder_rows)
            .where(reorder_rows.c.action == ReorderRecommendationAction.REORDER)
        ) or 0
        out_of_stock = self._db.scalar(
            select(func.count())
            .select_from(prediction_rows)
            .where(prediction_rows.c.prediction_status == StockoutPredictionStatus.ALREADY_OUT_OF_STOCK)
        ) or 0
        return {
            "total_active_products": total_products,
            "low_risk_products": risk_counts.low or 0,
            "medium_risk_products": risk_counts.medium or 0,
            "high_risk_products": risk_counts.high or 0,
            "critical_risk_products": risk_counts.critical or 0,
            "insufficient_data_products": risk_counts.insufficient or 0,
            "products_requiring_reorder": reorder_required,
            "products_already_out_of_stock": out_of_stock,
            "last_calculation_time": risk_counts.last_risk_at,
        }

    def latest_product_bundle(self, *, seller_id: UUID, product_id: UUID) -> dict | None:
        product = self._db.execute(
            select(Product).where(Product.seller_id == seller_id, Product.id == product_id)
        ).scalar_one_or_none()
        if not product:
            return None
        return {
            "product": product,
            "inventory": self._latest(InventoryHistory, seller_id=seller_id, product_id=product_id, date_column=InventoryHistory.snapshot_date),
            "velocity": self._latest(SalesVelocity, seller_id=seller_id, product_id=product_id, date_column=SalesVelocity.as_of_date),
            "prediction": self._latest(StockoutPrediction, seller_id=seller_id, product_id=product_id, date_column=StockoutPrediction.as_of_date),
            "reorder": self._latest(ReorderRecommendation, seller_id=seller_id, product_id=product_id, date_column=ReorderRecommendation.as_of_date),
            "risk": self._latest(InventoryRiskAssessment, seller_id=seller_id, product_id=product_id, date_column=InventoryRiskAssessment.as_of_date),
        }

    def reorder_list(
        self,
        *,
        seller_id: UUID,
        risk_level: InventoryRiskLevel | None,
        deadline_from: date | None,
        deadline_to: date | None,
        product_id: UUID | None,
        category: str | None,
        sort: str,
        limit: int,
        offset: int,
    ) -> tuple[list[dict], int]:
        rows, total = self._list_rows(
            seller_id=seller_id,
            risk_level=risk_level,
            insufficient_data=None,
            product_id=product_id,
            category=category,
            reorder_required=True,
            deadline_from=deadline_from,
            deadline_to=deadline_to,
            sort=sort,
            limit=limit,
            offset=offset,
        )
        return rows, total

    def risks(
        self,
        *,
        seller_id: UUID,
        risk_level: InventoryRiskLevel | None,
        insufficient_data: bool | None,
        product_id: UUID | None,
        category: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict], int]:
        return self._list_rows(
            seller_id=seller_id,
            risk_level=risk_level,
            insufficient_data=insufficient_data,
            product_id=product_id,
            category=category,
            reorder_required=None,
            deadline_from=None,
            deadline_to=None,
            sort="risk",
            limit=limit,
            offset=offset,
        )

    def latest_risks_for_scope(
        self,
        *,
        seller_id: UUID | None,
        product_id: UUID | None,
        as_of_date: date | None,
    ) -> list[InventoryRiskAssessment]:
        latest = _latest_ids(
            InventoryRiskAssessment,
            InventoryRiskAssessment.as_of_date,
            InventoryRiskAssessment.assessed_at,
            as_of_date=as_of_date,
        )
        statement = (
            select(InventoryRiskAssessment)
            .join(
                latest,
                and_(InventoryRiskAssessment.id == latest.c.id, latest.c.row_number == 1),
            )
        )
        if seller_id:
            statement = statement.where(InventoryRiskAssessment.seller_id == seller_id)
        if product_id:
            statement = statement.where(InventoryRiskAssessment.product_id == product_id)
        return list(self._db.execute(statement).scalars().all())

    def _list_rows(
        self,
        *,
        seller_id: UUID,
        risk_level: InventoryRiskLevel | None,
        insufficient_data: bool | None,
        product_id: UUID | None,
        category: str | None,
        reorder_required: bool | None,
        deadline_from: date | None,
        deadline_to: date | None,
        sort: str,
        limit: int,
        offset: int,
    ) -> tuple[list[dict], int]:
        latest_risks = _latest_ids(
            InventoryRiskAssessment,
            InventoryRiskAssessment.as_of_date,
            InventoryRiskAssessment.assessed_at,
        )
        statement = (
            select(Product, InventoryRiskAssessment, ReorderRecommendation, StockoutPrediction)
            .join(InventoryRiskAssessment, Product.id == InventoryRiskAssessment.product_id)
            .join(
                latest_risks,
                and_(InventoryRiskAssessment.id == latest_risks.c.id, latest_risks.c.row_number == 1),
            )
            .outerjoin(ReorderRecommendation, InventoryRiskAssessment.reorder_recommendation_id == ReorderRecommendation.id)
            .outerjoin(StockoutPrediction, InventoryRiskAssessment.stockout_prediction_id == StockoutPrediction.id)
            .where(Product.seller_id == seller_id, InventoryRiskAssessment.seller_id == seller_id)
        )
        if risk_level:
            statement = statement.where(InventoryRiskAssessment.risk_level == risk_level)
        if insufficient_data is not None:
            condition = InventoryRiskAssessment.data_status == InventoryRiskDataStatus.INSUFFICIENT
            statement = statement.where(condition if insufficient_data else ~condition)
        if product_id:
            statement = statement.where(Product.id == product_id)
        if category:
            statement = statement.where(Product.category == category)
        if reorder_required is not None:
            condition = ReorderRecommendation.action == ReorderRecommendationAction.REORDER
            statement = statement.where(condition if reorder_required else ~condition)
        if deadline_from:
            statement = statement.where(ReorderRecommendation.reorder_deadline >= deadline_from)
        if deadline_to:
            statement = statement.where(ReorderRecommendation.reorder_deadline <= deadline_to)
        total = self._db.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
        statement = statement.order_by(*_ordering(sort)).limit(limit).offset(offset)
        rows = self._db.execute(statement).all()
        return [
            {"product": product, "risk": risk, "reorder": reorder, "prediction": prediction}
            for product, risk, reorder, prediction in rows
        ], total

    def _latest(self, model, *, seller_id: UUID, product_id: UUID, date_column):
        statement = (
            select(model)
            .where(model.seller_id == seller_id, model.product_id == product_id)
            .order_by(date_column.desc(), getattr(model, "created_at", date_column).desc())
            .limit(1)
        )
        return self._db.execute(statement).scalar_one_or_none()


def _latest_ids(model, date_column, timestamp_column, *, as_of_date: date | None = None):
    row_number = func.row_number().over(
        partition_by=model.product_id,
        order_by=(date_column.desc(), timestamp_column.desc(), model.id.desc()),
    ).label("row_number")
    statement = select(model.id.label("id"), row_number)
    if as_of_date:
        statement = statement.where(date_column <= as_of_date)
    return statement.subquery()


def _ordering(sort: str):
    risk_sort = case(
        (InventoryRiskAssessment.risk_level == InventoryRiskLevel.CRITICAL, 4),
        (InventoryRiskAssessment.risk_level == InventoryRiskLevel.HIGH, 3),
        (InventoryRiskAssessment.risk_level == InventoryRiskLevel.MEDIUM, 2),
        (InventoryRiskAssessment.risk_level == InventoryRiskLevel.LOW, 1),
        else_=0,
    )
    if sort == "deadline":
        return (ReorderRecommendation.reorder_deadline.asc().nullslast(), risk_sort.desc(), Product.title.asc())
    if sort == "recommended_quantity":
        return (ReorderRecommendation.recommended_quantity.desc().nullslast(), risk_sort.desc(), Product.title.asc())
    return (risk_sort.desc(), ReorderRecommendation.reorder_deadline.asc().nullslast(), Product.title.asc())
