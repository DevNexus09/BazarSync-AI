from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import logging
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.models.inventory_history import InventoryHistory, InventorySnapshotSource
from app.models.product import Product
from app.models.seller import Seller
from app.repositories.inventory_history_repository import InventoryHistoryRepository

logger = logging.getLogger(__name__)


class ProductBatchRepository(Protocol):
    def iter_product_batches(
        self,
        *,
        batch_size: int,
        seller_id: UUID | None = None,
        product_id: UUID | None = None,
    ): ...

    def add_idempotent(self, snapshot: InventoryHistory) -> tuple[InventoryHistory, bool]: ...

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
    ) -> tuple[list[InventoryHistory], int]: ...

    def latest_for_product(self, *, seller_id: UUID, product_id: UUID) -> InventoryHistory | None: ...


@dataclass(frozen=True)
class InventoryQuantityState:
    quantity_on_hand: int
    quantity_reserved: int = 0
    quantity_incoming: int = 0

    @property
    def quantity_available(self) -> int:
        return self.quantity_on_hand - self.quantity_reserved

    @property
    def inventory_position(self) -> int:
        return self.quantity_on_hand + self.quantity_incoming - self.quantity_reserved


@dataclass(frozen=True)
class InventorySnapshotOutcome:
    snapshot: InventoryHistory
    created: bool


@dataclass(frozen=True)
class InventoryBatchResult:
    created_count: int
    skipped_count: int
    failed_count: int
    dry_run_count: int = 0


class InvalidInventoryQuantityError(ValueError):
    pass


class InventoryHistoryService:
    def __init__(
        self,
        db: Session | None = None,
        *,
        repository: ProductBatchRepository | None = None,
        log: logging.Logger | None = None,
    ) -> None:
        if repository is None and db is None:
            raise ValueError("Either db or repository is required.")
        self._repository = repository or InventoryHistoryRepository(db)  # type: ignore[arg-type]
        self._log = log or logger

    def create_snapshot_for_product(
        self,
        *,
        product: Product,
        seller: Seller | None = None,
        snapshot_date: date | None = None,
        captured_at: datetime | None = None,
        quantity_reserved: int = 0,
        quantity_incoming: int = 0,
        source: InventorySnapshotSource = InventorySnapshotSource.DAILY_SNAPSHOT,
        source_reference: str | None = None,
    ) -> InventorySnapshotOutcome:
        captured_at = _ensure_utc(captured_at or datetime.now(timezone.utc))
        seller_obj = seller or product.seller
        if snapshot_date is None:
            snapshot_date = self.business_date_for_seller(seller_obj, captured_at)
        state = InventoryQuantityState(
            quantity_on_hand=int(product.stock_quantity),
            quantity_reserved=quantity_reserved,
            quantity_incoming=quantity_incoming,
        )
        _validate_quantity_state(state)

        reference = source_reference or self._default_source_reference(
            product_id=product.id,
            snapshot_date=snapshot_date,
            source=source,
        )
        snapshot = InventoryHistory(
            seller_id=product.seller_id,
            product_id=product.id,
            snapshot_date=snapshot_date,
            captured_at=captured_at,
            quantity_on_hand=state.quantity_on_hand,
            quantity_reserved=state.quantity_reserved,
            quantity_available=state.quantity_available,
            quantity_incoming=state.quantity_incoming,
            source=source,
            source_reference=reference,
            content_hash=self.content_hash(
                seller_id=product.seller_id,
                product_id=product.id,
                snapshot_date=snapshot_date,
                state=state,
                source=source,
                source_reference=reference,
            ),
        )
        saved, created = self._repository.add_idempotent(snapshot)
        return InventorySnapshotOutcome(snapshot=saved, created=created)

    def capture_daily_snapshots(
        self,
        *,
        batch_size: int = 500,
        now: datetime | None = None,
        seller_id: UUID | None = None,
        product_id: UUID | None = None,
    ) -> InventoryBatchResult:
        captured_at = _ensure_utc(now or datetime.now(timezone.utc))
        created = 0
        skipped = 0
        failed = 0
        for batch in self._repository.iter_product_batches(
            batch_size=batch_size,
            seller_id=seller_id,
            product_id=product_id,
        ):
            for product, seller in batch:
                try:
                    outcome = self.create_snapshot_for_product(
                        product=product,
                        seller=seller,
                        captured_at=captured_at,
                        source=InventorySnapshotSource.DAILY_SNAPSHOT,
                    )
                except Exception:
                    failed += 1
                    self._log.exception(
                        "Inventory snapshot failed seller_id=%s product_id=%s",
                        getattr(product, "seller_id", None),
                        getattr(product, "id", None),
                    )
                    continue
                if outcome.created:
                    created += 1
                else:
                    skipped += 1
        self._log.info(
            "Inventory daily snapshot completed created=%s skipped=%s failed=%s",
            created,
            skipped,
            failed,
        )
        return InventoryBatchResult(created_count=created, skipped_count=skipped, failed_count=failed)

    def backfill_current_inventory(
        self,
        *,
        batch_size: int = 500,
        now: datetime | None = None,
        seller_id: UUID | None = None,
        product_id: UUID | None = None,
        dry_run: bool = False,
    ) -> InventoryBatchResult:
        captured_at = _ensure_utc(now or datetime.now(timezone.utc))
        created = 0
        skipped = 0
        failed = 0
        dry_run_count = 0
        for batch in self._repository.iter_product_batches(
            batch_size=batch_size,
            seller_id=seller_id,
            product_id=product_id,
        ):
            for product, seller in batch:
                snapshot_date = self.business_date_for_seller(seller, captured_at)
                if dry_run:
                    dry_run_count += 1
                    continue
                try:
                    outcome = self.create_snapshot_for_product(
                        product=product,
                        seller=seller,
                        snapshot_date=snapshot_date,
                        captured_at=captured_at,
                        source=InventorySnapshotSource.BACKFILL,
                        source_reference=f"baseline-current-stock:{product.id}:{snapshot_date.isoformat()}",
                    )
                except Exception:
                    failed += 1
                    self._log.exception(
                        "Inventory backfill failed seller_id=%s product_id=%s",
                        getattr(product, "seller_id", None),
                        getattr(product, "id", None),
                    )
                    continue
                if outcome.created:
                    created += 1
                else:
                    skipped += 1
        self._log.info(
            "Inventory backfill completed created=%s skipped=%s failed=%s dry_run=%s",
            created,
            skipped,
            failed,
            dry_run_count,
        )
        return InventoryBatchResult(
            created_count=created,
            skipped_count=skipped,
            failed_count=failed,
            dry_run_count=dry_run_count,
        )

    def list_product_history(
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
        return self._repository.list_for_product(
            seller_id=seller_id,
            product_id=product_id,
            from_date=from_date,
            to_date=to_date,
            order=order,
            limit=limit,
            offset=offset,
        )

    def latest_product_snapshot(self, *, seller_id: UUID, product_id: UUID) -> InventoryHistory | None:
        return self._repository.latest_for_product(seller_id=seller_id, product_id=product_id)

    @staticmethod
    def business_date_for_seller(seller: Seller, captured_at: datetime) -> date:
        timezone_name = getattr(seller, "timezone", None) or "UTC"
        try:
            seller_timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            seller_timezone = timezone.utc
        return _ensure_utc(captured_at).astimezone(seller_timezone).date()

    @staticmethod
    def content_hash(
        *,
        seller_id: UUID,
        product_id: UUID,
        snapshot_date: date,
        state: InventoryQuantityState,
        source: InventorySnapshotSource,
        source_reference: str | None,
    ) -> str:
        payload = {
            "seller_id": str(seller_id),
            "product_id": str(product_id),
            "snapshot_date": snapshot_date.isoformat(),
            "quantity_on_hand": state.quantity_on_hand,
            "quantity_reserved": state.quantity_reserved,
            "quantity_available": state.quantity_available,
            "quantity_incoming": state.quantity_incoming,
            "source": source.value,
            "source_reference": source_reference,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _default_source_reference(
        *,
        product_id: UUID,
        snapshot_date: date,
        source: InventorySnapshotSource,
    ) -> str:
        return f"{source.value.lower()}:{product_id}:{snapshot_date.isoformat()}"


def _validate_quantity_state(state: InventoryQuantityState) -> None:
    invalid_fields = [
        name
        for name in ("quantity_on_hand", "quantity_reserved", "quantity_incoming")
        if getattr(state, name) < 0
    ]
    if invalid_fields:
        raise InvalidInventoryQuantityError(
            f"Inventory quantities must be nonnegative: {', '.join(invalid_fields)}"
        )


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
