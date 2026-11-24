"""Deterministic, seller-scoped demo evidence and workflow orchestration.

This module extends the catalog-oriented demo seed.  It owns only records with
the ``demo-comprehensive-v1`` source namespace and sends no external messages
or marketplace requests.  Derived rows are produced by the application's real
services so the demo exercises the same calculations as ordinary seller data.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json
import random
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.models.competitor import Competitor
from app.models.competitor_event import CompetitorEvent, CompetitorEventType
from app.models.competitor_ranking import CompetitorRanking
from app.models.competitor_snapshot import CompetitorSnapshot
from app.models.copilot import (
    CopilotActionProposal,
    CopilotConversation,
    CopilotMessage,
    CopilotToolCall,
)
from app.models.dead_stock_assessment import DeadStockAssessment
from app.models.dead_stock_capital_recovery import DeadStockCapitalRecoveryEstimate
from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryRecommendation
from app.models.demand_elasticity_estimate import DemandElasticityEstimate
from app.models.dynamic_pricing_recommendation import (
    DynamicPricingAction,
    DynamicPricingRecommendation,
    DynamicPricingRecommendationStatus,
)
from app.models.inventory_aging import InventoryAgingSnapshot
from app.models.inventory_history import InventoryHistory, InventorySnapshotSource
from app.models.inventory_risk import InventoryRiskAssessment, InventoryRiskLevel
from app.models.inventory_stock_in import InventoryStockIn
from app.models.market_opportunity import MarketOpportunity
from app.models.product import Product
from app.models.product_price_history import ProductPriceHistory, ProductPriceHistorySource
from app.models.pricing_policy import PricingPolicy
from app.models.pricing_analytics_snapshot import PricingAnalyticsSnapshot
from app.models.promotion import (
    PromotionPlan,
    PromotionPlanStatus,
    PromotionResult,
    PromotionResultStatus,
)
from app.models.rag_memory import (
    RagMemoryChunk,
    RagMemoryDocument,
    RagMemoryEmbeddingStatus,
    RagQueryLog,
)
from app.models.recommendation import Recommendation, RecommendationAction
from app.models.recommendation_job import RecommendationJob
from app.models.reorder_recommendation import ReorderRecommendation
from app.models.sales_data_coverage import SalesDataCompletenessStatus, SalesDataCoverage
from app.models.sales_record import SalesRecord, SalesRecordPriceSource, SalesRecordStatus
from app.models.sales_velocity import SalesVelocity
from app.models.scrape_run import ScrapeRun
from app.models.seller import Seller
from app.models.stockout_prediction import StockoutPrediction
from app.models.telegram_inventory_alert import TelegramInventoryAlert
from app.services.competitor_event_service import CompetitorEventService
from app.services.competitor_ranking_service import CompetitorRankingService
from app.services.dead_stock_capital_recovery_service import DeadStockCapitalRecoveryService
from app.services.dead_stock_recovery_service import DeadStockRecoveryService
from app.services.dead_stock_service import DeadStockService
from app.services.demand_response_service import DemandResponseService
from app.services.demo_seed_service import (
    DEMO_EMAIL,
    MARKETPLACE,
    SEED_NAME as CATALOG_SEED_NAME,
    DemoSeedConflictError,
    DemoSeedSafetyError,
    assert_safe_seed_environment,
)
from app.services.dynamic_pricing_service import DynamicPricingService
from app.services.inventory_aging_service import InventoryAgingService
from app.services.inventory_intelligence_service import InventoryIntelligenceService
from app.services.inventory_risk_service import InventoryRiskService
from app.services.market_opportunity_service import MarketOpportunityService
from app.services.pricing_analytics_service import PricingAnalyticsService
from app.services.rag_memory_backfill_service import RagMemoryBackfillService
from app.services.reorder_recommendation_service import ReorderRecommendationService
from app.services.sales_velocity_service import SalesVelocityService
from app.services.stockout_prediction_service import StockoutPredictionService


SEED_NAMESPACE = "demo-comprehensive-v1"
DEMO_SUPPLIER = "Patuatuli Watch Wholesale, Dhaka"
# Generic demo seller labels; competitor URLs stay on demo.invalid so nothing looks like a real observed listing.
COMPETITOR_STORES = ("Time Square BD", "Watch Hub Dhaka", "Ghori Bazar", "Classic Time Store")
COMPETITOR_VARIANTS = ("similar model", "alternate colour", "copy model", "older stock")
RANDOM_SEED = 1622
HISTORY_DAYS = 120
INVENTORY_DAYS = 45
DEMO_CALCULATION_VERSION = "demo-comp-v5"


@dataclass(frozen=True)
class DemoScenario:
    code: str
    label: str
    demand: str
    on_hand: int
    reserved: int
    incoming: int
    lead_days: int
    moq: int
    pack_size: int
    age_days: int
    pricing_intent: str
    coverage: SalesDataCompletenessStatus = SalesDataCompletenessStatus.COMPLETE


SCENARIOS: tuple[DemoScenario, ...] = (
    DemoScenario("P01", "healthy_strong_sales", "high", 180, 4, 0, 7, 12, 6, 24, "HOLD"),
    DemoScenario("P02", "healthy_missing_fee_evidence", "medium", 130, 3, 0, 8, 12, 6, 32, "HOLD"),
    DemoScenario("P03", "low_stock_strong_demand", "high", 9, 2, 0, 12, 18, 6, 52, "HOLD"),
    DemoScenario("P04", "low_stock_increasing_demand", "increasing", 7, 1, 0, 10, 12, 6, 64, "HOLD"),
    DemoScenario("P05", "reorder_incoming_moq_pack", "high", 10, 2, 18, 14, 24, 6, 48, "HOLD"),
    DemoScenario("P06", "critical_near_stockout", "high", 2, 1, 0, 12, 18, 6, 75, "HOLD"),
    DemoScenario("P07", "already_out_of_stock", "intermittent", 0, 0, 0, 15, 24, 6, 90, "HOLD"),
    DemoScenario("P08", "slow_promotion_distorted", "low", 64, 3, 0, 9, 12, 6, 145, "LOWER"),
    DemoScenario("P09", "no_recent_demand", "no_recent", 70, 2, 0, 10, 12, 6, 175, "LOWER"),
    DemoScenario("P10", "aging_capital_recovery", "declining", 82, 1, 0, 12, 12, 6, 220, "LOWER"),
    DemoScenario("P11", "competitive_price_lower", "medium", 34, 2, 0, 7, 12, 6, 40, "LOWER"),
    DemoScenario("P12", "excess_stock_price_lower", "seasonal", 54, 2, 0, 8, 12, 6, 86, "LOWER"),
    DemoScenario("P13", "strong_demand_price_raise", "high", 26, 2, 0, 7, 12, 6, 28, "RAISE"),
    DemoScenario("P14", "scarce_market_price_raise", "increasing", 20, 1, 0, 9, 12, 6, 38, "RAISE"),
    DemoScenario(
        "P15", "insufficient_sales_evidence", "sparse", 38, 2, 0, 10, 12, 6, 55,
        "INSUFFICIENT_DATA", SalesDataCompletenessStatus.UNKNOWN,
    ),
    DemoScenario("P16", "steady_budget_seller", "medium", 64, 3, 0, 6, 24, 12, 30, "HOLD"),
    DemoScenario("P17", "rising_demand_healthy", "increasing", 45, 2, 12, 9, 12, 6, 42, "HOLD"),
    DemoScenario("P18", "seasonal_gift_clock", "seasonal", 40, 1, 0, 12, 12, 6, 60, "HOLD"),
    DemoScenario("P19", "declining_aged_premium", "declining", 58, 1, 0, 14, 12, 6, 160, "LOWER"),
    DemoScenario("P20", "intermittent_gift_box", "intermittent", 22, 1, 0, 10, 12, 6, 70, "HOLD"),
    DemoScenario("P21", "best_seller_price_raise", "high", 30, 3, 0, 8, 12, 6, 26, "RAISE"),
    DemoScenario("P22", "low_stock_reorder_now", "high", 6, 1, 0, 11, 24, 12, 50, "HOLD"),
    DemoScenario("P23", "healthy_steady_mid_range", "medium", 38, 2, 0, 8, 12, 6, 36, "HOLD"),
    DemoScenario("P24", "dead_stock_no_recent_sales", "no_recent", 72, 0, 0, 12, 12, 6, 200, "LOWER"),
    DemoScenario("P25", "new_arrival_rising", "increasing", 80, 4, 0, 7, 24, 12, 10, "HOLD"),
)


@dataclass
class ComprehensiveDemoReport:
    mode: str
    as_of_date: str
    seller_id: str | None = None
    product_count: int = 0
    created: dict[str, int] = field(default_factory=dict)
    totals: dict[str, Any] = field(default_factory=dict)
    workflows: dict[str, Any] = field(default_factory=dict)
    scenarios: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def bump(self, name: str, count: int = 1) -> None:
        self.created[name] = self.created.get(name, 0) + count

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ComprehensiveDemoSeedService:
    """Seed supporting evidence, execute workflows, and report observed state."""

    def __init__(self, db: Session, *, as_of_date: date) -> None:
        self.db = db
        self.as_of = as_of_date
        self.timestamp = datetime.combine(
            as_of_date, time(hour=18), tzinfo=timezone(timedelta(hours=6))
        ).astimezone(timezone.utc)

    def run(
        self,
        *,
        apply: bool,
        validate_only: bool = False,
        skip_external_services: bool = True,
    ) -> ComprehensiveDemoReport:
        assert_safe_seed_environment(apply=apply)
        report = ComprehensiveDemoReport(
            mode="VALIDATE_ONLY" if validate_only else ("APPLY" if apply else "DRY_RUN"),
            as_of_date=self.as_of.isoformat(),
        )
        seller, products = self._resolve_scope()
        report.seller_id = str(seller.id)
        report.product_count = len(products)
        if not apply or validate_only:
            return self.validate(seller=seller, products=products, report=report)

        try:
            self._seed_source_evidence(seller=seller, products=products, report=report)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        self._run_workflows(seller=seller, products=products, report=report)
        if skip_external_services:
            report.warnings.append(
                "External Groq/Copilot and embedding-provider execution was skipped; "
                "local RAG documents/chunks were still built where supported."
            )
        return self.validate(seller=seller, products=products, report=report)

    def _resolve_scope(self) -> tuple[Seller, list[Product]]:
        seller = self.db.scalar(
            select(Seller).where(func.lower(Seller.email) == DEMO_EMAIL)
        )
        if seller is None:
            raise DemoSeedSafetyError(
                f"Run the catalog demo seed first so the demo seller and its {len(SCENARIOS)} products exist."
            )
        products = list(
            self.db.scalars(
                select(Product)
                .where(Product.seller_id == seller.id)
                .order_by(Product.sku.asc().nulls_last(), Product.id.asc())
            )
        )
        if len(products) != len(SCENARIOS):
            raise DemoSeedConflictError(
                f"Expected exactly {len(SCENARIOS)} existing demo products; found {len(products)}."
            )
        return seller, products

    def _seed_source_evidence(
        self, *, seller: Seller, products: list[Product], report: ComprehensiveDemoReport
    ) -> None:
        for index, (product, scenario) in enumerate(zip(products, SCENARIOS, strict=True)):
            self._apply_product_scenario(product, scenario)
            self._configure_pricing_policy(seller, product, scenario)
            self._seed_sales(seller, product, scenario, index, report)
            self._seed_inventory(seller, product, scenario, index, report)
            self._seed_price_history(seller, product, scenario, report)
            self._seed_promotions(seller, product, scenario, report)
            self._seed_competitors(seller, product, scenario, index, report)

    def _apply_product_scenario(self, product: Product, scenario: DemoScenario) -> None:
        # These catalog rows are seed-owned and the requested history predates
        # their initial import.  Backdating the synthetic catalog availability
        # keeps product-age based coverage calculations internally consistent.
        synthetic_created_at = self.timestamp - timedelta(days=240)
        if product.created_at is None or product.created_at > synthetic_created_at:
            product.created_at = synthetic_created_at
        product.stock_quantity = scenario.on_hand
        product.supplier_lead_time = scenario.lead_days
        specs = dict(product.specifications or {})
        specs.update(
            {
                "demo_scenario_code": scenario.code,
                "demo_scenario": scenario.label,
                "demo_data_class": "SYNTHETIC_DEMO_BUSINESS_DATA",
                "quantity_reserved": str(scenario.reserved),
                "quantity_incoming_unconfirmed": str(scenario.incoming),
                "confirmed_incoming_quantity": str(scenario.incoming),
                "minimum_order_quantity": str(scenario.moq),
                "pack_size": str(scenario.pack_size),
                "safety_buffer_days": "7",
                "review_period_days": "14",
            }
        )
        product.specifications = specs

    def _configure_pricing_policy(
        self, seller: Seller, product: Product, scenario: DemoScenario
    ) -> None:
        policy = self.db.scalar(
            select(PricingPolicy).where(
                PricingPolicy.seller_id == seller.id,
                PricingPolicy.product_id == product.id,
                PricingPolicy.marketplace == MARKETPLACE,
                PricingPolicy.is_active.is_(True),
            )
        )
        if policy is None:
            return
        if scenario.code == "P08":
            # The lower market candidates remain present, but the real
            # MarginGuard must reject candidates below this seller floor.
            policy.minimum_allowed_price = _money(
                Decimal(product.selling_price) * Decimal("0.97")
            )
        elif scenario.code == "P02":
            # Keep the inventory healthy while demonstrating a deterministic
            # pricing HOLD: the seller has not authorized movement outside the
            # currently listed price until fee evidence is reviewed.
            policy.minimum_allowed_price = _money(Decimal(product.selling_price))
            policy.maximum_allowed_price = _money(Decimal(product.selling_price))

    def _seed_sales(
        self,
        seller: Seller,
        product: Product,
        scenario: DemoScenario,
        index: int,
        report: ComprehensiveDemoReport,
    ) -> None:
        """One SalesRecord per Daraz order line, keyed by a deterministic order number."""
        rng = random.Random(RANDOM_SEED + index)
        start = self.as_of - timedelta(days=HISTORY_DAYS)
        base_price = Decimal(product.selling_price)
        listing_id = (product.specifications or {}).get("source_listing_id")
        price_factors = (
            Decimal("0.94"), Decimal("0.97"), Decimal("1.00"), Decimal("1.03"),
            Decimal("0.96"), Decimal("1.02"), Decimal("0.90"), Decimal("1.00"),
        )
        valid_count = invalid_count = 0
        for offset in range(HISTORY_DAYS):
            day = start + timedelta(days=offset)
            quantity = self._daily_quantity(scenario.demand, offset, rng)
            if scenario.code == "P15":
                quantity = 1 if offset in {10, 41, 60, 73} else 0
            factor = price_factors[min(offset // 15, 7)]
            if scenario.pricing_intent == "LOWER" and scenario.demand != "no_recent":
                if factor <= Decimal("0.94"):
                    quantity = max(3, quantity + 2)
                elif factor >= Decimal("1.02") and quantity:
                    quantity = 1
            # Marketplace prices are whole taka.
            price = _money((base_price * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            # P08 contains a labelled promotion period (see _seed_promotions).
            if scenario.code == "P08" and 98 <= offset <= 106:
                price = _money((base_price * Decimal("0.82")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                quantity += 2
            lines: list[tuple[int, SalesRecordStatus]] = []
            remaining = quantity
            while remaining > 0:
                units = 2 if remaining >= 2 and rng.random() < 0.15 else 1
                lines.append(
                    (units, SalesRecordStatus.FULFILLED if rng.random() < 0.35 else SalesRecordStatus.COMPLETED)
                )
                remaining -= units
            # Roughly 4% of orders are cancelled or fail payment; they must not count as demand.
            if rng.random() < 0.04 * max(1, quantity) and scenario.code != "P15":
                lines.append(
                    (1, SalesRecordStatus.CANCELLED if rng.random() < 0.6 else SalesRecordStatus.FAILED_PAYMENT)
                )
            for line_no, (units, status) in enumerate(lines):
                order_number = _order_number(seller.id, product.id, day, line_no)
                sold_at = datetime.combine(
                    day,
                    time(hour=rng.randint(8, 23), minute=rng.randint(0, 59), second=rng.randint(0, 59)),
                    tzinfo=timezone(timedelta(hours=6)),
                ).astimezone(timezone.utc)
                excluded = status in {SalesRecordStatus.CANCELLED, SalesRecordStatus.FAILED_PAYMENT}
                returned = 1 if not excluded and units >= 2 and offset % 29 == 0 else 0
                if excluded:
                    invalid_count += 1
                else:
                    valid_count += 1
                if self.db.scalar(
                    select(SalesRecord.id).where(
                        SalesRecord.seller_id == seller.id,
                        SalesRecord.source_reference == order_number,
                    )
                ):
                    continue
                self.db.add(
                    SalesRecord(
                        seller_id=seller.id,
                        product_id=product.id,
                        source_reference=order_number,
                        status=status,
                        sold_at=sold_at,
                        quantity_sold=units,
                        unit_price=price,
                        line_total=_money(price * units),
                        currency="BDT",
                        marketplace_listing_id=listing_id,
                        price_source=SalesRecordPriceSource.IMPORTED_TRANSACTION,
                        returned_units=returned,
                        refunded_restocked_units=returned if offset % 58 == 0 else 0,
                        is_test_order=False,
                    )
                )
                report.bump("excluded_sales_records" if excluded else "sales_records")

        coverage_source = f"{SEED_NAMESPACE}:{self.as_of}:{scenario.code}"
        coverage = self.db.scalar(
            select(SalesDataCoverage).where(
                SalesDataCoverage.seller_id == seller.id,
                SalesDataCoverage.product_id == product.id,
                SalesDataCoverage.source == coverage_source,
            )
        )
        if coverage is None:
            coverage = SalesDataCoverage(
                    seller_id=seller.id,
                    product_id=product.id,
                    marketplace=None,
                    source=coverage_source,
                    coverage_start_date=start,
                    coverage_end_date=self.as_of - timedelta(days=1),
                    completeness_status=scenario.coverage,
                    imported_record_count=valid_count + invalid_count,
                    valid_sales_count=valid_count,
                    invalid_or_excluded_count=invalid_count,
                    last_imported_at=self.timestamp,
                    notes=(
                        f"Daraz Seller Center order export, {start:%d %b} to "
                        f"{self.as_of - timedelta(days=1):%d %b %Y}. Days without orders are "
                        "observed zero-sales days."
                        if scenario.coverage == SalesDataCompletenessStatus.COMPLETE
                        else "Partial order export; coverage unknown, so gaps are not zero demand."
                    ),
                )
            self.db.add(coverage)
            report.bump("sales_data_coverage")
        else:
            coverage.imported_record_count = valid_count + invalid_count
            coverage.valid_sales_count = valid_count
            coverage.invalid_or_excluded_count = invalid_count
            coverage.last_imported_at = self.timestamp

    def _seed_inventory(
        self,
        seller: Seller,
        product: Product,
        scenario: DemoScenario,
        index: int,
        report: ComprehensiveDemoReport,
    ) -> None:
        start = self.as_of - timedelta(days=INVENTORY_DAYS - 1)
        for offset in range(INVENTORY_DAYS):
            snapshot_date = start + timedelta(days=offset)
            remaining = INVENTORY_DAYS - 1 - offset
            if scenario.demand in {"low", "no_recent", "declining"}:
                on_hand = scenario.on_hand + remaining // 18
            else:
                on_hand = scenario.on_hand + remaining // 3
            reserved = min(scenario.reserved, on_hand)
            incoming = scenario.incoming if offset >= INVENTORY_DAYS - 5 else 0
            ref = f"{SEED_NAMESPACE}:inventory:{self.as_of}:{scenario.code}:{snapshot_date}"
            existing = self.db.scalar(
                select(InventoryHistory).where(
                    InventoryHistory.seller_id == seller.id,
                    InventoryHistory.product_id == product.id,
                    InventoryHistory.snapshot_date == snapshot_date,
                )
            )
            values = {
                "captured_at": _dhaka_evening(snapshot_date),
                "quantity_on_hand": on_hand,
                "quantity_reserved": reserved,
                "quantity_available": on_hand - reserved,
                "quantity_incoming": incoming,
                "source": InventorySnapshotSource.BACKFILL,
                "source_reference": ref,
                "content_hash": _hash(ref, on_hand, reserved, incoming),
            }
            if existing is None:
                self.db.add(
                    InventoryHistory(
                        seller_id=seller.id,
                        product_id=product.id,
                        snapshot_date=snapshot_date,
                        **values,
                    )
                )
                report.bump("inventory_history")
            elif (existing.source_reference or "").startswith((SEED_NAMESPACE, CATALOG_SEED_NAME)):
                for key, value in values.items():
                    setattr(existing, key, value)

        for sequence, days_ago in enumerate((scenario.age_days, min(scenario.age_days, 35))):
            received_at = self.timestamp - timedelta(days=days_ago)
            ref = f"PO-WW-{received_at:%y%m%d}-{index + 1:02d}{sequence + 1}"
            if self.db.scalar(
                select(InventoryStockIn.id).where(
                    InventoryStockIn.seller_id == seller.id,
                    InventoryStockIn.source_reference == ref,
                )
            ):
                continue
            quantity = max(1, scenario.on_hand // 2) if sequence else max(1, scenario.on_hand)
            self.db.add(
                InventoryStockIn(
                    seller_id=seller.id,
                    product_id=product.id,
                    quantity=quantity,
                    received_at=received_at,
                    unit_cost=product.cost_price,
                    currency="BDT",
                    source_reference=ref,
                    notes=f"Received from {DEMO_SUPPLIER}; counted and shelved.",
                )
            )
            report.bump("inventory_stock_in")

    def _seed_price_history(
        self, seller: Seller, product: Product, scenario: DemoScenario, report: ComprehensiveDemoReport
    ) -> None:
        current = Decimal(product.selling_price)
        factors = ("0.94", "0.97", "1.00", "1.03", "0.96", "1.02", "0.99", "1.00")
        prior: Decimal | None = None
        for sequence, factor in enumerate(factors):
            changed_at = self.timestamp - timedelta(days=56 - sequence * 8)
            new_price = current if sequence == len(factors) - 1 else _money(current * Decimal(factor))
            reason = f"{SEED_NAMESPACE}:{self.as_of}:{scenario.code}:price:{sequence}"
            if self.db.scalar(
                select(ProductPriceHistory.id).where(
                    ProductPriceHistory.seller_id == seller.id,
                    ProductPriceHistory.product_id == product.id,
                    ProductPriceHistory.reason == reason,
                )
            ):
                prior = new_price
                continue
            self.db.add(
                ProductPriceHistory(
                    seller_id=seller.id,
                    product_id=product.id,
                    marketplace=MARKETPLACE,
                    old_price=prior,
                    new_price=new_price,
                    currency="BDT",
                    reason=reason,
                    source=ProductPriceHistorySource.IMPORT,
                    changed_at=changed_at,
                )
            )
            prior = new_price
            report.bump("product_price_history")

    def _seed_promotions(
        self, seller: Seller, product: Product, scenario: DemoScenario, report: ComprehensiveDemoReport
    ) -> None:
        if scenario.code not in {"P08", "P10", "P12"}:
            return
        title = f"{SEED_NAMESPACE}:{self.as_of}:{scenario.code}:completed"
        plan = self.db.scalar(
            select(PromotionPlan).where(
                PromotionPlan.seller_id == seller.id,
                PromotionPlan.product_id == product.id,
                PromotionPlan.title == title,
            )
        )
        if plan is None:
            price = _money(Decimal(product.selling_price) * Decimal("0.85"))
            plan = PromotionPlan(
                seller_id=seller.id,
                product_id=product.id,
                marketplace=MARKETPLACE,
                promotion_type="DEMO_PERCENT_DISCOUNT",
                title=title,
                description="Synthetic completed promotion used to demonstrate distortion-aware evidence.",
                proposed_discount_rate=Decimal("0.15"),
                proposed_price=price,
                planned_start_at=self.timestamp - timedelta(days=22),
                planned_end_at=self.timestamp - timedelta(days=14),
                status=PromotionPlanStatus.COMPLETED,
                source="SYNTHETIC_DEMO",
                safety_checks_json={"external_execution": False, "synthetic": True},
                expected_impact_json={"evidence_only": True},
            )
            self.db.add(plan)
            self.db.flush()
            report.bump("promotion_plans")
        else:
            plan.planned_start_at = self.timestamp - timedelta(days=22)
            plan.planned_end_at = self.timestamp - timedelta(days=14)
        existing_result = self.db.scalar(
            select(PromotionResult).where(PromotionResult.promotion_plan_id == plan.id)
        )
        if existing_result is None:
            units = 22
            revenue = _money(Decimal(plan.proposed_price or product.selling_price) * units)
            profit = _money(revenue - Decimal(product.cost_price or 0) * units - Decimal("250"))
            self.db.add(
                PromotionResult(
                    seller_id=seller.id,
                    promotion_plan_id=plan.id,
                    product_id=product.id,
                    marketplace=MARKETPLACE,
                    started_at=plan.planned_start_at,
                    ended_at=plan.planned_end_at,
                    units_sold=units,
                    gross_revenue=revenue,
                    estimated_profit=profit,
                    spend=Decimal("250.00"),
                    discount_cost=_money(Decimal(product.selling_price) * Decimal("0.15") * units),
                    roi=_money(profit / Decimal("250")),
                    result_status=PromotionResultStatus.CALCULATED,
                    evidence_json={"synthetic": True, "formula": "(profit-spend)/spend"},
                    missing_data_json={},
                )
            )
            report.bump("promotion_results")
        else:
            if plan.planned_start_at is not None:
                existing_result.started_at = plan.planned_start_at
            existing_result.ended_at = plan.planned_end_at

        if scenario.code == "P12":
            scheduled_title = f"{SEED_NAMESPACE}:{self.as_of}:{scenario.code}:scheduled"
            scheduled = self.db.scalar(
                select(PromotionPlan).where(
                    PromotionPlan.seller_id == seller.id,
                    PromotionPlan.product_id == product.id,
                    PromotionPlan.title == scheduled_title,
                )
            )
            scheduled_values = {
                "planned_start_at": self.timestamp + timedelta(days=2),
                "planned_end_at": self.timestamp + timedelta(days=9),
                "status": PromotionPlanStatus.SCHEDULED,
            }
            if scheduled is None:
                self.db.add(
                    PromotionPlan(
                        seller_id=seller.id,
                        product_id=product.id,
                        marketplace=MARKETPLACE,
                        promotion_type="DEMO_PERCENT_DISCOUNT",
                        title=scheduled_title,
                        description=(
                            "Synthetic scheduled proposal for UI demonstration only; "
                            "no marketplace action is executed."
                        ),
                        proposed_discount_rate=Decimal("0.10"),
                        proposed_price=_money(
                            Decimal(product.selling_price) * Decimal("0.90")
                        ),
                        source="SYNTHETIC_DEMO",
                        safety_checks_json={
                            "external_execution": False,
                            "proposal_only": True,
                            "synthetic": True,
                        },
                        expected_impact_json={"evidence_only": True},
                        **scheduled_values,
                    )
                )
                report.bump("promotion_plans")
            else:
                for key, value in scheduled_values.items():
                    setattr(scheduled, key, value)

    def _seed_competitors(
        self,
        seller: Seller,
        product: Product,
        scenario: DemoScenario,
        index: int,
        report: ComprehensiveDemoReport,
    ) -> None:
        competitors: dict[int, Competitor] = {}
        base = Decimal(product.selling_price)
        run_count = 5 if scenario.code in {"P01", "P02", "P15"} else 4
        for run_index in range(run_count):
            run_key = f"{SEED_NAMESPACE}:{self.as_of}:{scenario.code}:run:{run_index}"
            run = self.db.scalar(
                select(ScrapeRun).where(
                    ScrapeRun.seller_id == seller.id,
                    ScrapeRun.product_id == product.id,
                    ScrapeRun.marketplace == MARKETPLACE,
                    ScrapeRun.run_key == run_key,
                )
            )
            # Never future-date runs: the latest finished_at wins in the competitor list,
            # so a seeded "today 18:00" run would hide real scrapes made earlier today.
            observed_at = min(self.timestamp, datetime.now(timezone.utc)) - timedelta(
                days=(run_count - 1 - run_index) * 7
            )
            if run is None:
                run = ScrapeRun(
                    seller_id=seller.id,
                    product_id=product.id,
                    marketplace=MARKETPLACE,
                    run_key=run_key,
                    status="COMPLETED",
                    started_at=observed_at - timedelta(minutes=2),
                    finished_at=observed_at,
                    completed_at=observed_at,
                    total_results=4,
                    successful_matches=4,
                    discovered_competitor_count=4,
                    snapshot_count=4,
                )
                self.db.add(run)
                self.db.flush()
                report.bump("scrape_runs")
            else:
                run.started_at = observed_at - timedelta(minutes=2)
                run.finished_at = observed_at
                run.completed_at = observed_at

            for competitor_index in range(4):
                external_id = f"demo-{scenario.code.lower()}-{competitor_index + 1}"
                competitor = competitors.get(competitor_index)
                if competitor is None:
                    competitor = self.db.scalar(
                        select(Competitor)
                        .join(CompetitorSnapshot, CompetitorSnapshot.competitor_id == Competitor.id)
                        .where(
                            Competitor.product_id == product.id,
                            CompetitorSnapshot.external_listing_id == external_id,
                            Competitor.marketplace == MARKETPLACE,
                        )
                        .limit(1)
                    )
                if competitor is None:
                    competitor = Competitor(
                        scrape_run_id=run.id,
                        product_id=product.id,
                        competitor_title=f"{product.title} ({COMPETITOR_VARIANTS[competitor_index]})",
                        competitor_description="Comparable listing from another Daraz seller (demo data).",
                        competitor_category=product.category,
                        competitor_brand=(product.specifications or {}).get("brand"),
                        competitor_attributes={"data_class": "DEMO_SYNTHETIC"},
                        competitor_price=base,
                        original_price=_money(base * Decimal("1.10")),
                        discount_percentage=10,
                        competitor_rating=4.0 + competitor_index * 0.2,
                        rating_count=80 + index * 5 + competitor_index * 30,
                        competitor_store=COMPETITOR_STORES[competitor_index],
                        stock_status="IN_STOCK",
                        similarity_score=0.91 - competitor_index * 0.03,
                        title_similarity=0.93,
                        description_similarity=0.85,
                        attribute_similarity=0.88,
                        keyword_score=0.90,
                        ranking_score=0.88,
                        match_confidence=0.92,
                        category_match=True,
                        matched_attributes=["category", "product_type"],
                        marketplace=MARKETPLACE,
                        product_url=f"https://demo.invalid/listings/{external_id}",
                        search_position=competitor_index + 1,
                    )
                    self.db.add(competitor)
                    self.db.flush()
                    report.bump("competitors")
                competitors[competitor_index] = competitor

                # Competitor 4 disappears from the final two completed runs.
                if competitor_index == 3 and run_index >= 2:
                    run.total_results = run.successful_matches = 3
                    run.discovered_competitor_count = run.snapshot_count = 3
                    continue
                if self.db.scalar(
                    select(CompetitorSnapshot.id).where(
                        CompetitorSnapshot.scrape_run_id == run.id,
                        CompetitorSnapshot.competitor_id == competitor.id,
                        CompetitorSnapshot.product_id == product.id,
                    )
                ):
                    continue
                price_factor = Decimal("0.90") + Decimal(competitor_index) * Decimal("0.05")
                price = _money(base * price_factor)
                if competitor_index == 0 and run_index == 1:
                    price = _money(price * Decimal("0.90"))  # price drop
                if competitor_index == 0 and run_index >= 2:
                    price = _money(base * Decimal("0.98"))  # later price rise
                stock_status = "IN_STOCK"
                if competitor_index == 1 and run_index == 1:
                    stock_status = "OUT_OF_STOCK"
                if competitor_index == 1 and run_index == 2:
                    stock_status = "IN_STOCK"
                self.db.add(
                    CompetitorSnapshot(
                        scrape_run_id=run.id,
                        competitor_id=competitor.id,
                        product_id=product.id,
                        price=price,
                        currency="BDT",
                        rating=Decimal(str(competitor.competitor_rating)),
                        review_count=competitor.rating_count,
                        stock_status=stock_status,
                        raw_stock_text="DEMO_SYNTHETIC",
                        source_url=f"https://demo.invalid/listings/{external_id}",
                        external_listing_id=external_id,
                        content_hash=_hash(run_key, external_id, price, stock_status),
                        captured_at=observed_at,
                        price_observed_at=observed_at,
                        stock_observed_at=observed_at,
                        match_score=competitor.match_confidence,
                    )
                )
                report.bump("competitor_snapshots")

    def _run_workflows(
        self, *, seller: Seller, products: list[Product], report: ComprehensiveDemoReport
    ) -> None:
        workflow_at = self.timestamp + timedelta(minutes=5)
        run_ids = list(
            self.db.scalars(
                select(ScrapeRun.id).where(
                    ScrapeRun.seller_id == seller.id,
                    ScrapeRun.run_key.like(f"{SEED_NAMESPACE}:{self.as_of}:%"),
                ).order_by(ScrapeRun.completed_at.asc())
            )
        )
        for run_id in run_ids:
            event = CompetitorEventService(self.db).generate_for_scrape_run(run_id)
            ranking = CompetitorRankingService(self.db).calculate_for_scrape_run(run_id)
            opportunity = MarketOpportunityService(self.db).generate_for_scrape_run(run_id)
            report.workflows.setdefault("competitor", {"events": 0, "rankings": 0, "opportunities": 0})
            report.workflows["competitor"]["events"] += event.generated_count
            report.workflows["competitor"]["rankings"] += ranking.created_count
            report.workflows["competitor"]["opportunities"] += opportunity.created_count

        velocity = SalesVelocityService(self.db).calculate_for_batch(
            seller_id=seller.id,
            as_of_date=self.as_of,
            calculated_at=workflow_at,
            calculation_version=DEMO_CALCULATION_VERSION,
        )
        stockout = StockoutPredictionService(self.db).calculate_for_batch(
            seller_id=seller.id,
            as_of_date=self.as_of,
            calculated_at=workflow_at,
            calculation_version=DEMO_CALCULATION_VERSION,
        )
        reorder = ReorderRecommendationService(self.db).calculate_for_batch(
            seller_id=seller.id,
            as_of_date=self.as_of,
            generated_at=workflow_at,
            calculation_version=DEMO_CALCULATION_VERSION,
        )
        risk = InventoryRiskService(self.db).assess_for_batch(
            seller_id=seller.id,
            as_of_date=self.as_of,
            assessed_at=workflow_at,
            calculation_version=DEMO_CALCULATION_VERSION,
        )
        aging = InventoryAgingService(
            self.db, calculation_version=DEMO_CALCULATION_VERSION
        ).calculate_batch(
            seller_id=seller.id, as_of_date=self.as_of, now=workflow_at
        )
        dead = DeadStockService(
            self.db, calculation_version=DEMO_CALCULATION_VERSION
        ).assess_batch(
            seller_id=seller.id, as_of_date=self.as_of, assessed_at=workflow_at
        )
        alerts = InventoryIntelligenceService(self.db).generate_alerts_for_latest_risks(
            seller_id=seller.id,
            product_id=None,
            as_of_date=self.as_of,
        )
        report.workflows["inventory"] = {
            "velocity_created": velocity.created_count,
            "stockout_created": stockout.created_count,
            "reorder_created": reorder.created_count,
            "risk_created": risk.created_count,
            "aging_created": aging.calculated_count,
            "dead_stock_created": dead.created_count,
            "alerts_created": alerts["created_count"],
            "alerts_skipped": alerts["skipped_count"],
        }

        recovery_created = capital_created = pricing_created = elasticity_created = dynamic_created = 0
        for product in products:
            try:
                _row, created = DeadStockRecoveryService(self.db).generate_for_product(
                    seller_id=seller.id, product_id=product.id, generated_at=workflow_at
                )
                recovery_created += int(created)
                DeadStockCapitalRecoveryService(self.db).estimate_for_product(
                    seller_id=seller.id, product_id=product.id, calculated_at=workflow_at
                )
                capital_created += 1
            except Exception as exc:
                report.warnings.append(f"dead_stock:{product.sku}:{type(exc).__name__}")
            try:
                PricingAnalyticsService(self.db).generate_for_product(
                    seller_id=seller.id, product_id=product.id, calculated_at=workflow_at
                )
                pricing_created += 1
                estimator = DemandResponseService(self.db)
                estimate = estimator.estimate_for_product(
                    seller_id=seller.id, product_id=product.id, as_of_date=self.as_of
                )
                estimate = replace(
                    estimate,
                    calculation_version=f"{estimate.calculation_version}:{DEMO_CALCULATION_VERSION}",
                )
                duplicates = list(
                    self.db.scalars(
                        select(DemandElasticityEstimate)
                        .where(
                            DemandElasticityEstimate.seller_id == seller.id,
                            DemandElasticityEstimate.product_id == product.id,
                            DemandElasticityEstimate.observation_end == estimate.observation_end,
                            DemandElasticityEstimate.calculation_version
                            == estimate.calculation_version,
                        )
                        .order_by(
                            DemandElasticityEstimate.created_at.asc(),
                            DemandElasticityEstimate.id.asc(),
                        )
                    )
                )
                for duplicate in duplicates[1:]:
                    self.db.delete(duplicate)
                if len(duplicates) > 1:
                    self.db.commit()
                estimator.persist_estimate(
                    seller_id=seller.id,
                    product_id=product.id,
                    estimate=estimate,
                    calculated_at=workflow_at,
                )
                elasticity_created += 1
                DynamicPricingService(self.db, include_evaluation_evidence=True).generate_for_product(
                    seller_id=seller.id, product_id=product.id, generated_at=workflow_at
                )
                dynamic_created += 1
            except Exception as exc:
                report.warnings.append(f"pricing:{product.sku}:{type(exc).__name__}:{exc}")
        report.workflows["pricing"] = {
            "analytics": pricing_created,
            "elasticity": elasticity_created,
            "dynamic_recommendations": dynamic_created,
        }
        report.workflows["dead_stock"] = {
            "recovery_recommendations": recovery_created,
            "capital_estimates": capital_created,
        }

        # Demonstrate supported lifecycle states through the owning service.
        dynamic_rows = list(
            self.db.scalars(
                select(DynamicPricingRecommendation)
                .where(DynamicPricingRecommendation.seller_id == seller.id)
                .order_by(DynamicPricingRecommendation.generated_at.asc())
            )
        )
        pricing_service = DynamicPricingService(self.db)
        acknowledged = next(
            (
                row
                for row in dynamic_rows
                if row.recommendation_status == DynamicPricingRecommendationStatus.OPEN
                and row.product_id != products[0].id
            ),
            None,
        )
        dismissed = next(
            (
                row
                for row in reversed(dynamic_rows)
                if row.recommendation_status == DynamicPricingRecommendationStatus.OPEN
                and row.product_id not in {products[0].id, getattr(acknowledged, "product_id", None)}
            ),
            None,
        )
        if acknowledged is not None:
            pricing_service.update_status(
                seller_id=seller.id,
                recommendation_id=acknowledged.id,
                status=DynamicPricingRecommendationStatus.ACKNOWLEDGED,
            )
        if dismissed is not None:
            pricing_service.update_status(
                seller_id=seller.id,
                recommendation_id=dismissed.id,
                status=DynamicPricingRecommendationStatus.DISMISSED,
            )

        rag = RagMemoryBackfillService(self.db).backfill(seller_id=seller.id)
        report.workflows["rag"] = asdict(rag)

    def validate(
        self,
        *,
        seller: Seller,
        products: list[Product],
        report: ComprehensiveDemoReport,
    ) -> ComprehensiveDemoReport:
        product_ids = [product.id for product in products]
        valid_sales_filter = (
            SalesRecord.seller_id == seller.id,
            SalesRecord.status.in_((SalesRecordStatus.COMPLETED, SalesRecordStatus.FULFILLED)),
            SalesRecord.is_test_order.is_(False),
        )
        sales_range = self.db.execute(
            select(func.min(SalesRecord.sold_at), func.max(SalesRecord.sold_at)).where(
                *valid_sales_filter
            )
        ).one()
        report.totals = {
            "seller_email": seller.email,
            "sales_date_start": sales_range[0].date().isoformat() if sales_range[0] else None,
            "sales_date_end": sales_range[1].date().isoformat() if sales_range[1] else None,
            "sales_records": self._count(SalesRecord, SalesRecord.seller_id == seller.id),
            "valid_sales_records": self._count(SalesRecord, *valid_sales_filter),
            "excluded_sales_records": self._count(
                SalesRecord,
                SalesRecord.seller_id == seller.id,
                ~SalesRecord.status.in_((SalesRecordStatus.COMPLETED, SalesRecordStatus.FULFILLED)),
            ),
            "units_sold": int(
                self.db.scalar(
                    select(func.coalesce(func.sum(SalesRecord.quantity_sold), 0)).where(
                        *valid_sales_filter
                    )
                )
                or 0
            ),
            "historical_revenue_bdt": str(
                self.db.scalar(
                    select(func.coalesce(func.sum(SalesRecord.line_total), 0)).where(
                        *valid_sales_filter
                    )
                )
                or Decimal("0")
            ),
            "inventory_snapshots": self._count(InventoryHistory, InventoryHistory.seller_id == seller.id),
            "stock_receipts": self._count(InventoryStockIn, InventoryStockIn.seller_id == seller.id),
            "competitors": self._count(Competitor, Competitor.product_id.in_(product_ids)),
            "completed_scrape_runs": self._count(
                ScrapeRun, ScrapeRun.seller_id == seller.id, ScrapeRun.status == "COMPLETED"
            ),
            "competitor_snapshots": self._count(CompetitorSnapshot, CompetitorSnapshot.product_id.in_(product_ids)),
            "competitor_events": self._count(CompetitorEvent, CompetitorEvent.seller_id == seller.id),
            "rankings": self._count(CompetitorRanking, CompetitorRanking.seller_id == seller.id),
            "market_opportunities": self._count(MarketOpportunity, MarketOpportunity.seller_id == seller.id),
            "sales_velocity": self._count(SalesVelocity, SalesVelocity.seller_id == seller.id),
            "stockout_predictions": self._count(StockoutPrediction, StockoutPrediction.seller_id == seller.id),
            "reorder_recommendations": self._count(ReorderRecommendation, ReorderRecommendation.seller_id == seller.id),
            "inventory_risks": self._count(InventoryRiskAssessment, InventoryRiskAssessment.seller_id == seller.id),
            "aging_snapshots": self._count(InventoryAgingSnapshot, InventoryAgingSnapshot.seller_id == seller.id),
            "dead_stock_assessments": self._count(DeadStockAssessment, DeadStockAssessment.seller_id == seller.id),
            "dead_stock_recovery": self._count(DeadStockRecoveryRecommendation, DeadStockRecoveryRecommendation.seller_id == seller.id),
            "capital_recovery": self._count(DeadStockCapitalRecoveryEstimate, DeadStockCapitalRecoveryEstimate.seller_id == seller.id),
            "elasticity_estimates": self._count(DemandElasticityEstimate, DemandElasticityEstimate.seller_id == seller.id),
            "seller_price_history": self._count(ProductPriceHistory, ProductPriceHistory.seller_id == seller.id),
            "promotion_plans": self._count(PromotionPlan, PromotionPlan.seller_id == seller.id),
            "active_promotions": self._count(
                PromotionPlan,
                PromotionPlan.seller_id == seller.id,
                PromotionPlan.status.in_(
                    (PromotionPlanStatus.APPROVED, PromotionPlanStatus.SCHEDULED, PromotionPlanStatus.RUNNING)
                ),
            ),
            "completed_promotions": self._count(
                PromotionPlan,
                PromotionPlan.seller_id == seller.id,
                PromotionPlan.status == PromotionPlanStatus.COMPLETED,
            ),
            "promotion_results": self._count(PromotionResult, PromotionResult.seller_id == seller.id),
            "pricing_analytics": self._count(PricingAnalyticsSnapshot, PricingAnalyticsSnapshot.seller_id == seller.id),
            "dynamic_pricing": self._count(DynamicPricingRecommendation, DynamicPricingRecommendation.seller_id == seller.id),
            "generic_recommendations": self._count(Recommendation, Recommendation.product_id.in_(product_ids)),
            "recommendation_jobs": self._count(
                RecommendationJob, RecommendationJob.seller_id == seller.id
            ),
            "completed_recommendation_jobs": self._count(
                RecommendationJob,
                RecommendationJob.seller_id == seller.id,
                RecommendationJob.status == "COMPLETED",
            ),
            "alerts": self._count(Alert, Alert.seller_id == seller.id),
            "telegram_inventory_alerts": self._count(
                TelegramInventoryAlert,
                TelegramInventoryAlert.seller_id == seller.id,
            ),
            "rag_documents": self._count(
                RagMemoryDocument,
                RagMemoryDocument.seller_id == seller.id,
                RagMemoryDocument.deleted_at.is_(None),
            ),
            "rag_chunks": self._count(
                RagMemoryChunk,
                RagMemoryChunk.seller_id == seller.id,
                RagMemoryChunk.deleted_at.is_(None),
            ),
            "rag_chunks_embedded": self._count(
                RagMemoryChunk,
                RagMemoryChunk.seller_id == seller.id,
                RagMemoryChunk.deleted_at.is_(None),
                RagMemoryChunk.embedding_status == RagMemoryEmbeddingStatus.EMBEDDED,
            ),
            "rag_chunks_pending": self._count(
                RagMemoryChunk,
                RagMemoryChunk.seller_id == seller.id,
                RagMemoryChunk.deleted_at.is_(None),
                RagMemoryChunk.embedding_status == RagMemoryEmbeddingStatus.PENDING,
            ),
            "copilot_conversations": self._count(CopilotConversation, CopilotConversation.seller_id == seller.id),
            "copilot_messages": self._count(CopilotMessage, CopilotMessage.seller_id == seller.id),
            "copilot_tool_calls": self._count(CopilotToolCall, CopilotToolCall.seller_id == seller.id),
            "copilot_action_proposals": self._count(CopilotActionProposal, CopilotActionProposal.seller_id == seller.id),
            "rag_query_logs": self._count(RagQueryLog, RagQueryLog.seller_id == seller.id),
        }
        report.totals["coverage_distribution"] = {
            status.value: self._count(
                SalesDataCoverage,
                SalesDataCoverage.seller_id == seller.id,
                SalesDataCoverage.completeness_status == status,
            )
            for status in SalesDataCompletenessStatus
        }
        report.totals["event_distribution"] = {
            event.value: self._count(
                CompetitorEvent,
                CompetitorEvent.seller_id == seller.id,
                CompetitorEvent.event_type == event,
            )
            for event in CompetitorEventType
        }
        report.totals["pricing_action_distribution"] = {
            action.value: self._count(
                DynamicPricingRecommendation,
                DynamicPricingRecommendation.seller_id == seller.id,
                DynamicPricingRecommendation.action == action,
            )
            for action in DynamicPricingAction
        }
        report.totals["pricing_status_distribution"] = {
            status.value: self._count(
                DynamicPricingRecommendation,
                DynamicPricingRecommendation.seller_id == seller.id,
                DynamicPricingRecommendation.recommendation_status == status,
            )
            for status in DynamicPricingRecommendationStatus
        }
        report.totals["inventory_risk_distribution"] = {
            level.value: self._count(
                InventoryRiskAssessment,
                InventoryRiskAssessment.seller_id == seller.id,
                InventoryRiskAssessment.risk_level == level,
            )
            for level in InventoryRiskLevel
        }
        report.totals["generic_recommendation_action_distribution"] = {
            action.value: self._count(
                Recommendation,
                Recommendation.product_id.in_(product_ids),
                Recommendation.action == action,
            )
            for action in RecommendationAction
        }
        report.totals["recommendation_job_status_distribution"] = {
            status: self._count(
                RecommendationJob,
                RecommendationJob.seller_id == seller.id,
                RecommendationJob.status == status,
            )
            for status in ("PENDING", "RUNNING", "COMPLETED", "FAILED")
        }
        guard_rejections: dict[str, int] = {}
        for recommendation in self.db.scalars(
            select(DynamicPricingRecommendation).where(
                DynamicPricingRecommendation.seller_id == seller.id
            )
        ):
            for candidate in (recommendation.evidence or {}).get("candidates", []):
                for reason in candidate.get("rejection_reasons", []):
                    guard_rejections[reason] = guard_rejections.get(reason, 0) + 1
        report.totals["margin_guard_rejections"] = guard_rejections
        report.scenarios = []
        for product, scenario in zip(products, SCENARIOS, strict=True):
            latest_risk = self.db.scalar(
                select(InventoryRiskAssessment)
                .where(InventoryRiskAssessment.product_id == product.id)
                .order_by(InventoryRiskAssessment.assessed_at.desc())
            )
            latest_reorder = self.db.scalar(
                select(ReorderRecommendation)
                .where(ReorderRecommendation.product_id == product.id)
                .order_by(ReorderRecommendation.generated_at.desc())
            )
            latest_pricing = self.db.scalar(
                select(DynamicPricingRecommendation)
                .where(DynamicPricingRecommendation.product_id == product.id)
                .order_by(DynamicPricingRecommendation.generated_at.desc())
            )
            latest_recommendation = self.db.scalar(
                select(Recommendation)
                .where(Recommendation.product_id == product.id)
                .order_by(Recommendation.created_at.desc(), Recommendation.id.desc())
            )
            embedded_chunks = self._count(
                RagMemoryChunk,
                RagMemoryChunk.seller_id == seller.id,
                RagMemoryChunk.product_id == product.id,
                RagMemoryChunk.deleted_at.is_(None),
                RagMemoryChunk.embedding_status == RagMemoryEmbeddingStatus.EMBEDDED,
            )
            pending_chunks = self._count(
                RagMemoryChunk,
                RagMemoryChunk.seller_id == seller.id,
                RagMemoryChunk.product_id == product.id,
                RagMemoryChunk.deleted_at.is_(None),
                RagMemoryChunk.embedding_status == RagMemoryEmbeddingStatus.PENDING,
            )
            report.scenarios.append(
                {
                    "code": scenario.code,
                    "product_id": str(product.id),
                    "sku": product.sku,
                    "product": product.title,
                    "scenario": scenario.label,
                    "valid_sales": self._count(
                        SalesRecord,
                        SalesRecord.product_id == product.id,
                        SalesRecord.status.in_((SalesRecordStatus.COMPLETED, SalesRecordStatus.FULFILLED)),
                        SalesRecord.is_test_order.is_(False),
                    ),
                    "inventory": product.stock_quantity,
                    "competitors": self._count(Competitor, Competitor.product_id == product.id),
                    "risk": getattr(getattr(latest_risk, "risk_level", None), "value", None),
                    "reorder": getattr(getattr(latest_reorder, "action", None), "value", None),
                    "pricing_outcome": getattr(getattr(latest_pricing, "action", None), "value", None),
                    "recommendation": getattr(
                        getattr(latest_recommendation, "action", None), "value", None
                    ),
                    "rag_documents": self._count(
                        RagMemoryDocument,
                        RagMemoryDocument.product_id == product.id,
                        RagMemoryDocument.deleted_at.is_(None),
                    ),
                    "rag_status": (
                        "MIXED"
                        if embedded_chunks and pending_chunks
                        else "EMBEDDED"
                        if embedded_chunks
                        else "PENDING"
                        if pending_chunks
                        else "NONE"
                    ),
                }
            )
        return report

    def write_markdown_report(self, report: ComprehensiveDemoReport, path: Path) -> None:
        lines = [
            "# Comprehensive demo seed report",
            "",
            f"- As of: {report.as_of_date}",
            f"- Seller: `{report.seller_id}`",
            f"- Products: {report.product_count}",
            "",
            "## Observed totals",
            "",
        ]
        lines.extend(f"- {key}: {value}" for key, value in report.totals.items())
        lines.extend(
            [
                "",
                "## Scenario coverage",
                "",
                "| Product | Scenario | Valid sales | Inventory | Competitors | Risk | Reorder | Pricing | Recommendation | RAG documents | RAG status |",
                "|---|---|---:|---:|---:|---|---|---|---|---:|---|",
            ]
        )
        for row in report.scenarios:
            lines.append(
                f"| {row['code']} {row['product']} | {row['scenario']} | {row['valid_sales']} | "
                f"{row['inventory']} | {row['competitors']} | {row['risk'] or '-'} | "
                f"{row['reorder'] or '-'} | {row['pricing_outcome'] or '-'} | "
                f"{row['recommendation'] or '-'} | {row['rag_documents']} | {row['rag_status']} |"
            )
        if report.warnings:
            lines.extend(["", "## Limitations", "", *[f"- {item}" for item in report.warnings]])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _count(self, model, *criteria) -> int:
        return int(self.db.scalar(select(func.count()).select_from(model).where(*criteria)) or 0)

    @staticmethod
    def _daily_quantity(pattern: str, offset: int, rng: random.Random) -> int:
        progress = Decimal(offset) / Decimal(HISTORY_DAYS - 1)
        if pattern == "high":
            return 2 + int(rng.random() < 0.35)
        if pattern == "medium":
            return 1 if rng.random() < 0.62 else 0
        if pattern == "increasing":
            return 1 + int(rng.random() < float(progress)) if rng.random() < 0.72 else 0
        if pattern == "declining":
            return 1 if rng.random() < float(Decimal("0.80") - progress * Decimal("0.65")) else 0
        if pattern == "seasonal":
            return 2 if offset % 14 in {5, 6} else int(rng.random() < 0.25)
        if pattern == "intermittent":
            return rng.choice((1, 2)) if rng.random() < 0.20 else 0
        if pattern == "no_recent":
            return int(offset < HISTORY_DAYS - 35 and rng.random() < 0.30)
        if pattern == "low":
            return int(rng.random() < 0.18)
        return int(rng.random() < 0.04)


def _money(value: Decimal | int) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _dhaka_noon(value: date) -> datetime:
    return datetime.combine(value, time(hour=12), tzinfo=timezone(timedelta(hours=6))).astimezone(timezone.utc)


def _dhaka_evening(value: date) -> datetime:
    return datetime.combine(value, time(hour=18), tzinfo=timezone(timedelta(hours=6))).astimezone(timezone.utc)


def _order_number(*values: object) -> str:
    """Deterministic 15-digit Daraz-style order number."""
    return str(600_000_000_000_000 + int(_hash(*values)[:13], 16) % 100_000_000_000_000)


def _hash(*values: object) -> str:
    payload = json.dumps([str(value) for value in values], separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()

