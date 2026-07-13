from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any, Callable
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.orm import Session, joinedload

from app.models.alert import Alert, AlertDeliveryStatus
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.dead_stock_assessment import DeadStockAssessment, DeadStockClassification
from app.models.dead_stock_capital_recovery import DeadStockCapitalRecoveryEstimate
from app.models.inventory_risk import InventoryRiskAssessment, InventoryRiskLevel
from app.models.marketplace_fee_policy import MarketplaceFeePolicy
from app.models.pricing_policy import PricingPolicy
from app.models.product import Product, ProductMarketplaceListing, ProductMarketplaceListingStatus, ProductStatus
from app.models.recommendation import Recommendation
from app.models.sales_data_coverage import SalesDataCompletenessStatus, SalesDataCoverage
from app.models.sales_record import SalesRecord, SalesRecordStatus
from app.services.copilot.metric_catalog import MetricCatalogService, MetricDefinition, MetricImplementationStatus
from app.services.copilot.query_constraints import CatalogValidationError


VALID_SALES_STATUSES = (SalesRecordStatus.COMPLETED, SalesRecordStatus.FULFILLED)
DEFAULT_LIMIT = 25
MAX_LIMIT = 100


class MetricExecutionService:
    """Executes only backend-owned handlers for catalog-registered metrics."""

    def __init__(self, db: Session, *, metric_catalog: MetricCatalogService | None = None) -> None:
        self._db = db
        self._catalog = metric_catalog or MetricCatalogService()
        self._handlers: dict[str, Callable[..., dict[str, Any]]] = {
            "product_count": self._product_count,
            "active_product_count": self._active_product_count,
            "listed_product_count": self._listed_product_count,
            "products_missing_cost_count": self._products_missing_cost_count,
            "products_missing_fee_policy_count": self._products_missing_fee_policy_count,
            "products_missing_pricing_policy_count": self._products_missing_pricing_policy_count,
            "products_with_stock_count": self._products_with_stock_count,
            "products_with_no_sales_count": self._products_with_no_valid_imported_sales_count,
            "products_with_no_valid_imported_sales_count": self._products_with_no_valid_imported_sales_count,
            "gross_revenue": self._gross_revenue,
            "units_sold": self._units_sold,
            "order_count": self._order_count,
            "average_order_value": self._average_order_value,
            "top_products_by_revenue": self._top_products_by_revenue,
            "revenue_trend": self._revenue_trend,
            "previous_period_revenue": self._previous_period_revenue,
            "revenue_change": self._revenue_change,
            "percentage_revenue_change": self._percentage_revenue_change,
            "products_with_revenue_decline": self._products_with_revenue_decline,
            "average_selling_price_delta": self._average_selling_price_delta,
            "estimated_profit": self._estimated_profit,
            "margin_rate": self._margin_rate,
            "products_excluded_from_profit": self._products_excluded_from_profit,
            "current_inventory_value": self._current_inventory_value,
            "low_stock_product_count": self._low_stock_product_count,
            "stockout_risk_count": self._stockout_risk_count,
            "dead_stock_count": self._dead_stock_count,
            "locked_capital": self._locked_capital,
            "competitor_undercut_count": self._competitor_undercut_count,
            "competitor_price_gap": self._competitor_price_gap,
            "pending_recommendation_count": self._pending_recommendation_count,
            "unresolved_alert_count": self._unresolved_alert_count,
        }
        self._catalog.validate_capability_contract(set(self._handlers))

    def execute(
        self,
        *,
        seller_id: UUID,
        metric_key: str,
        filters: dict[str, Any] | None = None,
        group_by: list[str] | tuple[str, ...] | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict[str, Any]:
        filters_used = dict(filters or {})
        filters_used["seller_id"] = seller_id
        if from_date is not None:
            filters_used["from_date"] = from_date
        if to_date is not None:
            filters_used["to_date"] = to_date
        metric = self._catalog.validate_metric_query(metric_key, filters=filters_used, group_by=group_by)
        if metric.implementation_status == MetricImplementationStatus.UNSUPPORTED:
            return self._result(
                metric,
                filters_used=filters_used,
                status="UNSUPPORTED",
                missing_data=[metric.unsupported_reason or "UNSUPPORTED_METRIC"],
                limit=_bound_limit(limit),
                offset=max(0, int(offset or 0)),
            )
        self._verify_product_scope(seller_id=seller_id, product_id=filters_used.get("product_id"))
        bounded_limit = _bound_limit(limit)
        bounded_offset = max(0, int(offset or 0))
        if filters_used.get("marketplace") and not self._marketplace_available(seller_id=seller_id, marketplace=str(filters_used["marketplace"])):
            return self._result(metric, filters_used=filters_used, status="MISSING_DATA", missing_data=["MISSING_MARKETPLACE_DATA"], limit=bounded_limit, offset=bounded_offset)
        handler = self._handlers.get(metric_key)
        if handler is None:
            return self._result(metric, filters_used=filters_used, status="UNSUPPORTED", missing_data=["UNSUPPORTED_METRIC_EXECUTOR"], limit=bounded_limit, offset=bounded_offset)
        return handler(metric=metric, seller_id=seller_id, filters=filters_used, group_by=tuple(group_by or ()), limit=bounded_limit, offset=bounded_offset)

    def _verify_product_scope(self, *, seller_id: UUID, product_id: Any | None) -> None:
        if product_id is None:
            return
        found = self._db.execute(select(Product.id).where(Product.seller_id == seller_id, Product.id == product_id)).scalar_one_or_none()
        if found is None:
            raise CatalogValidationError("product_id does not belong to the authenticated seller.")

    def _marketplace_available(self, *, seller_id: UUID, marketplace: str) -> bool:
        return self._db.execute(
            select(ProductMarketplaceListing.id).where(
                ProductMarketplaceListing.seller_id == seller_id,
                ProductMarketplaceListing.marketplace == marketplace,
                ProductMarketplaceListing.archived_at.is_(None),
            ).limit(1)
        ).first() is not None

    def _product_count(self, **kwargs) -> dict[str, Any]:
        return self._count_products_matching(**kwargs, extra=lambda stmt: stmt)

    def _active_product_count(self, **kwargs) -> dict[str, Any]:
        return self._count_products_matching(**kwargs, extra=lambda stmt: stmt.where(Product.status == ProductStatus.ACTIVE))

    def _products_missing_cost_count(self, **kwargs) -> dict[str, Any]:
        return self._count_products_matching(**kwargs, extra=lambda stmt: stmt.where(Product.cost_price.is_(None)))

    def _products_with_stock_count(self, **kwargs) -> dict[str, Any]:
        return self._count_products_matching(**kwargs, extra=lambda stmt: stmt.where(Product.stock_quantity > 0))

    def _listed_product_count(self, *, metric: MetricDefinition, seller_id: UUID, filters: dict[str, Any], group_by: tuple[str, ...], limit: int, offset: int) -> dict[str, Any]:
        stmt = select(ProductMarketplaceListing).join(Product, Product.id == ProductMarketplaceListing.product_id).where(ProductMarketplaceListing.seller_id == seller_id, Product.seller_id == seller_id)
        stmt = self._apply_product_filters(stmt, filters)
        stmt = self._apply_date_range(stmt, ProductMarketplaceListing.created_at, filters)
        marketplace = filters.get("marketplace")
        if marketplace:
            stmt = stmt.where(ProductMarketplaceListing.marketplace == marketplace)
        if filters.get("status"):
            stmt = stmt.where(ProductMarketplaceListing.listing_status == ProductMarketplaceListingStatus(str(filters["status"]).upper()))
        else:
            stmt = stmt.where(ProductMarketplaceListing.listing_status == ProductMarketplaceListingStatus.ACTIVE)
        rows = self._db.execute(stmt.options(joinedload(ProductMarketplaceListing.product))).scalars().all()
        return self._rows_or_count(metric, rows, group_by, filters, limit, offset, value_factory=lambda row: row.product_id, row_factory=lambda row: {"product_id": str(row.product_id), "marketplace": row.marketplace, "status": _enum(row.listing_status)})

    def _products_missing_fee_policy_count(self, **kwargs) -> dict[str, Any]:
        return self._missing_policy_count(policy="fee", **kwargs)

    def _products_missing_pricing_policy_count(self, **kwargs) -> dict[str, Any]:
        return self._missing_policy_count(policy="pricing", **kwargs)

    def _missing_policy_count(self, *, policy: str, metric: MetricDefinition, seller_id: UUID, filters: dict[str, Any], group_by: tuple[str, ...], limit: int, offset: int) -> dict[str, Any]:
        products = self._load_products(seller_id=seller_id, filters=filters)
        missing = []
        for product in products:
            has_policy = self._has_fee_policy(product, filters.get("marketplace")) if policy == "fee" else self._has_pricing_policy(product, filters.get("marketplace"))
            if not has_policy:
                missing.append(product)
        return self._product_rows_or_count(metric, missing, group_by, filters, limit, offset, evidence_table="products")

    def _products_with_no_valid_imported_sales_count(self, *, metric: MetricDefinition, seller_id: UUID, filters: dict[str, Any], group_by: tuple[str, ...], limit: int, offset: int) -> dict[str, Any]:
        products = self._load_products(seller_id=seller_id, filters=filters)
        missing_data = []
        safe_no_sales = []
        start = filters.get("from_date") or date(1970, 1, 1)
        end = filters.get("to_date") or date.today()
        for product in products:
            coverage = self._coverage_status(seller_id=seller_id, product_id=product.id, marketplace=filters.get("marketplace"), from_date=start, to_date=end)
            if coverage != SalesDataCompletenessStatus.COMPLETE:
                missing_data.append("SALES_COMPLETENESS_UNKNOWN_OR_PARTIAL")
                continue
            if not self._has_valid_sale(seller_id=seller_id, product_id=product.id, filters=filters):
                safe_no_sales.append(product)
        status = "PARTIAL" if missing_data else "CALCULATED"
        return self._product_rows_or_count(metric, safe_no_sales, group_by, filters, limit, offset, evidence_table="sales_data_coverage", status=status, missing_data=sorted(set(missing_data)))

    def _gross_revenue(self, **kwargs) -> dict[str, Any]:
        lines, missing = self._sales_lines(kwargs["seller_id"], kwargs["filters"])
        value = sum((line["revenue"] for line in lines), Decimal("0"))
        return self._sales_result(kwargs["metric"], value=value, rows=lines, missing=missing, unit="money", currency=_currency(lines), filters=kwargs["filters"], group_by=kwargs["group_by"], limit=kwargs["limit"], offset=kwargs["offset"])

    def _units_sold(self, **kwargs) -> dict[str, Any]:
        lines, missing = self._sales_lines(kwargs["seller_id"], kwargs["filters"])
        value = sum(int(line["net_units"]) for line in lines)
        return self._sales_result(kwargs["metric"], value=value, rows=lines, missing=missing, unit="units", filters=kwargs["filters"], group_by=kwargs["group_by"], limit=kwargs["limit"], offset=kwargs["offset"])

    def _order_count(self, **kwargs) -> dict[str, Any]:
        lines, missing = self._sales_lines(kwargs["seller_id"], kwargs["filters"])
        return self._sales_result(kwargs["metric"], value=len(lines), rows=lines, missing=missing, unit="orders", filters=kwargs["filters"], group_by=kwargs["group_by"], limit=kwargs["limit"], offset=kwargs["offset"])

    def _average_order_value(self, **kwargs) -> dict[str, Any]:
        lines, missing = self._sales_lines(kwargs["seller_id"], kwargs["filters"])
        revenue = sum((line["revenue"] for line in lines), Decimal("0"))
        value = None if not lines else revenue / Decimal(len(lines))
        if not lines:
            missing = [*missing, "NO_VALID_SALES_RECORDS"]
        return self._sales_result(kwargs["metric"], value=value, rows=lines, missing=missing, unit="money", currency=_currency(lines), filters=kwargs["filters"], group_by=kwargs["group_by"], limit=kwargs["limit"], offset=kwargs["offset"])

    def _top_products_by_revenue(self, **kwargs) -> dict[str, Any]:
        lines, missing = self._sales_lines(kwargs["seller_id"], kwargs["filters"])
        grouped: dict[UUID, dict[str, Any]] = {}
        for line in lines:
            item = grouped.setdefault(line["product_id"], {"product_id": str(line["product_id"]), "product_title": line["product_title"], "gross_revenue": Decimal("0"), "units_sold": 0, "order_count": 0})
            item["gross_revenue"] += line["revenue"]
            item["units_sold"] += line["net_units"]
            item["order_count"] += 1
        rows = sorted(grouped.values(), key=lambda row: row["gross_revenue"], reverse=True)
        return self._result(kwargs["metric"], value=rows[0]["gross_revenue"] if rows else Decimal("0"), rows=rows[kwargs["offset"] : kwargs["offset"] + kwargs["limit"]], filters_used=kwargs["filters"], status=_status_for_missing(missing), missing_data=missing, unit="money", currency=_currency(lines), evidence=[_evidence("sales_records", "seller_scope")])

    def _revenue_trend(self, **kwargs) -> dict[str, Any]:
        lines, missing = self._sales_lines(kwargs["seller_id"], kwargs["filters"])
        interval = str(kwargs["filters"].get("interval") or (kwargs["group_by"][0] if kwargs["group_by"] and kwargs["group_by"][0] in {"day", "week", "month"} else "day"))
        buckets: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for line in lines:
            buckets[_bucket(line["sold_at"], interval)] += line["revenue"]
        rows = [{"period": key, "gross_revenue": value} for key, value in sorted(buckets.items())]
        return self._result(kwargs["metric"], value=sum((row["gross_revenue"] for row in rows), Decimal("0")), rows=rows[kwargs["offset"] : kwargs["offset"] + kwargs["limit"]], filters_used=kwargs["filters"], status=_status_for_missing(missing), missing_data=missing, unit="money", currency=_currency(lines), evidence=[_evidence("sales_records", "seller_scope")])

    def _previous_period_revenue(self, **kwargs) -> dict[str, Any]:
        comparison_filters, missing = _comparison_filters(kwargs["filters"])
        if comparison_filters is None:
            return self._result(kwargs["metric"], value=None, rows=[], filters_used=kwargs["filters"], status="MISSING_DATA", missing_data=missing, unit="money", evidence=[_evidence("sales_records", "seller_scope")])
        lines, line_missing = self._sales_lines(kwargs["seller_id"], comparison_filters)
        value = sum((line["revenue"] for line in lines), Decimal("0"))
        return self._result(
            kwargs["metric"],
            value=value,
            rows=lines[kwargs["offset"] : kwargs["offset"] + kwargs["limit"]],
            filters_used=kwargs["filters"],
            status=_status_for_missing([*missing, *line_missing]),
            missing_data=[*missing, *line_missing],
            unit="money",
            currency=_currency(lines),
            comparison={"period": _period_payload(comparison_filters), "previous_period_revenue": value},
            evidence=[_evidence("sales_records", "seller_scope")],
        )

    def _revenue_change(self, **kwargs) -> dict[str, Any]:
        current_lines, current_missing = self._sales_lines(kwargs["seller_id"], kwargs["filters"])
        comparison_filters, comparison_missing = _comparison_filters(kwargs["filters"])
        if comparison_filters is None:
            return self._result(kwargs["metric"], value=None, rows=[], filters_used=kwargs["filters"], status="MISSING_DATA", missing_data=comparison_missing, unit="money", evidence=[_evidence("sales_records", "seller_scope")])
        previous_lines, previous_missing = self._sales_lines(kwargs["seller_id"], comparison_filters)
        current = sum((line["revenue"] for line in current_lines), Decimal("0"))
        previous = sum((line["revenue"] for line in previous_lines), Decimal("0"))
        value = current - previous
        missing = [*current_missing, *comparison_missing, *previous_missing]
        return self._result(
            kwargs["metric"],
            value=value,
            rows=[],
            filters_used=kwargs["filters"],
            status=_status_for_missing(missing),
            missing_data=missing,
            unit="money",
            currency=_common_currency([*current_lines, *previous_lines]),
            comparison={"current_period_revenue": current, "previous_period_revenue": previous, "revenue_change": value, "previous_period": _period_payload(comparison_filters)},
            evidence=[_evidence("sales_records", "seller_scope")],
        )

    def _percentage_revenue_change(self, **kwargs) -> dict[str, Any]:
        current_lines, current_missing = self._sales_lines(kwargs["seller_id"], kwargs["filters"])
        comparison_filters, comparison_missing = _comparison_filters(kwargs["filters"])
        if comparison_filters is None:
            return self._result(kwargs["metric"], value=None, rows=[], filters_used=kwargs["filters"], status="MISSING_DATA", missing_data=comparison_missing, unit="percent", evidence=[_evidence("sales_records", "seller_scope")])
        previous_lines, previous_missing = self._sales_lines(kwargs["seller_id"], comparison_filters)
        current = sum((line["revenue"] for line in current_lines), Decimal("0"))
        previous = sum((line["revenue"] for line in previous_lines), Decimal("0"))
        missing = [*current_missing, *comparison_missing, *previous_missing]
        if previous == 0:
            return self._result(
                kwargs["metric"],
                value=None,
                rows=[],
                filters_used=kwargs["filters"],
                status="MISSING_DATA",
                missing_data=[*missing, "PREVIOUS_PERIOD_REVENUE_ZERO"],
                unit="percent",
                comparison={"current_period_revenue": current, "previous_period_revenue": previous, "reason": "Percentage revenue change is undefined when previous-period revenue is zero."},
                evidence=[_evidence("sales_records", "seller_scope")],
            )
        value = ((current - previous) / previous) * Decimal("100")
        return self._result(
            kwargs["metric"],
            value=value,
            rows=[],
            filters_used=kwargs["filters"],
            status=_status_for_missing(missing),
            missing_data=missing,
            unit="percent",
            currency=None,
            comparison={"current_period_revenue": current, "previous_period_revenue": previous, "revenue_change": current - previous, "previous_period": _period_payload(comparison_filters)},
            evidence=[_evidence("sales_records", "seller_scope")],
        )

    def _products_with_revenue_decline(self, **kwargs) -> dict[str, Any]:
        current_lines, current_missing = self._sales_lines(kwargs["seller_id"], kwargs["filters"])
        comparison_filters, comparison_missing = _comparison_filters(kwargs["filters"])
        if comparison_filters is None:
            return self._result(kwargs["metric"], value=None, rows=[], filters_used=kwargs["filters"], status="MISSING_DATA", missing_data=comparison_missing, unit="products", evidence=[_evidence("sales_records", "seller_scope")])
        previous_lines, previous_missing = self._sales_lines(kwargs["seller_id"], comparison_filters)
        current = _revenue_by_product(current_lines)
        previous = _revenue_by_product(previous_lines)
        rows = []
        for product_id, previous_row in previous.items():
            current_revenue = current.get(product_id, {}).get("revenue", Decimal("0"))
            previous_revenue = previous_row["revenue"]
            if current_revenue >= previous_revenue:
                continue
            decline_amount = current_revenue - previous_revenue
            rows.append(
                {
                    "product_id": str(product_id),
                    "product_title": previous_row["product_title"],
                    "current_revenue": current_revenue,
                    "previous_revenue": previous_revenue,
                    "revenue_change": decline_amount,
                    "percentage_revenue_change": None if previous_revenue == 0 else (decline_amount / previous_revenue) * Decimal("100"),
                }
            )
        rows.sort(key=lambda row: (row["revenue_change"], row["product_title"], row["product_id"]))
        missing = [*current_missing, *comparison_missing, *previous_missing]
        return self._result(
            kwargs["metric"],
            value=len(rows),
            rows=rows[kwargs["offset"] : kwargs["offset"] + kwargs["limit"]],
            filters_used=kwargs["filters"],
            status=_status_for_missing(missing),
            missing_data=missing,
            unit="products",
            currency=_common_currency([*current_lines, *previous_lines]),
            comparison={"previous_period": _period_payload(comparison_filters)},
            evidence=[_evidence("sales_records", "seller_scope"), _evidence("products", "seller_scope")],
        )

    def _average_selling_price_delta(self, **kwargs) -> dict[str, Any]:
        current_lines, current_missing = self._sales_lines(kwargs["seller_id"], kwargs["filters"])
        comparison_filters, comparison_missing = _comparison_filters(kwargs["filters"])
        if comparison_filters is None:
            return self._result(kwargs["metric"], value=None, rows=[], filters_used=kwargs["filters"], status="MISSING_DATA", missing_data=comparison_missing, unit="money", evidence=[_evidence("sales_records", "seller_scope")])
        previous_lines, previous_missing = self._sales_lines(kwargs["seller_id"], comparison_filters)
        current_asp = _average_transaction_unit_price(current_lines)
        previous_asp = _average_transaction_unit_price(previous_lines)
        missing = [*current_missing, *comparison_missing, *previous_missing]
        if current_asp is None:
            missing.append("NO_CURRENT_PERIOD_TRANSACTION_PRICE")
        if previous_asp is None:
            missing.append("NO_PREVIOUS_PERIOD_TRANSACTION_PRICE")
        value = None if current_asp is None or previous_asp is None else current_asp - previous_asp
        return self._result(
            kwargs["metric"],
            value=value,
            rows=[],
            filters_used=kwargs["filters"],
            status="MISSING_DATA" if value is None else _status_for_missing(missing),
            missing_data=sorted(set(missing)),
            unit="money",
            currency=_common_currency([*current_lines, *previous_lines]),
            comparison={"current_average_selling_price": current_asp, "previous_average_selling_price": previous_asp, "previous_period": _period_payload(comparison_filters)},
            evidence=[_evidence("sales_records", "seller_scope")],
        )

    def _estimated_profit(self, **kwargs) -> dict[str, Any]:
        rows, missing = self._profit_rows(kwargs["seller_id"], kwargs["filters"])
        value = sum((row["estimated_profit"] for row in rows), Decimal("0"))
        return self._result(kwargs["metric"], value=value, rows=rows[kwargs["offset"] : kwargs["offset"] + kwargs["limit"]], filters_used=kwargs["filters"], status="PARTIAL" if missing else "CALCULATED", missing_data=missing, unit="money", currency="BDT", evidence=[_evidence("sales_records", "seller_scope"), _evidence("marketplace_fee_policies", "seller_scope")])

    def _margin_rate(self, **kwargs) -> dict[str, Any]:
        rows, missing = self._profit_rows(kwargs["seller_id"], kwargs["filters"])
        revenue = sum((row["gross_revenue"] for row in rows), Decimal("0"))
        profit = sum((row["estimated_profit"] for row in rows), Decimal("0"))
        value = None if revenue == 0 else profit / revenue
        if revenue == 0:
            missing = [*missing, "NO_PROFITABLE_REVENUE_BASIS"]
        return self._result(kwargs["metric"], value=value, rows=rows[kwargs["offset"] : kwargs["offset"] + kwargs["limit"]], filters_used=kwargs["filters"], status="PARTIAL" if missing else "CALCULATED", missing_data=missing, unit="ratio", evidence=[_evidence("sales_records", "seller_scope")])

    def _products_excluded_from_profit(self, **kwargs) -> dict[str, Any]:
        _, missing, excluded = self._profit_rows(kwargs["seller_id"], kwargs["filters"], include_excluded=True)
        return self._result(kwargs["metric"], value=len(excluded), rows=excluded[kwargs["offset"] : kwargs["offset"] + kwargs["limit"]], filters_used=kwargs["filters"], status="CALCULATED", missing_data=missing, unit="products", evidence=[_evidence("products", "seller_scope")])

    def _current_inventory_value(self, *, metric: MetricDefinition, seller_id: UUID, filters: dict[str, Any], group_by: tuple[str, ...], limit: int, offset: int) -> dict[str, Any]:
        rows = []
        missing = []
        for product in self._load_products(seller_id=seller_id, filters=filters):
            if product.cost_price is None:
                missing.append("MISSING_PRODUCT_COST")
                continue
            rows.append({"product_id": str(product.id), "product_title": product.title, "stock_quantity": product.stock_quantity, "inventory_value": Decimal(product.stock_quantity) * Decimal(str(product.cost_price))})
        return self._result(metric, value=sum((row["inventory_value"] for row in rows), Decimal("0")), rows=rows[offset : offset + limit], filters_used=filters, status="PARTIAL" if missing else "CALCULATED", missing_data=sorted(set(missing)), unit="money", currency="BDT", evidence=[_evidence("products", "seller_scope")])

    def _low_stock_product_count(self, **kwargs) -> dict[str, Any]:
        return self._count_products_matching(**kwargs, extra=lambda stmt: stmt.where(Product.stock_quantity <= 5))

    def _stockout_risk_count(self, *, metric: MetricDefinition, seller_id: UUID, filters: dict[str, Any], group_by: tuple[str, ...], limit: int, offset: int) -> dict[str, Any]:
        stmt = select(InventoryRiskAssessment).join(Product, Product.id == InventoryRiskAssessment.product_id).where(InventoryRiskAssessment.seller_id == seller_id, Product.seller_id == seller_id, InventoryRiskAssessment.risk_level.in_((InventoryRiskLevel.HIGH, InventoryRiskLevel.CRITICAL)))
        stmt = self._apply_product_filters(stmt, filters)
        stmt = self._apply_date_range(stmt, InventoryRiskAssessment.assessed_at, filters)
        rows = self._db.execute(stmt.options(joinedload(InventoryRiskAssessment.product))).scalars().all()
        return self._rows_or_count(metric, rows, group_by, filters, limit, offset, row_factory=lambda row: {"product_id": str(row.product_id), "risk_level": _enum(row.risk_level), "risk_score": row.risk_score}, evidence_table="inventory_risk_assessments")

    def _dead_stock_count(self, *, metric: MetricDefinition, seller_id: UUID, filters: dict[str, Any], group_by: tuple[str, ...], limit: int, offset: int) -> dict[str, Any]:
        stmt = select(DeadStockAssessment).join(Product, Product.id == DeadStockAssessment.product_id).where(DeadStockAssessment.seller_id == seller_id, Product.seller_id == seller_id, DeadStockAssessment.classification.in_((DeadStockClassification.AT_RISK, DeadStockClassification.DEAD_STOCK)))
        stmt = self._apply_product_filters(stmt, filters)
        stmt = self._apply_date_range(stmt, DeadStockAssessment.assessed_at, filters)
        rows = self._db.execute(stmt.options(joinedload(DeadStockAssessment.product))).scalars().all()
        return self._rows_or_count(metric, rows, group_by, filters, limit, offset, row_factory=lambda row: {"product_id": str(row.product_id), "classification": _enum(row.classification), "eligible_quantity": row.eligible_quantity}, evidence_table="dead_stock_assessments")

    def _locked_capital(self, *, metric: MetricDefinition, seller_id: UUID, filters: dict[str, Any], group_by: tuple[str, ...], limit: int, offset: int) -> dict[str, Any]:
        stmt = select(DeadStockCapitalRecoveryEstimate).where(DeadStockCapitalRecoveryEstimate.seller_id == seller_id)
        stmt = self._apply_date_range(stmt, DeadStockCapitalRecoveryEstimate.calculated_at, filters)
        if filters.get("product_id"):
            stmt = stmt.where(DeadStockCapitalRecoveryEstimate.product_id == filters["product_id"])
        rows = self._db.execute(stmt).scalars().all()
        value = sum((Decimal(str(row.locked_capital)) for row in rows if row.locked_capital is not None), Decimal("0"))
        missing = [] if all(row.locked_capital is not None for row in rows) else ["MISSING_LOCKED_CAPITAL"]
        return self._result(metric, value=value, rows=[{"product_id": str(row.product_id), "locked_capital": row.locked_capital} for row in rows][offset : offset + limit], filters_used=filters, status="PARTIAL" if missing else "CALCULATED", missing_data=missing, unit="money", currency="BDT", evidence=[_evidence("dead_stock_capital_recovery_estimates", "seller_scope")])

    def _competitor_undercut_count(self, *, metric: MetricDefinition, seller_id: UUID, filters: dict[str, Any], group_by: tuple[str, ...], limit: int, offset: int) -> dict[str, Any]:
        stmt = select(CompetitorSnapshot).join(Product, Product.id == CompetitorSnapshot.product_id).where(Product.seller_id == seller_id, CompetitorSnapshot.price.is_not(None), Product.selling_price.is_not(None), CompetitorSnapshot.price < Product.selling_price)
        stmt = self._apply_product_filters(stmt, filters)
        stmt = self._apply_date_range(stmt, CompetitorSnapshot.captured_at, filters)
        rows = self._db.execute(stmt.options(joinedload(CompetitorSnapshot.product))).scalars().all()
        return self._rows_or_count(metric, rows, group_by, filters, limit, offset, row_factory=lambda row: {"product_id": str(row.product_id), "competitor_id": str(row.competitor_id), "competitor_price": row.price}, evidence_table="competitor_snapshots")

    def _competitor_price_gap(self, *, metric: MetricDefinition, seller_id: UUID, filters: dict[str, Any], group_by: tuple[str, ...], limit: int, offset: int) -> dict[str, Any]:
        stmt = select(CompetitorSnapshot).join(Product, Product.id == CompetitorSnapshot.product_id).where(Product.seller_id == seller_id, CompetitorSnapshot.price.is_not(None), Product.selling_price.is_not(None))
        stmt = self._apply_product_filters(stmt, filters)
        stmt = self._apply_date_range(stmt, CompetitorSnapshot.captured_at, filters)
        rows = self._db.execute(stmt.options(joinedload(CompetitorSnapshot.product))).scalars().all()
        out = [{"product_id": str(row.product_id), "competitor_id": str(row.competitor_id), "price_gap": Decimal(str(row.product.selling_price)) - Decimal(str(row.price))} for row in rows]
        avg = None if not out else sum((row["price_gap"] for row in out), Decimal("0")) / Decimal(len(out))
        return self._result(metric, value=avg, rows=out[offset : offset + limit], filters_used=filters, status="CALCULATED", unit="money", currency="BDT", evidence=[_evidence("competitor_snapshots", "seller_scope")])

    def _pending_recommendation_count(self, *, metric: MetricDefinition, seller_id: UUID, filters: dict[str, Any], group_by: tuple[str, ...], limit: int, offset: int) -> dict[str, Any]:
        stmt = select(Recommendation).join(Product, Product.id == Recommendation.product_id).where(Product.seller_id == seller_id)
        stmt = self._apply_product_filters(stmt, filters)
        stmt = self._apply_date_range(stmt, Recommendation.created_at, filters)
        rows = self._db.execute(stmt.options(joinedload(Recommendation.product))).scalars().all()
        return self._rows_or_count(metric, rows, group_by, filters, limit, offset, row_factory=lambda row: {"product_id": str(row.product_id), "action": _enum(row.action), "confidence": _enum(row.confidence)}, evidence_table="recommendations")

    def _unresolved_alert_count(self, *, metric: MetricDefinition, seller_id: UUID, filters: dict[str, Any], group_by: tuple[str, ...], limit: int, offset: int) -> dict[str, Any]:
        stmt = select(Alert).join(Product, Product.id == Alert.product_id).where(Alert.seller_id == seller_id, Product.seller_id == seller_id, (Alert.delivery_status != AlertDeliveryStatus.delivered) | (Alert.read_at.is_(None)))
        stmt = self._apply_product_filters(stmt, filters)
        stmt = self._apply_date_range(stmt, Alert.created_at, filters)
        rows = self._db.execute(stmt.options(joinedload(Alert.product))).scalars().all()
        return self._rows_or_count(metric, rows, group_by, filters, limit, offset, row_factory=lambda row: {"product_id": str(row.product_id), "alert_type": row.alert_type, "delivery_status": _enum(row.delivery_status)}, evidence_table="alerts")

    def _count_products_matching(self, *, metric: MetricDefinition, seller_id: UUID, filters: dict[str, Any], group_by: tuple[str, ...], limit: int, offset: int, extra: Callable[[Any], Any]) -> dict[str, Any]:
        stmt = extra(select(Product).where(Product.seller_id == seller_id))
        stmt = self._apply_product_filters(stmt, filters)
        stmt = self._apply_date_range(stmt, Product.created_at, filters)
        rows = self._db.execute(stmt.order_by(Product.created_at.desc(), Product.id.desc())).scalars().all()
        return self._product_rows_or_count(metric, rows, group_by, filters, limit, offset, evidence_table="products")

    def _load_products(self, *, seller_id: UUID, filters: dict[str, Any]) -> list[Product]:
        stmt = select(Product).where(Product.seller_id == seller_id)
        stmt = self._apply_product_filters(stmt, filters)
        return self._db.execute(stmt.order_by(Product.created_at.desc(), Product.id.desc())).scalars().all()

    def _apply_product_filters(self, stmt: Any, filters: dict[str, Any]) -> Any:
        if filters.get("product_id"):
            stmt = stmt.where(Product.id == filters["product_id"])
        if filters.get("category"):
            stmt = stmt.where(Product.category == filters["category"])
        if filters.get("marketplace"):
            stmt = stmt.where(
                exists().where(
                    ProductMarketplaceListing.seller_id == Product.seller_id,
                    ProductMarketplaceListing.product_id == Product.id,
                    ProductMarketplaceListing.marketplace == filters["marketplace"],
                    ProductMarketplaceListing.archived_at.is_(None),
                )
            )
        return stmt

    def _apply_date_range(self, stmt: Any, column: Any, filters: dict[str, Any]) -> Any:
        if filters.get("from_date"):
            stmt = stmt.where(column >= _start(filters["from_date"]))
        if filters.get("to_date"):
            stmt = stmt.where(column <= _end(filters["to_date"]))
        return stmt

    def _sales_lines(self, seller_id: UUID, filters: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
        stmt = select(SalesRecord).options(joinedload(SalesRecord.product)).join(Product, Product.id == SalesRecord.product_id).where(SalesRecord.seller_id == seller_id, Product.seller_id == seller_id, SalesRecord.status.in_(VALID_SALES_STATUSES), SalesRecord.is_test_order.is_(False))
        stmt = self._apply_product_filters(stmt, filters)
        stmt = self._apply_date_range(stmt, SalesRecord.sold_at, filters)
        rows = self._db.execute(stmt.order_by(SalesRecord.sold_at.asc(), SalesRecord.id.asc())).scalars().all()
        out = []
        missing = []
        for sale in rows:
            qty = int(sale.quantity_sold or 0)
            returns = int(sale.returned_units or 0) + int(sale.refunded_restocked_units or 0)
            net_units = max(0, qty - returns)
            revenue = _sale_revenue(sale)
            if revenue is None:
                missing.append("MISSING_TRANSACTION_PRICE")
                continue
            out.append({"sale_id": str(sale.id), "product_id": sale.product_id, "product_title": sale.product.title, "sold_at": sale.sold_at, "quantity": qty, "net_units": net_units, "unit_price": sale.unit_price, "line_total": sale.line_total, "revenue": revenue, "currency": sale.currency or "BDT"})
        return out, sorted(set(missing))

    def _sales_result(self, metric: MetricDefinition, *, value: Any, rows: list[dict[str, Any]], missing: list[str], unit: str, filters: dict[str, Any], group_by: tuple[str, ...], limit: int, offset: int, currency: str | None = None) -> dict[str, Any]:
        if group_by:
            rows = _group_sales(rows, group_by)
        return self._result(metric, value=value, rows=rows[offset : offset + limit], filters_used=filters, status=_status_for_missing(missing), missing_data=missing, unit=unit, currency=currency, evidence=[_evidence("sales_records", "seller_scope")])

    def _profit_rows(self, seller_id: UUID, filters: dict[str, Any], *, include_excluded: bool = False):
        sales, missing = self._sales_lines(seller_id, filters)
        rows = []
        excluded = []
        for line in sales:
            product = self._db.get(Product, line["product_id"])
            if product is None or product.cost_price is None:
                missing.append("MISSING_PRODUCT_COST")
                excluded.append({"product_id": str(line["product_id"]), "reason": "MISSING_PRODUCT_COST"})
                continue
            fee = self._fee_policy(product, filters.get("marketplace"))
            if fee is None:
                missing.append("MISSING_FEE_POLICY")
                excluded.append({"product_id": str(line["product_id"]), "reason": "MISSING_FEE_POLICY"})
                continue
            gross = Decimal(str(line["revenue"]))
            qty = Decimal(int(line["net_units"]))
            variable_fee = gross * (Decimal(str(fee.percentage_commission_rate)) + Decimal(str(fee.payment_fee_rate)))
            fixed_fee = Decimal(str(fee.fixed_per_order_fee)) + qty * (Decimal(str(fee.fixed_per_unit_fee)) + Decimal(str(fee.fulfilment_fee)) + Decimal(str(fee.other_variable_cost)))
            cost = qty * Decimal(str(product.cost_price))
            rows.append({"product_id": str(product.id), "product_title": product.title, "gross_revenue": gross, "estimated_profit": gross - cost - variable_fee - fixed_fee})
        if include_excluded:
            return rows, sorted(set(missing)), excluded
        return rows, sorted(set(missing))

    def _has_valid_sale(self, *, seller_id: UUID, product_id: UUID, filters: dict[str, Any]) -> bool:
        stmt = select(SalesRecord.id).where(SalesRecord.seller_id == seller_id, SalesRecord.product_id == product_id, SalesRecord.status.in_(VALID_SALES_STATUSES), SalesRecord.is_test_order.is_(False))
        stmt = self._apply_date_range(stmt, SalesRecord.sold_at, filters)
        return self._db.execute(stmt.limit(1)).first() is not None

    def _coverage_status(self, *, seller_id: UUID, product_id: UUID, marketplace: str | None, from_date: date, to_date: date) -> SalesDataCompletenessStatus:
        stmt = select(SalesDataCoverage).where(SalesDataCoverage.seller_id == seller_id, SalesDataCoverage.coverage_start_date <= from_date, SalesDataCoverage.coverage_end_date >= to_date, (SalesDataCoverage.product_id == product_id) | (SalesDataCoverage.product_id.is_(None)))
        if marketplace:
            stmt = stmt.where(SalesDataCoverage.marketplace == marketplace)
        else:
            stmt = stmt.where(SalesDataCoverage.marketplace.is_(None))
        rows = self._db.execute(stmt).scalars().all()
        if rows and all(row.completeness_status == SalesDataCompletenessStatus.COMPLETE for row in rows):
            return SalesDataCompletenessStatus.COMPLETE
        if rows and any(row.completeness_status == SalesDataCompletenessStatus.PARTIAL for row in rows):
            return SalesDataCompletenessStatus.PARTIAL
        return SalesDataCompletenessStatus.UNKNOWN

    def _has_fee_policy(self, product: Product, marketplace: str | None) -> bool:
        return self._fee_policy(product, marketplace) is not None

    def _fee_policy(self, product: Product, marketplace: str | None) -> MarketplaceFeePolicy | None:
        stmt = select(MarketplaceFeePolicy).where(MarketplaceFeePolicy.seller_id == product.seller_id, MarketplaceFeePolicy.is_active.is_(True), (MarketplaceFeePolicy.product_id == product.id) | (MarketplaceFeePolicy.product_id.is_(None)))
        if marketplace:
            stmt = stmt.where(MarketplaceFeePolicy.marketplace == marketplace)
        return self._db.execute(stmt.order_by(MarketplaceFeePolicy.product_id.desc().nullslast(), MarketplaceFeePolicy.effective_from.desc()).limit(1)).scalar_one_or_none()

    def _has_pricing_policy(self, product: Product, marketplace: str | None) -> bool:
        stmt = select(PricingPolicy.id).where(PricingPolicy.seller_id == product.seller_id, PricingPolicy.product_id == product.id, PricingPolicy.is_active.is_(True))
        if marketplace:
            stmt = stmt.where(PricingPolicy.marketplace == marketplace)
        return self._db.execute(stmt.limit(1)).first() is not None

    def _product_rows_or_count(self, metric: MetricDefinition, products: list[Product], group_by: tuple[str, ...], filters: dict[str, Any], limit: int, offset: int, *, evidence_table: str, status: str = "CALCULATED", missing_data: list[str] | None = None) -> dict[str, Any]:
        if group_by:
            grouped: dict[tuple[Any, ...], int] = defaultdict(int)
            for product in products:
                grouped[tuple(_product_group_value(product, key) for key in group_by)] += 1
            rows = [{**{key: value for key, value in zip(group_by, group)}, "value": count} for group, count in grouped.items()]
        else:
            rows = [{"product_id": str(product.id), "title": product.title, "category": product.category, "status": _enum(product.status)} for product in products]
        return self._result(metric, value=len(products), rows=rows[offset : offset + limit], filters_used=filters, status=status, missing_data=missing_data or [], unit="products", evidence=[_evidence(evidence_table, "seller_scope")])

    def _rows_or_count(self, metric: MetricDefinition, rows: list[Any], group_by: tuple[str, ...], filters: dict[str, Any], limit: int, offset: int, *, value_factory: Callable[[Any], Any] | None = None, row_factory: Callable[[Any], dict[str, Any]], evidence_table: str | None = None) -> dict[str, Any]:
        if group_by:
            grouped: dict[tuple[Any, ...], int] = defaultdict(int)
            for row in rows:
                grouped[tuple(_row_group_value(row, key) for key in group_by)] += 1
            payload_rows = [{**{key: value for key, value in zip(group_by, group)}, "value": count} for group, count in grouped.items()]
        else:
            payload_rows = [row_factory(row) for row in rows]
        value = len({value_factory(row) for row in rows}) if value_factory else len(rows)
        return self._result(metric, value=value, rows=payload_rows[offset : offset + limit], filters_used=filters, unit="count", evidence=[_evidence(evidence_table or metric.required_source_table, "seller_scope")])

    def _result(self, metric: MetricDefinition, *, value: Any = None, rows: list[dict[str, Any]] | None = None, filters_used: dict[str, Any], status: str = "CALCULATED", missing_data: list[str] | None = None, unit: str | None = None, currency: str | None = None, evidence: list[dict[str, Any]] | None = None, comparison: dict[str, Any] | None = None, limit: int | None = None, offset: int | None = None) -> dict[str, Any]:
        calculated_at = datetime.now(timezone.utc).isoformat()
        freshness = [{"source_table": metric.required_source_table, "date_field": metric.date_field, "computed_at": calculated_at}]
        return {
            "metric_key": metric.metric_key,
            "status": status,
            "value": value,
            "rows": rows or [],
            "comparison": comparison or {},
            "unit": unit or _unit(metric.metric_key),
            "currency": currency,
            "calculation_status": status,
            "missing_data": missing_data or [],
            "evidence": evidence or [_evidence(metric.required_source_table, "seller_scope")],
            "freshness": freshness,
            "filters_used": _json_filters(filters_used),
            "calculated_at": calculated_at,
            "computed_at": calculated_at,
            "pagination": {"limit": limit, "offset": offset} if limit is not None else None,
        }


def _sale_revenue(sale: SalesRecord) -> Decimal | None:
    if sale.line_total is not None:
        return Decimal(str(sale.line_total))
    if sale.unit_price is not None:
        return Decimal(str(sale.unit_price)) * Decimal(int(sale.quantity_sold or 0))
    return None


def _comparison_filters(filters: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    from_date = filters.get("from_date")
    to_date = filters.get("to_date")
    if from_date is None or to_date is None:
        return None, ["DATE_RANGE_REQUIRED_FOR_COMPARISON"]
    start_date = from_date.date() if isinstance(from_date, datetime) else from_date
    end_date = to_date.date() if isinstance(to_date, datetime) else to_date
    if start_date > end_date:
        return None, ["INVALID_DATE_RANGE"]
    period_days = (end_date - start_date).days + 1
    previous_to = start_date.fromordinal(start_date.toordinal() - 1)
    previous_from = previous_to.fromordinal(previous_to.toordinal() - period_days + 1)
    comparison = dict(filters)
    comparison["from_date"] = previous_from
    comparison["to_date"] = previous_to
    return comparison, []


def _period_payload(filters: dict[str, Any]) -> dict[str, str | None]:
    return {
        "from_date": filters.get("from_date").isoformat() if hasattr(filters.get("from_date"), "isoformat") else None,
        "to_date": filters.get("to_date").isoformat() if hasattr(filters.get("to_date"), "isoformat") else None,
    }


def _revenue_by_product(lines: list[dict[str, Any]]) -> dict[UUID, dict[str, Any]]:
    grouped: dict[UUID, dict[str, Any]] = {}
    for line in lines:
        product_id = line["product_id"]
        item = grouped.setdefault(product_id, {"product_id": product_id, "product_title": line["product_title"], "revenue": Decimal("0")})
        item["revenue"] += line["revenue"]
    return grouped


def _average_transaction_unit_price(lines: list[dict[str, Any]]) -> Decimal | None:
    revenue = Decimal("0")
    quantity = 0
    for line in lines:
        qty = int(line.get("quantity") or 0)
        if qty <= 0:
            continue
        revenue += Decimal(str(line["revenue"]))
        quantity += qty
    if quantity <= 0:
        return None
    return revenue / Decimal(quantity)


def _start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc) if not isinstance(value, datetime) else value


def _end(value: date) -> datetime:
    return datetime.combine(value, time.max, tzinfo=timezone.utc) if not isinstance(value, datetime) else value


def _bound_limit(value: int | None) -> int:
    return max(1, min(int(value or DEFAULT_LIMIT), MAX_LIMIT))


def _status_for_missing(missing: list[str]) -> str:
    return "PARTIAL" if missing else "CALCULATED"


def _evidence(source_table: str, source_id: Any) -> dict[str, Any]:
    return {"source_table": source_table, "source_id": str(source_id), "payload": {}}


def _enum(value: Any) -> str | None:
    return getattr(value, "value", value)


def _unit(metric_key: str) -> str:
    if "count" in metric_key:
        return "count"
    if "revenue" in metric_key or "profit" in metric_key or "capital" in metric_key or "value" in metric_key or "gap" in metric_key:
        return "money"
    if "rate" in metric_key:
        return "ratio"
    return "value"


def _currency(lines: list[dict[str, Any]]) -> str | None:
    currencies = {line.get("currency") for line in lines if line.get("currency")}
    return currencies.pop() if len(currencies) == 1 else ("BDT" if not currencies else None)


def _common_currency(lines: list[dict[str, Any]]) -> str | None:
    return _currency(lines)


def _bucket(value: datetime, interval: str) -> str:
    day = value.date()
    if interval == "week":
        return day.fromordinal(day.toordinal() - day.weekday()).isoformat()
    if interval == "month":
        return day.replace(day=1).isoformat()
    return day.isoformat()


def _group_sales(rows: list[dict[str, Any]], group_by: tuple[str, ...]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(row.get(field) for field in group_by)
        item = grouped.setdefault(key, {**{field: value for field, value in zip(group_by, key)}, "gross_revenue": Decimal("0"), "units_sold": 0, "order_count": 0})
        item["gross_revenue"] += row["revenue"]
        item["units_sold"] += row["net_units"]
        item["order_count"] += 1
    return list(grouped.values())


def _product_group_value(product: Product, key: str) -> Any:
    if key == "status":
        return _enum(product.status)
    return getattr(product, key, None)


def _row_group_value(row: Any, key: str) -> Any:
    if key == "category" and getattr(row, "product", None) is not None:
        return row.product.category
    value = getattr(row, key, None)
    return _enum(value)


def _json_filters(filters: dict[str, Any]) -> dict[str, Any]:
    return {key: (value.isoformat() if hasattr(value, "isoformat") else str(value)) for key, value in filters.items()}
