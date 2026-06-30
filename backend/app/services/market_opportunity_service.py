from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import logging
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.competitor_event import CompetitorEvent, CompetitorEventType
from app.models.market_opportunity import (
    MarketOpportunity,
    MarketOpportunityAction,
    MarketOpportunityLevel,
    MarketOpportunityStatus,
    MarketOpportunityType,
)
from app.models.product import Product
from app.repositories.market_opportunity_repository import MarketOpportunityRepository

logger = logging.getLogger(__name__)
SCORE_QUANT = Decimal("0.0001")
MONEY_QUANT = Decimal("0.01")


@dataclass(frozen=True)
class MarketOpportunityWeights:
    trigger_impact: Decimal
    competitor_strength: Decimal
    stock_readiness: Decimal
    price_readiness: Decimal
    data_confidence: Decimal

    @classmethod
    def from_settings(cls) -> "MarketOpportunityWeights":
        return cls(
            Decimal(str(settings.market_opportunity_trigger_impact_weight)),
            Decimal(str(settings.market_opportunity_competitor_strength_weight)),
            Decimal(str(settings.market_opportunity_stock_readiness_weight)),
            Decimal(str(settings.market_opportunity_price_readiness_weight)),
            Decimal(str(settings.market_opportunity_data_confidence_weight)),
        )

    def validate(self) -> None:
        values = [
            self.trigger_impact,
            self.competitor_strength,
            self.stock_readiness,
            self.price_readiness,
            self.data_confidence,
        ]
        if any(value < 0 for value in values):
            raise ValueError("Market opportunity weights cannot be negative.")
        if sum(values, Decimal("0")) != Decimal("100"):
            raise ValueError("Market opportunity weights must total 100.")


@dataclass(frozen=True)
class MarketOpportunityConfig:
    weights: MarketOpportunityWeights
    high_threshold: Decimal
    medium_threshold: Decimal
    window_days: int
    calculation_version: str
    ranking_formula_version: str

    @classmethod
    def from_settings(cls) -> "MarketOpportunityConfig":
        return cls(
            weights=MarketOpportunityWeights.from_settings(),
            high_threshold=Decimal(str(settings.market_opportunity_high_threshold)),
            medium_threshold=Decimal(str(settings.market_opportunity_medium_threshold)),
            window_days=settings.market_opportunity_window_days,
            calculation_version=settings.market_opportunity_formula_version,
            ranking_formula_version=settings.competitor_ranking_formula_version,
        )

    def validate(self) -> None:
        self.weights.validate()
        if not (Decimal("0") <= self.medium_threshold <= self.high_threshold <= Decimal("100")):
            raise ValueError("Market opportunity thresholds must satisfy 0 <= medium <= high <= 100.")
        if self.window_days <= 0:
            raise ValueError("Market opportunity window must be positive.")


@dataclass(frozen=True)
class MarketOpportunityGenerationResult:
    scrape_run_id: UUID
    created_count: int
    skipped_count: int
    failed_count: int
    skipped_reason: str | None = None


class MarketOpportunityService:
    def __init__(
        self,
        db: Session,
        *,
        config: MarketOpportunityConfig | None = None,
        log: logging.Logger | None = None,
    ) -> None:
        self._db = db
        self._config = config or MarketOpportunityConfig.from_settings()
        self._config.validate()
        self._repo = MarketOpportunityRepository(db)
        self._log = log or logger

    def generate_for_scrape_run(self, scrape_run_id: UUID) -> MarketOpportunityGenerationResult:
        scrape_run = self._repo.get_completed_run(scrape_run_id)
        if scrape_run is None:
            return MarketOpportunityGenerationResult(scrape_run_id, 0, 0, 0, "not_completed")

        product = self._repo.product(scrape_run.product_id)
        if product is None:
            return MarketOpportunityGenerationResult(scrape_run_id, 0, 0, 1, "product_missing")

        events = self._repo.trigger_events_for_run(scrape_run.id)
        existing = self._repo.existing_trigger_ids([event.id for event in events])
        rankings = self._repo.rankings_for_run(scrape_run.id, self._config.ranking_formula_version)
        opportunities = [
            self._build_opportunity(event=event, product=product, competitor_ranking=rankings.get(event.competitor_id))
            for event in events
            if event.id not in existing
        ]
        opportunities = [item for item in opportunities if item is not None]
        self._repo.add_all(opportunities)
        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            existing = self._repo.existing_trigger_ids([event.id for event in events])
            opportunities = [item for item in opportunities if item.trigger_event_id not in existing]
            self._repo.add_all(opportunities)
            self._db.commit()

        skipped = len(events) - len(opportunities)
        self._log.info(
            "Market opportunities generated scrape_run_id=%s created=%s skipped=%s",
            scrape_run.id,
            len(opportunities),
            skipped,
        )
        return MarketOpportunityGenerationResult(scrape_run.id, len(opportunities), skipped, 0)

    def acknowledge(self, *, seller_id: UUID, opportunity_id: UUID) -> MarketOpportunity | None:
        opportunity = self._repo.get_for_seller(seller_id=seller_id, opportunity_id=opportunity_id)
        if opportunity is None:
            return None
        opportunity.status = MarketOpportunityStatus.ACKNOWLEDGED
        opportunity.acknowledged_at = _utc_now()
        self._db.commit()
        self._db.refresh(opportunity)
        return opportunity

    def dismiss(self, *, seller_id: UUID, opportunity_id: UUID) -> MarketOpportunity | None:
        opportunity = self._repo.get_for_seller(seller_id=seller_id, opportunity_id=opportunity_id)
        if opportunity is None:
            return None
        opportunity.status = MarketOpportunityStatus.DISMISSED
        opportunity.dismissed_at = _utc_now()
        self._db.commit()
        self._db.refresh(opportunity)
        return opportunity

    def list_opportunities(self, *, seller_id: UUID, product_id: UUID | None, level: str | None, status: str | None, recent_closed: bool, limit: int, offset: int):
        return self._repo.list_opportunities(
            seller_id=seller_id,
            product_id=product_id,
            level=level,
            status=status,
            recent_closed=recent_closed,
            limit=limit,
            offset=offset,
        )

    def get_detail(self, *, seller_id: UUID, opportunity_id: UUID) -> MarketOpportunity | None:
        return self._repo.get_for_seller(seller_id=seller_id, opportunity_id=opportunity_id)

    def _build_opportunity(self, *, event: CompetitorEvent, product: Product, competitor_ranking) -> MarketOpportunity | None:
        opportunity_type = _opportunity_type(event.event_type)
        if opportunity_type is None:
            return None

        trigger_impact = _trigger_impact(event)
        competitor_strength = Decimal(str(competitor_ranking.total_score)) if competitor_ranking else Decimal("35")
        stock_readiness = _stock_readiness(product.stock_quantity)
        price_readiness = _price_readiness(product)
        data_confidence = Decimal("75")
        confidence_penalties = []
        if competitor_ranking is None:
            data_confidence -= Decimal("20")
            confidence_penalties.append("competitor_ranking_missing")
        if not _has_fee_data(product):
            data_confidence -= Decimal("15")
            confidence_penalties.append("marketplace_fee_missing")
        estimated_revenue, revenue_evidence = self._estimate_revenue(
            product=product,
            opportunity_score=None,
            competitor_strength=competitor_strength,
            event_type=event.event_type,
            baseline_daily_units=None,
        )
        if estimated_revenue is None:
            data_confidence -= Decimal("15")

        score = (
            trigger_impact * self._config.weights.trigger_impact / Decimal("100")
            + competitor_strength * self._config.weights.competitor_strength / Decimal("100")
            + stock_readiness * self._config.weights.stock_readiness / Decimal("100")
            + price_readiness * self._config.weights.price_readiness / Decimal("100")
            + max(Decimal("0"), data_confidence) * self._config.weights.data_confidence / Decimal("100")
        ).quantize(SCORE_QUANT, rounding=ROUND_HALF_UP)
        level = _level(score, self._config)
        action = _recommended_action(product=product, event=event, stock_readiness=stock_readiness)
        explanation = _explanation(event.event_type, action, competitor_strength)
        evidence = {
            "event_type": event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type),
            "competitor_market_rank": competitor_ranking.market_rank if competitor_ranking else None,
            "competitor_total_score": str(competitor_strength),
            "seller_stock": product.stock_quantity,
            "seller_price": str(product.selling_price),
            "seller_cost_price": str(product.cost_price) if product.cost_price is not None else None,
            "minimum_margin": str(product.minimum_margin) if product.minimum_margin is not None else None,
            "marketplace_fee_available": _has_fee_data(product),
            "confidence_penalties": confidence_penalties,
            "revenue_estimate": revenue_evidence,
            "calculation_version": self._config.calculation_version,
        }
        return MarketOpportunity(
            seller_id=event.seller_id,
            product_id=event.product_id,
            competitor_id=event.competitor_id,
            trigger_event_id=event.id,
            scrape_run_id=event.scrape_run_id,
            opportunity_type=opportunity_type,
            opportunity_level=level,
            opportunity_score=score,
            estimated_revenue=estimated_revenue,
            estimated_revenue_currency="BDT",
            recommended_action=action,
            explanation=explanation,
            confidence_score=max(Decimal("0"), data_confidence).quantize(SCORE_QUANT),
            evidence=evidence,
            status=MarketOpportunityStatus.OPEN,
            detected_at=event.detected_at,
        )

    def _estimate_revenue(
        self,
        *,
        product: Product,
        opportunity_score: Decimal | None,
        competitor_strength: Decimal,
        event_type,
        baseline_daily_units: Decimal | None,
    ) -> tuple[Decimal | None, dict]:
        if baseline_daily_units is None or baseline_daily_units <= 0:
            return None, {"available": False, "reason": "historical_sales_data_insufficient"}
        capture_rate = _capture_rate(competitor_strength, event_type)
        estimate = (
            baseline_daily_units
            * Decimal(self._config.window_days)
            * capture_rate
            * product.selling_price
        ).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
        return estimate, {
            "available": True,
            "baseline_daily_units": str(baseline_daily_units),
            "window_days": self._config.window_days,
            "capture_rate": str(capture_rate),
            "label": "estimate",
        }


def _opportunity_type(event_type) -> MarketOpportunityType | None:
    value = event_type.value if hasattr(event_type, "value") else str(event_type)
    return {
        "OUT_OF_STOCK": MarketOpportunityType.COMPETITOR_OUT_OF_STOCK,
        "PRICE_RISE": MarketOpportunityType.COMPETITOR_PRICE_RISE,
        "COMPETITOR_REMOVED": MarketOpportunityType.COMPETITOR_REMOVED,
    }.get(value)


def _trigger_impact(event: CompetitorEvent) -> Decimal:
    value = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
    if value in {"OUT_OF_STOCK", "COMPETITOR_REMOVED"}:
        return Decimal("85")
    if value == "PRICE_RISE":
        percent = event.price_change_percent or Decimal("0")
        return min(Decimal("100"), Decimal("45") + Decimal(str(percent)) * Decimal("2"))
    return Decimal("0")


def _stock_readiness(stock: int) -> Decimal:
    if stock <= 0:
        return Decimal("0")
    if stock < 5:
        return Decimal("30")
    if stock < 20:
        return Decimal("70")
    return Decimal("100")


def _price_readiness(product: Product) -> Decimal:
    if product.cost_price is None or product.minimum_margin is None:
        return Decimal("25")
    floor = product.cost_price + product.minimum_margin
    if product.selling_price < floor:
        return Decimal("0")
    return Decimal("80")


def _recommended_action(*, product: Product, event: CompetitorEvent, stock_readiness: Decimal) -> MarketOpportunityAction:
    if stock_readiness <= Decimal("30"):
        return MarketOpportunityAction.REORDER
    if not _has_fee_data(product):
        return MarketOpportunityAction.HOLD
    if product.cost_price is None or product.minimum_margin is None:
        return MarketOpportunityAction.HOLD
    if event.event_type == CompetitorEventType.PRICE_RISE and product.selling_price >= product.cost_price + product.minimum_margin:
        return MarketOpportunityAction.HOLD
    return MarketOpportunityAction.HOLD


def _has_fee_data(product: Product) -> bool:
    return bool((product.specifications or {}).get("marketplace_fee"))


def _capture_rate(competitor_strength: Decimal, event_type) -> Decimal:
    base = Decimal("0.05")
    if (event_type.value if hasattr(event_type, "value") else str(event_type)) in {"OUT_OF_STOCK", "COMPETITOR_REMOVED"}:
        base = Decimal("0.10")
    return min(Decimal("0.30"), base + (competitor_strength / Decimal("1000")))


def _level(score: Decimal, config: MarketOpportunityConfig) -> MarketOpportunityLevel:
    if score >= config.high_threshold:
        return MarketOpportunityLevel.HIGH
    if score >= config.medium_threshold:
        return MarketOpportunityLevel.MEDIUM
    return MarketOpportunityLevel.LOW


def _explanation(event_type, action: MarketOpportunityAction, competitor_strength: Decimal) -> str:
    value = event_type.value if hasattr(event_type, "value") else str(event_type)
    if value == "OUT_OF_STOCK":
        return f"A competitor became unavailable while your product remains eligible for action. Recommended action: {action.value}."
    if value == "PRICE_RISE":
        return f"A competitor raised price; competitor strength score is {competitor_strength}. Recommended action: {action.value}."
    return f"A competitor appears removed after completed scrape confirmation. Recommended action: {action.value}."


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
