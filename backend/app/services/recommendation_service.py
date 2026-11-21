from __future__ import annotations

import asyncio

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import logging
import os
import time
from typing import Any, Mapping, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.explanation import ACTION_TEMPLATES, render_explanation
from app.ai.prompts import EXPLANATION_PROMPT_VERSION
from app.ai.recommendation_generator import RecommendationGenerator, RecommendationGenerationError, generate_bangla_explanation
from app.ai.schemas import ExplanationEvidence
from app.analytics.pricing_engine import PricingEngine
from app.analytics.recommendation_builder import (
    InvalidAnalyticsDataError,
    InvalidProductDataError,
    MissingCompetitorDataError,
    RecommendationContextBuilder,
)
from app.analytics.stock_engine import StockEngine
from app.core.config import settings
from app.models.competitor import Competitor
from app.models.product import Product
from app.models.recommendation import Recommendation, RecommendationAction, RecommendationConfidence
from app.models.rag_memory import RagMemorySourceType
from app.models.scrape_run import ScrapeRun
from app.recommendations.opportunity_calculator import OpportunityCalculator, OpportunityInput
from app.schemas.recommendation import (
    RecommendationAnalyticsResponse,
    RecommendationGenerateResponse,
    RecommendationResponse,
)
from app.schemas.dashboard.summary_schema import DashboardSummaryResponse
from app.services.dashboard.events import DashboardEventEmitter
from app.services.dashboard.dashboard_service import DashboardService
from app.services.margin_guard import MarginGuard
from app.services.decision_orchestrator import DecisionOrchestrator
from app.services.recommendation_selection import RecommendationDecision
from app.schemas.recommendation_candidate import RecoveryParameters, ReorderParameters
from app.models.dead_stock_recovery_recommendation import DeadStockRecoveryAction
from app.services.phase5_realtime_service import Phase5RealtimePublisher
from app.services.recommendation_business_signals import RecommendationBusinessSignals
from app.services.recommendation_jobs import JobAttempt, RecommendationJobs
from app.services.recommendation_dashboard_evidence import build_dashboard_evidence
from app.services.recommendation_explanation_evidence import build_explanation_evidence
from app.services.recommendation_evidence_validator import (
    MIN_MATCH, InvalidRecommendationEvidence, RecommendationEvidenceValidator, validate_finite_json,
)
from app.scraper.constants import MARKETPLACE_NAME
from app.services.recommendation_evidence_service import RecommendationEvidence, RecommendationEvidenceService
from app.services.realtime import RealtimeService
from app.services.rag_index_outbox_service import RagIndexOutboxService
from app.websocket.socket_events import (
    DashboardSummaryPayload,
    DashboardSummarySnapshot,
    InsightPayload,
    MarketOpportunityPayload,
    MarketOpportunitySnapshot,
    RecommendationCreatedPayload,
    RecommendationSnapshot,
    UrgencyScoreUpdatedPayload,
)
from app.websocket.socket_manager import get_socket_emitter, socket_manager
from app.websocket.socket_rooms import seller_room
from app.db.async_session import AsyncSessionLocal


class RecommendationServiceError(Exception):
    status_code = 500
    error_code = "recommendation_error"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ProductNotFoundError(RecommendationServiceError):
    status_code = 404
    error_code = "product_not_found"


class CompetitorDataNotFoundError(RecommendationServiceError):
    status_code = 404
    error_code = "competitor_data_missing"

    def __init__(self, detail: str, *, evidence: RecommendationEvidence | None = None) -> None:
        super().__init__(detail)
        self.evidence = evidence


class AnalyticsExecutionError(RecommendationServiceError):
    status_code = 400
    error_code = "analytics_failure"


class AIRecommendationError(RecommendationServiceError):
    status_code = 422
    error_code = "ai_generation_failed"


class RecommendationPersistenceError(RecommendationServiceError):
    status_code = 500
    error_code = "recommendation_persistence_failed"


class RecommendationAttemptLostError(Exception):
    """A superseded attempt cannot persist its result."""


class RecommendationNotFoundError(RecommendationServiceError):
    status_code = 404
    error_code = "recommendation_not_found"


@dataclass(frozen=True)
class RecommendationServiceResult:
    recommendation: Recommendation
    analytics: Mapping[str, Any]


class RecommendationService:
    """Orchestrates analytics, AI generation, and persistence."""

    def __init__(
        self,
        db: Session,
        logger: logging.Logger | None = None,
        *,
        event_emitter: DashboardEventEmitter | None = None,
        stock_risk_threshold: float | None = None,
    ) -> None:
        self._db = db
        self._logger = logger or logging.getLogger(__name__)
        self._pricing_engine = PricingEngine()
        self._stock_engine = StockEngine()
        self._context_builder = RecommendationContextBuilder()
        self._ai_generator = RecommendationGenerator()
        self._event_emitter = event_emitter or socket_manager
        self._realtime: RealtimeService | None = None
        self._opportunity_calculator = OpportunityCalculator()
        self._stock_risk_threshold = (
            stock_risk_threshold
            if stock_risk_threshold is not None
            else _get_env_float("BAZARSYNC_STOCK_RISK_EVENT_THRESHOLD", 0.7)
        )

    async def generate_recommendation(
        self, *, seller_id: UUID, product_id: UUID, scrape_run_id: UUID | None = None,
        attempt: JobAttempt | None = None, legacy_delivery: bool = False,
    ) -> RecommendationGenerateResponse:
        start_time = time.monotonic()
        self._log_event(
            logging.INFO,
            "recommendation_generation_start",
            product_id=str(product_id),
        )

        product = self.load_product(seller_id, product_id)
        decision = None
        evidence: RecommendationEvidence | None
        context: dict[str, Any]
        if settings.recommendation_orchestration_enabled and not legacy_delivery:
            evidence = self._collect_decision_evidence(product, scrape_run_id)
            try:
                decision = DecisionOrchestrator(self._db).evaluate(product, evidence)
            except ValueError as exc:
                raise AnalyticsExecutionError("Recommendation decision inputs are invalid.") from exc
            context, analytics = {}, decision.analytics
        else:
            context, analytics, evidence = self.prepare_recommendation(product, scrape_run_id=scrape_run_id)
        self._log_event(
            logging.INFO,
            "recommendation_analytics_complete",
            product_id=str(product_id),
        )
        await self._emit_stock_risk_event(
            seller_id=str(seller_id),
            product=product,
            analytics=analytics,
        )
        self._log_event(
            logging.INFO,
            "recommendation_context_built",
            product_id=str(product_id),
        )
        ai_response = None
        if not settings.recommendation_explanation_enabled and decision is None and "business_signals_version" not in analytics:
            self._log_event(logging.INFO, "recommendation_ai_start", product_id=str(product_id))
            ai_response = await self.generate_ai_recommendation(context)
            self._log_event(
                logging.INFO, "recommendation_ai_complete", product_id=str(product_id),
                model=ai_response.metadata.model, latency_ms=ai_response.metadata.latency_ms,
                retry_count=ai_response.metadata.retry_count,
            )
        # Refresh economic inputs under the product lock before final approval.
        product = self.load_product(seller_id, product_id, for_persistence=True)
        recommendation = self.save_recommendation(
            product, ai_response, context, analytics, evidence=evidence, attempt=attempt,
            **({"decision": decision} if decision is not None else {}),
        )
        if settings.recommendation_explanation_enabled and settings.recommendation_explanation_groq_enabled:
            await self._enhance_saved_explanation(recommendation, seller_id=seller_id, product_id=product_id)
        self._log_event(
            logging.INFO,
            "recommendation_saved",
            generation_job_id=str(attempt.job_id) if attempt is not None else None,
            recommendation_id=str(recommendation.id),
            product_id=str(product_id),
        )
        response = self.read_result(recommendation)
        _, published_analytics = self._split_context_snapshot(recommendation.recommendation_context)
        try:
            async with asyncio.timeout(5):
                await self._emit_recommendation_created(
                    seller_id=str(seller_id), recommendation=recommendation,
                    product=product, analytics=published_analytics,
                )
        except Exception:
            self._logger.warning("recommendation_notification_failed product_id=%s", product_id, exc_info=True)

        if (
            decision is None
            and not settings.recommendation_orchestration_enabled
            and settings.recommendation_orchestration_shadow_enabled
        ):
            self._compare_shadow(product, response.recommendation.action, evidence, scrape_run_id)

        self._log_event(
            logging.INFO,
            "recommendation_generation_success",
            product_id=str(product_id),
            duration_ms=int((time.monotonic() - start_time) * 1000),
        )
        return response

    def get_latest_recommendation(
        self, *, seller_id: UUID, product_id: UUID
    ) -> RecommendationGenerateResponse:
        self.load_product(seller_id, product_id)
        statement = (
            select(Recommendation)
            .where(Recommendation.product_id == product_id)
            .order_by(Recommendation.created_at.desc(), Recommendation.id.desc())
            .limit(1)
        )
        recommendation = self._db.execute(statement).scalar_one_or_none()
        if not recommendation:
            raise RecommendationNotFoundError("No recommendations found.")

        return self.read_result(recommendation)

    def read_result(self, recommendation: Recommendation) -> RecommendationGenerateResponse:
        context_snapshot, analytics_snapshot = self._split_context_snapshot(
            recommendation.recommendation_context
        )
        analytics_response = self._build_analytics_response(
            analytics_snapshot, context_snapshot
        )
        recommendation_response = RecommendationResponse(
            action=recommendation.action.value,
            confidence=recommendation.confidence.value,
            reasoning_bn=recommendation.reasoning_bn,
            revenue_opportunity=float(recommendation.revenue_opportunity),
        )
        dashboard_evidence = None
        if settings.recommendation_dashboard_evidence_enabled:
            try:
                dashboard_evidence = build_dashboard_evidence(recommendation)
            except (ValueError, TypeError, KeyError, AttributeError):
                self._log_event(logging.WARNING, "recommendation_dashboard_evidence_unavailable")
        return RecommendationGenerateResponse(
            success=True,
            product_id=recommendation.product_id,
            dashboard_evidence=dashboard_evidence,
            recommendation=recommendation_response,
            analytics=analytics_response,
            created_at=recommendation.created_at or datetime.now(timezone.utc),
        )

    def load_product(
        self, seller_id: UUID, product_id: UUID, *, for_persistence: bool = False,
    ) -> Product:
        statement = select(Product).where(
            Product.id == product_id,
            Product.seller_id == seller_id,
        )
        if for_persistence:
            statement = statement.with_for_update(read=True).execution_options(populate_existing=True)
        product = self._db.execute(statement).scalar_one_or_none()
        if not product:
            raise ProductNotFoundError("Product not found.")
        return product

    def load_competitors(
        self, seller_id: UUID, product_id: UUID
    ) -> list[dict[str, Any]]:
        run_statement = (
            select(ScrapeRun.id)
            .where(
                ScrapeRun.product_id == product_id,
                ScrapeRun.seller_id == seller_id,
                ScrapeRun.status.in_(("COMPLETED", "completed")),
            )
            .order_by(
                ScrapeRun.finished_at.desc().nullslast(),
                ScrapeRun.created_at.desc(),
            )
            .limit(1)
        )
        scrape_run_id = self._db.execute(run_statement).scalar_one_or_none()
        if not scrape_run_id:
            raise CompetitorDataNotFoundError("No competitor data available.")

        competitor_statement = (
            select(Competitor.competitor_price, Competitor.stock_status)
            .where(
                Competitor.product_id == product_id,
                Competitor.scrape_run_id == scrape_run_id,
            )
            .order_by(Competitor.similarity_score.desc().nullslast())
        )
        rows = self._db.execute(competitor_statement).all()
        competitors: list[dict[str, Any]] = []
        for price, stock_status in rows:
            if price is None:
                continue
            competitors.append(
                {
                    "competitor_price": float(price),
                    "stock_status": stock_status,
                    "price": float(price),
                }
            )

        if not competitors:
            raise CompetitorDataNotFoundError("No valid competitor prices found.")
        return competitors

    def generation_preflight(self, product: Product) -> UUID | None:
        if settings.recommendation_orchestration_enabled:
            run = RecommendationEvidenceService(self._db).completed_run(
                seller_id=product.seller_id, product_id=product.id,
            )
            return run.id if run is not None else None
        _, _, evidence = self.prepare_recommendation(product)
        return evidence.scrape_run_id if evidence else None

    def _collect_decision_evidence(
        self, product: Product, scrape_run_id: UUID | None,
    ) -> RecommendationEvidence:
        return RecommendationEvidenceService(self._db).collect(
            seller_id=product.seller_id, product_id=product.id, scrape_run_id=scrape_run_id,
        )

    def _compare_shadow(
        self, product: Product, visible_action: str, evidence: RecommendationEvidence | None,
        scrape_run_id: UUID | None,
    ) -> None:
        try:
            # A diagnostic failure must leave the saved legacy result and job intact.
            with self._db.begin_nested():
                shared_evidence = evidence or self._collect_decision_evidence(product, scrape_run_id)
                orchestrator = DecisionOrchestrator(self._db)
                decision = orchestrator.evaluate(product, shared_evidence)
            self._log_event(
                logging.INFO, "recommendation_decision_shadow",
                seller_id=str(product.seller_id), product_id=str(product.id),
                legacy_action=visible_action, orchestrated_action=decision.action.value,
                match=visible_action == decision.action.value,
            )
        except Exception:
            self._logger.warning("recommendation_decision_shadow_failed", exc_info=True)

    def prepare_recommendation(
        self, product: Product, *, scrape_run_id: UUID | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], RecommendationEvidence | None]:
        evidence = None
        validated = settings.recommendation_validation_enabled or settings.recommendation_explanation_enabled
        if validated or settings.recommendation_evidence_enabled or settings.recommendation_business_signals_enabled or scrape_run_id is not None:
            evidence = RecommendationEvidenceService(self._db).collect(
                seller_id=product.seller_id, product_id=product.id, scrape_run_id=scrape_run_id,
            )
            competitors: Sequence[Mapping[str, Any]] = (
                RecommendationEvidenceValidator(MarginGuard(self._db)).market(
                    product, evidence, evidence.evaluated_at,
                ) if validated else evidence.market_competitors
            )
            if not competitors and not validated:
                self._log_event(
                    logging.INFO, "recommendation_evidence_insufficient",
                    seller_id=str(product.seller_id), product_id=str(product.id),
                    scrape_run_id=evidence.scrape_run_id, quality_flags=evidence.to_context()["quality_flags"],
                )
                raise CompetitorDataNotFoundError(
                    "No sufficiently fresh, verified competitor prices from the completed scrape.",
                    evidence=evidence,
                )
        else:
            competitors = self.load_competitors(product.seller_id, product.id)
        if validated or settings.recommendation_business_signals_enabled:
            analytics = RecommendationBusinessSignals(self._db).analyze(product, competitors)
            if validated:
                analytics["evidence_validation_version"] = 1
            # The Task 2 explanation uses the validated evidence and action directly.
            return {}, analytics, evidence
        analytics = self.run_analytics(product, competitors, freshness_aware=evidence is not None)
        context = self.build_context(product, competitors, analytics)
        return context, analytics, evidence

    def run_analytics(
        self, product: Product, competitors: Sequence[Mapping[str, Any]], *, freshness_aware: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "seller_price": float(product.selling_price),
            "seller_cost": float(product.cost_price),
            "stock_quantity": product.stock_quantity,
            "supplier_lead_time": product.supplier_lead_time,
            "minimum_margin": float(product.minimum_margin),
            "competitors": [
                {"price": item["price"], "stock_status": item.get("stock_status")}
                for item in competitors
            ],
        }

        try:
            analytics: dict[str, Any] = dict(self._pricing_engine.analyze(payload, freshness_aware=freshness_aware))
            stock_metrics = self._stock_engine.analyze(payload, freshness_aware=freshness_aware)
        except (ValueError, InvalidAnalyticsDataError) as exc:
            raise AnalyticsExecutionError("Failed to compute analytics.") from exc

        analytics.update(
            {
                "estimated_days_of_stock_left": round(stock_metrics.estimated_days_of_stock_left, 2),
                "stock_risk_score": round(stock_metrics.stock_risk_score, 2),
                "urgency_score": round(stock_metrics.urgency_score, 2),
                "competitor_availability_ratio": (
                    round(stock_metrics.competitor_availability_ratio, 2)
                    if stock_metrics.competitor_availability_ratio is not None else None
                ),
                "out_of_stock_competitor_count": stock_metrics.out_of_stock_competitor_count,
                "in_stock_competitor_count": stock_metrics.in_stock_competitor_count,
            }
        )
        if stock_metrics.competitor_availability_ratio is None:
            analytics["out_of_stock_competitor_count"] = None
            analytics["in_stock_competitor_count"] = None
        if analytics["action"] == "RAISE":
            # The legacy rule has no raised-price candidate to validate.
            analytics.update(action="HOLD", confidence=0.0, recommendation_confidence=0.0)
            analytics["reason_codes"].append("NO_VALIDATED_RAISE_CANDIDATE")
        self._apply_margin_guard(product=product, analytics=analytics)
        if freshness_aware:
            analytics["recommendation_confidence"] = analytics["confidence"]
        return analytics

    def build_context(
        self,
        product: Product,
        competitors: Sequence[Mapping[str, Any]],
        analytics: Mapping[str, Any],
    ) -> dict[str, Any]:
        product_payload = {
            "id": str(product.id),
            "title": product.title,
            "selling_price": float(product.selling_price),
            "cost_price": float(product.cost_price),
            "stock_quantity": product.stock_quantity,
            "supplier_lead_time": product.supplier_lead_time,
            "minimum_margin": float(product.minimum_margin),
        }
        competitor_payload = [
            {
                "competitor_price": item["competitor_price"],
                "stock_status": item.get("stock_status"),
            }
            for item in competitors
        ]

        try:
            context = self._context_builder.build_context(
                product_payload,
                competitor_payload,
                analytics,
                require_competitors=True,
            )
        except (InvalidProductDataError, MissingCompetitorDataError, InvalidAnalyticsDataError) as exc:
            raise AnalyticsExecutionError("Failed to build recommendation context.") from exc
        return context.to_dict()

    async def generate_ai_recommendation(self, context: dict[str, Any]):
        try:
            return await self._ai_generator.generate(context)
        except RecommendationGenerationError as exc:
            raise AIRecommendationError("AI recommendation generation failed.") from exc

    def save_recommendation(
        self,
        product: Product,
        ai_response,
        context: dict[str, Any],
        analytics: Mapping[str, Any],
        *,
        evidence: RecommendationEvidence | None = None,
        attempt: JobAttempt | None = None,
        decision: RecommendationDecision | None = None,
    ) -> Recommendation:
        suggested_price = None
        revenue_opportunity = Decimal("0.00")
        assessment = None
        explain_from_evidence = settings.recommendation_explanation_enabled
        if decision is not None:
            requested_action = decision.action.value
            try:
                decision = DecisionOrchestrator(self._db).finalize(product, decision)
                orchestration = decision.to_context()
                validate_finite_json(orchestration)
            except ValueError as exc:
                raise AnalyticsExecutionError("Recommendation decision could not be validated.") from exc
            guarded_action = decision.action.value
            guarded_confidence = decision.confidence.value
            suggested_price = decision.target_price
            primary_guard = next(
                (item.guard for item in decision.evaluations if item.candidate is decision.primary), None,
            )
            guard_evidence = {
                **(primary_guard or {}),
                "requested_action": requested_action,
                "final_action": guarded_action,
                "fail_closed": requested_action != guarded_action,
            }
            analytics = {
                **decision.analytics, "action": guarded_action, "candidate_price": (
                    str(suggested_price) if suggested_price is not None else None
                ), "reason_codes": list(decision.reason_codes),
            }
            reasoning = "" if explain_from_evidence else _orchestration_reasoning(decision)
            evidence = decision.context.competitors
        elif settings.recommendation_validation_enabled or explain_from_evidence or "evidence_validation_version" in analytics:
            if evidence is None:
                raise AnalyticsExecutionError("Scoped recommendation evidence is required.")
            try:
                assessment = RecommendationEvidenceValidator(MarginGuard(self._db)).assess(product, evidence, analytics)
                validate_finite_json(context)
            except InvalidRecommendationEvidence as exc:
                raise AnalyticsExecutionError("Recommendation evidence could not be validated.") from exc
            guarded_action = assessment.action.value
            guarded_confidence = assessment.confidence.value
            guard_evidence = assessment.guard
            suggested_price = assessment.candidate_price
            analytics = {
                **analytics, **assessment.market_metrics, "action": guarded_action, "candidate_price": (
                    str(suggested_price) if suggested_price is not None else None
                ), "reason_codes": list(assessment.reason_codes),
            }
            reasoning = "" if explain_from_evidence else _business_reasoning(guarded_action, analytics, guard_evidence)
        elif "business_signals_version" in analytics:
            guarded_action, guarded_confidence, guard_evidence = self._guard_business_decision(product, analytics)
            reasoning = _business_reasoning(guarded_action, analytics, guard_evidence)
            if guarded_action in {"LOWER", "RAISE"}:
                suggested_price = Decimal(str(analytics["candidate_price"]))
        else:
            guarded_action, guarded_confidence, guard_evidence = self._guard_final_recommendation(
                product=product,
                requested_action=str(analytics["action"]) if evidence is not None else str(ai_response.recommendation.action),
                requested_confidence=str(ai_response.recommendation.confidence),
                analytics=analytics,
            )
            reasoning = _guarded_reasoning(ai_response.recommendation.reasoning_bn, guard_evidence)
            if guarded_action != "HOLD":
                revenue_opportunity = Decimal(str(ai_response.recommendation.revenue_opportunity))
        context_snapshot = {
            "context": context,
            "analytics": dict(analytics),
            "margin_guard": guard_evidence,
        }
        if decision is not None:
            context_snapshot["decision_orchestration"] = orchestration
        if evidence is not None:
            context_snapshot["competitor_evidence"] = evidence.to_context()
        if assessment is not None:
            context_snapshot["evidence_assessment"] = assessment.to_context()
        if explain_from_evidence:
            context_snapshot["explanation"] = {
                "source": "template", "prompt_version": EXPLANATION_PROMPT_VERSION,
            }
            try:
                market_at = max((
                    observation.price_evidence.observed_at
                    for observation in evidence.observations
                    if observation.price_evidence.status.value == "FRESH"
                    and observation.price_evidence.observed_at is not None
                    and observation.match_score is not None and MIN_MATCH <= observation.match_score <= 1
                    and observation.price is not None and observation.price.is_finite() and observation.price > 0
                ), default=None) if evidence is not None else None
                explanation = build_explanation_evidence(
                    product=product, action=RecommendationAction(guarded_action).value,
                    confidence=RecommendationConfidence(guarded_confidence).value,
                    target_price=suggested_price, analytics=analytics, guard=guard_evidence,
                    decision=decision, evaluated_at=datetime.now(timezone.utc),
                    market_observed_at=market_at,
                )
                reasoning = render_explanation(explanation)
                context_snapshot["explanation"]["evidence"] = explanation.model_dump(mode="json")
            except Exception as exc:
                reasoning = ACTION_TEMPLATES[guarded_action][0]
                self._log_event(logging.WARNING, "recommendation_explanation_evidence_unavailable",
                                error_type=type(exc).__name__)
            self._log_event(logging.INFO, "recommendation_explanation_rendered",
                            source="template", prompt_version=EXPLANATION_PROMPT_VERSION)
        recommendation = Recommendation(
            product_id=product.id,
            action=RecommendationAction(guarded_action),
            confidence=RecommendationConfidence(guarded_confidence),
            reasoning_bn=reasoning,
            suggested_price_min=suggested_price,
            suggested_price_max=suggested_price,
            revenue_opportunity=revenue_opportunity,
            recommendation_context=context_snapshot,
        )

        try:
            jobs = RecommendationJobs(self._db) if attempt is not None else None
            if jobs is not None and attempt is not None and not jobs.can_complete(attempt):
                raise RecommendationAttemptLostError()
            self._db.add(recommendation)
            if hasattr(self._db, "flush"):
                self._db.flush()
                RagIndexOutboxService(self._db).enqueue_upsert(
                    seller_id=product.seller_id,
                    source_type=RagMemorySourceType.RECOMMENDATION,
                    source_id=str(recommendation.id),
                    product_id=product.id,
                    source_updated_at=datetime.now(timezone.utc),
                )
            if jobs is not None and attempt is not None and not jobs.complete(attempt, recommendation.id):
                raise RecommendationAttemptLostError()
            self._db.commit()
        except RecommendationAttemptLostError:
            self._db.rollback()
            raise
        except Exception as exc:
            if hasattr(self._db, "rollback"):
                self._db.rollback()
            raise RecommendationPersistenceError("Failed to store recommendation.") from exc
        return recommendation

    async def _enhance_saved_explanation(
        self, recommendation: Recommendation, *, seller_id: UUID, product_id: UUID,
    ) -> None:
        """Update the explanation and its index together after the decision commits."""
        try:
            raw = recommendation.recommendation_context.get("explanation", {}).get("evidence")
            if raw is None:
                return
            evidence = ExplanationEvidence.model_validate(raw)
            reasoning = await generate_bangla_explanation(evidence)
            if reasoning is None or reasoning == recommendation.reasoning_bn:
                return
            current = self._db.scalars(
                select(Recommendation).join(Product)
                .where(Recommendation.id == recommendation.id, Recommendation.product_id == product_id,
                       Product.seller_id == seller_id)
                .with_for_update(of=Recommendation).execution_options(populate_existing=True)
            ).first()
            if current is None:
                self._db.rollback()
                return
            snapshot = current.recommendation_context
            metadata = snapshot.get("explanation", {})
            if metadata.get("source") != "template" or metadata.get("evidence") != raw or (
                current.action.value, current.confidence.value
            ) != (evidence.action, evidence.confidence):
                self._db.rollback()
                return
            current.reasoning_bn = reasoning
            current.recommendation_context = {**snapshot, "explanation": {
                **metadata, "source": "groq", "model": settings.recommendation_explanation_model,
            }}
            RagIndexOutboxService(self._db).enqueue_upsert(
                seller_id=seller_id, product_id=product_id, source_type=RagMemorySourceType.RECOMMENDATION,
                source_id=str(current.id), source_updated_at=datetime.now(timezone.utc),
            )
            self._db.commit()
            self._log_event(logging.INFO, "recommendation_explanation_rendered",
                            source="groq", prompt_version=EXPLANATION_PROMPT_VERSION)
        except Exception as exc:
            self._db.rollback()
            self._log_event(logging.WARNING, "recommendation_explanation_update_failed",
                            source="template", prompt_version=EXPLANATION_PROMPT_VERSION,
                            error_type=type(exc).__name__)

    def _guard_business_decision(
        self, product: Product, analytics: Mapping[str, Any],
    ) -> tuple[str, str, dict[str, Any]]:
        action = str(analytics["action"])
        score = float(analytics["confidence"])
        confidence = "HIGH" if score >= 0.75 else "MEDIUM" if score >= 0.5 else "LOW"
        if action not in {"LOWER", "RAISE"}:
            return action, confidence, {"requested_action": action, "final_action": action}
        candidate = analytics.get("candidate_price")
        if candidate is None:
            return "HOLD", "LOW", {"requested_action": action, "final_action": "HOLD", "fail_closed": True}
        price = Decimal(str(candidate))
        guard = MarginGuard(self._db).validate_candidate(
            seller_id=product.seller_id, product=product, candidate_price=price, marketplace=MARKETPLACE_NAME,
        )
        safe = guard.is_allowed and price == guard.candidate_price and (
            0 < price < product.selling_price if action == "LOWER" else price > product.selling_price
        )
        final = action if safe else "HOLD"
        return final, confidence if safe else "LOW", {
            **guard.to_evidence(), "requested_action": action, "final_action": final, "fail_closed": not safe,
        }

    def _apply_margin_guard(self, *, product: Product, analytics: dict[str, Any]) -> None:
        requested_action = str(analytics.get("action", "HOLD")).upper()
        candidate_price = _candidate_price_for_action(
            action=requested_action,
            product=product,
            analytics=analytics,
        )
        guard = MarginGuard(self._db).validate_candidate(
            seller_id=product.seller_id,
            product=product,
            candidate_price=candidate_price,
        )
        analytics["margin_guard"] = guard.to_evidence()
        analytics["candidate_price"] = float(guard.candidate_price)
        if requested_action in {"LOWER", "RAISE"} and not guard.is_allowed:
            analytics["action"] = "HOLD"
            analytics["confidence"] = min(float(analytics.get("confidence", 0.0)), 0.45)
            analytics.setdefault("reason_codes", []).append("MARGIN_GUARD_BLOCKED_PRICE_RECOMMENDATION")

    def _guard_final_recommendation(
        self,
        *,
        product: Product,
        requested_action: str,
        requested_confidence: str,
        analytics: Mapping[str, Any],
    ) -> tuple[str, str, dict[str, Any]]:
        action = requested_action.upper()
        candidate_price = _candidate_price_for_action(
            action=action,
            product=product,
            analytics=analytics,
        )
        guard = MarginGuard(self._db).validate_candidate(
            seller_id=product.seller_id,
            product=product,
            candidate_price=candidate_price,
        )
        evidence = guard.to_evidence()
        evidence["requested_action"] = action
        if action == "RAISE" or (action == "LOWER" and (
            not guard.is_allowed or not 0 < candidate_price < product.selling_price
        )):
            evidence["final_action"] = "HOLD"
            evidence["fail_closed"] = True
            return "HOLD", "LOW", evidence
        evidence["final_action"] = action
        evidence["fail_closed"] = False
        return action, requested_confidence.upper(), evidence

    def build_response(
        self,
        recommendation: Recommendation,
        analytics: Mapping[str, Any],
    ) -> RecommendationGenerateResponse:
        analytics_response = self._build_analytics_response(analytics, None)
        recommendation_response = RecommendationResponse(
            action=recommendation.action.value,
            confidence=recommendation.confidence.value,
            reasoning_bn=recommendation.reasoning_bn,
            revenue_opportunity=float(recommendation.revenue_opportunity),
        )
        return RecommendationGenerateResponse(
            success=True,
            product_id=recommendation.product_id,
            recommendation=recommendation_response,
            analytics=analytics_response,
            created_at=recommendation.created_at or datetime.now(timezone.utc),
        )

    def _log_event(self, level: int, event: str, **fields: Any) -> None:
        safe_fields = {key: value for key, value in fields.items() if value is not None}
        payload = " ".join(f"{key}={value}" for key, value in safe_fields.items())
        self._logger.log(level, f"{event} {payload}".strip())

    def _resolve_realtime(self) -> RealtimeService | None:
        if self._realtime is not None:
            return self._realtime
        try:
            emitter = get_socket_emitter()
        except RuntimeError:
            if not settings.redis_broker_url:
                return None
            self._realtime = RealtimeService(Phase5RealtimePublisher(self._logger))
            return self._realtime
        self._realtime = RealtimeService(emitter, logging.getLogger("app.websocket.realtime"))
        return self._realtime

    async def _emit_urgency_score_updated(
        self,
        *,
        realtime: RealtimeService,
        seller_id: UUID,
        recommendation: Recommendation,
        urgency_score: float,
    ) -> None:
        previous_score = self._load_previous_urgency_score(
            seller_id=seller_id,
            recommendation_id=recommendation.id,
            product_id=recommendation.product_id,
        )
        delta = int(round(urgency_score - previous_score)) if previous_score is not None else None
        payload = UrgencyScoreUpdatedPayload(
            urgency_score=int(round(urgency_score)),
            previous_score=int(round(previous_score)) if previous_score is not None else None,
            delta=delta,
            updated_at=recommendation.created_at or datetime.now(timezone.utc),
            reason="Recommendation generated.",
        )
        await realtime.emit_urgency_score_updated(
            payload, seller_id=seller_id, rooms=[seller_room(str(seller_id))]
        )

    async def _emit_dashboard_summary_updated(
        self,
        *,
        realtime: RealtimeService,
        seller_id: UUID,
    ) -> None:
        async with AsyncSessionLocal() as session:
            service = DashboardService(session, logger=self._logger)
            summary = await service.get_summary(seller_id=str(seller_id))
        payload = DashboardSummaryPayload(
            summary=_build_dashboard_summary_snapshot(summary)
        )
        await realtime.emit_dashboard_summary_updated(
            payload, seller_id=seller_id, rooms=[seller_room(str(seller_id))]
        )

    async def _emit_market_opportunity_detected(
        self,
        *,
        realtime: RealtimeService,
        seller_id: UUID,
        recommendation: Recommendation,
        product: Product,
        analytics: Mapping[str, Any],
    ) -> None:
        if recommendation.revenue_opportunity <= 0:
            return
        snapshot = _build_market_opportunity_snapshot(
            recommendation=recommendation,
            product=product,
            analytics=analytics,
            calculator=self._opportunity_calculator,
        )
        if not snapshot:
            return
        payload = MarketOpportunityPayload(opportunity=snapshot)
        await realtime.emit_market_opportunity_detected(
            payload,
            seller_id=seller_id,
            product_id=recommendation.product_id,
            rooms=[seller_room(str(seller_id))],
        )

    def _load_previous_urgency_score(
        self,
        *,
        seller_id: UUID,
        recommendation_id: UUID,
        product_id: UUID,
    ) -> float | None:
        statement = (
            select(Recommendation.recommendation_context)
            .join(Product, Recommendation.product_id == Product.id)
            .where(
                Recommendation.product_id == product_id,
                Recommendation.id != recommendation_id,
                Product.seller_id == seller_id,
            )
            .order_by(Recommendation.created_at.desc(), Recommendation.id.desc())
            .limit(1)
        )
        payload = self._db.execute(statement).scalar_one_or_none()
        if not payload:
            return None
        _, analytics = self._split_context_snapshot(payload)
        return _normalize_score(analytics.get("urgency_score"))

    async def _emit_recommendation_created(
        self,
        *,
        seller_id: str,
        recommendation: Recommendation,
        product: Product,
        analytics: Mapping[str, Any],
    ) -> None:
        realtime = self._resolve_realtime()
        if not realtime:
            self._logger.debug("realtime_emit_skipped reason=socket_unavailable")
            return
        seller_uuid = UUID(seller_id)
        urgency_score = _normalize_score(analytics.get("urgency_score"))
        recommendation_snapshot = RecommendationSnapshot(
            id=recommendation.id,
            title=_format_recommendation_title(recommendation.action),
            summary=recommendation.reasoning_bn,
            action=_map_action(recommendation.action),
            status="new",
            priority=_map_priority(urgency_score),
            confidence=_map_confidence(recommendation.confidence),
            expected_lift=0.0 if {"business_signals_version", "decision_orchestration_version"} & analytics.keys() else _expected_lift(urgency_score),
            product=product.title,
            competitor=None,
            created_at=recommendation.created_at or datetime.now(timezone.utc),
        )
        payload = RecommendationCreatedPayload(
            recommendation=recommendation_snapshot,
            urgency_score=int(round(urgency_score)),
            confidence=recommendation.confidence.value,
            opportunity_score=float(recommendation.revenue_opportunity),
        )
        await realtime.emit_recommendation_created(
            payload,
            seller_id=seller_uuid,
            product_id=recommendation.product_id,
            rooms=[seller_room(str(seller_uuid))],
        )
        await self._emit_urgency_score_updated(
            realtime=realtime,
            seller_id=seller_uuid,
            recommendation=recommendation,
            urgency_score=urgency_score,
        )
        await self._emit_dashboard_summary_updated(realtime=realtime, seller_id=seller_uuid)
        await self._emit_market_opportunity_detected(
            realtime=realtime,
            seller_id=seller_uuid,
            recommendation=recommendation,
            product=product,
            analytics=analytics,
        )

    async def _emit_stock_risk_event(
        self,
        *,
        seller_id: str,
        product: Product,
        analytics: Mapping[str, Any],
    ) -> None:
        stock_risk_score = self._to_float(analytics.get("stock_risk_score"))
        if stock_risk_score is None:
            return
        if stock_risk_score < self._stock_risk_threshold:
            return
        self._logger.info(
            "stock_risk_detected seller_id=%s product_id=%s score=%s",
            seller_id,
            product.id,
            stock_risk_score,
        )

    def _build_analytics_response(
        self,
        analytics: Mapping[str, Any] | None,
        context: Mapping[str, Any] | None,
    ) -> RecommendationAnalyticsResponse:
        def pick(key: str, context_key: str | None = None) -> Any:
            if analytics and key in analytics:
                return analytics.get(key)
            if context_key and context and context_key in context:
                return context.get(context_key)
            return None

        competitor_median_price = self._to_float(
            pick("competitor_median_price", "competitor_median_price")
        )
        price_gap_percent = self._to_float(pick("price_gap_percent"))
        competitors_oos = self._to_int(
            pick("out_of_stock_competitor_count", "competitors_oos")
        )
        stock_risk_score = self._to_float(
            pick("stock_risk_score", "stock_risk_score")
        ) or 0.0
        pricing_pressure_score = self._to_float(
            pick("pricing_pressure_score", "pricing_pressure_score")
        ) or 0.0
        estimated_days_of_stock_left = self._to_float(
            pick("estimated_days_of_stock_left", "days_of_stock_left")
        ) or 0.0

        return RecommendationAnalyticsResponse(
            competitor_median_price=competitor_median_price,
            price_gap_percent=price_gap_percent,
            competitors_oos=competitors_oos,
            stock_risk_score=stock_risk_score,
            pricing_pressure_score=pricing_pressure_score,
            estimated_days_of_stock_left=estimated_days_of_stock_left,
            **({
                "stock_coverage_available": analytics.get("estimated_days_of_stock_left") is not None,
                "stock_risk_available": analytics.get("stock_risk_score") is not None,
            } if analytics and ("business_signals_version" in analytics or "decision_orchestration_version" in analytics) else {}),
        )

    @staticmethod
    def _split_context_snapshot(
        payload: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        if "context" in payload or "analytics" in payload:
            context = payload.get("context")
            analytics = payload.get("analytics")
            return (
                context if isinstance(context, Mapping) else {},
                analytics if isinstance(analytics, Mapping) else {},
            )
        return payload, {}

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


def _get_env_float(key: str, default: float) -> float:
    value = os.getenv(key)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _normalize_score(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if 0 <= numeric <= 1:
        return numeric * 100.0
    return numeric


def _map_action(action: RecommendationAction) -> str:
    if action is RecommendationAction.LOWER:
        return "undercut"
    if action is RecommendationAction.RAISE:
        return "raise_price"
    if action is RecommendationAction.REORDER:
        return "restock"
    return "hold"


def _format_recommendation_title(action: RecommendationAction) -> str:
    if action is RecommendationAction.LOWER:
        return "Lower price recommendation"
    if action is RecommendationAction.RAISE:
        return "Raise price recommendation"
    if action is RecommendationAction.REORDER:
        return "Restock recommendation"
    return "Hold price recommendation"


def _map_priority(urgency_score: float) -> str:
    if urgency_score >= 80:
        return "critical"
    if urgency_score >= 60:
        return "high"
    if urgency_score >= 40:
        return "medium"
    return "low"


def _map_confidence(confidence: RecommendationConfidence) -> float:
    if confidence is RecommendationConfidence.HIGH:
        return 0.9
    if confidence is RecommendationConfidence.MEDIUM:
        return 0.7
    if confidence is RecommendationConfidence.LOW:
        return 0.5
    return 0.6


def _expected_lift(urgency_score: float) -> float:
    return min(max(urgency_score / 100.0, 0.0), 1.0)


def _build_dashboard_summary_snapshot(summary: DashboardSummaryResponse) -> DashboardSummarySnapshot:
    insights = []
    if summary.market_trend_summary:
        severity = "high" if summary.average_urgency_score >= 75 else "medium"
        if summary.average_urgency_score < 55:
            severity = "low"
        insights.append(
            {
                "id": "market-trend",
                "title": "Market trend",
                "summary": summary.market_trend_summary,
                "severity": severity,
            }
        )
    activity = summary.realtime_activity
    insights.append(
        {
            "id": "realtime-activity",
            "title": "Last hour activity",
            "summary": (
                f"Recommendations {activity.recommendations_last_hour}, alerts "
                f"{activity.alerts_last_hour}, competitor updates "
                f"{activity.competitor_updates_last_hour}."
            ),
            "severity": "low",
        }
    )
    system_status = "degraded" if summary.high_risk_stock_count > 0 or summary.active_alerts > 0 else "healthy"
    return DashboardSummarySnapshot(
        kpis=[],
        insights=[InsightPayload.model_validate(item) for item in insights],
        active_alerts=summary.active_alerts,
        live_competitors=summary.total_monitored_products,
        ai_recommendations=summary.realtime_activity.recommendations_last_hour,
        revenue_opportunities=summary.opportunity_count,
        urgency_score=int(round(summary.latest_urgency_score)),
        system_status=system_status,
        last_synced_at=summary.generated_at,
    )


def _candidate_price_for_action(
    *,
    action: str,
    product: Product,
    analytics: Mapping[str, Any],
) -> Decimal:
    if action.upper() == "LOWER":
        candidate = analytics.get("candidate_price") or analytics.get("competitor_median_price")
        if candidate is not None:
            return Decimal(str(candidate))
    return Decimal(str(product.selling_price))


def _orchestration_reasoning(decision: RecommendationDecision) -> str:
    params = decision.primary.proposed_parameters if decision.primary else None
    if isinstance(params, ReorderParameters) and decision.action == RecommendationAction.REORDER:
        return f"নথিভুক্ত বিক্রয় ও মজুত অনুযায়ী {params.quantity} ইউনিট পুনরায় অর্ডার করুন। আপাতত বর্তমান দাম রাখুন।"
    if decision.target_price is not None:
        return f"সাম্প্রতিক বাজারদর, বিক্রয় ও প্রযোজ্য ফি অনুযায়ী প্রস্তাবিত দাম ৳{decision.target_price}।"
    if isinstance(params, RecoveryParameters):
        return {
            DeadStockRecoveryAction.BUNDLE: "ধীরগতির মজুত বিক্রির জন্য বান্ডেল প্রস্তাবটি পর্যালোচনা করুন।",
            DeadStockRecoveryAction.DISCOUNT: "ধীরগতির মজুতের জন্য সীমিত ছাড়ের প্রস্তাবটি পর্যালোচনা করুন।",
            DeadStockRecoveryAction.FLASH_SALE: "ধীরগতির মজুতের জন্য স্বল্পমেয়াদি অফারটি পর্যালোচনা করুন।",
            DeadStockRecoveryAction.SEO_FIX: "পণ্যের তালিকা আরও সহজে খুঁজে পেতে তথ্য ও সার্চ দৃশ্যমানতা পর্যালোচনা করুন।",
            DeadStockRecoveryAction.MANUAL_REVIEW: "ধীরগতির মজুতের তথ্য যাচাই করে পরবর্তী পদক্ষেপ নির্ধারণ করুন।",
            DeadStockRecoveryAction.HOLD: "আপাতত বর্তমান দাম ও মজুত পরিকল্পনা বজায় রাখুন।",
        }[params.action]
    return "পরিবর্তনের পক্ষে যথেষ্ট যাচাই করা তথ্য নেই। আপাতত বর্তমান দাম ও মজুত পরিকল্পনা বজায় রাখুন।"


def _business_reasoning(
    action: str, analytics: Mapping[str, Any], guard: Mapping[str, Any],
) -> str:
    if action == "REORDER":
        return "নথিভুক্ত বিক্রয় ও মজুতের ভিত্তিতে পুনরায় পণ্য অর্ডার করার পরামর্শ দেওয়া হচ্ছে।"
    if action == "LOWER":
        return f"প্রতিযোগীদের সাম্প্রতিক দাম ও প্রযোজ্য ফি বিবেচনায় প্রস্তাবিত দাম ৳{analytics['candidate_price']}।"
    if action == "RAISE":
        return f"প্রযোজ্য মূল্যনীতি অনুযায়ী প্রস্তাবিত দাম ৳{analytics['candidate_price']}।"
    if (
        {"MARGIN_GUARD_BLOCKED", "MARGIN_GUARD_BLOCKED_PRICE_RECOMMENDATION"}.intersection(analytics["reason_codes"])
        or ("evidence_validation_version" not in analytics and guard.get("fail_closed"))
    ):
        return "দাম পরিবর্তনের প্রস্তাবটি মার্জিন বা মূল্যনীতির শর্ত পূরণ করেনি। আপাতত বর্তমান দাম রাখুন।"
    if "evidence_validation_version" in analytics and (
        guard.get("fail_closed") or "INSUFFICIENT_ACTION_EVIDENCE" in analytics["reason_codes"]
    ):
        return "প্রস্তাবিত পরিবর্তনের পক্ষে যথেষ্ট নির্ভরযোগ্য তথ্য নেই। আপাতত বর্তমান সিদ্ধান্ত বজায় রাখুন।"
    inventory = analytics["inventory_evidence"]
    if inventory["demand_status"] == "INSUFFICIENT":
        return "দৈনিক চাহিদা নির্ধারণের জন্য যথেষ্ট বিক্রয় তথ্য নেই। আপাতত বর্তমান সিদ্ধান্ত বজায় রাখুন।"
    if inventory["daily_net_sales_rate"] == "0.0000":
        return "পর্যবেক্ষিত সময়ে নিট বিক্রি শূন্য ছিল। আপাতত বর্তমান সিদ্ধান্ত বজায় রাখুন।"
    if inventory["available_units"] is None or inventory["supplier_lead_time_days"] is None:
        return "হালনাগাদ মজুত বা সরবরাহের সময় সম্পর্কে পর্যাপ্ত তথ্য নেই। আপাতত বর্তমান সিদ্ধান্ত বজায় রাখুন।"
    if {"MISSING_FEE_DATA", "MISSING_COST_DATA", "INVALID_POLICY", "UNSUPPORTED_CURRENCY"}.intersection(analytics["reason_codes"]):
        return "দাম পরিবর্তন যাচাই করার জন্য নির্ভরযোগ্য খরচ, ফি বা মূল্যনীতি পাওয়া যায়নি। বর্তমান দাম রাখুন।"
    return "উপলব্ধ তথ্য অনুযায়ী এখনই দাম বা মজুতে পরিবর্তনের সুপারিশ নেই।"


def _guarded_reasoning(reasoning: str, guard_evidence: Mapping[str, Any]) -> str:
    if guard_evidence.get("fail_closed"):
        reasons = ", ".join(guard_evidence.get("rejection_reasons", []))
        return f"{reasoning.strip()} Margin guard blocked price lowering: {reasons}."
    return reasoning


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_market_opportunity_snapshot(
    *,
    recommendation: Recommendation,
    product: Product,
    analytics: Mapping[str, Any],
    calculator: OpportunityCalculator,
) -> MarketOpportunitySnapshot | None:
    context, analytics_snapshot = RecommendationService._split_context_snapshot(
        recommendation.recommendation_context
    )
    merged_analytics = {**analytics_snapshot, **dict(analytics)}
    seller_price = _to_float(context.get("seller_price")) or float(product.selling_price)
    recommended_price = _to_float(context.get("recommended_price"))
    stock_quantity = _to_int(context.get("seller_stock")) or int(product.stock_quantity or 0)
    margin_percent = _to_float(merged_analytics.get("estimated_margin_percent"))
    if margin_percent is None:
        margin_percent = _compute_margin_percent(
            float(product.selling_price), float(product.cost_price)
        )
    opportunity_score = _to_float(merged_analytics.get("market_competitiveness_score")) or 0.0
    demand_indicator = _to_float(merged_analytics.get("demand_indicator")) or 0.0
    competitor_oos_ratio = _compute_oos_ratio(merged_analytics)
    inventory_turnover_days = _to_float(context.get("inventory_turnover_days"))

    try:
        result = calculator.calculate(
            OpportunityInput(
                seller_price=seller_price,
                recommended_price=recommended_price,
                current_stock=stock_quantity,
                margin_percent=margin_percent,
                opportunity_score=opportunity_score,
                demand_indicator=demand_indicator,
                competitor_oos_ratio=competitor_oos_ratio,
                inventory_turnover_days=inventory_turnover_days,
            )
        )
    except Exception:
        return None

    description = _build_opportunity_description(result)
    time_window = (
        recommendation.created_at.date().isoformat()
        if recommendation.created_at
        else "Rolling"
    )
    category = _resolve_opportunity_category(
        competitor_oos_ratio, result.projected_demand_shift
    )
    urgency_score = int(round(_normalize_score(merged_analytics.get("urgency_score"))))

    return MarketOpportunitySnapshot(
        id=recommendation.id,
        title=product.title,
        description=description,
        potential_revenue=float(recommendation.revenue_opportunity),
        probability=competitor_oos_ratio,
        urgency_score=urgency_score,
        time_window=time_window,
        category=category,
    )


def _build_opportunity_description(result) -> str:
    units = round(result.inventory_capture_units, 2)
    profit = round(result.estimated_profit_impact, 2)
    return f"Capture {units} units, est. profit impact {profit}"


def _resolve_opportunity_category(competitor_oos_ratio: float, demand_shift: float) -> str:
    if competitor_oos_ratio >= 0.5:
        return "inventory"
    if demand_shift >= 15:
        return "promotion"
    return "pricing"


def _compute_oos_ratio(analytics: Mapping[str, Any]) -> float:
    out_of_stock = _to_int(analytics.get("out_of_stock_competitor_count")) or 0
    in_stock = _to_int(analytics.get("in_stock_competitor_count")) or 0
    total = out_of_stock + in_stock
    if total == 0:
        return 0.0
    return out_of_stock / total


def _compute_margin_percent(selling_price: float, cost_price: float) -> float:
    if selling_price <= 0:
        return 0.0
    return ((selling_price - cost_price) / selling_price) * 100.0
