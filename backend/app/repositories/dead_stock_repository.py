from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import and_, case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.dead_stock_assessment import (
    DeadStockAssessment,
    DeadStockClassification,
    DeadStockDataStatus,
    DeadStockVisibilityStatus,
)
from app.models.inventory_aging import InventoryAgingSnapshot
from app.models.product import Product
from app.models.product_visibility_metric import ProductVisibilityMetric
from app.models.sales_record import SalesRecord
from app.models.sales_velocity import SalesVelocity
from app.models.seller import Seller
from app.repositories.sales_velocity_repository import VALID_SALES_STATUSES


class DeadStockRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def iter_product_batches(
        self,
        *,
        batch_size: int,
        seller_id: UUID | None = None,
        product_id: UUID | None = None,
    ):
        offset = 0
        while True:
            statement = select(Product, Seller).join(Seller, Product.seller_id == Seller.id)
            if seller_id:
                statement = statement.where(Product.seller_id == seller_id)
            if product_id:
                statement = statement.where(Product.id == product_id)
            rows = self._db.execute(
                statement.order_by(Product.created_at.asc(), Product.id.asc())
                .limit(batch_size)
                .offset(offset)
            ).all()
            if not rows:
                break
            yield rows
            offset += batch_size

    def latest_aging_for_products(
        self,
        *,
        seller_id: UUID,
        product_ids: list[UUID],
        as_of_date: date,
    ) -> dict[UUID, InventoryAgingSnapshot]:
        return _latest_by_date(
            self._db,
            model=InventoryAgingSnapshot,
            seller_id=seller_id,
            product_ids=product_ids,
            date_column=InventoryAgingSnapshot.as_of_date,
            as_of_date=as_of_date,
        )

    def latest_velocity_for_products(
        self,
        *,
        seller_id: UUID,
        product_ids: list[UUID],
        as_of_date: date,
    ) -> dict[UUID, SalesVelocity]:
        return _latest_by_date(
            self._db,
            model=SalesVelocity,
            seller_id=seller_id,
            product_ids=product_ids,
            date_column=SalesVelocity.as_of_date,
            as_of_date=as_of_date,
        )

    def sales_summaries_for_products(
        self,
        *,
        seller_id: UUID,
        product_ids: list[UUID],
    ) -> dict[UUID, dict]:
        if not product_ids:
            return {}
        returns = SalesRecord.returned_units + SalesRecord.refunded_restocked_units
        net_units = func.greatest(SalesRecord.quantity_sold - returns, 0)
        valid_positive_sale = and_(
            SalesRecord.status.in_(VALID_SALES_STATUSES),
            SalesRecord.is_test_order.is_(False),
            net_units > 0,
        )
        statement = (
            select(
                SalesRecord.product_id,
                func.count(SalesRecord.id).label("sales_record_count"),
                func.coalesce(func.sum(case((valid_positive_sale, 1), else_=0)), 0).label("valid_positive_sale_count"),
                func.max(case((valid_positive_sale, SalesRecord.sold_at), else_=None)).label("last_valid_sale_at"),
            )
            .where(
                SalesRecord.seller_id == seller_id,
                SalesRecord.product_id.in_(product_ids),
            )
            .group_by(SalesRecord.product_id)
        )
        return {
            row.product_id: {
                "sales_record_count": int(row.sales_record_count or 0),
                "valid_positive_sale_count": int(row.valid_positive_sale_count or 0),
                "last_valid_sale_at": row.last_valid_sale_at,
            }
            for row in self._db.execute(statement).all()
        }

    def visibility_for_products(
        self,
        *,
        seller_id: UUID,
        product_ids: list[UUID],
        as_of_date: date,
    ) -> dict[UUID, dict]:
        if not product_ids:
            return {}
        from app.services.product_visibility_service import ProductVisibilityService

        latest_dates = (
            select(
                ProductVisibilityMetric.product_id.label("product_id"),
                func.max(ProductVisibilityMetric.metric_date).label("metric_date"),
            )
            .where(
                ProductVisibilityMetric.seller_id == seller_id,
                ProductVisibilityMetric.product_id.in_(product_ids),
                ProductVisibilityMetric.metric_date <= as_of_date,
            )
            .group_by(ProductVisibilityMetric.product_id)
            .subquery()
        )
        rows = self._db.execute(
            select(ProductVisibilityMetric)
            .join(
                latest_dates,
                (ProductVisibilityMetric.product_id == latest_dates.c.product_id)
                & (ProductVisibilityMetric.metric_date == latest_dates.c.metric_date),
            )
            .where(ProductVisibilityMetric.seller_id == seller_id)
        ).scalars().all()
        result: dict[UUID, dict] = {}
        for row in rows:
            current = result.get(row.product_id)
            evidence = ProductVisibilityService.evidence(row)
            if current is None:
                result[row.product_id] = evidence
        return result

    def add_idempotent(self, assessment: DeadStockAssessment) -> tuple[DeadStockAssessment, bool]:
        existing = self.get_for_date(
            seller_id=assessment.seller_id,
            product_id=assessment.product_id,
            as_of_date=assessment.as_of_date,
            calculation_version=assessment.calculation_version,
        )
        if existing:
            return existing, False
        self._db.add(assessment)
        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            existing = self.get_for_date(
                seller_id=assessment.seller_id,
                product_id=assessment.product_id,
                as_of_date=assessment.as_of_date,
                calculation_version=assessment.calculation_version,
            )
            if existing:
                return existing, False
            raise
        self._db.refresh(assessment)
        return assessment, True

    def latest(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        calculation_version: str | None,
    ) -> DeadStockAssessment | None:
        statement = (
            select(DeadStockAssessment)
            .join(Product, DeadStockAssessment.product_id == Product.id)
            .where(
                DeadStockAssessment.seller_id == seller_id,
                DeadStockAssessment.product_id == product_id,
                Product.seller_id == seller_id,
            )
        )
        if calculation_version:
            statement = statement.where(DeadStockAssessment.calculation_version == calculation_version)
        return self._db.execute(
            statement.order_by(
                DeadStockAssessment.as_of_date.desc(),
                DeadStockAssessment.assessed_at.desc(),
                DeadStockAssessment.id.desc(),
            ).limit(1)
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
    ) -> tuple[list[DeadStockAssessment], int]:
        statement = (
            select(DeadStockAssessment)
            .join(Product, DeadStockAssessment.product_id == Product.id)
            .where(
                DeadStockAssessment.seller_id == seller_id,
                DeadStockAssessment.product_id == product_id,
                Product.seller_id == seller_id,
            )
        )
        if from_date:
            statement = statement.where(DeadStockAssessment.as_of_date >= from_date)
        if to_date:
            statement = statement.where(DeadStockAssessment.as_of_date <= to_date)
        if calculation_version:
            statement = statement.where(DeadStockAssessment.calculation_version == calculation_version)

        total = self._db.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
        ordering = DeadStockAssessment.as_of_date.asc() if order == "asc" else DeadStockAssessment.as_of_date.desc()
        rows = self._db.execute(
            statement.order_by(ordering, DeadStockAssessment.assessed_at.desc(), DeadStockAssessment.id.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
        return rows, total

    def list_assessments(
        self,
        *,
        seller_id: UUID,
        classification: DeadStockClassification | None,
        product_id: UUID | None,
        category: str | None,
        marketplace: str | None,
        min_age_days: int | None,
        max_age_days: int | None,
        min_days_since_last_sale: int | None,
        max_days_since_last_sale: int | None,
        visibility_status: DeadStockVisibilityStatus | None,
        data_status: DeadStockDataStatus | None,
        from_date: date | None,
        to_date: date | None,
        limit: int,
        offset: int,
    ) -> tuple[list[DeadStockAssessment], int]:
        del marketplace
        statement = (
            select(DeadStockAssessment)
            .join(Product, DeadStockAssessment.product_id == Product.id)
            .where(DeadStockAssessment.seller_id == seller_id, Product.seller_id == seller_id)
        )
        if classification:
            statement = statement.where(DeadStockAssessment.classification == classification)
        if product_id:
            statement = statement.where(DeadStockAssessment.product_id == product_id)
        if category:
            statement = statement.where(Product.category == category)
        if min_age_days is not None:
            statement = statement.where(DeadStockAssessment.inventory_age_days >= min_age_days)
        if max_age_days is not None:
            statement = statement.where(DeadStockAssessment.inventory_age_days <= max_age_days)
        if min_days_since_last_sale is not None:
            statement = statement.where(DeadStockAssessment.days_since_last_sale >= min_days_since_last_sale)
        if max_days_since_last_sale is not None:
            statement = statement.where(DeadStockAssessment.days_since_last_sale <= max_days_since_last_sale)
        if visibility_status:
            statement = statement.where(DeadStockAssessment.visibility_status == visibility_status)
        if data_status:
            statement = statement.where(DeadStockAssessment.data_status == data_status)
        if from_date:
            statement = statement.where(DeadStockAssessment.as_of_date >= from_date)
        if to_date:
            statement = statement.where(DeadStockAssessment.as_of_date <= to_date)

        total = self._db.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
        rows = self._db.execute(
            statement.order_by(DeadStockAssessment.assessed_at.desc(), DeadStockAssessment.id.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
        return rows, total

    def get_for_date(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        as_of_date: date,
        calculation_version: str,
    ) -> DeadStockAssessment | None:
        statement = (
            select(DeadStockAssessment)
            .join(Product, DeadStockAssessment.product_id == Product.id)
            .where(
                DeadStockAssessment.seller_id == seller_id,
                DeadStockAssessment.product_id == product_id,
                DeadStockAssessment.as_of_date == as_of_date,
                DeadStockAssessment.calculation_version == calculation_version,
                Product.seller_id == seller_id,
            )
        )
        return self._db.execute(statement).scalar_one_or_none()


def _latest_by_date(db: Session, *, model, seller_id: UUID, product_ids: list[UUID], date_column, as_of_date: date):
    if not product_ids:
        return {}
    latest_dates = (
        select(model.product_id.label("product_id"), func.max(date_column).label("as_of_date"))
        .where(
            model.seller_id == seller_id,
            model.product_id.in_(product_ids),
            date_column <= as_of_date,
        )
        .group_by(model.product_id)
        .subquery()
    )
    rows = db.execute(
        select(model)
        .join(
            latest_dates,
            (model.product_id == latest_dates.c.product_id)
            & (date_column == latest_dates.c.as_of_date),
        )
        .where(model.seller_id == seller_id)
    ).scalars().all()
    return {row.product_id: row for row in rows}
