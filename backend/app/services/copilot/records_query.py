"""Generic seller-scoped read-only records query for the Business Copilot (``query_business_records``).

The model picks an entity, filters, an aggregate and an allowlisted measure; this module
builds the SQLAlchemy query. The seller filter is always applied first and comes from the
authenticated tool context, never from arguments. Aggregation runs in Python with Decimal
so sums are exact and day/week/month buckets follow the seller's timezone on any database.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.inventory_history import InventoryHistory
from app.models.inventory_stock_in import InventoryStockIn
from app.models.product import Product
from app.models.product_price_history import ProductPriceHistory
from app.models.promotion import PromotionPlan
from app.models.recommendation import Recommendation
from app.models.sales_record import SalesRecord, SalesRecordStatus

CALCULATION_VERSION = "records_query_v1"
SELLER_TIMEZONE = ZoneInfo("Asia/Dhaka")
# Rows scanned per query; past this the caller must narrow the date range.
MAX_SCAN_ROWS = 50_000
VALID_SALES_STATUSES = (SalesRecordStatus.COMPLETED, SalesRecordStatus.FULFILLED)

Entity = Literal["sales", "stock_ins", "inventory_history", "price_history", "promotions", "alerts", "recommendations", "competitor_snapshots", "products"]
Aggregate = Literal["list", "count", "sum", "avg", "min", "max"]
GroupBy = Literal["none", "day", "week", "month", "product", "category", "marketplace"]
TIME_GROUPS = {"day", "week", "month"}


@dataclass(frozen=True, slots=True)
class Measure:
    """``value(row)`` returns a Decimal, or None when the row has no observation for it."""

    value: Callable[[Any], Decimal | None]
    unit: str  # "money", "units", "rate", "rating", "count"


@dataclass(frozen=True, slots=True)
class EntitySpec:
    model: Any
    source_table: str
    date_column: Any
    # None: seller scope comes from the joined Product (table has no seller_id).
    seller_column: Any | None
    measures: dict[str, Measure]
    list_fields: tuple[str, ...]
    marketplace_column: Any | None = None
    currency_attr: str | None = None
    extra_filters: tuple[Any, ...] = ()
    assumptions: tuple[str, ...] = ()
    product_join_required: bool = True
    groups: frozenset[str] = field(default_factory=lambda: frozenset({"none", "day", "week", "month", "product", "category"}))


def _dec(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _column(name: str) -> Callable[[Any], Decimal | None]:
    return lambda row: _dec(getattr(row, name))


def _sale_revenue(row: SalesRecord) -> Decimal | None:
    # Same rule as get_revenue_summary's gross revenue: the persisted line total, else units x unit price.
    if row.line_total is not None:
        return Decimal(str(row.line_total))
    if row.unit_price is not None:
        return Decimal(row.quantity_sold) * Decimal(str(row.unit_price))
    return None


def _stock_in_cost(row: InventoryStockIn) -> Decimal | None:
    return None if row.unit_cost is None else Decimal(str(row.unit_cost)) * Decimal(row.quantity)


def _net_units(row: SalesRecord) -> Decimal:
    return Decimal(max(0, row.quantity_sold - (row.returned_units or 0) - (row.refunded_restocked_units or 0)))


ENTITY_SPECS: dict[str, EntitySpec] = {
    "sales": EntitySpec(
        model=SalesRecord,
        source_table="sales_records",
        date_column=SalesRecord.sold_at,
        seller_column=SalesRecord.seller_id,
        measures={
            "revenue": Measure(_sale_revenue, "money"),
            "units": Measure(lambda row: Decimal(row.quantity_sold), "units"),
            "net_units": Measure(_net_units, "units"),
            "unit_price": Measure(_column("unit_price"), "money"),
        },
        list_fields=("sold_at", "status", "quantity_sold", "returned_units", "unit_price", "line_total", "currency"),
        currency_attr="currency",
        extra_filters=(SalesRecord.status.in_(VALID_SALES_STATUSES), SalesRecord.is_test_order.is_(False)),
        assumptions=("Only COMPLETED and FULFILLED non-test orders count, as in get_revenue_summary.", "Revenue is the line total, else units x unit price; rows with neither are counted as missing revenue."),
    ),
    "stock_ins": EntitySpec(
        model=InventoryStockIn,
        source_table="inventory_stock_in",
        date_column=InventoryStockIn.received_at,
        seller_column=InventoryStockIn.seller_id,
        measures={
            "quantity": Measure(lambda row: Decimal(row.quantity), "units"),
            "unit_cost": Measure(_column("unit_cost"), "money"),
            "total_cost": Measure(_stock_in_cost, "money"),
        },
        list_fields=("received_at", "quantity", "unit_cost", "currency", "source_reference", "notes"),
        currency_attr="currency",
        assumptions=("Stock-ins are purchase receipts (inventory received); there is no separate invoice table.",),
    ),
    "inventory_history": EntitySpec(
        model=InventoryHistory,
        source_table="inventory_history",
        date_column=InventoryHistory.captured_at,
        seller_column=InventoryHistory.seller_id,
        measures={name: Measure(_column(name), "units") for name in ("quantity_on_hand", "quantity_available", "quantity_reserved", "quantity_incoming")},
        list_fields=("snapshot_date", "captured_at", "quantity_on_hand", "quantity_available", "quantity_reserved", "quantity_incoming", "source"),
    ),
    "price_history": EntitySpec(
        model=ProductPriceHistory,
        source_table="product_price_history",
        date_column=ProductPriceHistory.changed_at,
        seller_column=ProductPriceHistory.seller_id,
        measures={"new_price": Measure(_column("new_price"), "money"), "old_price": Measure(_column("old_price"), "money")},
        list_fields=("changed_at", "marketplace", "old_price", "new_price", "currency", "source"),
        marketplace_column=ProductPriceHistory.marketplace,
        currency_attr="currency",
        groups=frozenset({"none", "day", "week", "month", "product", "category", "marketplace"}),
        assumptions=("Seller-side price changes only; competitor prices are in competitor_snapshots.",),
    ),
    "promotions": EntitySpec(
        model=PromotionPlan,
        source_table="promotion_plans",
        date_column=PromotionPlan.planned_start_at,
        seller_column=PromotionPlan.seller_id,
        measures={"proposed_discount_rate": Measure(_column("proposed_discount_rate"), "rate"), "proposed_price": Measure(_column("proposed_price"), "money")},
        list_fields=("planned_start_at", "planned_end_at", "status", "promotion_type", "marketplace", "proposed_discount_rate", "proposed_price"),
        marketplace_column=PromotionPlan.marketplace,
        product_join_required=False,
        groups=frozenset({"none", "day", "week", "month", "product", "category", "marketplace"}),
        assumptions=("Internal promotion plans; nothing here was executed on a marketplace.",),
    ),
    "alerts": EntitySpec(
        model=Alert,
        source_table="alerts",
        date_column=Alert.created_at,
        seller_column=Alert.seller_id,
        measures={},
        list_fields=("created_at", "alert_type", "urgency_level", "action_type", "delivery_status", "read_at"),
        product_join_required=False,
    ),
    "recommendations": EntitySpec(
        model=Recommendation,
        source_table="recommendations",
        date_column=Recommendation.created_at,
        seller_column=None,
        measures={
            "suggested_price_min": Measure(_column("suggested_price_min"), "money"),
            "suggested_price_max": Measure(_column("suggested_price_max"), "money"),
            "revenue_opportunity": Measure(_column("revenue_opportunity"), "money"),
        },
        list_fields=("created_at", "action", "confidence", "suggested_price_min", "suggested_price_max", "revenue_opportunity"),
        assumptions=("Recommendations are advisory; none changed a live price or stock.",),
    ),
    "competitor_snapshots": EntitySpec(
        model=CompetitorSnapshot,
        source_table="competitor_snapshots",
        date_column=CompetitorSnapshot.captured_at,
        seller_column=None,
        measures={"price": Measure(_column("price"), "money"), "rating": Measure(_column("rating"), "rating"), "review_count": Measure(_column("review_count"), "count")},
        list_fields=("captured_at", "price", "currency", "rating", "review_count", "stock_status"),
        currency_attr="currency",
    ),
    "products": EntitySpec(
        model=Product,
        source_table="products",
        date_column=Product.created_at,
        seller_column=Product.seller_id,
        measures={"selling_price": Measure(_column("selling_price"), "money"), "cost_price": Measure(_column("cost_price"), "money"), "stock_quantity": Measure(_column("stock_quantity"), "units")},
        list_fields=("title", "sku", "category", "status", "selling_price", "cost_price", "stock_quantity"),
        product_join_required=False,
        assumptions=("Date filters apply to the product's created_at.", "Products have no currency column; money is in the store currency (BDT)."),
    ),
}


class RecordsQueryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity: Entity
    product_id: UUID | None = None
    category: str | None = Field(default=None, max_length=120)
    marketplace: str | None = Field(default=None, max_length=120)
    from_date: date | None = None
    to_date: date | None = None
    aggregate: Aggregate = "list"
    measure: str | None = Field(default=None, max_length=60)
    group_by: GroupBy = "none"
    sort: Literal["desc", "asc"] = "desc"
    limit: int = Field(default=50, ge=1, le=200)

    @model_validator(mode="after")
    def validate_query(self) -> "RecordsQueryArgs":
        spec = ENTITY_SPECS[self.entity]
        if self.from_date and self.to_date and self.from_date > self.to_date:
            raise ValueError("from_date must be on or before to_date")
        if self.aggregate in {"sum", "avg", "min", "max"}:
            if not self.measure:
                raise ValueError(f"aggregate {self.aggregate} needs a measure; allowed for {self.entity}: {sorted(spec.measures) or 'none'}")
        if self.measure and self.measure not in spec.measures:
            raise ValueError(f"measure {self.measure!r} is not allowed for {self.entity}; allowed: {sorted(spec.measures) or 'none'}")
        if self.group_by not in spec.groups:
            raise ValueError(f"group_by {self.group_by!r} is not allowed for {self.entity}; allowed: {sorted(spec.groups)}")
        if self.group_by != "none" and self.aggregate == "list":
            raise ValueError("group_by needs an aggregate (count, sum, avg, min or max)")
        if self.marketplace and spec.marketplace_column is None:
            raise ValueError(f"{self.entity} has no marketplace field")
        return self


def query_business_records(db: Session, *, seller_id: UUID, args: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    query = RecordsQueryArgs.model_validate(args)
    spec = ENTITY_SPECS[query.entity]
    model = spec.model
    joins_product = model is not Product
    statement = select(model, Product) if joins_product else select(model)
    if joins_product:
        join_on = Product.id == model.product_id
        statement = statement.join(Product, join_on) if spec.product_join_required or spec.seller_column is None else statement.outerjoin(Product, join_on)
    # Seller scope first: the table's own column, and the product join for tables without one.
    seller_filters = [spec.seller_column == seller_id] if spec.seller_column is not None else []
    if spec.seller_column is None or spec.product_join_required:
        seller_filters.append(Product.seller_id == seller_id)
    statement = statement.where(*seller_filters, *spec.extra_filters)
    if query.product_id is not None:
        statement = statement.where((Product.id if model is Product else model.product_id) == query.product_id)
    if query.category:
        category_column = model.category if model is PromotionPlan else Product.category
        statement = statement.where(func.lower(category_column) == query.category.strip().lower())
    if query.marketplace:
        statement = statement.where(func.lower(spec.marketplace_column) == query.marketplace.strip().lower())
    if query.from_date:
        statement = statement.where(spec.date_column >= _day_start(query.from_date))
    if query.to_date:
        statement = statement.where(spec.date_column < _day_start(query.to_date + timedelta(days=1)))
    order = spec.date_column.desc() if query.sort == "desc" else spec.date_column.asc()
    statement = statement.order_by(order, model.id).limit(MAX_SCAN_ROWS + 1)

    pairs = [(row[0], row[1] if joins_product else row[0]) for row in db.execute(statement).all()]
    missing_data: list[str] = []
    scan_truncated = len(pairs) > MAX_SCAN_ROWS
    if scan_truncated:
        pairs = pairs[:MAX_SCAN_ROWS]
        missing_data.append(f"SCAN_LIMIT: more than {MAX_SCAN_ROWS} {query.entity} rows matched; narrow the date range for exact totals.")

    currencies = sorted({getattr(row, spec.currency_attr) for row, _ in pairs if spec.currency_attr and getattr(row, spec.currency_attr)})
    measure = spec.measures.get(query.measure or "")
    mixed_money = len(currencies) > 1 and measure is not None and measure.unit == "money" and query.aggregate in {"sum", "avg", "min", "max"}
    if mixed_money:
        missing_data.append(f"MIXED_CURRENCY: rows use {', '.join(currencies)}; no single money figure is given. Filter to one product or currency.")
    if not pairs:
        missing_data.append(f"NO_MATCHING_RECORDS: no {query.entity} recorded for this scope (observed zero, not missing data).")

    if query.aggregate == "list":
        rows = [_list_row(spec, row, product) for row, product in pairs[: query.limit]]
        truncated = len(pairs) > query.limit
    else:
        rows, truncated, rows_without_measure = _aggregate_rows(query, spec, measure, pairs)
        if mixed_money:
            # Money in different currencies cannot be added or compared; report it as unavailable, not a blended number.
            rows = [{**row, "value": None} for row in rows]
        if rows_without_measure:
            missing_data.append(f"MEASURE_UNAVAILABLE: {rows_without_measure} matching row(s) have no {query.measure} value and are excluded from it.")

    return {
        "entity": query.entity,
        "aggregate": query.aggregate,
        "measure": query.measure,
        "group_by": query.group_by,
        "filters": {key: _jsonable(value) for key, value in query.model_dump().items() if key in {"product_id", "category", "marketplace", "from_date", "to_date"} and value is not None},
        "rows": rows,
        "row_count": len(pairs),
        "truncated": truncated or scan_truncated,
        "measure_unit": measure.unit if measure else ("count" if query.aggregate == "count" else None),
        "currency": _currency(query.entity, measure, currencies),
        "source": spec.source_table,
        "freshness": [_freshness(db, spec, seller_id)],
        "calculation_version": CALCULATION_VERSION,
        "assumptions": list(spec.assumptions) + ["Dates are calendar days in Asia/Dhaka."],
        "missing_data": missing_data,
        "evidence": [row["evidence"] for row in rows if "evidence" in row][:50],
    }


def _aggregate_rows(query: RecordsQueryArgs, spec: EntitySpec, measure: Measure | None, pairs: list[tuple[Any, Any]]) -> tuple[list[dict[str, Any]], bool, int]:
    buckets: dict[Any, list[Decimal]] = defaultdict(list)
    counts: dict[Any, int] = defaultdict(int)
    labels: dict[Any, dict[str, Any]] = {}
    rows_without_measure = 0
    for row, product in pairs:
        key, label = _group_key(query.group_by, spec, row, product)
        counts[key] += 1
        labels.setdefault(key, label)
        if measure is not None:
            value = measure.value(row)
            if value is None:
                rows_without_measure += 1
            else:
                buckets[key].append(value)
    if query.group_by == "none":
        counts.setdefault(None, 0)
        labels.setdefault(None, {})
    results = []
    for key in counts:
        values = buckets.get(key, [])
        results.append({**labels[key], "value": _reduce(query.aggregate, values, counts[key]), "row_count": counts[key]})
    if query.group_by in TIME_GROUPS:
        results.sort(key=lambda item: item["period"], reverse=query.sort == "desc")
    else:
        # None (no observation) sorts last either way.
        present = [item for item in results if item["value"] is not None]
        absent = [item for item in results if item["value"] is None]
        present.sort(key=lambda item: Decimal(str(item["value"])), reverse=query.sort == "desc")
        results = present + absent
    return results[: query.limit], len(results) > query.limit, rows_without_measure


def _reduce(aggregate: str, values: list[Decimal], count: int) -> Any:
    if aggregate == "count":
        return count
    if aggregate == "sum":
        # No rows is an observed zero; rows that all lack the measure are unavailable.
        return str(sum(values, Decimal("0"))) if values or count == 0 else None
    if not values:
        return None
    if aggregate == "avg":
        return str((sum(values, Decimal("0")) / len(values)).quantize(Decimal("0.01")))
    return str(min(values) if aggregate == "min" else max(values))


def _group_key(group_by: str, spec: EntitySpec, row: Any, product: Any) -> tuple[Any, dict[str, Any]]:
    if group_by == "none":
        return None, {}
    if group_by in TIME_GROUPS:
        moment = getattr(row, spec.date_column.key)
        local = _local_date(moment)
        if local is None:
            return "unknown", {"period": "unknown"}
        if group_by == "week":
            local = local - timedelta(days=local.weekday())
        elif group_by == "month":
            local = local.replace(day=1)
        period = local.isoformat()[:7] if group_by == "month" else local.isoformat()
        return period, {"period": period}
    if group_by == "product":
        if product is None:
            return "no-product", {"product": None}
        return str(product.id), {"product": _product_ref(product)}
    if group_by == "category":
        category = (row.category if isinstance(row, PromotionPlan) and row.category else getattr(product, "category", None)) or "uncategorized"
        return category, {"category": category}
    marketplace = getattr(row, spec.marketplace_column.key) if spec.marketplace_column is not None else None
    return marketplace or "unknown", {"marketplace": marketplace or "unknown"}


def _list_row(spec: EntitySpec, row: Any, product: Any) -> dict[str, Any]:
    item: dict[str, Any] = {"id": str(row.id)}
    for name in spec.list_fields:
        item[name] = _jsonable(getattr(row, name, None))
    if product is not None and spec.model is not Product:
        item["product"] = _product_ref(product)
    for name, measure in spec.measures.items():
        if name not in item:
            value = measure.value(row)
            item[name] = None if value is None else str(value)
    item["evidence"] = {"source_table": spec.source_table, "source_id": str(row.id), "payload": {}}
    return item


def _currency(entity: str, measure: Measure | None, currencies: list[str]) -> str | list[str] | None:
    if len(currencies) == 1:
        return currencies[0]
    if currencies:
        return currencies
    # Products carry no currency column; their prices are in the store currency.
    return "BDT" if entity == "products" and measure is not None and measure.unit == "money" else None


def _product_ref(product: Any) -> dict[str, Any]:
    return {"id": str(product.id), "title": product.title, "sku": product.sku, "category": product.category}


def _freshness(db: Session, spec: EntitySpec, seller_id: UUID) -> dict[str, Any]:
    statement = select(func.max(spec.date_column))
    if spec.seller_column is not None:
        statement = statement.where(spec.seller_column == seller_id)
    else:
        statement = statement.join(Product, Product.id == spec.model.product_id).where(Product.seller_id == seller_id)
    latest = db.execute(statement).scalar_one_or_none()
    return {"source_table": spec.source_table, "date_field": spec.date_column.key, "latest_record_at": _jsonable(latest)}


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=SELLER_TIMEZONE).astimezone(timezone.utc)


def _local_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return aware.astimezone(SELLER_TIMEZONE).date()
    return value if isinstance(value, date) else None


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "value") and not isinstance(value, (str, int, float, bool)):
        return value.value
    return value
