from __future__ import annotations

from dataclasses import dataclass

from app.models.rag_memory import RagMemorySourceType
from app.services.copilot.query_constraints import (
    BusinessDomainKey,
    CatalogValidationError,
    COMMON_SELLER_FILTERS,
    DEFAULT_RESTRICTED_FIELDS,
    QueryConstraint,
    ensure_no_restricted_fields,
    safe_field_tuple,
)


@dataclass(frozen=True, slots=True)
class BusinessDomainDefinition:
    domain_key: BusinessDomainKey
    description: str
    source_tables: tuple[str, ...]
    source_models: tuple[str, ...]
    safe_fields: tuple[str, ...]
    restricted_fields: tuple[str, ...]
    date_field: str | None
    product_field: str | None
    seller_field: str
    supported_filters: tuple[str, ...]
    supported_metrics: tuple[str, ...]
    supported_tools: tuple[str, ...]
    rag_source_types: tuple[RagMemorySourceType, ...]
    freshness_expectation: str
    missing_data_rules: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.seller_field:
            raise CatalogValidationError(f"{self.domain_key.value} must define seller scoping.")
        ensure_no_restricted_fields(self.safe_fields, self.restricted_fields)

    @property
    def query_constraint(self) -> QueryConstraint:
        return QueryConstraint(
            seller_field=self.seller_field,
            product_field=self.product_field,
            date_field=self.date_field,
            allowed_filters=self.supported_filters,
            allowed_group_by=("product_id", "category", "marketplace", "status", "source_type"),
        )


def _domain(
    *,
    domain_key: BusinessDomainKey,
    description: str,
    source_tables: tuple[str, ...],
    source_models: tuple[str, ...],
    safe_fields: tuple[str, ...],
    date_field: str | None,
    product_field: str | None,
    supported_filters: tuple[str, ...],
    supported_metrics: tuple[str, ...],
    supported_tools: tuple[str, ...],
    rag_source_types: tuple[RagMemorySourceType, ...] = (),
    freshness_expectation: str = "Use the latest seller-scoped records available; report stale or missing records.",
    missing_data_rules: tuple[str, ...] = (),
    seller_field: str = "seller_id",
) -> BusinessDomainDefinition:
    return BusinessDomainDefinition(
        domain_key=domain_key,
        description=description,
        source_tables=source_tables,
        source_models=source_models,
        safe_fields=safe_field_tuple(safe_fields),
        restricted_fields=DEFAULT_RESTRICTED_FIELDS,
        date_field=date_field,
        product_field=product_field,
        seller_field=seller_field,
        supported_filters=tuple(dict.fromkeys(("seller_id", *supported_filters))),
        supported_metrics=supported_metrics,
        supported_tools=supported_tools,
        rag_source_types=rag_source_types,
        freshness_expectation=freshness_expectation,
        missing_data_rules=missing_data_rules,
    )


BUSINESS_DOMAINS: dict[BusinessDomainKey, BusinessDomainDefinition] = {
    BusinessDomainKey.PRODUCT_CATALOG: _domain(
        domain_key=BusinessDomainKey.PRODUCT_CATALOG,
        description="Seller product catalog, setup completeness, listing status, prices, cost, category, and marketplace scope.",
        source_tables=("products", "product_marketplace_listings"),
        source_models=("Product", "ProductMarketplaceListing"),
        safe_fields=("id", "seller_id", "product_id", "title", "sku", "category", "marketplace", "marketplace_listing_id", "listing_status", "status", "selling_price", "previous_selling_price", "cost_price", "landed_cost", "currency", "stock_quantity", "supplier_lead_time", "minimum_margin", "is_primary", "published_at", "last_synced_at", "created_at", "updated_at", "setup_completeness"),
        date_field="created_at",
        product_field="id",
        supported_filters=(*COMMON_SELLER_FILTERS, "status", "setup_complete", "has_cost", "has_fee_policy"),
        supported_metrics=("product_count", "active_product_count", "products_missing_cost_count", "products_missing_fee_policy_count", "products_with_stock_count"),
        supported_tools=("search_products", "get_product_profile"),
        rag_source_types=(RagMemorySourceType.PRODUCT_PROFILE,),
        missing_data_rules=("Treat missing SKU or marketplace listing as unavailable, not inactive.", "Return MISSING_MARKETPLACE when no seller-scoped listing exists.", "Setup completeness requires product cost and required pricing/fee policy data."),
    ),
    BusinessDomainKey.SALES_REVENUE: _domain(
        domain_key=BusinessDomainKey.SALES_REVENUE,
        description="Completed/fulfilled seller sales, units, order count, AOV, returns, refunds, and revenue trends.",
        source_tables=("sales_records", "orders", "order_items"),
        source_models=("SalesRecord",),
        safe_fields=("id", "seller_id", "product_id", "status", "sold_at", "quantity_sold", "returned_units", "refunded_restocked_units", "is_test_order", "created_at"),
        date_field="sold_at",
        product_field="product_id",
        supported_filters=(*COMMON_SELLER_FILTERS, "status", "include_returns", "sales_completeness_known"),
        supported_metrics=("gross_revenue", "net_revenue", "units_sold", "order_count", "average_order_value", "top_products_by_revenue", "revenue_trend", "products_with_no_sales_count"),
        supported_tools=("explain_revenue_drop", "get_sales_analytics", "get_revenue_analytics"),
        rag_source_types=(RagMemorySourceType.SALES_HISTORY,),
        missing_data_rules=("Use completed/fulfilled sales only.", "Do not treat missing sales history as zero sales unless completeness is known.", "Net revenue is unavailable unless return/refund semantics are complete."),
    ),
    BusinessDomainKey.PROFIT_MARGIN: _domain(
        domain_key=BusinessDomainKey.PROFIT_MARGIN,
        description="Seller cost, marketplace fees, pricing policies, estimated contribution, estimated profit, and margin safety.",
        source_tables=("products", "marketplace_fee_policies", "pricing_policies", "pricing_analytics_snapshots"),
        source_models=("Product", "MarketplaceFeePolicy", "PricingPolicy", "PricingAnalyticsSnapshot"),
        safe_fields=("seller_id", "product_id", "cost_price", "landed_cost", "selling_price", "currency", "minimum_margin", "percentage_commission_rate", "payment_fee_rate", "fixed_per_order_fee", "fixed_per_unit_fee", "fulfilment_fee", "shipping_subsidy", "other_variable_cost", "minimum_allowed_price", "maximum_allowed_price", "minimum_safe_price", "margin_rate", "effective_from", "effective_to", "is_active"),
        date_field="effective_from",
        product_field="product_id",
        supported_filters=(*COMMON_SELLER_FILTERS, "is_active", "has_cost", "has_fee_policy"),
        supported_metrics=("estimated_profit", "margin_rate", "products_excluded_from_profit", "products_missing_cost_count", "products_missing_fee_policy_count"),
        supported_tools=("get_pricing_recommendations", "simulate_price_change", "get_margin_analytics"),
        rag_source_types=(RagMemorySourceType.PRICE_HISTORY,),
        missing_data_rules=("Do not calculate profit if product cost or applicable fee policy is missing.", "Report excluded products explicitly."),
    ),
    BusinessDomainKey.INVENTORY: _domain(
        domain_key=BusinessDomainKey.INVENTORY,
        description="Inventory snapshots, stock-ins, aging, velocity, stockout predictions, risk assessments, and reorder recommendations.",
        source_tables=("inventory_history", "inventory_stock_in", "inventory_aging_snapshots", "sales_velocity", "stockout_predictions", "inventory_risk_assessments", "reorder_recommendations"),
        source_models=("InventoryHistory", "InventoryStockIn", "InventoryAgingSnapshot", "SalesVelocity", "StockoutPrediction", "InventoryRiskAssessment", "ReorderRecommendation"),
        safe_fields=("seller_id", "product_id", "snapshot_date", "quantity_on_hand", "quantity_reserved", "quantity_available", "quantity_incoming", "source", "captured_at", "quantity", "received_at", "age_days", "daily_sales_rate", "days_remaining", "predicted_stockout_date", "risk_level", "risk_score", "recommended_quantity", "reorder_deadline", "recommendation_status"),
        date_field="captured_at",
        product_field="product_id",
        supported_filters=(*COMMON_SELLER_FILTERS, "risk_level", "recommendation_status", "source"),
        supported_metrics=("current_inventory_value", "low_stock_product_count", "stockout_risk_count", "products_with_stock_count"),
        supported_tools=("get_restock_recommendations", "get_inventory_risks", "get_inventory_history", "get_sales_velocity"),
        rag_source_types=(RagMemorySourceType.INVENTORY_HISTORY, RagMemorySourceType.RECOMMENDATION),
        missing_data_rules=("Current stock uses latest seller inventory snapshot or product stock if snapshots are unavailable.", "Do not infer stockout risk from missing prediction records."),
    ),
    BusinessDomainKey.COMPETITOR: _domain(
        domain_key=BusinessDomainKey.COMPETITOR,
        description="Competitor listings, snapshots, events, rankings, scrape runs, market opportunities, price gaps, stock status, and threat signals.",
        source_tables=("competitors", "competitor_snapshots", "competitor_events", "competitor_rankings", "market_opportunities", "scrape_runs", "price_history"),
        source_models=("Competitor", "CompetitorSnapshot", "CompetitorEvent", "CompetitorRanking", "MarketOpportunity", "ScrapeRun", "PriceHistory"),
        safe_fields=("seller_id", "product_id", "competitor_id", "scrape_run_id", "competitor_title", "competitor_store", "marketplace", "competitor_price", "price", "observed_price", "stock_status", "rating", "review_count", "search_position", "event_type", "old_value", "new_value", "price_change_amount", "price_change_percent", "severity", "market_rank", "opportunity_score", "recommended_action", "detected_at", "captured_at", "finished_at"),
        date_field="detected_at",
        product_field="product_id",
        supported_filters=(*COMMON_SELLER_FILTERS, "competitor_id", "event_type", "severity", "stock_status", "scrape_status"),
        supported_metrics=("competitor_undercut_count", "competitor_price_gap"),
        supported_tools=("get_competitor_threats", "get_competitor_snapshots", "get_market_opportunities"),
        rag_source_types=(RagMemorySourceType.COMPETITOR_HISTORY,),
        missing_data_rules=("A missing scrape run means competitor freshness is unknown, not that there is no threat.", "Use seller-owned product joins for competitor rows."),
    ),
    BusinessDomainKey.PRICING: _domain(
        domain_key=BusinessDomainKey.PRICING,
        description="Dynamic pricing recommendations, pricing analytics, policies, fee policies, elasticity, seller price history, and MarginGuard results.",
        source_tables=("dynamic_pricing_recommendations", "pricing_analytics_snapshots", "pricing_policies", "marketplace_fee_policies", "demand_elasticity_estimates", "product_price_history"),
        source_models=("DynamicPricingRecommendation", "PricingAnalyticsSnapshot", "PricingPolicy", "MarketplaceFeePolicy", "DemandElasticityEstimate", "ProductPriceHistory"),
        safe_fields=("seller_id", "product_id", "current_price", "recommended_price", "minimum_safe_price", "minimum_allowed_price", "maximum_allowed_price", "margin_rate", "expected_revenue", "expected_profit", "revenue_impact", "profit_impact", "confidence_score", "recommendation_status", "objective", "elasticity", "data_status", "generated_at", "calculated_at"),
        date_field="generated_at",
        product_field="product_id",
        supported_filters=(*COMMON_SELLER_FILTERS, "recommendation_status", "objective", "data_status", "is_active"),
        supported_metrics=("estimated_profit", "margin_rate", "products_excluded_from_profit"),
        supported_tools=("get_pricing_recommendations", "simulate_price_change", "get_pricing_analytics", "get_price_history", "get_product_price_changes"),
        rag_source_types=(RagMemorySourceType.PRICE_HISTORY, RagMemorySourceType.SELLER_PRICE_HISTORY),
        missing_data_rules=("MarginGuard requires cost, active fee policy, and pricing policy where applicable.", "Do not override blocked pricing recommendations."),
    ),
    BusinessDomainKey.PROMOTION: _domain(
        domain_key=BusinessDomainKey.PROMOTION,
        description="Internal promotion plans/results plus recommendation-derived promotion suitability. Approval records internal state only; marketplace execution is not implemented.",
        source_tables=("promotion_plans", "promotion_results", "dead_stock_recovery_recommendations", "dynamic_pricing_recommendations"),
        source_models=("PromotionPlan", "PromotionResult", "DeadStockRecoveryRecommendation", "DynamicPricingRecommendation"),
        safe_fields=("seller_id", "product_id", "category", "marketplace", "promotion_type", "title", "status", "started_at", "ended_at", "units_sold", "gross_revenue", "estimated_profit", "spend", "discount_cost", "roi", "result_status", "recommended_discount_rate", "recommended_price", "confidence_score"),
        date_field="started_at",
        product_field="product_id",
        supported_filters=(*COMMON_SELLER_FILTERS, "promotion_type", "status", "result_status", "recommendation_status"),
        supported_metrics=(),
        supported_tools=("get_promotion_summary", "get_promotion_plans", "get_promotion_results", "compare_promotion_performance", "get_promotion_recommendations"),
        rag_source_types=(RagMemorySourceType.PROMOTION_PLAN, RagMemorySourceType.PROMOTION_RESULT, RagMemorySourceType.RECOMMENDATION),
        missing_data_rules=("Promotion plans are internal records only; approval does not create live marketplace campaigns.", "Promotion ROI is unavailable unless revenue, cost, spend, and discount cost records exist."),
    ),
    BusinessDomainKey.DEAD_STOCK: _domain(
        domain_key=BusinessDomainKey.DEAD_STOCK,
        description="Dead-stock assessments, aging snapshots, recovery recommendations, capital recovery estimates, locked capital, and recovery estimates.",
        source_tables=("dead_stock_assessments", "inventory_aging_snapshots", "dead_stock_recovery_recommendations", "dead_stock_capital_recovery_estimates"),
        source_models=("DeadStockAssessment", "InventoryAgingSnapshot", "DeadStockRecoveryRecommendation", "DeadStockCapitalRecoveryEstimate"),
        safe_fields=("seller_id", "product_id", "classification", "eligible_quantity", "age_days", "stock_value", "primary_action", "recommended_price", "recommended_discount_rate", "recommended_quantity", "recovery_estimate", "locked_capital", "estimate_status", "recommendation_status", "assessed_at", "generated_at"),
        date_field="assessed_at",
        product_field="product_id",
        supported_filters=(*COMMON_SELLER_FILTERS, "classification", "recommendation_status", "estimate_status"),
        supported_metrics=("dead_stock_count", "locked_capital"),
        supported_tools=("get_dead_stock_recovery",),
        rag_source_types=(RagMemorySourceType.DEAD_STOCK, RagMemorySourceType.RECOMMENDATION),
        missing_data_rules=("Locked capital requires eligible quantity and product cost.", "Do not classify products as dead stock when aging data is missing."),
    ),
    BusinessDomainKey.SEO_VISIBILITY: _domain(
        domain_key=BusinessDomainKey.SEO_VISIBILITY,
        description="Product visibility metrics, impressions, views, clicks, CTR, search rank, listing quality, and SEO opportunities.",
        source_tables=("product_visibility_metrics",),
        source_models=("ProductVisibilityMetric",),
        safe_fields=("seller_id", "product_id", "marketplace", "metric_date", "impressions", "views", "clicks", "search_rank", "listing_quality_score", "conversion_rate", "source", "created_at", "updated_at"),
        date_field="metric_date",
        product_field="product_id",
        supported_filters=(*COMMON_SELLER_FILTERS, "source", "has_visibility_data"),
        supported_metrics=(),
        supported_tools=("get_seo_opportunities", "get_visibility_history"),
        rag_source_types=(RagMemorySourceType.SEO,),
        missing_data_rules=("Do not treat missing visibility as low visibility.", "CTR requires views or impressions plus clicks."),
    ),
    BusinessDomainKey.RECOMMENDATIONS: _domain(
        domain_key=BusinessDomainKey.RECOMMENDATIONS,
        description="General, reorder, pricing, and dead-stock recovery recommendations with pending/acknowledged/dismissed state where available.",
        source_tables=("recommendations", "reorder_recommendations", "dynamic_pricing_recommendations", "dead_stock_recovery_recommendations"),
        source_models=("Recommendation", "ReorderRecommendation", "DynamicPricingRecommendation", "DeadStockRecoveryRecommendation"),
        safe_fields=("seller_id", "product_id", "action", "primary_action", "recommendation_status", "confidence", "confidence_score", "reasoning_bn", "suggested_price_min", "suggested_price_max", "recommended_quantity", "recommended_price", "created_at", "generated_at"),
        date_field="created_at",
        product_field="product_id",
        supported_filters=(*COMMON_SELLER_FILTERS, "recommendation_status", "action", "source"),
        supported_metrics=("pending_recommendation_count",),
        supported_tools=("get_today_actions", "get_restock_recommendations", "get_pricing_recommendations", "get_dead_stock_recovery"),
        rag_source_types=(RagMemorySourceType.RECOMMENDATION,),
        missing_data_rules=("Use status fields when available; otherwise report state as unavailable.",),
    ),
    BusinessDomainKey.ALERTS: _domain(
        domain_key=BusinessDomainKey.ALERTS,
        description="Seller alerts, Telegram inventory alerts, delivery logs, Telegram connection state, and notification status.",
        source_tables=("alerts", "telegram_inventory_alerts", "alert_delivery_logs", "seller_telegram_connections"),
        source_models=("Alert", "TelegramInventoryAlert", "AlertDeliveryLog", "SellerTelegramConnection"),
        safe_fields=("seller_id", "product_id", "alert_type", "urgency_level", "action_type", "confidence", "delivery_status", "status", "attempt_count", "delivered_at", "read_at", "sent_at", "created_at", "updated_at", "connected_at"),
        date_field="created_at",
        product_field="product_id",
        supported_filters=(*COMMON_SELLER_FILTERS, "alert_type", "urgency_level", "delivery_status", "status", "read_state"),
        supported_metrics=("unresolved_alert_count",),
        supported_tools=("get_today_actions",),
        rag_source_types=(RagMemorySourceType.ALERT,),
        missing_data_rules=("Do not expose Telegram chat/user identifiers.", "Notification state requires delivery logs or connection records."),
    ),
    BusinessDomainKey.RAG_MEMORY: _domain(
        domain_key=BusinessDomainKey.RAG_MEMORY,
        description="RAG documents and chunks, indexed source coverage, embedding status, stale records, and failed memory records.",
        source_tables=("rag_memory_documents", "rag_memory_chunks", "rag_query_logs"),
        source_models=("RagMemoryDocument", "RagMemoryChunk", "RagQueryLog"),
        safe_fields=("seller_id", "product_id", "source_type", "source_table", "source_id", "title", "summary_text", "language", "metadata_json", "sensitivity_level", "visibility_scope", "event_time", "embedding_status", "embedding_model", "embedding_dimension", "embedding_version", "embedding_failure_reason", "created_at", "updated_at"),
        date_field="event_time",
        product_field="product_id",
        supported_filters=(*COMMON_SELLER_FILTERS, "source_type", "source_table", "embedding_status", "include_stale"),
        supported_metrics=(),
        supported_tools=("retrieve_business_memory",),
        rag_source_types=tuple(RagMemorySourceType),
        missing_data_rules=("Report stale or failed embeddings explicitly.", "RAG coverage is limited to indexed source records."),
    ),
    BusinessDomainKey.COPILOT: _domain(
        domain_key=BusinessDomainKey.COPILOT,
        description="Copilot conversations, messages, tool calls, and action proposals for seller-scoped assistant history and proposal state.",
        source_tables=("copilot_conversations", "copilot_messages", "copilot_tool_calls", "copilot_action_proposals"),
        source_models=("CopilotConversation", "CopilotMessage", "CopilotToolCall", "CopilotActionProposal"),
        safe_fields=("seller_id", "conversation_id", "message_id", "role", "content", "language", "answer_confidence", "model_id", "prompt_version", "evidence_json", "missing_context_json", "tool_name", "tool_version", "status", "error_code", "action_type", "requires_confirmation", "created_at", "updated_at", "archived_at"),
        date_field="created_at",
        product_field="product_id",
        supported_filters=(*COMMON_SELLER_FILTERS, "conversation_id", "status", "role", "tool_name", "action_type"),
        supported_metrics=(),
        supported_tools=(),
        rag_source_types=(),
        missing_data_rules=("Copilot history is seller-scoped and should not be used as business fact unless backed by evidence.",),
    ),
}


class BusinessDataCatalogService:
    def __init__(self, domains: dict[BusinessDomainKey, BusinessDomainDefinition] | None = None) -> None:
        self._domains = domains or BUSINESS_DOMAINS

    def list_domains(self) -> list[BusinessDomainDefinition]:
        return list(self._domains.values())

    def get_domain(self, domain_key: BusinessDomainKey | str) -> BusinessDomainDefinition:
        try:
            key = domain_key if isinstance(domain_key, BusinessDomainKey) else BusinessDomainKey(str(domain_key).upper())
        except ValueError as exc:
            raise CatalogValidationError(f"Unknown business domain: {domain_key}") from exc
        try:
            return self._domains[key]
        except KeyError as exc:
            raise CatalogValidationError(f"Unknown business domain: {domain_key}") from exc

    def get_domain_for_question(self, question: str) -> BusinessDomainDefinition | None:
        normalized = (question or "").casefold()
        for key, keywords in _QUESTION_KEYWORDS.items():
            if any(keyword in normalized for keyword in keywords):
                return self._domains[key]
        return None

    def get_safe_fields(self, domain_key: BusinessDomainKey | str) -> tuple[str, ...]:
        return self.get_domain(domain_key).safe_fields

    def get_supported_tools(self, domain_key: BusinessDomainKey | str) -> tuple[str, ...]:
        return self.get_domain(domain_key).supported_tools

    def get_missing_data_guidance(self, domain_key: BusinessDomainKey | str) -> tuple[str, ...]:
        return self.get_domain(domain_key).missing_data_rules


_QUESTION_KEYWORDS: dict[BusinessDomainKey, tuple[str, ...]] = {
    BusinessDomainKey.PRODUCT_CATALOG: ("product", "catalog", "sku", "listed", "setup"),
    BusinessDomainKey.SALES_REVENUE: ("revenue", "sales", "orders", "aov", "sold"),
    BusinessDomainKey.PROFIT_MARGIN: ("profit", "margin", "fee", "cost", "contribution"),
    BusinessDomainKey.INVENTORY: ("inventory", "stock", "stockout", "reorder", "restock"),
    BusinessDomainKey.COMPETITOR: ("competitor", "threat", "undercut", "ranking"),
    BusinessDomainKey.PRICING: ("pricing", "price", "marginguard", "elasticity"),
    BusinessDomainKey.PROMOTION: ("promotion", "campaign", "discount", "roi"),
    BusinessDomainKey.DEAD_STOCK: ("dead stock", "slow moving", "locked capital"),
    BusinessDomainKey.SEO_VISIBILITY: ("seo", "visibility", "impressions", "clicks", "ctr", "rank"),
    BusinessDomainKey.RECOMMENDATIONS: ("recommendation", "recommended", "pending"),
    BusinessDomainKey.ALERTS: ("alert", "notification", "telegram"),
    BusinessDomainKey.RAG_MEMORY: ("memory", "rag", "indexed", "embedding"),
    BusinessDomainKey.COPILOT: ("copilot", "conversation", "proposal", "tool call"),
}
