from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import logging
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.inventory_aging import InventoryAgeSource, InventoryAgingSnapshot
from app.models.inventory_history import InventoryHistory
from app.models.product import Product
from app.models.seller import Seller
from app.repositories.inventory_aging_repository import InventoryAgingRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InventoryLotState:
    received_date: date
    remaining_quantity: int
    source: InventoryAgeSource = InventoryAgeSource.INVENTORY_LOT
    reference: str | None = None


class InventoryAgingRepositoryProtocol(Protocol):
    def iter_product_batches(
        self,
        *,
        batch_size: int,
        seller_id: UUID | None = None,
        product_id: UUID | None = None,
    ): ...

    def latest_inventory_for_products(
        self,
        *,
        seller_id: UUID,
        product_ids: list[UUID],
        as_of_date: date,
    ) -> dict[UUID, InventoryHistory]: ...

    def first_positive_inventory_for_products(
        self,
        *,
        seller_id: UUID,
        product_ids: list[UUID],
        as_of_date: date,
    ) -> dict[UUID, InventoryHistory]: ...

    def add_idempotent(self, snapshot: InventoryAgingSnapshot) -> tuple[InventoryAgingSnapshot, bool]: ...

    def latest(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        calculation_version: str | None,
    ) -> InventoryAgingSnapshot | None: ...

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
    ) -> tuple[list[InventoryAgingSnapshot], int]: ...


@dataclass(frozen=True)
class InventoryAgingOutcome:
    snapshot: InventoryAgingSnapshot
    created: bool


@dataclass(frozen=True)
class InventoryAgingBatchResult:
    calculated_count: int
    estimated_count: int
    unavailable_count: int
    skipped_count: int
    failed_count: int
    dry_run_count: int = 0


class InventoryAgingService:
    def __init__(
        self,
        db: Session | None = None,
        *,
        repository: InventoryAgingRepositoryProtocol | None = None,
        bucket_edges: list[int] | None = None,
        calculation_version: str | None = None,
        log: logging.Logger | None = None,
    ) -> None:
        if repository is None and db is None:
            raise ValueError("Either db or repository is required.")
        self._repository = repository or InventoryAgingRepository(db)  # type: ignore[arg-type]
        self._bucket_edges = _normalize_bucket_edges(bucket_edges or settings.inventory_aging_bucket_edges_days)
        self._calculation_version = calculation_version or settings.inventory_aging_calculation_version
        self._log = log or logger

    def calculate_for_product(
        self,
        *,
        product: Product,
        seller: Seller | None = None,
        as_of_date: date,
        calculated_at: datetime | None = None,
        inventory_snapshot: InventoryHistory | None = None,
        first_positive_snapshot: InventoryHistory | None = None,
        lots: list[InventoryLotState] | None = None,
    ) -> InventoryAgingOutcome:
        calculated_at = _ensure_utc(calculated_at or datetime.now(timezone.utc))
        seller_obj = seller or product.seller
        quantities = _quantity_state(product=product, inventory_snapshot=inventory_snapshot)
        eligible_quantity = max(0, quantities["quantity_on_hand"] - quantities["quantity_reserved"])
        usable_lots = [
            lot
            for lot in lots or []
            if eligible_quantity > 0 and lot.remaining_quantity > 0 and lot.received_date <= as_of_date
        ]

        if usable_lots:
            age_payload = self._lot_age_payload(
                lots=usable_lots,
                eligible_quantity=eligible_quantity,
                as_of_date=as_of_date,
            )
        else:
            age_payload = self._estimated_age_payload(
                product=product,
                as_of_date=as_of_date,
                eligible_quantity=eligible_quantity,
                first_positive_snapshot=first_positive_snapshot,
            )

        snapshot = InventoryAgingSnapshot(
            seller_id=product.seller_id,
            product_id=product.id,
            inventory_snapshot_id=getattr(inventory_snapshot, "id", None),
            as_of_date=as_of_date,
            quantity_on_hand=quantities["quantity_on_hand"],
            quantity_reserved=quantities["quantity_reserved"],
            quantity_available=quantities["quantity_available"],
            eligible_unsold_quantity=eligible_quantity,
            oldest_age_days=age_payload["oldest_age_days"],
            newest_age_days=age_payload["newest_age_days"],
            weighted_average_age_days=age_payload["weighted_average_age_days"],
            age_source=age_payload["age_source"],
            is_estimated=age_payload["is_estimated"],
            confidence_score=age_payload["confidence_score"],
            age_buckets=age_payload["age_buckets"],
            evidence={
                **age_payload["evidence"],
                "formula": "weighted_average_age_days = sum(remaining_quantity * age_days) / sum(remaining_quantity)",
                "eligible_unsold_quantity_policy": "max(0, quantity_on_hand - quantity_reserved)",
                "seller_timezone": getattr(seller_obj, "timezone", None) or "UTC",
                "source_priority": [
                    InventoryAgeSource.INVENTORY_LOT.value,
                    InventoryAgeSource.PURCHASE_RECEIPT.value,
                    InventoryAgeSource.INVENTORY_TRANSACTION.value,
                    InventoryAgeSource.FIRST_POSITIVE_SNAPSHOT.value,
                    InventoryAgeSource.PRODUCT_CREATED_AT_ESTIMATE.value,
                    InventoryAgeSource.UNAVAILABLE.value,
                ],
            },
            calculation_version=self._calculation_version,
            calculated_at=calculated_at,
        )
        saved, created = self._repository.add_idempotent(snapshot)
        return InventoryAgingOutcome(snapshot=saved, created=created)

    def calculate_batch(
        self,
        *,
        batch_size: int = 500,
        as_of_date: date | None = None,
        now: datetime | None = None,
        seller_id: UUID | None = None,
        product_id: UUID | None = None,
        dry_run: bool = False,
    ) -> InventoryAgingBatchResult:
        calculated_at = _ensure_utc(now or datetime.now(timezone.utc))
        calculated = 0
        estimated = 0
        unavailable = 0
        skipped = 0
        failed = 0
        dry_run_count = 0

        for batch in self._repository.iter_product_batches(
            batch_size=batch_size,
            seller_id=seller_id,
            product_id=product_id,
        ):
            by_seller: dict[UUID, list[tuple[Product, Seller]]] = defaultdict(list)
            for product, seller in batch:
                by_seller[product.seller_id].append((product, seller))

            for batch_seller_id, rows in by_seller.items():
                seller_obj = rows[0][1]
                seller_as_of_date = as_of_date or self.business_date_for_seller(seller_obj, calculated_at)
                product_ids = [product.id for product, _ in rows]
                latest_inventory = self._repository.latest_inventory_for_products(
                    seller_id=batch_seller_id,
                    product_ids=product_ids,
                    as_of_date=seller_as_of_date,
                )
                first_positive = self._repository.first_positive_inventory_for_products(
                    seller_id=batch_seller_id,
                    product_ids=product_ids,
                    as_of_date=seller_as_of_date,
                )
                lots_by_product = self._lot_states_for_products(
                    seller_id=batch_seller_id,
                    product_ids=product_ids,
                    as_of_date=seller_as_of_date,
                )

                for product, seller in rows:
                    if dry_run:
                        dry_run_count += 1
                        continue
                    try:
                        outcome = self.calculate_for_product(
                            product=product,
                            seller=seller,
                            as_of_date=seller_as_of_date,
                            calculated_at=calculated_at,
                            inventory_snapshot=latest_inventory.get(product.id),
                            first_positive_snapshot=first_positive.get(product.id),
                            lots=lots_by_product.get(product.id, []),
                        )
                    except Exception:
                        failed += 1
                        self._log.exception(
                            "inventory_aging_product_failed seller_id=%s product_id=%s as_of_date=%s",
                            getattr(product, "seller_id", None),
                            getattr(product, "id", None),
                            seller_as_of_date,
                        )
                        continue
                    if outcome.created:
                        calculated += 1
                        if outcome.snapshot.age_source == InventoryAgeSource.UNAVAILABLE:
                            unavailable += 1
                        elif outcome.snapshot.is_estimated:
                            estimated += 1
                    else:
                        skipped += 1

        self._log.info(
            "inventory_aging_batch_completed calculated=%s estimated=%s unavailable=%s skipped=%s failed=%s dry_run=%s",
            calculated,
            estimated,
            unavailable,
            skipped,
            failed,
            dry_run_count,
        )
        return InventoryAgingBatchResult(
            calculated_count=calculated,
            estimated_count=estimated,
            unavailable_count=unavailable,
            skipped_count=skipped,
            failed_count=failed,
            dry_run_count=dry_run_count,
        )

    def backfill_baseline(
        self,
        *,
        batch_size: int = 500,
        as_of_date: date | None = None,
        now: datetime | None = None,
        seller_id: UUID | None = None,
        product_id: UUID | None = None,
        dry_run: bool = False,
    ) -> InventoryAgingBatchResult:
        return self.calculate_batch(
            batch_size=batch_size,
            as_of_date=as_of_date,
            now=now,
            seller_id=seller_id,
            product_id=product_id,
            dry_run=dry_run,
        )

    def latest_aging(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        calculation_version: str | None = None,
    ) -> InventoryAgingSnapshot | None:
        return self._repository.latest(
            seller_id=seller_id,
            product_id=product_id,
            calculation_version=calculation_version,
        )

    def aging_history(
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
        return self._repository.history(
            seller_id=seller_id,
            product_id=product_id,
            from_date=from_date,
            to_date=to_date,
            calculation_version=calculation_version,
            order=order,
            limit=limit,
            offset=offset,
        )

    def age_bucket_distribution(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        calculation_version: str | None = None,
    ) -> dict:
        latest = self.latest_aging(
            seller_id=seller_id,
            product_id=product_id,
            calculation_version=calculation_version,
        )
        return latest.age_buckets if latest else self._empty_buckets()

    def explain_age_source(
        self,
        snapshot: InventoryAgingSnapshot,
    ) -> str:
        if snapshot.age_source == InventoryAgeSource.INVENTORY_LOT:
            return "Exact inventory age was calculated from remaining lot quantities and received dates."
        if snapshot.age_source == InventoryAgeSource.FIRST_POSITIVE_SNAPSHOT:
            return "Estimated inventory age was calculated from the first positive inventory-history snapshot."
        if snapshot.age_source == InventoryAgeSource.PRODUCT_CREATED_AT_ESTIMATE:
            return "Estimated inventory age was calculated from the product creation date because no inventory receipt or positive snapshot was available."
        return "Inventory age is unavailable because no reliable age source exists for the current unsold inventory."

    def detect_unavailable_aging_data(
        self,
        *,
        product: Product,
        inventory_snapshot: InventoryHistory | None,
        first_positive_snapshot: InventoryHistory | None,
        lots: list[InventoryLotState] | None,
    ) -> bool:
        quantities = _quantity_state(product=product, inventory_snapshot=inventory_snapshot)
        if max(0, quantities["quantity_on_hand"] - quantities["quantity_reserved"]) <= 0:
            return True
        if lots:
            return False
        return first_positive_snapshot is None and getattr(product, "created_at", None) is None

    @staticmethod
    def business_date_for_seller(seller: Seller, captured_at: datetime) -> date:
        timezone_name = getattr(seller, "timezone", None) or "UTC"
        try:
            seller_timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            seller_timezone = timezone.utc
        return _ensure_utc(captured_at).astimezone(seller_timezone).date()

    def _lot_age_payload(
        self,
        *,
        lots: list[InventoryLotState],
        eligible_quantity: int,
        as_of_date: date,
    ) -> dict:
        weighted_sum = Decimal("0")
        total_quantity = 0
        ages: list[int] = []
        for lot in lots:
            age_days = max(0, (as_of_date - lot.received_date).days)
            weighted_sum += Decimal(lot.remaining_quantity) * Decimal(age_days)
            total_quantity += lot.remaining_quantity
            ages.append(age_days)

        weighted_average = _quantize(weighted_sum / Decimal(total_quantity)) if total_quantity else None
        evidence_quantity_note = None
        if eligible_quantity and total_quantity != eligible_quantity:
            evidence_quantity_note = "Lot remaining quantity differs from current eligible quantity; exact lot quantities were used for age weighting."

        return {
            "oldest_age_days": max(ages) if ages else None,
            "newest_age_days": min(ages) if ages else None,
            "weighted_average_age_days": weighted_average,
            "age_source": lots[0].source if lots else InventoryAgeSource.INVENTORY_LOT,
            "is_estimated": False,
            "confidence_score": Decimal("95.00"),
            "age_buckets": self._bucketize_lots(lots=lots, as_of_date=as_of_date),
            "evidence": {
                "age_source_reason": "remaining inventory lots with received dates were available",
                "lot_count": len(lots),
                "lot_total_quantity": total_quantity,
                "quantity_note": evidence_quantity_note,
                "stock_consumption_policy": "repository lot remaining quantities; no separate stock-consumption policy table found",
            },
        }

    def _estimated_age_payload(
        self,
        *,
        product: Product,
        as_of_date: date,
        eligible_quantity: int,
        first_positive_snapshot: InventoryHistory | None,
    ) -> dict:
        if eligible_quantity <= 0:
            return self._unavailable_payload(
                reason="no eligible unsold quantity remains after excluding reserved stock",
            )

        if first_positive_snapshot is not None:
            age_days = max(0, (as_of_date - first_positive_snapshot.snapshot_date).days)
            return {
                "oldest_age_days": age_days,
                "newest_age_days": age_days,
                "weighted_average_age_days": _quantize(Decimal(age_days)),
                "age_source": InventoryAgeSource.FIRST_POSITIVE_SNAPSHOT,
                "is_estimated": True,
                "confidence_score": Decimal("70.00"),
                "age_buckets": self._bucketize_single(age_days=age_days, quantity=eligible_quantity),
                "evidence": {
                    "age_source_reason": "first positive inventory-history snapshot was the earliest reliable source",
                    "first_positive_snapshot_id": str(first_positive_snapshot.id),
                    "first_positive_snapshot_date": first_positive_snapshot.snapshot_date.isoformat(),
                    "limitation": "estimated product-level age; individual receipt or lot ages are not available",
                },
            }

        product_created_at = getattr(product, "created_at", None)
        if product_created_at is not None:
            created_date = _ensure_utc(product_created_at).date()
            age_days = max(0, (as_of_date - created_date).days)
            return {
                "oldest_age_days": age_days,
                "newest_age_days": age_days,
                "weighted_average_age_days": _quantize(Decimal(age_days)),
                "age_source": InventoryAgeSource.PRODUCT_CREATED_AT_ESTIMATE,
                "is_estimated": True,
                "confidence_score": Decimal("45.00"),
                "age_buckets": self._bucketize_single(age_days=age_days, quantity=eligible_quantity),
                "evidence": {
                    "age_source_reason": "product creation date was used as a final fallback",
                    "product_created_date": created_date.isoformat(),
                    "limitation": "this is not exact inventory age and may overstate or understate the age of current units",
                },
            }

        return self._unavailable_payload(reason="no inventory lots, receipts, transactions, positive snapshots, or product creation date were available")

    def _unavailable_payload(self, *, reason: str) -> dict:
        return {
            "oldest_age_days": None,
            "newest_age_days": None,
            "weighted_average_age_days": None,
            "age_source": InventoryAgeSource.UNAVAILABLE,
            "is_estimated": False,
            "confidence_score": Decimal("0.00"),
            "age_buckets": self._empty_buckets(),
            "evidence": {
                "age_source_reason": reason,
                "limitation": "inventory age is unavailable and was not replaced with zero",
            },
        }

    def _bucketize_lots(self, *, lots: list[InventoryLotState], as_of_date: date) -> dict:
        buckets = self._empty_buckets()
        for lot in lots:
            age_days = max(0, (as_of_date - lot.received_date).days)
            bucket_key = _bucket_key(age_days=age_days, edges=self._bucket_edges)
            buckets[bucket_key]["quantity"] += lot.remaining_quantity
        return buckets

    def _bucketize_single(self, *, age_days: int, quantity: int) -> dict:
        buckets = self._empty_buckets()
        buckets[_bucket_key(age_days=age_days, edges=self._bucket_edges)]["quantity"] = quantity
        return buckets

    def _empty_buckets(self) -> dict:
        buckets = {}
        lower = 0
        for edge in self._bucket_edges:
            key = f"{lower}_{edge}"
            buckets[key] = {"min_days": lower, "max_days": edge, "quantity": 0}
            lower = edge + 1
        buckets[f"{lower}_plus"] = {"min_days": lower, "max_days": None, "quantity": 0}
        return buckets

    def _lot_states_for_products(
        self,
        *,
        seller_id: UUID,
        product_ids: list[UUID],
        as_of_date: date,
    ) -> dict[UUID, list[InventoryLotState]]:
        getter = getattr(self._repository, "lot_states_for_products", None)
        if getter is None:
            return {}
        return getter(seller_id=seller_id, product_ids=product_ids, as_of_date=as_of_date)


def _quantity_state(*, product: Product, inventory_snapshot: InventoryHistory | None) -> dict[str, int]:
    if inventory_snapshot is not None:
        return {
            "quantity_on_hand": int(inventory_snapshot.quantity_on_hand),
            "quantity_reserved": int(inventory_snapshot.quantity_reserved),
            "quantity_available": max(0, int(inventory_snapshot.quantity_available)),
        }
    quantity_on_hand = max(0, int(product.stock_quantity))
    return {
        "quantity_on_hand": quantity_on_hand,
        "quantity_reserved": 0,
        "quantity_available": quantity_on_hand,
    }


def _bucket_key(*, age_days: int, edges: list[int]) -> str:
    lower = 0
    for edge in edges:
        if lower <= age_days <= edge:
            return f"{lower}_{edge}"
        lower = edge + 1
    return f"{lower}_plus"


def _normalize_bucket_edges(edges: list[int]) -> list[int]:
    normalized = sorted({int(edge) for edge in edges if int(edge) >= 0})
    return normalized or [30, 45, 60, 90, 180]


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
