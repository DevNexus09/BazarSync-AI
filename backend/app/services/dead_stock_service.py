from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import logging
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.dead_stock_assessment import (
    DeadStockAssessment,
    DeadStockClassification,
    DeadStockDataStatus,
    DeadStockInventoryAgeState,
    DeadStockNoSalesState,
    DeadStockRiskLevel,
    DeadStockVisibilityStatus,
)
from app.models.inventory_aging import InventoryAgeSource, InventoryAgingSnapshot
from app.models.product import Product
from app.models.sales_velocity import SalesVelocity, SalesVelocityDataStatus
from app.models.seller import Seller
from app.repositories.dead_stock_repository import DeadStockRepository

logger = logging.getLogger(__name__)


class DeadStockRepositoryProtocol(Protocol):
    def iter_product_batches(self, *, batch_size: int, seller_id: UUID | None = None, product_id: UUID | None = None): ...
    def latest_aging_for_products(self, *, seller_id: UUID, product_ids: list[UUID], as_of_date: date) -> dict[UUID, InventoryAgingSnapshot]: ...
    def latest_velocity_for_products(self, *, seller_id: UUID, product_ids: list[UUID], as_of_date: date) -> dict[UUID, SalesVelocity]: ...
    def sales_summaries_for_products(self, *, seller_id: UUID, product_ids: list[UUID]) -> dict[UUID, dict] | None: ...
    def visibility_for_products(self, *, seller_id: UUID, product_ids: list[UUID], as_of_date: date) -> dict[UUID, dict]: ...
    def add_idempotent(self, assessment: DeadStockAssessment) -> tuple[DeadStockAssessment, bool]: ...
    def latest(self, *, seller_id: UUID, product_id: UUID, calculation_version: str | None) -> DeadStockAssessment | None: ...
    def history(self, *, seller_id: UUID, product_id: UUID, from_date: date | None, to_date: date | None, calculation_version: str | None, order: str, limit: int, offset: int) -> tuple[list[DeadStockAssessment], int]: ...
    def list_assessments(self, **kwargs) -> tuple[list[DeadStockAssessment], int]: ...


@dataclass(frozen=True)
class DeadStockBatchResult:
    created_count: int
    skipped_count: int
    failed_count: int
    insufficient_data_count: int
    dead_stock_count: int


class DeadStockService:
    def __init__(
        self,
        db: Session | None = None,
        *,
        repository: DeadStockRepositoryProtocol | None = None,
        calculation_version: str | None = None,
        log: logging.Logger | None = None,
    ) -> None:
        if repository is None and db is None:
            raise ValueError("Either db or repository is required.")
        self._repository = repository or DeadStockRepository(db)  # type: ignore[arg-type]
        self._calculation_version = calculation_version or settings.dead_stock_calculation_version
        self._log = log or logger

    def assess_for_product(
        self,
        *,
        product: Product,
        seller: Seller,
        inventory_aging: InventoryAgingSnapshot | None,
        sales_velocity: SalesVelocity | None,
        sales_summary: dict | None,
        visibility: dict | None,
        as_of_date: date,
        assessed_at: datetime | None = None,
    ) -> tuple[DeadStockAssessment, bool]:
        assessment = self.build_assessment(
            product=product,
            seller=seller,
            inventory_aging=inventory_aging,
            sales_velocity=sales_velocity,
            sales_summary=sales_summary,
            visibility=visibility,
            as_of_date=as_of_date,
            assessed_at=_ensure_utc(assessed_at or datetime.now(timezone.utc)),
        )
        return self._repository.add_idempotent(assessment)

    def assess_batch(
        self,
        *,
        batch_size: int = 500,
        as_of_date: date | None = None,
        assessed_at: datetime | None = None,
        seller_id: UUID | None = None,
        product_id: UUID | None = None,
    ) -> DeadStockBatchResult:
        timestamp = _ensure_utc(assessed_at or datetime.now(timezone.utc))
        created = skipped = failed = insufficient = dead_stock = 0
        for batch in self._repository.iter_product_batches(
            batch_size=batch_size,
            seller_id=seller_id,
            product_id=product_id,
        ):
            products_by_seller: dict[UUID, tuple[Seller, list[Product]]] = {}
            for product, seller in batch:
                products_by_seller.setdefault(product.seller_id, (seller, []))[1].append(product)

            for batch_seller_id, (seller, products) in products_by_seller.items():
                current_date = as_of_date or self.business_date_for_seller(seller, timestamp)
                product_ids = [product.id for product in products]
                try:
                    aging = self._repository.latest_aging_for_products(
                        seller_id=batch_seller_id,
                        product_ids=product_ids,
                        as_of_date=current_date,
                    )
                    velocities = self._repository.latest_velocity_for_products(
                        seller_id=batch_seller_id,
                        product_ids=product_ids,
                        as_of_date=current_date,
                    )
                    sales_summaries = self._repository.sales_summaries_for_products(
                        seller_id=batch_seller_id,
                        product_ids=product_ids,
                    )
                    visibility = self._repository.visibility_for_products(
                        seller_id=batch_seller_id,
                        product_ids=product_ids,
                        as_of_date=current_date,
                    )
                    for product in products:
                        saved, was_created = self.assess_for_product(
                            product=product,
                            seller=seller,
                            inventory_aging=aging.get(product.id),
                            sales_velocity=velocities.get(product.id),
                            sales_summary=None if sales_summaries is None else sales_summaries.get(product.id, {}),
                            visibility=visibility.get(product.id),
                            as_of_date=current_date,
                            assessed_at=timestamp,
                        )
                        created += int(was_created)
                        skipped += int(not was_created)
                        insufficient += int(saved.data_status == DeadStockDataStatus.INSUFFICIENT)
                        dead_stock += int(saved.classification == DeadStockClassification.DEAD_STOCK)
                except Exception:
                    failed += len(products)
                    self._log.exception(
                        "dead_stock_batch_failed seller_id=%s product_count=%s as_of_date=%s",
                        batch_seller_id,
                        len(products),
                        current_date,
                    )
        self._log.info(
            "dead_stock_assessment_completed created=%s skipped=%s failed=%s insufficient=%s dead_stock=%s version=%s",
            created,
            skipped,
            failed,
            insufficient,
            dead_stock,
            self._calculation_version,
        )
        return DeadStockBatchResult(created, skipped, failed, insufficient, dead_stock)

    def build_assessment(
        self,
        *,
        product: Product,
        seller: Seller,
        inventory_aging: InventoryAgingSnapshot | None,
        sales_velocity: SalesVelocity | None,
        sales_summary: dict | None,
        visibility: dict | None,
        as_of_date: date,
        assessed_at: datetime,
    ) -> DeadStockAssessment:
        del seller
        eligible_quantity = int(getattr(inventory_aging, "eligible_unsold_quantity", max(0, getattr(product, "stock_quantity", 0) or 0)) or 0)
        last_sale_at = None if sales_summary is None else sales_summary.get("last_valid_sale_at")
        days_since_last_sale = (as_of_date - _ensure_utc(last_sale_at).date()).days if last_sale_at else None
        product_age_days = max(0, (as_of_date - _ensure_utc(product.created_at).date()).days) if getattr(product, "created_at", None) else None

        no_sales_state = _no_sales_state(
            sales_summary=sales_summary,
            days_since_last_sale=days_since_last_sale,
            product_age_days=product_age_days,
        )
        inventory_age_state = _inventory_age_state(inventory_aging)
        visibility_status, visibility_score = _visibility_status(visibility)
        classification = self._classify(
            eligible_quantity=eligible_quantity,
            no_sales_state=no_sales_state,
            inventory_age_state=inventory_age_state,
            inventory_aging=inventory_aging,
            sales_velocity=sales_velocity,
            visibility_status=visibility_status,
            product_age_days=product_age_days,
        )
        data_status = _data_status(
            inventory_aging=inventory_aging,
            sales_summary=sales_summary,
            visibility_status=visibility_status,
            classification=classification,
        )
        triggered_rules = _triggered_rules(
            no_sales_state=no_sales_state,
            inventory_age_state=inventory_age_state,
            visibility_status=visibility_status,
            classification=classification,
            sales_velocity=sales_velocity,
            inventory_aging=inventory_aging,
        )
        risk = _risk_assessment(
            inventory_aging=inventory_aging,
            sales_velocity=sales_velocity,
            sales_summary=sales_summary,
            no_sales_state=no_sales_state,
            inventory_age_state=inventory_age_state,
            visibility_status=visibility_status,
            visibility_score=visibility_score,
            days_since_last_sale=days_since_last_sale,
            product_age_days=product_age_days,
            eligible_quantity=eligible_quantity,
        )
        rule_results = _rule_results(
            product=product,
            inventory_aging=inventory_aging,
            sales_velocity=sales_velocity,
            sales_summary=sales_summary,
            no_sales_state=no_sales_state,
            inventory_age_state=inventory_age_state,
            visibility_status=visibility_status,
            visibility_score=visibility_score,
            days_since_last_sale=days_since_last_sale,
            last_sale_at=last_sale_at,
            eligible_quantity=eligible_quantity,
            product_age_days=product_age_days,
            classification=classification,
            data_status=data_status,
            triggered_rules=triggered_rules,
            calculation_version=self._calculation_version,
            risk=risk,
        )
        return DeadStockAssessment(
            seller_id=product.seller_id,
            product_id=product.id,
            inventory_aging_id=getattr(inventory_aging, "id", None),
            inventory_snapshot_id=getattr(inventory_aging, "inventory_snapshot_id", None),
            sales_velocity_id=getattr(sales_velocity, "id", None),
            as_of_date=as_of_date,
            classification=classification,
            eligible_quantity=eligible_quantity,
            days_since_last_sale=days_since_last_sale,
            last_sale_at=last_sale_at,
            inventory_age_days=getattr(inventory_aging, "oldest_age_days", None),
            inventory_age_is_estimated=bool(getattr(inventory_aging, "is_estimated", False)),
            no_sales_state=no_sales_state,
            inventory_age_state=inventory_age_state,
            visibility_score=visibility_score,
            visibility_status=visibility_status,
            risk_score=risk["score"],
            risk_level=risk["level"],
            rule_results=rule_results,
            triggered_rules=triggered_rules,
            data_status=data_status,
            confidence_score=_confidence(data_status=data_status, inventory_aging=inventory_aging, sales_velocity=sales_velocity, visibility_status=visibility_status),
            calculation_version=self._calculation_version,
            assessed_at=assessed_at,
        )

    def latest_assessment(self, *, seller_id: UUID, product_id: UUID, calculation_version: str | None = None):
        return self._repository.latest(seller_id=seller_id, product_id=product_id, calculation_version=calculation_version)

    def assessment_history(self, *, seller_id: UUID, product_id: UUID, from_date: date | None, to_date: date | None, calculation_version: str | None, order: str, limit: int, offset: int):
        return self._repository.history(seller_id=seller_id, product_id=product_id, from_date=from_date, to_date=to_date, calculation_version=calculation_version, order=order, limit=limit, offset=offset)

    def list_assessments(self, **kwargs):
        return self._repository.list_assessments(**kwargs)

    @staticmethod
    def business_date_for_seller(seller: Seller, captured_at: datetime) -> date:
        timezone_name = getattr(seller, "timezone", None) or "UTC"
        try:
            seller_timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            seller_timezone = timezone.utc
        return _ensure_utc(captured_at).astimezone(seller_timezone).date()

    @staticmethod
    def _classify(
        *,
        eligible_quantity: int,
        no_sales_state: DeadStockNoSalesState,
        inventory_age_state: DeadStockInventoryAgeState,
        inventory_aging: InventoryAgingSnapshot | None,
        sales_velocity: SalesVelocity | None,
        visibility_status: DeadStockVisibilityStatus,
        product_age_days: int | None,
    ) -> DeadStockClassification:
        if eligible_quantity <= 0:
            return DeadStockClassification.INSUFFICIENT_DATA
        if no_sales_state == DeadStockNoSalesState.PRODUCT_TOO_NEW:
            return DeadStockClassification.HEALTHY
        if no_sales_state == DeadStockNoSalesState.SALES_DATA_INSUFFICIENT or inventory_age_state == DeadStockInventoryAgeState.AGE_DATA_UNAVAILABLE:
            return DeadStockClassification.INSUFFICIENT_DATA

        no_sales_breached = no_sales_state in {
            DeadStockNoSalesState.NO_SALES_WITHIN_THRESHOLD,
            DeadStockNoSalesState.NEVER_SOLD,
        }
        age_breached = _age_threshold_breached(inventory_aging, inventory_age_state)
        low_visibility = visibility_status == DeadStockVisibilityStatus.LOW_VISIBILITY
        slow_velocity = _is_slow_velocity(sales_velocity)
        excessive_coverage = _has_excessive_coverage(inventory_aging=inventory_aging, sales_velocity=sales_velocity)
        age_warning = _age_warning(inventory_aging)
        no_sales_warning = _no_sales_warning(product_age_days=product_age_days, no_sales_state=no_sales_state)

        if age_breached and no_sales_breached:
            return DeadStockClassification.DEAD_STOCK
        if age_breached or no_sales_breached or (low_visibility and (age_warning or no_sales_warning)):
            return DeadStockClassification.AT_RISK
        if slow_velocity or excessive_coverage or age_warning:
            return DeadStockClassification.SLOW_MOVING
        return DeadStockClassification.HEALTHY


def _no_sales_state(*, sales_summary: dict | None, days_since_last_sale: int | None, product_age_days: int | None) -> DeadStockNoSalesState:
    if sales_summary is None:
        return DeadStockNoSalesState.SALES_DATA_INSUFFICIENT
    if product_age_days is not None and product_age_days < settings.dead_stock_product_age_grace_period_days:
        return DeadStockNoSalesState.PRODUCT_TOO_NEW
    if int(sales_summary.get("sales_record_count", 0) or 0) == 0:
        return DeadStockNoSalesState.NEVER_SOLD
    if int(sales_summary.get("valid_positive_sale_count", 0) or 0) == 0:
        return DeadStockNoSalesState.NEVER_SOLD
    if days_since_last_sale is None:
        return DeadStockNoSalesState.SALES_DATA_INSUFFICIENT
    if days_since_last_sale >= settings.dead_stock_no_sales_threshold_days:
        return DeadStockNoSalesState.NO_SALES_WITHIN_THRESHOLD
    return DeadStockNoSalesState.RECENT_SALE


def _inventory_age_state(inventory_aging: InventoryAgingSnapshot | None) -> DeadStockInventoryAgeState:
    if inventory_aging is None or inventory_aging.oldest_age_days is None:
        return DeadStockInventoryAgeState.AGE_DATA_UNAVAILABLE
    if inventory_aging.is_estimated:
        return DeadStockInventoryAgeState.AGE_ESTIMATED
    if inventory_aging.oldest_age_days >= settings.dead_stock_inventory_age_threshold_days:
        return DeadStockInventoryAgeState.AGE_THRESHOLD_EXCEEDED
    return DeadStockInventoryAgeState.AGE_BELOW_THRESHOLD


def _visibility_status(visibility: dict | None) -> tuple[DeadStockVisibilityStatus, Decimal | None]:
    if not visibility:
        return DeadStockVisibilityStatus.VISIBILITY_DATA_UNAVAILABLE, None
    status = visibility.get("status")
    score = _decimal_or_none(visibility.get("score"))
    if status:
        return DeadStockVisibilityStatus(status), score
    if score is None:
        return DeadStockVisibilityStatus.VISIBILITY_DATA_LIMITED, None
    if score <= Decimal(str(settings.dead_stock_low_visibility_threshold)):
        return DeadStockVisibilityStatus.LOW_VISIBILITY, _score(score)
    return DeadStockVisibilityStatus.NORMAL_VISIBILITY, _score(score)


def _data_status(*, inventory_aging: InventoryAgingSnapshot | None, sales_summary: dict | None, visibility_status: DeadStockVisibilityStatus, classification: DeadStockClassification) -> DeadStockDataStatus:
    if classification == DeadStockClassification.INSUFFICIENT_DATA:
        return DeadStockDataStatus.INSUFFICIENT
    if inventory_aging is None or sales_summary is None:
        return DeadStockDataStatus.INSUFFICIENT
    if inventory_aging.is_estimated or visibility_status in {
        DeadStockVisibilityStatus.VISIBILITY_DATA_LIMITED,
        DeadStockVisibilityStatus.VISIBILITY_DATA_UNAVAILABLE,
    }:
        return DeadStockDataStatus.LIMITED
    return DeadStockDataStatus.SUFFICIENT


def _triggered_rules(*, no_sales_state: DeadStockNoSalesState, inventory_age_state: DeadStockInventoryAgeState, visibility_status: DeadStockVisibilityStatus, classification: DeadStockClassification, sales_velocity: SalesVelocity | None, inventory_aging: InventoryAgingSnapshot | None) -> list[str]:
    rules: list[str] = []
    if no_sales_state in {DeadStockNoSalesState.NO_SALES_WITHIN_THRESHOLD, DeadStockNoSalesState.NEVER_SOLD}:
        rules.append("NO_VALID_SALES")
    if _age_threshold_breached(inventory_aging, inventory_age_state):
        rules.append("INVENTORY_AGE_THRESHOLD")
    if inventory_age_state == DeadStockInventoryAgeState.AGE_ESTIMATED:
        rules.append("INVENTORY_AGE_ESTIMATED")
    if visibility_status == DeadStockVisibilityStatus.LOW_VISIBILITY:
        rules.append("LOW_VISIBILITY")
    if _is_slow_velocity(sales_velocity):
        rules.append("LOW_SALES_VELOCITY")
    if _has_excessive_coverage(inventory_aging=inventory_aging, sales_velocity=sales_velocity):
        rules.append("EXCESSIVE_INVENTORY_COVERAGE")
    if classification == DeadStockClassification.INSUFFICIENT_DATA:
        rules.append("INSUFFICIENT_REQUIRED_DATA")
    return rules


def _rule_results(**kwargs) -> dict:
    product = kwargs["product"]
    inventory_aging = kwargs["inventory_aging"]
    sales_velocity = kwargs["sales_velocity"]
    last_sale_at = kwargs["last_sale_at"]
    risk = kwargs["risk"]
    return {
        "no_sales_threshold_days": settings.dead_stock_no_sales_threshold_days,
        "days_since_last_sale": kwargs["days_since_last_sale"],
        "last_sale_at": _iso_or_none(last_sale_at),
        "no_sales_state": kwargs["no_sales_state"].value,
        "inventory_age_threshold_days": settings.dead_stock_inventory_age_threshold_days,
        "inventory_age_days": kwargs["inventory_aging"].oldest_age_days if inventory_aging else None,
        "inventory_age_source": getattr(getattr(inventory_aging, "age_source", None), "value", None),
        "inventory_age_is_estimated": bool(getattr(inventory_aging, "is_estimated", False)),
        "inventory_age_state": kwargs["inventory_age_state"].value,
        "eligible_quantity": kwargs["eligible_quantity"],
        "visibility_status": kwargs["visibility_status"].value,
        "visibility_score": str(kwargs["visibility_score"]) if kwargs["visibility_score"] is not None else None,
        "sales_velocity_daily_rate": str(getattr(sales_velocity, "daily_sales_rate", "")) if sales_velocity else None,
        "sales_velocity_data_status": getattr(getattr(sales_velocity, "data_status", None), "value", None),
        "inventory_coverage_days": risk["coverage_days"],
        "product_age_days": kwargs["product_age_days"],
        "product_category": getattr(product, "category", None),
        "risk_score": str(risk["score"]),
        "risk_level": risk["level"].value,
        "risk_component_scores": risk["component_scores"],
        "risk_component_statuses": risk["component_statuses"],
        "risk_base_weights": risk["base_weights"],
        "risk_effective_weights": risk["effective_weights"],
        "risk_formula": risk["formula"],
        "risk_explanation": risk["explanation"],
        "classification": kwargs["classification"].value,
        "data_status": kwargs["data_status"].value,
        "triggered_rules": kwargs["triggered_rules"],
        "calculation_version": kwargs["calculation_version"],
        "valid_sales_statuses": ["COMPLETED", "FULFILLED"],
        "excluded_sales": ["PENDING", "CANCELLED", "FAILED_PAYMENT", "test_orders", "non_positive_net_sales"],
    }


def _is_slow_velocity(sales_velocity: SalesVelocity | None) -> bool:
    if sales_velocity is None or sales_velocity.data_status == SalesVelocityDataStatus.INSUFFICIENT:
        return False
    rate = Decimal(str(sales_velocity.daily_sales_rate or "0"))
    return Decimal("0") < rate <= Decimal(str(settings.dead_stock_slow_velocity_units_per_day))


def _has_excessive_coverage(*, inventory_aging: InventoryAgingSnapshot | None, sales_velocity: SalesVelocity | None) -> bool:
    if inventory_aging is None or sales_velocity is None:
        return False
    rate = Decimal(str(sales_velocity.daily_sales_rate or "0"))
    if rate <= 0:
        return False
    coverage = Decimal(inventory_aging.eligible_unsold_quantity) / rate
    return coverage >= Decimal(settings.dead_stock_excess_coverage_days)


def _risk_assessment(
    *,
    inventory_aging: InventoryAgingSnapshot | None,
    sales_velocity: SalesVelocity | None,
    sales_summary: dict | None,
    no_sales_state: DeadStockNoSalesState,
    inventory_age_state: DeadStockInventoryAgeState,
    visibility_status: DeadStockVisibilityStatus,
    visibility_score: Decimal | None,
    days_since_last_sale: int | None,
    product_age_days: int | None,
    eligible_quantity: int,
) -> dict:
    base_weights = _risk_base_weights()
    component_scores: dict[str, str | None] = {}
    component_statuses: dict[str, str] = {}

    _set_component(
        component_scores,
        component_statuses,
        "inventory_age_severity",
        _inventory_age_severity(inventory_aging=inventory_aging, inventory_age_state=inventory_age_state),
    )
    _set_component(
        component_scores,
        component_statuses,
        "no_sales_severity",
        _no_sales_severity(
            sales_summary=sales_summary,
            no_sales_state=no_sales_state,
            days_since_last_sale=days_since_last_sale,
            product_age_days=product_age_days,
        ),
    )
    _set_component(
        component_scores,
        component_statuses,
        "sales_velocity_weakness",
        _velocity_weakness(sales_velocity),
    )
    coverage_days = _inventory_coverage_days(inventory_aging=inventory_aging, sales_velocity=sales_velocity)
    _set_component(
        component_scores,
        component_statuses,
        "excess_coverage",
        _excess_coverage_severity(coverage_days),
    )
    _set_component(
        component_scores,
        component_statuses,
        "visibility_weakness",
        _visibility_weakness(visibility_status=visibility_status, visibility_score=visibility_score),
    )

    available_weight = sum(
        base_weights[name]
        for name, status in component_statuses.items()
        if status == "AVAILABLE"
    )
    effective_weights: dict[str, str] = {}
    weighted_score = Decimal("0")
    if available_weight > 0:
        for name, weight in base_weights.items():
            if component_statuses[name] != "AVAILABLE":
                effective_weights[name] = "0.00"
                continue
            effective_weight = weight / available_weight
            effective_weights[name] = str(_score(effective_weight * Decimal("100")))
            weighted_score += Decimal(component_scores[name] or "0") * effective_weight
    else:
        effective_weights = {name: "0.00" for name in base_weights}

    score = _score(max(Decimal("0"), min(weighted_score, Decimal("100"))))
    return {
        "score": score,
        "level": _risk_level(score),
        "component_scores": component_scores,
        "component_statuses": component_statuses,
        "base_weights": {name: str(_score(weight)) for name, weight in base_weights.items()},
        "effective_weights": effective_weights,
        "coverage_days": str(_score(coverage_days)) if coverage_days is not None else None,
        "formula": "weighted_average_available_components_v1",
        "explanation": _risk_explanation(component_scores=component_scores, component_statuses=component_statuses, eligible_quantity=eligible_quantity),
    }


def _risk_base_weights() -> dict[str, Decimal]:
    weights = {
        "inventory_age_severity": Decimal(str(settings.dead_stock_inventory_age_weight)),
        "no_sales_severity": Decimal(str(settings.dead_stock_no_sales_weight)),
        "sales_velocity_weakness": Decimal(str(settings.dead_stock_sales_velocity_weight)),
        "excess_coverage": Decimal(str(settings.dead_stock_excess_coverage_weight)),
        "visibility_weakness": Decimal(str(settings.dead_stock_visibility_weight)),
    }
    if any(weight < 0 for weight in weights.values()):
        raise ValueError("Dead-stock risk weights must be non-negative.")
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("At least one dead-stock risk weight must be positive.")
    return weights


def _set_component(scores: dict[str, str | None], statuses: dict[str, str], name: str, value: Decimal | None) -> None:
    if value is None:
        scores[name] = None
        statuses[name] = "UNAVAILABLE"
        return
    scores[name] = str(_score(max(Decimal("0"), min(value, Decimal("100")))))
    statuses[name] = "AVAILABLE"


def _inventory_age_severity(*, inventory_aging: InventoryAgingSnapshot | None, inventory_age_state: DeadStockInventoryAgeState) -> Decimal | None:
    if inventory_aging is None or inventory_aging.oldest_age_days is None or inventory_age_state == DeadStockInventoryAgeState.AGE_DATA_UNAVAILABLE:
        return None
    return _threshold_severity(
        value=Decimal(inventory_aging.oldest_age_days),
        warning=Decimal(settings.dead_stock_inventory_age_threshold_days) * Decimal(str(settings.dead_stock_age_warning_ratio)),
        critical=Decimal(settings.dead_stock_inventory_age_threshold_days),
        extreme=Decimal(settings.dead_stock_inventory_age_threshold_days) * Decimal(str(settings.dead_stock_extreme_age_multiplier)),
    )


def _no_sales_severity(*, sales_summary: dict | None, no_sales_state: DeadStockNoSalesState, days_since_last_sale: int | None, product_age_days: int | None) -> Decimal | None:
    if sales_summary is None or no_sales_state == DeadStockNoSalesState.SALES_DATA_INSUFFICIENT:
        return None
    if no_sales_state == DeadStockNoSalesState.PRODUCT_TOO_NEW:
        return Decimal("0")
    if no_sales_state == DeadStockNoSalesState.NEVER_SOLD:
        if product_age_days is None:
            return None
        return _threshold_severity(
            value=Decimal(product_age_days),
            warning=Decimal(settings.dead_stock_no_sales_threshold_days) * Decimal(str(settings.dead_stock_no_sales_warning_ratio)),
            critical=Decimal(settings.dead_stock_no_sales_threshold_days),
            extreme=Decimal(settings.dead_stock_no_sales_threshold_days) * Decimal(str(settings.dead_stock_extreme_no_sales_multiplier)),
        )
    if days_since_last_sale is None:
        return None
    return _threshold_severity(
        value=Decimal(days_since_last_sale),
        warning=Decimal(settings.dead_stock_no_sales_threshold_days) * Decimal(str(settings.dead_stock_no_sales_warning_ratio)),
        critical=Decimal(settings.dead_stock_no_sales_threshold_days),
        extreme=Decimal(settings.dead_stock_no_sales_threshold_days) * Decimal(str(settings.dead_stock_extreme_no_sales_multiplier)),
    )


def _velocity_weakness(sales_velocity: SalesVelocity | None) -> Decimal | None:
    if sales_velocity is None or sales_velocity.data_status == SalesVelocityDataStatus.INSUFFICIENT:
        return None
    rate = Decimal(str(sales_velocity.daily_sales_rate or "0"))
    if rate <= 0:
        return Decimal("100")
    strong_rate = Decimal(str(settings.dead_stock_strong_velocity_units_per_day))
    if strong_rate <= 0:
        raise ValueError("Dead-stock strong velocity threshold must be positive.")
    if rate >= strong_rate:
        return Decimal("0")
    return (strong_rate - rate) / strong_rate * Decimal("100")


def _inventory_coverage_days(*, inventory_aging: InventoryAgingSnapshot | None, sales_velocity: SalesVelocity | None) -> Decimal | None:
    if inventory_aging is None or sales_velocity is None or sales_velocity.data_status == SalesVelocityDataStatus.INSUFFICIENT:
        return None
    rate = Decimal(str(sales_velocity.daily_sales_rate or "0"))
    if rate <= 0:
        return None
    return Decimal(inventory_aging.eligible_unsold_quantity) / rate


def _excess_coverage_severity(coverage_days: Decimal | None) -> Decimal | None:
    if coverage_days is None:
        return None
    critical = Decimal(settings.dead_stock_excess_coverage_days)
    return _threshold_severity(
        value=coverage_days,
        warning=critical * Decimal(str(settings.dead_stock_excess_coverage_warning_ratio)),
        critical=critical,
        extreme=critical * Decimal(str(settings.dead_stock_extreme_coverage_multiplier)),
    )


def _visibility_weakness(*, visibility_status: DeadStockVisibilityStatus, visibility_score: Decimal | None) -> Decimal | None:
    if visibility_status in {
        DeadStockVisibilityStatus.VISIBILITY_DATA_UNAVAILABLE,
        DeadStockVisibilityStatus.VISIBILITY_DATA_LIMITED,
    } or visibility_score is None:
        return None
    return Decimal("100") - visibility_score


def _threshold_severity(*, value: Decimal, warning: Decimal, critical: Decimal, extreme: Decimal) -> Decimal:
    if critical <= warning:
        raise ValueError("Dead-stock critical threshold must be greater than warning threshold.")
    if extreme <= critical:
        raise ValueError("Dead-stock extreme threshold must be greater than critical threshold.")
    if value < warning:
        return Decimal("0")
    if value < critical:
        return (value - warning) / (critical - warning) * Decimal("75")
    if value < extreme:
        return Decimal("75") + ((value - critical) / (extreme - critical) * Decimal("25"))
    return Decimal("100")


def _risk_level(score: Decimal) -> DeadStockRiskLevel:
    if score < Decimal("25"):
        return DeadStockRiskLevel.LOW
    if score < Decimal("50"):
        return DeadStockRiskLevel.MEDIUM
    if score < Decimal("75"):
        return DeadStockRiskLevel.HIGH
    return DeadStockRiskLevel.CRITICAL


def _risk_explanation(*, component_scores: dict[str, str | None], component_statuses: dict[str, str], eligible_quantity: int) -> str:
    available = [
        f"{name}={component_scores[name]}"
        for name, status in component_statuses.items()
        if status == "AVAILABLE"
    ]
    unavailable = [
        name
        for name, status in component_statuses.items()
        if status != "AVAILABLE"
    ]
    parts = [
        "Risk score is an explainable weighted business score from 0 to 100, not a calibrated probability.",
        f"Eligible inventory quantity is {eligible_quantity}.",
    ]
    if available:
        parts.append("Available component scores: " + ", ".join(available) + ".")
    if unavailable:
        parts.append("Unavailable components were excluded and remaining weights were re-normalized: " + ", ".join(unavailable) + ".")
    return " ".join(parts)


def _age_warning(inventory_aging: InventoryAgingSnapshot | None) -> bool:
    if inventory_aging is None or inventory_aging.oldest_age_days is None:
        return False
    threshold = Decimal(settings.dead_stock_inventory_age_threshold_days) * Decimal(str(settings.dead_stock_age_warning_ratio))
    return Decimal(inventory_aging.oldest_age_days) >= threshold


def _age_threshold_breached(inventory_aging: InventoryAgingSnapshot | None, inventory_age_state: DeadStockInventoryAgeState) -> bool:
    if inventory_age_state == DeadStockInventoryAgeState.AGE_THRESHOLD_EXCEEDED:
        return True
    if inventory_age_state == DeadStockInventoryAgeState.AGE_ESTIMATED and inventory_aging and inventory_aging.oldest_age_days is not None:
        return inventory_aging.oldest_age_days >= settings.dead_stock_inventory_age_threshold_days
    return False


def _no_sales_warning(*, product_age_days: int | None, no_sales_state: DeadStockNoSalesState) -> bool:
    if no_sales_state in {DeadStockNoSalesState.NEVER_SOLD, DeadStockNoSalesState.NO_SALES_WITHIN_THRESHOLD}:
        return True
    if product_age_days is None:
        return False
    threshold = Decimal(settings.dead_stock_no_sales_threshold_days) * Decimal(str(settings.dead_stock_no_sales_warning_ratio))
    return Decimal(product_age_days) >= threshold


def _confidence(*, data_status: DeadStockDataStatus, inventory_aging: InventoryAgingSnapshot | None, sales_velocity: SalesVelocity | None, visibility_status: DeadStockVisibilityStatus) -> Decimal:
    score = Decimal("85")
    if data_status == DeadStockDataStatus.INSUFFICIENT:
        return Decimal("25.00")
    if inventory_aging and inventory_aging.is_estimated:
        score -= Decimal("15")
    if sales_velocity is None or sales_velocity.data_status == SalesVelocityDataStatus.INSUFFICIENT:
        score -= Decimal("20")
    if visibility_status == DeadStockVisibilityStatus.VISIBILITY_DATA_UNAVAILABLE:
        score -= Decimal("10")
    elif visibility_status == DeadStockVisibilityStatus.VISIBILITY_DATA_LIMITED:
        score -= Decimal("15")
    return _score(max(Decimal("0"), min(score, Decimal("100"))))


def _decimal_or_none(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _score(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _iso_or_none(value: datetime | None) -> str | None:
    return _ensure_utc(value).isoformat() if value else None


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
