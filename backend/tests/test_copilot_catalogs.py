from __future__ import annotations

import unittest

from app.services.copilot.business_data_catalog import BusinessDataCatalogService
from app.services.copilot.metric_catalog import MetricCatalogService, MetricImplementationStatus
from app.services.copilot.query_constraints import (
    BusinessDomainKey,
    CatalogValidationError,
    DEFAULT_RESTRICTED_FIELDS,
    field_is_restricted,
)
from app.services.copilot.tool_registry import CopilotToolRegistry


REQUIRED_DOMAINS = {
    "PRODUCT_CATALOG",
    "SALES_REVENUE",
    "PROFIT_MARGIN",
    "INVENTORY",
    "COMPETITOR",
    "PRICING",
    "PROMOTION",
    "DEAD_STOCK",
    "SEO_VISIBILITY",
    "RECOMMENDATIONS",
    "ALERTS",
    "RAG_MEMORY",
    "COPILOT",
}


REQUIRED_METRICS = {
    "product_count",
    "active_product_count",
    "listed_product_count",
    "products_missing_cost_count",
    "products_missing_fee_policy_count",
    "products_missing_pricing_policy_count",
    "products_with_stock_count",
    "products_with_no_sales_count",
    "products_with_no_valid_imported_sales_count",
    "gross_revenue",
    "net_revenue",
    "units_sold",
    "order_count",
    "average_order_value",
    "top_products_by_revenue",
    "revenue_trend",
    "previous_period_revenue",
    "revenue_change",
    "percentage_revenue_change",
    "products_with_revenue_decline",
    "average_selling_price_delta",
    "estimated_profit",
    "margin_rate",
    "products_excluded_from_profit",
    "current_inventory_value",
    "low_stock_product_count",
    "stockout_risk_count",
    "dead_stock_count",
    "locked_capital",
    "competitor_undercut_count",
    "competitor_price_gap",
    "pending_recommendation_count",
    "unresolved_alert_count",
}


class CopilotCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.business_catalog = BusinessDataCatalogService()
        self.metric_catalog = MetricCatalogService()

    def test_all_required_domains_are_registered(self):
        self.assertEqual(REQUIRED_DOMAINS, {domain.domain_key.value for domain in self.business_catalog.list_domains()})

    def test_all_required_metrics_are_registered(self):
        self.assertEqual(REQUIRED_METRICS, {metric.metric_key for metric in self.metric_catalog.list_metrics()})

    def test_restricted_fields_are_excluded_from_domains(self):
        for domain in self.business_catalog.list_domains():
            with self.subTest(domain=domain.domain_key.value):
                self.assertTrue(set(DEFAULT_RESTRICTED_FIELDS).issubset(set(domain.restricted_fields)))
                self.assertFalse(
                    [field for field in domain.safe_fields if field_is_restricted(field)],
                    f"{domain.domain_key.value} exposes restricted fields",
                )

    def test_every_domain_requires_seller_scoping(self):
        for domain in self.business_catalog.list_domains():
            with self.subTest(domain=domain.domain_key.value):
                self.assertEqual("seller_id", domain.seller_field)
                self.assertIn("seller_id", domain.supported_filters)
                self.assertIn("seller_id", domain.query_constraint.required_filters)

    def test_unknown_domain_fails_safely(self):
        with self.assertRaisesRegex(CatalogValidationError, "Unknown business domain"):
            self.business_catalog.get_domain("UNKNOWN_DOMAIN")

    def test_unknown_metric_fails_safely(self):
        with self.assertRaisesRegex(CatalogValidationError, "Unknown metric"):
            self.metric_catalog.get_metric("unknown_metric")

    def test_metric_validation_rejects_unsupported_filters(self):
        with self.assertRaisesRegex(CatalogValidationError, "Unsupported filter"):
            self.metric_catalog.validate_metric_query(
                "gross_revenue",
                filters={"seller_id": "seller-1", "raw_sql": "select *"},
            )

    def test_metric_validation_rejects_unsupported_group_by(self):
        with self.assertRaisesRegex(CatalogValidationError, "Unsupported group_by"):
            self.metric_catalog.validate_metric_query(
                "gross_revenue",
                filters={"seller_id": "seller-1"},
                group_by=["password"],
            )

    def test_metric_validation_requires_seller_filter(self):
        with self.assertRaisesRegex(CatalogValidationError, "Missing required filter"):
            self.metric_catalog.validate_metric_query("gross_revenue", filters={"product_id": "product-1"})

    def test_metric_catalog_never_exposes_secrets(self):
        for metric in self.metric_catalog.list_metrics():
            fields = (
                *metric.allowed_filters,
                *metric.allowed_group_by_fields,
                *metric.required_data_dependencies,
                *metric.evidence_mapping,
            )
            with self.subTest(metric=metric.metric_key):
                self.assertFalse([field for field in fields if field_is_restricted(field)])

    def test_metric_catalog_maps_metrics_to_evidence_sources(self):
        for metric in self.metric_catalog.list_metrics():
            with self.subTest(metric=metric.metric_key):
                self.assertGreaterEqual(len(metric.evidence_mapping), 1)
                self.assertIn(metric.required_source_table, metric.evidence_mapping)

    def test_metric_capability_contract_metadata_is_complete(self):
        handler_metrics = {
            metric
            for tool in CopilotToolRegistry().list_tools()
            if tool.name == "run_seller_metric_query"
            for metric in tool.catalog_metrics
        }
        self.metric_catalog.validate_capability_contract(handler_metrics)
        for metric in self.metric_catalog.list_metrics():
            with self.subTest(metric=metric.metric_key):
                self.assertEqual("seller_id", metric.seller_scope_path)
                self.assertTrue(metric.evidence_mapper)
                if metric.is_money_metric:
                    self.assertTrue(metric.currency_behavior)
                if metric.implementation_status == MetricImplementationStatus.UNSUPPORTED:
                    self.assertTrue(metric.unsupported_reason)

    def test_net_revenue_is_not_declared_as_executable_without_deductions(self):
        metric = self.metric_catalog.get_metric("net_revenue")

        self.assertEqual(MetricImplementationStatus.UNSUPPORTED, metric.implementation_status)
        self.assertIsNone(metric.executor_handler)
        self.assertIn("deductions", metric.unsupported_reason)

    def test_question_domain_lookup_is_allowlisted(self):
        self.assertEqual(
            BusinessDomainKey.SALES_REVENUE,
            self.business_catalog.get_domain_for_question("Why is revenue down?").domain_key,
        )
        self.assertIsNone(self.business_catalog.get_domain_for_question("Can the sky be green?"))

    def test_tool_registry_references_registered_catalog_entries(self):
        registry = CopilotToolRegistry()
        for tool in registry.list_tools():
            with self.subTest(tool=tool.name):
                for domain in tool.catalog_domains:
                    self.business_catalog.get_domain(domain)
                for metric in tool.catalog_metrics:
                    self.metric_catalog.get_metric(metric)


if __name__ == "__main__":
    unittest.main()
