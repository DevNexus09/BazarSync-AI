from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.inventory_aging import InventoryAgingSnapshot
from app.models.inventory_history import InventoryHistory
from app.models.inventory_stock_in import InventoryStockIn
from app.models.product import Product
from app.models.seller import Seller


class InventoryAgingRepository:
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

    def latest_inventory_for_products(
        self,
        *,
        seller_id: UUID,
        product_ids: list[UUID],
        as_of_date: date,
    ) -> dict[UUID, InventoryHistory]:
        if not product_ids:
            return {}
        latest_dates = (
            select(
                InventoryHistory.product_id.label("product_id"),
                func.max(InventoryHistory.snapshot_date).label("snapshot_date"),
            )
            .where(
                InventoryHistory.seller_id == seller_id,
                InventoryHistory.product_id.in_(product_ids),
                InventoryHistory.snapshot_date <= as_of_date,
            )
            .group_by(InventoryHistory.product_id)
            .subquery()
        )
        statement = (
            select(InventoryHistory)
            .join(
                latest_dates,
                (InventoryHistory.product_id == latest_dates.c.product_id)
                & (InventoryHistory.snapshot_date == latest_dates.c.snapshot_date),
            )
            .where(InventoryHistory.seller_id == seller_id)
        )
        rows = self._db.execute(statement).scalars().all()
        latest: dict[UUID, InventoryHistory] = {}
        for row in rows:
            current = latest.get(row.product_id)
            if current is None or row.captured_at > current.captured_at:
                latest[row.product_id] = row
        return latest

    def first_positive_inventory_for_products(
        self,
        *,
        seller_id: UUID,
        product_ids: list[UUID],
        as_of_date: date,
    ) -> dict[UUID, InventoryHistory]:
        if not product_ids:
            return {}
        first_dates = (
            select(
                InventoryHistory.product_id.label("product_id"),
                func.min(InventoryHistory.snapshot_date).label("snapshot_date"),
            )
            .where(
                InventoryHistory.seller_id == seller_id,
                InventoryHistory.product_id.in_(product_ids),
                InventoryHistory.snapshot_date <= as_of_date,
                InventoryHistory.quantity_on_hand > 0,
            )
            .group_by(InventoryHistory.product_id)
            .subquery()
        )
        statement = (
            select(InventoryHistory)
            .join(
                first_dates,
                (InventoryHistory.product_id == first_dates.c.product_id)
                & (InventoryHistory.snapshot_date == first_dates.c.snapshot_date),
            )
            .where(InventoryHistory.seller_id == seller_id)
        )
        rows = self._db.execute(statement).scalars().all()
        earliest: dict[UUID, InventoryHistory] = {}
        for row in rows:
            current = earliest.get(row.product_id)
            if current is None or row.captured_at < current.captured_at:
                earliest[row.product_id] = row
        return earliest

    def add_idempotent(self, snapshot: InventoryAgingSnapshot) -> tuple[InventoryAgingSnapshot, bool]:
        existing = self.get_for_date(
            seller_id=snapshot.seller_id,
            product_id=snapshot.product_id,
            as_of_date=snapshot.as_of_date,
            calculation_version=snapshot.calculation_version,
        )
        if existing:
            return existing, False

        self._db.add(snapshot)
        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            existing = self.get_for_date(
                seller_id=snapshot.seller_id,
                product_id=snapshot.product_id,
                as_of_date=snapshot.as_of_date,
                calculation_version=snapshot.calculation_version,
            )
            if existing:
                return existing, False
            raise
        self._db.refresh(snapshot)
        return snapshot, True

    def get_for_date(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        as_of_date: date,
        calculation_version: str,
    ) -> InventoryAgingSnapshot | None:
        statement = (
            select(InventoryAgingSnapshot)
            .join(Product, InventoryAgingSnapshot.product_id == Product.id)
            .where(
                InventoryAgingSnapshot.seller_id == seller_id,
                InventoryAgingSnapshot.product_id == product_id,
                InventoryAgingSnapshot.as_of_date == as_of_date,
                InventoryAgingSnapshot.calculation_version == calculation_version,
                Product.seller_id == seller_id,
            )
        )
        return self._db.execute(statement).scalar_one_or_none()

    def latest(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        calculation_version: str | None,
    ) -> InventoryAgingSnapshot | None:
        statement = (
            select(InventoryAgingSnapshot)
            .join(Product, InventoryAgingSnapshot.product_id == Product.id)
            .where(
                InventoryAgingSnapshot.seller_id == seller_id,
                InventoryAgingSnapshot.product_id == product_id,
                Product.seller_id == seller_id,
            )
        )
        if calculation_version:
            statement = statement.where(InventoryAgingSnapshot.calculation_version == calculation_version)
        return self._db.execute(
            statement.order_by(
                InventoryAgingSnapshot.as_of_date.desc(),
                InventoryAgingSnapshot.calculated_at.desc(),
                InventoryAgingSnapshot.id.desc(),
            ).limit(1)
        ).scalar_one_or_none()

    def lot_states_for_products(
        self,
        *,
        seller_id: UUID,
        product_ids: list[UUID],
        as_of_date: date,
    ) -> dict[UUID, list]:
        if not product_ids:
            return {}
        from app.models.inventory_aging import InventoryAgeSource
        from app.services.inventory_aging_service import InventoryLotState

        rows = self._db.execute(
            select(InventoryStockIn)
            .where(
                InventoryStockIn.seller_id == seller_id,
                InventoryStockIn.product_id.in_(product_ids),
                func.date(InventoryStockIn.received_at) <= as_of_date,
            )
            .order_by(InventoryStockIn.received_at.asc(), InventoryStockIn.id.asc())
        ).scalars().all()
        result: dict[UUID, list[InventoryLotState]] = {}
        for row in rows:
            result.setdefault(row.product_id, []).append(
                InventoryLotState(
                    received_date=row.received_at.date(),
                    remaining_quantity=int(row.quantity),
                    source=InventoryAgeSource.INVENTORY_TRANSACTION,
                    reference=row.source_reference,
                )
            )
        return result

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
    ) -> tuple[list[InventoryAgingSnapshot], int]:
        statement = (
            select(InventoryAgingSnapshot)
            .join(Product, InventoryAgingSnapshot.product_id == Product.id)
            .where(
                InventoryAgingSnapshot.seller_id == seller_id,
                InventoryAgingSnapshot.product_id == product_id,
                Product.seller_id == seller_id,
            )
        )
        if from_date:
            statement = statement.where(InventoryAgingSnapshot.as_of_date >= from_date)
        if to_date:
            statement = statement.where(InventoryAgingSnapshot.as_of_date <= to_date)
        if calculation_version:
            statement = statement.where(InventoryAgingSnapshot.calculation_version == calculation_version)

        total = self._db.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
        ordering = InventoryAgingSnapshot.as_of_date.asc() if order == "asc" else InventoryAgingSnapshot.as_of_date.desc()
        rows = self._db.execute(
            statement.order_by(ordering, InventoryAgingSnapshot.calculated_at.desc(), InventoryAgingSnapshot.id.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
        return rows, total
