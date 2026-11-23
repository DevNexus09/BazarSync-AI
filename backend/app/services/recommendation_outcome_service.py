"""Evaluate acted-on recommendations and report the track record (Phase 6). Seller-scoped throughout."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.dynamic_pricing_recommendation import DynamicPricingRecommendation, DynamicPricingRecommendationStatus
from app.models.inventory_history import InventoryHistory
from app.models.pricing_analytics_snapshot import PricingAnalyticsSnapshot
from app.models.product import Product
from app.models.recommendation_outcome import (
    RecommendationOutcome,
    RecommendationOutcomeStatus,
    RecommendationOutcomeType,
)
from app.models.reorder_recommendation import ReorderRecommendation, ReorderRecommendationStatus
from app.models.sales_record import SalesRecord, SalesRecordStatus
from app.services.recommendation_outcomes import (
    OUTCOME_VERSION,
    OutcomeResult,
    SaleLine,
    evaluate_price_change,
    evaluate_reorder,
    reorder_window_days,
    track_record,
)

VALID_STATUSES = (SalesRecordStatus.COMPLETED, SalesRecordStatus.FULFILLED)


class RecommendationOutcomeService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def evaluate_seller(self, *, seller_id: UUID, now: datetime | None = None) -> dict[str, int]:
        """Record outcomes whose window has fully passed. Re-running is a no-op (unique per recommendation and window)."""
        timestamp = now or datetime.now(timezone.utc)
        window = settings.recommendation_outcome_window_days
        oldest = timestamp - timedelta(days=settings.recommendation_outcome_lookback_days)
        counts = {"pricing": 0, "reorder": 0}

        pricing = self._db.execute(
            select(DynamicPricingRecommendation).where(
                DynamicPricingRecommendation.seller_id == seller_id,
                DynamicPricingRecommendation.recommendation_status == DynamicPricingRecommendationStatus.ACKNOWLEDGED,
                DynamicPricingRecommendation.acknowledged_at.is_not(None),
                DynamicPricingRecommendation.acknowledged_at >= oldest,
                DynamicPricingRecommendation.acknowledged_at <= timestamp - timedelta(days=window),
                ~self._already_evaluated(DynamicPricingRecommendation.id, window),
            )
        ).scalars().all()
        for rec in pricing:
            assert rec.acknowledged_at is not None
            decided = rec.acknowledged_at.date()
            result = self._evaluate_pricing(rec, decided, window)
            counts["pricing"] += self._save(RecommendationOutcomeType.PRICING, rec.seller_id, rec.product_id, rec.id, rec.acknowledged_at, decided, window, timestamp, result, rec.confidence_score, rec.formula_version, {})

        decided_column = func.coalesce(ReorderRecommendation.ordered_at, ReorderRecommendation.updated_at)
        reorders = self._db.execute(
            select(ReorderRecommendation).where(
                ReorderRecommendation.seller_id == seller_id,
                ReorderRecommendation.recommendation_status == ReorderRecommendationStatus.ORDERED,
                decided_column >= oldest,
                decided_column <= timestamp - timedelta(days=window),
            )
        ).scalars().all()
        for order in reorders:
            decided_at = order.ordered_at or order.updated_at
            days = reorder_window_days(window, order.supplier_lead_time_days, order.safety_buffer_days)
            if decided_at > timestamp - timedelta(days=days) or self._exists(order.id, days):
                continue
            decided = decided_at.date()
            units, available = self._daily(order.seller_id, order.product_id, decided, decided + timedelta(days=days - 1))
            result = evaluate_reorder(
                decided_on=decided,
                window_days=days,
                daily_sales_rate=Decimal(order.daily_sales_rate),
                reorder_deadline=order.reorder_deadline,
                units_by_day=units,
                available_by_day=available,
            )
            source: dict[str, object] = {"decided_at_source": "ordered_at" if order.ordered_at else "updated_at"}
            counts["reorder"] += self._save(RecommendationOutcomeType.REORDER, order.seller_id, order.product_id, order.id, decided_at, decided, days, timestamp, result, order.confidence_score, order.calculation_version, source)
        self._db.commit()
        return counts

    def track_record(self, *, seller_id: UUID, recommendation_type: RecommendationOutcomeType, now: datetime | None = None) -> dict[str, object]:
        since = (now or datetime.now(timezone.utc)) - timedelta(days=settings.recommendation_track_record_days)
        rows = self._db.execute(
            select(RecommendationOutcome.hit, RecommendationOutcome.confidence_score).where(
                RecommendationOutcome.seller_id == seller_id,
                RecommendationOutcome.recommendation_type == recommendation_type,
                RecommendationOutcome.observed_status == RecommendationOutcomeStatus.OBSERVED,
                RecommendationOutcome.evaluated_at >= since,
            )
        ).all()
        return {
            "recommendation_type": recommendation_type.value,
            "days": settings.recommendation_track_record_days,
            **track_record([(row.hit, row.confidence_score) for row in rows], min_outcomes=settings.recommendation_track_record_min_outcomes),
        }

    def _evaluate_pricing(self, rec: DynamicPricingRecommendation, decided: date, window: int) -> OutcomeResult:
        snapshot = self._db.get(PricingAnalyticsSnapshot, rec.pricing_analytics_id)
        product = self._db.execute(
            select(Product).where(Product.seller_id == rec.seller_id, Product.id == rec.product_id)
        ).scalar_one_or_none()
        if snapshot is None or snapshot.seller_id != rec.seller_id or product is None:
            return OutcomeResult(False, None, None, None, {"unavailable_reason": "pricing_inputs_missing"})
        return evaluate_price_change(
            before=self._lines(rec.seller_id, rec.product_id, decided - timedelta(days=window), decided - timedelta(days=1)),
            after=self._lines(rec.seller_id, rec.product_id, decided, decided + timedelta(days=window - 1)),
            recommended_price=Decimal(rec.recommended_price),
            current_price=Decimal(rec.current_price),
            unit_cost=Decimal(product.cost_price),
            percentage_fee_rate=Decimal(snapshot.percentage_fee_rate),
            fixed_fee_amount=Decimal(snapshot.fixed_fee_amount),
            predicted_profit_impact=Decimal(rec.profit_impact) if rec.profit_impact is not None else None,
            window_days=window,
        )

    def _lines(self, seller_id: UUID, product_id: UUID, start: date, end: date) -> list[SaleLine]:
        day = func.date(SalesRecord.sold_at)
        rows = self._db.execute(
            select(day.label("day"), SalesRecord.unit_price, SalesRecord.quantity_sold, SalesRecord.returned_units, SalesRecord.refunded_restocked_units).where(
                SalesRecord.seller_id == seller_id,
                SalesRecord.product_id == product_id,
                SalesRecord.status.in_(VALID_STATUSES),
                SalesRecord.is_test_order.is_(False),
                day >= start,
                day <= end,
            )
        ).all()
        return [
            SaleLine(row.day, Decimal(row.unit_price) if row.unit_price is not None else None, max(0, row.quantity_sold - row.returned_units - row.refunded_restocked_units))
            for row in rows
        ]

    def _daily(self, seller_id: UUID, product_id: UUID, start: date, end: date) -> tuple[dict[date, int], dict[date, int]]:
        units: dict[date, int] = {}
        for line in self._lines(seller_id, product_id, start, end):
            units[line.day] = units.get(line.day, 0) + line.net_units
        stock = self._db.execute(
            select(InventoryHistory.snapshot_date, InventoryHistory.quantity_available).where(
                InventoryHistory.seller_id == seller_id,
                InventoryHistory.product_id == product_id,
                InventoryHistory.snapshot_date >= start,
                InventoryHistory.snapshot_date <= end,
            )
        ).all()
        return units, {row.snapshot_date: int(row.quantity_available) for row in stock}

    def _already_evaluated(self, id_column, window: int):
        return (
            select(RecommendationOutcome.id)
            .where(RecommendationOutcome.recommendation_id == id_column, RecommendationOutcome.window_days == window)
            .exists()
        )

    def _exists(self, recommendation_id: UUID, window: int) -> bool:
        return self._db.execute(
            select(RecommendationOutcome.id).where(
                RecommendationOutcome.recommendation_id == recommendation_id, RecommendationOutcome.window_days == window
            )
        ).first() is not None

    def _save(
        self,
        kind: RecommendationOutcomeType,
        seller_id: UUID,
        product_id: UUID,
        recommendation_id: UUID,
        decided_at: datetime,
        window_start: date,
        window_days: int,
        evaluated_at: datetime,
        result: OutcomeResult,
        confidence: Decimal | None,
        recommendation_version: str,
        extra: dict[str, object],
    ) -> int:
        statement = (
            insert(RecommendationOutcome)
            .values(
                seller_id=seller_id,
                product_id=product_id,
                recommendation_type=kind,
                recommendation_id=recommendation_id,
                decided_at=decided_at,
                window_start=window_start,
                window_days=window_days,
                evaluated_at=evaluated_at,
                predicted_value=result.predicted_value,
                observed_value=result.observed_value,
                observed_status=RecommendationOutcomeStatus.OBSERVED if result.observed else RecommendationOutcomeStatus.UNAVAILABLE,
                hit=result.hit,
                confidence_score=confidence,
                calculation_version=OUTCOME_VERSION,
                details={**result.details, **extra, "recommendation_version": recommendation_version},
            )
            # Redelivery or a concurrent run must not create a second outcome.
            .on_conflict_do_nothing(constraint="uq_recommendation_outcomes_recommendation_window")
        )
        inserted = self._db.execute(statement)
        return int(getattr(inserted, "rowcount", 0) or 0)
