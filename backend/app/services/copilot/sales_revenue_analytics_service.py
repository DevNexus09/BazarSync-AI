from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from app.models.product import Product, ProductMarketplaceListing
from app.models.sales_data_coverage import SalesDataCompletenessStatus, SalesDataCoverage
from app.models.sales_record import SalesRecord, SalesRecordPriceSource, SalesRecordStatus


VALID_SALES_STATUSES = (SalesRecordStatus.COMPLETED, SalesRecordStatus.FULFILLED)
DEFAULT_SELLER_TIMEZONE = "Asia/Dhaka"


def is_valid_sales_record(sale: SalesRecord) -> bool:
    return sale.status in VALID_SALES_STATUSES and not bool(getattr(sale, "is_test_order", False))


def latest_recorded_sale_date(db: Session, *, seller_id: UUID, product_id: UUID | None = None, seller_timezone: str = DEFAULT_SELLER_TIMEZONE) -> str | None:
    """The seller's most recent valid (completed/fulfilled, non-test) sale day in the seller calendar, or None.

    An empty period is only proof of "no sales" next to this date: it shows the sales history exists.
    """
    statement = select(func.max(SalesRecord.sold_at)).where(
        SalesRecord.seller_id == seller_id,
        SalesRecord.status.in_(VALID_SALES_STATUSES),
        SalesRecord.is_test_order.is_(False),
    )
    if product_id is not None:
        statement = statement.where(SalesRecord.product_id == product_id)
    latest = db.execute(statement).scalar_one_or_none()
    if latest is None:
        return None
    aware = latest if latest.tzinfo else latest.replace(tzinfo=timezone.utc)
    return aware.astimezone(ZoneInfo(seller_timezone)).date().isoformat()


@dataclass(frozen=True, slots=True)
class SalesLine:
    sale: SalesRecord
    product: Product
    gross_units: int
    net_units: int
    unit_price: Decimal | None
    revenue_is_estimated: bool
    line_total: Decimal | None = None
    revenue_estimation_method: str = "TRANSACTION"
    price_source: str = "TRANSACTION"

    @property
    def gross_revenue(self) -> Decimal:
        if self.line_total is not None:
            return self.line_total
        return Decimal(self.gross_units) * (self.unit_price or Decimal("0"))

    @property
    def net_revenue(self) -> Decimal:
        return Decimal(self.net_units) * (self.unit_price or Decimal("0"))


class SalesRevenueAnalyticsService:
    def __init__(self, db: Session, *, seller_timezone: str = DEFAULT_SELLER_TIMEZONE) -> None:
        self._db = db
        self._seller_timezone = ZoneInfo(seller_timezone)

    def get_revenue_summary(
        self,
        *,
        seller_id: UUID,
        from_date: date,
        to_date: date,
        product_id: UUID | None = None,
        category: str | None = None,
        marketplace: str | None = None,
        compare_to_previous_period: bool = True,
        top_limit: int = 5,
    ) -> tuple[dict[str, Any], list[str]]:
        lines = self._sales_lines(**_sales_line_args(
            seller_id=seller_id,
            from_date=from_date,
            to_date=to_date,
            product_id=product_id,
            category=category,
            marketplace=marketplace,
        ))
        summary = self._summarize_lines(lines)
        coverage = self._sales_coverage(
            seller_id=seller_id,
            from_date=from_date,
            to_date=to_date,
            product_id=product_id,
            marketplace=marketplace,
        )
        previous = None
        change = None
        pct = None
        if compare_to_previous_period:
            days = (to_date - from_date).days + 1
            previous_to = from_date - timedelta(days=1)
            previous_from = previous_to - timedelta(days=days - 1)
            previous = self._summarize_lines(
                self._sales_lines(**_sales_line_args(
                    seller_id=seller_id,
                    from_date=previous_from,
                    to_date=previous_to,
                    product_id=product_id,
                    category=category,
                    marketplace=marketplace,
                ))
            )
            change = summary["gross_revenue"] - previous["gross_revenue"]
            pct = None if previous["gross_revenue"] == 0 else change / previous["gross_revenue"] * Decimal("100")
        top_products = self._top_products(lines, limit=top_limit)
        previous_by_product = {}
        if compare_to_previous_period and previous is not None:
            previous_by_product = {
                item["product"]["id"]: item["gross_revenue"]
                for item in self._top_products(
                    self._sales_lines(**_sales_line_args(
                        seller_id=seller_id,
                        from_date=from_date - timedelta(days=(to_date - from_date).days + 1),
                        to_date=from_date - timedelta(days=1),
                        product_id=product_id,
                        category=category,
                        marketplace=marketplace,
                    )),
                    limit=100,
                )
            }
        decline = [
            {
                **item,
                "previous_gross_revenue": previous_by_product.get(item["product"]["id"], Decimal("0")),
                "revenue_delta": item["gross_revenue"] - previous_by_product.get(item["product"]["id"], Decimal("0")),
            }
            for item in top_products
            if previous_by_product and item["gross_revenue"] < previous_by_product.get(item["product"]["id"], Decimal("0"))
        ]
        missing = self._missing_notes(lines=lines, marketplace=marketplace, coverage=coverage)
        return {
            "gross_revenue": summary["gross_revenue"],
            "net_revenue": summary["net_revenue"],
            "units_sold": summary["units_sold"],
            "order_count": summary["order_count"],
            "average_order_value": summary["average_order_value"],
            "revenue_is_estimated": summary["revenue_is_estimated"],
            "revenue_estimation_method": summary["revenue_estimation_method"],
            "confidence": _confidence(summary=summary, coverage=coverage),
            "missing_data": _missing_codes(lines=lines, coverage=coverage),
            "previous_period_revenue": previous["gross_revenue"] if previous else None,
            "revenue_change": change,
            "percentage_change": pct,
            "top_products_by_revenue": top_products,
            "products_with_revenue_decline": decline,
            "data_completeness": self._data_completeness(lines),
            "sales_coverage": coverage,
            "latest_recorded_sale_date": self._latest_sale_date(seller_id=seller_id, product_id=product_id),
            "filters_used": _filters(from_date=from_date, to_date=to_date, product_id=product_id, category=category, marketplace=marketplace),
            "evidence": self._evidence(lines, default_source="sales_records"),
        }, missing

    def get_sales_trends(
        self,
        *,
        seller_id: UUID,
        from_date: date,
        to_date: date,
        granularity: str,
        product_id: UUID | None = None,
        category: str | None = None,
        marketplace: str | None = None,
    ) -> tuple[dict[str, Any], list[str]]:
        lines = self._sales_lines(**_sales_line_args(seller_id=seller_id, from_date=from_date, to_date=to_date, product_id=product_id, category=category, marketplace=marketplace))
        coverage = self._sales_coverage(seller_id=seller_id, from_date=from_date, to_date=to_date, product_id=product_id, marketplace=marketplace)
        buckets: dict[str, dict[str, Any]] = defaultdict(lambda: {"gross_revenue": Decimal("0"), "units_sold": 0, "order_count": 0})
        for line in lines:
            key = self._bucket_key(line.sale.sold_at, granularity)
            buckets[key]["gross_revenue"] += line.gross_revenue
            buckets[key]["units_sold"] += line.net_units
            buckets[key]["order_count"] += 1
        series = [{"period": key, **value} for key, value in sorted(buckets.items())]
        direction = _trend_direction([item["gross_revenue"] for item in series])
        product_totals = self._product_period_deltas(lines, granularity=granularity)
        missing = self._missing_notes(lines=lines, marketplace=marketplace, coverage=coverage)
        return {
            "time_series": series,
            "trend_direction": direction,
            "top_increases": sorted(product_totals, key=lambda item: item["delta"], reverse=True)[:5],
            "top_decreases": sorted(product_totals, key=lambda item: item["delta"])[:5],
            "latest_recorded_sale_date": self._latest_sale_date(seller_id=seller_id, product_id=product_id),
            "filters_used": _filters(from_date=from_date, to_date=to_date, product_id=product_id, category=category, marketplace=marketplace),
            "sales_coverage": coverage,
            "evidence": self._evidence(lines, default_source="sales_records"),
        }, missing

    def get_top_products_by_revenue(
        self,
        *,
        seller_id: UUID,
        from_date: date,
        to_date: date,
        limit: int,
        category: str | None = None,
        marketplace: str | None = None,
    ) -> tuple[dict[str, Any], list[str]]:
        lines = self._sales_lines(**_sales_line_args(seller_id=seller_id, from_date=from_date, to_date=to_date, category=category, marketplace=marketplace))
        coverage = self._sales_coverage(seller_id=seller_id, from_date=from_date, to_date=to_date, product_id=None, marketplace=marketplace)
        return {
            "products": self._top_products(lines, limit=limit),
            "filters_used": _filters(from_date=from_date, to_date=to_date, category=category, marketplace=marketplace),
            "sales_coverage": coverage,
            "evidence": self._evidence(lines, default_source="sales_records"),
        }, self._missing_notes(lines=lines, marketplace=marketplace, coverage=coverage)

    def get_products_with_no_sales(
        self,
        *,
        seller_id: UUID,
        since_date: date | None,
        category: str | None = None,
        marketplace: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[dict[str, Any], list[str]]:
        statement = select(Product).where(Product.seller_id == seller_id)
        if category:
            statement = statement.where(Product.category == category)
        if marketplace:
            statement = statement.where(_listing_exists(seller_id=seller_id, marketplace=marketplace))
        products = self._db.execute(statement.order_by(Product.created_at.desc(), Product.id.desc())).scalars().all()
        sold_ids = {
            line.product.id
            for line in self._sales_lines(**_sales_line_args(
                seller_id=seller_id,
                from_date=since_date or date(1970, 1, 1),
                to_date=date.today(),
                category=category,
                marketplace=marketplace,
            ))
        }
        period_from = since_date or date(1970, 1, 1)
        period_to = date.today()
        items = []
        has_incomplete_coverage = False
        for product in products:
            if product.id in sold_ids:
                continue
            coverage = self._sales_coverage(
                seller_id=seller_id,
                from_date=period_from,
                to_date=period_to,
                product_id=product.id,
                marketplace=marketplace,
            )
            coverage_complete = coverage["completeness_status"] == SalesDataCompletenessStatus.COMPLETE.value
            has_incomplete_coverage = has_incomplete_coverage or not coverage_complete
            items.append({
                "product": _product_ref(product),
                "stock": product.stock_quantity,
                "product_age_days": (datetime.now(timezone.utc) - _aware(product.created_at)).days if product.created_at else None,
                "inventory_age": None,
                "sales_status": "NO_SALES" if coverage_complete else "NO_VALID_IMPORTED_SALES_FOUND",
                "warning": None if coverage_complete else "Sales completeness is unknown or partial.",
                "sales_coverage": coverage,
                "evidence": _evidence("products", product.id),
            })
        missing = ["Sales completeness is unknown or partial. No valid imported sales found is not guaranteed zero marketplace sales."] if has_incomplete_coverage else []
        total = len(items)
        return {
            "products": items[offset : offset + limit],
            "pagination": {"total": total, "limit": limit, "offset": offset, "has_next": offset + limit < total},
            "warning": missing[0] if missing else None,
            "filters_used": _filters(from_date=since_date, to_date=None, category=category, marketplace=marketplace),
            "evidence": [_evidence("products", "seller_scope"), _evidence("sales_records", "seller_scope")],
        }, missing

    def _sales_lines(
        self,
        *,
        seller_id: UUID,
        from_date: date,
        to_date: date,
        product_id: UUID | None = None,
        category: str | None = None,
        marketplace: str | None = None,
    ) -> list[SalesLine]:
        start, end = _date_bounds(from_date, to_date, self._seller_timezone)
        statement = (
            select(SalesRecord)
            .options(joinedload(SalesRecord.product))
            .join(Product, Product.id == SalesRecord.product_id)
            .where(
                SalesRecord.seller_id == seller_id,
                Product.seller_id == seller_id,
                SalesRecord.status.in_(VALID_SALES_STATUSES),
                SalesRecord.is_test_order.is_(False),
                SalesRecord.sold_at >= start,
                SalesRecord.sold_at <= end,
            )
        )
        if product_id is not None:
            statement = statement.where(SalesRecord.product_id == product_id)
        if category:
            statement = statement.where(Product.category == category)
        if marketplace:
            statement = statement.where(_listing_exists(seller_id=seller_id, marketplace=marketplace))
        rows = self._db.execute(statement.order_by(SalesRecord.sold_at.asc(), SalesRecord.id.asc())).scalars().all()
        return [self._line(row) for row in rows]

    def _line(self, sale: SalesRecord) -> SalesLine:
        product = sale.product
        unit_price, line_total, estimated, method, price_source = _revenue_values_for_sale(sale, product)
        returns = int(sale.returned_units or 0) + int(sale.refunded_restocked_units or 0)
        return SalesLine(
            sale=sale,
            product=product,
            gross_units=int(sale.quantity_sold or 0),
            net_units=max(0, int(sale.quantity_sold or 0) - returns),
            unit_price=unit_price,
            revenue_is_estimated=estimated,
            line_total=line_total,
            revenue_estimation_method=method,
            price_source=price_source,
        )

    def _summarize_lines(self, lines: list[SalesLine]) -> dict[str, Any]:
        gross = sum((line.gross_revenue for line in lines), Decimal("0"))
        net = sum((line.net_revenue for line in lines), Decimal("0"))
        orders = len(lines)
        return {
            "gross_revenue": gross,
            "net_revenue": net,
            "units_sold": sum(line.net_units for line in lines),
            "order_count": orders,
            "average_order_value": None if orders == 0 else gross / Decimal(orders),
            "revenue_is_estimated": any(line.revenue_is_estimated for line in lines),
            "revenue_estimation_method": _revenue_estimation_method(lines),
        }

    def _top_products(self, lines: list[SalesLine], *, limit: int) -> list[dict[str, Any]]:
        grouped: dict[UUID, dict[str, Any]] = {}
        for line in lines:
            row = grouped.setdefault(
                line.product.id,
                {"product": _product_ref(line.product), "gross_revenue": Decimal("0"), "net_revenue": Decimal("0"), "units_sold": 0, "order_count": 0, "revenue_is_estimated": False, "evidence": []},
            )
            row["gross_revenue"] += line.gross_revenue
            row["net_revenue"] += line.net_revenue
            row["units_sold"] += line.net_units
            row["order_count"] += 1
            row["revenue_is_estimated"] = row["revenue_is_estimated"] or line.revenue_is_estimated
            row["revenue_estimation_method"] = _revenue_estimation_method([line])
            row["evidence"].append(_evidence("sales_records", line.sale.id))
        return sorted(grouped.values(), key=lambda item: item["gross_revenue"], reverse=True)[:limit]

    def _bucket_key(self, value: datetime, granularity: str) -> str:
        local_date = _aware(value).astimezone(self._seller_timezone).date()
        if granularity == "weekly":
            start = local_date - timedelta(days=local_date.weekday())
            return start.isoformat()
        if granularity == "monthly":
            return local_date.replace(day=1).isoformat()
        return local_date.isoformat()

    def _product_period_deltas(self, lines: list[SalesLine], *, granularity: str) -> list[dict[str, Any]]:
        by_product: dict[UUID, dict[str, Any]] = {}
        for line in lines:
            bucket = self._bucket_key(line.sale.sold_at, granularity)
            item = by_product.setdefault(line.product.id, {"product": _product_ref(line.product), "periods": defaultdict(lambda: Decimal("0"))})
            item["periods"][bucket] += line.gross_revenue
        output = []
        for item in by_product.values():
            values = [item["periods"][key] for key in sorted(item["periods"])]
            delta = Decimal("0") if len(values) < 2 else values[-1] - values[0]
            output.append({"product": item["product"], "delta": delta})
        return output

    def _data_completeness(self, lines: list[SalesLine]) -> dict[str, Any]:
        estimated_count = sum(1 for line in lines if line.revenue_is_estimated)
        return {
            "valid_sales_records": len(lines),
            "transaction_price_available": estimated_count == 0 and bool(lines),
            "estimated_revenue_records": estimated_count,
            "missing_transaction_price_records": estimated_count,
            "valid_statuses": [status.value for status in VALID_SALES_STATUSES],
            "excluded_statuses": ["PENDING", "CANCELLED", "FAILED_PAYMENT", "test_orders"],
        }

    def _latest_sale_date(self, *, seller_id: UUID, product_id: UUID | None) -> str | None:
        if not hasattr(self, "_db"):
            return None
        return latest_recorded_sale_date(self._db, seller_id=seller_id, product_id=product_id, seller_timezone=self._seller_timezone.key)

    def _sales_coverage(
        self,
        *,
        seller_id: UUID,
        from_date: date,
        to_date: date,
        product_id: UUID | None,
        marketplace: str | None,
    ) -> dict[str, Any]:
        if not hasattr(self, "_db"):
            return _coverage_payload(status=SalesDataCompletenessStatus.UNKNOWN)
        statement = select(SalesDataCoverage).where(
            SalesDataCoverage.seller_id == seller_id,
            SalesDataCoverage.coverage_start_date <= from_date,
            SalesDataCoverage.coverage_end_date >= to_date,
        )
        if product_id is not None:
            statement = statement.where((SalesDataCoverage.product_id == product_id) | (SalesDataCoverage.product_id.is_(None)))
        else:
            statement = statement.where(SalesDataCoverage.product_id.is_(None))
        if marketplace is not None:
            statement = statement.where(SalesDataCoverage.marketplace == marketplace)
        else:
            statement = statement.where(SalesDataCoverage.marketplace.is_(None))
        try:
            rows = self._db.execute(statement.order_by(SalesDataCoverage.updated_at.desc())).scalars().all()
        except SQLAlchemyError:
            self._db.rollback()
            return _coverage_payload(status=SalesDataCompletenessStatus.UNKNOWN)
        if not rows:
            return _coverage_payload(status=SalesDataCompletenessStatus.UNKNOWN)
        status = _coverage_rollup([row.completeness_status for row in rows])
        return _coverage_payload(
            status=status,
            source=rows[0].source,
            coverage_start_date=min(row.coverage_start_date for row in rows),
            coverage_end_date=max(row.coverage_end_date for row in rows),
            imported_record_count=sum(row.imported_record_count for row in rows),
            valid_sales_count=sum(row.valid_sales_count for row in rows),
            invalid_or_excluded_count=sum(row.invalid_or_excluded_count for row in rows),
            marketplace=marketplace,
            product_id=product_id,
        )

    def _missing_notes(self, *, lines: list[SalesLine], marketplace: str | None, coverage: dict[str, Any] | None = None) -> list[str]:
        notes = []
        if any(line.revenue_is_estimated for line in lines):
            notes.append("MISSING_TRANSACTION_PRICE: Some sales records lack transaction unit_price/line_total; revenue is estimated from current Product.selling_price with LOW confidence.")
        if not lines:
            notes.append("No completed/fulfilled non-test sales records were found for the requested scope.")
        if coverage and coverage.get("completeness_status") != SalesDataCompletenessStatus.COMPLETE.value:
            notes.append("SALES_COMPLETENESS_UNKNOWN_OR_PARTIAL: Sales completeness is unknown or partial for the requested scope.")
        return notes

    def _evidence(self, lines: list[SalesLine], *, default_source: str) -> list[dict[str, Any]]:
        evidence = [_evidence(default_source, line.sale.id) for line in lines[:20]]
        product_ids = sorted({str(line.product.id) for line in lines})
        if product_ids:
            evidence.append(_evidence("products", "joined_products", {"product_ids": product_ids[:20]}))
        return evidence


def _date_bounds(from_date: date, to_date: date, seller_timezone: ZoneInfo) -> tuple[datetime, datetime]:
    start_local = datetime.combine(from_date, time.min, tzinfo=seller_timezone)
    end_local = datetime.combine(to_date, time.max, tzinfo=seller_timezone)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _sales_line_args(**kwargs):
    return {key: value for key, value in kwargs.items() if key != "marketplace" or value is not None}


def _revenue_values_for_sale(sale: SalesRecord, product: Product) -> tuple[Decimal | None, Decimal | None, bool, str, str]:
    unit_price = getattr(sale, "unit_price", None)
    line_total = getattr(sale, "line_total", None)
    if unit_price is not None or line_total is not None:
        return (
            Decimal(str(unit_price)) if unit_price is not None else None,
            Decimal(str(line_total)) if line_total is not None else None,
            False,
            "TRANSACTION",
            _enum_value(getattr(sale, "price_source", SalesRecordPriceSource.TRANSACTION)),
        )
    value = getattr(product, "selling_price", None)
    if value is not None:
        return Decimal(str(value)), None, True, SalesRecordPriceSource.CURRENT_PRODUCT_PRICE_ESTIMATE.value, SalesRecordPriceSource.CURRENT_PRODUCT_PRICE_ESTIMATE.value
    return None, None, True, "UNKNOWN", "UNKNOWN"


def _revenue_estimation_method(lines: list[SalesLine]) -> str:
    if any(line.revenue_estimation_method == SalesRecordPriceSource.CURRENT_PRODUCT_PRICE_ESTIMATE.value for line in lines):
        return SalesRecordPriceSource.CURRENT_PRODUCT_PRICE_ESTIMATE.value
    if lines and all(not line.revenue_is_estimated for line in lines):
        return "TRANSACTION"
    return "UNKNOWN"


def _missing_codes(*, lines: list[SalesLine], coverage: dict[str, Any]) -> list[str]:
    missing = []
    if any(line.revenue_is_estimated for line in lines):
        missing.append("MISSING_TRANSACTION_PRICE")
    if coverage.get("completeness_status") != SalesDataCompletenessStatus.COMPLETE.value:
        missing.append("SALES_COMPLETENESS_UNKNOWN_OR_PARTIAL")
    return missing


def _confidence(*, summary: dict[str, Any], coverage: dict[str, Any]) -> str:
    if summary.get("revenue_is_estimated") or coverage.get("completeness_status") != SalesDataCompletenessStatus.COMPLETE.value:
        return "LOW"
    return "HIGH"


def _coverage_rollup(statuses: list[SalesDataCompletenessStatus]) -> SalesDataCompletenessStatus:
    if any(status == SalesDataCompletenessStatus.FAILED for status in statuses):
        return SalesDataCompletenessStatus.FAILED
    if any(status == SalesDataCompletenessStatus.PARTIAL for status in statuses):
        return SalesDataCompletenessStatus.PARTIAL
    if statuses and all(status == SalesDataCompletenessStatus.COMPLETE for status in statuses):
        return SalesDataCompletenessStatus.COMPLETE
    return SalesDataCompletenessStatus.UNKNOWN


def _coverage_payload(
    *,
    status: SalesDataCompletenessStatus,
    source: str | None = None,
    coverage_start_date: date | None = None,
    coverage_end_date: date | None = None,
    imported_record_count: int = 0,
    valid_sales_count: int = 0,
    invalid_or_excluded_count: int = 0,
    marketplace: str | None = None,
    product_id: UUID | None = None,
) -> dict[str, Any]:
    return {
        "completeness_status": status.value,
        "source": source,
        "coverage_start_date": coverage_start_date.isoformat() if coverage_start_date else None,
        "coverage_end_date": coverage_end_date.isoformat() if coverage_end_date else None,
        "imported_record_count": imported_record_count,
        "valid_sales_count": valid_sales_count,
        "invalid_or_excluded_count": invalid_or_excluded_count,
        "marketplace": marketplace,
        "product_id": str(product_id) if product_id else None,
    }


def _enum_value(value: Any) -> str:
    return getattr(value, "value", str(value))


def _product_ref(product: Product) -> dict[str, Any]:
    return {"id": str(product.id), "title": product.title, "category": product.category}


def _listing_exists(*, seller_id: UUID, marketplace: str):
    return (
        select(ProductMarketplaceListing.id)
        .where(
            ProductMarketplaceListing.seller_id == seller_id,
            ProductMarketplaceListing.product_id == Product.id,
            ProductMarketplaceListing.marketplace == marketplace,
            ProductMarketplaceListing.archived_at.is_(None),
        )
        .exists()
    )


def _evidence(source_table: str, source_id: Any, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"source_table": source_table, "source_id": str(source_id), "payload": payload or {}}


def _filters(**kwargs) -> dict[str, Any]:
    return {key: value.isoformat() if hasattr(value, "isoformat") else str(value) for key, value in kwargs.items() if value is not None}


def _trend_direction(values: list[Decimal]) -> str:
    if len(values) < 2:
        return "FLAT"
    if values[-1] > values[0]:
        return "UP"
    if values[-1] < values[0]:
        return "DOWN"
    return "FLAT"


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
