from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import re
from typing import Any, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import settings
from app.services.copilot.business_data_catalog import BusinessDataCatalogService
from app.services.copilot.date_range_parser import CopilotDateRangeParser, ParsedDateRange, default_period
from app.services.copilot.entity_resolver import CopilotEntityResolver, EntityResolutionResult, ResolvedProductEntity
from app.services.copilot.safety_rules import apply_strict_safety
from app.services.copilot.intent_classifier import CopilotIntent, CopilotIntentResult
from app.services.copilot.metric_catalog import MetricCatalogService
from app.services.copilot.query_constraints import BusinessDomainKey
from app.models.rag_memory import RagMemorySourceType

CONTEXT_FOLLOWUP_CUES = (
    "what about",
    "how about",
    "and last",
    "last week",
    "last month",
    "previous",
    "before",
    "that product",
    "same product",
    "cheapest",
    "involved",
    "what happened",
    "আগে",
    "গত",
)
DEFAULT_EXECUTION_TOOL_LIMIT = 10
GENERAL_BUSINESS_ALIASES = (
    "how is my business",
    "business doing",
    "overall business",
    "business health",
    "pulse check",
    "red flags",
    "dashboard",
    "business status",
    "biggest problem",
    "biggest problems",
    "need attention",
    "needs attention",
    "focus on",
    "what changed",
    "changed since",
    "what should i focus",
    "কি অবস্থা",
    "ব্যবসা কেমন",
)
DOMAIN_ALIASES: dict[BusinessDomainKey, tuple[str, ...]] = {
    BusinessDomainKey.PRODUCT_CATALOG: ("product", "products", "catalog", "sku", "listing", "listed", "setup", "item"),
    BusinessDomainKey.SALES_REVENUE: ("revenue", "sales", "sold", "orders", "aov", "income", "earning", "বিক্রি", "রেভিনিউ"),
    BusinessDomainKey.PROFIT_MARGIN: ("profit", "margin", "fee", "cost", "contribution", "লাভ"),
    BusinessDomainKey.INVENTORY: ("inventory", "stock", "stockout", "reorder", "restock", "velocity", "ইনভেন্টরি", "স্টক"),
    BusinessDomainKey.COMPETITOR: ("competitor", "cheapest", "undercut", "threat", "ranking", "price gap", "প্রতিযোগী"),
    BusinessDomainKey.PRICING: ("price", "pricing", "discount", "marginguard", "elasticity", "price history", "price changes"),
    BusinessDomainKey.PROMOTION: ("promotion", "campaign", "deal", "discount", "roi"),
    BusinessDomainKey.DEAD_STOCK: ("dead stock", "slow moving", "overstock", "locked capital", "stuck inventory"),
    BusinessDomainKey.SEO_VISIBILITY: ("seo", "visibility", "impressions", "clicks", "ctr", "rank", "listing quality"),
    BusinessDomainKey.RECOMMENDATIONS: ("recommendation", "recommended", "action", "today", "focus", "attention"),
    BusinessDomainKey.ALERTS: ("alert", "notification", "warning", "unresolved", "red flags"),
    BusinessDomainKey.RAG_MEMORY: ("memory", "history", "previous", "before", "last time"),
}
METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "product_count": ("how many products", "number of products", "count products", "products listed", "product count"),
    "listed_product_count": ("listed products", "active listings"),
    "products_missing_cost_count": ("missing cost", "without cost", "cost missing"),
    "gross_revenue": ("revenue", "sales amount", "income", "earning"),
    "revenue_trend": ("trend", "over time", "changed", "change since", "growth", "decline"),
    "top_products_by_revenue": ("top product", "most revenue", "best selling", "generated most", "highest revenue"),
    "estimated_profit": ("profit", "margin", "earned after cost"),
    "stockout_risk_count": ("stockout", "stock risk", "inventory risk"),
    "low_stock_product_count": ("low stock", "restock", "reorder"),
    "competitor_undercut_count": ("undercut", "cheapest competitor", "competitor cheaper"),
    "competitor_price_gap": ("price gap", "competitor price"),
    "dead_stock_count": ("dead stock", "slow moving", "overstock"),
    "locked_capital": ("locked capital", "stuck money"),
    "pending_recommendation_count": ("pending recommendations", "actions pending"),
    "unresolved_alert_count": ("unresolved alerts", "alerts"),
}
DOMAIN_TOOL_PRIORITIES: dict[BusinessDomainKey, tuple[str, ...]] = {
    BusinessDomainKey.PRODUCT_CATALOG: ("get_product_setup_summary", "count_products", "list_products", "search_products"),
    BusinessDomainKey.SALES_REVENUE: ("get_revenue_summary", "get_sales_trends", "get_top_products_by_revenue"),
    BusinessDomainKey.PROFIT_MARGIN: ("get_profit_summary", "get_margin_safety", "get_fee_policy"),
    BusinessDomainKey.INVENTORY: ("get_inventory_summary", "get_sales_velocity_summary", "get_stockout_summary", "get_reorder_summary", "get_inventory_aging_summary", "get_inventory_risks", "get_sales_velocity", "get_reorder_recommendations"),
    BusinessDomainKey.COMPETITOR: ("get_competitor_summary", "get_competitor_price_change_summary", "get_competitor_undercut_summary", "get_market_opportunity_summary", "get_scrape_health_summary", "get_competitor_threats", "get_competitor_snapshots", "get_market_opportunities"),
    BusinessDomainKey.PRICING: ("get_pricing_summary", "get_fee_policy_summary", "get_pricing_policy_summary", "get_elasticity_summary", "get_seller_price_history_summary", "get_pricing_recommendations", "get_price_history", "get_product_price_changes"),
    BusinessDomainKey.PROMOTION: ("get_promotion_summary", "get_promotion_outcome_summary", "compare_promotion_performance", "get_promotion_results", "get_promotion_recommendations"),
    BusinessDomainKey.DEAD_STOCK: ("get_dead_stock_summary", "get_dead_stock_recovery", "get_capital_recovery_summary"),
    BusinessDomainKey.SEO_VISIBILITY: ("get_visibility_summary", "get_seo_opportunities", "get_visibility_history"),
    BusinessDomainKey.ALERTS: ("get_alert_summary", "get_alert_recommendation_summary", "get_unresolved_alerts", "get_recent_alerts"),
    BusinessDomainKey.RECOMMENDATIONS: ("get_recommendation_summary", "get_today_actions", "get_alert_recommendation_summary", "get_restock_recommendations"),
    BusinessDomainKey.RAG_MEMORY: ("retrieve_business_memory",),
}


class CopilotExecutionQuestionType(str, Enum):
    LOOKUP = "LOOKUP"
    LIST = "LIST"
    COUNT = "COUNT"
    METRIC = "METRIC"
    RANKING = "RANKING"
    COMPARISON = "COMPARISON"
    TREND = "TREND"
    DIAGNOSTIC = "DIAGNOSTIC"
    RECOMMENDATION = "RECOMMENDATION"
    MEMORY = "MEMORY"
    ACTION_PROPOSAL = "ACTION_PROPOSAL"
    GENERAL_BUSINESS = "GENERAL_BUSINESS"


class ResolvedEntitiesPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_ids: list[str] = Field(default_factory=list)
    competitor_ids: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    marketplaces: list[str] = Field(default_factory=list)


class DateRangePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_date: date | None = None
    to_date: date | None = None
    comparison_from_date: date | None = None
    comparison_to_date: date | None = None

    @model_validator(mode="after")
    def _valid_ranges(self) -> "DateRangePlan":
        if self.from_date and self.to_date and self.from_date > self.to_date:
            raise ValueError("from_date must be on or before to_date")
        if self.comparison_from_date and self.comparison_to_date and self.comparison_from_date > self.comparison_to_date:
            raise ValueError("comparison_from_date must be on or before comparison_to_date")
        return self


class MetricQueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_key: str
    filters: dict[str, Any] = Field(default_factory=dict)
    group_by: list[str] = Field(default_factory=list)


class ToolCallPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    required: bool = True


class MemoryQueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    source_types: list[RagMemorySourceType] = Field(default_factory=list)
    top_k: int = Field(default=8, ge=1, le=20)


class CopilotExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_type: CopilotExecutionQuestionType
    resolved_entities: ResolvedEntitiesPlan = Field(default_factory=ResolvedEntitiesPlan)
    date_range: DateRangePlan = Field(default_factory=DateRangePlan)
    domains: list[BusinessDomainKey] = Field(default_factory=list)
    metric_queries: list[MetricQueryPlan] = Field(default_factory=list)
    tool_calls: list[ToolCallPlan] = Field(default_factory=list)
    memory_query: MemoryQueryPlan = Field(default_factory=MemoryQueryPlan)
    requires_clarification: bool = False
    clarification_question: str | None = None
    safety_flags: list[str] = Field(default_factory=list)


class CopilotQuestionType(str, Enum):
    LOOKUP = "LOOKUP"
    ANALYTIC = "ANALYTIC"
    DIAGNOSTIC = "DIAGNOSTIC"
    RECOMMENDATION = "RECOMMENDATION"
    ACTION_REQUEST = "ACTION_REQUEST"
    MEMORY_SEARCH = "MEMORY_SEARCH"
    GENERAL_BUSINESS = "GENERAL_BUSINESS"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class PlannedToolCall:
    tool_name: str
    args: dict[str, Any]
    reason: str
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "args": _json_safe(self.args),
            "reason": self.reason,
            "required": self.required,
        }


@dataclass(frozen=True, slots=True)
class MemorySearchPlan:
    enabled: bool = True
    source_types: list[str] = field(default_factory=list)
    top_k: int = 8

    def to_dict(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "source_types": self.source_types, "top_k": self.top_k}


@dataclass(frozen=True, slots=True)
class PlannedEntities:
    products: list[dict[str, Any]]
    categories: list[str]
    marketplaces: list[str]
    competitors: list[str]
    competitor_ids: list[str]
    date_range: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "products": self.products,
            "categories": self.categories,
            "marketplaces": self.marketplaces,
            "competitors": self.competitors,
            "competitor_ids": self.competitor_ids,
            "date_range": self.date_range,
        }


@dataclass(frozen=True, slots=True)
class CopilotPlanningContext:
    recent_messages: list[dict[str, Any]] = field(default_factory=list)
    active_products: list[dict[str, Any]] = field(default_factory=list)
    active_competitors: list[str] = field(default_factory=list)
    active_competitor_ids: list[str] = field(default_factory=list)
    active_categories: list[str] = field(default_factory=list)
    active_marketplaces: list[str] = field(default_factory=list)
    active_date_range: dict[str, Any] | None = None
    active_metrics: list[str] = field(default_factory=list)
    active_domains: list[str] = field(default_factory=list)
    pending_clarification: str | None = None
    last_successful_plan: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "recent_messages": list(self.recent_messages),
            "active_products": list(self.active_products),
            "active_competitors": list(self.active_competitors),
            "active_competitor_ids": list(self.active_competitor_ids),
            "active_categories": list(self.active_categories),
            "active_marketplaces": list(self.active_marketplaces),
            "active_date_range": dict(self.active_date_range) if self.active_date_range else None,
            "active_metrics": list(self.active_metrics),
            "active_domains": list(self.active_domains),
            "pending_clarification": self.pending_clarification,
            "last_successful_plan": dict(self.last_successful_plan) if self.last_successful_plan else None,
        }


@dataclass(frozen=True, slots=True)
class CopilotQuestionPlan:
    question_type: CopilotQuestionType
    language: str
    entities: PlannedEntities
    required_domains: list[str]
    metric_plan: list[str]
    tool_plan: list[PlannedToolCall]
    memory_search_plan: MemorySearchPlan
    needs_clarification: bool = False
    clarification_question: str | None = None
    safety_flags: list[str] = field(default_factory=list)
    execution_plan: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_type": self.question_type.value,
            "language": self.language,
            "entities": self.entities.to_dict(),
            "required_domains": self.required_domains,
            "metric_plan": list(self.metric_plan),
            "tool_plan": [item.to_dict() for item in self.tool_plan],
            "memory_search_plan": self.memory_search_plan.to_dict(),
            "needs_clarification": self.needs_clarification,
            "clarification_question": self.clarification_question,
            "safety_flags": list(self.safety_flags),
            "execution_plan": self.execution_plan,
        }


def build_planning_context_from_messages(messages: list[dict[str, Any]] | None) -> CopilotPlanningContext:
    recent = list(messages or [])
    active_products: list[dict[str, Any]] = []
    active_competitors: list[str] = []
    active_competitor_ids: list[str] = []
    active_categories: list[str] = []
    active_marketplaces: list[str] = []
    active_date_range: dict[str, Any] | None = None
    active_metrics: list[str] = []
    active_domains: list[str] = []
    pending_clarification: str | None = None
    last_successful_plan: dict[str, Any] | None = None

    for message in recent:
        if not isinstance(message, dict):
            continue
        metadata = message.get("response_metadata") if isinstance(message.get("response_metadata"), dict) else {}
        stored_context = metadata.get("planning_context") if isinstance(metadata.get("planning_context"), dict) else {}
        plan = (
            stored_context.get("last_successful_plan")
            if isinstance(stored_context.get("last_successful_plan"), dict)
            else metadata.get("last_successful_plan")
            if isinstance(metadata.get("last_successful_plan"), dict)
            else None
        )
        if isinstance(plan, dict):
            last_successful_plan = plan
            active_domains = _dedupe_strings(_string_list(plan.get("required_domains")) or active_domains)
            active_metrics = _dedupe_strings(_string_list(plan.get("metric_plan")) or active_metrics)
            entities = plan.get("entities") if isinstance(plan.get("entities"), dict) else {}
            products = entities.get("products") if isinstance(entities, dict) else []
            if isinstance(products, list) and products:
                active_products = _safe_products(products)
            if isinstance(entities, dict):
                active_categories = _dedupe_strings(_string_list(entities.get("categories")) or active_categories)
                active_marketplaces = _dedupe_strings(_string_list(entities.get("marketplaces")) or active_marketplaces)
                active_competitors = _dedupe_strings(_string_list(entities.get("competitors")) or active_competitors)
                active_competitor_ids = _dedupe_strings(_string_list(entities.get("competitor_ids")) or active_competitor_ids)
                if isinstance(entities.get("date_range"), dict):
                    active_date_range = dict(entities["date_range"])
        if isinstance(stored_context, dict):
            active_products = _safe_products(stored_context.get("active_products")) or active_products
            active_competitors = _dedupe_strings(_string_list(stored_context.get("active_competitors")) or active_competitors)
            active_competitor_ids = _dedupe_strings(_string_list(stored_context.get("active_competitor_ids")) or active_competitor_ids)
            active_categories = _dedupe_strings(_string_list(stored_context.get("active_categories")) or active_categories)
            active_marketplaces = _dedupe_strings(_string_list(stored_context.get("active_marketplaces")) or active_marketplaces)
            active_metrics = _dedupe_strings(_string_list(stored_context.get("active_metrics")) or active_metrics)
            active_domains = _dedupe_strings(_string_list(stored_context.get("active_domains")) or active_domains)
            if isinstance(stored_context.get("active_date_range"), dict):
                active_date_range = dict(stored_context["active_date_range"])
            if isinstance(stored_context.get("pending_clarification"), str):
                pending_clarification = stored_context["pending_clarification"]
        if isinstance(metadata.get("pending_clarification"), str):
            pending_clarification = metadata["pending_clarification"]
        if isinstance(message.get("domains_used"), list) and message["domains_used"]:
            active_domains = _dedupe_strings([*active_domains, *_string_list(message["domains_used"])])

    return CopilotPlanningContext(
        recent_messages=recent,
        active_products=active_products,
        active_competitors=active_competitors,
        active_competitor_ids=active_competitor_ids,
        active_categories=active_categories,
        active_marketplaces=active_marketplaces,
        active_date_range=active_date_range,
        active_metrics=active_metrics,
        active_domains=active_domains,
        pending_clarification=pending_clarification,
        last_successful_plan=last_successful_plan,
    )


class ToolRegistryLike(Protocol):
    def list_tools(self) -> list[Any]: ...
    def validate_arguments(self, name: str, arguments: dict[str, Any]) -> tuple[bool, dict[str, Any] | None, str | None]: ...


class CopilotPlanValidator:
    def __init__(
        self,
        *,
        metric_catalog: MetricCatalogService,
        tool_registry: Any,
        max_tools: int,
        include_current_data: bool,
        include_memory: bool,
    ) -> None:
        self._metric_catalog = metric_catalog
        self._tool_registry = tool_registry
        self._max_tools = max(1, max_tools)
        self._include_current_data = include_current_data
        self._include_memory = include_memory
        self._tools = {tool.name: tool for tool in getattr(tool_registry, "list_tools", lambda: [])()}
        self._metric_executor_metrics = set(getattr(self._tools.get("run_seller_metric_query"), "catalog_metrics", ()) or ())

    def validate(self, plan: CopilotExecutionPlan) -> CopilotExecutionPlan:
        safety_flags = list(plan.safety_flags)
        valid_metric_queries: list[MetricQueryPlan] = []
        for query in plan.metric_queries:
            try:
                metric = self._metric_catalog.validate_metric_query(
                    query.metric_key,
                    filters={key: value for key, value in query.filters.items() if key != "seller_id"} | {"seller_id": "seller_scope"},
                    group_by=query.group_by,
                )
            except Exception as exc:
                # Snapshot metrics (e.g. product counts) take no dates; drop the chat's date filter instead of the metric.
                undated = {key: value for key, value in query.filters.items() if key not in {"from_date", "to_date"}}
                if undated == query.filters:
                    safety_flags.append(f"INVALID_METRIC:{query.metric_key}:{exc}")
                    continue
                try:
                    metric = self._metric_catalog.validate_metric_query(
                        query.metric_key,
                        filters={key: value for key, value in undated.items() if key != "seller_id"} | {"seller_id": "seller_scope"},
                        group_by=query.group_by,
                    )
                except Exception:
                    safety_flags.append(f"INVALID_METRIC:{query.metric_key}:{exc}")
                    continue
                query = query.model_copy(update={"filters": undated})
                safety_flags.append(f"METRIC_DATE_FILTER_IGNORED:{query.metric_key}")
            if not metric.is_selectable_for_execution:
                safety_flags.append(f"UNSUPPORTED_METRIC:{query.metric_key}")
                continue
            if query.metric_key not in self._metric_executor_metrics:
                safety_flags.append(f"UNSUPPORTED_METRIC_EXECUTOR:{query.metric_key}")
                continue
            del metric
            valid_metric_queries.append(query)

        valid_tool_calls: list[ToolCallPlan] = []
        for call in plan.tool_calls:
            if len(valid_tool_calls) >= self._max_tools:
                safety_flags.append("TOOL_LIMIT_ENFORCED")
                break
            if call.tool_name == "retrieve_business_memory":
                if not self._include_memory:
                    safety_flags.append("MEMORY_TOOL_SKIPPED_BY_MODE")
                    continue
            elif not self._include_current_data:
                safety_flags.append(f"CURRENT_DATA_TOOL_SKIPPED_BY_MODE:{call.tool_name}")
                continue
            if call.tool_name not in self._tools:
                safety_flags.append(f"UNKNOWN_TOOL:{call.tool_name}")
                continue
            validate = getattr(self._tool_registry, "validate_arguments", None)
            if validate is not None:
                is_valid, parsed, error = validate(call.tool_name, call.args)
                if not is_valid:
                    safety_flags.append(f"INVALID_TOOL_ARGS:{call.tool_name}:{error}")
                    continue
                valid_tool_calls.append(call.model_copy(update={"args": parsed or call.args}))
            else:
                valid_tool_calls.append(call)

        memory_query = plan.memory_query
        if not self._include_memory:
            memory_query = memory_query.model_copy(update={"enabled": False, "source_types": []})
        return plan.model_copy(
            update={
                "metric_queries": valid_metric_queries,
                "tool_calls": valid_tool_calls,
                "memory_query": memory_query,
                "safety_flags": safety_flags,
            }
        )


class CopilotQuestionPlanner:
    def __init__(
        self,
        *,
        business_catalog: BusinessDataCatalogService | None = None,
        metric_catalog: MetricCatalogService | None = None,
        entity_resolver: CopilotEntityResolver | None = None,
        date_range_parser: CopilotDateRangeParser | None = None,
        now: datetime | None = None,
        strict_safety: bool | None = None,
    ) -> None:
        self._business_catalog = business_catalog or BusinessDataCatalogService()
        self._strict_safety = settings.copilot_strict_safety_planning_enabled if strict_safety is None else strict_safety
        self._metric_catalog = metric_catalog or MetricCatalogService()
        self._entity_resolver = entity_resolver or CopilotEntityResolver()
        self._date_range_parser = date_range_parser or CopilotDateRangeParser(now=now)
        self._now = now

    def plan(
        self,
        *,
        seller_id: UUID,
        question: str,
        language: str,
        conversation_history: list[dict[str, Any]] | None,
        product_id: UUID | None,
        from_date: date | None,
        to_date: date | None,
        top_k: int,
        include_memory: bool,
        business_catalog: BusinessDataCatalogService | None,
        metric_catalog: MetricCatalogService | None,
        tool_registry: Any,
        classification_hint: CopilotIntentResult,
        max_tools: int,
        domain_filters: list[BusinessDomainKey] | None = None,
        include_current_data: bool = True,
        memory_source_types: list[RagMemorySourceType] | None = None,
        planning_context: CopilotPlanningContext | dict[str, Any] | None = None,
    ) -> CopilotQuestionPlan:
        context = _coerce_planning_context(planning_context, conversation_history)
        business_catalog = business_catalog or self._business_catalog
        metric_catalog = metric_catalog or self._metric_catalog
        normalized = _normalize(question)
        date_result = self._date_range_parser.parse(question, explicit_from_date=from_date, explicit_to_date=to_date)
        inherited_context_allowed = _should_use_context(normalized, context)
        context_date_range = _context_date_range(context) if inherited_context_allowed and not from_date and not to_date else None
        date_range = date_result.date_range or _date_range_from_hint(classification_hint) or context_date_range
        # One stated window for every dated tool and metric, so their facts never disagree.
        date_range = date_range or default_period(self._date_range_parser.today())
        entities = self._entity_resolver.resolve(seller_id=seller_id, question=question, product_id=product_id)
        if inherited_context_allowed:
            entities = _merge_context_entities(entities, context)
        base_question_type = _question_type(normalized, classification_hint)
        domains = _matched_domains(normalized, business_catalog, base_question_type)
        if domain_filters:
            domains = _dedupe_domains(domain_filters)
        elif inherited_context_allowed:
            domains = _dedupe_domains(domains + _context_domains(context))
        metrics = _matched_metrics(normalized, metric_catalog, base_question_type)
        if inherited_context_allowed:
            metrics = list(dict.fromkeys(metrics + context.active_metrics))
        execution_question_type = _execution_question_type(
            normalized=normalized,
            classification_hint=classification_hint,
            domains=domains,
            metrics=metrics,
            inherited_context_allowed=inherited_context_allowed,
        )
        question_type = _legacy_question_type(execution_question_type)
        question_type = _question_type_from_context(question_type, context, inherited_context_allowed)
        available_tools = _available_tool_names(tool_registry, classification_hint.suggested_tools)
        tool_steps = self._build_tool_steps(
            question=question,
            normalized=normalized,
            question_type=question_type,
            classification_hint=classification_hint,
            domains=domains,
            metrics=metrics,
            entities=entities,
            date_range=date_range,
            include_current_data=include_current_data,
            memory_source_types=memory_source_types,
            top_k=top_k,
            include_memory=include_memory,
            available_tools=available_tools,
        )
        safety_flags = []
        if date_result.invalid_reason:
            safety_flags.append(f"INVALID_DATE_RANGE: {date_result.invalid_reason}")
        if question_type == CopilotQuestionType.ACTION_REQUEST:
            safety_flags.append("ACTION_PROPOSAL_ONLY")
        if entities.clarification_question:
            ambiguity = next(
                (
                    resolution.entity_type
                    for resolution in (
                        entities.product_resolution,
                        entities.category_resolution,
                        entities.marketplace_resolution,
                        entities.competitor_resolution,
                    )
                    if resolution and resolution.ambiguous
                ),
                "ENTITY",
            )
            safety_flags.append(f"{ambiguity}_AMBIGUITY")
        safety_flags.extend(item for item in entities.missing_data if item not in safety_flags)

        bounded = self._validate_and_bound(tool_steps, tool_registry=tool_registry, max_tools=max_tools, safety_flags=safety_flags)
        execution_plan = _execution_plan_from_candidates(
            question_type=execution_question_type,
            entities=entities,
            date_range=date_range,
            domains=domains,
            metrics=metrics,
            tool_steps=bounded,
            include_memory=include_memory,
            memory_source_types=memory_source_types,
            top_k=top_k,
            needs_clarification=bool(entities.clarification_question),
            clarification_question=entities.clarification_question,
            safety_flags=safety_flags,
        )
        execution_plan = CopilotPlanValidator(
            metric_catalog=metric_catalog,
            tool_registry=tool_registry,
            max_tools=max_tools,
            include_current_data=include_current_data,
            include_memory=include_memory,
        ).validate(execution_plan)
        bounded = [PlannedToolCall(item.tool_name, item.args, item.reason, item.required) for item in execution_plan.tool_calls]
        safety_flags = list(execution_plan.safety_flags)
        memory_enabled = include_memory and any(step.tool_name == "retrieve_business_memory" for step in bounded)
        memory_plan = MemorySearchPlan(
            enabled=memory_enabled,
            source_types=[source_type.value for source_type in execution_plan.memory_query.source_types] if execution_plan.memory_query.source_types else _source_types_for_domains(domains, business_catalog),
            top_k=max(1, min(top_k, 20)),
        )
        planned_entities = PlannedEntities(
            products=[item.to_dict() for item in entities.products],
            categories=entities.categories,
            marketplaces=entities.marketplaces,
            competitors=entities.competitors,
            competitor_ids=entities.competitor_ids,
            date_range=date_range.to_dict() if date_range else None,
        )
        plan = CopilotQuestionPlan(
            question_type=question_type,
            language=language,
            entities=planned_entities,
            required_domains=[domain.value for domain in domains],
            metric_plan=[metric for metric in metrics],
            tool_plan=bounded,
            memory_search_plan=memory_plan,
            needs_clarification=bool(entities.clarification_question),
            clarification_question=entities.clarification_question,
            safety_flags=safety_flags,
            execution_plan=execution_plan.model_dump(mode="json"),
        )
        if self._strict_safety:
            plan = apply_strict_safety(plan, question=question)
        return plan

    def _build_tool_steps(
        self,
        *,
        question: str,
        normalized: str,
        question_type: CopilotQuestionType,
        classification_hint: CopilotIntentResult,
        domains: list[BusinessDomainKey],
        metrics: list[str],
        entities: EntityResolutionResult,
        date_range: ParsedDateRange | None,
        include_current_data: bool,
        memory_source_types: list[RagMemorySourceType] | None,
        top_k: int,
        include_memory: bool,
        available_tools: set[str],
    ) -> list[PlannedToolCall]:
        steps: list[PlannedToolCall] = []
        product_id = _resolved_product_id(entities)
        competitor_id = _resolved_competitor_id(entities)
        category = entities.categories[0] if entities.categories else None
        marketplace = entities.marketplaces[0] if entities.marketplaces else None

        def add(tool_name: str, reason: str, args: dict[str, Any] | None = None, *, required: bool = True) -> None:
            if tool_name not in available_tools:
                return
            if tool_name != "retrieve_business_memory" and not include_current_data:
                return
            if tool_name != "run_seller_metric_query" and any(step.tool_name == tool_name for step in steps):
                return
            steps.append(PlannedToolCall(tool_name=tool_name, args=args or {}, reason=reason, required=required))

        if question_type == CopilotQuestionType.GENERAL_BUSINESS:
            if classification_hint.intent == CopilotIntent.TODAY_ACTIONS:
                # The action-center feed answers "what should I do today"; keep it ahead of the tool cap.
                add("get_today_actions", "today's prioritized action candidates requested", _limit_args(product_id))
            add("get_business_overview", "broad business summary requested", _optional_dated_args(None, date_range) | _category_marketplace(category, marketplace))
            add("get_revenue_summary", "broad summary includes revenue trend", _dated_args(product_id, date_range, category, marketplace) | {"compare_to_previous_period": True})
            add("get_profit_summary", "broad summary includes profit health", _dated_args(product_id, date_range, category, marketplace))
            add("get_inventory_summary", "broad summary includes inventory health", _source_args(product_id, date_range, category, marketplace))
            add("get_inventory_risks", "broad summary includes risk domain", _limit_args(product_id))
            add("get_competitor_summary", "broad summary includes competitor health", _source_args(product_id, date_range, category, marketplace))
            add("get_competitor_threats", "broad summary includes competitor domain", _optional_dated_args(product_id, date_range) | {"limit": 10})
            add("get_pricing_summary", "broad summary includes pricing health", _source_args(product_id, date_range, category, marketplace))
            add("get_pricing_recommendations", "broad summary includes pricing domain", _limit_args(product_id))
            add("get_dead_stock_summary", "broad summary includes dead-stock risk", _source_args(product_id, date_range, category, marketplace))
            add("get_alert_recommendation_summary", "broad summary includes alert and recommendation state", _source_args(product_id, date_range, category, marketplace))
            add("get_today_actions", "broad summary includes action candidates", _limit_args(product_id))

        if BusinessDomainKey.SALES_REVENUE in domains or any(metric in metrics for metric in ("gross_revenue", "revenue_trend", "revenue_change", "top_products_by_revenue")):
            add("run_seller_metric_query", "allowlisted gross revenue metric requested", _metric_args("gross_revenue", product_id, date_range, category, marketplace))
            add("run_seller_metric_query", "allowlisted revenue trend metric requested", _metric_args("revenue_trend", product_id, date_range, category, marketplace) | {"group_by": ["day"]})
            add("get_revenue_summary", "deterministic revenue metric requested", _dated_args(product_id, date_range, category, marketplace) | {"compare_to_previous_period": True})
            add("get_sales_trends", "deterministic sales trend evidence requested", _dated_args(product_id, date_range, category, marketplace) | {"granularity": "daily"})
            if question_type == CopilotQuestionType.DIAGNOSTIC:
                add("explain_revenue_change_deterministic", "deterministic revenue change diagnosis requested", _dated_args(product_id, date_range, category, marketplace) | {"compare_to_previous_period": True})
                add("explain_revenue_drop", "legacy deterministic revenue drop diagnosis", _dated_args(product_id, date_range, None, None) | {"compare_to_previous_period": True})
                add("get_competitor_threats", "diagnosis checks competitor pressure", _optional_dated_args(product_id, date_range) | {"limit": 10})
                if include_memory:
                    add("retrieve_business_memory", "memory context for revenue diagnosis", _memory_args(question, product_id, date_range, memory_source_types, top_k), required=False)

        if classification_hint.intent != CopilotIntent.UNKNOWN:
            for tool_name in classification_hint.suggested_tools:
                if tool_name == "retrieve_business_memory" and not include_memory:
                    continue
                add(tool_name, "safe legacy intent hint", _args_for_tool(tool_name, question, product_id, date_range, category, marketplace, memory_source_types, top_k))
        elif classification_hint.suggested_tools:
            for tool_name in classification_hint.suggested_tools:
                add(tool_name, "legacy unknown-intent hint for registry validation", _args_for_tool(tool_name, question, product_id, date_range, category, marketplace, memory_source_types, top_k), required=False)

        if question_type == CopilotQuestionType.MEMORY_SEARCH and include_memory:
            add("retrieve_business_memory", "memory search requested", _memory_args(question, product_id, date_range, memory_source_types, top_k), required=False)

        if question_type == CopilotQuestionType.LOOKUP:
            if _contains_any(normalized, ("how many products", "count products", "number of products", "কয়টি পণ্য", "কত পণ্য")):
                metric_key = "listed_product_count" if "listed" in normalized else "product_count"
                add("run_seller_metric_query", "allowlisted product count metric requested", _metric_args(metric_key, product_id, date_range, category, marketplace))
                add("count_products", "product count lookup", _product_filter_args(normalized, category, marketplace))
            if _contains_any(normalized, ("missing cost", "without cost", "cost missing", "খরচ নেই", "কস্ট নেই")):
                add("run_seller_metric_query", "allowlisted missing cost metric requested", _metric_args("products_missing_cost_count", product_id, date_range, category, marketplace))
                add("list_products", "products missing cost lookup", _product_filter_args(normalized, category, marketplace) | {"missing_cost": True, "limit": 10, "offset": 0, "sort_by": "created_at_desc"})
                add("get_products_missing_setup", "pricing setup completeness lookup", _setup_args("COST", category, marketplace))
            if _contains_any(normalized, ("show", "list", "which products", "all ", "দেখাও", "তালিকা")):
                add("list_products", "product list lookup", _product_filter_args(normalized, category, marketplace) | {"limit": 10, "offset": 0, "sort_by": "created_at_desc"})
            if product_id:
                add("get_product_profile", "resolved product profile lookup", {"product_id": str(product_id)})

        if question_type in {CopilotQuestionType.ANALYTIC, CopilotQuestionType.DIAGNOSTIC}:
            if "top_products_by_revenue" in metrics or _contains_any(normalized, ("most profit", "top products", "best selling", "highest revenue")):
                add("get_top_products_by_revenue", "top product metric requested", _dated_args(None, date_range, category, marketplace) | {"limit": 10})
            if BusinessDomainKey.PROFIT_MARGIN in domains or _contains_any(normalized, ("profit", "margin")):
                add("run_seller_metric_query", "allowlisted profit metric requested", _metric_args("estimated_profit", product_id, date_range, category, marketplace))
                add("get_profit_summary", "profit or margin metric requested", _dated_args(product_id, date_range, category, marketplace))
            if question_type == CopilotQuestionType.DIAGNOSTIC:
                add("explain_revenue_change_deterministic", "deterministic diagnosis requested", _dated_args(product_id, date_range, category, marketplace) | {"compare_to_previous_period": True})
                add("get_competitor_threats", "diagnosis checks competitor pressure", _optional_dated_args(product_id, date_range) | {"limit": 10})
                add("get_inventory_risks", "diagnosis checks inventory risk", _limit_args(product_id))

        if BusinessDomainKey.COMPETITOR in domains:
            add("get_competitor_threats", "competitor domain requested", _optional_dated_args(product_id, date_range) | {"limit": 10})
            if _contains_any(normalized, ("snapshot", "snapshots", "observed", "history", "price history")):
                add(
                    "get_competitor_snapshots",
                    "competitor source history requested",
                    _source_args(product_id, date_range, category, marketplace) | ({"competitor_id": str(competitor_id)} if competitor_id else {}),
                    required=False,
                )
            if _contains_any(normalized, ("rank", "ranking", "position")):
                add(
                    "get_competitor_rankings",
                    "competitor ranking history requested",
                    _source_args(product_id, date_range, category, marketplace) | ({"competitor_id": str(competitor_id)} if competitor_id else {}),
                    required=False,
                )
            if _contains_any(normalized, ("opportunity", "opportunities")):
                add(
                    "get_market_opportunities",
                    "market opportunity records requested",
                    _source_args(product_id, date_range, category, marketplace) | ({"competitor_id": str(competitor_id)} if competitor_id else {}),
                    required=False,
                )
        if BusinessDomainKey.INVENTORY in domains:
            add("get_inventory_risks", "inventory domain requested", _limit_args(product_id))
            if _contains_any(normalized, ("history", "snapshot", "snapshots")):
                add("get_inventory_history", "inventory source history requested", _source_args(product_id, date_range, category, marketplace), required=False)
            if _contains_any(normalized, ("velocity", "sales velocity", "sell through")):
                add("get_sales_velocity", "sales velocity records requested", _source_args(product_id, date_range, category, marketplace), required=False)
            if _contains_any(normalized, ("low stock", "reorder", "restock")):
                add("get_products_low_stock", "low-stock source records requested", _source_args(product_id, date_range, category, marketplace), required=False)
            if question_type in {CopilotQuestionType.RECOMMENDATION, CopilotQuestionType.ACTION_REQUEST}:
                add("get_restock_recommendations", "restock recommendation requested", _limit_args(product_id) | ({"category": category} if category else {}))
        if BusinessDomainKey.PRICING in domains or _contains_any(normalized, ("unsafe to discount", "safe to discount", "discount safety")):
            add("get_products_missing_pricing_setup", "pricing setup safety requested", _source_args(product_id, date_range, category, marketplace))
            add("get_margin_safety", "margin safety requested", _source_args(product_id, date_range, category, marketplace))
            add("get_pricing_recommendations", "pricing recommendation requested", _limit_args(product_id))
            if _contains_any(normalized, ("price history", "price change", "price changes", "changed price")):
                add("get_product_price_changes", "seller price history requested", _price_history_args(product_id, date_range, marketplace), required=False)
        if BusinessDomainKey.PROMOTION in domains:
            add("get_promotion_summary", "promotion domain requested", _source_args(product_id, date_range, category, marketplace))
            if _contains_any(normalized, ("result", "outcome", "roi", "performance")):
                add("get_promotion_results", "promotion outcomes requested", _promotion_args(product_id, date_range, marketplace), required=False)
                add("compare_promotion_performance", "promotion comparison requested", _promotion_args(product_id, date_range, marketplace), required=False)
            add("get_promotion_recommendations", "promotion recommendation requested", _limit_args(product_id) | ({"category": category} if category else {}))
            add("get_pricing_recommendations", "promotion safety requires pricing evidence", _limit_args(product_id))
        if BusinessDomainKey.DEAD_STOCK in domains:
            add("get_dead_stock_summary", "dead stock summary requested", _source_args(product_id, date_range, category, marketplace))
            add("get_dead_stock_recovery", "dead stock recommendation requested", _limit_args(product_id))
            if _contains_any(normalized, ("capital", "recovery", "locked")):
                add("get_capital_recovery_summary", "capital recovery records requested", _source_args(product_id, date_range, category, marketplace), required=False)
        if BusinessDomainKey.SEO_VISIBILITY in domains:
            add("get_visibility_summary", "visibility domain requested", _source_args(product_id, date_range, category, marketplace))
            if _contains_any(normalized, ("history", "impression", "click", "ctr", "rank")):
                add("get_visibility_history", "visibility history requested", _source_args(product_id, date_range, category, marketplace), required=False)
            add("get_seo_opportunities", "SEO opportunity requested", _limit_args(product_id), required=False)
        if BusinessDomainKey.ALERTS in domains or BusinessDomainKey.RECOMMENDATIONS in domains:
            add("get_alert_recommendation_summary", "alerts and recommendations requested", _source_args(product_id, date_range, category, marketplace))
            if BusinessDomainKey.ALERTS in domains and _contains_any(normalized, ("alert", "alerts", "warning", "unresolved")):
                add("get_unresolved_alerts", "unresolved alert records requested", _source_args(product_id, date_range, category, marketplace), required=False)
        if question_type == CopilotQuestionType.GENERAL_BUSINESS:
            add("get_business_overview", "broad business summary requested", _optional_dated_args(None, date_range) | _category_marketplace(category, marketplace))
            add("get_revenue_summary", "broad summary includes revenue trend", _dated_args(product_id, date_range, category, marketplace) | {"compare_to_previous_period": True})
            add("get_inventory_summary", "broad summary includes inventory health", _source_args(product_id, date_range, category, marketplace))
            add("get_inventory_risks", "broad summary includes risk domain", _limit_args(product_id))
            add("get_competitor_summary", "broad summary includes competitor health", _source_args(product_id, date_range, category, marketplace))
            add("get_competitor_threats", "broad summary includes competitor domain", _optional_dated_args(product_id, date_range) | {"limit": 10})
            add("get_pricing_summary", "broad summary includes pricing health", _source_args(product_id, date_range, category, marketplace))
            add("get_pricing_recommendations", "broad summary includes pricing domain", _limit_args(product_id))
            add("get_dead_stock_summary", "broad summary includes dead-stock risk", _source_args(product_id, date_range, category, marketplace))
            add("get_alert_recommendation_summary", "broad summary includes alert and recommendation state", _source_args(product_id, date_range, category, marketplace))
            add("get_today_actions", "broad summary includes action candidates", _limit_args(product_id))

        if not steps and domains:
            for tool_name in _registry_tools_for_domains(tool_registry=None, available_tools=available_tools, domains=domains):
                add(tool_name, "registered tool catalog match", _args_for_tool(tool_name, question, product_id, date_range, category, marketplace, memory_source_types, top_k), required=False)
            for domain in domains:
                for tool_name in self._business_catalog.get_supported_tools(domain):
                    add(tool_name, f"business data catalog match: {domain.value}", _args_for_tool(tool_name, question, product_id, date_range, category, marketplace, memory_source_types, top_k), required=False)

        if include_memory and not classification_hint.suggested_tools and (question_type in {CopilotQuestionType.MEMORY_SEARCH, CopilotQuestionType.DIAGNOSTIC, CopilotQuestionType.GENERAL_BUSINESS, CopilotQuestionType.UNKNOWN} or not steps):
            add("retrieve_business_memory", "memory fallback for business context", _memory_args(question, product_id, date_range, memory_source_types, top_k), required=False)

        if not steps and "retrieve_business_memory" in available_tools and include_memory:
            add("retrieve_business_memory", "unknown business question fallback", _memory_args(question, product_id, date_range, memory_source_types, top_k), required=False)
        return steps

    def _validate_and_bound(self, steps: list[PlannedToolCall], *, tool_registry: Any, max_tools: int, safety_flags: list[str]) -> list[PlannedToolCall]:
        valid: list[PlannedToolCall] = []
        for step in steps:
            if len(valid) >= max(1, max_tools):
                safety_flags.append("TOOL_LIMIT_ENFORCED")
                break
            validate = getattr(tool_registry, "validate_arguments", None)
            if validate is not None:
                is_valid, parsed, error = validate(step.tool_name, step.args)
                if not is_valid:
                    safety_flags.append(f"INVALID_TOOL_ARGS:{step.tool_name}:{error}")
                    continue
                valid.append(PlannedToolCall(step.tool_name, parsed or step.args, step.reason, step.required))
            else:
                valid.append(step)
        return valid


def _question_type(normalized: str, classification: CopilotIntentResult) -> CopilotQuestionType:
    if classification.requires_action_proposal:
        return CopilotQuestionType.ACTION_REQUEST
    if classification.intent == CopilotIntent.BUSINESS_MEMORY_SEARCH or _contains_any(normalized, ("last time", "before", "previous", "worked before", "আগে", "গতবার")):
        return CopilotQuestionType.MEMORY_SEARCH
    if _is_general_business_question(normalized):
        return CopilotQuestionType.GENERAL_BUSINESS
    if _contains_any(normalized, ("why", "down", "stop selling", "risk high", "কমেছে", "কেন")):
        return CopilotQuestionType.DIAGNOSTIC
    if _contains_any(normalized, ("revenue", "profit", "margin", "growing", "trend", "generated most", "বিক্রি", "রেভিনিউ")):
        return CopilotQuestionType.ANALYTIC
    if _contains_any(normalized, ("should i", "what should", "recommend", "restock", "promotion", "unsafe to discount", "কী করব", "রিস্টক")):
        return CopilotQuestionType.RECOMMENDATION
    if _contains_any(normalized, ("how many", "which products", "show me", "list", "missing", "listed", "কত", "দেখাও")):
        return CopilotQuestionType.LOOKUP
    if classification.intent != CopilotIntent.UNKNOWN:
        return CopilotQuestionType.RECOMMENDATION
    return CopilotQuestionType.UNKNOWN


def _execution_question_type(
    *,
    normalized: str,
    classification_hint: CopilotIntentResult,
    domains: list[BusinessDomainKey],
    metrics: list[str],
    inherited_context_allowed: bool,
) -> CopilotExecutionQuestionType:
    if classification_hint.requires_action_proposal:
        return CopilotExecutionQuestionType.ACTION_PROPOSAL
    if _is_general_business_question(normalized):
        return CopilotExecutionQuestionType.GENERAL_BUSINESS
    if classification_hint.intent == CopilotIntent.BUSINESS_MEMORY_SEARCH:
        return CopilotExecutionQuestionType.MEMORY
    if _contains_any(normalized, ("why", "fall", "fell", "drop", "down", "problem", "involved", "caused", "কারণ", "কেন", "কমেছে")):
        return CopilotExecutionQuestionType.DIAGNOSTIC
    if _contains_any(normalized, ("compare", "versus", "vs", "than", "change since", "what changed", "compared")):
        return CopilotExecutionQuestionType.COMPARISON
    if _contains_any(normalized, ("trend", "over time", "by day", "by week", "by month", "growth")) or "revenue_trend" in metrics:
        return CopilotExecutionQuestionType.TREND
    if _contains_any(normalized, ("top", "highest", "most", "best", "ranking", "rank")) or "top_products_by_revenue" in metrics:
        return CopilotExecutionQuestionType.RANKING
    if _contains_any(normalized, ("how many", "count", "number of", "কত", "কয়টি")):
        return CopilotExecutionQuestionType.COUNT
    if _contains_any(normalized, ("list", "show", "which products", "দেখাও", "তালিকা")):
        return CopilotExecutionQuestionType.LIST
    if _contains_any(normalized, ("should", "recommend", "focus", "attention", "restock", "reorder", "what to do", "কী করব")):
        return CopilotExecutionQuestionType.RECOMMENDATION
    if metrics:
        return CopilotExecutionQuestionType.METRIC
    if inherited_context_allowed and domains:
        return CopilotExecutionQuestionType.METRIC
    if domains == [BusinessDomainKey.RAG_MEMORY]:
        return CopilotExecutionQuestionType.MEMORY
    return CopilotExecutionQuestionType.LOOKUP


def _legacy_question_type(execution_type: CopilotExecutionQuestionType) -> CopilotQuestionType:
    if execution_type == CopilotExecutionQuestionType.ACTION_PROPOSAL:
        return CopilotQuestionType.ACTION_REQUEST
    if execution_type == CopilotExecutionQuestionType.MEMORY:
        return CopilotQuestionType.MEMORY_SEARCH
    if execution_type in {CopilotExecutionQuestionType.COUNT, CopilotExecutionQuestionType.LIST, CopilotExecutionQuestionType.LOOKUP}:
        return CopilotQuestionType.LOOKUP
    if execution_type in {CopilotExecutionQuestionType.METRIC, CopilotExecutionQuestionType.RANKING, CopilotExecutionQuestionType.COMPARISON, CopilotExecutionQuestionType.TREND}:
        return CopilotQuestionType.ANALYTIC
    if execution_type == CopilotExecutionQuestionType.DIAGNOSTIC:
        return CopilotQuestionType.DIAGNOSTIC
    if execution_type == CopilotExecutionQuestionType.RECOMMENDATION:
        return CopilotQuestionType.RECOMMENDATION
    if execution_type == CopilotExecutionQuestionType.GENERAL_BUSINESS:
        return CopilotQuestionType.GENERAL_BUSINESS
    return CopilotQuestionType.UNKNOWN


def _is_general_business_question(normalized: str) -> bool:
    if _contains_any(normalized, GENERAL_BUSINESS_ALIASES):
        return True
    tokens = set(_meaningful_tokens(normalized))
    business_terms = {"business", "store", "shop", "overall", "today", "problems", "attention", "focus", "changed"}
    return bool(tokens & business_terms) and _contains_any(normalized, ("doing", "health", "problems", "attention", "focus", "changed", "today"))


def _execution_plan_from_candidates(
    *,
    question_type: CopilotExecutionQuestionType,
    entities: EntityResolutionResult,
    date_range: ParsedDateRange | None,
    domains: list[BusinessDomainKey],
    metrics: list[str],
    tool_steps: list[PlannedToolCall],
    include_memory: bool,
    memory_source_types: list[RagMemorySourceType] | None,
    top_k: int,
    needs_clarification: bool,
    clarification_question: str | None,
    safety_flags: list[str],
) -> CopilotExecutionPlan:
    metric_queries = []
    for metric in metrics:
        filters: dict[str, Any] = {}
        product_id = _resolved_product_id(entities)
        if product_id:
            filters["product_id"] = str(product_id)
        if entities.categories:
            filters["category"] = entities.categories[0]
        if entities.marketplaces:
            filters["marketplace"] = entities.marketplaces[0]
        if date_range:
            filters["from_date"] = date_range.from_date
            filters["to_date"] = date_range.to_date
        metric_queries.append(MetricQueryPlan(metric_key=metric, filters=filters, group_by=_group_by_for_metric(metric, question_type)))
    return CopilotExecutionPlan(
        question_type=question_type,
        resolved_entities=ResolvedEntitiesPlan(
            product_ids=[str(item.product_id) for item in entities.products if item.product_id],
            competitor_ids=list(entities.competitor_ids),
            categories=list(entities.categories),
            marketplaces=list(entities.marketplaces),
        ),
        date_range=DateRangePlan(from_date=date_range.from_date if date_range else None, to_date=date_range.to_date if date_range else None),
        domains=domains,
        metric_queries=metric_queries,
        tool_calls=[ToolCallPlan(tool_name=step.tool_name, args=step.args, reason=step.reason, required=step.required) for step in tool_steps],
        memory_query=MemoryQueryPlan(
            enabled=include_memory and any(step.tool_name == "retrieve_business_memory" for step in tool_steps),
            source_types=list(memory_source_types or []),
            top_k=max(1, min(top_k, 20)),
        ),
        requires_clarification=needs_clarification,
        clarification_question=clarification_question,
        safety_flags=list(safety_flags),
    )


def _group_by_for_metric(metric: str, question_type: CopilotExecutionQuestionType) -> list[str]:
    if question_type == CopilotExecutionQuestionType.RANKING and metric in {"top_products_by_revenue", "gross_revenue", "units_sold"}:
        return ["product_id"]
    if question_type == CopilotExecutionQuestionType.TREND and metric == "revenue_trend":
        return ["day"]
    return []


def _coerce_planning_context(
    planning_context: CopilotPlanningContext | dict[str, Any] | None,
    conversation_history: list[dict[str, Any]] | None,
) -> CopilotPlanningContext:
    if isinstance(planning_context, CopilotPlanningContext):
        return planning_context
    if isinstance(planning_context, dict):
        return CopilotPlanningContext(
            recent_messages=list(planning_context.get("recent_messages") or []),
            active_products=_safe_products(planning_context.get("active_products")),
            active_competitors=_dedupe_strings(_string_list(planning_context.get("active_competitors"))),
            active_competitor_ids=_dedupe_strings(_string_list(planning_context.get("active_competitor_ids"))),
            active_categories=_dedupe_strings(_string_list(planning_context.get("active_categories"))),
            active_marketplaces=_dedupe_strings(_string_list(planning_context.get("active_marketplaces"))),
            active_date_range=planning_context.get("active_date_range") if isinstance(planning_context.get("active_date_range"), dict) else None,
            active_metrics=_dedupe_strings(_string_list(planning_context.get("active_metrics"))),
            active_domains=_dedupe_strings(_string_list(planning_context.get("active_domains"))),
            pending_clarification=planning_context.get("pending_clarification") if isinstance(planning_context.get("pending_clarification"), str) else None,
            last_successful_plan=planning_context.get("last_successful_plan") if isinstance(planning_context.get("last_successful_plan"), dict) else None,
        )
    return build_planning_context_from_messages(conversation_history)


def _should_use_context(normalized: str, context: CopilotPlanningContext) -> bool:
    if not (
        context.active_products
        or context.active_competitors
        or context.active_categories
        or context.active_marketplaces
        or context.active_domains
        or context.active_metrics
        or context.active_date_range
    ):
        return False
    tokens = _meaningful_tokens(normalized)
    return _contains_any(normalized, CONTEXT_FOLLOWUP_CUES) or len(tokens) <= 4


def _question_type_from_context(
    question_type: CopilotQuestionType,
    context: CopilotPlanningContext,
    inherited_context_allowed: bool,
) -> CopilotQuestionType:
    if not inherited_context_allowed:
        return question_type
    last_type = None
    if isinstance(context.last_successful_plan, dict):
        last_type = context.last_successful_plan.get("question_type")
    if question_type == CopilotQuestionType.UNKNOWN and isinstance(last_type, str):
        try:
            return CopilotQuestionType(last_type)
        except ValueError:
            pass
    if question_type == CopilotQuestionType.UNKNOWN and (context.active_metrics or context.active_domains):
        return CopilotQuestionType.ANALYTIC
    return question_type


def _context_date_range(context: CopilotPlanningContext) -> ParsedDateRange | None:
    value = context.active_date_range
    if not isinstance(value, dict):
        return None
    try:
        from_date = date.fromisoformat(str(value.get("from_date")))
        to_date = date.fromisoformat(str(value.get("to_date")))
    except (TypeError, ValueError):
        return None
    if from_date > to_date or value.get("defaulted"):
        return None
    return ParsedDateRange(from_date, to_date, str(value.get("source_text") or "conversation context"))


def _merge_context_entities(
    entities: EntityResolutionResult,
    context: CopilotPlanningContext,
) -> EntityResolutionResult:
    explicit = entities.explicit_entity_types
    products = list(entities.products)
    if not products and "product" not in explicit:
        products = [_product_from_context(item) for item in context.active_products]
        products = [item for item in products if item is not None]
    categories = entities.categories if "category" in explicit else entities.categories or context.active_categories
    marketplaces = entities.marketplaces if "marketplace" in explicit else entities.marketplaces or context.active_marketplaces
    competitors = entities.competitors if "competitor" in explicit else entities.competitors or context.active_competitors
    return EntityResolutionResult(
        products=products,
        categories=list(categories),
        marketplaces=list(marketplaces),
        competitors=list(competitors),
        clarification_question=entities.clarification_question,
        product_resolution=entities.product_resolution,
        category_resolution=entities.category_resolution,
        marketplace_resolution=entities.marketplace_resolution,
        competitor_resolution=entities.competitor_resolution,
        missing_data=list(entities.missing_data),
        explicit_entity_types=entities.explicit_entity_types,
        inherited_competitor_ids=tuple(entities.competitor_ids if "competitor" in explicit else entities.competitor_ids or context.active_competitor_ids),
    )


def _product_from_context(value: dict[str, Any]) -> Any:
    raw_id = value.get("product_id") or value.get("id")
    if not raw_id:
        return None
    try:
        product_id = UUID(str(raw_id))
    except (TypeError, ValueError):
        return None
    title = str(value.get("title") or value.get("text") or product_id)
    return ResolvedProductEntity(
        text=title,
        product_id=product_id,
        title=title,
        matched_products=[{"id": str(product_id), "title": title}],
        confidence="HIGH",
    )


def _context_domains(context: CopilotPlanningContext) -> list[BusinessDomainKey]:
    domains: list[BusinessDomainKey] = []
    for item in context.active_domains:
        try:
            domains.append(BusinessDomainKey(str(item)))
        except ValueError:
            continue
    return domains


def _matched_domains(normalized: str, catalog: BusinessDataCatalogService, question_type: CopilotQuestionType) -> list[BusinessDomainKey]:
    domains: list[BusinessDomainKey] = []
    tokens = _catalog_tokens(normalized)
    if question_type == CopilotQuestionType.GENERAL_BUSINESS or _is_general_business_question(normalized):
        domains.extend(
            [
                BusinessDomainKey.PRODUCT_CATALOG,
                BusinessDomainKey.SALES_REVENUE,
                BusinessDomainKey.PROFIT_MARGIN,
                BusinessDomainKey.INVENTORY,
                BusinessDomainKey.COMPETITOR,
                BusinessDomainKey.PRICING,
                BusinessDomainKey.DEAD_STOCK,
                BusinessDomainKey.ALERTS,
                BusinessDomainKey.RECOMMENDATIONS,
            ]
        )
    for domain_key, aliases in DOMAIN_ALIASES.items():
        if _contains_any(normalized, aliases):
            domains.append(domain_key)
    for domain in catalog.list_domains():
        text = f"{domain.domain_key.value} {domain.description} {' '.join(domain.supported_metrics)} {' '.join(domain.supported_tools)}".casefold().replace("_", " ")
        if any(token in text for token in tokens):
            domains.append(domain.domain_key)
    if _contains_any(normalized, ("competitor", "প্রতিযোগী", "কম্পিটিটর")):
        domains.append(BusinessDomainKey.COMPETITOR)
    if _contains_any(normalized, ("revenue", "sales", "বিক্রি", "রেভিনিউ")):
        domains.append(BusinessDomainKey.SALES_REVENUE)
    if _contains_any(normalized, ("product", "products", "catalog", "listed", "পণ্য")):
        domains.append(BusinessDomainKey.PRODUCT_CATALOG)
    if _contains_any(normalized, ("price", "pricing", "discount", "margin", "দাম", "ডিসকাউন্ট")):
        domains.extend([BusinessDomainKey.PRICING, BusinessDomainKey.PROFIT_MARGIN])
    return _dedupe_domains(domains)


def _matched_metrics(normalized: str, catalog: MetricCatalogService, question_type: CopilotQuestionType) -> list[str]:
    metrics = []
    tokens = _catalog_tokens(normalized)
    for metric_key, aliases in METRIC_ALIASES.items():
        if _contains_any(normalized, aliases):
            metrics.append(metric_key)
    for metric in catalog.list_metrics():
        if not metric.is_selectable_for_execution:
            continue
        text = f"{metric.metric_key} {metric.description} {metric.domain.value}".casefold().replace("_", " ")
        if any(token in text for token in tokens):
            metrics.append(metric.metric_key)
    if question_type == CopilotQuestionType.GENERAL_BUSINESS or _is_general_business_question(normalized):
        metrics.extend(
            [
                "product_count",
                "gross_revenue",
                "revenue_trend",
                "estimated_profit",
                "stockout_risk_count",
                "competitor_undercut_count",
                "dead_stock_count",
                "pending_recommendation_count",
                "unresolved_alert_count",
            ]
        )
    if _contains_any(normalized, ("how many products", "product count", "number of products")):
        metrics.append("product_count")
    if _contains_any(normalized, ("revenue", "sales", "রেভিনিউ", "বিক্রি")):
        metrics.extend(["gross_revenue", "revenue_trend"])
    if question_type == CopilotQuestionType.DIAGNOSTIC and _contains_any(normalized, ("down", "কমেছে")):
        metrics.extend(["revenue_change", "percentage_revenue_change"])
    selectable = catalog.selectable_metric_keys()
    return [metric for metric in dict.fromkeys(metrics) if metric in selectable]


def _available_tool_names(tool_registry: Any, suggested_tools: list[str]) -> set[str]:
    list_tools = getattr(tool_registry, "list_tools", None)
    if list_tools is None:
        return set(suggested_tools) | _KNOWN_TOOL_FALLBACK
    return {tool.name for tool in list_tools()}


def _resolved_product_id(entities: EntityResolutionResult) -> UUID | None:
    resolved = [item.product_id for item in entities.products if item.product_id]
    return resolved[0] if len(resolved) == 1 and not entities.clarification_question else None


def _resolved_competitor_id(entities: EntityResolutionResult) -> UUID | None:
    if entities.clarification_question or len(entities.competitor_ids) != 1:
        return None
    try:
        return UUID(entities.competitor_ids[0])
    except (TypeError, ValueError):
        return None


def _date_range_from_hint(classification: CopilotIntentResult) -> ParsedDateRange | None:
    if not classification.date_range:
        return None
    return ParsedDateRange(classification.date_range.from_date, classification.date_range.to_date, classification.date_range.source_text)


def _args_for_tool(tool_name: str, question: str, product_id: UUID | None, date_range: ParsedDateRange | None, category: str | None, marketplace: str | None, memory_source_types: list[RagMemorySourceType] | None, top_k: int) -> dict[str, Any]:
    if tool_name == "run_seller_metric_query":
        return _metric_args("product_count", product_id, date_range, category, marketplace)
    if tool_name == "retrieve_business_memory":
        return _memory_args(question, product_id, date_range, memory_source_types, top_k)
    if tool_name in {"get_revenue_summary", "get_sales_trends", "get_profit_summary", "explain_revenue_change_deterministic"}:
        payload = _dated_args(product_id, date_range, category, marketplace)
        if tool_name == "get_sales_trends":
            payload["granularity"] = "daily"
        if tool_name in {"get_revenue_summary", "explain_revenue_change_deterministic"}:
            payload["compare_to_previous_period"] = True
        return payload
    if tool_name == "explain_revenue_drop":
        return _dated_args(product_id, date_range, None, None) | {"compare_to_previous_period": True}
    if tool_name == "get_business_overview":
        return _optional_dated_args(None, date_range) | _category_marketplace(category, marketplace)
    if tool_name == "count_products":
        return _product_filter_args(_normalize(question), category, marketplace)
    if tool_name == "list_products":
        return _product_filter_args(_normalize(question), category, marketplace) | {"limit": 10, "offset": 0, "sort_by": "created_at_desc"}
    if tool_name == "get_products_missing_setup":
        return _setup_args(None, category, marketplace)
    if tool_name == "get_product_profile" and product_id:
        return {"product_id": str(product_id)}
    if tool_name == "search_products":
        return {"query": _search_query_from_question(question), "limit": 10} | _category_marketplace(category, marketplace)
    if tool_name == "get_top_products_by_revenue":
        return _dated_args(None, date_range, category, marketplace) | {"limit": 10}
    if tool_name == "get_products_with_no_sales":
        payload = {"limit": 10, "offset": 0} | _category_marketplace(category, marketplace)
        if date_range and not date_range.defaulted:
            payload["since_date"] = date_range.from_date.isoformat()
        return payload
    if tool_name == "get_competitor_threats":
        return _optional_dated_args(product_id, date_range) | {"limit": 10}
    if tool_name == "simulate_price_change":
        payload = {"forecast_horizon_days": 30}
        if product_id:
            payload["product_id"] = str(product_id)
        price_delta = _extract_percent_delta(question)
        if price_delta is not None:
            payload["candidate_discount_rate"] = str(price_delta)
        return payload
    if tool_name in {"get_restock_recommendations", "get_promotion_recommendations"}:
        return _limit_args(product_id) | ({"category": category} if category else {})
    if tool_name in {"get_inventory_risks", "get_pricing_recommendations", "get_dead_stock_recovery", "get_seo_opportunities", "get_today_actions"}:
        return _limit_args(product_id)
    if tool_name in {"get_price_history", "get_product_price_changes", "get_products_with_recent_price_changes"}:
        return _price_history_args(product_id, date_range, marketplace)
    if tool_name in {"get_promotion_plans", "get_promotion_results", "compare_promotion_performance"}:
        return _promotion_args(product_id, date_range, marketplace)
    return _source_args(product_id, date_range, category, marketplace)


def _dated_args(product_id: UUID | None, date_range: ParsedDateRange | None, category: str | None, marketplace: str | None) -> dict[str, Any]:
    selected = date_range or default_period(datetime.now(ZoneInfo("Asia/Dhaka")).date())
    payload = {"from_date": selected.from_date.isoformat(), "to_date": selected.to_date.isoformat()} | _category_marketplace(category, marketplace)
    if product_id:
        payload["product_id"] = str(product_id)
    return payload


def _optional_dated_args(product_id: UUID | None, date_range: ParsedDateRange | None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if product_id:
        payload["product_id"] = str(product_id)
    if date_range and not date_range.defaulted:
        payload["from_date"] = date_range.from_date.isoformat()
        payload["to_date"] = date_range.to_date.isoformat()
    return payload


def _metric_args(metric_key: str, product_id: UUID | None, date_range: ParsedDateRange | None, category: str | None, marketplace: str | None) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    if product_id:
        filters["product_id"] = str(product_id)
    if category:
        filters["category"] = category
    if marketplace:
        filters["marketplace"] = marketplace
    payload: dict[str, Any] = {"metric_key": metric_key, "filters": filters, "limit": 25, "offset": 0}
    if date_range:
        payload["from_date"] = date_range.from_date.isoformat()
        payload["to_date"] = date_range.to_date.isoformat()
    return payload


def _memory_args(question: str, product_id: UUID | None, date_range: ParsedDateRange | None, memory_source_types: list[RagMemorySourceType] | None, top_k: int) -> dict[str, Any]:
    payload: dict[str, Any] = {"question": question, "top_k": max(1, min(top_k, 20))}
    if product_id:
        payload["product_id"] = str(product_id)
    if memory_source_types:
        payload["source_types"] = [source_type.value for source_type in memory_source_types]
    if date_range and not date_range.defaulted:
        payload["from_date"] = date_range.from_date.isoformat()
        payload["to_date"] = date_range.to_date.isoformat()
    return payload


def _limit_args(product_id: UUID | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"limit": 10}
    if product_id:
        payload["product_id"] = str(product_id)
    return payload


def _source_args(product_id: UUID | None, date_range: ParsedDateRange | None, category: str | None, marketplace: str | None) -> dict[str, Any]:
    return _optional_dated_args(product_id, date_range) | _category_marketplace(category, marketplace) | {"limit": 10, "offset": 0}


def _price_history_args(product_id: UUID | None, date_range: ParsedDateRange | None, marketplace: str | None) -> dict[str, Any]:
    payload = _optional_dated_args(product_id, date_range) | {"limit": 10, "offset": 0}
    if marketplace:
        payload["marketplace"] = marketplace
    return payload


def _promotion_args(product_id: UUID | None, date_range: ParsedDateRange | None, marketplace: str | None) -> dict[str, Any]:
    payload = _optional_dated_args(product_id, date_range) | {"limit": 10, "offset": 0}
    if marketplace:
        payload["marketplace"] = marketplace
    return payload


def _setup_args(setup_type: str | None, category: str | None, marketplace: str | None) -> dict[str, Any]:
    payload = {"limit": 10, "offset": 0} | _category_marketplace(category, marketplace)
    if setup_type:
        payload["setup_type"] = setup_type
    return payload


def _product_filter_args(normalized: str, category: str | None, marketplace: str | None) -> dict[str, Any]:
    payload = _category_marketplace(category, marketplace)
    if _contains_any(normalized, ("listed", "active")):
        payload["status"] = "listed"
    if _contains_any(normalized, ("missing cost", "without cost", "cost missing")):
        payload["missing_cost"] = True
    return payload


def _category_marketplace(category: str | None, marketplace: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if category:
        payload["category"] = category
    if marketplace:
        payload["marketplace"] = marketplace
    return payload


def _source_types_for_domains(domains: list[BusinessDomainKey], catalog: BusinessDataCatalogService) -> list[str]:
    values: list[str] = []
    for domain in domains:
        values.extend(source_type.value for source_type in catalog.get_domain(domain).rag_source_types)
    return list(dict.fromkeys(values))


def _registry_tools_for_domains(*, tool_registry: Any, available_tools: set[str], domains: list[BusinessDomainKey]) -> list[str]:
    del tool_registry
    tools: list[str] = []
    for domain in domains:
        tools.extend(tool for tool in DOMAIN_TOOL_PRIORITIES.get(domain, ()) if tool in available_tools)
    return list(dict.fromkeys(tools))


def _search_query_from_question(question: str) -> str:
    normalized = " ".join((question or "").split())
    for prefix in ("search product", "find product", "match product"):
        if normalized.casefold().startswith(prefix):
            candidate = normalized[len(prefix):].strip(" :?-")
            if candidate:
                return candidate[:200]
    return normalized[:200] or "product"


def _extract_percent_delta(question: str) -> Decimal | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", question or "")
    if not match:
        return None
    return Decimal(match.group(1)) / Decimal("100")


def _meaningful_tokens(value: str) -> list[str]:
    stop = {"what", "which", "show", "tell", "with", "from", "this", "that", "have", "my", "are", "the", "and", "ones"}
    return [token for token in re.findall(r"[a-z0-9\u0980-\u09FF]+", value.casefold()) if len(token) > 2 and token not in stop]


def _catalog_tokens(value: str) -> list[str]:
    generic = {
        "product",
        "products",
        "seller",
        "business",
        "data",
        "records",
        "record",
        "history",
        "quality",
        "setup",
        "missing",
        "listed",
        "active",
        "count",
        "number",
        "many",
    }
    return [token for token in _meaningful_tokens(value) if token not in generic]


def _normalize(value: str) -> str:
    return " ".join((value or "").casefold().split())


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)


def _dedupe_domains(domains: list[BusinessDomainKey]) -> list[BusinessDomainKey]:
    return list(dict.fromkeys(domains))


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _dedupe_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


def _safe_products(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    products: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        product_id = item.get("product_id") or item.get("id")
        if not product_id:
            continue
        products.append(
            {
                "product_id": str(product_id),
                "title": str(item.get("title") or item.get("text") or product_id),
                "text": str(item.get("text") or item.get("title") or product_id),
            }
        )
    return products


def _json_safe(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


_KNOWN_TOOL_FALLBACK = {
    "get_business_overview",
    "count_products",
    "list_products",
    "search_products",
    "get_product_profile",
    "get_products_missing_setup",
    "get_revenue_summary",
    "get_sales_trends",
    "get_profit_summary",
    "explain_revenue_change_deterministic",
    "get_top_products_by_revenue",
    "get_products_with_no_sales",
    "get_today_actions",
    "get_restock_recommendations",
    "get_inventory_risks",
    "explain_revenue_drop",
    "get_competitor_threats",
    "get_pricing_recommendations",
    "simulate_price_change",
    "get_promotion_recommendations",
    "get_dead_stock_recovery",
    "get_seo_opportunities",
    "retrieve_business_memory",
    "get_products_missing_pricing_setup",
    "get_margin_safety",
}
