from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
import logging
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.inventory_history import InventoryHistory
from app.models.product import Product
from app.models.sales_velocity import SalesVelocity, SalesVelocityDataStatus
from app.models.seller import Seller
from app.models.stockout_prediction import StockoutPrediction, StockoutPredictionStatus
from app.repositories.stockout_prediction_repository import StockoutPredictionRepository

logger = logging.getLogger(__name__)


class StockoutPredictionRepositoryProtocol(Protocol):
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

    def latest_velocity_for_products(
        self,
        *,
        seller_id: UUID,
        product_ids: list[UUID],
        as_of_date: date,
    ) -> dict[UUID, SalesVelocity]: ...

    def add_idempotent(self, prediction: StockoutPrediction) -> tuple[StockoutPrediction, bool]: ...

    def latest(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        calculation_version: str | None,
    ) -> StockoutPrediction | None: ...

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
    ) -> tuple[list[StockoutPrediction], int]: ...


@dataclass(frozen=True)
class StockoutPredictionOutcome:
    prediction: StockoutPrediction
    created: bool


@dataclass(frozen=True)
class StockoutPredictionBatchResult:
    created_count: int
    skipped_count: int
    failed_count: int
    insufficient_data_count: int


class StockoutPredictionService:
    def __init__(
        self,
        db: Session | None = None,
        *,
        repository: StockoutPredictionRepositoryProtocol | None = None,
        calculation_version: str | None = None,
        use_snapshot_incoming: bool | None = None,
        log: logging.Logger | None = None,
    ) -> None:
        if repository is None and db is None:
            raise ValueError("Either db or repository is required.")
        self._repository = repository or StockoutPredictionRepository(db)  # type: ignore[arg-type]
        self._calculation_version = calculation_version or settings.stockout_prediction_calculation_version
        self._use_snapshot_incoming = (
            settings.stockout_prediction_use_snapshot_incoming
            if use_snapshot_incoming is None
            else use_snapshot_incoming
        )
        self._log = log or logger

    def calculate_for_product(
        self,
        *,
        product: Product,
        seller: Seller,
        inventory_snapshot: InventoryHistory | None,
        sales_velocity: SalesVelocity | None,
        as_of_date: date | None = None,
        calculated_at: datetime | None = None,
        calculation_version: str | None = None,
        confirmed_incoming_quantity: int | None = None,
    ) -> StockoutPredictionOutcome:
        timestamp = _ensure_utc(calculated_at or datetime.now(timezone.utc))
        as_of = as_of_date or self.business_date_for_seller(seller, timestamp)
        prediction = self.build_prediction(
            product=product,
            seller=seller,
            inventory_snapshot=inventory_snapshot,
            sales_velocity=sales_velocity,
            as_of_date=as_of,
            calculated_at=timestamp,
            calculation_version=calculation_version or self._calculation_version,
            confirmed_incoming_quantity=confirmed_incoming_quantity,
        )
        saved, created = self._repository.add_idempotent(prediction)
        return StockoutPredictionOutcome(prediction=saved, created=created)

    def calculate_for_batch(
        self,
        *,
        batch_size: int = 500,
        as_of_date: date | None = None,
        calculated_at: datetime | None = None,
        calculation_version: str | None = None,
        seller_id: UUID | None = None,
        product_id: UUID | None = None,
    ) -> StockoutPredictionBatchResult:
        timestamp = _ensure_utc(calculated_at or datetime.now(timezone.utc))
        version = calculation_version or self._calculation_version
        created = 0
        skipped = 0
        failed = 0
        insufficient = 0

        for batch in self._repository.iter_product_batches(
            batch_size=batch_size,
            seller_id=seller_id,
            product_id=product_id,
        ):
            products_by_seller: dict[UUID, tuple[Seller, list[Product]]] = {}
            for product, seller in batch:
                products_by_seller.setdefault(product.seller_id, (seller, []))[1].append(product)

            for batch_seller_id, (seller, products) in products_by_seller.items():
                as_of = as_of_date or self.business_date_for_seller(seller, timestamp)
                product_ids = [item.id for item in products]
                try:
                    inventory_by_product = self._repository.latest_inventory_for_products(
                        seller_id=batch_seller_id,
                        product_ids=product_ids,
                        as_of_date=as_of,
                    )
                    velocity_by_product = self._repository.latest_velocity_for_products(
                        seller_id=batch_seller_id,
                        product_ids=product_ids,
                        as_of_date=as_of,
                    )
                    for product in products:
                        prediction = self.build_prediction(
                            product=product,
                            seller=seller,
                            inventory_snapshot=inventory_by_product.get(product.id),
                            sales_velocity=velocity_by_product.get(product.id),
                            as_of_date=as_of,
                            calculated_at=timestamp,
                            calculation_version=version,
                        )
                        saved, was_created = self._repository.add_idempotent(prediction)
                        if was_created:
                            created += 1
                        else:
                            skipped += 1
                        if saved.prediction_status == StockoutPredictionStatus.INSUFFICIENT_DATA:
                            insufficient += 1
                            self._log.info(
                                "Stockout prediction insufficient data seller_id=%s product_id=%s reason=%s",
                                product.seller_id,
                                product.id,
                                saved.explanation,
                            )
                except Exception:
                    failed += len(products)
                    self._log.exception(
                        "Stockout prediction batch failed seller_id=%s product_count=%s",
                        batch_seller_id,
                        len(products),
                    )
        self._log.info(
            "Stockout prediction completed created=%s skipped=%s failed=%s insufficient=%s version=%s",
            created,
            skipped,
            failed,
            insufficient,
            version,
        )
        return StockoutPredictionBatchResult(
            created_count=created,
            skipped_count=skipped,
            failed_count=failed,
            insufficient_data_count=insufficient,
        )

    def build_prediction(
        self,
        *,
        product: Product,
        seller: Seller,
        inventory_snapshot: InventoryHistory | None,
        sales_velocity: SalesVelocity | None,
        as_of_date: date,
        calculated_at: datetime,
        calculation_version: str,
        confirmed_incoming_quantity: int | None = None,
    ) -> StockoutPrediction:
        quantity_on_hand = int(getattr(inventory_snapshot, "quantity_on_hand", product.stock_quantity or 0))
        quantity_reserved = int(getattr(inventory_snapshot, "quantity_reserved", 0) or 0)
        snapshot_incoming = int(getattr(inventory_snapshot, "quantity_incoming", 0) or 0)
        incoming_used = self._confirmed_incoming_quantity(
            snapshot_incoming=snapshot_incoming,
            confirmed_incoming_quantity=confirmed_incoming_quantity,
        )
        inventory_position = quantity_on_hand + incoming_used - quantity_reserved
        daily_rate = Decimal(str(getattr(sales_velocity, "daily_sales_rate", Decimal("0")) or Decimal("0")))
        velocity_status = getattr(sales_velocity, "data_status", None)

        days_remaining = Decimal("0.0000")
        predicted_date: date | None = None
        status: StockoutPredictionStatus
        explanation: str

        if inventory_position <= 0:
            status = StockoutPredictionStatus.ALREADY_OUT_OF_STOCK
            predicted_date = as_of_date
            explanation = "Inventory position is zero or negative, so the product is already out of stock."
        elif sales_velocity is None:
            status = StockoutPredictionStatus.INSUFFICIENT_DATA
            explanation = "No sales velocity calculation is available for this product."
        elif velocity_status == SalesVelocityDataStatus.INSUFFICIENT:
            status = StockoutPredictionStatus.INSUFFICIENT_DATA
            explanation = "Sales velocity is marked insufficient, so no precise stockout date is calculated."
        elif daily_rate <= 0:
            status = StockoutPredictionStatus.NO_RECENT_DEMAND
            explanation = "Recent completed sales velocity is zero; no finite stockout date is predicted."
        else:
            status = StockoutPredictionStatus.PREDICTED
            days_remaining = (Decimal(inventory_position) / daily_rate).quantize(
                Decimal("0.0001"),
                rounding=ROUND_HALF_UP,
            )
            predicted_date = self.predicted_stockout_date(
                seller=seller,
                as_of_date=as_of_date,
                days_remaining=days_remaining,
            )
            explanation = (
                "Predicted stockout date is the local business date on which inventory reaches zero, "
                "using conservative rounding down for fractional days."
            )

        confidence = self.confidence_score(
            sales_velocity=sales_velocity,
            inventory_snapshot=inventory_snapshot,
            as_of_date=as_of_date,
            incoming_used=incoming_used,
            snapshot_incoming=snapshot_incoming,
            status=status,
        )
        metadata = {
            "formula": "days_remaining = inventory_position / daily_sales_rate",
            "inventory_position_formula": "quantity_on_hand + confirmed_incoming_quantity - reserved_quantity",
            "incoming_policy": (
                "snapshot incoming quantity included"
                if self._use_snapshot_incoming or confirmed_incoming_quantity is not None
                else "snapshot incoming quantity excluded because no confirmed purchase-order model exists"
            ),
            "snapshot_incoming_quantity": snapshot_incoming,
            "inventory_snapshot_date": getattr(inventory_snapshot, "snapshot_date", None).isoformat()
            if getattr(inventory_snapshot, "snapshot_date", None)
            else None,
            "date_policy": "predicted_stockout_date is the seller local business date on which inventory reaches zero",
            "rounding_policy": "fractional days are rounded down when deriving the stockout date",
            "sales_velocity_data_status": getattr(velocity_status, "value", None),
            "sales_velocity_sales_days": getattr(sales_velocity, "sales_days", None),
        }
        return StockoutPrediction(
            seller_id=product.seller_id,
            product_id=product.id,
            inventory_snapshot_id=getattr(inventory_snapshot, "id", None),
            sales_velocity_id=getattr(sales_velocity, "id", None),
            as_of_date=as_of_date,
            quantity_on_hand=quantity_on_hand,
            quantity_reserved=quantity_reserved,
            quantity_incoming=incoming_used,
            inventory_position=inventory_position,
            daily_sales_rate=daily_rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            days_remaining=days_remaining,
            predicted_stockout_date=predicted_date,
            prediction_status=status,
            confidence_score=confidence,
            calculation_version=calculation_version,
            calculated_at=calculated_at,
            explanation=explanation,
            calculation_metadata=metadata,
        )

    def latest_prediction(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        calculation_version: str | None = None,
    ) -> StockoutPrediction | None:
        return self._repository.latest(
            seller_id=seller_id,
            product_id=product_id,
            calculation_version=calculation_version,
        )

    def prediction_history(
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
    ) -> tuple[list[StockoutPrediction], int]:
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

    def _confirmed_incoming_quantity(
        self,
        *,
        snapshot_incoming: int,
        confirmed_incoming_quantity: int | None,
    ) -> int:
        if confirmed_incoming_quantity is not None:
            return max(0, confirmed_incoming_quantity)
        if self._use_snapshot_incoming:
            return max(0, snapshot_incoming)
        return 0

    @staticmethod
    def predicted_stockout_date(*, seller: Seller, as_of_date: date, days_remaining: Decimal) -> date:
        del seller
        whole_days = int(days_remaining.to_integral_value(rounding=ROUND_DOWN))
        return as_of_date + timedelta(days=whole_days)

    @staticmethod
    def confidence_score(
        *,
        sales_velocity: SalesVelocity | None,
        inventory_snapshot: InventoryHistory | None,
        as_of_date: date,
        incoming_used: int,
        snapshot_incoming: int,
        status: StockoutPredictionStatus,
    ) -> Decimal:
        velocity_confidence = Decimal(str(getattr(sales_velocity, "confidence_score", Decimal("0")) or Decimal("0")))
        freshness = _inventory_freshness_score(inventory_snapshot=inventory_snapshot, as_of_date=as_of_date)
        incoming_reliability = Decimal("100") if incoming_used == 0 or incoming_used <= snapshot_incoming else Decimal("70")
        sales_days = Decimal(str(getattr(sales_velocity, "sales_days", 0) or 0))
        sales_days_score = min(sales_days / Decimal("7"), Decimal("1")) * Decimal("100")
        score = (
            velocity_confidence * Decimal("0.60")
            + freshness * Decimal("0.25")
            + incoming_reliability * Decimal("0.10")
            + sales_days_score * Decimal("0.05")
        )
        if status == StockoutPredictionStatus.INSUFFICIENT_DATA:
            score = min(score, Decimal("35"))
        elif status == StockoutPredictionStatus.NO_RECENT_DEMAND:
            score = min(score, Decimal("60"))
        return score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def business_date_for_seller(seller: Seller, captured_at: datetime) -> date:
        return _ensure_utc(captured_at).astimezone(_seller_timezone(seller)).date()


def _inventory_freshness_score(*, inventory_snapshot: InventoryHistory | None, as_of_date: date) -> Decimal:
    if inventory_snapshot is None:
        return Decimal("0")
    age_days = max(0, (as_of_date - inventory_snapshot.snapshot_date).days)
    if age_days <= 1:
        return Decimal("100")
    if age_days <= 3:
        return Decimal("80")
    if age_days <= 7:
        return Decimal("50")
    return Decimal("25")


def _seller_timezone(seller: Seller):
    timezone_name = getattr(seller, "timezone", None) or "UTC"
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return timezone.utc


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
