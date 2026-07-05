from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.dead_stock_assessment import DeadStockAssessment, DeadStockClassification, DeadStockRiskLevel
from app.models.dead_stock_recovery_recommendation import (
    DeadStockRecoveryAction,
    DeadStockRecoveryRecommendation,
    DeadStockRecoveryRecommendationStatus,
)
from app.models.inventory_aging import InventoryAgingSnapshot
from app.models.product import Product
from app.models.sales_velocity import SalesVelocity
from app.repositories.dead_stock_recovery_repository import DeadStockRecoveryRepository
from app.services.margin_guard import MarginGuard

MONEY = Decimal("0.01")


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
        self._calculation_version = calculation_version or settings.dead_stock_recovery_formula_version

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
            aging = self._repository.latest_aging(seller_id=seller_id, product_id=product_id, as_of_date=assessment.as_of_date)
            velocity = self._repository.latest_velocity(seller_id=seller_id, product_id=product_id, as_of_date=assessment.as_of_date)
            visibility = self._repository.visibility_for_product(seller_id=seller_id, product_id=product_id, as_of_date=assessment.as_of_date)
            promotion_history = self._repository.promotion_history_for_product(seller_id=seller_id, product_id=product_id)
            bundle_data = self._repository.bundle_compatibility_for_product(seller_id=seller_id, product_id=product_id)
            companions = self._repository.companion_products(seller_id=seller_id, product=product)
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
        return self._repository.add_idempotent(recommendation)

    def build_recommendation(
        self,
        *,
        product: Product,
        assessment: DeadStockAssessment,
        aging: InventoryAgingSnapshot | None,
        velocity: SalesVelocity | None,
        visibility: dict | None,
        promotion_history: list[dict],
        bundle_data: list[dict],
        companion_products: list[Product],
        generated_at: datetime,
    ) -> DeadStockRecoveryRecommendation:
        candidates: list[Candidate] = []
        rejected: list[dict] = []
        common = {
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
        elif _restricted(product):
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

        candidates = sorted(candidates, key=lambda item: item.score, reverse=True)
        primary = candidates[0]
        secondary = [item.action.value for item in candidates[1:3]]
        status = DeadStockRecoveryRecommendationStatus.OPEN
        if primary.action == DeadStockRecoveryAction.MANUAL_REVIEW and primary.confidence <= Decimal("35"):
            status = DeadStockRecoveryRecommendationStatus.INSUFFICIENT_DATA

        evidence = {
            "formula_version": self._calculation_version,
            "inputs": common,
            "candidate_actions": [_candidate_evidence(item) for item in candidates],
            "ranking_formula": "score = capital_recovery + sell_through + margin_safety + data_confidence + inventory_age + visibility_evidence - operational_complexity - further_loss_risk",
            "no_automatic_execution": True,
        }
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
            expires_at=generated_at + timedelta(days=settings.dead_stock_recovery_expiration_days),
        )

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
        allowed_discounts: list[tuple[Decimal, Decimal, object]] = []
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


def _restricted(product: Product) -> bool:
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
    if _decimal_or_none(evidence.get("impressions")) is not None and _decimal_or_none(evidence.get("impressions")) <= Decimal("100"):
        rules.append("LOW_IMPRESSIONS")
    if _decimal_or_none(evidence.get("click_through_rate")) is not None and _decimal_or_none(evidence.get("click_through_rate")) <= Decimal("0.01"):
        rules.append("LOW_CTR")
    if _decimal_or_none(evidence.get("listing_quality_score")) is not None and _decimal_or_none(evidence.get("listing_quality_score")) <= Decimal("40"):
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
