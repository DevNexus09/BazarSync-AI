from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.inventory_history import InventoryHistory
from app.models.product import Product
from app.models.reorder_recommendation import ReorderRecommendation
from app.models.sales_velocity import SalesVelocity
from app.models.seller import Seller
from app.models.stockout_prediction import StockoutPrediction


class ReorderRecommendationRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def iter_product_batches(self, *, batch_size: int, seller_id: UUID | None = None, product_id: UUID | None = None):
        offset = 0
        while True:
            statement = select(Product, Seller).join(Seller, Product.seller_id == Seller.id)
            if seller_id:
                statement = statement.where(Product.seller_id == seller_id)
            if product_id:
                statement = statement.where(Product.id == product_id)
            rows = self._db.execute(statement.order_by(Product.created_at.asc(), Product.id.asc()).limit(batch_size).offset(offset)).all()
            if not rows:
                break
            yield rows
            offset += batch_size

    def latest_inventory_for_products(self, *, seller_id: UUID, product_ids: list[UUID], as_of_date: date) -> dict[UUID, InventoryHistory]:
        return _latest_by_date(
            self._db,
            model=InventoryHistory,
            seller_id=seller_id,
            product_ids=product_ids,
            date_column=InventoryHistory.snapshot_date,
            as_of_date=as_of_date,
        )

    def latest_velocity_for_products(self, *, seller_id: UUID, product_ids: list[UUID], as_of_date: date) -> dict[UUID, SalesVelocity]:
        return _latest_by_date(
            self._db,
            model=SalesVelocity,
            seller_id=seller_id,
            product_ids=product_ids,
            date_column=SalesVelocity.as_of_date,
            as_of_date=as_of_date,
        )

    def latest_stockout_for_products(self, *, seller_id: UUID, product_ids: list[UUID], as_of_date: date) -> dict[UUID, StockoutPrediction]:
        return _latest_by_date(
            self._db,
            model=StockoutPrediction,
            seller_id=seller_id,
            product_ids=product_ids,
            date_column=StockoutPrediction.as_of_date,
            as_of_date=as_of_date,
        )

    def add_idempotent(self, recommendation: ReorderRecommendation) -> tuple[ReorderRecommendation, bool]:
        existing = self.get_for_date(
            seller_id=recommendation.seller_id,
            product_id=recommendation.product_id,
            as_of_date=recommendation.as_of_date,
            calculation_version=recommendation.calculation_version,
        )
        if existing:
            return existing, False
        self._db.add(recommendation)
        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            existing = self.get_for_date(
                seller_id=recommendation.seller_id,
                product_id=recommendation.product_id,
                as_of_date=recommendation.as_of_date,
                calculation_version=recommendation.calculation_version,
            )
            if existing:
                return existing, False
            raise
        self._db.refresh(recommendation)
        return recommendation, True

    def latest(self, *, seller_id: UUID, product_id: UUID, calculation_version: str | None) -> ReorderRecommendation | None:
        statement = (
            select(ReorderRecommendation)
            .join(Product, ReorderRecommendation.product_id == Product.id)
            .where(
                ReorderRecommendation.seller_id == seller_id,
                ReorderRecommendation.product_id == product_id,
                Product.seller_id == seller_id,
            )
        )
        if calculation_version:
            statement = statement.where(ReorderRecommendation.calculation_version == calculation_version)
        return self._db.execute(
            statement.order_by(ReorderRecommendation.as_of_date.desc(), ReorderRecommendation.generated_at.desc(), ReorderRecommendation.id.desc()).limit(1)
        ).scalar_one_or_none()

    def history(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        from_date: date | None,
        to_date: date | None,
        calculation_version: str | None,
        order: str,
        limit: int,
        offset: int,
    ) -> tuple[list[ReorderRecommendation], int]:
        statement = (
            select(ReorderRecommendation)
            .join(Product, ReorderRecommendation.product_id == Product.id)
            .where(
                ReorderRecommendation.seller_id == seller_id,
                ReorderRecommendation.product_id == product_id,
                Product.seller_id == seller_id,
            )
        )
        if from_date:
            statement = statement.where(ReorderRecommendation.as_of_date >= from_date)
        if to_date:
            statement = statement.where(ReorderRecommendation.as_of_date <= to_date)
        if calculation_version:
            statement = statement.where(ReorderRecommendation.calculation_version == calculation_version)
        total = self._db.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
        ordering = ReorderRecommendation.as_of_date.asc() if order == "asc" else ReorderRecommendation.as_of_date.desc()
        rows = self._db.execute(
            statement.order_by(ordering, ReorderRecommendation.generated_at.desc(), ReorderRecommendation.id.desc()).limit(limit).offset(offset)
        ).scalars().all()
        return rows, total

    def get_for_date(self, *, seller_id: UUID, product_id: UUID, as_of_date: date, calculation_version: str) -> ReorderRecommendation | None:
        statement = (
            select(ReorderRecommendation)
            .join(Product, ReorderRecommendation.product_id == Product.id)
            .where(
                ReorderRecommendation.seller_id == seller_id,
                ReorderRecommendation.product_id == product_id,
                Product.seller_id == seller_id,
                ReorderRecommendation.as_of_date == as_of_date,
                ReorderRecommendation.calculation_version == calculation_version,
            )
        )
        return self._db.execute(statement).scalar_one_or_none()

    def get_by_id(self, *, seller_id: UUID, recommendation_id: UUID) -> ReorderRecommendation | None:
        statement = select(ReorderRecommendation).where(
            ReorderRecommendation.seller_id == seller_id,
            ReorderRecommendation.id == recommendation_id,
        )
        return self._db.execute(statement).scalar_one_or_none()

    def save_status(self, recommendation: ReorderRecommendation) -> ReorderRecommendation:
        self._db.commit()
        self._db.refresh(recommendation)
        return recommendation


def _latest_by_date(db: Session, *, model, seller_id: UUID, product_ids: list[UUID], date_column, as_of_date: date):
    if not product_ids:
        return {}
    latest_dates = (
        select(model.product_id.label("product_id"), func.max(date_column).label("as_of_date"))
        .where(model.seller_id == seller_id, model.product_id.in_(product_ids), date_column <= as_of_date)
        .group_by(model.product_id)
        .subquery()
    )
    rows = db.execute(
        select(model)
        .join(latest_dates, (model.product_id == latest_dates.c.product_id) & (date_column == latest_dates.c.as_of_date))
        .where(model.seller_id == seller_id)
    ).scalars().all()
    return {row.product_id: row for row in rows}
