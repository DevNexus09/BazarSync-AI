from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.rag_memory import RagMemorySensitivityLevel, RagMemorySourceType, RagMemoryVisibilityScope


@dataclass(frozen=True)
class RagSourceDefinition:
    source_type: RagMemorySourceType
    source_table: str | None
    model_name: str | None
    adapter_function: str | None
    builder_function: str | None
    allowed_fields: tuple[str, ...]
    excluded_fields: tuple[str, ...]
    date_field: str | None
    product_field: str | None
    seller_field: str | None
    implemented: bool
    reindex_supported: bool
    coverage_status: str
    template_version: str
    chunking_version: str
    sensitivity_level: RagMemorySensitivityLevel
    visibility_scope: RagMemoryVisibilityScope
    chunking_rules: dict[str, Any]
    reindex_triggers: tuple[str, ...]


COMMON_EXCLUDED_FIELDS = (
    "password",
    "password_hash",
    "api_key",
    "token",
    "cookie",
    "secret",
    "telegram_chat_id",
    "telegram_message_id",
    "telegram_user_id",
    "connection_token",
    "token_expires_at",
    "delivery_error",
    "error_message",
    "stack_trace",
    "traceback",
    "raw_html",
    "html",
    "customer_email",
    "customer_phone",
    "customer_name",
    "customer_message",
    "private_message",
    "source_reference",
    "dedupe_key",
    "celery_task_id",
    "embedding",
    "embedding_failure_reason",
)


def _source(
    source_type: RagMemorySourceType,
    *,
    table: str | None,
    model: str | None,
    adapter: str | None,
    builder: str | None,
    fields: tuple[str, ...],
    date_field: str | None,
    product_field: str | None = "product_id",
    seller_field: str | None = "seller_id",
    implemented: bool = True,
    reindex: bool = True,
    coverage: str = "implemented",
    sensitivity: RagMemorySensitivityLevel = RagMemorySensitivityLevel.INTERNAL,
    visibility: RagMemoryVisibilityScope = RagMemoryVisibilityScope.PRODUCT,
    max_tokens: int = 320,
    triggers: tuple[str, ...] = (),
) -> RagSourceDefinition:
    return RagSourceDefinition(
        source_type=source_type,
        source_table=table,
        model_name=model,
        adapter_function=adapter,
        builder_function=builder,
        allowed_fields=fields,
        excluded_fields=COMMON_EXCLUDED_FIELDS,
        date_field=date_field,
        product_field=product_field,
        seller_field=seller_field,
        implemented=implemented,
        reindex_supported=implemented and reindex,
        coverage_status=coverage if implemented else "not_implemented",
        template_version=f"{source_type.value.lower()}_v1",
        chunking_version="compact_business_memory_v1",
        sensitivity_level=sensitivity,
        visibility_scope=visibility,
        chunking_rules={"mode": "deterministic_factual_document", "max_tokens": max_tokens},
        reindex_triggers=triggers,
    )


RAG_SOURCE_REGISTRY: dict[RagMemorySourceType, RagSourceDefinition] = {
    RagMemorySourceType.PRODUCT_PROFILE: _source(
        RagMemorySourceType.PRODUCT_PROFILE,
        table="products",
        model="Product",
        adapter="_backfill_product_profiles",
        builder="build_from_product_profile",
        fields=("title", "category", "specifications", "selling_price", "cost_price", "stock_quantity", "created_at"),
        date_field="created_at",
        triggers=("product_created", "product_updated"),
    ),
    RagMemorySourceType.SALES_HISTORY: _source(
        RagMemorySourceType.SALES_HISTORY,
        table="sales_records",
        model="SalesRecord",
        adapter="_backfill_sales_history",
        builder="build_from_sales_record",
        fields=(
            "sold_at",
            "quantity_sold",
            "returned_units",
            "refunded_restocked_units",
            "status",
            "is_test_order",
            "unit_price",
            "line_total",
            "currency",
            "marketplace_listing_id",
            "price_source",
        ),
        date_field="sold_at",
        sensitivity=RagMemorySensitivityLevel.CONFIDENTIAL,
        triggers=("sales_record_imported", "sales_record_updated"),
    ),
    RagMemorySourceType.SALES_REVENUE_SUMMARY: _source(
        RagMemorySourceType.SALES_REVENUE_SUMMARY,
        table="sales_records",
        model="SalesRecord",
        adapter="_backfill_sales_revenue_summary",
        builder="build_from_sales_revenue_summary",
        fields=("sold_at", "quantity_sold", "returned_units", "status", "is_test_order", "unit_price", "line_total", "price_source"),
        date_field="sold_at",
        product_field=None,
        sensitivity=RagMemorySensitivityLevel.CONFIDENTIAL,
        triggers=("sales_summary_rebuilt",),
    ),
    RagMemorySourceType.INVENTORY_HISTORY: _source(
        RagMemorySourceType.INVENTORY_HISTORY,
        table="inventory_history",
        model="InventoryHistory",
        adapter="_backfill_inventory_lifecycle",
        builder="build_from_inventory_snapshot_or_risk",
        fields=("snapshot_date", "quantity_on_hand", "quantity_reserved", "quantity_available", "quantity_incoming", "source", "captured_at"),
        date_field="captured_at",
        triggers=("inventory_snapshot_created",),
    ),
    RagMemorySourceType.INVENTORY_LIFECYCLE: _source(
        RagMemorySourceType.INVENTORY_LIFECYCLE,
        table="inventory_history",
        model="InventoryHistory",
        adapter="_backfill_inventory_lifecycle",
        builder="build_from_inventory_lifecycle",
        fields=("snapshot_date", "quantity_on_hand", "quantity_reserved", "quantity_available", "quantity_incoming", "captured_at"),
        date_field="captured_at",
        triggers=("inventory_snapshot_created", "stock_in_created", "stockout_prediction_created", "inventory_risk_assessed", "reorder_recommendation_created"),
    ),
    RagMemorySourceType.PRICE_HISTORY: _source(
        RagMemorySourceType.PRICE_HISTORY,
        table="dynamic_pricing_recommendations",
        model="DynamicPricingRecommendation",
        adapter="_backfill_pricing_history",
        builder="build_from_pricing_recommendation",
        fields=("action", "current_price", "recommended_price", "minimum_safe_price", "expected_revenue", "expected_profit", "confidence_score", "recommendation_status", "generated_at"),
        date_field="generated_at",
        sensitivity=RagMemorySensitivityLevel.CONFIDENTIAL,
        triggers=("dynamic_pricing_recommendation_created", "pricing_policy_updated", "fee_policy_updated"),
    ),
    RagMemorySourceType.PRICING_HISTORY: _source(
        RagMemorySourceType.PRICING_HISTORY,
        table="pricing_analytics_snapshots",
        model="PricingAnalyticsSnapshot",
        adapter="_backfill_pricing_history",
        builder="build_from_pricing_history",
        fields=("current_price", "unit_cost", "minimum_safe_price", "current_margin_rate", "competitor_count", "demand_score", "data_status", "confidence_score", "calculated_at"),
        date_field="calculated_at",
        sensitivity=RagMemorySensitivityLevel.CONFIDENTIAL,
        triggers=("pricing_analytics_calculated", "dynamic_pricing_recommendation_created"),
    ),
    RagMemorySourceType.SELLER_PRICE_HISTORY: _source(
        RagMemorySourceType.SELLER_PRICE_HISTORY,
        table="product_price_history",
        model="ProductPriceHistory",
        adapter="_backfill_seller_price_history",
        builder="build_from_seller_price_history",
        fields=("product_id", "listing_id", "marketplace", "old_price", "new_price", "currency", "reason", "source", "changed_at", "created_at"),
        date_field="changed_at",
        sensitivity=RagMemorySensitivityLevel.CONFIDENTIAL,
        triggers=("product_price_changed", "listing_price_changed", "seller_price_baseline_created"),
    ),
    RagMemorySourceType.COMPETITOR_HISTORY: _source(
        RagMemorySourceType.COMPETITOR_HISTORY,
        table="competitor_events",
        model="CompetitorEvent",
        adapter="_backfill_competitor_history",
        builder="build_from_competitor_event",
        fields=("event_type", "old_value", "new_value", "price_change_amount", "price_change_percent", "severity", "detected_at"),
        date_field="detected_at",
        triggers=("competitor_event_created", "competitor_snapshot_created", "market_opportunity_created", "scrape_run_completed"),
    ),
    RagMemorySourceType.DEAD_STOCK: _source(
        RagMemorySourceType.DEAD_STOCK,
        table="dead_stock_assessments",
        model="DeadStockAssessment",
        adapter="_backfill_dead_stock_history",
        builder="build_from_dead_stock_history",
        fields=("classification", "risk_level", "eligible_quantity", "inventory_age_days", "days_since_last_sale", "confidence_score", "assessed_at"),
        date_field="assessed_at",
        sensitivity=RagMemorySensitivityLevel.CONFIDENTIAL,
        triggers=("dead_stock_assessed", "dead_stock_recovery_created"),
    ),
    RagMemorySourceType.DEAD_STOCK_HISTORY: _source(
        RagMemorySourceType.DEAD_STOCK_HISTORY,
        table="dead_stock_assessments",
        model="DeadStockAssessment",
        adapter="_backfill_dead_stock_history",
        builder="build_from_dead_stock_history",
        fields=("classification", "risk_level", "eligible_quantity", "inventory_age_days", "days_since_last_sale", "confidence_score", "assessed_at"),
        date_field="assessed_at",
        sensitivity=RagMemorySensitivityLevel.CONFIDENTIAL,
        triggers=("dead_stock_assessed", "capital_recovery_estimated"),
    ),
    RagMemorySourceType.SEO: _source(
        RagMemorySourceType.SEO,
        table="product_visibility_metrics",
        model="ProductVisibilityMetric",
        adapter="_backfill_seo_visibility_history",
        builder="build_from_visibility_metric",
        fields=("metric_date", "impressions", "views", "clicks", "search_rank", "listing_quality_score", "conversion_rate", "source"),
        date_field="metric_date",
        triggers=("visibility_metric_created",),
    ),
    RagMemorySourceType.SEO_VISIBILITY_HISTORY: _source(
        RagMemorySourceType.SEO_VISIBILITY_HISTORY,
        table="product_visibility_metrics",
        model="ProductVisibilityMetric",
        adapter="_backfill_seo_visibility_history",
        builder="build_from_visibility_metric",
        fields=("metric_date", "impressions", "views", "clicks", "search_rank", "listing_quality_score", "conversion_rate", "source"),
        date_field="metric_date",
        triggers=("visibility_metric_created",),
    ),
    RagMemorySourceType.ALERT: _source(
        RagMemorySourceType.ALERT,
        table="alerts",
        model="Alert",
        adapter="_backfill_alert_history",
        builder="build_from_alert",
        fields=("alert_type", "urgency_level", "action_type", "confidence", "delivery_status", "delivered_at", "read_at", "created_at"),
        date_field="created_at",
        triggers=("alert_created", "alert_delivery_status_changed", "telegram_connection_updated"),
    ),
    RagMemorySourceType.ALERT_HISTORY: _source(
        RagMemorySourceType.ALERT_HISTORY,
        table="alerts",
        model="Alert",
        adapter="_backfill_alert_history",
        builder="build_from_alert_history",
        fields=("alert_type", "urgency_level", "action_type", "confidence", "delivery_status", "delivered_at", "read_at", "created_at"),
        date_field="created_at",
        triggers=("alert_created", "alert_delivery_logged", "telegram_connection_updated"),
    ),
    RagMemorySourceType.RECOMMENDATION: _source(
        RagMemorySourceType.RECOMMENDATION,
        table="recommendations",
        model="Recommendation",
        adapter="_backfill_recommendation_history",
        builder="build_from_recommendation",
        fields=("action", "confidence", "reasoning_bn", "suggested_price_min", "suggested_price_max", "revenue_opportunity", "created_at"),
        date_field="created_at",
        sensitivity=RagMemorySensitivityLevel.CONFIDENTIAL,
        triggers=("recommendation_created", "recommendation_updated"),
    ),
    RagMemorySourceType.RECOMMENDATION_HISTORY: _source(
        RagMemorySourceType.RECOMMENDATION_HISTORY,
        table="recommendations",
        model="Recommendation",
        adapter="_backfill_recommendation_history",
        builder="build_from_recommendation_history",
        fields=("action", "confidence", "reasoning_bn", "suggested_price_min", "suggested_price_max", "revenue_opportunity", "created_at"),
        date_field="created_at",
        sensitivity=RagMemorySensitivityLevel.CONFIDENTIAL,
        triggers=("recommendation_created", "reorder_recommendation_created", "pricing_recommendation_created", "dead_stock_recovery_created"),
    ),
    RagMemorySourceType.COPILOT_HISTORY: _source(
        RagMemorySourceType.COPILOT_HISTORY,
        table="copilot_messages",
        model="CopilotMessage",
        adapter="_backfill_copilot_history",
        builder="build_from_copilot_history",
        fields=("role", "content", "answer_confidence", "created_at"),
        date_field="created_at",
        product_field=None,
        sensitivity=RagMemorySensitivityLevel.CONFIDENTIAL,
        visibility=RagMemoryVisibilityScope.SELLER,
        triggers=("copilot_message_created", "copilot_action_proposal_updated"),
    ),
    RagMemorySourceType.PROMOTION_PLAN: _source(
        RagMemorySourceType.PROMOTION_PLAN,
        table="promotion_plans",
        model="PromotionPlan",
        adapter="_backfill_promotion_plans",
        builder="build_from_promotion_plan",
        fields=("product_id", "category", "marketplace", "promotion_type", "title", "description", "proposed_discount_rate", "proposed_price", "planned_start_at", "planned_end_at", "status", "source", "expected_impact_json", "created_at", "updated_at"),
        date_field="updated_at",
        sensitivity=RagMemorySensitivityLevel.CONFIDENTIAL,
        triggers=("promotion_plan_created", "promotion_plan_updated"),
    ),
    RagMemorySourceType.PROMOTION_RESULT: _source(
        RagMemorySourceType.PROMOTION_RESULT,
        table="promotion_results",
        model="PromotionResult",
        adapter="_backfill_promotion_results",
        builder="build_from_promotion_result",
        fields=("promotion_plan_id", "product_id", "marketplace", "started_at", "ended_at", "units_sold", "gross_revenue", "estimated_profit", "spend", "discount_cost", "roi", "result_status", "missing_data_json"),
        date_field="ended_at",
        sensitivity=RagMemorySensitivityLevel.CONFIDENTIAL,
        triggers=("promotion_result_created", "promotion_result_updated"),
    ),
    RagMemorySourceType.ACTION_CENTER: _source(
        RagMemorySourceType.ACTION_CENTER,
        table=None,
        model=None,
        adapter=None,
        builder=None,
        fields=(),
        date_field=None,
        product_field=None,
        implemented=False,
        reindex=False,
        coverage="not_implemented_no_action_center_model",
        visibility=RagMemoryVisibilityScope.SELLER,
    ),
    RagMemorySourceType.SUPPORT_LOG: _source(
        RagMemorySourceType.SUPPORT_LOG,
        table=None,
        model=None,
        adapter=None,
        builder=None,
        fields=(),
        date_field=None,
        product_field=None,
        implemented=False,
        reindex=False,
        coverage="not_implemented_no_support_log_policy",
        visibility=RagMemoryVisibilityScope.SELLER,
    ),
    RagMemorySourceType.CUSTOMER_CONTEXT: _source(
        RagMemorySourceType.CUSTOMER_CONTEXT,
        table=None,
        model=None,
        adapter=None,
        builder=None,
        fields=(),
        date_field=None,
        product_field=None,
        implemented=False,
        reindex=False,
        coverage="not_implemented_requires_explicit_customer_data_policy",
        sensitivity=RagMemorySensitivityLevel.CONFIDENTIAL,
        visibility=RagMemoryVisibilityScope.SELLER,
    ),
}


def get_rag_source_definition(source_type: RagMemorySourceType) -> RagSourceDefinition:
    try:
        return RAG_SOURCE_REGISTRY[source_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported RAG memory source type: {source_type}") from exc


def implemented_source_types() -> list[RagMemorySourceType]:
    return [source_type for source_type, definition in RAG_SOURCE_REGISTRY.items() if definition.implemented]
