from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
import hashlib
import html
import re
from typing import Any
from uuid import UUID

from app.models.rag_memory import RagMemoryEmbeddingStatus, RagMemorySourceType
from app.schemas.rag_memory import RagMemoryDocumentCreate
from app.services.rag_memory_source_registry import (
    COMMON_EXCLUDED_FIELDS,
    RagSourceDefinition,
    get_rag_source_definition,
)


class RagMemoryBuildError(ValueError):
    """Raised when a source object cannot be normalized safely."""


class RagMemoryDocumentBuilder:
    def build_from_product_profile(self, product: Any) -> RagMemoryDocumentCreate:
        definition = get_rag_source_definition(RagMemorySourceType.PRODUCT_PROFILE)
        sku = _spec_value(product, "sku") or "unknown"
        title = f"Product profile for {_name(product, fallback=f'product {product.id}')}"
        content = (
            f"Product {_name(product, fallback=f'product {product.id}')} has SKU {sku}, category {_clean_text(getattr(product, 'category', None) or 'unknown')}, "
            f"selling price {_money(getattr(product, 'selling_price', None))}, cost setup {'available' if getattr(product, 'cost_price', None) is not None else 'missing'}, "
            f"inventory setup {'available' if getattr(product, 'stock_quantity', None) is not None else 'missing'}, marketplace unknown, status unknown. "
            f"Created at {_date_text(getattr(product, 'created_at', None))}. Source: products."
        )
        return self._document(
            definition=definition,
            seller_id=product.seller_id,
            product_id=product.id,
            source_id=product.id,
            title=title,
            summary=f"Product profile for {_name(product, fallback=f'product {product.id}')}.",
            content=content,
            event_time=getattr(product, "updated_at", None) or getattr(product, "created_at", None),
            metadata={"sku": sku, "category": getattr(product, "category", None), "has_cost": getattr(product, "cost_price", None) is not None},
        )

    def build_from_sales_record(self, sale: Any) -> RagMemoryDocumentCreate:
        definition = get_rag_source_definition(RagMemorySourceType.SALES_HISTORY)
        product = getattr(sale, "product", None)
        product_name = _name(product, fallback=f"product {sale.product_id}")
        quantity = int(getattr(sale, "quantity_sold", 0) or 0)
        returns = int(getattr(sale, "returned_units", 0) or 0) + int(getattr(sale, "refunded_restocked_units", 0) or 0)
        net_units = max(0, quantity - returns)
        unit_price = _transaction_price(sale, product)
        revenue = _transaction_revenue(sale)
        if revenue is None and unit_price is not None:
            revenue = unit_price * Decimal(net_units)
        price_source = _enum_value(getattr(sale, "price_source", None)) or "UNKNOWN"
        status = _enum_value(getattr(sale, "status", None))
        excluded = bool(getattr(sale, "is_test_order", False)) or status not in {"COMPLETED", "FULFILLED"}
        content = (
            f"On {_date_text(getattr(sale, 'sold_at', None))}, sales record for {product_name} had status {status}. "
            f"Gross units sold: {quantity}. Net units after returns/refunds: {net_units}. "
            f"Transaction unit price: {_money(unit_price) if unit_price is not None else 'unavailable'}. "
            f"Price source: {price_source}. "
            f"Revenue contribution: {_money(revenue) if revenue is not None else 'unavailable'}. "
            f"Excluded from exact revenue: {'yes' if excluded else 'no'}. Source: sales_records."
        )
        return self._document(
            definition=definition,
            seller_id=sale.seller_id,
            product_id=sale.product_id,
            source_id=sale.id,
            title=f"Sales record for {product_name}",
            summary=f"{product_name} sold {net_units} valid net units on {_date_text(getattr(sale, 'sold_at', None))}.",
            content=content,
            event_time=getattr(sale, "sold_at", None),
            metadata={"status": status, "net_units": net_units, "revenue": _decimal_text(revenue), "price_source": price_source, "excluded": excluded},
        )

    def build_from_sales_revenue_summary(self, summary: Mapping[str, Any] | Any) -> RagMemoryDocumentCreate:
        data = _mapping_from_source(summary)
        definition = get_rag_source_definition(RagMemorySourceType.SALES_REVENUE_SUMMARY)
        period = f"{_date_text(data.get('from_date'))} to {_date_text(data.get('to_date'))}"
        content = (
            f"Sales revenue summary for {period}: revenue {_money(data.get('revenue'))}, units sold {_clean_text(data.get('units_sold'))}, "
            f"order count {_clean_text(data.get('order_count'))}, trend {_clean_text(data.get('trend') or 'unknown')}. "
            f"Top products: {_clean_text(data.get('top_products') or 'unavailable')}. "
            f"Sales completeness: {_clean_text(data.get('completeness_status') or 'UNKNOWN')}. "
            f"Missing data notes: {_clean_text(data.get('missing_data') or 'none')}. Source: sales_records."
        )
        return self._document(
            definition=definition,
            seller_id=_required(data, "seller_id"),
            product_id=None,
            source_id=data.get("id") or f"sales-summary-{data.get('seller_id')}-{period}",
            title=f"Sales revenue summary {period}",
            summary=f"Revenue summary for {period}.",
            content=content,
            event_time=data.get("to_date") or data.get("event_time"),
            metadata={"period": period, "completeness_status": data.get("completeness_status") or "UNKNOWN"},
        )

    def build_from_inventory_lifecycle(self, source: Any) -> RagMemoryDocumentCreate:
        if hasattr(source, "quantity_available") and hasattr(source, "captured_at"):
            return self.build_from_inventory_snapshot_or_risk(source)
        definition = get_rag_source_definition(RagMemorySourceType.INVENTORY_LIFECYCLE)
        product = getattr(source, "product", None)
        product_id = getattr(source, "product_id", None)
        product_name = _name(product, fallback=f"product {product_id}")
        event_time = (
            getattr(source, "received_at", None)
            or getattr(source, "calculated_at", None)
            or getattr(source, "assessed_at", None)
            or getattr(source, "generated_at", None)
            or getattr(source, "created_at", None)
        )
        content = (
            f"Inventory lifecycle event for {product_name} on {_date_text(event_time)}. "
            f"Stock-in quantity: {_clean_text(getattr(source, 'quantity', None))}. "
            f"Inventory age: {_clean_text(getattr(source, 'weighted_average_age_days', None) or getattr(source, 'oldest_age_days', None))}. "
            f"Velocity: {_decimal_text(getattr(source, 'daily_sales_rate', None))}. "
            f"Stockout prediction: {_decimal_text(getattr(source, 'days_remaining', None))} days remaining. "
            f"Risk: {_enum_value(getattr(source, 'risk_level', None) or getattr(source, 'prediction_status', None))}. "
            f"Reorder action: {_enum_value(getattr(source, 'action', None))}. Source: {_table_name(source)}."
        )
        return self._document(
            definition=definition,
            seller_id=source.seller_id,
            product_id=product_id,
            source_id=source.id,
            title=f"Inventory lifecycle for {product_name}",
            summary=f"Inventory lifecycle event for {product_name}.",
            content=content,
            event_time=event_time,
            metadata={"source_model": type(source).__name__},
            source_table_override=_table_name(source),
        )

    def build_from_pricing_history(self, row: Any) -> RagMemoryDocumentCreate:
        definition = get_rag_source_definition(RagMemorySourceType.PRICING_HISTORY)
        product = getattr(row, "product", None)
        product_name = _name(product, fallback=f"product {row.product_id}")
        content = (
            f"On {_date_text(getattr(row, 'calculated_at', None) or getattr(row, 'generated_at', None) or getattr(row, 'effective_from', None))}, pricing history for {product_name}. "
            f"Current price: {_money(getattr(row, 'current_price', None))}. Recommended price: {_money(getattr(row, 'recommended_price', None))}. "
            f"Minimum safe price: {_money(getattr(row, 'minimum_safe_price', None))}. Margin rate: {_decimal_text(getattr(row, 'current_margin_rate', None) or getattr(row, 'margin_rate', None))}. "
            f"Fee setup: {'available' if getattr(row, 'fee_policy_id', None) or getattr(row, 'percentage_fee_rate', None) is not None else 'unknown or missing'}. "
            f"Demand/elasticity signal: {_decimal_text(getattr(row, 'demand_score', None) or getattr(row, 'elasticity', None))}. "
            f"Confidence: {_decimal_text(getattr(row, 'confidence_score', None) or getattr(row, 'confidence', None))}. Source: {row.__tablename__ if hasattr(row, '__tablename__') else type(row).__name__}."
        )
        return self._document(
            definition=definition,
            seller_id=row.seller_id,
            product_id=getattr(row, "product_id", None),
            source_id=row.id,
            title=f"Pricing history for {product_name}",
            summary=f"Pricing history for {product_name}.",
            content=content,
            event_time=getattr(row, "calculated_at", None) or getattr(row, "generated_at", None) or getattr(row, "effective_from", None),
            metadata={"source_model": type(row).__name__, "data_status": _enum_value(getattr(row, "data_status", None))},
            source_table_override=_table_name(row),
        )

    def build_from_dead_stock_history(self, row: Any) -> RagMemoryDocumentCreate:
        definition = get_rag_source_definition(RagMemorySourceType.DEAD_STOCK_HISTORY)
        product = getattr(row, "product", None)
        product_name = _name(product, fallback=f"product {row.product_id}")
        content = (
            f"Dead-stock history for {product_name} on {_date_text(getattr(row, 'assessed_at', None) or getattr(row, 'calculated_at', None) or getattr(row, 'generated_at', None))}. "
            f"Classification: {_enum_value(getattr(row, 'classification', None))}. Risk level: {_enum_value(getattr(row, 'risk_level', None))}. "
            f"Inventory age days: {_clean_text(getattr(row, 'inventory_age_days', None) or getattr(row, 'weighted_average_age_days', None))}. "
            f"Days since last sale: {_clean_text(getattr(row, 'days_since_last_sale', None))}. Locked capital: {_money(getattr(row, 'locked_capital', None))}. "
            f"Recovery action: {_enum_value(getattr(row, 'primary_action', None) or getattr(row, 'recovery_action', None))}. "
            f"Estimated recovery: {_money(getattr(row, 'gross_recovered_cash', None) or getattr(row, 'net_cash_recovered', None))}. "
            f"Confidence: {_decimal_text(getattr(row, 'confidence_score', None))}. Source: {_table_name(row)}."
        )
        return self._document(
            definition=definition,
            seller_id=row.seller_id,
            product_id=row.product_id,
            source_id=row.id,
            title=f"Dead-stock history for {product_name}",
            summary=f"Dead-stock history for {product_name}.",
            content=content,
            event_time=getattr(row, "assessed_at", None) or getattr(row, "calculated_at", None) or getattr(row, "generated_at", None),
            metadata={"source_model": type(row).__name__, "classification": _enum_value(getattr(row, "classification", None))},
            source_table_override=_table_name(row),
        )

    def build_from_visibility_metric(self, metric: Any) -> RagMemoryDocumentCreate:
        definition = get_rag_source_definition(RagMemorySourceType.SEO_VISIBILITY_HISTORY)
        product = getattr(metric, "product", None)
        product_name = _name(product, fallback=f"product {metric.product_id}")
        views = Decimal(getattr(metric, "views", 0) or 0)
        clicks = Decimal(getattr(metric, "clicks", 0) or 0)
        ctr = None if views == 0 else clicks / views
        content = (
            f"Visibility metrics for {product_name} on {_date_text(getattr(metric, 'metric_date', None))}: "
            f"impressions {getattr(metric, 'impressions', 0)}, views {getattr(metric, 'views', 0)}, clicks {getattr(metric, 'clicks', 0)}, "
            f"CTR {_decimal_text(ctr)}, search rank {_clean_text(getattr(metric, 'search_rank', None))}, listing quality {_decimal_text(getattr(metric, 'listing_quality_score', None))}. "
            f"Missing visibility records mean unavailable visibility, not low visibility. Source: product_visibility_metrics."
        )
        return self._document(
            definition=definition,
            seller_id=metric.seller_id,
            product_id=metric.product_id,
            source_id=metric.id,
            title=f"Visibility history for {product_name}",
            summary=f"Visibility history for {product_name}.",
            content=content,
            event_time=getattr(metric, "metric_date", None),
            metadata={"ctr": _decimal_text(ctr), "listing_quality_score": _decimal_text(getattr(metric, "listing_quality_score", None))},
        )

    def build_from_alert_history(self, row: Any) -> RagMemoryDocumentCreate:
        if hasattr(row, "alert_type"):
            return self.build_from_alert(row)
        definition = get_rag_source_definition(RagMemorySourceType.ALERT_HISTORY)
        product_id = getattr(row, "product_id", None)
        content = (
            f"Alert delivery event on {_date_text(getattr(row, 'sent_at', None) or getattr(row, 'created_at', None) or getattr(row, 'connected_at', None))}. "
            f"Status: {_enum_value(getattr(row, 'delivery_status', None) or getattr(row, 'status', None) or getattr(row, 'is_connected', None))}. "
            f"Product: {_clean_text(product_id)}. Source: {_table_name(row)}."
        )
        return self._document(
            definition=definition,
            seller_id=row.seller_id,
            product_id=product_id,
            source_id=row.id,
            title=f"Alert history from {_table_name(row)}",
            summary=f"Alert history from {_table_name(row)}.",
            content=content,
            event_time=getattr(row, "sent_at", None) or getattr(row, "created_at", None) or getattr(row, "connected_at", None),
            metadata={"source_model": type(row).__name__},
            source_table_override=_table_name(row),
        )

    def build_from_recommendation_history(self, row: Any) -> RagMemoryDocumentCreate:
        if type(row).__name__ == "Recommendation":
            return self.build_from_recommendation(row)
        if type(row).__name__ == "ReorderRecommendation":
            return self.build_from_reorder_recommendation(row)
        if type(row).__name__ == "DeadStockRecoveryRecommendation":
            return self.build_from_dead_stock_recovery_recommendation(row)
        return self.build_from_pricing_recommendation(row)

    def build_from_copilot_history(self, row: Any) -> RagMemoryDocumentCreate:
        definition = get_rag_source_definition(RagMemorySourceType.COPILOT_HISTORY)
        role = _enum_value(getattr(row, "role", None))
        content_text = _clean_text(getattr(row, "content", None))
        if len(content_text) > 600:
            content_text = f"{content_text[:600]}..."
        content = (
            f"Copilot {role.lower()} message on {_date_text(getattr(row, 'created_at', None))}. "
            f"Summary: {content_text}. Confidence: {_clean_text(getattr(row, 'answer_confidence', None))}. Source: copilot_messages."
        )
        return self._document(
            definition=definition,
            seller_id=row.seller_id,
            product_id=getattr(row, "product_id", None),
            source_id=row.id,
            title=f"Copilot {role.lower()} history",
            summary=f"Copilot {role.lower()} history.",
            content=content,
            event_time=getattr(row, "created_at", None),
            metadata={"role": role, "conversation_id": _optional_uuid(getattr(row, "conversation_id", None))},
        )

    def build_from_competitor_event(self, event: Any) -> RagMemoryDocumentCreate:
        definition = get_rag_source_definition(RagMemorySourceType.COMPETITOR_HISTORY)
        product = getattr(event, "product", None)
        competitor = getattr(event, "competitor", None)
        product_name = _name(product, fallback=f"product {event.product_id}")
        competitor_name = _first_present(
            competitor,
            ("competitor_title", "competitor_store", "title", "name"),
            fallback=f"competitor {event.competitor_id}",
        )
        event_type = _enum_value(getattr(event, "event_type", None))
        event_day = _date_text(getattr(event, "detected_at", None))
        old_price = _value_from_dict(getattr(event, "old_value", None), "price")
        new_price = _value_from_dict(getattr(event, "new_value", None), "price")
        seller_price = _decimal_text(getattr(product, "selling_price", None))
        title = f"Competitor {event_type.lower().replace('_', ' ')} for {product_name}"
        summary = f"{competitor_name} triggered {event_type} for {product_name} on {event_day}."
        content_parts = [
            f"On {event_day}, competitor {competitor_name} triggered {event_type} for {product_name}.",
        ]
        if old_price is not None or new_price is not None:
            content_parts.append(f"Competitor price changed from {_money(old_price)} to {_money(new_price)}.")
        if seller_price is not None:
            content_parts.append(f"Seller product price at the time: BDT {seller_price}.")
        content_parts.extend(
            [
                f"Severity: {_enum_value(getattr(event, 'severity', None))}.",
            ]
        )
        opportunity = getattr(event, "market_opportunity", None)
        if opportunity is not None:
            content_parts.append(
                f"Opportunity score: {_decimal_text(getattr(opportunity, 'opportunity_score', None))}. "
                f"Recommended action: {_enum_value(getattr(opportunity, 'recommended_action', None))}."
            )
        content_parts.append("Source: competitor_events.")
        return self._document(
            definition=definition,
            seller_id=event.seller_id,
            product_id=event.product_id,
            source_id=event.id,
            title=title,
            summary=summary,
            content=" ".join(content_parts),
            event_time=event.detected_at,
            metadata={
                "competitor_id": str(event.competitor_id),
                "scrape_run_id": str(event.scrape_run_id),
                "previous_snapshot_id": _optional_uuid(getattr(event, "previous_snapshot_id", None)),
                "current_snapshot_id": _optional_uuid(getattr(event, "current_snapshot_id", None)),
                "event_type": event_type,
                "severity": _enum_value(getattr(event, "severity", None)),
                "price_change_amount": _decimal_text(getattr(event, "price_change_amount", None)),
                "price_change_percent": _decimal_text(getattr(event, "price_change_percent", None)),
                "opportunity_id": _optional_uuid(getattr(opportunity, "id", None)),
                "opportunity_score": _decimal_text(getattr(opportunity, "opportunity_score", None)),
                "opportunity_action": _enum_value(getattr(opportunity, "recommended_action", None)) if opportunity else None,
            },
        )

    def build_from_pricing_recommendation(self, recommendation: Any) -> RagMemoryDocumentCreate:
        definition = get_rag_source_definition(RagMemorySourceType.PRICE_HISTORY)
        product = getattr(recommendation, "product", None)
        product_name = _name(product, fallback=f"product {recommendation.product_id}")
        action = _enum_value(getattr(recommendation, "action", None))
        status = _enum_value(getattr(recommendation, "recommendation_status", None))
        event_time = getattr(recommendation, "generated_at", None) or getattr(recommendation, "created_at", None)
        title = f"Pricing recommendation {action} for {product_name}"
        summary = f"Pricing recommendation {action} for {product_name} with status {status}."
        evidence = getattr(recommendation, "evidence", None) or {}
        target = evidence.get("recommended_target_price", getattr(recommendation, "recommended_price", None))
        content = (
            f"On {_date_text(event_time)}, pricing recommendation for {product_name} selected action {action}. "
            f"Current price: {_money(getattr(recommendation, 'current_price', None))}. "
            f"Recommended price: {_money(target)}. "
            f"Minimum safe price: {_money(getattr(recommendation, 'minimum_safe_price', None))}. "
            f"Expected revenue: {_money(getattr(recommendation, 'expected_revenue', None))}. "
            f"Expected profit: {_money(getattr(recommendation, 'expected_profit', None))}. "
            f"Revenue impact: {_money(getattr(recommendation, 'revenue_impact', None))}. "
            f"Profit impact: {_money(getattr(recommendation, 'profit_impact', None))}. "
            f"Margin rate: {_decimal_text(getattr(recommendation, 'margin_rate', None))}. "
            f"Confidence score: {_decimal_text(getattr(recommendation, 'confidence_score', None))}. "
            f"Estimation method: {_enum_value(getattr(recommendation, 'estimation_method', None))}. "
            f"Status: {status}. Source: dynamic_pricing_recommendations."
        )
        return self._document(
            definition=definition,
            seller_id=recommendation.seller_id,
            product_id=recommendation.product_id,
            source_id=recommendation.id,
            title=title,
            summary=summary,
            content=content,
            event_time=event_time,
            metadata={
                "pricing_analytics_id": str(recommendation.pricing_analytics_id),
                "elasticity_estimate_id": _optional_uuid(getattr(recommendation, "elasticity_estimate_id", None)),
                "action": action,
                "status": status,
                "objective": _enum_value(getattr(recommendation, "objective", None)),
                "estimation_method": _enum_value(getattr(recommendation, "estimation_method", None)),
                "formula_version": getattr(recommendation, "formula_version", None),
            },
        )

    def build_from_inventory_snapshot_or_risk(
        self,
        inventory_snapshot: Any,
        *,
        risk_assessment: Any | None = None,
        sales_velocity: Any | None = None,
        stockout_prediction: Any | None = None,
        reorder_recommendation: Any | None = None,
    ) -> RagMemoryDocumentCreate:
        definition = get_rag_source_definition(RagMemorySourceType.INVENTORY_HISTORY)
        product = getattr(inventory_snapshot, "product", None)
        product_name = _name(product, fallback=f"product {inventory_snapshot.product_id}")
        event_time = getattr(inventory_snapshot, "captured_at", None)
        title = f"Inventory snapshot for {product_name}"
        summary = (
            f"{product_name} had {inventory_snapshot.quantity_available} units available "
            f"on {_date_text(getattr(inventory_snapshot, 'snapshot_date', None) or event_time)}."
        )
        parts = [
            f"On {_date_text(getattr(inventory_snapshot, 'snapshot_date', None) or event_time)}, {product_name} had "
            f"{inventory_snapshot.quantity_available} units available.",
            f"On hand: {inventory_snapshot.quantity_on_hand}. Reserved: {inventory_snapshot.quantity_reserved}. Incoming: {inventory_snapshot.quantity_incoming}.",
        ]
        if sales_velocity is not None:
            parts.append(f"Sales velocity was {_decimal_text(getattr(sales_velocity, 'daily_sales_rate', None))} units/day.")
        if stockout_prediction is not None:
            parts.append(f"Predicted stockout was {_decimal_text(getattr(stockout_prediction, 'days_remaining', None))} days.")
        if risk_assessment is not None:
            parts.append(f"Inventory risk: {_enum_value(getattr(risk_assessment, 'risk_level', None))}.")
            parts.append(f"Risk confidence: {_decimal_text(getattr(risk_assessment, 'confidence_score', None))}.")
        if reorder_recommendation is not None:
            parts.append(
                f"Reorder recommendation: {_enum_value(getattr(reorder_recommendation, 'action', None))}; "
                f"recommended quantity {_clean_text(getattr(reorder_recommendation, 'recommended_quantity', None))}; "
                f"supplier lead time {getattr(reorder_recommendation, 'supplier_lead_time_days', 'unknown')} days."
            )
        parts.append("Source: inventory_history.")
        return self._document(
            definition=definition,
            seller_id=inventory_snapshot.seller_id,
            product_id=inventory_snapshot.product_id,
            source_id=inventory_snapshot.id,
            title=title,
            summary=summary,
            content=" ".join(parts),
            event_time=event_time,
            metadata={
                "snapshot_date": _date_text(getattr(inventory_snapshot, "snapshot_date", None)),
                "source": _enum_value(getattr(inventory_snapshot, "source", None)),
                "risk_assessment_id": _optional_uuid(getattr(risk_assessment, "id", None)),
                "sales_velocity_id": _optional_uuid(getattr(sales_velocity, "id", None)),
                "stockout_prediction_id": _optional_uuid(getattr(stockout_prediction, "id", None)),
                "reorder_recommendation_id": _optional_uuid(getattr(reorder_recommendation, "id", None)),
                "risk_level": _enum_value(getattr(risk_assessment, "risk_level", None)),
            },
        )

    def build_from_telegram_inventory_alert(self, alert: Any) -> RagMemoryDocumentCreate:
        definition = get_rag_source_definition(RagMemorySourceType.ALERT)
        product = getattr(alert, "product", None)
        product_name = _name(product, fallback=f"product {alert.product_id}")
        title = f"Telegram inventory alert {_enum_value(alert.alert_type)} for {product_name}"
        message_summary = _clean_text(getattr(alert, "message_text", None) or "")
        if len(message_summary) > 240:
            message_summary = f"{message_summary[:237]}..."
        content = (
            f"On {_date_text(alert.created_at)}, Telegram inventory alert {_enum_value(alert.alert_type)} "
            f"was created for {product_name}. Status: {_enum_value(alert.status)}. "
            f"Message summary: {message_summary or 'No message text stored.'} Source: telegram_inventory_alerts."
        )
        return self._document(
            definition=definition,
            seller_id=alert.seller_id,
            product_id=alert.product_id,
            source_id=alert.id,
            title=title,
            summary=f"Telegram alert {_enum_value(alert.alert_type)} for {product_name}.",
            content=content,
            event_time=getattr(alert, "sent_at", None) or alert.created_at,
            metadata={
                "risk_assessment_id": _optional_uuid(getattr(alert, "risk_assessment_id", None)),
                "reorder_recommendation_id": _optional_uuid(getattr(alert, "reorder_recommendation_id", None)),
                "alert_type": _enum_value(alert.alert_type),
                "status": _enum_value(alert.status),
                "attempt_count": getattr(alert, "attempt_count", None),
                "metadata": getattr(alert, "alert_metadata", None),
            },
        )

    def build_from_recommendation(self, recommendation: Any) -> RagMemoryDocumentCreate:
        definition = get_rag_source_definition(RagMemorySourceType.RECOMMENDATION)
        product = getattr(recommendation, "product", None)
        if product is None or getattr(product, "seller_id", None) is None:
            raise RagMemoryBuildError("Recommendation memory requires a product with seller ownership.")
        product_name = _name(product, fallback=f"product {recommendation.product_id}")
        action = _enum_value(getattr(recommendation, "action", None))
        title = f"Recommendation {action} for {product_name}"
        summary = f"Recommendation {action} for {product_name} with {_enum_value(recommendation.confidence)} confidence."
        explanation = (getattr(recommendation, "recommendation_context", None) or {}).get("explanation", {})
        revenue_text = (
            "" if explanation.get("prompt_version")
            else f"Revenue opportunity: {_money(recommendation.revenue_opportunity)}. "
        )
        content = (
            f"On {_date_text(recommendation.created_at)}, recommendation for {product_name} selected action {action}. "
            f"Confidence: {_enum_value(recommendation.confidence)}. "
            f"Suggested price range: {_money(recommendation.suggested_price_min)} to {_money(recommendation.suggested_price_max)}. "
            f"{revenue_text}"
            f"Reason: {_clean_text(recommendation.reasoning_bn)} Source: recommendations."
        )
        return self._document(
            definition=definition,
            seller_id=product.seller_id,
            product_id=recommendation.product_id,
            source_id=recommendation.id,
            title=title,
            summary=summary,
            content=content,
            event_time=recommendation.created_at,
            metadata={
                "action": action,
                "confidence": _enum_value(recommendation.confidence),
            },
        )

    def build_from_reorder_recommendation(self, recommendation: Any) -> RagMemoryDocumentCreate:
        definition = get_rag_source_definition(RagMemorySourceType.RECOMMENDATION)
        product = getattr(recommendation, "product", None)
        product_name = _name(product, fallback=f"product {recommendation.product_id}")
        action = _enum_value(getattr(recommendation, "action", None))
        status = _enum_value(getattr(recommendation, "recommendation_status", None))
        content = (
            f"On {_date_text(recommendation.generated_at)}, inventory recommendation for {product_name} selected action {action}. "
            f"Recommended quantity: {_clean_text(getattr(recommendation, 'recommended_quantity', None))}. "
            f"Reorder deadline: {_date_text(getattr(recommendation, 'reorder_deadline', None))}. "
            f"Supplier lead time: {_clean_text(getattr(recommendation, 'supplier_lead_time_days', None))} days. "
            f"Daily sales rate: {_decimal_text(getattr(recommendation, 'daily_sales_rate', None))}. "
            f"Confidence score: {_decimal_text(getattr(recommendation, 'confidence_score', None))}. "
            f"Status: {status}. Reason: {_clean_text(getattr(recommendation, 'explanation', None))} Source: reorder_recommendations."
        )
        return self._document(
            definition=definition,
            seller_id=recommendation.seller_id,
            product_id=recommendation.product_id,
            source_id=recommendation.id,
            title=f"Inventory recommendation {action} for {product_name}",
            summary=f"Inventory recommendation {action} for {product_name} with status {status}.",
            content=content,
            event_time=recommendation.generated_at,
            metadata={
                "action": action,
                "status": status,
                "inventory_snapshot_id": _optional_uuid(getattr(recommendation, "inventory_snapshot_id", None)),
                "sales_velocity_id": _optional_uuid(getattr(recommendation, "sales_velocity_id", None)),
                "stockout_prediction_id": _optional_uuid(getattr(recommendation, "stockout_prediction_id", None)),
                "calculation_version": getattr(recommendation, "calculation_version", None),
            },
            source_table_override="reorder_recommendations",
        )

    def build_from_dead_stock_recovery_recommendation(self, recommendation: Any) -> RagMemoryDocumentCreate:
        definition = get_rag_source_definition(RagMemorySourceType.RECOMMENDATION)
        product = getattr(recommendation, "product", None)
        product_name = _name(product, fallback=f"product {recommendation.product_id}")
        action = _enum_value(getattr(recommendation, "primary_action", None))
        status = _enum_value(getattr(recommendation, "recommendation_status", None))
        content = (
            f"On {_date_text(recommendation.generated_at)}, dead-stock recovery recommendation for {product_name} selected action {action}. "
            f"Recommended price: {_money(getattr(recommendation, 'recommended_price', None))}. "
            f"Recommended discount rate: {_decimal_text(getattr(recommendation, 'recommended_discount_rate', None))}. "
            f"Recommended quantity: {_clean_text(getattr(recommendation, 'recommended_quantity', None))}. "
            f"Duration: {_clean_text(getattr(recommendation, 'suggested_duration_days', None))} days. "
            f"Confidence score: {_decimal_text(getattr(recommendation, 'confidence_score', None))}. "
            f"Status: {status}. Reason: {_clean_text(getattr(recommendation, 'explanation', None))} Source: dead_stock_recovery_recommendations."
        )
        return self._document(
            definition=definition,
            seller_id=recommendation.seller_id,
            product_id=recommendation.product_id,
            source_id=recommendation.id,
            title=f"Dead-stock recovery recommendation {action} for {product_name}",
            summary=f"Dead-stock recovery recommendation {action} for {product_name} with status {status}.",
            content=content,
            event_time=recommendation.generated_at,
            metadata={
                "primary_action": action,
                "secondary_actions": getattr(recommendation, "secondary_actions", None),
                "status": status,
                "dead_stock_assessment_id": _optional_uuid(getattr(recommendation, "dead_stock_assessment_id", None)),
                "calculation_version": getattr(recommendation, "calculation_version", None),
            },
            source_table_override="dead_stock_recovery_recommendations",
        )

    def build_from_alert(self, alert: Any) -> RagMemoryDocumentCreate:
        definition = get_rag_source_definition(RagMemorySourceType.ALERT)
        product = getattr(alert, "product", None)
        product_name = _name(product, fallback=f"product {alert.product_id}")
        title = f"Alert {alert.alert_type} for {product_name}"
        summary = f"Alert {alert.alert_type} for {product_name} had urgency {_enum_value(alert.urgency_level)}."
        content = (
            f"On {_date_text(alert.created_at)}, alert {alert.alert_type} was created for {product_name}. "
            f"Urgency: {_enum_value(alert.urgency_level)}. Action: {_enum_value(alert.action_type)}. "
            f"Confidence: {_enum_value(alert.confidence)}. Delivery status: {_enum_value(alert.delivery_status)}. "
            f"Source: alerts."
        )
        return self._document(
            definition=definition,
            seller_id=alert.seller_id,
            product_id=alert.product_id,
            source_id=alert.id,
            title=title,
            summary=summary,
            content=content,
            event_time=alert.created_at,
            metadata={
                "recommendation_id": _optional_uuid(getattr(alert, "recommendation_id", None)),
                "alert_type": alert.alert_type,
                "urgency_level": _enum_value(alert.urgency_level),
                "action_type": _enum_value(alert.action_type),
                "delivery_status": _enum_value(alert.delivery_status),
                "payload": getattr(alert, "payload", None),
            },
        )

    def build_from_promotion_result(self, result: Mapping[str, Any] | Any) -> RagMemoryDocumentCreate:
        definition = get_rag_source_definition(RagMemorySourceType.PROMOTION_RESULT)
        data = _mapping_from_source(result)
        seller_id = _required(data, "seller_id")
        source_id = data.get("id") or data.get("source_id")
        if source_id is None:
            raise RagMemoryBuildError("Promotion result memory requires id or source_id.")
        product_id = data.get("product_id")
        name = _clean_text(data.get("promotion_name") or data.get("title") or f"promotion {data.get('promotion_plan_id') or source_id}")
        product_name = _clean_text(data.get("product_name") or f"product {product_id}")
        event_time = data.get("ended_at") or data.get("started_at") or data.get("event_time")
        title = f"Promotion result for {product_name}"
        outcome = data.get("outcome") or data.get("result_status") or "recorded"
        summary = f"{name} result for {product_name}: {outcome}."
        content = (
            f"Promotion {name} for {product_name} ran from {_date_text(data.get('started_at'))} to {_date_text(data.get('ended_at'))}. "
            f"Units sold: {_clean_text(data.get('units_sold'))}. Revenue: {_money(data.get('gross_revenue') or data.get('revenue'))}. "
            f"Estimated profit: {_money(data.get('estimated_profit') or data.get('profit'))}. Spend: {_money(data.get('spend'))}. "
            f"Discount cost: {_money(data.get('discount_cost'))}. ROI: {_decimal_text(data.get('roi'))}. "
            f"Outcome: {_clean_text(outcome)}. Missing data: {_clean_text(data.get('missing_data_json') or data.get('missing_data') or 'none')}. Source: promotion_results."
        )
        return self._document(
            definition=definition,
            seller_id=seller_id,
            product_id=product_id,
            source_id=source_id,
            title=title,
            summary=summary,
            content=content,
            event_time=event_time,
            metadata={
                "promotion_name": name,
                "outcome": _clean_text(outcome),
            },
        )

    def build_from_promotion_plan(self, plan: Mapping[str, Any] | Any) -> RagMemoryDocumentCreate:
        definition = get_rag_source_definition(RagMemorySourceType.PROMOTION_PLAN)
        data = _mapping_from_source(plan)
        seller_id = _required(data, "seller_id")
        source_id = data.get("id") or data.get("source_id")
        if source_id is None:
            raise RagMemoryBuildError("Promotion plan memory requires id or source_id.")
        product_id = data.get("product_id")
        title_text = _clean_text(data.get("title") or "Promotion plan")
        product_name = _clean_text(data.get("product_name") or f"product {product_id}")
        content = (
            f"Promotion plan {title_text} for {product_name} is {_clean_text(data.get('status') or 'UNKNOWN')}. "
            f"Type: {_clean_text(data.get('promotion_type'))}. Marketplace: {_clean_text(data.get('marketplace') or 'unspecified')}. "
            f"Category: {_clean_text(data.get('category') or 'unspecified')}. Proposed discount rate: {_decimal_text(data.get('proposed_discount_rate'))}. "
            f"Proposed price: {_money(data.get('proposed_price'))}. Planned period: {_date_text(data.get('planned_start_at'))} to {_date_text(data.get('planned_end_at'))}. "
            f"Expected impact: {_clean_text(data.get('expected_impact_json') or 'unavailable')}. Source: promotion_plans. Marketplace execution is not implemented."
        )
        return self._document(
            definition=definition,
            seller_id=seller_id,
            product_id=product_id,
            source_id=source_id,
            title=f"Promotion plan {title_text}",
            summary=f"Promotion plan {title_text} for {product_name}.",
            content=content,
            event_time=data.get("updated_at") or data.get("created_at") or data.get("planned_start_at"),
            metadata={"promotion_type": data.get("promotion_type"), "status": data.get("status"), "marketplace_execution_enabled": False},
        )

    def build_from_seller_price_history(self, row: Mapping[str, Any] | Any) -> RagMemoryDocumentCreate:
        definition = get_rag_source_definition(RagMemorySourceType.SELLER_PRICE_HISTORY)
        data = _mapping_from_source(row)
        seller_id = _required(data, "seller_id")
        source_id = data.get("id") or data.get("source_id")
        if source_id is None:
            raise RagMemoryBuildError("Seller price history memory requires id or source_id.")
        product_id = _required(data, "product_id")
        source = _clean_text(data.get("source") or "UNKNOWN")
        product_name = _clean_text(data.get("product_name") or f"product {product_id}")
        is_baseline = source == "BASELINE_CURRENT_PRICE"
        content = (
            f"Seller price record for {product_name} on {_date_text(data.get('changed_at') or data.get('created_at'))}. "
            f"Old price: {_money(data.get('old_price'))}. New price: {_money(data.get('new_price'))} {_clean_text(data.get('currency') or '')}. "
            f"Marketplace: {_clean_text(data.get('marketplace') or 'unspecified')}. Source: {source}. "
            f"Reason: {_clean_text(data.get('reason') or 'unspecified')}. "
            f"Baseline current price, not a historical change: {'yes' if is_baseline else 'no'}. Source table: product_price_history."
        )
        return self._document(
            definition=definition,
            seller_id=seller_id,
            product_id=product_id,
            source_id=source_id,
            title=f"Seller price history for {product_name}",
            summary=f"Seller price record for {product_name} from {source}.",
            content=content,
            event_time=data.get("changed_at") or data.get("created_at"),
            metadata={"source": source, "marketplace": data.get("marketplace"), "baseline_not_historical_change": is_baseline},
        )

    def build_generic_from_registered_source(
        self,
        *,
        source_type: RagMemorySourceType,
        source: Mapping[str, Any],
    ) -> RagMemoryDocumentCreate:
        definition = get_rag_source_definition(source_type)
        if definition.model_name is not None:
            raise RagMemoryBuildError(f"Generic builder is not enabled for {source_type.value}.")
        raise RagMemoryBuildError(f"Unsupported generic source type: {source_type.value}.")

    def _document(
        self,
        *,
        definition: RagSourceDefinition,
        seller_id: UUID,
        product_id: UUID | None,
        source_id: Any,
        title: str,
        summary: str,
        content: str,
        event_time: datetime | date | None,
        metadata: dict[str, Any],
        source_table_override: str | None = None,
    ) -> RagMemoryDocumentCreate:
        normalized_title = _clean_text(title)
        normalized_summary = _clean_text(summary)
        normalized_content = _clean_text(content)
        if not normalized_content:
            raise RagMemoryBuildError("Memory document content is empty after sanitization.")
        business_hash = _content_hash(
            source_type=definition.source_type,
            template_version=definition.template_version,
            title=normalized_title,
            summary=normalized_summary,
            content=normalized_content,
        )
        safe_metadata = _sanitize_metadata(
            {
                **metadata,
                "source_table": definition.source_table,
                "actual_source_table": source_table_override or definition.source_table,
                "source_id": str(source_id),
                "template_version": definition.template_version,
                "chunking_rules": definition.chunking_rules,
                "reindex_triggers": list(definition.reindex_triggers),
            },
            excluded=definition.excluded_fields,
        )
        return RagMemoryDocumentCreate(
            seller_id=seller_id,
            product_id=product_id,
            source_type=definition.source_type,
            source_table=source_table_override or definition.source_table or definition.source_type.value.lower(),
            source_id=str(source_id),
            source_version=definition.template_version,
            title=normalized_title,
            summary_text=normalized_summary,
            content_text=normalized_content,
            language="en",
            metadata_json=safe_metadata,
            sensitivity_level=definition.sensitivity_level,
            visibility_scope=definition.visibility_scope,
            event_time=_datetime_or_none(event_time),
            content_hash=business_hash,
            chunking_version=definition.chunking_version,
            embedding_status=RagMemoryEmbeddingStatus.PENDING,
        )


def _content_hash(*, source_type: RagMemorySourceType, template_version: str, title: str, summary: str, content: str) -> str:
    payload = "\n".join([source_type.value, template_version, title, summary, content])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<style\b[^<]*(?:(?!</style>)<[^<]*)*</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*\S+", r"\1: [REDACTED]", text)
    text = re.sub(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[REDACTED_EMAIL]", text)
    text = re.sub(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)", _redact_phone_candidate, text)
    text = re.sub(r"Traceback \(most recent call last\):.*", "[REDACTED_STACK_TRACE]", text, flags=re.DOTALL)
    return re.sub(r"\s+", " ", text).strip()


def _redact_phone_candidate(match: re.Match[str]) -> str:
    candidate = match.group(0)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate):
        return candidate
    digits = re.sub(r"\D", "", candidate)
    if len(digits) < 10:
        return candidate
    return "[REDACTED_PHONE]"


def _sanitize_metadata(value: Any, *, excluded: tuple[str, ...] = COMMON_EXCLUDED_FIELDS) -> Any:
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if any(excluded_item in lowered for excluded_item in excluded):
                continue
            result[key_text] = _sanitize_metadata(item, excluded=excluded)
        return result
    if isinstance(value, list):
        return [_sanitize_metadata(item, excluded=excluded) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_metadata(item, excluded=excluded) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return _clean_text(value) if isinstance(value, str) else value


def _mapping_from_source(source: Mapping[str, Any] | Any) -> dict[str, Any]:
    if isinstance(source, Mapping):
        return dict(source)
    return {
        key: getattr(source, key)
        for key in dir(source)
        if not key.startswith("_") and not callable(getattr(source, key))
    }


def _required(data: Mapping[str, Any], key: str) -> Any:
    value = data.get(key)
    if value is None:
        raise RagMemoryBuildError(f"Memory source is missing required field: {key}")
    return value


def _enum_value(value: Any) -> str:
    if value is None:
        return "UNKNOWN"
    return str(getattr(value, "value", value))


def _optional_uuid(value: Any) -> str | None:
    return None if value is None else str(value)


def _datetime_or_none(value: datetime | date | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime(value.year, value.month, value.day)


def _date_text(value: datetime | date | None) -> str:
    if value is None:
        return "unknown date"
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


def _decimal_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return _clean_text(value)


def _money(value: Any) -> str:
    amount = _decimal_text(value)
    if amount is None or amount == "":
        return "unknown"
    return f"BDT {amount}"


def _value_from_dict(data: Mapping[str, Any] | None, key: str) -> Any:
    if not isinstance(data, Mapping):
        return None
    return data.get(key)


def _name(obj: Any, *, fallback: str) -> str:
    return _first_present(obj, ("title", "name", "product_name"), fallback=fallback)


def _first_present(obj: Any, fields: tuple[str, ...], *, fallback: str) -> str:
    if obj is None:
        return _clean_text(fallback)
    for field in fields:
        value = getattr(obj, field, None)
        if value:
            return _clean_text(value)
    return _clean_text(fallback)


def _spec_value(product: Any, key: str) -> str | None:
    specs = getattr(product, "specifications", None) or {}
    if not isinstance(specs, Mapping):
        return None
    for candidate in (key, key.upper(), key.lower()):
        value = specs.get(candidate)
        if value:
            return _clean_text(value)
    return None


def _transaction_price(sale: Any, product: Any) -> Decimal | None:
    value = getattr(sale, "unit_price", None)
    return Decimal(str(value)) if value is not None else None


def _transaction_revenue(sale: Any) -> Decimal | None:
    value = getattr(sale, "line_total", None)
    return Decimal(str(value)) if value is not None else None


def _table_name(row: Any) -> str:
    table = getattr(row, "__tablename__", None)
    if table:
        return _clean_text(table)
    table_obj = getattr(row, "__table__", None)
    name = getattr(table_obj, "name", None)
    return _clean_text(name or type(row).__name__)
