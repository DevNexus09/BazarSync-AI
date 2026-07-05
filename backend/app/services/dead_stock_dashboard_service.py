from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from app.models.dead_stock_assessment import DeadStockClassification, DeadStockDataStatus, DeadStockRiskLevel
from app.models.dead_stock_capital_recovery import DeadStockCapitalRecoveryEstimate
from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryAction
from app.repositories.dead_stock_dashboard_repository import DeadStockDashboardRepository
from app.schemas.dead_stock_dashboard import (
    DeadStockProductIntelligenceResponse,
    DeadStockProductListItem,
    DeadStockProductPageResponse,
    DeadStockSummaryResponse,
)


class DashboardRepositoryProtocol(Protocol):
    def product_exists(self, *, seller_id: UUID, product_id: UUID) -> bool: ...
    def rows(self, **kwargs) -> tuple[list[dict], int]: ...
    def product_bundle(self, *, seller_id: UUID, product_id: UUID) -> dict | None: ...


class DeadStockDashboardService:
    def __init__(self, db=None, *, repository: DashboardRepositoryProtocol | None = None) -> None:
        if repository is None and db is None:
            raise ValueError("Either db or repository is required.")
        self._repository = repository or DeadStockDashboardRepository(db)

    def summary(self, *, seller_id: UUID) -> DeadStockSummaryResponse:
        rows, _ = self._repository.rows(seller_id=seller_id, limit=None, offset=0)
        products = [row["product"] for row in rows]
        assessments = [row["assessment"] for row in rows if row["assessment"] is not None]
        capital_rows = [row["capital"] for row in rows if row["capital"] is not None]
        comparable = _comparable_capital(capital_rows)
        return DeadStockSummaryResponse(
            total_products_with_inventory=len(products),
            healthy_product_count=_count_class(assessments, DeadStockClassification.HEALTHY),
            slow_moving_count=_count_class(assessments, DeadStockClassification.SLOW_MOVING),
            at_risk_count=_count_class(assessments, DeadStockClassification.AT_RISK),
            dead_stock_count=_count_class(assessments, DeadStockClassification.DEAD_STOCK),
            critical_risk_count=sum(1 for item in assessments if item.risk_level == DeadStockRiskLevel.CRITICAL),
            total_eligible_dead_stock_units=sum(
                int(getattr(item, "eligible_quantity", 0) or 0)
                for item in assessments
                if item.classification == DeadStockClassification.DEAD_STOCK
            ),
            total_locked_capital=_sum_nullable([row.locked_capital for row in capital_rows]) if comparable["monetary"] else None,
            locked_capital_currency=comparable["currency"] if comparable["monetary"] else None,
            estimated_recoverable_cash=_sum_nullable([row.gross_recovered_cash for row in capital_rows]) if comparable["monetary"] and comparable["horizon"] else None,
            recoverable_cash_currency=comparable["currency"] if comparable["monetary"] and comparable["horizon"] else None,
            products_with_insufficient_data=sum(1 for item in assessments if item.data_status == DeadStockDataStatus.INSUFFICIENT),
            products_requiring_manual_review=sum(1 for row in rows if getattr(row["recommendation"], "primary_action", None) == DeadStockRecoveryAction.MANUAL_REVIEW),
            last_calculation_time=max(_timestamps(rows), default=None),
            formula_version=_formula_version(rows),
            monetary_totals_comparable=bool(comparable["monetary"] and comparable["horizon"]),
            forecast_horizon_days=comparable["duration"] if comparable["horizon"] else None,
            age_distribution=_age_distribution(assessments),
        )

    def products(self, *, seller_id: UUID, classification, risk_level, category, marketplace, min_age_days, min_locked_capital, recommendation_action, data_status, sort, limit, offset) -> DeadStockProductPageResponse:
        rows, total = self._repository.rows(
            seller_id=seller_id,
            classification=classification,
            risk_level=risk_level,
            category=category,
            marketplace=marketplace,
            min_age_days=min_age_days,
            min_locked_capital=min_locked_capital,
            recommendation_action=recommendation_action,
            data_status=data_status,
            sort=sort,
            limit=limit,
            offset=offset,
        )
        return DeadStockProductPageResponse(
            items=[_list_item(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    def product_intelligence(self, *, seller_id: UUID, product_id: UUID) -> DeadStockProductIntelligenceResponse | None:
        row = self._repository.product_bundle(seller_id=seller_id, product_id=product_id)
        if row is None:
            return None
        product = row["product"]
        assessment = row["assessment"]
        aging = row["aging"]
        velocity = row["velocity"]
        recommendation = row["recommendation"]
        capital = row["capital"]
        last = max(_timestamps([row]), default=None)
        return DeadStockProductIntelligenceResponse(
            product_id=product.id,
            product_name=product.title,
            category=product.category,
            current_inventory=product.stock_quantity,
            eligible_unsold_quantity=getattr(assessment, "eligible_quantity", None),
            inventory_age_days=getattr(assessment, "inventory_age_days", None),
            inventory_age_is_estimated=bool(getattr(assessment, "inventory_age_is_estimated", False)),
            inventory_age_state=getattr(assessment, "inventory_age_state", None),
            age_source=getattr(getattr(aging, "age_source", None), "value", None),
            days_since_last_sale=getattr(assessment, "days_since_last_sale", None),
            daily_sales_rate=getattr(velocity, "daily_sales_rate", None),
            velocity_data_status=getattr(getattr(velocity, "data_status", None), "value", None),
            visibility_status=getattr(assessment, "visibility_status", None),
            classification=getattr(assessment, "classification", None),
            risk_score=getattr(assessment, "risk_score", None),
            risk_level=getattr(assessment, "risk_level", None),
            triggered_rules=getattr(assessment, "triggered_rules", []) if assessment else [],
            locked_capital=getattr(capital, "locked_capital", None),
            locked_capital_currency=_currency(capital),
            primary_recovery_recommendation=getattr(recommendation, "primary_action", None),
            recommended_discount_rate=getattr(recommendation, "recommended_discount_rate", None),
            recommended_price=getattr(recommendation, "recommended_price", None),
            potential_recovered_cash_low=getattr(capital, "gross_recovered_cash_low", None),
            potential_recovered_cash=getattr(capital, "gross_recovered_cash", None),
            potential_recovered_cash_high=getattr(capital, "gross_recovered_cash_high", None),
            confidence=_min_confidence(assessment, recommendation, capital),
            data_status=getattr(assessment, "data_status", None),
            last_updated_at=last,
            formula_version=_formula_version([row]),
            recovery_recommendation=_recommendation_payload(recommendation),
            capital_recovery=_capital_payload(capital),
            evidence={
                "dead_stock": getattr(assessment, "rule_results", None),
                "recovery": getattr(recommendation, "evidence", None),
                "capital_recovery": getattr(capital, "evidence", None),
            },
        )


def _list_item(row: dict) -> DeadStockProductListItem:
    product = row["product"]
    assessment = row["assessment"]
    recommendation = row["recommendation"]
    capital = row["capital"]
    return DeadStockProductListItem(
        product_id=product.id,
        product_name=product.title,
        category=product.category,
        current_stock=product.stock_quantity,
        eligible_unsold_quantity=getattr(assessment, "eligible_quantity", None),
        inventory_age_days=getattr(assessment, "inventory_age_days", None),
        inventory_age_is_estimated=bool(getattr(assessment, "inventory_age_is_estimated", False)),
        age_source=getattr(getattr(row["aging"], "age_source", None), "value", None),
        days_since_last_sale=getattr(assessment, "days_since_last_sale", None),
        classification=getattr(assessment, "classification", None),
        risk_score=getattr(assessment, "risk_score", None),
        risk_level=getattr(assessment, "risk_level", None),
        locked_capital=getattr(capital, "locked_capital", None),
        locked_capital_currency=_currency(capital),
        primary_recommendation=getattr(recommendation, "primary_action", None),
        recommendation_status=getattr(recommendation, "recommendation_status", None),
        potential_recovery=getattr(capital, "gross_recovered_cash", None),
        potential_recovery_low=getattr(capital, "gross_recovered_cash_low", None),
        potential_recovery_high=getattr(capital, "gross_recovered_cash_high", None),
        data_status=getattr(assessment, "data_status", None),
        last_calculated_at=max(_timestamps([row]), default=None),
    )


def _count_class(items, classification):
    return sum(1 for item in items if item.classification == classification)


def _sum_nullable(values):
    clean = [value for value in values if value is not None]
    return sum(clean, Decimal("0.00")) if clean else None


def _currency(capital: DeadStockCapitalRecoveryEstimate | None):
    if capital is None:
        return None
    return (capital.evidence or {}).get("currency")


def _duration(capital: DeadStockCapitalRecoveryEstimate | None):
    if capital is None:
        return None
    return (capital.evidence or {}).get("duration_days")


def _comparable_capital(items):
    currencies = {_currency(item) for item in items if item.locked_capital is not None}
    durations = {_duration(item) for item in items if item.gross_recovered_cash is not None}
    return {
        "monetary": len(currencies) == 1,
        "currency": next(iter(currencies)) if len(currencies) == 1 else None,
        "horizon": len(durations) == 1,
        "duration": next(iter(durations)) if len(durations) == 1 else None,
    }


def _timestamps(rows) -> list[datetime]:
    values = []
    for row in rows:
        for key, attr in (("assessment", "assessed_at"), ("recommendation", "generated_at"), ("capital", "calculated_at"), ("aging", "calculated_at"), ("velocity", "calculated_at")):
            value = getattr(row.get(key), attr, None)
            if value is not None:
                values.append(value)
    return values


def _formula_version(rows):
    versions = [getattr(row.get("capital"), "calculation_version", None) or getattr(row.get("recommendation"), "calculation_version", None) or getattr(row.get("assessment"), "calculation_version", None) for row in rows]
    clean = [version for version in versions if version]
    return clean[0] if clean else None


def _age_distribution(assessments):
    buckets = {"0-30": 0, "31-45": 0, "46-60": 0, "61-90": 0, "91-180": 0, "180+": 0}
    for item in assessments:
        age = item.inventory_age_days
        if age is None:
            continue
        if age <= 30:
            buckets["0-30"] += 1
        elif age <= 45:
            buckets["31-45"] += 1
        elif age <= 60:
            buckets["46-60"] += 1
        elif age <= 90:
            buckets["61-90"] += 1
        elif age <= 180:
            buckets["91-180"] += 1
        else:
            buckets["180+"] += 1
    return buckets


def _min_confidence(*items):
    values = [getattr(item, "confidence_score", None) for item in items if item is not None and getattr(item, "confidence_score", None) is not None]
    return min(values) if values else None


def _recommendation_payload(item):
    if item is None:
        return None
    return {
        "primary_action": item.primary_action.value,
        "secondary_actions": item.secondary_actions,
        "explanation": item.explanation,
        "evidence": item.evidence,
        "rejected_actions": item.rejected_actions,
        "confidence_score": str(item.confidence_score),
    }


def _capital_payload(item):
    if item is None:
        return None
    return {
        "estimate_status": item.estimate_status.value,
        "estimation_method": item.estimation_method.value,
        "evidence": item.evidence,
        "confidence_score": str(item.confidence_score),
        "contribution_recovered": str(item.contribution_recovered) if item.contribution_recovered is not None else None,
        "capital_recovery_ratio": str(item.capital_recovery_ratio) if item.capital_recovery_ratio is not None else None,
    }
