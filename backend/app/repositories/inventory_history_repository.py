from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.inventory_history import InventoryHistory
from app.models.product import Product
from app.models.seller import Seller


class InventoryHistoryRepository:
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

    def get_for_scope(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        snapshot_date: date,
    ) -> InventoryHistory | None:
        statement = select(InventoryHistory).where(
            InventoryHistory.seller_id == seller_id,
            InventoryHistory.product_id == product_id,
            InventoryHistory.snapshot_date == snapshot_date,
        )
        return self._db.execute(statement).scalar_one_or_none()

    def add_idempotent(self, snapshot: InventoryHistory) -> tuple[InventoryHistory, bool]:
        existing = self.get_for_scope(
            seller_id=snapshot.seller_id,
            product_id=snapshot.product_id,
            snapshot_date=snapshot.snapshot_date,
        )
        if existing:
            return existing, False

        self._db.add(snapshot)
        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            existing = self.get_for_scope(
                seller_id=snapshot.seller_id,
                product_id=snapshot.product_id,
                snapshot_date=snapshot.snapshot_date,
            )
            if existing:
                return existing, False
            raise
        self._db.refresh(snapshot)
        return snapshot, True

    def list_for_product(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        from_date: date | None,
        to_date: date | None,
        order: str,
        limit: int,
        offset: int,
    ) -> tuple[list[InventoryHistory], int]:
        statement = (
            select(InventoryHistory)
            .join(Product, InventoryHistory.product_id == Product.id)
            .where(
                InventoryHistory.seller_id == seller_id,
                InventoryHistory.product_id == product_id,
                Product.seller_id == seller_id,
            )
        )
        if from_date:
            statement = statement.where(InventoryHistory.snapshot_date >= from_date)
        if to_date:
            statement = statement.where(InventoryHistory.snapshot_date <= to_date)

        total = self._db.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
        ordering = InventoryHistory.snapshot_date.asc() if order == "asc" else InventoryHistory.snapshot_date.desc()
        items = self._db.execute(
            statement.order_by(ordering, InventoryHistory.captured_at.desc(), InventoryHistory.id.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
        return items, total

    def latest_for_product(self, *, seller_id: UUID, product_id: UUID) -> InventoryHistory | None:
        statement = (
            select(InventoryHistory)
            .join(Product, InventoryHistory.product_id == Product.id)
            .where(
                InventoryHistory.seller_id == seller_id,
                InventoryHistory.product_id == product_id,
                Product.seller_id == seller_id,
            )
            .order_by(
                InventoryHistory.snapshot_date.desc(),
                InventoryHistory.captured_at.desc(),
                InventoryHistory.id.desc(),
            )
            .limit(1)
        )
        return self._db.execute(statement).scalar_one_or_none()
