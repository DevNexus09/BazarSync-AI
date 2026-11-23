"""Offline fit and lookup for category-pooled elasticity (Phase 5.1).

Training runs only from the Celery task, never in a request handler. Requests
read the stored estimate through ``latest_pooled_estimate``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import String, cast, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.demand_elasticity_estimate import (
    DemandElasticityEstimate,
    DemandEstimateDataStatus,
    DemandEstimationMethod,
)
from app.models.inventory_history import InventoryHistory
from app.models.product import Product
from app.models.promotion import PromotionPlan
from app.models.sales_record import SalesRecord
from app.services.demand_response_service import (
    VALID_DEMAND_STATUSES,
    DemandElasticityResult,
    DemandResponseService,
)
from app.services.pooled_elasticity import (
    POOLED_VERSION,
    DailyPoint,
    PooledConfig,
    build_daily_panel,
    fit_category,
    censored_days,
)

UNCATEGORISED = "__uncategorised__"


def pooled_config() -> PooledConfig:
    return PooledConfig(
        zero_unit_adjustment=Decimal(str(settings.demand_response_zero_unit_adjustment)),
        min_elasticity=Decimal(str(settings.demand_response_min_elasticity)),
        max_elasticity=Decimal(str(settings.demand_response_max_elasticity)),
        pooling_strength=settings.demand_response_pooling_strength,
        min_product_days=settings.demand_response_min_observations,
        min_price_variation_rate=Decimal(str(settings.demand_response_min_price_variation_rate)),
        holdout_days=settings.demand_response_pooling_holdout_days,
        min_holdout_days=settings.demand_response_pooling_min_holdout_days,
        min_improvement_rate=Decimal(str(settings.demand_response_pooling_min_improvement_rate)),
    )


class PooledElasticityService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._config = pooled_config()

    def fit_for_seller(self, *, seller_id: UUID, as_of_date: date, window_days: int) -> dict[str, int]:
        """Fit every category of one seller and persist one estimate per product. Idempotent per day."""
        start = as_of_date - timedelta(days=window_days)
        products = self._db.execute(
            select(Product.id, Product.category).where(Product.seller_id == seller_id)
        ).all()
        categories: dict[str, list[UUID]] = {}
        for product_id, category in products:
            categories.setdefault((category or "").strip().lower() or UNCATEGORISED, []).append(product_id)
        panel = self._daily_panel(seller_id=seller_id, start=start, end=as_of_date)
        estimator = DemandResponseService(self._db)
        persisted = categories_fitted = 0
        for category, product_ids in categories.items():
            members = set(product_ids)
            result = fit_category([point for point in panel if point.product_id in members], self._config)
            if result.fit is None:
                continue
            categories_fitted += 1
            for estimate in result.products:
                estimator.persist_estimate(
                    seller_id=seller_id,
                    product_id=estimate.product_id,
                    estimate=DemandElasticityResult(
                        method=DemandEstimationMethod.POOLED_CATEGORY,
                        elasticity=estimate.elasticity,
                        sample_count=estimate.observation_count,
                        baseline_units=estimate.baseline_units,
                        observation_start=estimate.observation_start,
                        observation_end=estimate.observation_end,
                        price_range=None,
                        quality_metrics={
                            "category": None if category == UNCATEGORISED else category,
                            "category_elasticity": round(result.fit.elasticity, 6),
                            "category_observations": result.fit.observation_count,
                            "category_products": result.fit.product_count,
                            "category_r_squared": round(result.fit.r_squared, 4),
                            "own_elasticity": str(estimate.own_elasticity) if estimate.own_elasticity is not None else None,
                            "shrink_weight": str(estimate.shrink_weight),
                            "pooling_strength": self._config.pooling_strength,
                            "controls": ["product_fixed_effect", "weekday", "promotion"],
                            "stockout_days_excluded": True,
                            "out_of_time": result.out_of_time,
                            **estimate.metrics,
                        },
                        confidence=_confidence(estimate.observation_count, result.fit.r_squared, bool(result.out_of_time.get("passed"))),
                        data_status=DemandEstimateDataStatus.SUFFICIENT if estimate.own_elasticity is not None else DemandEstimateDataStatus.LIMITED,
                        calculation_version=POOLED_VERSION,
                        evidence={},
                    ),
                )
                persisted += 1
        return {"products": len(products), "categories_fitted": categories_fitted, "estimates": persisted}

    def _daily_panel(self, *, seller_id: UUID, start: date, end: date) -> list[DailyPoint]:
        window_start = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
        window_end = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        sales = self._db.execute(
            select(
                SalesRecord.product_id,
                SalesRecord.sold_at,
                SalesRecord.unit_price,
                SalesRecord.quantity_sold,
                SalesRecord.returned_units,
                SalesRecord.refunded_restocked_units,
            ).where(
                SalesRecord.seller_id == seller_id,
                SalesRecord.status.in_(VALID_DEMAND_STATUSES),
                SalesRecord.is_test_order.is_(False),
                SalesRecord.unit_price.is_not(None),
                SalesRecord.sold_at >= window_start,
                SalesRecord.sold_at < window_end,
            )
        ).all()
        promotions = self._db.execute(
            select(PromotionPlan.product_id, PromotionPlan.planned_start_at, PromotionPlan.planned_end_at).where(
                PromotionPlan.seller_id == seller_id,
                PromotionPlan.planned_start_at.is_not(None),
                PromotionPlan.planned_start_at < window_end,
                PromotionPlan.planned_end_at.is_(None) | (PromotionPlan.planned_end_at >= window_start),
            )
        ).all()
        stock_rows = self._db.execute(
            select(InventoryHistory.product_id, InventoryHistory.snapshot_date, InventoryHistory.quantity_available).where(
                InventoryHistory.seller_id == seller_id,
                InventoryHistory.snapshot_date >= start,
                InventoryHistory.snapshot_date <= end,
            )
        ).all()
        available: dict[UUID, dict[date, int]] = {}
        for product_id, snapshot_date, quantity in stock_rows:
            available.setdefault(product_id, {})[snapshot_date] = int(quantity)

        def promoted(product_id: UUID, sold_at: datetime) -> bool:
            return any(
                row.product_id == product_id and row.planned_start_at <= sold_at and (row.planned_end_at is None or sold_at <= row.planned_end_at)
                for row in promotions
            )

        return build_daily_panel(
            [
                (
                    row.product_id,
                    row.sold_at.date(),
                    Decimal(row.unit_price),
                    max(0, row.quantity_sold - row.returned_units - row.refunded_restocked_units),
                    promoted(row.product_id, row.sold_at),
                )
                for row in sales
            ],
            {product_id: censored_days(days) for product_id, days in available.items()},
        )


def latest_pooled_estimate(db: Session, *, seller_id: UUID, product_id: UUID, as_of_date: date) -> DemandElasticityEstimate | None:
    """Freshest stored pooled estimate for this seller's product, or None when stale or absent."""
    oldest = as_of_date - timedelta(days=settings.demand_response_max_data_age_days)
    return db.execute(
        select(DemandElasticityEstimate)
        .where(
            DemandElasticityEstimate.seller_id == seller_id,
            DemandElasticityEstimate.product_id == product_id,
            # Text comparison: safe even before the migration adds the enum value.
            cast(DemandElasticityEstimate.estimation_method, String) == DemandEstimationMethod.POOLED_CATEGORY.value,
            DemandElasticityEstimate.observation_end >= oldest,
            DemandElasticityEstimate.observation_end <= as_of_date,
        )
        .order_by(DemandElasticityEstimate.calculated_at.desc(), DemandElasticityEstimate.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def out_of_time_passed(record: DemandElasticityEstimate | None) -> bool:
    metrics = (record.quality_metrics or {}) if record is not None else {}
    evaluation = metrics.get("out_of_time")
    return isinstance(evaluation, dict) and evaluation.get("passed") is True


def _confidence(observations: int, r_squared: float, validated: bool) -> Decimal:
    score = Decimal("40") + min(Decimal("30"), Decimal(observations)) + Decimal(str(max(0.0, r_squared))) * Decimal("10")
    if validated:
        score += Decimal("10")
    return min(Decimal("90"), score).quantize(Decimal("0.01"))
