from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.dead_stock_assessment import DeadStockAssessment, DeadStockClassification, DeadStockDataStatus, DeadStockNoSalesState, DeadStockRiskLevel
from app.models.dead_stock_recovery_recommendation import (
    EVIDENCE_RECOVERY_VERSION,
    DeadStockRecoveryAction,
    DeadStockRecoveryRecommendation,
    DeadStockRecoveryRecommendationStatus,
)
from app.models.inventory_aging import InventoryAgingSnapshot
from app.models.inventory_history import InventoryHistory, InventorySnapshotSource
from app.models.product import Product
from app.models.rag_memory import RagMemorySourceType
from app.models.sales_velocity import SalesVelocity, SalesVelocityDataStatus
from app.repositories.dead_stock_recovery_repository import DeadStockRecoveryRepository
from app.repositories.reorder_recommendation_repository import ReorderRecommendationRepository
from app.scraper.constants import MARKETPLACE_NAME
from app.services.dead_stock_recovery_evidence import (
    SCENARIO_DAYS, cash_scenarios, holding_cost, load_recovery_forecast, money, nonnegative_decimal,
    promotion_observations,
)
from app.services.margin_guard import MarginGuard, MarginGuardResult
from app.services.rag_index_outbox_service import RagIndexOutboxService
from app.services.sales_velocity_service import SalesVelocityCalculation

MONEY = Decimal("0.01")
RECOVERY_CLASSES = {DeadStockClassification.SLOW_MOVING, DeadStockClassification.AT_RISK, DeadStockClassification.DEAD_STOCK}
RECOVERY_ALTERNATIVES = (DeadStockRecoveryAction.DISCOUNT, DeadStockRecoveryAction.FLASH_SALE, DeadStockRecoveryAction.BUNDLE, DeadStockRecoveryAction.SEO_FIX)


class DeadStockRecoveryRepositoryProtocol(Protocol):
    def product(self, *, seller_id: UUID, product_id: UUID) -> Product | None: ...
    def latest_assessment(self, *, seller_id: UUID, product_id: UUID) -> DeadStockAssessment | None: ...
    def latest_aging(self, *, seller_id: UUID, product_id: UUID, as_of_date) -> InventoryAgingSnapshot | None: ...
    def latest_velocity(self, *, seller_id: UUID, product_id: UUID, as_of_date) -> SalesVelocity | None: ...
    def companion_products(self, *, seller_id: UUID, product: Product, limit: int = 5) -> list[Product]: ...
    def visibility_for_product(self, *, seller_id: UUID, product_id: UUID, as_of_date) -> dict | None: ...
    def promotion_history_for_product(self, *, seller_id: UUID, product_id: UUID) -> list[dict]: ...
    def bundle_compatibility_for_product(self, *, seller_id: UUID, product_id: UUID) -> list[dict]: ...
    def add_idempotent(self, recommendation: DeadStockRecoveryRecommendation) -> tuple[DeadStockRecoveryRecommendation, bool]: ...
    def latest_recommendation(self, *, seller_id: UUID, product_id: UUID) -> DeadStockRecoveryRecommendation | None: ...
    def list_recommendations(self, *, seller_id: UUID, product_id: UUID, limit: int, offset: int) -> tuple[list[DeadStockRecoveryRecommendation], int]: ...
    def get(self, *, seller_id: UUID, recommendation_id: UUID) -> DeadStockRecoveryRecommendation | None: ...
    def save(self, recommendation: DeadStockRecoveryRecommendation) -> DeadStockRecoveryRecommendation: ...


@dataclass(frozen=True)
class Candidate:
    action: DeadStockRecoveryAction
    score: Decimal
    confidence: Decimal
    explanation: str
    evidence: dict
    discount_rate: Decimal | None = None
    price: Decimal | None = None
    duration_days: int | None = None
    quantity: int | None = None
    complexity: int = 1


class DeadStockRecoveryService:
    def __init__(
        self,
        db: Session | None = None,
        *,
        repository: DeadStockRecoveryRepositoryProtocol | None = None,
        margin_guard_factory=None,
        calculation_version: str | None = None,
    ) -> None:
        if repository is None and db is None:
            raise ValueError("Either db or repository is required.")
        self._db = db
        self._repository = repository or DeadStockRecoveryRepository(db)  # type: ignore[arg-type]
        self._margin_guard_factory = margin_guard_factory or (lambda session: MarginGuard(session))
        self._evidence_driven = settings.evidence_driven_recovery_enabled
        self._calculation_version = (
            EVIDENCE_RECOVERY_VERSION if self._evidence_driven
            else calculation_version or settings.dead_stock_recovery_formula_version
        )

    def generate_for_product(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        generated_at: datetime | None = None,
    ) -> tuple[DeadStockRecoveryRecommendation, bool]:
        timestamp = _utc(generated_at or datetime.now(timezone.utc))
        product = self._repository.product(seller_id=seller_id, product_id=product_id)
        if product is None:
            raise ValueError("Product not found.")
        assessment = self._repository.latest_assessment(seller_id=seller_id, product_id=product_id)
        if assessment is None:
            recommendation = self._build_without_assessment(product=product, generated_at=timestamp)
        else:
            if self._evidence_driven and isinstance(self._repository, DeadStockRecoveryRepository):
                saved = self._repository.get_for_assessment(
                    seller_id=seller_id, assessment_id=assessment.id, calculation_version=self._calculation_version,
                )
                if saved is not None:
                    return saved, False
            aging = self._repository.latest_aging(seller_id=seller_id, product_id=product_id, as_of_date=assessment.as_of_date)
            through = min(assessment.as_of_date, timestamp.date() - timedelta(days=1)) if self._evidence_driven else assessment.as_of_date
            velocity = self._repository.latest_velocity(seller_id=seller_id, product_id=product_id, as_of_date=through)
            visibility = self._repository.visibility_for_product(seller_id=seller_id, product_id=product_id, as_of_date=assessment.as_of_date)
            promotion_history = self._repository.promotion_history_for_product(seller_id=seller_id, product_id=product_id)
            bundle_data = self._repository.bundle_compatibility_for_product(seller_id=seller_id, product_id=product_id)
            companions = [] if self._evidence_driven else self._repository.companion_products(seller_id=seller_id, product=product)
            recommendation = self.build_recommendation(
                product=product,
                assessment=assessment,
                aging=aging,
                velocity=velocity,
                visibility=visibility,
                promotion_history=promotion_history,
                bundle_data=bundle_data,
                companion_products=companions,
                generated_at=timestamp,
            )
        if self._evidence_driven and isinstance(self._repository, DeadStockRecoveryRepository) and self._db is not None:
            outbox = RagIndexOutboxService(self._db)
            def enqueue(row: DeadStockRecoveryRecommendation) -> None:
                outbox.enqueue_upsert(
                    seller_id=row.seller_id, source_type=RagMemorySourceType.RECOMMENDATION,
                    source_id=str(row.id), product_id=row.product_id, source_updated_at=row.generated_at,
                )
            return self._repository.add_idempotent(recommendation, before_commit=enqueue)
        saved, created = self._repository.add_idempotent(recommendation)
        if created and self._db is not None:
            RagIndexOutboxService(self._db).enqueue_upsert(
                seller_id=saved.seller_id,
                source_type=RagMemorySourceType.RECOMMENDATION,
                source_id=str(saved.id),
                product_id=saved.product_id,
                source_updated_at=saved.generated_at,
            )
            self._db.commit()
        return saved, created

    def build_recommendation(
        self,
        *,
        product: Product,
        assessment: DeadStockAssessment,
        aging: InventoryAgingSnapshot | None,
        velocity: SalesVelocity | SalesVelocityCalculation | None,
        visibility: dict | None,
        promotion_history: list[dict],
        bundle_data: list[dict],
        companion_products: list[Product],
        generated_at: datetime,
        inventory: InventoryHistory | None = None,
        prefer_listing: bool = False,
    ) -> DeadStockRecoveryRecommendation:
        if self._evidence_driven:
            return self._build_evidence_driven(
                product=product, assessment=assessment, aging=aging, velocity=velocity,
                inventory=inventory, visibility=visibility, at=_utc(generated_at), prefer_listing=prefer_listing,
            )
        candidates: list[Candidate] = []
        rejected: list[dict] = []
        common: dict[str, Any] = {
            "risk_score": _json_decimal(getattr(assessment, "risk_score", None)),
            "risk_level": _enum_value(getattr(assessment, "risk_level", None)),
            "classification": _enum_value(assessment.classification),
            "eligible_quantity": assessment.eligible_quantity,
            "inventory_age_days": assessment.inventory_age_days,
            "current_price": _json_decimal(product.selling_price),
            "unit_cost_available": product.cost_price is not None,
            "category": product.category,
            "promotion_history_count": len(promotion_history),
        }

        if assessment.classification not in {
            DeadStockClassification.SLOW_MOVING,
            DeadStockClassification.AT_RISK,
            DeadStockClassification.DEAD_STOCK,
        }:
            candidates.append(_hold_candidate("No recovery action is recommended for the current dead-stock classification.", common))
        elif recovery_is_restricted(product):
            candidates.append(_manual_review_candidate("Product restrictions, damage, or expiry status require manual review before recovery action.", common))
        else:
            candidates.extend(self._bundle_candidates(product=product, assessment=assessment, companions=companion_products, bundle_data=bundle_data, common=common))
            candidates.extend(self._priced_candidates(product=product, assessment=assessment, common=common, rejected=rejected))
            seo = self._seo_candidate(assessment=assessment, visibility=visibility, common=common)
            if seo:
                candidates.append(seo)
            else:
                rejected.append({"action": DeadStockRecoveryAction.SEO_FIX.value, "reasons": ["Reliable visibility or listing-quality evidence is unavailable."]})

        if not candidates:
            candidates.append(_manual_review_candidate("Recovery calculations cannot be trusted with the available inputs.", common))

        return self._assemble(assessment, candidates, rejected, common, generated_at)

    def _assemble(
        self,
        assessment: DeadStockAssessment,
        candidates: list[Candidate],
        rejected: list[dict],
        common: dict,
        generated_at: datetime,
        *,
        prefer_listing: bool = False,
    ) -> DeadStockRecoveryRecommendation:
        candidates = sorted(
            candidates,
            key=lambda item: (
                prefer_listing and item.action == DeadStockRecoveryAction.SEO_FIX,
                item.score,
            ),
            reverse=True,
        )
        primary = candidates[0]
        secondary = (
            list(
                dict.fromkeys(
                    item.action.value
                    for item in candidates[1:]
                    if item.action != primary.action
                )
            )[:2]
            if self._evidence_driven
            else [item.action.value for item in candidates[1:3]]
        )
        status = DeadStockRecoveryRecommendationStatus.OPEN
        if (
            primary.action == DeadStockRecoveryAction.MANUAL_REVIEW
            and primary.confidence <= Decimal("35")
        ):
            status = DeadStockRecoveryRecommendationStatus.INSUFFICIENT_DATA

        evidence = {
            "formula_version": self._calculation_version,
            "inputs": common,
            "candidate_actions": [_candidate_evidence(item) for item in candidates],
            "ranking_formula": "score = capital_recovery + sell_through + margin_safety + data_confidence + inventory_age + visibility_evidence - operational_complexity - further_loss_risk",
            "no_automatic_execution": True,
        }
        if self._evidence_driven:
            evidence.update(
                ranking_formula="Verified listing findings, assessment risk, preserved unit margin, baseline stock exposure, and campaign complexity.",
                sales_response_status="UNKNOWN",
                expected_promotion_uplift=None,
                prefers_compatible_listing_advice=prefer_listing,
            )
        return DeadStockRecoveryRecommendation(
            seller_id=assessment.seller_id,
            product_id=assessment.product_id,
            dead_stock_assessment_id=assessment.id,
            primary_action=primary.action,
            secondary_actions=secondary,
            recommended_discount_rate=primary.discount_rate,
            recommended_price=primary.price,
            suggested_duration_days=primary.duration_days,
            recommended_quantity=primary.quantity,
            confidence_score=_score(primary.confidence),
            recommendation_status=status,
            explanation=primary.explanation,
            evidence=evidence,
            rejected_actions=rejected,
            calculation_version=self._calculation_version,
            generated_at=generated_at,
            expires_at=generated_at
            + timedelta(days=settings.dead_stock_recovery_expiration_days),
        )

    def _build_evidence_driven(
        self,
        *,
        product: Product,
        assessment: DeadStockAssessment,
        aging: InventoryAgingSnapshot | None,
        velocity: SalesVelocity | SalesVelocityCalculation | None,
        inventory: InventoryHistory | None,
        visibility: dict | None,
        at: datetime,
        prefer_listing: bool,
    ) -> DeadStockRecoveryRecommendation:
        scope = {"seller_id": product.seller_id, "product_id": product.id}
        if any(
            (item.seller_id, item.product_id) != (product.seller_id, product.id)
            for item in (assessment, aging, velocity, inventory)
            if item is not None
        ):
            raise ValueError(
                "Recovery inputs outside authorized seller and product scope."
            )
        cutoff = timedelta(hours=settings.recommendation_inventory_max_age_hours)
        common: dict[str, Any] = {
            "risk_score": _json_decimal(assessment.risk_score),
            "classification": assessment.classification.value,
            "assessment_id": str(assessment.id),
            "assessed_at": _utc(assessment.assessed_at).isoformat(),
            "current_price": _json_decimal(product.selling_price),
            "on_hand_units": product.stock_quantity,
            "inventory_age_days": assessment.inventory_age_days,
        }
        if (
            assessment.data_status == DeadStockDataStatus.INSUFFICIENT
            or assessment.classification == DeadStockClassification.INSUFFICIENT_DATA
            or not (
                timedelta(0) <= at - _utc(assessment.assessed_at) <= cutoff
                and timedelta(0)
                <= at.date() - assessment.as_of_date
                <= cutoff + timedelta(days=1)
            )
        ):
            reason = "ASSESSMENT_STALE_OR_INSUFFICIENT"
        elif recovery_is_restricted(product):
            reason = "PRODUCT_REQUIRES_MANUAL_REVIEW"
        elif (
            assessment.classification not in RECOVERY_CLASSES
            or assessment.no_sales_state == DeadStockNoSalesState.PRODUCT_TOO_NEW
        ):
            return self._assemble(
                assessment,
                [
                    _hold_candidate(
                        "The assessment supports keeping the current recovery plan unchanged.",
                        common,
                    )
                ],
                _blocked_alternatives("CLASSIFICATION_DOES_NOT_REQUIRE_RECOVERY"),
                common,
                at,
            )
        else:
            reason = None
        if reason:
            return self._assemble(
                assessment,
                [
                    _manual_review_candidate(
                        "Review product restrictions or assessment evidence before recovery.",
                        common,
                    )
                ],
                _blocked_alternatives(reason),
                common,
                at,
            )
        if inventory is None and self._db is not None:
            inventory = (
                ReorderRecommendationRepository(self._db)
                .latest_inventory_for_products(
                    seller_id=product.seller_id,
                    product_ids=[product.id],
                    as_of_date=at.date(),
                )
                .get(product.id)
            )
        cap = None
        if (
            inventory is not None
            and inventory.id == assessment.inventory_snapshot_id
            and inventory.source != InventorySnapshotSource.BACKFILL
            and inventory.quantity_on_hand == product.stock_quantity
            and inventory.quantity_available
            == inventory.quantity_on_hand - inventory.quantity_reserved
            and inventory.snapshot_date <= at.date()
            and timedelta(0) <= at - _utc(inventory.captured_at) <= cutoff
        ):
            cap = max(
                0, min(assessment.eligible_quantity, inventory.quantity_available)
            )
        matched_aging = (
            aging is not None
            and aging.id == assessment.inventory_aging_id
            and aging.inventory_snapshot_id == assessment.inventory_snapshot_id
            and aging.as_of_date <= assessment.as_of_date
            and _utc(aging.calculated_at) <= at
        )
        age = (
            aging.oldest_age_days
            if aging is not None and matched_aging
            else assessment.inventory_age_days
        )
        estimated_age = (
            aging.is_estimated
            if aging is not None and matched_aging
            else assessment.inventory_age_is_estimated
        )
        sales = _recorded_recovery_sales(velocity, at)
        records = (
            self._repository.promotion_observations(
                **scope, since=at - timedelta(days=180), at=at
            )
            if isinstance(self._repository, DeadStockRecoveryRepository)
            else []
        )
        history = promotion_observations(records, product=product, at=at)
        forecast: dict[str, Any] = (
            load_recovery_forecast(self._db, product, at)
            if cap
            else {"status": "UNAVAILABLE", "reason": "ELIGIBLE_STOCK_UNVERIFIED"}
        )
        point = (
            forecast.get("forecast", {}).get("expected_units")
            if forecast["status"] == "APPROVED_BASELINE_ONLY"
            else None
        )
        forecast["baseline_point_covers_eligible_units"] = (
            Decimal(point) >= cap if point is not None and cap else None
        )
        cost, carrying = nonnegative_decimal(product.cost_price), holding_cost(product)
        common.update(
            inventory_snapshot_id=str(inventory.id) if inventory is not None else None,
            inventory_age_days=age,
            inventory_age_is_estimated=estimated_age,
            eligible_quantity=cap,
            reserved_units=inventory.quantity_reserved
            if inventory is not None
            else None,
            recorded_sales=sales,
            promotion_history=history,
            baseline_demand=forecast,
            unit_cost_bdt=str(cost) if cost is not None else None,
            locked_cost_basis_bdt=money(cost * cap)
            if cost is not None and cap is not None
            else None,
            holding_cost_bdt_per_unit_per_day=str(carrying)
            if carrying is not None
            else None,
        )
        candidates = []
        rejected: list[dict] = [
            {
                "action": "BUNDLE",
                "reasons": ["VERIFIED_BUNDLE_TERMS_AND_ECONOMICS_UNAVAILABLE"],
            }
        ]
        seo = self._seo_candidate(
            assessment=assessment,
            visibility=_recent_visibility(visibility, at, cutoff),
            common={},
        )
        if seo:
            candidates.append(seo)
        else:
            rejected.append(
                {"action": "SEO_FIX", "reasons": ["LISTING_EVIDENCE_UNAVAILABLE"]}
            )
        failures = [
            code
            for condition, code in (
                (bool(cap), "ELIGIBLE_STOCK_UNVERIFIED_OR_EMPTY"),
                (
                    age is not None
                    and age >= settings.dead_stock_inventory_age_threshold_days,
                    "INVENTORY_AGE_BELOW_THRESHOLD_OR_UNAVAILABLE",
                ),
                (sales is not None, "RECENT_SALES_EVIDENCE_UNAVAILABLE"),
                (
                    assessment.classification == DeadStockClassification.DEAD_STOCK
                    or assessment.risk_level
                    in {DeadStockRiskLevel.HIGH, DeadStockRiskLevel.CRITICAL},
                    "RISK_BELOW_PROMOTION_THRESHOLD",
                ),
                (
                    product.selling_price is not None
                    and product.selling_price.is_finite()
                    and product.selling_price > 0,
                    "CURRENT_PRICE_UNAVAILABLE",
                ),
            )
            if not condition
        ]
        if failures:
            rejected.extend(
                {"action": action, "reasons": failures}
                for action in ("DISCOUNT", "FLASH_SALE")
            )
        else:
            assert cap is not None
            candidates.extend(
                self._evidence_prices(
                    product,
                    assessment,
                    cap,
                    carrying,
                    history,
                    forecast,
                    rejected,
                )
            )
        if not candidates:
            candidates.append(
                _manual_review_candidate(
                    "Review the stock, sales, listing, and price evidence before committing to recovery.",
                    {},
                )
            )
        return self._assemble(
            assessment, candidates, rejected, common, at, prefer_listing=prefer_listing
        )

    def _evidence_prices(
        self,
        product: Product,
        assessment: DeadStockAssessment,
        cap: int,
        carrying: Decimal | None,
        history: dict,
        forecast: dict,
        rejected: list[dict],
    ) -> list[Candidate]:
        guard: MarginGuard = self._margin_guard_factory(self._db)
        baseline = guard.validate_candidate(
            seller_id=product.seller_id,
            product=product,
            marketplace=MARKETPLACE_NAME,
            candidate_price=product.selling_price,
        )
        candidates: list[Candidate] = []
        rates = _discount_rates()
        flash_blockers = []
        if cap < settings.dead_stock_recovery_flash_sale_min_quantity:
            flash_blockers.append("FLASH_STOCK_BELOW_MINIMUM")
        if len(history["observed_outcomes"]) < 2:
            flash_blockers.append("FLASH_HISTORY_INSUFFICIENT")
        if settings.dead_stock_recovery_flash_sale_duration_days <= 0:
            flash_blockers.append("FLASH_DURATION_INVALID")
        if flash_blockers:
            rejected.append({"action": "FLASH_SALE", "reasons": flash_blockers})
        if not rates:
            rejected.append(
                {"action": "DISCOUNT", "reasons": ["DISCOUNT_GRID_UNAVAILABLE"]}
            )
            if not flash_blockers:
                rejected.append(
                    {"action": "FLASH_SALE", "reasons": ["DISCOUNT_GRID_UNAVAILABLE"]}
                )
            return candidates
        floor = product.selling_price * (1 - rates[-1])
        checked = set()
        for rate in rates:
            requested = _money(product.selling_price * (1 - rate))
            quote = guard.validate_candidate(
                seller_id=product.seller_id,
                product=product,
                marketplace=MARKETPLACE_NAME,
                candidate_price=requested,
                round_down_to_increment=True,
            )
            price = quote.candidate_price
            if price in checked:
                continue
            checked.add(price)
            reasons = [reason.value for reason in quote.rejection_reasons]
            if not floor <= price < product.selling_price:
                reasons.append("ROUNDED_PRICE_OUTSIDE_RECOVERY_GRID")
            for action in (
                DeadStockRecoveryAction.DISCOUNT,
                DeadStockRecoveryAction.FLASH_SALE,
            ):
                if action == DeadStockRecoveryAction.FLASH_SALE and flash_blockers:
                    continue
                evidence: dict[str, Any] = {
                    "candidate_price": str(price),
                    "requested_price": str(requested),
                    "margin_guard": quote.to_evidence(),
                }
                if reasons or not quote.is_allowed:
                    rejected.append(
                        {
                            "action": action.value,
                            **evidence,
                            "reasons": reasons or ["MARGIN_GUARD_BLOCKED"],
                        }
                    )
                    continue
                duration = (
                    settings.dead_stock_recovery_flash_sale_duration_days
                    if action == DeadStockRecoveryAction.FLASH_SALE
                    else SCENARIO_DAYS
                )
                score_parts = {
                    "base": Decimal(52),
                    "assessment_risk": _risk_points(assessment),
                    "unit_margin": _margin_points(quote),
                    "campaign_complexity": Decimal(-8)
                    if action == DeadStockRecoveryAction.FLASH_SALE
                    else Decimal(0),
                    "baseline_coverage_penalty": Decimal(-12)
                    if forecast.get("baseline_point_covers_eligible_units")
                    else Decimal(0),
                }
                evidence.update(
                    ranking_components={
                        name: str(value) for name, value in score_parts.items()
                    },
                    scenario_duration_days=duration,
                    sales_response_status="UNKNOWN",
                    cash_scenarios=cash_scenarios(
                        quote,
                        quantity=cap,
                        holding_per_day=carrying,
                        duration_days=duration,
                        baseline=baseline,
                    ),
                )
                candidates.append(
                    Candidate(
                        action=action,
                        score=sum(score_parts.values(), Decimal(0)),
                        confidence=Decimal("60"),
                        explanation="Review this guarded recovery price. Financial scenarios show what happens at specified quantities sold.",
                        evidence=evidence,
                        discount_rate=(
                            (product.selling_price - price) / product.selling_price
                        ).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP),
                        price=price,
                        quantity=cap,
                        duration_days=duration
                        if action == DeadStockRecoveryAction.FLASH_SALE
                        else None,
                    )
                )
        # The grid is in increasing discount order, so equal scores retain the
        # highest candidate price and avoid an unsupported preference for deeper cuts.
        return candidates

    def _bundle_candidates(self, *, product: Product, assessment: DeadStockAssessment, companions: list[Product], bundle_data: list[dict], common: dict) -> list[Candidate]:
        if assessment.eligible_quantity < settings.dead_stock_recovery_bundle_min_quantity:
            return []
        if assessment.classification == DeadStockClassification.DEAD_STOCK:
            base = Decimal("45")
        else:
            base = Decimal("60")
        reliable = bool(bundle_data or companions)
        companion_evidence = [
            {"product_id": str(item.id), "category": item.category}
            for item in companions[:3]
        ]
        return [
            Candidate(
                action=DeadStockRecoveryAction.BUNDLE,
                score=base + _age_points(assessment) + (Decimal("8") if reliable else Decimal("0")),
                confidence=Decimal("70") if reliable else Decimal("55"),
                explanation="Bundle recovery is recommended; companion selection requires manual review." if not reliable else "Bundle recovery is recommended using observed same-category companion evidence.",
                evidence={**common, "companion_selection_requires_manual_review": not reliable, "companion_products": companion_evidence, "bundle_data": bundle_data},
                quantity=min(int(assessment.eligible_quantity), int(getattr(product, "stock_quantity", assessment.eligible_quantity) or assessment.eligible_quantity)),
                complexity=3,
            )
        ]

    def _priced_candidates(self, *, product: Product, assessment: DeadStockAssessment, common: dict, rejected: list[dict]) -> list[Candidate]:
        if self._db is None and self._margin_guard_factory is None:
            return []
        if assessment.classification != DeadStockClassification.DEAD_STOCK and getattr(assessment, "risk_level", None) not in {
            DeadStockRiskLevel.HIGH,
            DeadStockRiskLevel.CRITICAL,
        }:
            rejected.append({"action": DeadStockRecoveryAction.DISCOUNT.value, "reasons": ["Discount recovery is reserved for dead stock or high-risk products."]})
            rejected.append({"action": DeadStockRecoveryAction.FLASH_SALE.value, "reasons": ["Flash sales are reserved for old, significant, high-risk inventory."]})
            return []
        candidates: list[Candidate] = []
        guard = self._margin_guard_factory(self._db)
        allowed_discounts: list[tuple[Decimal, Decimal, MarginGuardResult]] = []
        blocked_reasons: set[str] = set()
        for rate in _discount_rates():
            candidate_price = _money(Decimal(str(product.selling_price)) * (Decimal("1") - rate))
            result = guard.validate_candidate(seller_id=product.seller_id, product=product, candidate_price=candidate_price)
            evidence = {**common, "discount_rate": str(_score(rate)), "candidate_price": str(candidate_price), "margin_guard": result.to_evidence()}
            del evidence
            if result.is_allowed:
                allowed_discounts.append((rate, candidate_price, result))
            else:
                reasons = [reason.value for reason in result.rejection_reasons]
                blocked_reasons.update(reasons)
                rejected.append({"action": DeadStockRecoveryAction.DISCOUNT.value, "discount_rate": str(_score(rate)), "reasons": reasons})

        if not allowed_discounts:
            if "MISSING_COST_DATA" in blocked_reasons:
                candidates.append(_manual_review_candidate("Product cost is missing, so recovery pricing cannot be trusted.", common))
            elif "MISSING_FEE_DATA" in blocked_reasons:
                candidates.append(_manual_review_candidate("Effective marketplace fee data is missing, so recovery pricing cannot be trusted.", common))
            elif blocked_reasons:
                candidates.append(_manual_review_candidate("MarginGuard rejected all recovery prices, so manual review is required.", common))
            return candidates

        best_rate, best_price, best_guard = allowed_discounts[-1]
        candidates.append(
            Candidate(
                action=DeadStockRecoveryAction.DISCOUNT,
                score=Decimal("58") + _risk_points(assessment) + _margin_points(best_guard),
                confidence=Decimal("75"),
                explanation="A bounded discount is recommended because MarginGuard confirms the candidate price is safe.",
                evidence={**common, "discount_rate": str(_score(best_rate)), "candidate_price": str(best_price), "margin_guard": best_guard.to_evidence()},
                discount_rate=best_rate,
                price=best_price,
                quantity=assessment.eligible_quantity,
                complexity=2,
            )
        )
        if (assessment.inventory_age_days or 0) >= settings.dead_stock_inventory_age_threshold_days and assessment.eligible_quantity >= settings.dead_stock_recovery_flash_sale_min_quantity:
            flash_rate, flash_price, flash_guard = allowed_discounts[min(len(allowed_discounts) - 1, 1)]
            candidates.append(
                Candidate(
                    action=DeadStockRecoveryAction.FLASH_SALE,
                    score=Decimal("62") + _age_points(assessment) + _margin_points(flash_guard),
                    confidence=Decimal("72"),
                    explanation="A short flash sale is recommended; this only proposes duration, discount, and maximum quantity.",
                    evidence={**common, "discount_rate": str(_score(flash_rate)), "candidate_price": str(flash_price), "margin_guard": flash_guard.to_evidence(), "limitations": ["Campaign must be reviewed and created manually.", "Quantity is capped to eligible inventory."]},
                    discount_rate=flash_rate,
                    price=flash_price,
                    duration_days=settings.dead_stock_recovery_flash_sale_duration_days,
                    quantity=assessment.eligible_quantity,
                    complexity=3,
                )
            )
        return candidates

    def _seo_candidate(self, *, assessment: DeadStockAssessment, visibility: dict | None, common: dict) -> Candidate | None:
        evidence = visibility or _visibility_from_assessment(assessment)
        if not evidence:
            return None
        low_evidence = _low_visibility_evidence(evidence)
        if not low_evidence:
            return None
        return Candidate(
            action=DeadStockRecoveryAction.SEO_FIX,
            score=Decimal("50") + Decimal(len(low_evidence) * 8),
            confidence=Decimal("68"),
            explanation="Listing visibility remediation is recommended based on observed visibility or listing-quality evidence.",
            evidence={**common, "visibility_evidence": evidence, "triggering_visibility_rules": low_evidence},
            complexity=2,
        )

    def _build_without_assessment(self, *, product: Product, generated_at: datetime) -> DeadStockRecoveryRecommendation:
        del product, generated_at
        raise ValueError("Latest dead-stock assessment is required.")

    def latest_recommendation(self, *, seller_id: UUID, product_id: UUID):
        return self._repository.latest_recommendation(seller_id=seller_id, product_id=product_id)

    def recommendation_history(self, *, seller_id: UUID, product_id: UUID, limit: int, offset: int):
        return self._repository.list_recommendations(seller_id=seller_id, product_id=product_id, limit=limit, offset=offset)

    def acknowledge(self, *, seller_id: UUID, recommendation_id: UUID, timestamp: datetime | None = None):
        rec = self._repository.get(seller_id=seller_id, recommendation_id=recommendation_id)
        if rec is None:
            return None
        rec.recommendation_status = DeadStockRecoveryRecommendationStatus.ACKNOWLEDGED
        rec.acknowledged_at = _utc(timestamp or datetime.now(timezone.utc))
        saved = self._repository.save(rec)
        _enqueue_dead_stock_recalculation(saved, "recommendation_acknowledged")
        return saved

    def dismiss(self, *, seller_id: UUID, recommendation_id: UUID, timestamp: datetime | None = None):
        rec = self._repository.get(seller_id=seller_id, recommendation_id=recommendation_id)
        if rec is None:
            return None
        rec.recommendation_status = DeadStockRecoveryRecommendationStatus.DISMISSED
        rec.dismissed_at = _utc(timestamp or datetime.now(timezone.utc))
        saved = self._repository.save(rec)
        _enqueue_dead_stock_recalculation(saved, "recommendation_dismissed")
        return saved


def _hold_candidate(explanation: str, common: dict) -> Candidate:
    return Candidate(DeadStockRecoveryAction.HOLD, Decimal("50"), Decimal("70"), explanation, common)


def _blocked_alternatives(reason: str) -> list[dict]:
    return [
        {"action": action.value, "reasons": [reason]}
        for action in RECOVERY_ALTERNATIVES
    ]


def _recorded_recovery_sales(
    velocity: SalesVelocity | SalesVelocityCalculation | None,
    at: datetime,
) -> dict | None:
    if (
        velocity is None
        or velocity.data_status != SalesVelocityDataStatus.SUFFICIENT
        or not 1 <= (at.date() - velocity.as_of_date).days <= 3
        or nonnegative_decimal(velocity.daily_sales_rate) is None
        or nonnegative_decimal(velocity.confidence_score) is None
        or velocity.confidence_score
        < Decimal(str(settings.reorder_minimum_velocity_confidence))
        or (isinstance(velocity, SalesVelocity) and _utc(velocity.calculated_at) > at)
    ):
        return None
    return {
        "source": "recorded_net_sales",
        "through": velocity.as_of_date.isoformat(),
        "net_units": velocity.net_units_sold,
        "sales_days": velocity.sales_days,
        "window_days": velocity.window_days,
        "daily_rate": str(velocity.daily_sales_rate),
        "calculation_version": velocity.calculation_version,
        "total_window_sell_through": None,
    }


def _recent_visibility(
    visibility: dict | None, at: datetime, age: timedelta
) -> dict | None:
    if not visibility or visibility.get("marketplace") != MARKETPLACE_NAME:
        return None
    try:
        day = datetime.fromisoformat(visibility["metric_date"]).date()
    except (KeyError, TypeError, ValueError):
        return None
    if timedelta(0) <= at.date() - day <= age + timedelta(days=1):
        return {
            key: value
            for key, value in visibility.items()
            if key not in {"impressions", "click_through_rate", "listing_quality_score"}
            or nonnegative_decimal(value) is not None
        }
    return None


def _manual_review_candidate(explanation: str, common: dict) -> Candidate:
    return Candidate(DeadStockRecoveryAction.MANUAL_REVIEW, Decimal("55"), Decimal("30"), explanation, common, complexity=4)


def _enqueue_dead_stock_recalculation(recommendation: DeadStockRecoveryRecommendation, reason: str) -> None:
    from app.tasks.dead_stock_workflow_tasks import enqueue_dead_stock_recalculation

    enqueue_dead_stock_recalculation(
        seller_id=recommendation.seller_id,
        product_id=recommendation.product_id,
        reason=reason,
    )


def _discount_rates() -> list[Decimal]:
    rates = [Decimal(str(rate)) for rate in settings.dead_stock_recovery_discount_rates]
    if any(rate <= 0 or rate >= 1 for rate in rates):
        raise ValueError("Dead-stock recovery discount rates must be between 0 and 1.")
    return sorted(rates)


def recovery_is_restricted(product: Product) -> bool:
    specs = getattr(product, "specifications", None) or {}
    return any(bool(specs.get(key)) for key in ("expired", "damaged", "restricted", "regulated"))


def _visibility_from_assessment(assessment: DeadStockAssessment) -> dict | None:
    if "LOW_VISIBILITY" in (assessment.triggered_rules or []):
        return {"status": "LOW_VISIBILITY", "source": "dead_stock_assessment"}
    return None


def _low_visibility_evidence(evidence: dict) -> list[str]:
    rules: list[str] = []
    if evidence.get("status") == "LOW_VISIBILITY":
        rules.append("LOW_VISIBILITY_STATUS")
    impressions = _decimal_or_none(evidence.get("impressions"))
    if impressions is not None and impressions <= Decimal("100"):
        rules.append("LOW_IMPRESSIONS")
    ctr = _decimal_or_none(evidence.get("click_through_rate"))
    if ctr is not None and ctr <= Decimal("0.01"):
        rules.append("LOW_CTR")
    quality = _decimal_or_none(evidence.get("listing_quality_score"))
    if quality is not None and quality <= Decimal("40"):
        rules.append("LOW_LISTING_QUALITY")
    if evidence.get("missing_keywords"):
        rules.append("MISSING_KEYWORDS")
    return rules


def _candidate_evidence(candidate: Candidate) -> dict:
    return {
        "action": candidate.action.value,
        "score": str(_score(candidate.score)),
        "confidence": str(_score(candidate.confidence)),
        "explanation": candidate.explanation,
        "evidence": candidate.evidence,
    }


def _risk_points(assessment: DeadStockAssessment) -> Decimal:
    level = getattr(assessment, "risk_level", None)
    if level == DeadStockRiskLevel.CRITICAL:
        return Decimal("18")
    if level == DeadStockRiskLevel.HIGH:
        return Decimal("12")
    if level == DeadStockRiskLevel.MEDIUM:
        return Decimal("6")
    return Decimal("0")


def _age_points(assessment: DeadStockAssessment) -> Decimal:
    age = Decimal(str(assessment.inventory_age_days or 0))
    threshold = Decimal(settings.dead_stock_inventory_age_threshold_days)
    return min(Decimal("15"), (age / threshold * Decimal("10")) if threshold > 0 else Decimal("0"))


def _margin_points(guard) -> Decimal:
    margin = guard.margin_rate or Decimal("0")
    return min(Decimal("10"), margin * Decimal("50"))


def _decimal_or_none(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _json_decimal(value) -> str | None:
    if value is None:
        return None
    return str(value)


def _enum_value(value) -> str | None:
    return getattr(value, "value", value)


def _score(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
