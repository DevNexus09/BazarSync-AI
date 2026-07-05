from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.dead_stock_assessment import DeadStockAssessment
from app.models.dead_stock_capital_recovery import DeadStockCapitalRecoveryEstimate
from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryRecommendation
from app.models.inventory_aging import InventoryAgeSource, InventoryAgingSnapshot
from app.models.inventory_history import InventoryHistory
from app.models.inventory_stock_in import InventoryStockIn
from app.models.marketplace_fee_policy import MarketplaceFeePolicy
from app.models.pricing_policy import PricingPolicy
from app.models.product import Product
from app.models.product_visibility_metric import ProductVisibilityMetric
from app.models.sales_record import SalesRecord, SalesRecordStatus
from app.models.sales_velocity import SalesVelocity
from app.schemas.dead_stock_readiness import (
    DeadStockReadinessCheck,
    DeadStockReadinessNextAction,
    DeadStockReadinessResponse,
    DeadStockReadinessStatus,
)

VALID_SALE_STATUSES = (SalesRecordStatus.COMPLETED, SalesRecordStatus.FULFILLED)


class DeadStockReadinessService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def evaluate(self, *, seller_id: UUID, product_id: UUID) -> DeadStockReadinessResponse | None:
        product = self._product(seller_id=seller_id, product_id=product_id)
        if product is None:
            return None

        now = datetime.now(timezone.utc)
        aging = self._latest_aging(seller_id=seller_id, product_id=product_id)
        first_stock_in = self._first_stock_in(seller_id=seller_id, product_id=product_id)
        first_positive_inventory = self._first_positive_inventory(seller_id=seller_id, product_id=product_id)
        assessment = self._latest_assessment(seller_id=seller_id, product_id=product_id)
        velocity = self._latest_velocity(seller_id=seller_id, product_id=product_id)
        recommendation = self._latest_recommendation(seller_id=seller_id, product_id=product_id)
        capital = self._latest_capital(seller_id=seller_id, product_id=product_id)
        marketplace = _marketplace_for_product(product) or self._known_marketplace(seller_id=seller_id, product=product)
        currency = self._known_currency(seller_id=seller_id, product=product, marketplace=marketplace)
        fee_policy = self._active_fee_policy(seller_id=seller_id, product=product, marketplace=marketplace)
        pricing_policy = self._active_pricing_policy(seller_id=seller_id, product_id=product.id, marketplace=marketplace)
        visibility_metric = self._latest_visibility_metric(seller_id=seller_id, product_id=product.id)
        sales = self._sales_state(seller_id=seller_id, product_id=product.id)

        checks: dict[str, DeadStockReadinessCheck] = {}
        checks["current_stock"] = _check(
            status=DeadStockReadinessStatus.OK if product.stock_quantity > 0 else DeadStockReadinessStatus.MISSING,
            reason_code=None if product.stock_quantity > 0 else "MISSING_CURRENT_STOCK",
            message="Current stock is available." if product.stock_quantity > 0 else "No current available stock exists for this product.",
            blocking=product.stock_quantity <= 0,
            current_value=product.stock_quantity,
            next_action=None if product.stock_quantity > 0 else "Add stock before running active dead-stock recovery.",
        )
        has_cost = product.cost_price is not None and _decimal(product.cost_price) > 0
        checks["product_cost"] = _check(
            status=DeadStockReadinessStatus.OK if has_cost else DeadStockReadinessStatus.MISSING,
            reason_code=None if has_cost else "MISSING_PRODUCT_COST",
            message="Product cost is available." if has_cost else "Product cost is required to calculate locked capital and safe recovery pricing.",
            blocking=not has_cost,
            current_value=product.cost_price if has_cost else None,
            next_action=None if has_cost else "Add product landed cost.",
            href=None if has_cost else f"/app/products/{product.id}/edit",
        )
        has_price = product.selling_price is not None and _decimal(product.selling_price) > 0
        checks["selling_price"] = _check(
            status=DeadStockReadinessStatus.OK if has_price else DeadStockReadinessStatus.MISSING,
            reason_code=None if has_price else "MISSING_SELLING_PRICE",
            message="Current selling price is available." if has_price else "Current selling price is required before recovery pricing can be evaluated.",
            blocking=not has_price,
            current_value=product.selling_price if has_price else None,
            next_action=None if has_price else "Add current selling price.",
            href=None if has_price else f"/app/products/{product.id}/edit",
        )
        checks["currency"] = _check(
            status=DeadStockReadinessStatus.OK if currency else DeadStockReadinessStatus.MISSING,
            reason_code=None if currency else "MISSING_CURRENCY",
            message="Currency is available from pricing or fee policy." if currency else "Currency is required for safe pricing and capital recovery estimates.",
            blocking=currency is None,
            current_value=currency,
            next_action=None if currency else "Set up marketplace fees or pricing policy with currency.",
            href=None if currency else f"/app/pricing/fee-setup?productId={product.id}",
        )
        checks["marketplace"] = _check(
            status=DeadStockReadinessStatus.OK if marketplace else DeadStockReadinessStatus.MISSING,
            reason_code=None if marketplace else "MISSING_MARKETPLACE",
            message="Marketplace is available." if marketplace else "Marketplace is required to select the correct fee and pricing policy.",
            blocking=marketplace is None,
            current_value=marketplace,
            next_action=None if marketplace else "Set up marketplace fees for this product.",
            href=None if marketplace else f"/app/pricing/fee-setup?productId={product.id}",
        )

        age_available = aging is not None and aging.age_source != InventoryAgeSource.UNAVAILABLE and aging.oldest_age_days is not None
        source_available = age_available or first_stock_in is not None or first_positive_inventory is not None
        checks["inventory_age_source"] = _check(
            status=DeadStockReadinessStatus.OK if source_available else DeadStockReadinessStatus.MISSING,
            reason_code=None if source_available else "MISSING_INVENTORY_AGE_SOURCE",
            message=(
                "Inventory age source is available."
                if source_available
                else "Inventory received date or stock-in history is required to calculate inventory age."
            ),
            blocking=not source_available,
            current_value=getattr(getattr(aging, "age_source", None), "value", None) or getattr(first_stock_in, "received_at", None) or getattr(first_positive_inventory, "snapshot_date", None),
            next_action=None if source_available else "Add purchase receipt, inventory lot, goods-received date, or stock-in transaction.",
            href=None,
        )
        checks["inventory_aging"] = _check(
            status=DeadStockReadinessStatus.OK if age_available else DeadStockReadinessStatus.PENDING_CALCULATION if source_available else DeadStockReadinessStatus.MISSING,
            reason_code=None if age_available else "MISSING_INVENTORY_AGING_CALCULATION",
            message=(
                "Latest inventory aging has been calculated."
                if age_available
                else "Inventory aging has not been calculated from the available source data."
                if source_available
                else "Inventory aging requires an inventory age source first."
            ),
            blocking=not source_available,
            current_value=getattr(aging, "oldest_age_days", None),
            next_action=None if age_available else "Run inventory aging calculation.",
        )

        checks["sales_history"] = self._sales_history_check(sales)
        checks["sales_velocity"] = _check(
            status=DeadStockReadinessStatus.OK if velocity else DeadStockReadinessStatus.MISSING,
            reason_code=None if velocity else "MISSING_SALES_VELOCITY",
            message="Latest sales velocity is available." if velocity else "Sales velocity has not been calculated yet.",
            blocking=False,
            current_value=getattr(velocity, "daily_sales_rate", None),
            next_action=None if velocity else "Run sales velocity calculation after sales data is imported.",
        )
        checks["marketplace_fee_policy"] = _check(
            status=DeadStockReadinessStatus.OK if fee_policy else DeadStockReadinessStatus.MISSING,
            reason_code=None if fee_policy else "MISSING_MARKETPLACE_FEE_POLICY",
            message="Marketplace fee policy is available." if fee_policy else "Marketplace fee policy is required before discount recovery can be estimated safely.",
            blocking=fee_policy is None,
            current_value=getattr(fee_policy, "version", None),
            next_action=None if fee_policy else "Set up marketplace fees.",
            href=None if fee_policy else f"/app/pricing/fee-setup?productId={product.id}",
        )
        checks["pricing_policy"] = _check(
            status=DeadStockReadinessStatus.OK if pricing_policy else DeadStockReadinessStatus.MISSING,
            reason_code=None if pricing_policy else "MISSING_PRICING_POLICY",
            message="Pricing policy is available." if pricing_policy else "Pricing policy is required to know the minimum margin, discount limit, and price increment.",
            blocking=pricing_policy is None,
            current_value=getattr(pricing_policy, "id", None),
            next_action=None if pricing_policy else "Set up pricing policy.",
            href=None,
        )
        visibility_status = self._visibility_status(visibility_metric)
        checks["visibility_data"] = _check(
            status=DeadStockReadinessStatus.OK if visibility_metric else DeadStockReadinessStatus.UNAVAILABLE,
            reason_code=None if visibility_metric else "VISIBILITY_DATA_UNAVAILABLE",
            message=(
                f"Visibility metrics are available. Current status: {visibility_status}."
                if visibility_metric
                else "Visibility data is unavailable. SEO recovery recommendations cannot be evaluated yet."
            ),
            blocking=False,
            current_value=visibility_status if visibility_metric else None,
            next_action=None if visibility_metric else "Add visibility metrics later.",
            href=None if visibility_metric else f"/app/products/{product.id}/visibility",
        )
        checks["dead_stock_assessment"] = _check(
            status=DeadStockReadinessStatus.OK if assessment else DeadStockReadinessStatus.PENDING_CALCULATION,
            reason_code=None if assessment else "MISSING_DEAD_STOCK_ASSESSMENT",
            message="Latest dead-stock assessment is available." if assessment else "Dead stock assessment has not been calculated for the latest available data.",
            blocking=False,
            current_value=getattr(getattr(assessment, "classification", None), "value", None),
            next_action=None if assessment else "Run dead stock analysis.",
        )
        checks["risk_score"] = _check(
            status=DeadStockReadinessStatus.OK if assessment and assessment.risk_score is not None else DeadStockReadinessStatus.PENDING_CALCULATION if assessment else DeadStockReadinessStatus.MISSING,
            reason_code=None if assessment and assessment.risk_score is not None else "MISSING_RISK_SCORE",
            message=(
                "Risk score is available."
                if assessment and assessment.risk_score is not None
                else "Run risk scoring to calculate risk score."
                if assessment
                else "Risk score requires a dead stock assessment first."
            ),
            blocking=False,
            current_value=getattr(assessment, "risk_score", None),
            next_action=None if assessment and assessment.risk_score is not None else "Run risk scoring.",
        )
        checks["recovery_recommendation"] = _check(
            status=DeadStockReadinessStatus.OK if recommendation else DeadStockReadinessStatus.ACTION_REQUIRED,
            reason_code=None if recommendation else "MISSING_RECOVERY_RECOMMENDATION",
            message=(
                "Latest recovery recommendation is available."
                if recommendation
                else "Recovery recommendation requires product cost, selling price, fee policy, pricing policy, and MarginGuard validation."
            ),
            blocking=False,
            current_value=getattr(getattr(recommendation, "primary_action", None), "value", None),
            next_action=None if recommendation else "Add pricing safety data, then run recovery recommendation generation.",
        )
        checks["capital_recovery_estimate"] = _check(
            status=DeadStockReadinessStatus.OK if capital else DeadStockReadinessStatus.MISSING,
            reason_code=None if capital else "MISSING_CAPITAL_RECOVERY_ESTIMATE",
            message="Latest capital recovery estimate is available." if capital else "Capital recovery estimate has not been calculated from a safe recovery recommendation.",
            blocking=False,
            current_value=getattr(capital, "gross_recovered_cash", None),
            next_action=None if capital else "Run capital recovery estimator after a safe recommendation exists.",
        )
        needs_recalc = _needs_recalculation(aging=aging, velocity=velocity, assessment=assessment, recommendation=recommendation, capital=capital)
        checks["phase9_pipeline"] = _check(
            status=DeadStockReadinessStatus.PENDING_CALCULATION if needs_recalc else DeadStockReadinessStatus.OK,
            reason_code="PHASE9_RECALCULATION_REQUIRED" if needs_recalc else None,
            message="Run Phase 9 dead stock analysis after source data has been added." if needs_recalc else "Phase 9 records are current for the latest available calculations.",
            blocking=False,
            current_value=None,
            next_action="Run dead stock analysis." if needs_recalc else None,
        )

        can_classify = checks["current_stock"].status == DeadStockReadinessStatus.OK and source_available and checks["sales_history"].status in {DeadStockReadinessStatus.OK, DeadStockReadinessStatus.INSUFFICIENT}
        can_score = assessment is not None
        can_locked = can_classify and has_cost and currency is not None
        can_recommend = bool(assessment and has_cost and has_price and currency and marketplace and fee_policy and pricing_policy)
        can_recover = bool(can_recommend and recommendation)
        ready = can_classify and can_score and can_locked and can_recommend and can_recover
        return DeadStockReadinessResponse(
            product_id=product.id,
            product_name=product.title,
            ready=ready,
            can_classify_dead_stock=can_classify,
            can_score_risk=can_score,
            can_estimate_locked_capital=can_locked,
            can_generate_recovery_recommendation=can_recommend,
            can_estimate_potential_recovery=can_recover,
            checks=checks,
            blocking_reasons=_reasons(checks, blocking=True),
            non_blocking_reasons=_reasons(checks, blocking=False),
            next_actions=_next_actions(product_id=product.id, checks=checks),
            recommended_setup_order=[
                "Add product cost or landed cost.",
                "Add current selling price if missing.",
                "Add inventory receipt, lot, goods-received date, or stock-in transaction.",
                "Import valid completed or fulfilled sales records, or mark the product as never sold if supported.",
                "Set up marketplace fee policy.",
                "Set up pricing policy.",
                "Run Phase 9 dead stock analysis.",
                "Refresh the dashboard.",
            ],
            last_checked_at=now,
        )

    def _product(self, *, seller_id: UUID, product_id: UUID) -> Product | None:
        return self._db.execute(select(Product).where(Product.seller_id == seller_id, Product.id == product_id)).scalar_one_or_none()

    def _latest_aging(self, *, seller_id: UUID, product_id: UUID) -> InventoryAgingSnapshot | None:
        return self._db.execute(
            select(InventoryAgingSnapshot)
            .where(InventoryAgingSnapshot.seller_id == seller_id, InventoryAgingSnapshot.product_id == product_id)
            .order_by(InventoryAgingSnapshot.as_of_date.desc(), InventoryAgingSnapshot.calculated_at.desc(), InventoryAgingSnapshot.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def _first_positive_inventory(self, *, seller_id: UUID, product_id: UUID) -> InventoryHistory | None:
        return self._db.execute(
            select(InventoryHistory)
            .where(InventoryHistory.seller_id == seller_id, InventoryHistory.product_id == product_id, InventoryHistory.quantity_on_hand > 0)
            .order_by(InventoryHistory.snapshot_date.asc(), InventoryHistory.captured_at.asc(), InventoryHistory.id.asc())
            .limit(1)
        ).scalar_one_or_none()

    def _first_stock_in(self, *, seller_id: UUID, product_id: UUID) -> InventoryStockIn | None:
        return self._db.execute(
            select(InventoryStockIn)
            .where(InventoryStockIn.seller_id == seller_id, InventoryStockIn.product_id == product_id)
            .order_by(InventoryStockIn.received_at.asc(), InventoryStockIn.id.asc())
            .limit(1)
        ).scalar_one_or_none()

    def _latest_assessment(self, *, seller_id: UUID, product_id: UUID) -> DeadStockAssessment | None:
        return self._db.execute(
            select(DeadStockAssessment)
            .where(DeadStockAssessment.seller_id == seller_id, DeadStockAssessment.product_id == product_id)
            .order_by(DeadStockAssessment.as_of_date.desc(), DeadStockAssessment.assessed_at.desc(), DeadStockAssessment.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def _latest_velocity(self, *, seller_id: UUID, product_id: UUID) -> SalesVelocity | None:
        return self._db.execute(
            select(SalesVelocity)
            .where(SalesVelocity.seller_id == seller_id, SalesVelocity.product_id == product_id)
            .order_by(SalesVelocity.as_of_date.desc(), SalesVelocity.calculated_at.desc(), SalesVelocity.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def _latest_recommendation(self, *, seller_id: UUID, product_id: UUID) -> DeadStockRecoveryRecommendation | None:
        return self._db.execute(
            select(DeadStockRecoveryRecommendation)
            .where(DeadStockRecoveryRecommendation.seller_id == seller_id, DeadStockRecoveryRecommendation.product_id == product_id)
            .order_by(DeadStockRecoveryRecommendation.generated_at.desc(), DeadStockRecoveryRecommendation.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def _latest_capital(self, *, seller_id: UUID, product_id: UUID) -> DeadStockCapitalRecoveryEstimate | None:
        return self._db.execute(
            select(DeadStockCapitalRecoveryEstimate)
            .where(DeadStockCapitalRecoveryEstimate.seller_id == seller_id, DeadStockCapitalRecoveryEstimate.product_id == product_id)
            .order_by(DeadStockCapitalRecoveryEstimate.calculated_at.desc(), DeadStockCapitalRecoveryEstimate.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def _sales_state(self, *, seller_id: UUID, product_id: UUID) -> dict[str, int]:
        rows = self._db.execute(
            select(
                func.count(SalesRecord.id).label("total_records"),
                func.count(SalesRecord.id)
                .filter(SalesRecord.status.in_(VALID_SALE_STATUSES), SalesRecord.is_test_order.is_(False))
                .label("valid_records"),
            ).where(SalesRecord.seller_id == seller_id, SalesRecord.product_id == product_id)
        ).one()
        return {"total_records": int(rows.total_records or 0), "valid_records": int(rows.valid_records or 0)}

    def _latest_visibility_metric(self, *, seller_id: UUID, product_id: UUID) -> ProductVisibilityMetric | None:
        return self._db.execute(
            select(ProductVisibilityMetric)
            .where(ProductVisibilityMetric.seller_id == seller_id, ProductVisibilityMetric.product_id == product_id)
            .order_by(ProductVisibilityMetric.metric_date.desc(), ProductVisibilityMetric.created_at.desc(), ProductVisibilityMetric.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    @staticmethod
    def _visibility_status(metric: ProductVisibilityMetric | None) -> str | None:
        if metric is None:
            return None
        from app.services.product_visibility_service import ProductVisibilityService

        status, _ = ProductVisibilityService.evaluate(metric)
        return status.value

    def _sales_history_check(self, sales: dict[str, int]) -> DeadStockReadinessCheck:
        if sales["valid_records"] > 0:
            return _check(
                status=DeadStockReadinessStatus.OK,
                reason_code=None,
                message="Completed or fulfilled sales history is available.",
                blocking=False,
                current_value=sales["valid_records"],
            )
        if sales["total_records"] > 0:
            return _check(
                status=DeadStockReadinessStatus.INSUFFICIENT,
                reason_code="NEVER_SOLD",
                message="This product has no completed or fulfilled sales yet.",
                blocking=False,
                current_value=0,
                next_action="Import completed or fulfilled sales records if they exist.",
            )
        return _check(
            status=DeadStockReadinessStatus.MISSING,
            reason_code="MISSING_SALES_HISTORY",
            message="Sales history has not been imported or is insufficient.",
            blocking=False,
            current_value=None,
            next_action="Import completed sales records.",
            href=None,
        )

    def _known_marketplace(self, *, seller_id: UUID, product: Product) -> str | None:
        row = self._db.execute(
            select(MarketplaceFeePolicy.marketplace)
            .where(
                MarketplaceFeePolicy.seller_id == seller_id,
                MarketplaceFeePolicy.is_active.is_(True),
                or_(MarketplaceFeePolicy.product_id == product.id, MarketplaceFeePolicy.product_id.is_(None)),
            )
            .order_by(MarketplaceFeePolicy.product_id.desc().nullslast(), MarketplaceFeePolicy.effective_from.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row:
            return row
        return self._db.execute(
            select(PricingPolicy.marketplace)
            .where(PricingPolicy.seller_id == seller_id, PricingPolicy.product_id == product.id, PricingPolicy.is_active.is_(True))
            .order_by(PricingPolicy.effective_from.desc())
            .limit(1)
        ).scalar_one_or_none()

    def _known_currency(self, *, seller_id: UUID, product: Product, marketplace: str | None) -> str | None:
        currency = self._db.execute(
            select(PricingPolicy.currency)
            .where(PricingPolicy.seller_id == seller_id, PricingPolicy.product_id == product.id, PricingPolicy.is_active.is_(True))
            .order_by(PricingPolicy.effective_from.desc())
            .limit(1)
        ).scalar_one_or_none()
        if currency:
            return currency
        statement = select(MarketplaceFeePolicy.currency).where(MarketplaceFeePolicy.seller_id == seller_id, MarketplaceFeePolicy.is_active.is_(True))
        if marketplace:
            statement = statement.where(MarketplaceFeePolicy.marketplace == marketplace)
        return self._db.execute(statement.order_by(MarketplaceFeePolicy.effective_from.desc()).limit(1)).scalar_one_or_none()

    def _active_fee_policy(self, *, seller_id: UUID, product: Product, marketplace: str | None) -> MarketplaceFeePolicy | None:
        statement = select(MarketplaceFeePolicy).where(MarketplaceFeePolicy.seller_id == seller_id, MarketplaceFeePolicy.is_active.is_(True))
        if marketplace:
            statement = statement.where(MarketplaceFeePolicy.marketplace == marketplace)
        statement = statement.where(
            or_(
                MarketplaceFeePolicy.product_id == product.id,
                MarketplaceFeePolicy.product_id.is_(None) & (MarketplaceFeePolicy.category == product.category),
                MarketplaceFeePolicy.product_id.is_(None) & MarketplaceFeePolicy.category.is_(None),
            )
        )
        return self._db.execute(statement.order_by(MarketplaceFeePolicy.product_id.desc().nullslast(), MarketplaceFeePolicy.category.desc().nullslast(), MarketplaceFeePolicy.effective_from.desc()).limit(1)).scalar_one_or_none()

    def _active_pricing_policy(self, *, seller_id: UUID, product_id: UUID, marketplace: str | None) -> PricingPolicy | None:
        statement = select(PricingPolicy).where(PricingPolicy.seller_id == seller_id, PricingPolicy.product_id == product_id, PricingPolicy.is_active.is_(True))
        if marketplace:
            statement = statement.where(PricingPolicy.marketplace == marketplace)
        return self._db.execute(statement.order_by(PricingPolicy.effective_from.desc()).limit(1)).scalar_one_or_none()


def _check(**kwargs) -> DeadStockReadinessCheck:
    return DeadStockReadinessCheck(**kwargs)


def _decimal(value) -> Decimal:
    return Decimal(str(value))


def _marketplace_for_product(product: Product) -> str | None:
    specs = product.specifications or {}
    for key in ("marketplace", "marketplace_name", "channel"):
        value = specs.get(key)
        if value:
            return str(value)
    return None


def _needs_recalculation(
    *,
    aging: InventoryAgingSnapshot | None,
    velocity: SalesVelocity | None,
    assessment: DeadStockAssessment | None,
    recommendation: DeadStockRecoveryRecommendation | None,
    capital: DeadStockCapitalRecoveryEstimate | None,
) -> bool:
    if aging and assessment is None:
        return True
    if assessment and assessment.calculation_version != settings.dead_stock_formula_version:
        return True
    if assessment and velocity and velocity.calculated_at > assessment.assessed_at:
        return True
    if assessment and recommendation is None:
        return True
    if recommendation and capital is None:
        return True
    if recommendation and capital and recommendation.generated_at > capital.calculated_at:
        return True
    return False


def _reasons(checks: dict[str, DeadStockReadinessCheck], *, blocking: bool) -> list[str]:
    return [
        check.reason_code
        for check in checks.values()
        if check.reason_code and check.blocking is blocking
    ]


def _next_actions(*, product_id: UUID, checks: dict[str, DeadStockReadinessCheck]) -> list[DeadStockReadinessNextAction]:
    actions: list[DeadStockReadinessNextAction] = []
    if checks["product_cost"].reason_code or checks["selling_price"].reason_code:
        actions.append(DeadStockReadinessNextAction(key="add_product_cost", label="Add product cost", description="Required to calculate locked capital and safe recovery pricing.", href=f"/app/products/{product_id}/edit", implemented=True, priority=1))
    if checks["inventory_age_source"].reason_code:
        actions.append(DeadStockReadinessNextAction(key="add_inventory_receipt", label="Add inventory receipt", description="Required to calculate inventory age.", href=f"/app/inventory/receipts/new?productId={product_id}", implemented=True, priority=2))
    if checks["marketplace_fee_policy"].reason_code:
        actions.append(DeadStockReadinessNextAction(key="set_up_marketplace_fees", label="Set up marketplace fees", description="Required before discount recovery can be estimated safely.", href=f"/app/pricing/fee-setup?productId={product_id}", implemented=True, priority=3))
    if checks["pricing_policy"].reason_code:
        actions.append(DeadStockReadinessNextAction(key="set_up_pricing_policy", label="Set up pricing policy", description="Required to enforce minimum margin and discount limits.", href=f"/app/pricing/policy-setup?productId={product_id}", implemented=True, priority=4))
    if checks["sales_history"].reason_code == "MISSING_SALES_HISTORY":
        actions.append(DeadStockReadinessNextAction(key="import_sales_records", label="Import sales records", description="Needed to calculate last sale, velocity, and demand confidence.", href=f"/app/sales/import?productId={product_id}", implemented=True, priority=5))
    if checks["phase9_pipeline"].reason_code or checks["dead_stock_assessment"].reason_code:
        actions.append(DeadStockReadinessNextAction(key="run_dead_stock_analysis", label="Run dead stock analysis", description="Run after required source data has been added.", href=None, implemented=True, priority=6))
    if checks["visibility_data"].reason_code:
        actions.append(DeadStockReadinessNextAction(key="add_visibility_metrics", label="Add visibility metrics", description="Optional. Required only for SEO recovery recommendations.", href=f"/app/products/{product_id}/visibility", implemented=True, priority=7))
    return sorted(actions, key=lambda item: item.priority)
