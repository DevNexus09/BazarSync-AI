from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import logging
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.product import Product
from app.models.sales_velocity import SalesVelocity, SalesVelocityDataStatus
from app.models.seller import Seller
from app.repositories.sales_velocity_repository import SalesVelocityRepository

logger = logging.getLogger(__name__)

STOCKOUT_AWARE_VERSION = "v2"
STOCKOUT_LIMITED_SHARE = Decimal("0.80")


class SalesVelocityRepositoryProtocol(Protocol):
    def iter_product_batches(
        self,
        *,
        batch_size: int,
        seller_id: UUID | None = None,
        product_id: UUID | None = None,
    ): ...

    def aggregate_sales(
        self,
        *,
        seller_id: UUID,
        product_ids: list[UUID],
        window_start: datetime,
        window_end: datetime,
    ) -> dict[UUID, dict[str, int]]: ...

    def add_idempotent(self, record: SalesVelocity) -> tuple[SalesVelocity, bool]: ...

    def daily_available_stock(
        self,
        *,
        seller_id: UUID,
        product_ids: list[UUID],
        start_date: date,
        end_date: date,
    ) -> dict[UUID, dict[date, int]]: ...

    def latest(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        window_days: int | None,
        calculation_version: str | None,
    ) -> SalesVelocity | None: ...

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
    ) -> tuple[list[SalesVelocity], int]: ...

    def get_for_date(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        as_of_date: date,
        window_days: int,
        calculation_version: str,
    ) -> SalesVelocity | None: ...


@dataclass(frozen=True)
class SalesVelocityCalculation:
    product_id: UUID
    seller_id: UUID
    as_of_date: date
    window_days: int
    observed_days: int
    gross_units_sold: int
    returned_units: int
    net_units_sold: int
    daily_sales_rate: Decimal
    sales_days: int
    confidence_score: Decimal
    data_status: SalesVelocityDataStatus
    calculation_version: str
    metadata: dict[str, object]


@dataclass(frozen=True)
class SalesVelocityOutcome:
    record: SalesVelocity
    created: bool


@dataclass(frozen=True)
class SalesVelocityBatchResult:
    created_count: int
    skipped_count: int
    failed_count: int


class SalesVelocityService:
    def __init__(
        self,
        db: Session | None = None,
        *,
        repository: SalesVelocityRepositoryProtocol | None = None,
        default_window_days: int | None = None,
        calculation_version: str | None = None,
        log: logging.Logger | None = None,
    ) -> None:
        if repository is None and db is None:
            raise ValueError("Either db or repository is required.")
        self._repository = repository or SalesVelocityRepository(db)  # type: ignore[arg-type]
        self._default_window_days = default_window_days or settings.sales_velocity_default_window_days
        self._calculation_version = calculation_version or settings.sales_velocity_calculation_version
        self._log = log or logger
        if self._default_window_days <= 0:
            raise ValueError("Sales velocity window must be positive.")

    def calculate_for_product(
        self,
        *,
        product: Product,
        seller: Seller | None = None,
        as_of_date: date | None = None,
        window_days: int | None = None,
        calculation_version: str | None = None,
        calculated_at: datetime | None = None,
    ) -> SalesVelocityOutcome:
        calculation = self.measure_for_product(
            product=product, seller=seller, as_of_date=as_of_date, window_days=window_days,
            calculation_version=calculation_version, calculated_at=calculated_at,
        )
        return self._save_calculation(calculation, calculated_at=calculated_at)

    def measure_for_product(
        self,
        *,
        product: Product,
        seller: Seller | None = None,
        as_of_date: date | None = None,
        window_days: int | None = None,
        calculation_version: str | None = None,
        calculated_at: datetime | None = None,
    ) -> SalesVelocityCalculation:
        seller_obj = seller or product.seller
        window = window_days or self._default_window_days
        version = calculation_version or self._calculation_version
        as_of = as_of_date or self.business_date_for_seller(seller_obj, calculated_at or datetime.now(timezone.utc))
        window_start, window_end = self.window_bounds(seller_obj, as_of, window)
        aggregate = self._repository.aggregate_sales(
            seller_id=product.seller_id,
            product_ids=[product.id],
            window_start=window_start,
            window_end=window_end,
        ).get(product.id, {})
        stock = self._stock_by_day(product.seller_id, [product.id], as_of, window, version).get(product.id, {})
        return self.calculate_from_aggregate(
            product=product,
            seller=seller_obj,
            as_of_date=as_of,
            window_days=window,
            aggregate=aggregate,
            calculation_version=version,
            stock_by_day=stock,
        )

    def calculate_for_batch(
        self,
        *,
        batch_size: int = 500,
        as_of_date: date | None = None,
        window_days: int | None = None,
        calculation_version: str | None = None,
        calculated_at: datetime | None = None,
        seller_id: UUID | None = None,
        product_id: UUID | None = None,
    ) -> SalesVelocityBatchResult:
        created = 0
        skipped = 0
        failed = 0
        window = window_days or self._default_window_days
        version = calculation_version or self._calculation_version
        timestamp = _ensure_utc(calculated_at or datetime.now(timezone.utc))

        for batch in self._repository.iter_product_batches(
            batch_size=batch_size,
            seller_id=seller_id,
            product_id=product_id,
        ):
            products_by_seller: dict[UUID, tuple[Seller, list[Product]]] = {}
            for product, seller in batch:
                products_by_seller.setdefault(product.seller_id, (seller, []) )[1].append(product)

            for batch_seller_id, (seller, products) in products_by_seller.items():
                try:
                    as_of = as_of_date or self.business_date_for_seller(seller, timestamp)
                    window_start, window_end = self.window_bounds(seller, as_of, window)
                    aggregates = self._repository.aggregate_sales(
                        seller_id=batch_seller_id,
                        product_ids=[item.id for item in products],
                        window_start=window_start,
                        window_end=window_end,
                    )
                    stock = self._stock_by_day(batch_seller_id, [item.id for item in products], as_of, window, version)
                    for product in products:
                        calculation = self.calculate_from_aggregate(
                            product=product,
                            seller=seller,
                            as_of_date=as_of,
                            window_days=window,
                            aggregate=aggregates.get(product.id, {}),
                            calculation_version=version,
                            stock_by_day=stock.get(product.id, {}),
                        )
                        outcome = self._save_calculation(calculation, calculated_at=timestamp)
                        if outcome.created:
                            created += 1
                        else:
                            skipped += 1
                except Exception:
                    failed += len(products)
                    self._log.exception(
                        "Sales velocity batch failed seller_id=%s product_count=%s",
                        batch_seller_id,
                        len(products),
                    )
        self._log.info(
            "Sales velocity calculation completed created=%s skipped=%s failed=%s window_days=%s version=%s",
            created,
            skipped,
            failed,
            window,
            version,
        )
        return SalesVelocityBatchResult(created_count=created, skipped_count=skipped, failed_count=failed)

    def calculate_from_aggregate(
        self,
        *,
        product: Product,
        seller: Seller,
        as_of_date: date,
        window_days: int,
        aggregate: dict[str, int],
        calculation_version: str,
        stock_by_day: dict[date, int] | None = None,
    ) -> SalesVelocityCalculation:
        observed_days = self.observed_days(product, seller, as_of_date, window_days)
        stockout_aware = calculation_version == STOCKOUT_AWARE_VERSION
        stockout_days, covered_days = (
            self.stockout_days(stock_by_day or {}, as_of_date, observed_days) if stockout_aware else (0, 0)
        )
        effective_days = max(1, observed_days - stockout_days)
        gross = int(aggregate.get("gross_units_sold", 0))
        returned = int(aggregate.get("returned_units", 0))
        net = max(0, int(aggregate.get("net_units_sold", 0)))
        valid_records = int(aggregate.get("valid_sales_records", 0))
        sales_days = int(aggregate.get("sales_days", 0))
        daily_rate = (Decimal(net) / Decimal(effective_days)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        data_status = self.data_status(valid_records=valid_records, observed_days=observed_days, window_days=window_days)
        mostly_stocked_out = Decimal(stockout_days) > STOCKOUT_LIMITED_SHARE * Decimal(observed_days)
        if mostly_stocked_out and data_status == SalesVelocityDataStatus.SUFFICIENT:
            data_status = SalesVelocityDataStatus.LIMITED
        confidence = self.confidence_score(
            valid_records=valid_records,
            observed_days=observed_days,
            window_days=window_days,
            data_status=data_status,
        )
        metadata = {
            "formula": "daily_sales_rate = net_units_sold / effective_window_days",
            "effective_window_days": effective_days,
            "valid_statuses": ["COMPLETED", "FULFILLED"],
            "excluded_statuses": ["PENDING", "CANCELLED", "FAILED_PAYMENT"],
            "test_orders_excluded": True,
            "net_units_definition": "quantity_sold - returned_units - refunded_restocked_units, capped at zero per sale record",
            "valid_sales_records": valid_records,
            "confidence_formula": "50*observed_window_coverage + 30*valid_record_coverage + 20*sales_data_availability",
        }
        if stockout_aware:
            metadata["formula"] = "daily_sales_rate = net_units_sold / (observed_days - stockout_days)"
            metadata["stockout_days"] = stockout_days
            metadata["stockout_day_definition"] = (
                "quantity_available <= 0 in both the previous day's and the day's inventory_history snapshot"
            )
            metadata["stock_history_coverage"] = str(
                (Decimal(covered_days) / Decimal(observed_days)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            )
            metadata["missing_stock_history_assumption"] = "days without history are kept in the window (unknown, not in stock)"
            if mostly_stocked_out:
                metadata["limited_reason"] = "stocked_out_more_than_80_percent_of_window"
        if valid_records == 0:
            metadata["insufficient_data_reason"] = "no_valid_completed_or_fulfilled_sales_records"
        return SalesVelocityCalculation(
            product_id=product.id,
            seller_id=product.seller_id,
            as_of_date=as_of_date,
            window_days=window_days,
            observed_days=observed_days,
            gross_units_sold=gross,
            returned_units=returned,
            net_units_sold=net,
            daily_sales_rate=daily_rate,
            sales_days=sales_days,
            confidence_score=confidence,
            data_status=data_status,
            calculation_version=calculation_version,
            metadata=metadata,
        )

    def latest_velocity(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        window_days: int | None = None,
        calculation_version: str | None = None,
    ) -> SalesVelocity | None:
        return self._repository.latest(
            seller_id=seller_id,
            product_id=product_id,
            window_days=window_days,
            calculation_version=calculation_version,
        )

    def velocity_history(
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
        return self._repository.history(
            seller_id=seller_id,
            product_id=product_id,
            from_date=from_date,
            to_date=to_date,
            window_days=window_days,
            calculation_version=calculation_version,
            order=order,
            limit=limit,
            offset=offset,
        )

    def velocity_for_date(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        as_of_date: date,
        window_days: int | None = None,
        calculation_version: str | None = None,
    ) -> SalesVelocity | None:
        return self._repository.get_for_date(
            seller_id=seller_id,
            product_id=product_id,
            as_of_date=as_of_date,
            window_days=window_days or self._default_window_days,
            calculation_version=calculation_version or self._calculation_version,
        )

    def explain_inputs(self, record: SalesVelocity) -> dict[str, object]:
        return {
            "as_of_date": record.as_of_date.isoformat(),
            "window_days": record.window_days,
            "observed_days": record.observed_days,
            "gross_units_sold": record.gross_units_sold,
            "returned_units": record.returned_units,
            "net_units_sold": record.net_units_sold,
            "daily_sales_rate": str(record.daily_sales_rate),
            "data_status": record.data_status.value,
            "confidence_score": str(record.confidence_score),
            "calculation_version": record.calculation_version,
            "metadata": record.calculation_metadata or {},
        }

    def _save_calculation(
        self,
        calculation: SalesVelocityCalculation,
        *,
        calculated_at: datetime | None,
    ) -> SalesVelocityOutcome:
        record = SalesVelocity(
            seller_id=calculation.seller_id,
            product_id=calculation.product_id,
            as_of_date=calculation.as_of_date,
            window_days=calculation.window_days,
            observed_days=calculation.observed_days,
            gross_units_sold=calculation.gross_units_sold,
            returned_units=calculation.returned_units,
            net_units_sold=calculation.net_units_sold,
            daily_sales_rate=calculation.daily_sales_rate,
            sales_days=calculation.sales_days,
            confidence_score=calculation.confidence_score,
            data_status=calculation.data_status,
            calculation_version=calculation.calculation_version,
            calculated_at=_ensure_utc(calculated_at or datetime.now(timezone.utc)),
            calculation_metadata=calculation.metadata,
        )
        saved, created = self._repository.add_idempotent(record)
        return SalesVelocityOutcome(record=saved, created=created)

    @staticmethod
    def data_status(*, valid_records: int, observed_days: int, window_days: int) -> SalesVelocityDataStatus:
        if valid_records == 0:
            return SalesVelocityDataStatus.INSUFFICIENT
        if observed_days < min(window_days, 7):
            return SalesVelocityDataStatus.LIMITED
        return SalesVelocityDataStatus.SUFFICIENT

    @staticmethod
    def confidence_score(
        *,
        valid_records: int,
        observed_days: int,
        window_days: int,
        data_status: SalesVelocityDataStatus,
    ) -> Decimal:
        observed_component = min(Decimal(observed_days) / Decimal(window_days), Decimal("1")) * Decimal("50")
        record_component = min(Decimal(valid_records) / Decimal("10"), Decimal("1")) * Decimal("30")
        availability_component = Decimal("20") if valid_records > 0 else Decimal("0")
        score = observed_component + record_component + availability_component
        if data_status == SalesVelocityDataStatus.INSUFFICIENT:
            score = min(score, Decimal("20"))
        elif data_status == SalesVelocityDataStatus.LIMITED:
            score = min(score, Decimal("65"))
        return score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def observed_days(product: Product, seller: Seller, as_of_date: date, window_days: int) -> int:
        created_at = getattr(product, "created_at", None)
        if created_at is None:
            return window_days
        product_date = _ensure_utc(created_at).astimezone(_seller_timezone(seller)).date()
        product_age_days = max(1, (as_of_date - product_date).days + 1)
        return max(1, min(window_days, product_age_days))

    @staticmethod
    def stockout_days(stock_by_day: dict[date, int], as_of_date: date, observed_days: int) -> tuple[int, int]:
        """Return (stocked-out days, days with history) over the last observed_days ending at as_of_date.

        A day is stocked out for the whole day only when it starts (previous day's snapshot) and ends
        (its own snapshot) with nothing available. A missing snapshot means unknown, so the day is kept.
        """
        stocked_out = 0
        covered = 0
        for offset in range(observed_days):
            day = as_of_date - timedelta(days=offset)
            end = stock_by_day.get(day)
            if end is None:
                continue
            covered += 1
            start = stock_by_day.get(day - timedelta(days=1))
            if start is not None and start <= 0 and end <= 0:
                stocked_out += 1
        return stocked_out, covered

    def _stock_by_day(
        self, seller_id: UUID, product_ids: list[UUID], as_of_date: date, window_days: int, version: str
    ) -> dict[UUID, dict[date, int]]:
        if version != STOCKOUT_AWARE_VERSION:
            return {}
        return self._repository.daily_available_stock(
            seller_id=seller_id,
            product_ids=product_ids,
            # One extra day so the first window day has a start-of-day reading.
            start_date=as_of_date - timedelta(days=window_days),
            end_date=as_of_date,
        )

    @staticmethod
    def business_date_for_seller(seller: Seller, captured_at: datetime) -> date:
        return _ensure_utc(captured_at).astimezone(_seller_timezone(seller)).date()

    @staticmethod
    def window_bounds(seller: Seller, as_of_date: date, window_days: int) -> tuple[datetime, datetime]:
        tz = _seller_timezone(seller)
        start_date = as_of_date - timedelta(days=window_days - 1)
        local_start = datetime.combine(start_date, time.min, tzinfo=tz)
        local_end = datetime.combine(as_of_date + timedelta(days=1), time.min, tzinfo=tz)
        return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)


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
