from __future__ import annotations

from datetime import date
from decimal import Decimal
import unittest
from uuid import UUID, uuid4

from app.services.copilot.tool_registry import (
    CopilotToolContext,
    CopilotToolRegistry,
    CopilotToolSafetyLevel,
    SOURCE_TOOL_SPECS,
    ToolExecutionStatus,
)


SELLER_ID = UUID("00000000-0000-0000-0000-000000000001")
PRODUCT_ID = UUID("00000000-0000-0000-0000-000000000010")
OTHER_PRODUCT_ID = UUID("00000000-0000-0000-0000-000000000099")


def _evidence(source_table: str = "test_source") -> dict:
    return {"source_table": source_table, "source_id": str(uuid4()), "payload": {"signal": "test"}}


class _FakeDataAccess:
    def __init__(self, *, allow_product: bool = True, missing: bool = False) -> None:
        self.allow_product = allow_product
        self.missing = missing
        self.verified_products: list[UUID] = []
        self.called_tools: list[str] = []
        self.mutations = 0

    def verify_product_owned(self, *, seller_id, product_id):
        self.verified_products.append(product_id)
        return self.allow_product and seller_id == SELLER_ID and product_id == PRODUCT_ID

    def _rows(self, tool: str, row: dict):
        self.called_tools.append(tool)
        if self.missing:
            return [], [f"No data for {tool}."]
        return [row | {"evidence": _evidence(tool)}], []

    def _payload(self, tool: str, payload: dict):
        self.called_tools.append(tool)
        if self.missing:
            return payload | {"evidence": [], "confidence": "NO_CONTEXT"}, [f"No data for {tool}."]
        return payload, []

    def get_business_overview(self, **kwargs):
        return self._payload(
            "get_business_overview",
            {"overview": {"total_products": 2}, "evidence": [_evidence("products")]},
        )

    def count_products(self, **kwargs):
        return self._payload(
            "count_products",
            {"count": 2, "filters_used": kwargs.get("filters", {}), "evidence": [_evidence("products")]},
        )

    def list_products(self, **kwargs):
        return self._payload(
            "list_products",
            {
                "products": [{"id": str(PRODUCT_ID), "title": "Product A", "evidence": _evidence("products")}],
                "pagination": {"total": 1, "limit": kwargs.get("limit"), "offset": kwargs.get("offset")},
                "evidence": [_evidence("products")],
            },
        )

    def search_products(self, **kwargs):
        return self._payload(
            "search_products",
            {"products": [{"id": str(PRODUCT_ID), "title": "Product A"}], "confidence": "HIGH", "evidence": [_evidence("products")]},
        )

    def get_product_profile(self, **kwargs):
        return self._payload(
            "get_product_profile",
            {"product": {"id": str(PRODUCT_ID), "name": "Product A"}, "evidence": [_evidence("products")]},
        )

    def get_products_missing_setup(self, **kwargs):
        return self._payload(
            "get_products_missing_setup",
            {
                "products": [{"product": {"id": str(PRODUCT_ID), "title": "Product A"}, "missing_setup_fields": ["MARKETPLACE_FEE_POLICY"]}],
                "pagination": {"total": 1, "limit": kwargs.get("limit"), "offset": kwargs.get("offset")},
                "evidence": [_evidence("products")],
            },
        )

    def get_inventory_summary(self, **kwargs):
        return self._payload("get_inventory_summary", {"summary": {"total_products_with_stock": 1}, "freshness": [], "evidence": [_evidence("products")]})

    def get_sales_velocity_summary(self, **kwargs):
        return self._payload("get_sales_velocity_summary", {"summary": {"products_with_velocity": 1}, "top_products": [], "freshness": [], "evidence": [_evidence("sales_velocity")]})

    def get_stockout_summary(self, **kwargs):
        return self._payload("get_stockout_summary", {"summary": {"predicted_stockout_count": 1}, "top_affected_products": [], "freshness": [], "evidence": [_evidence("stockout_predictions")]})

    def get_reorder_summary(self, **kwargs):
        return self._payload("get_reorder_summary", {"summary": {"open_reorder_count": 1}, "top_affected_products": [], "freshness": [], "evidence": [_evidence("reorder_recommendations")]})

    def get_inventory_aging_summary(self, **kwargs):
        return self._payload("get_inventory_aging_summary", {"summary": {"aged_inventory_count": 1}, "top_affected_products": [], "freshness": [], "evidence": [_evidence("inventory_aging_snapshots")]})

    def get_product_setup_summary(self, **kwargs):
        return self._payload("get_product_setup_summary", {"summary": {"total_products": 1}, "freshness": [], "evidence": [_evidence("products")]})

    def get_competitor_summary(self, **kwargs):
        return self._payload("get_competitor_summary", {"summary": {"tracked_competitor_count": 1}, "freshness": [], "evidence": [_evidence("competitor_events")]})

    def get_competitor_price_change_summary(self, **kwargs):
        return self._payload("get_competitor_price_change_summary", {"summary": {"price_drop_count": 1}, "latest_price_change_events": [], "freshness": [], "evidence": [_evidence("competitor_events")]})

    def get_competitor_undercut_summary(self, **kwargs):
        return self._payload("get_competitor_undercut_summary", {"summary": {"undercut_product_count": 1}, "top_affected_products": [], "freshness": [], "evidence": [_evidence("competitor_snapshots")]})

    def get_market_opportunity_summary(self, **kwargs):
        return self._payload("get_market_opportunity_summary", {"summary": {"open_opportunity_count": 1}, "top_opportunities": [], "freshness": [], "evidence": [_evidence("market_opportunities")]})

    def get_scrape_health_summary(self, **kwargs):
        return self._payload("get_scrape_health_summary", {"summary": {"completed_scrape_count": 1}, "freshness": [], "evidence": [_evidence("scrape_runs")]})

    def get_pricing_summary(self, **kwargs):
        return self._payload("get_pricing_summary", {"summary": {"products_missing_fee_policy": 0}, "freshness": [], "evidence": [_evidence("pricing_policies")]})

    def get_fee_policy_summary(self, **kwargs):
        return self._payload("get_fee_policy_summary", {"summary": {"products_missing_fee_policy": 0}, "freshness": [], "evidence": [_evidence("marketplace_fee_policies")]})

    def get_pricing_policy_summary(self, **kwargs):
        return self._payload("get_pricing_policy_summary", {"summary": {"products_missing_pricing_policy": 0}, "freshness": [], "evidence": [_evidence("pricing_policies")]})

    def get_elasticity_summary(self, **kwargs):
        return self._payload("get_elasticity_summary", {"summary": {"products_lacking_elasticity_evidence": 0}, "top_pricing_risks": [], "freshness": [], "evidence": [_evidence("demand_elasticity_estimates")]})

    def get_seller_price_history_summary(self, **kwargs):
        return self._payload("get_seller_price_history_summary", {"summary": {"seller_price_change_count": 1, "competitor_price_history_included": False}, "latest_price_changes": [], "freshness": [], "evidence": [_evidence("product_price_history")]})

    def get_promotion_summary(self, **kwargs):
        return self._payload("get_promotion_summary", {"summary": {"products_suitable_for_promotion": 0}, "freshness": [], "evidence": [_evidence("dead_stock_recovery_recommendations")]})

    def get_promotion_outcome_summary(self, **kwargs):
        return self._payload("get_promotion_outcome_summary", {"summary": {"completed_promotion_result_count": 1}, "top_performing_promotions": [], "underperforming_promotions": [], "freshness": [], "evidence": [_evidence("promotion_results")]})

    def get_promotion_plans(self, **kwargs):
        return self._payload("get_promotion_plans", {"rows": [{"title": "Plan A", "evidence": _evidence("promotion_plans")}], "freshness": [], "evidence": [_evidence("promotion_plans")]})

    def get_promotion_results(self, **kwargs):
        return self._payload("get_promotion_results", {"rows": [{"result_status": "PARTIAL", "evidence": _evidence("promotion_results")}], "freshness": [], "evidence": [_evidence("promotion_results")]})

    def compare_promotion_performance(self, **kwargs):
        return self._payload("compare_promotion_performance", {"summary": {"promotion_result_count": 1}, "freshness": [], "evidence": [_evidence("promotion_results")]})

    def get_price_history(self, **kwargs):
        return self._payload("get_price_history", {"rows": [{"source": "PRODUCT_EDIT", "evidence": _evidence("product_price_history")}], "freshness": [], "evidence": [_evidence("product_price_history")]})

    def get_products_with_recent_price_changes(self, **kwargs):
        return self._payload("get_products_with_recent_price_changes", {"products": [{"latest_price_change": {"source": "PRODUCT_EDIT"}}], "freshness": [], "evidence": [_evidence("product_price_history")]})

    def get_dead_stock_summary(self, **kwargs):
        return self._payload("get_dead_stock_summary", {"summary": {"dead_stock_product_count": 0}, "freshness": [], "evidence": [_evidence("dead_stock_assessments")]})

    def get_visibility_summary(self, **kwargs):
        return self._payload("get_visibility_summary", {"summary": {"products_with_visibility_data": 0}, "freshness": [], "evidence": [_evidence("product_visibility_metrics")]})

    def get_alert_recommendation_summary(self, **kwargs):
        return self._payload("get_alert_recommendation_summary", {"summary": {"unresolved_alert_count": 0}, "freshness": [], "evidence": [_evidence("alerts")]})

    def get_alert_summary(self, **kwargs):
        return self._payload("get_alert_summary", {"summary": {"unresolved_alert_count": 0}, "urgent_affected_products": [], "freshness": [], "evidence": [_evidence("alerts")]})

    def get_recommendation_summary(self, **kwargs):
        return self._payload("get_recommendation_summary", {"summary": {"open_action_center_items": 1}, "top_prioritized_actions": [], "freshness": [], "evidence": [_evidence("action_center_items")]})

    def query_business_records(self, **kwargs):
        return self._payload(
            "query_business_records",
            {
                "entity": kwargs.get("entity"),
                "rows": [{"value": "2", "row_count": 2}],
                "row_count": 2,
                "truncated": False,
                "evidence": [_evidence("sales_records")],
                "calculation_version": "records_query_v2",
            },
        )

    def run_seller_metric_query(self, **kwargs):
        return self._payload(
            "run_seller_metric_query",
            {
                "metric_key": kwargs.get("metric_key"),
                "value": 2,
                "rows": [{"value": 2}],
                "unit": "count",
                "calculation_status": "CALCULATED",
                "evidence": [_evidence("products")],
                "freshness": [],
                "filters_used": kwargs.get("filters", {}),
                "computed_at": "2026-07-01T00:00:00+00:00",
            },
        )

    def get_today_actions(self, **kwargs):
        return self._rows(
            "get_today_actions",
            {
                "action_type": "REORDER",
                "product": {"id": str(PRODUCT_ID), "title": "Product A"},
                "expected_impact": {"revenue": "100.00"},
                "urgency": "HIGH",
                "confidence": "80",
            },
        )

    def get_restock_recommendations(self, **kwargs):
        return self._rows(
            "get_restock_recommendations",
            {
                "product": {"id": str(PRODUCT_ID), "title": "Product A"},
                "current_stock": 3,
                "sales_velocity": "2.5",
                "days_remaining": "1.2",
                "supplier_lead_time": 7,
                "reorder_quantity": 20,
                "risk_level": "HIGH",
                "confidence": "85",
            },
        )

    def get_inventory_risks(self, **kwargs):
        return self._rows(
            "get_inventory_risks",
            {
                "product": {"id": str(PRODUCT_ID), "title": "Product A"},
                "risk_level": "CRITICAL",
                "stockout_prediction": {"days_remaining": "0.5"},
                "velocity": "3.0",
                "confidence": "90",
            },
        )

    def explain_revenue_drop(self, **kwargs):
        return self._payload(
            "explain_revenue_drop",
            {
                "revenue_change": {"current_period_revenue": Decimal("100"), "previous_period_revenue": Decimal("200")},
                "likely_factors": [{"source": "inventory", "reason": "Stockout risk found."}],
                "evidence_by_source": {"inventory": [_evidence("inventory_risk_assessments")]},
                "confidence": "MEDIUM",
            },
        )

    def get_revenue_summary(self, **kwargs):
        return self._payload(
            "get_revenue_summary",
            {
                "gross_revenue": Decimal("250.00"),
                "net_revenue": Decimal("230.00"),
                "units_sold": 5,
                "order_count": 2,
                "average_order_value": Decimal("125.00"),
                "revenue_is_estimated": False,
                "previous_period_revenue": Decimal("200.00"),
                "revenue_change": Decimal("50.00"),
                "percentage_change": Decimal("25.00"),
                "top_products_by_revenue": [{"product": {"id": str(PRODUCT_ID), "title": "Product A"}, "gross_revenue": Decimal("250.00")}],
                "evidence": [_evidence("sales_records")],
            },
        )

    def get_sales_trends(self, **kwargs):
        return self._payload(
            "get_sales_trends",
            {
                "time_series": [{"period": "2026-07-01", "gross_revenue": Decimal("250.00"), "units_sold": 5}],
                "trend_direction": "UP",
                "top_increases": [],
                "top_decreases": [],
                "evidence": [_evidence("sales_records")],
            },
        )

    def get_profit_summary(self, **kwargs):
        return self._payload(
            "get_profit_summary",
            {
                "gross_revenue": Decimal("250.00"),
                "estimated_profit": Decimal("45.00"),
                "profit_label": "COMPLETE",
                "profit_by_product": [{"product": {"id": str(PRODUCT_ID), "title": "Product A"}, "estimated_profit": Decimal("45.00")}],
                "margin_rate": Decimal("0.18"),
                "confidence": "HIGH",
                "evidence": [_evidence("sales_records"), _evidence("marketplace_fee_policies")],
            },
        )

    def explain_revenue_change_deterministic(self, **kwargs):
        return self._payload(
            "explain_revenue_change_deterministic",
            {
                "current_period_revenue": Decimal("250.00"),
                "previous_period_revenue": Decimal("200.00"),
                "revenue_delta": Decimal("50.00"),
                "units_sold_delta": 1,
                "average_selling_price_delta": Decimal("5.00"),
                "likely_factors": [{"source": "sales_records", "reason": "Revenue increased."}],
                "confidence": "MEDIUM",
                "evidence": [_evidence("sales_records")],
            },
        )

    def get_top_products_by_revenue(self, **kwargs):
        return self._payload(
            "get_top_products_by_revenue",
            {
                "products": [{"product": {"id": str(PRODUCT_ID), "title": "Product A"}, "gross_revenue": Decimal("250.00"), "units_sold": 5, "order_count": 2}],
                "evidence": [_evidence("sales_records")],
            },
        )

    def get_products_with_no_sales(self, **kwargs):
        return self._payload(
            "get_products_with_no_sales",
            {
                "products": [{"product": {"id": str(PRODUCT_ID), "title": "Product A"}, "sales_status": "NO_VALID_IMPORTED_SALES_FOUND"}],
                "pagination": {"total": 1, "limit": kwargs.get("limit"), "offset": kwargs.get("offset")},
                "warning": "Sales history completeness is not tracked.",
                "evidence": [_evidence("products"), _evidence("sales_records")],
            },
        )

    def get_competitor_threats(self, **kwargs):
        return self._rows(
            "get_competitor_threats",
            {
                "competitor": {"id": str(uuid4()), "title": "Competitor A"},
                "affected_product": {"id": str(PRODUCT_ID), "title": "Product A"},
                "price_gap": "-10.00",
                "stock_status": "in_stock",
                "ranking": 1,
                "threat_reason": "PRICE_DROP",
                "confidence": "0.9",
            },
        )

    def get_pricing_recommendations(self, **kwargs):
        return self._rows(
            "get_pricing_recommendations",
            {
                "product": {"id": str(PRODUCT_ID), "title": "Product A"},
                "current_price": "100.00",
                "recommended_price": "95.00",
                "recommended_action": "PRICE_LOWER",
                "margin_safety": {"safe": True},
                "expected_impact": {"revenue": "50.00"},
                "blocked_reasons": [],
                "confidence": "80",
            },
        )

    def simulate_price_change(self, **kwargs):
        return self._payload(
            "simulate_price_change",
            {
                "allowed": True,
                "margin_guard": {"safe": True, "minimum_safe_price": Decimal("80")},
                "expected_revenue": Decimal("1200"),
                "expected_profit": Decimal("250"),
                "blocked_reasons": [],
                "evidence": [_evidence("pricing_analytics_snapshots")],
            },
        )

    def get_promotion_recommendations(self, **kwargs):
        return self._rows(
            "get_promotion_recommendations",
            {
                "promotion_type": "DISCOUNT",
                "expected_impact": {"revenue": "75.00"},
                "confidence": "70",
                "margin_safety": {"execution_enabled": False},
            },
        )

    def get_dead_stock_recovery(self, **kwargs):
        return self._rows(
            "get_dead_stock_recovery",
            {
                "product": {"id": str(PRODUCT_ID), "title": "Product A"},
                "locked_capital": "500.00",
                "classification": "DEAD_STOCK",
                "recovery_action": "DISCOUNT",
                "potential_recovery_range": {"low": "200.00", "high": "350.00"},
                "confidence": "75",
            },
        )

    def get_seo_opportunities(self, **kwargs):
        return self._rows(
            "get_seo_opportunities",
            {
                "product": {"id": str(PRODUCT_ID), "title": "Product A"},
                "issue": "Listing quality score is low.",
                "suggested_improvement": "Improve title and attributes.",
                "visibility_evidence": {"listing_quality_score": "45"},
                "confidence": "45",
            },
        )

    def retrieve_business_memory(self, **kwargs):
        return self._payload(
            "retrieve_business_memory",
            {
                "memory_chunks": [{"evidence_id": "rag-1", "snippet": "Historical restock note"}],
                "evidence_ids": ["rag-1"],
                "retrieval_confidence": "HIGH",
                "evidence": [_evidence("rag_memory_chunks")],
            },
        )

    def get_business_source(self, **kwargs):
        spec = kwargs["spec"]
        return self._payload(
            spec.name,
            {
                "source_table": spec.source_table,
                "rows": [{"id": str(uuid4()), "source_table": spec.source_table, "evidence": _evidence(spec.source_table)}],
                "pagination": {"limit": kwargs.get("limit"), "offset": kwargs.get("offset"), "has_next": False},
                "freshness": {"latest_record_at": "2026-07-01T00:00:00+00:00", "date_field": spec.date_field},
                "evidence": [_evidence(spec.source_table)],
            },
        )


class CopilotToolRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = CopilotToolContext(seller_id=SELLER_ID, request_id="req-test")

    def _arguments(self, tool_name: str, *, product_id=PRODUCT_ID) -> dict:
        common = {
            "get_business_overview": {"from_date": "2026-07-01", "to_date": "2026-07-05", "category": "cat"},
            "count_products": {"category": "cat", "has_stock": True},
            "list_products": {"category": "cat", "has_stock": True, "sort_by": "created_at_desc", "limit": 5, "offset": 0},
            "search_products": {"query": "Product", "category": "cat", "limit": 5},
            "get_product_profile": {"product_id": product_id},
            "get_products_missing_setup": {"setup_type": "MARKETPLACE_FEE_POLICY", "category": "cat", "limit": 5, "offset": 0},
            "get_product_setup_summary": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "category": "cat", "limit": 5, "offset": 0},
            "get_inventory_summary": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "category": "cat", "limit": 5, "offset": 0},
            "get_sales_velocity_summary": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "category": "cat", "limit": 5, "offset": 0},
            "get_stockout_summary": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "category": "cat", "limit": 5, "offset": 0},
            "get_reorder_summary": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "category": "cat", "limit": 5, "offset": 0},
            "get_inventory_aging_summary": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "category": "cat", "limit": 5, "offset": 0},
            "get_competitor_summary": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "category": "cat", "limit": 5, "offset": 0},
            "get_competitor_price_change_summary": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "category": "cat", "limit": 5, "offset": 0},
            "get_competitor_undercut_summary": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "category": "cat", "limit": 5, "offset": 0},
            "get_market_opportunity_summary": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "category": "cat", "limit": 5, "offset": 0},
            "get_scrape_health_summary": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "marketplace": "Daraz Bangladesh", "limit": 5, "offset": 0},
            "get_pricing_summary": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "category": "cat", "limit": 5, "offset": 0},
            "get_fee_policy_summary": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "category": "cat", "marketplace": "Daraz Bangladesh", "limit": 5, "offset": 0},
            "get_pricing_policy_summary": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "category": "cat", "limit": 5, "offset": 0},
            "get_elasticity_summary": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "category": "cat", "limit": 5, "offset": 0},
            "get_seller_price_history_summary": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "marketplace": "Daraz Bangladesh", "limit": 5, "offset": 0},
            "get_promotion_summary": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "category": "cat", "limit": 5, "offset": 0},
            "get_promotion_outcome_summary": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "marketplace": "Daraz Bangladesh", "limit": 5, "offset": 0},
            "get_promotion_plans": {"product_id": product_id, "status": "PROPOSED", "from_date": "2026-07-01", "to_date": "2026-07-05", "marketplace": "Daraz Bangladesh", "limit": 5, "offset": 0},
            "get_promotion_results": {"product_id": product_id, "status": "PARTIAL", "from_date": "2026-07-01", "to_date": "2026-07-05", "marketplace": "Daraz Bangladesh", "limit": 5, "offset": 0},
            "compare_promotion_performance": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "marketplace": "Daraz Bangladesh", "limit": 5, "offset": 0},
            "get_product_price_changes": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "marketplace": "Daraz Bangladesh", "limit": 5, "offset": 0},
            "get_products_with_recent_price_changes": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "marketplace": "Daraz Bangladesh", "limit": 5, "offset": 0},
            "get_dead_stock_summary": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "category": "cat", "limit": 5, "offset": 0},
            "get_visibility_summary": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "category": "cat", "limit": 5, "offset": 0},
            "get_alert_recommendation_summary": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "category": "cat", "limit": 5, "offset": 0},
            "get_alert_summary": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "category": "cat", "limit": 5, "offset": 0},
            "get_recommendation_summary": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "category": "cat", "limit": 5, "offset": 0},
            "run_seller_metric_query": {"metric_key": "product_count", "filters": {"category": "cat"}, "limit": 5, "offset": 0},
            "query_business_records": {"entity": "sales", "product_id": product_id, "aggregate": "sum", "measure": "revenue", "from_date": "2026-07-01", "to_date": "2026-07-05"},
            "get_today_actions": {"product_id": product_id, "limit": 5},
            "get_restock_recommendations": {"product_id": product_id, "category": "cat", "limit": 5},
            "get_inventory_risks": {"product_id": product_id, "risk_level": "high", "limit": 5},
            "explain_revenue_drop": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05"},
            "get_revenue_summary": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "compare_to_previous_period": True},
            "get_sales_trends": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "granularity": "daily"},
            "get_profit_summary": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05"},
            "explain_revenue_change_deterministic": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "compare_to_previous_period": True},
            "get_top_products_by_revenue": {"from_date": "2026-07-01", "to_date": "2026-07-05", "limit": 5},
            "get_products_with_no_sales": {"since_date": "2026-07-01", "category": "cat", "limit": 5, "offset": 0},
            "get_competitor_threats": {"product_id": product_id, "from_date": "2026-07-01", "to_date": "2026-07-05", "limit": 5},
            "get_pricing_recommendations": {"product_id": product_id, "limit": 5},
            "simulate_price_change": {"product_id": product_id, "candidate_price": "99.00", "forecast_horizon_days": 30},
            "get_promotion_recommendations": {"product_id": product_id, "category": "cat", "limit": 5},
            "get_dead_stock_recovery": {"product_id": product_id, "limit": 5},
            "get_seo_opportunities": {"product_id": product_id, "limit": 5},
            "retrieve_business_memory": {"product_id": product_id, "question": "What happened?", "source_types": ["ALERT"], "from_date": "2026-07-01", "to_date": "2026-07-05", "top_k": 5},
        }
        if tool_name in SOURCE_TOOL_SPECS:
            return {
                "product_id": product_id,
                "from_date": "2026-07-01",
                "to_date": "2026-07-05",
                "category": "cat",
                "marketplace": "Daraz Bangladesh",
                "limit": 5,
                "offset": 0,
            }
        return common[tool_name]

    def test_registry_exposes_only_expected_read_only_tools(self):
        registry = CopilotToolRegistry(_FakeDataAccess())
        tools = registry.list_tools()

        self.assertEqual(
            {
                "get_today_actions",
                "get_business_overview",
                "count_products",
                "list_products",
                "search_products",
                "get_product_profile",
                "get_products_missing_setup",
                "get_product_setup_summary",
                "get_inventory_summary",
                "get_sales_velocity_summary",
                "get_stockout_summary",
                "get_reorder_summary",
                "get_inventory_aging_summary",
                "get_competitor_summary",
                "get_competitor_price_change_summary",
                "get_competitor_undercut_summary",
                "get_market_opportunity_summary",
                "get_scrape_health_summary",
                "get_pricing_summary",
                "get_fee_policy_summary",
                "get_pricing_policy_summary",
                "get_elasticity_summary",
                "get_seller_price_history_summary",
                "get_promotion_summary",
                "get_promotion_outcome_summary",
                "get_promotion_plans",
                "get_promotion_results",
                "compare_promotion_performance",
                "get_product_price_changes",
                "get_products_with_recent_price_changes",
                "get_dead_stock_summary",
                "get_visibility_summary",
                "get_alert_recommendation_summary",
                "get_alert_summary",
                "get_recommendation_summary",
                "run_seller_metric_query",
                "query_business_records",
                "get_restock_recommendations",
                "get_inventory_risks",
                "explain_revenue_drop",
                "get_revenue_summary",
                "get_sales_trends",
                "get_profit_summary",
                "explain_revenue_change_deterministic",
                "get_top_products_by_revenue",
                "get_products_with_no_sales",
                "get_competitor_threats",
                "get_pricing_recommendations",
                "simulate_price_change",
                "get_promotion_recommendations",
                "get_dead_stock_recovery",
                "get_seo_opportunities",
                "retrieve_business_memory",
                *SOURCE_TOOL_SPECS.keys(),
            },
            {tool.name for tool in tools},
        )
        for tool in tools:
            self.assertEqual(CopilotToolSafetyLevel.READ_ONLY, tool.safety_level)
            self.assertFalse(tool.requires_confirmation)
            self.assertTrue(tool.allowed_in_read_only_mode)
            self.assertIn("seller_id_from_context", tool.seller_ownership_checks)

    def test_every_tool_valid_seller_access_returns_evidence(self):
        for tool_name in [tool.name for tool in CopilotToolRegistry(_FakeDataAccess()).list_tools()]:
            with self.subTest(tool=tool_name):
                data_access = _FakeDataAccess()
                result = CopilotToolRegistry(data_access).execute(
                    name=tool_name,
                    context=self.context,
                    arguments=self._arguments(tool_name),
                )

                self.assertEqual(ToolExecutionStatus.SUCCEEDED, result.status)
                self.assertGreaterEqual(len(result.evidence), 1)
                expected_verified = [PRODUCT_ID] if self._arguments(tool_name).get("product_id") else []
                self.assertEqual(expected_verified, data_access.verified_products)
                self.assertEqual(0, data_access.mutations)

    def test_every_tool_blocks_cross_seller_product(self):
        for tool_name in [tool.name for tool in CopilotToolRegistry(_FakeDataAccess()).list_tools()]:
            with self.subTest(tool=tool_name):
                data_access = _FakeDataAccess(allow_product=False)
                result = CopilotToolRegistry(data_access).execute(
                    name=tool_name,
                    context=self.context,
                    arguments=self._arguments(tool_name, product_id=OTHER_PRODUCT_ID),
                )

                if self._arguments(tool_name, product_id=OTHER_PRODUCT_ID).get("product_id"):
                    self.assertEqual(ToolExecutionStatus.BLOCKED, result.status)
                    self.assertEqual("PRODUCT_ACCESS_DENIED", result.error["code"])
                    self.assertEqual([], data_access.called_tools)
                else:
                    self.assertEqual(ToolExecutionStatus.SUCCEEDED, result.status)
                self.assertEqual(0, data_access.mutations)

    def test_every_tool_rejects_invalid_args(self):
        for tool_name in [tool.name for tool in CopilotToolRegistry(_FakeDataAccess()).list_tools()]:
            with self.subTest(tool=tool_name):
                result = CopilotToolRegistry(_FakeDataAccess()).execute(
                    name=tool_name,
                    context=self.context,
                    arguments={"product_id": str(PRODUCT_ID), "limit": 999, "unexpected": True},
                )

                self.assertEqual(ToolExecutionStatus.BLOCKED, result.status)
                self.assertEqual("INVALID_ARGUMENTS", result.error["code"])

    def test_every_tool_returns_missing_data_without_raw_failure(self):
        for tool_name in [tool.name for tool in CopilotToolRegistry(_FakeDataAccess()).list_tools()]:
            with self.subTest(tool=tool_name):
                result = CopilotToolRegistry(_FakeDataAccess(missing=True)).execute(
                    name=tool_name,
                    context=self.context,
                    arguments=self._arguments(tool_name),
                )

                self.assertEqual(ToolExecutionStatus.SUCCEEDED, result.status)
                self.assertTrue(result.missing_data)
                self.assertIsNone(result.error)

    def test_unknown_tool_is_blocked(self):
        result = CopilotToolRegistry(_FakeDataAccess()).execute(
            name="os.system",
            context=self.context,
            arguments={},
        )

        self.assertEqual(ToolExecutionStatus.BLOCKED, result.status)
        self.assertEqual("TOOL_NOT_ALLOWLISTED", result.error["code"])

    def test_date_validation_blocks_reversed_range(self):
        result = CopilotToolRegistry(_FakeDataAccess()).execute(
            name="explain_revenue_drop",
            context=self.context,
            arguments={
                "product_id": str(PRODUCT_ID),
                "from_date": date(2026, 7, 5).isoformat(),
                "to_date": date(2026, 7, 1).isoformat(),
            },
        )

        self.assertEqual(ToolExecutionStatus.BLOCKED, result.status)
        self.assertEqual("INVALID_ARGUMENTS", result.error["code"])


if __name__ == "__main__":
    unittest.main()
