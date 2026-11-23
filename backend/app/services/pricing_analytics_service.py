from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
import hashlib
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.competitor_ranking import CompetitorRanking
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.inventory_history import InventoryHistory
from app.models.inventory_risk import InventoryRiskAssessment
from app.models.marketplace_fee_policy import MarketplaceFeePolicy
from app.models.pricing_analytics_snapshot import PricingAnalyticsDataStatus, PricingAnalyticsSnapshot
from app.models.product import Product
from app.models.sales_velocity import SalesVelocity, SalesVelocityDataStatus
from app.models.scrape_run import ScrapeRun
from app.services.pricing_calculator import FeeInputs, PricingCalculationError, PricingCalculator
from app.services.pricing_policy_service import PricingPolicyService

MONEY_QUANT = Decimal("0.01")
RATE_QUANT = Decimal("0.000001")
SCORE_QUANT = Decimal("0.01")


@dataclass(frozen=True)
class PricingAnalyticsConfig:
    max_competitor_data_age: timedelta
    max_inventory_data_age: timedelta
    max_velocity_data_age: timedelta
    demand_velocity_weight: Decimal
    demand_recent_sales_weight: Decimal
    demand_competitor_availability_weight: Decimal
    demand_product_maturity_weight: Decimal
    demand_velocity_reference_units_per_day: Decimal
    demand_recent_sales_reference_units: Decimal
    calculation_version: str

    @classmethod
    def from_settings(cls) -> "PricingAnalyticsConfig":
        config = cls(
            max_competitor_data_age=timedelta(hours=settings.pricing_analytics_max_competitor_data_age_hours),
            max_inventory_data_age=timedelta(hours=settings.pricing_analytics_max_inventory_data_age_hours),
            max_velocity_data_age=timedelta(hours=settings.pricing_analytics_max_velocity_data_age_hours),
            demand_velocity_weight=Decimal(str(settings.pricing_analytics_demand_velocity_weight)),
            demand_recent_sales_weight=Decimal(str(settings.pricing_analytics_demand_recent_sales_weight)),
            demand_competitor_availability_weight=Decimal(str(settings.pricing_analytics_demand_competitor_availability_weight)),
            demand_product_maturity_weight=Decimal(str(settings.pricing_analytics_demand_product_maturity_weight)),
            demand_velocity_reference_units_per_day=Decimal(str(settings.pricing_analytics_demand_velocity_reference_units_per_day)),
            demand_recent_sales_reference_units=Decimal(str(settings.pricing_analytics_demand_recent_sales_reference_units)),
            calculation_version=settings.pricing_analytics_formula_version,
        )
        config.validate()
        return config

    def validate(self) -> None:
        total = (
            self.demand_velocity_weight
            + self.demand_recent_sales_weight
            + self.demand_competitor_availability_weight
            + self.demand_product_maturity_weight
        )
        if total != Decimal("100"):
            raise ValueError("Pricing analytics demand weights must total 100")
        if self.demand_velocity_reference_units_per_day <= 0:
            raise ValueError("Velocity reference must be positive")
        if self.demand_recent_sales_reference_units <= 0:
            raise ValueError("Recent sales reference must be positive")


@dataclass(frozen=True)
class MarketStats:
    min_price: Decimal | None
    q1_price: Decimal | None
    mean_price: Decimal | None
    median_price: Decimal | None
    q3_price: Decimal | None
    max_price: Decimal | None
    weighted_market_price: Decimal | None
    seller_price_difference_from_median: Decimal | None
    seller_price_percentile: Decimal | None
    competitor_count: int
    in_stock_competitor_count: int
    out_of_stock_competitor_count: int = 0


@dataclass(frozen=True)
class DemandScore:
    score: Decimal | None
    status: PricingAnalyticsDataStatus
    confidence: Decimal
    components: dict[str, object]


class ProductNotFoundError(Exception):
    pass


class PricingAnalyticsService:
    def __init__(self, db: Session, *, config: PricingAnalyticsConfig | None = None) -> None:
        self._db = db
        self._config = config or PricingAnalyticsConfig.from_settings()

    def generate_for_product(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        marketplace: str = "Daraz Bangladesh",
        calculated_at: datetime | None = None,
    ) -> PricingAnalyticsSnapshot:
        timestamp = _ensure_utc(calculated_at or datetime.now(timezone.utc))
        product = self._product_for_seller(seller_id=seller_id, product_id=product_id)

        run = self._latest_completed_run(seller_id=seller_id, product_id=product_id, marketplace=marketplace)
        run_fresh = _is_fresh(run.completed_at or run.finished_at if run else None, timestamp, self._config.max_competitor_data_age)
        snapshots = self._snapshots_for_run(run.id) if run and run_fresh else []
        rankings = self._rankings_for_run(run.id) if run and run_fresh else {}
        market_stats = calculate_market_stats(
            snapshots=snapshots,
            rankings=rankings,
            seller_price=Decimal(product.selling_price),
        )

        inventory = self._latest_inventory(seller_id=seller_id, product_id=product_id)
        inventory_fresh = _is_fresh(inventory.captured_at if inventory else None, timestamp, self._config.max_inventory_data_age)
        velocity = self._latest_velocity(seller_id=seller_id, product_id=product_id)
        velocity_fresh = _is_fresh(velocity.calculated_at if velocity else None, timestamp, self._config.max_velocity_data_age)
        risk = self._latest_inventory_risk(seller_id=seller_id, product_id=product_id)

        policy_service = PricingPolicyService(self._db)
        policy = policy_service.get_product_policy(seller_id=seller_id, product_id=product_id, marketplace=marketplace)
        fee_policy = policy_service.effective_fee_policy(
            seller_id=seller_id,
            product_id=product_id,
            marketplace=marketplace,
            as_of=timestamp,
        )
        fees = fee_inputs_from_policy(fee_policy)
        calculator = PricingCalculator(currency=policy.currency)
        current_unit_profit = calculator.calculate_unit_profit(
            price=product.selling_price,
            unit_cost=product.cost_price,
            fees=fees,
        )
        current_margin_rate = None
        if Decimal(product.selling_price) > 0:
            current_margin_rate = calculator.calculate_margin_rate(
                price=product.selling_price,
                unit_cost=product.cost_price,
                fees=fees,
            )
        minimum_safe_price = calculator.calculate_minimum_safe_price(
            unit_cost=product.cost_price,
            fees=fees,
            minimum_margin_rate=policy.minimum_margin_rate,
            minimum_unit_profit=policy.minimum_unit_profit,
            price_increment=policy.price_increment,
        )

        inventory_position = None
        if inventory and inventory_fresh:
            inventory_position = inventory.quantity_on_hand + inventory.quantity_incoming - inventory.quantity_reserved
        velocity_usable = velocity is not None and velocity_fresh and velocity.data_status != SalesVelocityDataStatus.INSUFFICIENT
        daily_sales_rate = velocity.daily_sales_rate if velocity_usable else None
        recent_net_sales = velocity.net_units_sold if velocity_usable else None
        product_age_days = max(0, (timestamp.date() - product.created_at.date()).days) if product.created_at else None

        demand = calculate_demand_score(
            daily_sales_rate=daily_sales_rate,
            recent_net_sales=recent_net_sales,
            product_age_days=product_age_days,
            competitor_count=market_stats.competitor_count,
            in_stock_competitor_count=market_stats.in_stock_competitor_count,
            out_of_stock_competitor_count=market_stats.out_of_stock_competitor_count,
            velocity_status=velocity.data_status if velocity else None,
            config=self._config,
        )
        data_status = determine_data_status(
            run_exists=run is not None,
            run_fresh=run_fresh,
            has_competitor_prices=market_stats.competitor_count > 0,
            inventory_exists=inventory is not None,
            inventory_fresh=inventory_fresh,
            velocity_exists=velocity is not None,
            velocity_fresh=velocity_fresh,
            velocity_usable=velocity_usable,
        )
        confidence = calculate_confidence(
            data_status=data_status,
            demand_confidence=demand.confidence,
            run_fresh=run_fresh,
            inventory_fresh=inventory_fresh,
            velocity_fresh=velocity_fresh,
            competitor_count=market_stats.competitor_count,
        )
        evidence = {
            "freshness": {
                "competitor": _freshness_payload(run.completed_at or run.finished_at if run else None, timestamp, self._config.max_competitor_data_age, run_fresh),
                "inventory": _freshness_payload(inventory.captured_at if inventory else None, timestamp, self._config.max_inventory_data_age, inventory_fresh),
                "velocity": _freshness_payload(velocity.calculated_at if velocity else None, timestamp, self._config.max_velocity_data_age, velocity_fresh),
            },
            "market_stats": {
                "competitor_count": market_stats.competitor_count,
                "in_stock_competitor_count": market_stats.in_stock_competitor_count,
                "out_of_stock_competitor_count": market_stats.out_of_stock_competitor_count,
                "outlier_policy": "No outliers removed in v1.",
            },
            "demand": {
                "formula_version": self._config.calculation_version,
                "components": demand.components,
            },
            "pricing_policy": {
                "policy_id": str(policy.id) if policy.id else None,
                "fee_policy_id": str(fee_policy.id) if fee_policy.id else None,
                "minimum_margin_rate": str(policy.minimum_margin_rate),
                "objective": str(policy.objective.value if hasattr(policy.objective, "value") else policy.objective),
            },
            "promotion_state": "UNKNOWN",
        }
        dedupe_key = _dedupe_key(
            seller_id=seller_id,
            product_id=product_id,
            calculation_version=self._config.calculation_version,
            source_ids=[
                run.id if run and run_fresh else None,
                inventory.id if inventory and inventory_fresh else None,
                velocity.id if velocity_usable else None,
                fee_policy.id,
            ],
            current_price=product.selling_price,
            unit_cost=product.cost_price,
        )
        existing = self._by_dedupe_key(dedupe_key)
        if existing:
            return existing

        snapshot = PricingAnalyticsSnapshot(
            seller_id=seller_id,
            product_id=product_id,
            competitor_scrape_run_id=run.id if run and run_fresh else None,
            inventory_snapshot_id=inventory.id if inventory and inventory_fresh else None,
            sales_velocity_id=velocity.id if velocity_usable else None,
            fee_policy_id=fee_policy.id,
            current_price=calculator.round_currency(product.selling_price),
            unit_cost=calculator.round_currency(product.cost_price),
            percentage_fee_rate=fees.percentage_fee_rate.quantize(RATE_QUANT),
            fixed_fee_amount=calculator.round_currency(fees.fixed_costs),
            current_unit_profit=calculator.round_currency(current_unit_profit),
            current_margin_rate=current_margin_rate,
            minimum_safe_price=minimum_safe_price,
            competitor_min_price=market_stats.min_price,
            competitor_q1_price=market_stats.q1_price,
            competitor_mean_price=market_stats.mean_price,
            competitor_median_price=market_stats.median_price,
            competitor_q3_price=market_stats.q3_price,
            competitor_max_price=market_stats.max_price,
            weighted_market_price=market_stats.weighted_market_price,
            seller_price_difference_from_median=market_stats.seller_price_difference_from_median,
            seller_price_percentile=market_stats.seller_price_percentile,
            competitor_count=market_stats.competitor_count,
            in_stock_competitor_count=market_stats.in_stock_competitor_count,
            inventory_position=inventory_position,
            inventory_risk_level=risk.risk_level.value if risk and risk.risk_level else None,
            daily_sales_rate=daily_sales_rate,
            recent_net_sales=recent_net_sales,
            product_age_days=product_age_days,
            promotion_state="UNKNOWN",
            demand_score=demand.score,
            demand_data_status=demand.status,
            data_status=data_status,
            confidence_score=confidence,
            evidence=evidence,
            calculation_version=self._config.calculation_version,
            dedupe_key=dedupe_key,
            calculated_at=timestamp,
        )
        self._db.add(snapshot)
        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            existing = self._by_dedupe_key(dedupe_key)
            if existing:
                return existing
            raise
        self._db.refresh(snapshot)
        return snapshot

    def generate_batch(
        self,
        *,
        seller_id: UUID | None = None,
        product_id: UUID | None = None,
        batch_size: int = 500,
    ) -> dict[str, int]:
        statement = select(Product).where(True).order_by(Product.id).limit(batch_size)
        if seller_id:
            statement = statement.where(Product.seller_id == seller_id)
        if product_id:
            statement = statement.where(Product.id == product_id)
        products = self._db.execute(statement).scalars().all()
        created_or_existing = 0
        failed = 0
        for product in products:
            try:
                self.generate_for_product(seller_id=product.seller_id, product_id=product.id)
                created_or_existing += 1
            except (ProductNotFoundError, PricingCalculationError, ValueError):
                self._db.rollback()
                failed += 1
        return {"processed_count": len(products), "snapshot_count": created_or_existing, "failed_count": failed}

    def latest(self, *, seller_id: UUID, product_id: UUID) -> PricingAnalyticsSnapshot | None:
        self._product_for_seller(seller_id=seller_id, product_id=product_id)
        return self._db.execute(
            select(PricingAnalyticsSnapshot)
            .where(PricingAnalyticsSnapshot.seller_id == seller_id, PricingAnalyticsSnapshot.product_id == product_id)
            .order_by(PricingAnalyticsSnapshot.calculated_at.desc(), PricingAnalyticsSnapshot.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    def history(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[PricingAnalyticsSnapshot], int]:
        self._product_for_seller(seller_id=seller_id, product_id=product_id)
        filters = [
            PricingAnalyticsSnapshot.seller_id == seller_id,
            PricingAnalyticsSnapshot.product_id == product_id,
        ]
        if date_from:
            filters.append(PricingAnalyticsSnapshot.calculated_at >= _ensure_utc(date_from))
        if date_to:
            filters.append(PricingAnalyticsSnapshot.calculated_at <= _ensure_utc(date_to))
        total = self._db.execute(select(func.count()).select_from(PricingAnalyticsSnapshot).where(*filters)).scalar_one()
        items = self._db.execute(
            select(PricingAnalyticsSnapshot)
            .where(*filters)
            .order_by(PricingAnalyticsSnapshot.calculated_at.desc(), PricingAnalyticsSnapshot.created_at.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
        return items, int(total)

    def explain_source_inputs(self, *, seller_id: UUID, product_id: UUID) -> dict[str, object]:
        latest = self.latest(seller_id=seller_id, product_id=product_id)
        if not latest:
            return {"snapshot": None, "message": "No pricing analytics snapshot has been calculated."}
        return {
            "snapshot_id": str(latest.id),
            "data_status": latest.data_status.value,
            "evidence": latest.evidence,
        }

    def _product_for_seller(self, *, seller_id: UUID, product_id: UUID) -> Product:
        product = self._db.execute(select(Product).where(Product.seller_id == seller_id, Product.id == product_id)).scalar_one_or_none()
        if product is None:
            raise ProductNotFoundError
        return product

    def _latest_completed_run(self, *, seller_id: UUID, product_id: UUID, marketplace: str) -> ScrapeRun | None:
        return self._db.execute(
            select(ScrapeRun)
            .where(
                ScrapeRun.seller_id == seller_id,
                ScrapeRun.product_id == product_id,
                ScrapeRun.marketplace == marketplace,
                ScrapeRun.status == "COMPLETED",
            )
            .order_by(ScrapeRun.completed_at.desc().nullslast(), ScrapeRun.finished_at.desc().nullslast(), ScrapeRun.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    def _snapshots_for_run(self, scrape_run_id: UUID) -> list[CompetitorSnapshot]:
        return self._db.execute(select(CompetitorSnapshot).where(CompetitorSnapshot.scrape_run_id == scrape_run_id)).scalars().all()

    def _rankings_for_run(self, scrape_run_id: UUID) -> dict[UUID, CompetitorRanking]:
        rankings = self._db.execute(select(CompetitorRanking).where(CompetitorRanking.scrape_run_id == scrape_run_id)).scalars().all()
        return {ranking.competitor_id: ranking for ranking in rankings}

    def _latest_inventory(self, *, seller_id: UUID, product_id: UUID) -> InventoryHistory | None:
        return self._db.execute(
            select(InventoryHistory)
            .where(InventoryHistory.seller_id == seller_id, InventoryHistory.product_id == product_id)
            .order_by(InventoryHistory.captured_at.desc(), InventoryHistory.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    def _latest_velocity(self, *, seller_id: UUID, product_id: UUID) -> SalesVelocity | None:
        return self._db.execute(
            select(SalesVelocity)
            .where(SalesVelocity.seller_id == seller_id, SalesVelocity.product_id == product_id)
            .order_by(SalesVelocity.calculated_at.desc(), SalesVelocity.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    def _latest_inventory_risk(self, *, seller_id: UUID, product_id: UUID) -> InventoryRiskAssessment | None:
        return self._db.execute(
            select(InventoryRiskAssessment)
            .where(InventoryRiskAssessment.seller_id == seller_id, InventoryRiskAssessment.product_id == product_id)
            .order_by(InventoryRiskAssessment.assessed_at.desc(), InventoryRiskAssessment.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    def _by_dedupe_key(self, dedupe_key: str) -> PricingAnalyticsSnapshot | None:
        return self._db.execute(select(PricingAnalyticsSnapshot).where(PricingAnalyticsSnapshot.dedupe_key == dedupe_key)).scalar_one_or_none()


def calculate_market_stats(
    *,
    snapshots: list[CompetitorSnapshot],
    rankings: dict[UUID, CompetitorRanking],
    seller_price: Decimal,
) -> MarketStats:
    valid = [snapshot for snapshot in snapshots if snapshot.price is not None and Decimal(snapshot.price) > 0]
    prices = sorted(Decimal(snapshot.price) for snapshot in valid)
    in_stock = sum(1 for snapshot in valid if snapshot.stock_status == "IN_STOCK")
    out_of_stock = sum(1 for snapshot in valid if snapshot.stock_status == "OUT_OF_STOCK")
    if not prices:
        return MarketStats(None, None, None, None, None, None, None, None, None, 0, 0)

    median = percentile(prices, Decimal("0.50"))
    weighted = weighted_market_price(valid, rankings)
    count_at_or_below_seller = sum(1 for price in prices if price <= seller_price)
    seller_percentile = (Decimal(count_at_or_below_seller) / Decimal(len(prices)) * Decimal("100")).quantize(SCORE_QUANT)
    return MarketStats(
        min_price=money(min(prices)),
        q1_price=money(percentile(prices, Decimal("0.25"))),
        mean_price=money(sum(prices) / Decimal(len(prices))),
        median_price=money(median),
        q3_price=money(percentile(prices, Decimal("0.75"))),
        max_price=money(max(prices)),
        weighted_market_price=money(weighted) if weighted is not None else None,
        seller_price_difference_from_median=money(seller_price - median),
        seller_price_percentile=seller_percentile,
        competitor_count=len(prices),
        in_stock_competitor_count=in_stock,
        out_of_stock_competitor_count=out_of_stock,
    )


def percentile(sorted_values: list[Decimal], fraction: Decimal) -> Decimal:
    if not sorted_values:
        raise ValueError("percentile requires at least one value")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = fraction * Decimal(len(sorted_values) - 1)
    lower_index = int(position.to_integral_value(rounding=ROUND_FLOOR))
    upper_index = int(position.to_integral_value(rounding=ROUND_CEILING))
    if lower_index == upper_index:
        return sorted_values[lower_index]
    lower = sorted_values[lower_index]
    upper = sorted_values[upper_index]
    weight = position - Decimal(lower_index)
    return lower + ((upper - lower) * weight)


def weighted_market_price(
    snapshots: list[CompetitorSnapshot],
    rankings: dict[UUID, CompetitorRanking],
) -> Decimal | None:
    weighted_sum = Decimal("0")
    weight_total = Decimal("0")
    for snapshot in snapshots:
        if snapshot.price is None or Decimal(snapshot.price) <= 0:
            continue
        ranking = rankings.get(snapshot.competitor_id)
        if not ranking or ranking.total_score <= 0:
            continue
        weight = Decimal(ranking.total_score)
        weighted_sum += Decimal(snapshot.price) * weight
        weight_total += weight
    if weight_total <= 0:
        return None
    return weighted_sum / weight_total


def calculate_demand_score(
    *,
    daily_sales_rate: Decimal | None,
    recent_net_sales: int | None,
    product_age_days: int | None,
    competitor_count: int,
    in_stock_competitor_count: int,
    out_of_stock_competitor_count: int,
    velocity_status: SalesVelocityDataStatus | None,
    config: PricingAnalyticsConfig,
) -> DemandScore:
    if daily_sales_rate is None or velocity_status == SalesVelocityDataStatus.INSUFFICIENT:
        return DemandScore(
            score=None,
            status=PricingAnalyticsDataStatus.INSUFFICIENT,
            confidence=Decimal("30.00"),
            components={"missing": "valid_sales_velocity"},
        )
    velocity_score = min(Decimal("100"), (daily_sales_rate / config.demand_velocity_reference_units_per_day) * Decimal("100"))
    sales_score = min(
        Decimal("100"),
        (Decimal(recent_net_sales or 0) / config.demand_recent_sales_reference_units) * Decimal("100"),
    )
    # v2: UNKNOWN stock (scraper default) is not evidence of a stockout; ratio uses known statuses only.
    known_stock_count = in_stock_competitor_count + out_of_stock_competitor_count
    availability_score = Decimal("50")
    if known_stock_count > 0:
        availability_score = Decimal(out_of_stock_competitor_count) / Decimal(known_stock_count) * Decimal("100")
    maturity_score = min(Decimal("100"), (Decimal(product_age_days or 0) / Decimal("30")) * Decimal("100"))
    score = (
        velocity_score * config.demand_velocity_weight
        + sales_score * config.demand_recent_sales_weight
        + availability_score * config.demand_competitor_availability_weight
        + maturity_score * config.demand_product_maturity_weight
    ) / Decimal("100")
    status = PricingAnalyticsDataStatus.SUFFICIENT if velocity_status == SalesVelocityDataStatus.SUFFICIENT else PricingAnalyticsDataStatus.LIMITED
    confidence = Decimal("85.00") if status == PricingAnalyticsDataStatus.SUFFICIENT else Decimal("60.00")
    return DemandScore(
        score=score.quantize(SCORE_QUANT, rounding=ROUND_HALF_UP),
        status=status,
        confidence=confidence,
        components={
            "velocity_score": str(velocity_score.quantize(SCORE_QUANT, rounding=ROUND_HALF_UP)),
            "recent_sales_score": str(sales_score.quantize(SCORE_QUANT, rounding=ROUND_HALF_UP)),
            "competitor_availability_score": str(availability_score.quantize(SCORE_QUANT, rounding=ROUND_HALF_UP)),
            "competitor_availability": "known" if known_stock_count > 0 else "unknown",
            "competitor_stock_known_count": known_stock_count,
            "competitor_stock_unknown_count": max(0, competitor_count - known_stock_count),
            "product_maturity_score": str(maturity_score.quantize(SCORE_QUANT, rounding=ROUND_HALF_UP)),
            "weights": {
                "velocity": str(config.demand_velocity_weight),
                "recent_sales": str(config.demand_recent_sales_weight),
                "competitor_availability": str(config.demand_competitor_availability_weight),
                "product_maturity": str(config.demand_product_maturity_weight),
            },
        },
    )


def determine_data_status(
    *,
    run_exists: bool,
    run_fresh: bool,
    has_competitor_prices: bool,
    inventory_exists: bool,
    inventory_fresh: bool,
    velocity_exists: bool,
    velocity_fresh: bool,
    velocity_usable: bool,
) -> PricingAnalyticsDataStatus:
    if (run_exists and not run_fresh) or (inventory_exists and not inventory_fresh) or (velocity_exists and not velocity_fresh):
        return PricingAnalyticsDataStatus.STALE
    if has_competitor_prices and inventory_exists and inventory_fresh and velocity_usable:
        return PricingAnalyticsDataStatus.SUFFICIENT
    if has_competitor_prices or (inventory_exists and inventory_fresh) or velocity_usable:
        return PricingAnalyticsDataStatus.LIMITED
    return PricingAnalyticsDataStatus.INSUFFICIENT


def calculate_confidence(
    *,
    data_status: PricingAnalyticsDataStatus,
    demand_confidence: Decimal,
    run_fresh: bool,
    inventory_fresh: bool,
    velocity_fresh: bool,
    competitor_count: int,
) -> Decimal:
    base = {
        PricingAnalyticsDataStatus.SUFFICIENT: Decimal("80"),
        PricingAnalyticsDataStatus.LIMITED: Decimal("55"),
        PricingAnalyticsDataStatus.INSUFFICIENT: Decimal("25"),
        PricingAnalyticsDataStatus.STALE: Decimal("35"),
    }[data_status]
    freshness_bonus = Decimal("0")
    freshness_bonus += Decimal("5") if run_fresh else Decimal("0")
    freshness_bonus += Decimal("5") if inventory_fresh else Decimal("0")
    freshness_bonus += Decimal("5") if velocity_fresh else Decimal("0")
    competitor_bonus = min(Decimal("5"), Decimal(competitor_count))
    score = (base + freshness_bonus + competitor_bonus + demand_confidence) / Decimal("2")
    return max(Decimal("0"), min(Decimal("100"), score)).quantize(SCORE_QUANT, rounding=ROUND_HALF_UP)


def fee_inputs_from_policy(policy) -> FeeInputs:
    return FeeInputs(
        percentage_commission_rate=Decimal(str(policy.percentage_commission_rate)),
        payment_fee_rate=Decimal(str(policy.payment_fee_rate)),
        fixed_per_order_fee=Decimal(str(policy.fixed_per_order_fee)),
        fixed_per_unit_fee=Decimal(str(policy.fixed_per_unit_fee)),
        fulfilment_fee=Decimal(str(policy.fulfilment_fee)),
        shipping_subsidy=Decimal(str(policy.shipping_subsidy)),
        other_variable_cost=Decimal(str(policy.other_variable_cost)),
    )


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _is_fresh(source_time: datetime | None, timestamp: datetime, max_age: timedelta) -> bool:
    if source_time is None:
        return False
    source = _ensure_utc(source_time)
    return source <= timestamp and timestamp - source <= max_age


def _freshness_payload(source_time: datetime | None, timestamp: datetime, max_age: timedelta, is_fresh: bool) -> dict[str, object]:
    if source_time is None:
        return {"available": False, "is_fresh": False, "max_age_seconds": int(max_age.total_seconds())}
    source = _ensure_utc(source_time)
    return {
        "available": True,
        "is_fresh": is_fresh,
        "source_time": source.isoformat(),
        "age_seconds": int((timestamp - source).total_seconds()) if timestamp >= source else None,
        "max_age_seconds": int(max_age.total_seconds()),
    }


def _dedupe_key(
    *,
    seller_id: UUID,
    product_id: UUID,
    calculation_version: str,
    source_ids: list[UUID | None],
    current_price: Decimal,
    unit_cost: Decimal,
) -> str:
    raw = "|".join(
        [
            str(seller_id),
            str(product_id),
            calculation_version,
            *[str(item) if item else "none" for item in source_ids],
            str(current_price),
            str(unit_cost),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
