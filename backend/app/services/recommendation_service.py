from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import logging
import os
import time
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.recommendation_generator import RecommendationGenerator, RecommendationGenerationError
from app.analytics.pricing_engine import PricingEngine
from app.analytics.recommendation_builder import (
    InvalidAnalyticsDataError,
    InvalidProductDataError,
    MissingCompetitorDataError,
    RecommendationContextBuilder,
)
from app.analytics.stock_engine import StockEngine
from app.models.competitor import Competitor
from app.models.product import Product
from app.models.recommendation import Recommendation, RecommendationAction, RecommendationConfidence
from app.models.scrape_run import ScrapeRun
from app.schemas.recommendation import (
    RecommendationAnalyticsResponse,
    RecommendationGenerateResponse,
    RecommendationResponse,
)
from app.services.dashboard.events import DashboardEvent, DashboardEventEmitter
from app.websocket.socket_manager import socket_manager


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


class AnalyticsExecutionError(RecommendationServiceError):
    status_code = 400
    error_code = "analytics_failure"


class AIRecommendationError(RecommendationServiceError):
    status_code = 422
    error_code = "ai_generation_failed"


class RecommendationPersistenceError(RecommendationServiceError):
    status_code = 500
    error_code = "recommendation_persistence_failed"


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
        self._stock_risk_threshold = (
            stock_risk_threshold
            if stock_risk_threshold is not None
            else _get_env_float("BAZARSYNC_STOCK_RISK_EVENT_THRESHOLD", 0.7)
        )

    async def generate_recommendation(
        self, *, seller_id: UUID, product_id: UUID
    ) -> RecommendationGenerateResponse:
        start_time = time.monotonic()
        self._log_event(
            logging.INFO,
            "recommendation_generation_start",
            product_id=str(product_id),
        )

        product = self.load_product(seller_id, product_id)
        competitors = self.load_competitors(seller_id, product_id)
        analytics = self.run_analytics(product, competitors)
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
        context = self.build_context(product, competitors, analytics)
        self._log_event(
            logging.INFO,
            "recommendation_context_built",
            product_id=str(product_id),
        )
        self._log_event(
            logging.INFO,
            "recommendation_ai_start",
            product_id=str(product_id),
        )
        ai_response = await self.generate_ai_recommendation(context)
        self._log_event(
            logging.INFO,
            "recommendation_ai_complete",
            product_id=str(product_id),
            model=ai_response.metadata.model,
            latency_ms=ai_response.metadata.latency_ms,
            retry_count=ai_response.metadata.retry_count,
        )
        recommendation = self.save_recommendation(product, ai_response, context, analytics)
        self._log_event(
            logging.INFO,
            "recommendation_saved",
            recommendation_id=str(recommendation.id),
            product_id=str(product_id),
        )
        await self._emit_recommendation_created(
            seller_id=str(seller_id),
            recommendation=recommendation,
            analytics=analytics,
        )
        response = self.build_response(recommendation, analytics)

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
        return RecommendationGenerateResponse(
            success=True,
            product_id=recommendation.product_id,
            recommendation=recommendation_response,
            analytics=analytics_response,
            created_at=recommendation.created_at or datetime.now(timezone.utc),
        )

    def load_product(self, seller_id: UUID, product_id: UUID) -> Product:
        statement = select(Product).where(
            Product.id == product_id,
            Product.seller_id == seller_id,
        )
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
                ScrapeRun.status == "completed",
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

    def run_analytics(self, product: Product, competitors: list[dict[str, Any]]) -> dict[str, Any]:
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
            analytics = self._pricing_engine.analyze(payload)
            stock_metrics = self._stock_engine.analyze(payload)
        except (ValueError, InvalidAnalyticsDataError) as exc:
            raise AnalyticsExecutionError("Failed to compute analytics.") from exc

        analytics.update(
            {
                "estimated_days_of_stock_left": round(stock_metrics.estimated_days_of_stock_left, 2),
                "stock_risk_score": round(stock_metrics.stock_risk_score, 2),
                "urgency_score": round(stock_metrics.urgency_score, 2),
                "competitor_availability_ratio": round(
                    stock_metrics.competitor_availability_ratio, 2
                ),
                "out_of_stock_competitor_count": stock_metrics.out_of_stock_competitor_count,
                "in_stock_competitor_count": stock_metrics.in_stock_competitor_count,
            }
        )
        return analytics

    def build_context(
        self,
        product: Product,
        competitors: list[dict[str, Any]],
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
    ) -> Recommendation:
        context_snapshot = {
            "context": context,
            "analytics": dict(analytics),
        }
        recommendation = Recommendation(
            product_id=product.id,
            action=RecommendationAction(ai_response.recommendation.action),
            confidence=RecommendationConfidence(ai_response.recommendation.confidence),
            reasoning_bn=ai_response.recommendation.reasoning_bn,
            suggested_price_min=None,
            suggested_price_max=None,
            revenue_opportunity=Decimal(str(ai_response.recommendation.revenue_opportunity)),
            recommendation_context=context_snapshot,
        )

        try:
            self._db.add(recommendation)
            self._db.commit()
            self._db.refresh(recommendation)
        except Exception as exc:
            self._db.rollback()
            raise RecommendationPersistenceError("Failed to store recommendation.") from exc
        return recommendation

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

    async def _emit_recommendation_created(
        self,
        *,
        seller_id: str,
        recommendation: Recommendation,
        analytics: Mapping[str, Any],
    ) -> None:
        payload = {
            "recommendation_id": str(recommendation.id),
            "product_id": str(recommendation.product_id),
            "seller_id": seller_id,
            "action": recommendation.action.value,
            "confidence": recommendation.confidence.value,
            "revenue_opportunity": float(recommendation.revenue_opportunity),
            "urgency_score": analytics.get("urgency_score"),
            "stock_risk_score": analytics.get("stock_risk_score"),
            "created_at": recommendation.created_at.isoformat()
            if recommendation.created_at
            else None,
        }
        await self._event_emitter.emit(DashboardEvent.recommendation_created, payload)

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
        payload = {
            "product_id": str(product.id),
            "seller_id": seller_id,
            "stock_risk_score": stock_risk_score,
            "estimated_days_of_stock_left": analytics.get("estimated_days_of_stock_left"),
            "stock_quantity": product.stock_quantity,
        }
        await self._event_emitter.emit(DashboardEvent.stock_risk_detected, payload)

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
