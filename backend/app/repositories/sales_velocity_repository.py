from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.product import Product
from app.models.sales_record import SalesRecord, SalesRecordStatus
from app.models.sales_velocity import SalesVelocity
from app.models.seller import Seller


VALID_SALES_STATUSES = (SalesRecordStatus.COMPLETED, SalesRecordStatus.FULFILLED)


class SalesVelocityRepository:
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

    def aggregate_sales(
        self,
        *,
        seller_id: UUID,
        product_ids: list[UUID],
        window_start: datetime,
        window_end: datetime,
    ) -> dict[UUID, dict[str, int]]:
        if not product_ids:
            return {}
        returns = SalesRecord.returned_units + SalesRecord.refunded_restocked_units
        row_net = func.greatest(SalesRecord.quantity_sold - returns, 0)
        statement = (
            select(
                SalesRecord.product_id,
                func.coalesce(func.sum(SalesRecord.quantity_sold), 0).label("gross_units_sold"),
                func.coalesce(func.sum(returns), 0).label("returned_units"),
                func.coalesce(func.sum(row_net), 0).label("net_units_sold"),
                func.count(SalesRecord.id).label("valid_sales_records"),
                func.count(func.distinct(func.date(SalesRecord.sold_at))).label("sales_days"),
            )
            .where(
                SalesRecord.seller_id == seller_id,
                SalesRecord.product_id.in_(product_ids),
                SalesRecord.status.in_(VALID_SALES_STATUSES),
                SalesRecord.is_test_order.is_(False),
                SalesRecord.quantity_sold > 0,
                SalesRecord.returned_units >= 0,
                SalesRecord.refunded_restocked_units >= 0,
                SalesRecord.sold_at >= window_start,
                SalesRecord.sold_at < window_end,
            )
            .group_by(SalesRecord.product_id)
        )
        rows = self._db.execute(statement).all()
        return {
            row.product_id: {
                "gross_units_sold": int(row.gross_units_sold or 0),
                "returned_units": int(row.returned_units or 0),
                "net_units_sold": int(row.net_units_sold or 0),
                "valid_sales_records": int(row.valid_sales_records or 0),
                "sales_days": int(row.sales_days or 0),
            }
            for row in rows
        }

    def add_idempotent(self, record: SalesVelocity) -> tuple[SalesVelocity, bool]:
        existing = self.get_for_date(
            seller_id=record.seller_id,
            product_id=record.product_id,
            as_of_date=record.as_of_date,
            window_days=record.window_days,
            calculation_version=record.calculation_version,
        )
        if existing:
            return existing, False

        self._db.add(record)
        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            existing = self.get_for_date(
                seller_id=record.seller_id,
                product_id=record.product_id,
                as_of_date=record.as_of_date,
                window_days=record.window_days,
                calculation_version=record.calculation_version,
            )
            if existing:
                return existing, False
            raise
        self._db.refresh(record)
        return record, True

    def latest(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        window_days: int | None,
        calculation_version: str | None,
    ) -> SalesVelocity | None:
        statement = (
            select(SalesVelocity)
            .join(Product, SalesVelocity.product_id == Product.id)
            .where(
                SalesVelocity.seller_id == seller_id,
                SalesVelocity.product_id == product_id,
                Product.seller_id == seller_id,
            )
        )
        if window_days:
            statement = statement.where(SalesVelocity.window_days == window_days)
        if calculation_version:
            statement = statement.where(SalesVelocity.calculation_version == calculation_version)
        return self._db.execute(
            statement.order_by(
                SalesVelocity.as_of_date.desc(),
                SalesVelocity.calculated_at.desc(),
                SalesVelocity.id.desc(),
            ).limit(1)
        ).scalar_one_or_none()

    def history(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        from_date: date | None,
        to_date: date | None,
        window_days: int | None,
        calculation_version: str | None,
        order: str,
        limit: int,
        offset: int,
    ) -> tuple[list[SalesVelocity], int]:
        statement = (
            select(SalesVelocity)
            .join(Product, SalesVelocity.product_id == Product.id)
            .where(
                SalesVelocity.seller_id == seller_id,
                SalesVelocity.product_id == product_id,
                Product.seller_id == seller_id,
            )
        )
        if from_date:
            statement = statement.where(SalesVelocity.as_of_date >= from_date)
        if to_date:
            statement = statement.where(SalesVelocity.as_of_date <= to_date)
        if window_days:
            statement = statement.where(SalesVelocity.window_days == window_days)
        if calculation_version:
            statement = statement.where(SalesVelocity.calculation_version == calculation_version)

        total = self._db.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
        ordering = SalesVelocity.as_of_date.asc() if order == "asc" else SalesVelocity.as_of_date.desc()
        items = self._db.execute(
            statement.order_by(ordering, SalesVelocity.calculated_at.desc(), SalesVelocity.id.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
        return items, total

    def get_for_date(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        as_of_date: date,
        window_days: int,
        calculation_version: str,
    ) -> SalesVelocity | None:
        statement = (
            select(SalesVelocity)
            .join(Product, SalesVelocity.product_id == Product.id)
            .where(
                SalesVelocity.seller_id == seller_id,
                SalesVelocity.product_id == product_id,
                Product.seller_id == seller_id,
                SalesVelocity.as_of_date == as_of_date,
                SalesVelocity.window_days == window_days,
                SalesVelocity.calculation_version == calculation_version,
            )
        )
        return self._db.execute(statement).scalar_one_or_none()
