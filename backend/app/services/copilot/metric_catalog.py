from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.services.copilot.query_constraints import (
    BusinessDomainKey,
    CatalogValidationError,
    QueryConstraint,
    ensure_no_restricted_fields,
)


class MetricCalculationMethod(str, Enum):
    COUNT = "COUNT"
    SUM = "SUM"
    RATIO = "RATIO"
    TREND = "TREND"
    TOP_N = "TOP_N"
    DERIVED = "DERIVED"


class MetricImplementationStatus(str, Enum):
    IMPLEMENTED = "IMPLEMENTED"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    metric_key: str
    domain: BusinessDomainKey
    description: str
    required_source_table: str
    required_source_model: str
    required_seller_filter: str
    allowed_filters: tuple[str, ...]
    allowed_group_by_fields: tuple[str, ...]
    date_field: str | None
    calculation_method: MetricCalculationMethod
    required_data_dependencies: tuple[str, ...]
    missing_data_behavior: str
    evidence_mapping: tuple[str, ...]
    implementation_status: MetricImplementationStatus = MetricImplementationStatus.IMPLEMENTED
    executor_handler: str | None = None
    unsupported_reason: str | None = None
    required_models: tuple[str, ...] = ()
    required_fields: tuple[str, ...] = ()
    allowed_dimensions: tuple[str, ...] = ()
    seller_scope_path: str = "seller_id"
    evidence_mapper: tuple[str, ...] = ()
    completeness_requirements: tuple[str, ...] = ()
    currency_behavior: str | None = None
    money_behavior: str | None = None

    def __post_init__(self) -> None:
        if self.required_seller_filter != "seller_id":
            raise CatalogValidationError(f"{self.metric_key} must require seller_id scoping.")
        if self.seller_scope_path != "seller_id":
            raise CatalogValidationError(f"{self.metric_key} must define seller_id seller scope metadata.")
        if self.implementation_status == MetricImplementationStatus.UNSUPPORTED and not self.unsupported_reason:
            raise CatalogValidationError(f"{self.metric_key} is unsupported but has no unsupported_reason.")
        if self.implementation_status != MetricImplementationStatus.UNSUPPORTED and not self.executor_handler:
            raise CatalogValidationError(f"{self.metric_key} must name an executor handler.")
        if not self.evidence_mapper:
            raise CatalogValidationError(f"{self.metric_key} must define evidence mapping.")
        ensure_no_restricted_fields(
            (
                *self.allowed_filters,
                *self.allowed_group_by_fields,
                *self.evidence_mapping,
                *self.evidence_mapper,
                *self.required_data_dependencies,
                *self.required_fields,
                *self.allowed_dimensions,
            )
        )

    @property
    def query_constraint(self) -> QueryConstraint:
        return QueryConstraint(
            seller_field=self.required_seller_filter,
            product_field="product_id" if "product_id" in self.allowed_filters else None,
            date_field=self.date_field,
            allowed_filters=self.allowed_filters,
            allowed_group_by=self.allowed_group_by_fields,
        )

    @property
    def is_selectable_for_execution(self) -> bool:
        return self.implementation_status in {
            MetricImplementationStatus.IMPLEMENTED,
            MetricImplementationStatus.PARTIAL,
        } and bool(self.executor_handler)

    @property
    def is_money_metric(self) -> bool:
        if self.metric_key.endswith("_count") or self.calculation_method == MetricCalculationMethod.COUNT:
            return False
        if self.metric_key.endswith("_rate") or self.metric_key.startswith("percentage_"):
            return False
        return any(token in self.metric_key for token in ("revenue", "profit", "price", "capital", "value", "gap"))


def _metric(
    metric_key: str,
    domain: BusinessDomainKey,
    description: str,
    source_table: str,
    source_model: str,
    method: MetricCalculationMethod,
    *,
    date_field: str | None = None,
    filters: tuple[str, ...] = ("seller_id", "product_id", "category", "marketplace", "from_date", "to_date"),
    group_by: tuple[str, ...] = (),
    dependencies: tuple[str, ...] = (),
    missing: str = "Return missing-data guidance instead of inferring unavailable business facts.",
    evidence: tuple[str, ...] | None = None,
    status: MetricImplementationStatus = MetricImplementationStatus.IMPLEMENTED,
    handler: str | None = None,
    unsupported_reason: str | None = None,
    required_fields: tuple[str, ...] = (),
    completeness: tuple[str, ...] = (),
    currency_behavior: str | None = None,
    money_behavior: str | None = None,
) -> MetricDefinition:
    evidence_mapping = evidence or (source_table,)
    money_tokens = ("revenue", "profit", "price", "capital", "value", "money", "gap")
    resolved_currency_behavior = currency_behavior
    resolved_money_behavior = money_behavior
    if any(token in metric_key for token in money_tokens):
        resolved_currency_behavior = resolved_currency_behavior or "Use transaction currency when homogeneous; return null currency when mixed; default BDT only when source rows omit currency."
        resolved_money_behavior = resolved_money_behavior or "Use Decimal arithmetic; do not round intermediate values."
    return MetricDefinition(
        metric_key=metric_key,
        domain=domain,
        description=description,
        required_source_table=source_table,
        required_source_model=source_model,
        required_seller_filter="seller_id",
        allowed_filters=tuple(dict.fromkeys(("seller_id", *filters))),
        allowed_group_by_fields=group_by,
        date_field=date_field,
        calculation_method=method,
        required_data_dependencies=dependencies,
        missing_data_behavior=missing,
        evidence_mapping=evidence_mapping,
        implementation_status=status,
        executor_handler=handler or (f"_{metric_key}" if status != MetricImplementationStatus.UNSUPPORTED else None),
        unsupported_reason=unsupported_reason,
        required_models=(source_model,),
        required_fields=required_fields,
        allowed_dimensions=group_by,
        seller_scope_path="seller_id",
        evidence_mapper=evidence_mapping,
        completeness_requirements=completeness,
        currency_behavior=resolved_currency_behavior,
        money_behavior=resolved_money_behavior,
    )


METRICS: dict[str, MetricDefinition] = {
    "product_count": _metric("product_count", BusinessDomainKey.PRODUCT_CATALOG, "Count seller products.", "products", "Product", MetricCalculationMethod.COUNT, date_field="created_at", group_by=("category", "marketplace", "status")),
    "active_product_count": _metric("active_product_count", BusinessDomainKey.PRODUCT_CATALOG, "Count active/listed seller products when status is available.", "products", "Product", MetricCalculationMethod.COUNT, date_field="created_at", filters=("seller_id", "status", "category", "marketplace"), group_by=("category", "marketplace", "status"), missing="If product status is absent, report that active/listed count is unavailable."),
    "listed_product_count": _metric("listed_product_count", BusinessDomainKey.PRODUCT_CATALOG, "Count products with active marketplace listings.", "product_marketplace_listings", "ProductMarketplaceListing", MetricCalculationMethod.COUNT, date_field="created_at", filters=("seller_id", "product_id", "category", "marketplace", "from_date", "to_date", "status"), group_by=("category", "marketplace", "status"), dependencies=("products", "product_marketplace_listings"), missing="Marketplace listing data is required for listed product counts.", evidence=("products", "product_marketplace_listings")),
    "products_missing_cost_count": _metric("products_missing_cost_count", BusinessDomainKey.PRODUCT_CATALOG, "Count products missing cost or landed cost.", "products", "Product", MetricCalculationMethod.COUNT, group_by=("category", "marketplace"), dependencies=("cost_price",), missing="Missing cost excludes products from profit calculations."),
    "products_missing_fee_policy_count": _metric("products_missing_fee_policy_count", BusinessDomainKey.PROFIT_MARGIN, "Count products without applicable active marketplace fee policy.", "marketplace_fee_policies", "MarketplaceFeePolicy", MetricCalculationMethod.COUNT, group_by=("category", "marketplace"), dependencies=("products", "marketplace_fee_policies"), missing="Fee policy coverage is required before profit metrics are exact.", evidence=("products", "marketplace_fee_policies")),
    "products_missing_pricing_policy_count": _metric("products_missing_pricing_policy_count", BusinessDomainKey.PRICING, "Count products without active pricing policy.", "pricing_policies", "PricingPolicy", MetricCalculationMethod.COUNT, group_by=("category", "marketplace"), dependencies=("products", "pricing_policies"), missing="Pricing policy coverage is required before pricing automation metrics are exact.", evidence=("products", "pricing_policies")),
    "products_with_stock_count": _metric("products_with_stock_count", BusinessDomainKey.INVENTORY, "Count products with positive current stock.", "products", "Product", MetricCalculationMethod.COUNT, group_by=("category", "marketplace"), dependencies=("stock_quantity",)),
    "products_with_no_sales_count": _metric("products_with_no_sales_count", BusinessDomainKey.SALES_REVENUE, "Count products with no completed/fulfilled sales only when sales completeness is known.", "sales_records", "SalesRecord", MetricCalculationMethod.COUNT, date_field="sold_at", group_by=("category", "marketplace"), dependencies=("products", "sales_records", "sales_completeness_known"), missing="Do not treat missing sales history as zero sales unless sales completeness is known.", evidence=("products", "sales_records"), handler="_products_with_no_valid_imported_sales_count"),
    "products_with_no_valid_imported_sales_count": _metric("products_with_no_valid_imported_sales_count", BusinessDomainKey.SALES_REVENUE, "Count products with no valid imported completed/fulfilled sales only when coverage is complete.", "sales_records", "SalesRecord", MetricCalculationMethod.COUNT, date_field="sold_at", group_by=("category", "marketplace"), dependencies=("products", "sales_records", "sales_data_coverage"), missing="Do not claim no sales without complete sales_data_coverage for the requested scope.", evidence=("products", "sales_records", "sales_data_coverage")),
    "gross_revenue": _metric("gross_revenue", BusinessDomainKey.SALES_REVENUE, "Sum completed/fulfilled sales revenue using Decimal money.", "sales_records", "SalesRecord", MetricCalculationMethod.SUM, date_field="sold_at", group_by=("product_id", "category", "marketplace"), dependencies=("completed_or_fulfilled_sales", "product_price_at_sale_or_safe_revenue_source"), missing="Revenue is unavailable when no reliable sale price/revenue basis exists.", required_fields=("status", "sold_at", "unit_price", "line_total", "quantity_sold", "is_test_order", "currency"), completeness=("valid_completed_or_fulfilled_sales",)),
    "net_revenue": _metric("net_revenue", BusinessDomainKey.SALES_REVENUE, "Gross revenue adjusted by supported discounts, refunds, returns, and marketplace deductions.", "sales_records", "SalesRecord", MetricCalculationMethod.DERIVED, date_field="sold_at", group_by=("product_id", "category", "marketplace"), dependencies=("completed_or_fulfilled_sales", "discounts", "refund_amounts", "marketplace_deductions"), missing="Net revenue is unavailable because reliable monetary discounts, refund amounts, and marketplace deductions are not stored in sales_records.", status=MetricImplementationStatus.UNSUPPORTED, unsupported_reason="sales_records only stores gross transaction price plus returned/restocked unit counts; it does not store monetary discounts, refund amounts, marketplace deductions, or equivalent net-revenue inputs."),
    "units_sold": _metric("units_sold", BusinessDomainKey.SALES_REVENUE, "Sum completed/fulfilled units sold.", "sales_records", "SalesRecord", MetricCalculationMethod.SUM, date_field="sold_at", group_by=("product_id", "category", "marketplace"), dependencies=("completed_or_fulfilled_sales",)),
    "order_count": _metric("order_count", BusinessDomainKey.SALES_REVENUE, "Count completed/fulfilled sales records or orders.", "sales_records", "SalesRecord", MetricCalculationMethod.COUNT, date_field="sold_at", group_by=("product_id", "category", "marketplace"), dependencies=("completed_or_fulfilled_sales",)),
    "average_order_value": _metric("average_order_value", BusinessDomainKey.SALES_REVENUE, "Gross revenue divided by order count.", "sales_records", "SalesRecord", MetricCalculationMethod.RATIO, date_field="sold_at", group_by=("category", "marketplace"), dependencies=("gross_revenue", "order_count"), missing="AOV is unavailable when order count is zero or unknown."),
    "top_products_by_revenue": _metric("top_products_by_revenue", BusinessDomainKey.SALES_REVENUE, "Rank products by completed/fulfilled revenue.", "sales_records", "SalesRecord", MetricCalculationMethod.TOP_N, date_field="sold_at", group_by=("product_id", "category"), dependencies=("gross_revenue", "products"), evidence=("sales_records", "products")),
    "revenue_trend": _metric("revenue_trend", BusinessDomainKey.SALES_REVENUE, "Revenue by day/week/month for completed/fulfilled sales.", "sales_records", "SalesRecord", MetricCalculationMethod.TREND, date_field="sold_at", filters=("seller_id", "product_id", "category", "marketplace", "from_date", "to_date", "interval"), group_by=("day", "week", "month", "product_id", "category"), dependencies=("gross_revenue",)),
    "previous_period_revenue": _metric("previous_period_revenue", BusinessDomainKey.SALES_REVENUE, "Revenue for the immediately preceding equal-length comparison period.", "sales_records", "SalesRecord", MetricCalculationMethod.DERIVED, date_field="sold_at", group_by=("product_id", "category", "marketplace"), dependencies=("gross_revenue", "comparison_period"), missing="Unavailable when a comparison period cannot be derived or has no reliable sales records.", required_fields=("sold_at", "unit_price", "line_total", "quantity_sold", "currency")),
    "revenue_change": _metric("revenue_change", BusinessDomainKey.SALES_REVENUE, "Current-period revenue minus previous-period revenue.", "sales_records", "SalesRecord", MetricCalculationMethod.DERIVED, date_field="sold_at", group_by=("product_id", "category", "marketplace"), dependencies=("gross_revenue", "previous_period_revenue"), missing="Unavailable when previous-period revenue cannot be calculated.", required_fields=("sold_at", "unit_price", "line_total", "quantity_sold", "currency")),
    "percentage_revenue_change": _metric("percentage_revenue_change", BusinessDomainKey.SALES_REVENUE, "Revenue change divided by previous-period revenue.", "sales_records", "SalesRecord", MetricCalculationMethod.RATIO, date_field="sold_at", group_by=("product_id", "category", "marketplace"), dependencies=("revenue_change", "previous_period_revenue"), missing="Unavailable when previous-period revenue is zero or unknown.", required_fields=("sold_at", "unit_price", "line_total", "quantity_sold", "currency")),
    "products_with_revenue_decline": _metric("products_with_revenue_decline", BusinessDomainKey.SALES_REVENUE, "Products whose current-period revenue is lower than the comparable previous period.", "sales_records", "SalesRecord", MetricCalculationMethod.DERIVED, date_field="sold_at", group_by=("product_id", "category"), dependencies=("gross_revenue", "previous_period_revenue", "products"), evidence=("sales_records", "products"), required_fields=("product_id", "sold_at", "unit_price", "line_total", "quantity_sold", "currency")),
    "average_selling_price_delta": _metric("average_selling_price_delta", BusinessDomainKey.SALES_REVENUE, "Current-period average historical transaction selling price minus previous-period value.", "sales_records", "SalesRecord", MetricCalculationMethod.DERIVED, date_field="sold_at", group_by=("product_id", "category", "marketplace"), dependencies=("transaction_unit_price_or_line_total_quantity", "comparison_period"), missing="Unavailable when transaction price or previous-period comparison data is missing.", required_fields=("sold_at", "unit_price", "line_total", "quantity_sold", "currency")),
    "estimated_profit": _metric("estimated_profit", BusinessDomainKey.PROFIT_MARGIN, "Estimate profit only when cost and fee policy are available.", "sales_records", "SalesRecord", MetricCalculationMethod.DERIVED, date_field="sold_at", group_by=("product_id", "category", "marketplace"), dependencies=("gross_revenue", "products.cost_price", "marketplace_fee_policies"), missing="Do not calculate profit if cost or fee policy is missing.", evidence=("sales_records", "products", "marketplace_fee_policies")),
    "margin_rate": _metric("margin_rate", BusinessDomainKey.PROFIT_MARGIN, "Estimated profit divided by revenue or pricing analytics margin rate.", "pricing_analytics_snapshots", "PricingAnalyticsSnapshot", MetricCalculationMethod.RATIO, date_field="calculated_at", group_by=("product_id", "category", "marketplace"), dependencies=("estimated_profit_or_pricing_analytics",), missing="Margin rate is unavailable for products excluded from profit."),
    "products_excluded_from_profit": _metric("products_excluded_from_profit", BusinessDomainKey.PROFIT_MARGIN, "List/count products excluded from profit due to missing cost or fee policy.", "products", "Product", MetricCalculationMethod.COUNT, group_by=("category", "marketplace"), dependencies=("products", "marketplace_fee_policies", "cost_price"), missing="Return exclusions instead of profit."),
    "current_inventory_value": _metric("current_inventory_value", BusinessDomainKey.INVENTORY, "Current stock value using stock quantity and cost.", "products", "Product", MetricCalculationMethod.DERIVED, group_by=("product_id", "category", "marketplace"), dependencies=("current_stock", "cost_price"), missing="Unavailable when cost or current stock is missing."),
    "low_stock_product_count": _metric("low_stock_product_count", BusinessDomainKey.INVENTORY, "Count products with low stock or reorder signal.", "reorder_recommendations", "ReorderRecommendation", MetricCalculationMethod.COUNT, date_field="generated_at", group_by=("category", "marketplace", "risk_level"), dependencies=("reorder_recommendations_or_inventory_thresholds",)),
    "stockout_risk_count": _metric("stockout_risk_count", BusinessDomainKey.INVENTORY, "Count high/critical stockout risk assessments.", "inventory_risk_assessments", "InventoryRiskAssessment", MetricCalculationMethod.COUNT, date_field="assessed_at", filters=("seller_id", "product_id", "category", "marketplace", "from_date", "to_date", "risk_level"), group_by=("risk_level", "product_id", "category"), dependencies=("inventory_risk_assessments",)),
    "dead_stock_count": _metric("dead_stock_count", BusinessDomainKey.DEAD_STOCK, "Count dead or at-risk stock assessments.", "dead_stock_assessments", "DeadStockAssessment", MetricCalculationMethod.COUNT, date_field="assessed_at", filters=("seller_id", "product_id", "category", "marketplace", "from_date", "to_date", "classification"), group_by=("classification", "product_id", "category"), dependencies=("dead_stock_assessments",)),
    "locked_capital": _metric("locked_capital", BusinessDomainKey.DEAD_STOCK, "Estimate locked capital from eligible dead-stock quantity and product cost.", "dead_stock_capital_recovery_estimates", "DeadStockCapitalRecoveryEstimate", MetricCalculationMethod.DERIVED, date_field="estimated_at", group_by=("product_id", "category"), dependencies=("eligible_quantity", "product_cost_or_capital_recovery_estimate"), missing="Unavailable when eligible quantity or product cost is missing.", evidence=("dead_stock_assessments", "dead_stock_capital_recovery_estimates", "products")),
    "competitor_undercut_count": _metric("competitor_undercut_count", BusinessDomainKey.COMPETITOR, "Count competitor events/snapshots where competitor price undercuts seller price.", "competitor_events", "CompetitorEvent", MetricCalculationMethod.COUNT, date_field="detected_at", filters=("seller_id", "product_id", "category", "marketplace", "from_date", "to_date", "competitor_id", "severity"), group_by=("product_id", "category", "competitor_id", "severity"), dependencies=("competitor_events_or_snapshots", "seller_price"), evidence=("competitor_events", "competitor_snapshots", "products")),
    "competitor_price_gap": _metric("competitor_price_gap", BusinessDomainKey.COMPETITOR, "Calculate seller price minus competitor price where both are available.", "competitor_snapshots", "CompetitorSnapshot", MetricCalculationMethod.DERIVED, date_field="captured_at", filters=("seller_id", "product_id", "category", "marketplace", "from_date", "to_date", "competitor_id"), group_by=("product_id", "competitor_id", "category"), dependencies=("competitor_price", "seller_price"), missing="Unavailable when either seller or competitor price is missing.", evidence=("competitor_snapshots", "products")),
    "pending_recommendation_count": _metric("pending_recommendation_count", BusinessDomainKey.RECOMMENDATIONS, "Count open/pending recommendation records across recommendation engines.", "recommendations", "Recommendation", MetricCalculationMethod.COUNT, date_field="created_at", filters=("seller_id", "product_id", "category", "marketplace", "from_date", "to_date", "recommendation_status", "source"), group_by=("source", "recommendation_status", "product_id", "category"), dependencies=("recommendations", "reorder_recommendations", "dynamic_pricing_recommendations", "dead_stock_recovery_recommendations"), evidence=("recommendations", "reorder_recommendations", "dynamic_pricing_recommendations", "dead_stock_recovery_recommendations")),
    "unresolved_alert_count": _metric("unresolved_alert_count", BusinessDomainKey.ALERTS, "Count unread/undelivered/unresolved seller alerts.", "alerts", "Alert", MetricCalculationMethod.COUNT, date_field="created_at", filters=("seller_id", "product_id", "category", "marketplace", "from_date", "to_date", "alert_type", "urgency_level", "delivery_status", "status"), group_by=("alert_type", "urgency_level", "delivery_status", "product_id"), dependencies=("alerts",), evidence=("alerts", "telegram_inventory_alerts", "alert_delivery_logs")),
}


class MetricCatalogService:
    def __init__(self, metrics: dict[str, MetricDefinition] | None = None) -> None:
        self._metrics = metrics or METRICS

    def list_metrics(self) -> list[MetricDefinition]:
        return list(self._metrics.values())

    def get_metric(self, metric_key: str) -> MetricDefinition:
        try:
            return self._metrics[metric_key]
        except KeyError as exc:
            raise CatalogValidationError(f"Unknown metric: {metric_key}") from exc

    def validate_metric_query(
        self,
        metric_key: str,
        *,
        filters: dict[str, Any] | None = None,
        group_by: tuple[str, ...] | list[str] | None = None,
    ) -> MetricDefinition:
        metric = self.get_metric(metric_key)
        metric.query_constraint.validate(filters=filters, group_by=group_by)
        return metric

    def get_missing_data_guidance(self, metric_key: str) -> str:
        return self.get_metric(metric_key).missing_data_behavior

    def selectable_metric_keys(self) -> set[str]:
        return {metric.metric_key for metric in self.list_metrics() if metric.is_selectable_for_execution}

    def validate_capability_contract(self, executor_handlers: set[str] | dict[str, Any]) -> None:
        validate_metric_capability_contract(self._metrics, set(executor_handlers))


def validate_metric_capability_contract(metrics: dict[str, MetricDefinition], executor_handlers: set[str]) -> None:
    errors: list[str] = []
    for metric_key, metric in sorted(metrics.items()):
        if not metric.seller_scope_path:
            errors.append(f"{metric_key}: missing seller-scope metadata")
        if not metric.evidence_mapper:
            errors.append(f"{metric_key}: missing evidence mapper")
        if metric.is_money_metric and not metric.currency_behavior:
            errors.append(f"{metric_key}: missing currency behavior")
        if metric.implementation_status == MetricImplementationStatus.UNSUPPORTED and not metric.unsupported_reason:
            errors.append(f"{metric_key}: unsupported metric missing reason")
        if metric.implementation_status != MetricImplementationStatus.UNSUPPORTED:
            if not metric.executor_handler:
                errors.append(f"{metric_key}: implemented metric missing executor handler")
            elif metric.metric_key not in executor_handlers:
                errors.append(f"{metric_key}: executor handler {metric.executor_handler} not registered")

    undeclared = sorted(set(executor_handlers) - set(metrics))
    if undeclared:
        errors.append(f"Executor handlers without catalog metrics: {', '.join(undeclared)}")

    if errors:
        raise CatalogValidationError("Metric capability contract invalid: " + "; ".join(errors))
