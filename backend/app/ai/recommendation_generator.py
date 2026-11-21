"""AI-driven recommendation generation.

This module orchestrates Groq LLM calls and validates the response strictly.
The LLM never computes business metrics; it only explains deterministic analytics.

Example usage:
    from app.ai.recommendation_generator import RecommendationGenerator

    generator = RecommendationGenerator()
    result = await generator.generate({
        "sku": "DBL200",
        "product_title": "Dove Body Lotion 200ml",
        "seller_price": 450,
        "seller_cost": 320,
        "seller_stock": 20,
        "competitor_min_price": 420,
        "competitor_median_price": 435,
        "competitors_oos": 2,
        "margin_after_fees": 18,
        "margin_floor": 15,
        "days_of_stock_left": 6,
        "supplier_lead_time": 7,
        "pricing_pressure_score": 0.75,
        "stock_risk_score": 0.64,
        "recommended_action": "LOWER",
        "recommendation_confidence": 0.82,
    })

    print(result.model_dump())

Sample valid LLM response:
    {"action":"LOWER","confidence":"HIGH","reasoning_bn":"...","revenue_opportunity":0}

Sample invalid LLM response (rejected):
    {"action":"LOWER","confidence":"HIGH","reasoning_bn":"...","extra":"field"}
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import asyncio
import time
from typing import Any, Mapping, Sequence

from pydantic import ValidationError
from tenacity import AsyncRetrying, RetryCallState, retry_if_exception, stop_after_attempt
from tenacity import wait_exponential_jitter

from app.ai.groq_client import (
    GroqAPIError,
    GroqInvalidResponseError,
    GroqRateLimitError,
    GroqTimeoutError,
    GroqUnavailableError,
    generate_completion,
    generate_json_completion,
)
from app.ai.explanation import approved_sentences, render_explanation, selection_schema
from app.ai.prompts import EXPLANATION_PROMPT_VERSION, build_explanation_prompt, build_recommendation_prompt
from app.ai.schemas import (
    AIModelResponse,
    ExplanationEvidence,
    ExplanationSelection,
    RecommendationContext,
    RecommendationMetadata,
    RecommendationResponse,
)
from app.core.config import settings


async def generate_bangla_explanation(evidence: ExplanationEvidence) -> str | None:
    """Return verified text or let the stored template stand."""
    logger = logging.getLogger(__name__)
    try:
        timeout = settings.recommendation_explanation_timeout_seconds
        async with asyncio.timeout(timeout):
            response = await generate_completion(
                build_explanation_prompt(evidence, approved_sentences(evidence)),
                model=settings.recommendation_explanation_model,
                temperature=settings.recommendation_explanation_temperature,
                max_tokens=768,
                response_format=selection_schema(evidence),
                timeout_seconds=timeout,
                max_retries=settings.recommendation_explanation_max_retries,
            )
        content = response.get("content")
        if not isinstance(content, str) or len(content) > 4096:
            raise ValueError("Invalid explanation content.")
        return render_explanation(evidence, ExplanationSelection.model_validate_json(content))
    except Exception as exc:
        logger.info("recommendation_explanation_fallback prompt_version=%s source=template error_type=%s",
                    EXPLANATION_PROMPT_VERSION, type(exc).__name__)
        return None


class RecommendationGenerationError(Exception):
    """Base class for recommendation generation failures."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class InvalidAIResponseError(RecommendationGenerationError):
    """Raised when the LLM response is empty or malformed."""


class RecommendationValidationError(RecommendationGenerationError):
    """Raised when AI output violates schema rules."""


class RecommendationTimeoutError(RecommendationGenerationError):
    """Raised when LLM requests timeout."""


@dataclass(frozen=True)
class _GenerationResult:
    recommendation: RecommendationResponse
    metadata: RecommendationMetadata


class RecommendationGenerator:
    """Generates Bangla recommendations using Groq with strict validation."""

    def __init__(
        self,
        *,
        max_retries: int = 2,
        logger: logging.Logger | None = None,
    ) -> None:
        self._max_retries = max(0, max_retries)
        self._logger = logger or logging.getLogger(__name__)

    async def generate(self, context: Mapping[str, Any] | RecommendationContext) -> AIModelResponse:
        """Generate a validated AI recommendation response."""
        validated_context = (
            context
            if isinstance(context, RecommendationContext)
            else RecommendationContext.model_validate(context)
        )
        messages = build_recommendation_prompt(validated_context.model_dump())

        start_time = time.monotonic()
        self._log_event(
            logging.INFO,
            "ai_recommendation_start",
            model=None,
            sku=validated_context.sku,
        )

        result = await self.retry_invalid_generation(messages, validated_context)

        self._log_event(
            logging.INFO,
            "ai_recommendation_success",
            model=result.metadata.model,
            latency_ms=result.metadata.latency_ms,
            retry_count=result.metadata.retry_count,
            duration_ms=int((time.monotonic() - start_time) * 1000),
        )

        return AIModelResponse(
            recommendation=result.recommendation,
            metadata=result.metadata,
        )

    async def retry_invalid_generation(
        self,
        messages: Sequence[Mapping[str, str]],
        context: RecommendationContext,
    ) -> _GenerationResult:
        """Retry when the model response is invalid or transiently unavailable."""
        retry_limit = self._max_retries + 1
        last_error: Exception | None = None

        async for attempt in AsyncRetrying(
            retry=retry_if_exception(self._is_retryable_error),
            wait=wait_exponential_jitter(initial=0.5, max=4.0),
            stop=stop_after_attempt(retry_limit),
            before_sleep=lambda state: self._log_retry(state),
            reraise=True,
        ):
            with attempt:
                try:
                    response = await self._call_groq(messages)
                    parsed = self.parse_json_response(response)
                    recommendation = self.validate_ai_response(parsed, context)
                    response_size = len(json.dumps(parsed, ensure_ascii=False))
                    attempt_number = attempt.retry_state.attempt_number
                    metadata = self.build_generation_metadata(
                        response,
                        retry_count=attempt_number - 1,
                    )
                    self._log_event(
                        logging.INFO,
                        "ai_recommendation_response_parsed",
                        response_size=response_size,
                    )
                    return _GenerationResult(
                        recommendation=recommendation,
                        metadata=metadata,
                    )
                except Exception as exc:  # noqa: BLE001 - re-raised for retry control
                    last_error = exc
                    self._log_event(
                        logging.WARNING,
                        "ai_recommendation_attempt_failed",
                        error=exc.__class__.__name__,
                        attempt=attempt.retry_state.attempt_number,
                    )
                    raise

        # Should never reach here due to reraise=True, but keep fallback.
        raise RecommendationGenerationError(
            "Recommendation generation failed.", retryable=False
        ) from last_error

    async def _call_groq(
        self, messages: Sequence[Mapping[str, str]]
    ) -> Mapping[str, Any]:
        try:
            return await generate_json_completion(messages)
        except GroqTimeoutError as exc:
            raise RecommendationTimeoutError("Groq request timed out.", retryable=True) from exc
        except (GroqRateLimitError, GroqUnavailableError) as exc:
            raise RecommendationGenerationError(
                "Groq is temporarily unavailable.", retryable=True
            ) from exc
        except GroqInvalidResponseError as exc:
            raise InvalidAIResponseError("Groq returned invalid JSON.", retryable=True) from exc
        except GroqAPIError as exc:
            raise RecommendationGenerationError(
                "Groq API error occurred.", retryable=False
            ) from exc

    def parse_json_response(self, response: Mapping[str, Any]) -> Mapping[str, Any]:
        """Extract JSON payload from Groq response."""
        if not isinstance(response, Mapping):
            raise InvalidAIResponseError("Groq response must be a mapping.", retryable=True)

        content = response.get("content")
        if content is None:
            raise InvalidAIResponseError("Groq response content missing.", retryable=True)

        if isinstance(content, Mapping):
            return content
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as exc:
                raise InvalidAIResponseError("Groq returned invalid JSON.", retryable=True) from exc
            if not isinstance(parsed, Mapping):
                raise InvalidAIResponseError("Groq JSON must be an object.", retryable=True)
            return parsed

        raise InvalidAIResponseError("Groq response content invalid.", retryable=True)

    def validate_ai_response(
        self,
        payload: Mapping[str, Any],
        context: RecommendationContext,
    ) -> RecommendationResponse:
        """Validate AI response schema and enforce deterministic fields."""
        try:
            recommendation = RecommendationResponse.model_validate(payload)
        except ValidationError as exc:
            raise RecommendationValidationError(
                "AI response failed schema validation.", retryable=True
            ) from exc

        if recommendation.action != context.recommended_action:
            raise RecommendationValidationError(
                "AI response action does not match analytics action.", retryable=True
            )

        expected_confidence = _map_confidence_label(
            context.recommendation_confidence
        )
        if recommendation.confidence != expected_confidence:
            raise RecommendationValidationError(
                "AI response confidence label is inconsistent.", retryable=True
            )

        if recommendation.revenue_opportunity != 0:
            raise RecommendationValidationError(
                "AI response revenue_opportunity must be 0 when not provided.",
                retryable=True,
            )

        return recommendation

    def build_generation_metadata(
        self, response: Mapping[str, Any], *, retry_count: int
    ) -> RecommendationMetadata:
        """Build metadata for observability and audit logging."""
        model = str(response.get("model") or "unknown")
        latency_ms = int(response.get("latency_ms") or 0)
        return RecommendationMetadata(
            model=model,
            latency_ms=max(latency_ms, 0),
            retry_count=max(retry_count, 0),
            generated_at=datetime.now(tz=timezone.utc),
        )

    def _is_retryable_error(self, exc: BaseException) -> bool:
        if isinstance(exc, RecommendationTimeoutError):
            return True
        if isinstance(exc, (InvalidAIResponseError, RecommendationValidationError)):
            return True
        if isinstance(exc, RecommendationGenerationError):
            return getattr(exc, "retryable", False)
        return False

    def _log_retry(self, state: RetryCallState) -> None:
        exc = state.outcome.exception() if state.outcome else None
        self._log_event(
            logging.WARNING,
            "ai_recommendation_retry",
            attempt=state.attempt_number,
            error=exc.__class__.__name__ if exc else "unknown",
        )

    def _log_event(self, level: int, event: str, **fields: Any) -> None:
        safe_fields = {key: value for key, value in fields.items() if value is not None}
        payload = " ".join(f"{key}={value}" for key, value in safe_fields.items())
        self._logger.log(level, f"{event} {payload}".strip())


def _map_confidence_label(value: float) -> str:
    if value >= 0.75:
        return "HIGH"
    if value >= 0.5:
        return "MEDIUM"
    return "LOW"
