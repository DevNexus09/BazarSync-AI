from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.competitor_event import CompetitorEvent
from app.models.dynamic_pricing_recommendation import DynamicPricingRecommendation
from app.models.inventory_risk import InventoryRiskAssessment, InventoryRiskLevel
from app.services.copilot.sales_revenue_analytics_service import SalesRevenueAnalyticsService, _evidence


class BusinessChangeAnalyticsService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._sales = SalesRevenueAnalyticsService(db)

    def explain_revenue_change(
        self,
        *,
        seller_id: UUID,
        from_date,
        to_date,
        compare_to_previous_period: bool = True,
        product_id: UUID | None = None,
        category: str | None = None,
        marketplace: str | None = None,
    ) -> tuple[dict[str, Any], list[str]]:
        current, missing = self._sales.get_revenue_summary(
            seller_id=seller_id,
            from_date=from_date,
            to_date=to_date,
            product_id=product_id,
            category=category,
            marketplace=marketplace,
            compare_to_previous_period=compare_to_previous_period,
        )
        days = (to_date - from_date).days + 1
        previous_from = from_date - timedelta(days=days)
        previous_to = from_date - timedelta(days=1)
        previous, _ = self._sales.get_revenue_summary(
            seller_id=seller_id,
            from_date=previous_from,
            to_date=previous_to,
            product_id=product_id,
            category=category,
            marketplace=marketplace,
            compare_to_previous_period=False,
        )
        units_delta = current["units_sold"] - previous["units_sold"]
        current_asp = _ratio(current["gross_revenue"], Decimal(current["units_sold"])) if current["units_sold"] else None
        previous_asp = _ratio(previous["gross_revenue"], Decimal(previous["units_sold"])) if previous["units_sold"] else None
        asp_delta = None if current_asp is None or previous_asp is None else current_asp - previous_asp
        factors = self._factors(seller_id=seller_id, product_id=product_id)
        missing.append("Promotion persistence is not implemented; promotion effect is unavailable unless promotion result records are added.")
        return {
            "revenue_delta": current["gross_revenue"] - previous["gross_revenue"],
            "units_sold_delta": units_delta,
            "average_selling_price_delta": asp_delta,
            "inventory_stockout_effect": _factor_payload(factors, "inventory"),
            "competitor_effect": _factor_payload(factors, "competitor"),
            "pricing_recommendation_effect": _factor_payload(factors, "pricing"),
            "promotion_effect": None,
            "likely_factors": sorted(factors, key=lambda item: item["evidence_strength"], reverse=True),
            "current_period": current,
            "previous_period": previous,
            "evidence": current["evidence"] + previous["evidence"] + [item["evidence"] for item in factors],
        }, missing

    def _factors(self, *, seller_id: UUID, product_id: UUID | None) -> list[dict[str, Any]]:
        factors = []
        risk_statement = select(func.count()).select_from(InventoryRiskAssessment).where(
            InventoryRiskAssessment.seller_id == seller_id,
            InventoryRiskAssessment.risk_level.in_([InventoryRiskLevel.HIGH, InventoryRiskLevel.CRITICAL]),
        )
        if product_id:
            risk_statement = risk_statement.where(InventoryRiskAssessment.product_id == product_id)
        risk_count = int(self._db.execute(risk_statement).scalar_one() or 0)
        if risk_count:
            factors.append({"source": "inventory", "reason": f"{risk_count} high/critical inventory risk signal(s).", "evidence_strength": min(100, risk_count * 20), "evidence": _evidence("inventory_risk_assessments", "seller_scope")})
        competitor_statement = select(func.count()).select_from(CompetitorEvent).where(CompetitorEvent.seller_id == seller_id)
        if product_id:
            competitor_statement = competitor_statement.where(CompetitorEvent.product_id == product_id)
        competitor_count = int(self._db.execute(competitor_statement).scalar_one() or 0)
        if competitor_count:
            factors.append({"source": "competitor", "reason": f"{competitor_count} competitor event(s) found.", "evidence_strength": min(100, competitor_count * 15), "evidence": _evidence("competitor_events", "seller_scope")})
        pricing_statement = select(func.count()).select_from(DynamicPricingRecommendation).where(DynamicPricingRecommendation.seller_id == seller_id)
        if product_id:
            pricing_statement = pricing_statement.where(DynamicPricingRecommendation.product_id == product_id)
        pricing_count = int(self._db.execute(pricing_statement).scalar_one() or 0)
        if pricing_count:
            factors.append({"source": "pricing", "reason": f"{pricing_count} pricing recommendation signal(s) found.", "evidence_strength": min(100, pricing_count * 15), "evidence": _evidence("dynamic_pricing_recommendations", "seller_scope")})
        return factors


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    return None if denominator == 0 else numerator / denominator


def _factor_payload(factors: list[dict[str, Any]], source: str) -> dict[str, Any] | None:
    return next((item for item in factors if item["source"] == source), None)

