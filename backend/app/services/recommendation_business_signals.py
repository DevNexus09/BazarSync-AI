from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from statistics import median
from typing import Any, Mapping, Sequence

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.analytics.metrics import (
    PricingConfig,
    compute_availability_counts,
    score_pricing_pressure,
    score_stock_risk,
)
from app.core.config import settings
from app.models.inventory_history import InventoryHistory
from app.models.product import Product
from app.models.seller import Seller
from app.models.reorder_recommendation import ReorderRecommendationAction
from app.models.sales_data_coverage import (
    SalesDataCompletenessStatus,
    SalesDataCoverage,
)
from app.models.sales_velocity import SalesVelocityDataStatus
from app.repositories.reorder_recommendation_repository import (
    ReorderRecommendationRepository,
)
from app.schemas.recommendation_decision import DemandStatus
from app.scraper.constants import MARKETPLACE_NAME
from app.services.margin_guard import (
    MarginGuard,
    MarginGuardRejectionReason,
    MarginGuardResult,
)
from app.services.pricing_calculator import PricingCalculator
from app.services.reorder_recommendation_service import ReorderRecommendationService
from app.services.sales_velocity_service import (
    SalesVelocityCalculation,
    SalesVelocityService,
)


@dataclass(frozen=True)
class DemandInventoryEvidence:
    seller: Seller
    business_date: date
    velocity: SalesVelocityCalculation
    coverage: SalesDataCoverage | None
    demand_status: DemandStatus
    rate: Decimal | None
    inventory: InventoryHistory | None
    available_units: int | None
    lead_time: int | None
    days_left: Decimal | None
    reason_codes: tuple[str, ...]

    @property
    def stock_risk(self) -> float | None:
        if self.days_left is None or self.lead_time is None:
            return None
        return score_stock_risk(
            float(self.days_left),
            self.lead_time,
            PricingConfig().low_stock_days_threshold,
        )

    def to_context(self) -> dict[str, Any]:
        velocity, inventory = self.velocity, self.inventory
        valid_records = velocity.metadata.get("valid_sales_records", 0)
        observed = valid_records or self.demand_status == "OBSERVED"
        return {
            "demand_status": self.demand_status,
            "daily_net_sales_rate": str(self.rate) if self.rate is not None else None,
            "recorded_net_units": velocity.net_units_sold if observed else None,
            "recorded_gross_units": velocity.gross_units_sold if observed else None,
            "recorded_returns": velocity.returned_units if observed else None,
            "valid_sales_records": valid_records,
            "sales_days": velocity.sales_days,
            "window_days": velocity.window_days,
            "through": velocity.as_of_date.isoformat(),
            "velocity_version": velocity.calculation_version,
            "coverage_id": str(self.coverage.id) if self.coverage else None,
            "inventory_snapshot_id": str(inventory.id)
            if inventory is not None
            else None,
            "inventory_captured_at": inventory.captured_at.isoformat()
            if inventory is not None
            else None,
            "available_units": self.available_units,
            "on_hand_units": inventory.quantity_on_hand
            if inventory is not None
            else None,
            "supplier_lead_time_days": self.lead_time,
        }


class RecommendationBusinessSignals:
    """Measure seller demand and evaluate advisory price candidates without writing records."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self._guard = MarginGuard(db)

    def analyze(
        self,
        product: Product,
        competitors: Sequence[Mapping[str, Any]],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        evaluated_at = now or datetime.now(timezone.utc)
        measured = self.measure_inventory(product, evaluated_at)
        seller, business_date, velocity = (
            measured.seller,
            measured.business_date,
            measured.velocity,
        )
        inventory, lead = measured.inventory, measured.lead_time
        lead_known = lead is not None
        days_left = measured.days_left
        risk = measured.stock_risk
        reasons = list(measured.reason_codes)
        config = PricingConfig()

        action = "HOLD"
        confidence = 0.0
        reorder = None
        if days_left is not None and lead_known:
            reorder = ReorderRecommendationService(self._db).build_recommendation(
                product=product,
                seller=seller,
                inventory_snapshot=inventory,
                sales_velocity=velocity,
                stockout_prediction=None,
                as_of_date=business_date,
                generated_at=evaluated_at,
                calculation_version=settings.reorder_calculation_version,
            )
            if reorder.action == ReorderRecommendationAction.REORDER:
                action = "REORDER"
                confidence = float(reorder.confidence_score / Decimal(100))
                reasons.append("REORDER_ENGINE_RECOMMENDS_REPLENISHMENT")
            elif reorder.evidence["insufficient_reason"]:
                reasons.append("REORDER_ENGINE_INSUFFICIENT_EVIDENCE")

        prices = [Decimal(str(row["price"])) for row in competitors]
        midpoint = median(prices) if prices else None
        current = product.selling_price
        price_known = current is not None and current.is_finite() and current > 0
        gap = (
            (current - midpoint) / midpoint * Decimal(100)
            if price_known and midpoint is not None
            else None
        )
        counts = compute_availability_counts(
            row.get("stock_status") for row in competitors
        )
        if not counts["total"]:
            reasons.append("COMPETITOR_AVAILABILITY_UNKNOWN")
        pressure = score_pricing_pressure(
            float(gap) if gap is not None else None,
            config.pricing_pressure_reference_percent,
        )

        baseline = None
        if price_known:
            baseline = self._guard.validate_candidate(
                seller_id=product.seller_id,
                product=product,
                candidate_price=current,
                marketplace=MARKETPLACE_NAME,
            )
            reasons.extend(reason.value for reason in baseline.rejection_reasons)
        else:
            reasons.append("MISSING_OR_INVALID_CURRENT_PRICE")
        candidate = None
        if (
            action == "HOLD"
            and days_left is not None
            and lead_known
            and reorder is not None
            and not reorder.evidence["insufficient_reason"]
            and len(prices) >= config.min_competitor_count
            and midpoint is not None
            and gap is not None
            and gap >= Decimal(str(config.price_undercut_threshold_percent))
        ):
            candidate = self._guard.validate_candidate(
                seller_id=product.seller_id,
                product=product,
                candidate_price=midpoint,
                marketplace=MARKETPLACE_NAME,
                round_down_to_increment=True,
            )
            if candidate.is_allowed and 0 < candidate.candidate_price < current:
                action, confidence = "LOWER", pressure
                reasons.append("COMPETITOR_MEDIAN_LOWER")
            else:
                reasons.append("MARGIN_GUARD_BLOCKED_PRICE_RECOMMENDATION")
                reasons.extend(reason.value for reason in candidate.rejection_reasons)
        if not reasons:
            reasons.append("NO_ACTIONABLE_CHANGE")

        return {
            "business_signals_version": 1,
            "action": action,
            "confidence": round(confidence, 2),
            **(
                {"action_signal_strength": confidence}
                if settings.recommendation_validation_enabled
                else {}
            ),
            "reason_codes": list(dict.fromkeys(reasons)),
            "competitor_median_price": str(midpoint) if midpoint is not None else None,
            "price_gap_percent": float(gap) if gap is not None else None,
            "pricing_pressure_score": round(pressure, 2),
            "competitor_availability_ratio": float(counts["ratio"])
            if counts["total"]
            else None,
            "out_of_stock_competitor_count": int(counts["out_of_stock"])
            if counts["total"]
            else None,
            "estimated_days_of_stock_left": round(float(days_left), 2)
            if days_left is not None
            else None,
            "stock_risk_score": round(risk, 2) if risk is not None else None,
            "urgency_score": round(risk, 2) if risk is not None else None,
            "candidate_price": str(candidate.candidate_price)
            if action == "LOWER" and candidate
            else None,
            "pricing_evidence": {
                "marketplace": MARKETPLACE_NAME,
                "current_offer": _economics(baseline) if baseline else None,
                "candidate_offer": _economics(candidate) if candidate else None,
                "candidate_guard": candidate.to_evidence() if candidate else None,
            },
            "inventory_evidence": {
                **measured.to_context(),
                "reorder": {
                    **reorder.evidence,
                    "dedicated_action": reorder.action.value,
                    "recommended_quantity": reorder.recommended_quantity,
                }
                if reorder is not None
                else None,
            },
        }

    def measure_inventory(
        self,
        product: Product,
        evaluated_at: datetime,
    ) -> DemandInventoryEvidence:
        seller = product.seller
        business_date = SalesVelocityService.business_date_for_seller(
            seller, evaluated_at
        )
        # A partial current day would dilute the rate.
        through = business_date - timedelta(days=1)
        velocity = SalesVelocityService(self._db).measure_for_product(
            product=product,
            seller=seller,
            as_of_date=through,
            calculated_at=evaluated_at,
        )
        coverage = self._sales_window_coverage(
            product,
            through,
            velocity.window_days,
            evaluated_at,
        )
        valid_records = velocity.metadata.get("valid_sales_records", 0)
        enough_samples = (
            velocity.data_status == SalesVelocityDataStatus.SUFFICIENT
            and velocity.sales_days >= 3
            and velocity.confidence_score
            >= Decimal(str(settings.reorder_minimum_velocity_confidence))
        )
        complete = (
            coverage is not None
            and coverage.completeness_status == SalesDataCompletenessStatus.COMPLETE
            and velocity.observed_days == velocity.window_days
        )
        demand_status: DemandStatus
        if complete:
            demand_status = "OBSERVED"
            rate = velocity.daily_sales_rate
        elif enough_samples and velocity.daily_sales_rate > 0:
            demand_status = "ESTIMATED_FROM_RECORDED_SALES"
            rate = velocity.daily_sales_rate
        else:
            demand_status = "INSUFFICIENT"
            rate = None

        inventory = self.current_inventory(product, business_date, evaluated_at)
        available = (
            max(0, inventory.quantity_available) if inventory is not None else None
        )
        lead = product.supplier_lead_time
        lead_known = lead is not None and lead > 0
        days_left = (
            Decimal(available) / rate
            if available is not None and rate is not None and rate > 0
            else None
        )
        reasons = []
        if rate is None:
            reasons.append(
                "INSUFFICIENT_SALES_HISTORY"
                if not valid_records
                else "SPARSE_OR_INCOMPLETE_SALES_HISTORY"
            )
        elif rate == 0:
            reasons.append("ZERO_NET_SALES_IN_COVERED_WINDOW")
        if inventory is None:
            reasons.append("MISSING_OR_STALE_INVENTORY_SNAPSHOT")
        if not lead_known:
            reasons.append("MISSING_SUPPLIER_LEAD_TIME")

        return DemandInventoryEvidence(
            seller=seller,
            business_date=business_date,
            velocity=velocity,
            coverage=coverage,
            demand_status=demand_status,
            rate=rate,
            inventory=inventory,
            available_units=available,
            lead_time=lead if lead_known else None,
            days_left=days_left,
            reason_codes=tuple(reasons),
        )

    def current_inventory(
        self,
        product: Product,
        business_date: date,
        evaluated_at: datetime,
        *,
        refresh: bool = False,
    ) -> InventoryHistory | None:
        inventory = (
            ReorderRecommendationRepository(self._db)
            .latest_inventory_for_products(
                seller_id=product.seller_id,
                product_ids=[product.id],
                as_of_date=business_date,
                refresh=refresh,
            )
            .get(product.id)
        )
        if inventory is not None and (
            inventory.captured_at.utcoffset() is None
            or not timedelta(0)
            <= evaluated_at - inventory.captured_at
            <= timedelta(hours=settings.recommendation_inventory_max_age_hours)
            or inventory.quantity_on_hand != product.stock_quantity
        ):
            inventory = None
        return inventory

    def _sales_window_coverage(
        self,
        product: Product,
        through: date,
        window_days: int,
        evaluated_at: datetime,
    ) -> SalesDataCoverage | None:
        # Product-specific coverage avoids treating multi-product imports as
        # proof that every product was observed.
        return self._db.scalars(
            select(SalesDataCoverage)
            .where(
                SalesDataCoverage.seller_id == product.seller_id,
                SalesDataCoverage.product_id == product.id,
                or_(
                    SalesDataCoverage.marketplace.is_(None),
                    SalesDataCoverage.marketplace == MARKETPLACE_NAME,
                ),
                SalesDataCoverage.coverage_start_date
                <= through - timedelta(days=window_days - 1),
                SalesDataCoverage.coverage_end_date >= through,
                SalesDataCoverage.last_imported_at <= evaluated_at,
            )
            .order_by(
                SalesDataCoverage.last_imported_at.desc(), SalesDataCoverage.id.desc()
            )
            .limit(1)
        ).first()


def _economics(result: MarginGuardResult) -> dict[str, Any]:
    price = result.candidate_price
    cost = result.unit_cost
    calculator = PricingCalculator()
    if MarginGuardRejectionReason.UNSUPPORTED_CURRENCY in result.rejection_reasons:
        return {
            "gross_revenue_per_unit": None,
            "gross_margin_per_unit": None,
            "contribution_margin_per_unit": None,
            "contribution_margin_rate": None,
            "estimated_profit": None,
            "currency": None,
            "fee_policy_version": None,
        }
    gross = calculator.round_currency(price - cost) if cost is not None else None
    contribution = result.unit_profit
    if set(result.rejection_reasons) & {
        MarginGuardRejectionReason.MISSING_FEE_DATA,
        MarginGuardRejectionReason.INVALID_POLICY,
        MarginGuardRejectionReason.UNSUPPORTED_CURRENCY,
        MarginGuardRejectionReason.MISSING_COST_DATA,
    }:
        contribution = None
    return {
        "gross_revenue_per_unit": str(price),
        "gross_margin_per_unit": str(gross) if gross is not None else None,
        "contribution_margin_per_unit": str(contribution)
        if contribution is not None
        else None,
        "contribution_margin_rate": str(result.margin_rate)
        if contribution is not None
        else None,
        "estimated_profit": None,
        "currency": "BDT",
        "fee_policy_version": result.policy_version,
    }
