from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.marketplace_fee_policy import MarketplaceFeePolicy
from app.models.product import Product
from app.services.copilot.sales_revenue_analytics_service import SalesLine, SalesRevenueAnalyticsService, _evidence


class ProfitMarginAnalyticsService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._sales = SalesRevenueAnalyticsService(db)

    def get_profit_summary(
        self,
        *,
        seller_id: UUID,
        from_date,
        to_date,
        product_id: UUID | None = None,
        category: str | None = None,
        marketplace: str | None = None,
    ) -> tuple[dict[str, Any], list[str]]:
        sales_args = {
            "seller_id": seller_id,
            "from_date": from_date,
            "to_date": to_date,
            "product_id": product_id,
            "category": category,
        }
        if marketplace is not None:
            sales_args["marketplace"] = marketplace
        lines = self._sales._sales_lines(**sales_args)
        fee_policies = self._fee_policies(seller_id=seller_id)
        by_product: dict[UUID, dict[str, Any]] = {}
        excluded_missing_cost: dict[UUID, Product] = {}
        excluded_missing_fee: dict[UUID, Product] = {}
        excluded_missing_price: dict[UUID, Product] = {}
        total_revenue = Decimal("0")
        total_profit = Decimal("0")
        for line in lines:
            total_revenue += line.gross_revenue
            if line.unit_price is None:
                excluded_missing_price[line.product.id] = line.product
                continue
            if line.product.cost_price is None:
                excluded_missing_cost[line.product.id] = line.product
                continue
            policy = _matching_fee_policy(line.product, fee_policies)
            if policy is None:
                excluded_missing_fee[line.product.id] = line.product
                continue
            fee = _fee_for_line(line, policy)
            profit = line.gross_revenue - Decimal(line.gross_units) * Decimal(line.product.cost_price) - fee
            total_profit += profit
            row = by_product.setdefault(
                line.product.id,
                {"product": {"id": str(line.product.id), "title": line.product.title, "category": line.product.category}, "gross_revenue": Decimal("0"), "estimated_profit": Decimal("0"), "units_sold": 0, "evidence": []},
            )
            row["gross_revenue"] += line.gross_revenue
            row["estimated_profit"] += profit
            row["units_sold"] += line.net_units
            row["evidence"].append(_evidence("sales_records", line.sale.id))
        partial = bool(excluded_missing_cost or excluded_missing_fee or excluded_missing_price)
        margin_rate = None if total_revenue == 0 or not by_product else total_profit / total_revenue
        missing = []
        if excluded_missing_cost:
            missing.append("Some products were excluded from profit because product cost is missing.")
        if excluded_missing_fee:
            missing.append("Some products were excluded from profit because marketplace fee policy is missing.")
        if excluded_missing_price:
            missing.append("Some products were excluded from profit because transaction/current selling price is missing.")
        return {
            "gross_revenue": total_revenue,
            "estimated_profit": total_profit if by_product else None,
            "profit_label": "PARTIAL" if partial else "COMPLETE",
            "profit_by_product": sorted(by_product.values(), key=lambda item: item["estimated_profit"], reverse=True),
            "margin_rate": margin_rate,
            "products_excluded_due_to_missing_cost": [_product_ref(product) for product in excluded_missing_cost.values()],
            "products_excluded_due_to_missing_marketplace_fee_policy": [_product_ref(product) for product in excluded_missing_fee.values()],
            "products_excluded_due_to_missing_transaction_price": [_product_ref(product) for product in excluded_missing_price.values()],
            "confidence": "MEDIUM" if partial else "HIGH",
            "evidence": [_evidence("sales_records", line.sale.id) for line in lines[:20]] + [_evidence("marketplace_fee_policies", "seller_scope")],
        }, missing

    def _fee_policies(self, *, seller_id: UUID) -> list[MarketplaceFeePolicy]:
        return self._db.execute(
            select(MarketplaceFeePolicy).where(MarketplaceFeePolicy.seller_id == seller_id, MarketplaceFeePolicy.is_active.is_(True))
        ).scalars().all()


def _matching_fee_policy(product: Product, policies: list[MarketplaceFeePolicy]) -> MarketplaceFeePolicy | None:
    for policy in policies:
        if policy.product_id == product.id:
            return policy
    for policy in policies:
        if policy.product_id is None and policy.category == product.category:
            return policy
    for policy in policies:
        if policy.product_id is None and policy.category is None:
            return policy
    return None


def _fee_for_line(line: SalesLine, policy: MarketplaceFeePolicy) -> Decimal:
    unit_price = line.unit_price or Decimal("0")
    return (
        line.gross_revenue * Decimal(policy.percentage_commission_rate)
        + line.gross_revenue * Decimal(policy.payment_fee_rate)
        + Decimal(line.gross_units) * Decimal(policy.fixed_per_unit_fee)
        + Decimal(policy.fixed_per_order_fee)
        + Decimal(line.gross_units) * Decimal(policy.fulfilment_fee)
        + Decimal(line.gross_units) * Decimal(policy.other_variable_cost)
        - Decimal(line.gross_units) * Decimal(policy.shipping_subsidy)
    )


def _product_ref(product: Product) -> dict[str, Any]:
    return {"id": str(product.id), "title": product.title, "category": product.category}
