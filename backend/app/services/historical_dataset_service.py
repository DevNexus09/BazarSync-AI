"""Canonical seller-product-day observations for offline forecasting and evaluation."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Context, Decimal, localcontext
from itertools import groupby
from typing import Iterable
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.inventory_history import InventoryHistory
from app.models.product import Product, ProductMarketplaceListing
from app.models.sales_data_coverage import (
    SalesDataCompletenessStatus,
    SalesDataCoverage,
)
from app.models.sales_record import (
    SalesRecord,
    SalesRecordPriceSource,
    SalesRecordStatus,
)
from app.models.scrape_run import ScrapeRun
from app.repositories.historical_dataset_repository import HistoricalDatasetRepository
from app.services.forecast_source_policy import MIN_MATCH, VALID_COUNTING_STATUSES

BUSINESS_TIMEZONE = ZoneInfo("Asia/Dhaka")
DAY = timedelta(days=1)
COMPETITOR_LOOKBACK = timedelta(days=7)
DATASET_VERSION = "daily-business-v1"
LABEL_BLOCKING_FLAGS = {
    "UNKEYED_SALE",
    "INVALID_SALE",
    "DUPLICATE_SALE",
    "UNRESOLVED_SALES",
    "SYNTHETIC_DEMO_SALES",
}
TRANSACTION_PRICES = {
    SalesRecordPriceSource.TRANSACTION,
    SalesRecordPriceSource.IMPORTED_TRANSACTION,
}


def _utc(value: datetime) -> datetime:
    # SQLite drops timezone offsets. Persisted legacy naive timestamps are UTC.
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def _opening(day: date) -> datetime:
    return datetime.combine(day, time.min, BUSINESS_TIMEZONE).astimezone(timezone.utc)


class CompetitorPriceStatistics(BaseModel):
    marketplace: str
    currency: str
    count: int
    minimum: Decimal
    maximum: Decimal
    mean: Decimal


class DailyBusinessRow(BaseModel):
    seller_id: UUID
    product_id: UUID
    business_date: date
    as_of_timestamp: datetime
    prediction_cutoff: datetime
    observed_units_sold: int | None = None
    valid_order_count: int | None = None
    returned_or_cancelled_units: int | None = None
    effective_selling_price: Decimal | None = None
    currency: str | None = None
    on_hand_stock: int | None = None
    stockout_indicator: bool | None = None
    promotion_indicator: bool | None = None
    category: str | None = None
    brand: str | None = None
    marketplace: str | None = None
    competitor_prices: tuple[CompetitorPriceStatistics, ...] = ()
    sales_coverage_complete: bool = False
    forecast_label_eligible: bool = False
    data_quality_flags: tuple[str, ...] = ()
    source_ids: dict[str, tuple[UUID, ...]]


class HistoricalDatasetQuality(BaseModel):
    row_count: int
    product_count: int
    products_with_observed_sales: int
    history_days: int
    observed_days_by_product: dict[str, int]
    missing_values: dict[str, int]
    stockout_observed_days: int
    inventory_observed_days: int
    invalid_sales_records: int
    negative_quantity_records: int
    duplicate_sales_records: int
    unkeyed_sales_records: int
    category_distribution: dict[str, int]
    unknown_category_product_days: int
    eligible_product_days: int
    longest_eligible_run_by_product: dict[str, int]


class HistoricalDataset(BaseModel):
    version: str = DATASET_VERSION
    business_timezone: str = BUSINESS_TIMEZONE.key
    prediction_feature_fields: tuple[str, ...] = (
        "category",
        "brand",
        "competitor_prices",
    )
    seller_id: UUID
    start_date: date
    end_date: date
    as_of_timestamp: datetime
    rows: tuple[DailyBusinessRow, ...]
    quality: HistoricalDatasetQuality


def _coverage_revision_at(record: SalesDataCoverage) -> datetime:
    return max(
        map(_utc, (record.created_at, record.updated_at, record.last_imported_at))
    )


def _coverage_for_day(
    records: list[SalesDataCoverage],
    opening: datetime,
    closing: datetime,
) -> SalesDataCoverage | None:
    # SalesImportService derives implicit coverage dates in UTC. Require
    # coverage of every UTC calendar date intersecting the Dhaka business day.
    first, last = opening.date(), (closing - timedelta(microseconds=1)).date()
    for _, revision in groupby(records, key=_coverage_revision_at):
        overlapping = [
            record
            for record in revision
            if record.coverage_start_date <= last and record.coverage_end_date >= first
        ]
        if not overlapping:
            continue
        if all(
            record.coverage_start_date <= first
            and record.coverage_end_date >= last
            and _utc(record.last_imported_at) >= closing
            and record.completeness_status == SalesDataCompletenessStatus.COMPLETE
            for record in overlapping
        ):
            return overlapping[0]
        # Conflicting declarations at the latest availability time cannot prove zero.
        return None
    return None


def _currency(value: str | None) -> str | None:
    if value and len(value) == 3 and value.isascii() and value.isalpha():
        return value.upper()
    return None


def _sale_amount(sale: SalesRecord, remaining: int) -> Decimal | None:
    if sale.price_source not in TRANSACTION_PRICES:
        return None
    unit, total = sale.unit_price, sale.line_total
    if any(
        value is not None and (not value.is_finite() or value < 0)
        for value in (unit, total)
    ):
        return None
    if unit is None:
        return total * remaining / sale.quantity_sold if total is not None else None
    if total is not None and unit * sale.quantity_sold != total:
        return None
    return unit * remaining


def _sales_fields(
    records: list[SalesRecord],
    complete: bool,
    flags: set[str],
    issues: Counter[str],
) -> tuple[
    int | None, int | None, int | None, Decimal | None, str | None, list[SalesRecord]
]:
    net_units = removals = valid_lines = priced_units = currency_units = 0
    amount = Decimal(0)
    currencies: set[str] = set()
    included = []
    seen: set[str] = set()
    for sale in records:
        if sale.is_test_order:
            continue
        if not sale.source_reference or not sale.source_reference.strip():
            flags.add("UNKEYED_SALE")
            issues["unkeyed"] += 1
            continue
        if sale.source_reference in seen:
            flags.add("DUPLICATE_SALE")
            issues["duplicate"] += 1
            continue
        seen.add(sale.source_reference)
        quantity = sale.quantity_sold
        returned = sale.returned_units + sale.refunded_restocked_units
        invalid = (
            quantity <= 0
            or min(sale.returned_units, sale.refunded_restocked_units) < 0
            or returned > quantity
            or _utc(sale.created_at) < _utc(sale.sold_at)
        )
        if invalid:
            flags.add("INVALID_SALE")
            issues["invalid"] += 1
            if min(quantity, sale.returned_units, sale.refunded_restocked_units) < 0:
                flags.add("NEGATIVE_QUANTITY")
                issues["negative"] += 1
            continue
        if sale.status == SalesRecordStatus.CANCELLED:
            included.append(sale)
            removals += quantity
            continue
        if sale.status not in VALID_COUNTING_STATUSES:
            if sale.status == SalesRecordStatus.PENDING:
                flags.add("UNRESOLVED_SALES")
            continue
        included.append(sale)
        valid_lines += 1
        remaining = quantity - returned
        net_units += remaining
        removals += returned
        if remaining:
            line_amount, currency = (
                _sale_amount(sale, remaining),
                _currency(sale.currency),
            )
            if currency:
                currencies.add(currency)
                currency_units += remaining
            if line_amount is not None and currency:
                priced_units += remaining
                amount += line_amount
    trustworthy_zero = complete and flags.isdisjoint(LABEL_BLOCKING_FLAGS)
    currency = (
        next(iter(currencies))
        if len(currencies) == 1 and currency_units == net_units
        else None
    )
    if len(currencies) > 1:
        flags.add("MIXED_SALES_CURRENCY")
    if net_units and priced_units != net_units:
        flags.add("MISSING_TRANSACTION_PRICE")
    if valid_lines:
        flags.add("ORDER_ID_UNAVAILABLE")
    return (
        net_units if valid_lines or trustworthy_zero else None,
        0 if not valid_lines and trustworthy_zero else None,
        removals if included or trustworthy_zero else None,
        amount / net_units
        if net_units and priced_units == net_units and currency
        else None,
        currency,
        included,
    )


def _explicit_brand(product: Product) -> str | None:
    values = {
        value.strip()
        for key, value in (product.specifications or {}).items()
        if key.strip().casefold() == "brand"
        and isinstance(value, str)
        and value.strip().casefold() not in {"", "unknown", "n/a", "none", "-"}
    }
    return next(iter(values)) if len(values) == 1 else None


def _listing_marketplace(
    sales: list[SalesRecord],
    listings: list[ProductMarketplaceListing],
) -> tuple[str | None, tuple[UUID, ...]]:
    if not sales:
        return None, ()
    ids: set[UUID] = set()
    markets: set[str] = set()
    for sale in sales:
        sold = _utc(sale.sold_at)
        matches = [
            listing
            for listing in listings
            if listing.marketplace_listing_id == sale.marketplace_listing_id
            and max(_utc(listing.created_at), _utc(listing.updated_at)) <= sold
            and (listing.archived_at is None or sold < _utc(listing.archived_at))
        ]
        if len(matches) != 1:
            return None, ()
        ids.add(matches[0].id)
        markets.add(matches[0].marketplace)
    return (
        (next(iter(markets)), tuple(sorted(ids))) if len(markets) == 1 else (None, ())
    )


@dataclass(frozen=True)
class VerifiedCompetitorPrice:
    marketplace: str
    listing: str
    currency: str
    price: Decimal
    snapshot_id: UUID
    observed_at: datetime
    available_at: datetime


def verified_competitor_prices(
    observations: list[tuple[CompetitorSnapshot, ScrapeRun]],
) -> Iterable[VerifiedCompetitorPrice]:
    for snapshot, run in observations:
        observed_at, price = snapshot.price_observed_at, snapshot.price
        currency, listing = _currency(snapshot.currency), snapshot.external_listing_id
        if (
            observed_at is None
            or run.finished_at is None
            or _utc(observed_at) > _utc(snapshot.captured_at)
            or price is None
            or not price.is_finite()
            or price <= 0
            or not currency
            or snapshot.match_score is None
            or not MIN_MATCH <= snapshot.match_score <= 1
            or not listing
            or not listing.strip()
            or listing == str(snapshot.competitor_id)
        ):
            continue
        yield VerifiedCompetitorPrice(
            marketplace=run.marketplace,
            listing=listing,
            currency=currency,
            price=price,
            snapshot_id=snapshot.id,
            observed_at=_utc(observed_at),
            available_at=max(
                _utc(snapshot.captured_at),
                _utc(snapshot.created_at),
                _utc(run.created_at),
                _utc(run.finished_at),
                _utc(run.updated_at),
            ),
        )


def _competitor_observations_by_day(
    observations: list[tuple[CompetitorSnapshot, ScrapeRun]],
    first_day: date,
    last_day: date,
) -> dict[date, list[tuple[tuple[str, str], str, Decimal, UUID]]]:
    by_day: dict[date, list[tuple[tuple[str, str], str, Decimal, UUID]]] = defaultdict(
        list
    )
    for item in verified_competitor_prices(observations):
        day = max(
            first_day, item.available_at.astimezone(BUSINESS_TIMEZONE).date() + DAY
        )
        expires_at = item.observed_at + COMPETITOR_LOOKBACK
        while day <= last_day and _opening(day) <= expires_at:
            by_day[day].append(
                (
                    (item.marketplace, item.listing),
                    item.currency,
                    item.price,
                    item.snapshot_id,
                )
            )
            day += DAY
    return by_day


def _competitor_prices(
    observations: list[tuple[tuple[str, str], str, Decimal, UUID]],
) -> tuple[tuple[CompetitorPriceStatistics, ...], tuple[UUID, ...]]:
    seen: set[tuple[str, str]] = set()
    prices: dict[tuple[str, str], list[Decimal]] = defaultdict(list)
    sources = []
    for key, currency, price, snapshot_id in observations:
        if key in seen:
            continue
        seen.add(key)
        sources.append(snapshot_id)
        prices[(key[0], currency)].append(price)
    return tuple(
        CompetitorPriceStatistics(
            marketplace=market,
            currency=currency,
            count=len(values),
            minimum=min(values),
            maximum=max(values),
            mean=sum(values, Decimal(0)) / len(values),
        )
        for (market, currency), values in sorted(prices.items())
    ), tuple(sorted(sources))


class HistoricalDatasetService:
    def __init__(self, db: Session, *, authorized_seller_id: UUID) -> None:
        self.repo = HistoricalDatasetRepository(db, authorized_seller_id)

    def build(
        self,
        *,
        start_date: date,
        end_date: date,
        as_of: datetime,
        product_id: UUID | None = None,
    ) -> HistoricalDataset:
        if as_of.utcoffset() is None:
            raise ValueError("as_of must include a timezone offset.")
        as_of = _utc(as_of)
        if not 0 <= (end_date - start_date).days < 366:
            raise ValueError("Select a date range of 1 to 366 business days.")
        closing = _opening(end_date + DAY)
        if closing > as_of:
            raise ValueError("Every requested business day must be closed at as_of.")
        products = [
            p for p in self.repo.products(product_id) if _utc(p.created_at) <= as_of
        ]
        if product_id is not None and not products:
            raise LookupError("Product not found.")
        days = tuple(
            start_date + i * DAY for i in range((end_date - start_date).days + 1)
        )
        issues: Counter[str] = Counter()
        with localcontext(Context(prec=38)):
            rows = tuple(
                row
                for product in products
                for row in self._product_rows(product, days, as_of, issues)
            )
        return HistoricalDataset(
            seller_id=self.repo.seller_id,
            start_date=start_date,
            end_date=end_date,
            as_of_timestamp=as_of,
            rows=rows,
            quality=_validate_and_summarize(
                rows, self.repo.seller_id, products, days, issues
            ),
        )

    def _product_rows(
        self,
        product: Product,
        days: tuple[date, ...],
        as_of: datetime,
        issues: Counter[str],
    ) -> Iterable[DailyBusinessRow]:
        start, end = _opening(days[0]), _opening(days[-1] + DAY)
        sales: dict[date, list[SalesRecord]] = defaultdict(list)
        for sale in self.repo.sales(product.id, start, end, as_of):
            sales[_utc(sale.sold_at).astimezone(BUSINESS_TIMEZONE).date()].append(sale)
        inventory: dict[date, list[InventoryHistory]] = defaultdict(list)
        for observation in self.repo.inventory(product.id, start, end):
            day = _utc(observation.captured_at).astimezone(BUSINESS_TIMEZONE).date()
            if (
                max(_utc(observation.captured_at), _utc(observation.created_at))
                < _opening(day + DAY)
                and observation.quantity_on_hand >= 0
                and observation.quantity_reserved >= 0
                and observation.quantity_available
                == observation.quantity_on_hand - observation.quantity_reserved
            ):
                inventory[day].append(observation)
        coverage = self.repo.coverage(
            product.id, start.date(), (end - timedelta(microseconds=1)).date(), as_of
        )
        coverage.sort(key=_coverage_revision_at, reverse=True)
        listings = self.repo.listings(product.id)
        competitors = self.repo.competitors(
            product.id, start - COMPETITOR_LOOKBACK, _opening(days[-1])
        )
        competitors_by_day = _competitor_observations_by_day(
            competitors, days[0], days[-1]
        )
        for day in days:
            cutoff = _opening(day)
            declared = _coverage_for_day(coverage, cutoff, _opening(day + DAY))
            flags: set[str] = set()
            units, orders, removals, price, currency, included = _sales_fields(
                sales[day],
                declared is not None,
                flags,
                issues,
            )
            if declared is None:
                flags.add("SALES_COVERAGE_UNVERIFIED")
            elif declared.source == "SYNTHETIC_DEMO_SEED":
                flags.add("SYNTHETIC_DEMO_SALES")
            stock = inventory[day]
            stockout = (
                any(item.quantity_available <= 0 for item in stock) if stock else None
            )
            if stockout is None:
                flags.add("STOCKOUT_UNKNOWN")
            elif stockout:
                flags.add("STOCKOUT_CENSORED")
            catalog_known = (
                max(_utc(product.created_at), _utc(product.updated_at)) < cutoff
            )
            category = (
                (product.category or "").strip() or None if catalog_known else None
            )
            brand = _explicit_brand(product) if catalog_known else None
            market, listing_ids = _listing_marketplace(included, listings)
            stats, competitor_ids = _competitor_prices(competitors_by_day.get(day, []))
            yield DailyBusinessRow(
                seller_id=self.repo.seller_id,
                product_id=product.id,
                business_date=day,
                as_of_timestamp=as_of,
                prediction_cutoff=cutoff,
                observed_units_sold=units,
                valid_order_count=orders,
                returned_or_cancelled_units=removals,
                effective_selling_price=price,
                currency=currency,
                marketplace=market,
                on_hand_stock=stock[-1].quantity_on_hand if stock else None,
                stockout_indicator=stockout,
                category=category,
                brand=brand,
                competitor_prices=stats,
                sales_coverage_complete=declared is not None,
                forecast_label_eligible=(
                    units is not None
                    and stockout is False
                    and declared is not None
                    and flags.isdisjoint(LABEL_BLOCKING_FLAGS)
                ),
                data_quality_flags=tuple(sorted(flags)),
                source_ids={
                    "sales_records": tuple(sorted(sale.id for sale in included)),
                    "sales_coverage": (declared.id,) if declared else (),
                    "inventory_history": tuple(sorted(item.id for item in stock)),
                    "competitor_snapshots": competitor_ids,
                    "product_marketplace_listings": listing_ids,
                    "products": (product.id,) if category or brand else (),
                },
            )


def _validate_and_summarize(
    rows: tuple[DailyBusinessRow, ...],
    seller_id: UUID,
    products: list[Product],
    days: tuple[date, ...],
    issues: Counter[str],
) -> HistoricalDatasetQuality:
    expected = ((seller_id, product.id, day) for product in products for day in days)
    if len(rows) != len(products) * len(days):
        raise ValueError("Invalid historical dataset row count.")
    categorized: Counter[str] = Counter()
    missing: Counter[str] = Counter()
    observed = dict.fromkeys((str(p.id) for p in products), 0)
    longest = observed.copy()
    consecutive = observed.copy()
    for row, key in zip(rows, expected, strict=True):
        if (row.seller_id, row.product_id, row.business_date) != key:
            raise ValueError("Unexpected, missing or duplicate historical dataset key.")
        counts = (
            row.observed_units_sold,
            row.valid_order_count,
            row.returned_or_cancelled_units,
        )
        if any(value is not None and value < 0 for value in counts):
            raise ValueError("Unexpected negative historical dataset quantity.")
        product = str(row.product_id)
        observed[product] += int(row.observed_units_sold is not None)
        consecutive[product] = (
            consecutive[product] + 1 if row.forecast_label_eligible else 0
        )
        longest[product] = max(longest[product], consecutive[product])
        if row.category is not None:
            categorized[row.category] += 1
        for field in (
            "observed_units_sold",
            "valid_order_count",
            "returned_or_cancelled_units",
            "effective_selling_price",
            "currency",
            "on_hand_stock",
            "stockout_indicator",
            "promotion_indicator",
            "category",
            "brand",
            "marketplace",
            "competitor_prices",
        ):
            value = getattr(row, field)
            missing[field] += int(value is None or value == ())
    return HistoricalDatasetQuality(
        row_count=len(rows),
        product_count=len(products),
        products_with_observed_sales=sum(count > 0 for count in observed.values()),
        history_days=len(days),
        observed_days_by_product=observed,
        missing_values=dict(missing),
        stockout_observed_days=sum(row.stockout_indicator is True for row in rows),
        inventory_observed_days=sum(row.stockout_indicator is not None for row in rows),
        invalid_sales_records=issues["invalid"],
        negative_quantity_records=issues["negative"],
        duplicate_sales_records=issues["duplicate"],
        unkeyed_sales_records=issues["unkeyed"],
        category_distribution=dict(categorized),
        unknown_category_product_days=missing["category"],
        eligible_product_days=sum(row.forecast_label_eligible for row in rows),
        longest_eligible_run_by_product=longest,
    )
