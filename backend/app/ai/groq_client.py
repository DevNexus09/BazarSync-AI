"""Groq client integration.

This module provides a safe, reusable Groq client for FastAPI/Celery usage.
It enforces deterministic analytics ownership by ensuring the LLM only explains
precomputed metrics. The LLM never calculates business logic in this layer.

Example usage:
    from app.ai.groq_client import generate_completion, generate_json_completion

    async def get_bn_reasoning(context: dict[str, object]) -> dict[str, object]:
        messages = [
            {"role": "system", "content": "Explain the analytics in Bangla."},
            {"role": "user", "content": f"Context: {context}"},
        ]
        return await generate_json_completion(
            messages,
            schema_hint={"action": "LOWER", "reasoning_bn": "..."},
        )

FastAPI integration example:
    from fastapi import Depends
    from app.ai.groq_client import get_groq_client, generate_json_completion

    @router.post("/recommendations")
    async def explain_recommendation(payload: dict, _=Depends(get_groq_client)):
        return await generate_json_completion(payload["messages"])

Celery compatibility notes:
    - Celery tasks can call `run_async(generate_completion(...))`
      or use `generate_completion_sync` helper if you prefer sync tasks.
    - The Groq client is a singleton and safe for concurrent usage.
"""

from __future__ import annotations

from dataclasses import dataclass
import asyncio
import json
import logging
import os
import threading
import time
from typing import Any, Mapping, Sequence

from dotenv import load_dotenv
from groq import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncGroq,
    AuthenticationError,
    BadRequestError,
    GroqError,
    InternalServerError,
    RateLimitError,
    UnprocessableEntityError,
)
from tenacity import AsyncRetrying, RetryCallState, retry_if_exception, stop_after_attempt
from tenacity import wait_exponential_jitter

from app.core.async_runner import run_async

DEFAULT_MODEL = "llama-3.3-70b-versatile"


class GroqAPIError(Exception):
    """Base class for Groq API integration errors."""


class GroqTimeoutError(GroqAPIError):
    """Raised when Groq requests timeout."""


class GroqRateLimitError(GroqAPIError):
    """Raised when Groq rate limits requests."""


class GroqInvalidResponseError(GroqAPIError):
    """Raised when Groq responses are empty or malformed."""


class GroqConfigurationError(GroqAPIError):
    """Raised when Groq settings are missing or invalid."""


@dataclass(frozen=True)
class GroqSettings:
    api_key: str
    model: str
    timeout_seconds: float
    max_retries: int

    @classmethod
    def from_env(cls) -> "GroqSettings":
        load_dotenv()

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise GroqConfigurationError("GROQ_API_KEY is missing.")

        model = os.getenv("GROQ_MODEL", DEFAULT_MODEL)
        timeout_seconds = _get_float_env("GROQ_TIMEOUT_SECONDS", 30.0, min_value=1.0)
        max_retries = _get_int_env("GROQ_MAX_RETRIES", 3, min_value=0)

        return cls(
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )


class GroqClientManager:
    """Singleton manager for Groq client and settings."""

    _client: AsyncGroq | None = None
    _settings: GroqSettings | None = None
    _lock = threading.Lock()

    @classmethod
    def get_settings(cls) -> GroqSettings:
        if cls._settings is None:
            with cls._lock:
                if cls._settings is None:
                    cls._settings = GroqSettings.from_env()
        return cls._settings

    @classmethod
    def get_client(cls) -> AsyncGroq:
        if cls._client is None:
            with cls._lock:
                if cls._client is None:
                    settings = cls.get_settings()
                    cls._client = AsyncGroq(
                        api_key=settings.api_key,
                        timeout=settings.timeout_seconds,
                        max_retries=0,
                    )
        return cls._client


def get_groq_client() -> AsyncGroq:
    """FastAPI dependency hook to initialize the Groq client once."""
    return GroqClientManager.get_client()


async def generate_completion(
    messages: Sequence[Mapping[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    response_format: Mapping[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Generate a plain-text completion from Groq."""
    if not messages:
        raise GroqInvalidResponseError("messages cannot be empty.")

    settings = GroqClientManager.get_settings()
    selected_model = model or settings.model
    client = GroqClientManager.get_client()
    logger = logging.getLogger(__name__)

    start_time = time.monotonic()
    _log_event(
        logger,
        logging.INFO,
        "groq_request_start",
        model=selected_model,
        request_id=request_id,
    )

    try:
        response = await _execute_with_retry(
            client,
            settings,
            messages,
            selected_model,
            temperature,
            max_tokens,
            response_format=response_format,
            request_id=request_id,
        )
    except APITimeoutError as exc:
        _log_event(
            logger,
            logging.ERROR,
            "groq_request_timeout",
            model=selected_model,
            request_id=request_id,
            error=exc.__class__.__name__,
        )
        raise GroqTimeoutError("Groq request timed out.") from exc
    except RateLimitError as exc:
        _log_event(
            logger,
            logging.ERROR,
            "groq_rate_limit",
            model=selected_model,
            request_id=request_id,
            error=exc.__class__.__name__,
        )
        raise GroqRateLimitError("Groq rate limit reached.") from exc
    except (BadRequestError, AuthenticationError, UnprocessableEntityError) as exc:
        _log_event(
            logger,
            logging.ERROR,
            "groq_request_invalid",
            model=selected_model,
            request_id=request_id,
            error=exc.__class__.__name__,
        )
        raise GroqAPIError("Groq request is invalid.") from exc
    except GroqError as exc:
        _log_event(
            logger,
            logging.ERROR,
            "groq_request_failed",
            model=selected_model,
            request_id=request_id,
            error=exc.__class__.__name__,
        )
        raise GroqAPIError("Groq API error occurred.") from exc

    latency_ms = int((time.monotonic() - start_time) * 1000)
    content = _extract_content(response)
    usage = _extract_usage(response)

    _log_event(
        logger,
        logging.INFO,
        "groq_request_success",
        model=selected_model,
        request_id=request_id,
        latency_ms=latency_ms,
        **usage,
    )

    return {
        "success": True,
        "model": selected_model,
        "content": content,
        "latency_ms": latency_ms,
    }


async def generate_json_completion(
    messages: Sequence[Mapping[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    schema_hint: Mapping[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Generate and parse a JSON-only completion from Groq."""
    json_guard = _build_json_guard(schema_hint)
    guarded_messages = [{"role": "system", "content": json_guard}, *messages]

    response = await generate_completion(
        guarded_messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        request_id=request_id,
    )

    content = response["content"]
    parsed = _parse_json_content(content)
    response["content"] = parsed
    return response


def generate_completion_sync(
    messages: Sequence[Mapping[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Synchronous wrapper for Celery or CLI usage."""
    return run_async(
        generate_completion(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            request_id=request_id,
        )
    )


def generate_json_completion_sync(
    messages: Sequence[Mapping[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    schema_hint: Mapping[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Synchronous wrapper for JSON completions."""
    return run_async(
        generate_json_completion(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            schema_hint=schema_hint,
            request_id=request_id,
        )
    )


async def _execute_with_retry(
    client: AsyncGroq,
    settings: GroqSettings,
    messages: Sequence[Mapping[str, str]],
    model: str,
    temperature: float,
    max_tokens: int | None,
    response_format: Mapping[str, Any] | None,
    *,
    request_id: str | None = None,
):
    logger = logging.getLogger(__name__)
    retry_limit = settings.max_retries + 1

    async for attempt in AsyncRetrying(
        retry=retry_if_exception(_is_transient_error),
        wait=wait_exponential_jitter(initial=0.5, max=4.0),
        stop=stop_after_attempt(retry_limit),
        before_sleep=lambda state: _log_retry(logger, state, model, request_id),
        reraise=True,
    ):
        with attempt:
            request_payload: dict[str, Any] = {
                "model": model,
                "messages": list(messages),
                "temperature": temperature,
            }
            if max_tokens is not None:
                request_payload["max_tokens"] = max_tokens
            if response_format is not None:
                request_payload["response_format"] = response_format
            return await client.chat.completions.create(**request_payload)


def _is_transient_error(exc: BaseException) -> bool:
    if isinstance(exc, (APITimeoutError, RateLimitError, APIConnectionError, InternalServerError)):
        return True
    if isinstance(exc, APIStatusError) and exc.status_code in {500, 502, 503, 504}:
        return True
    return False


def _log_retry(
    logger: logging.Logger,
    state: RetryCallState,
    model: str,
    request_id: str | None,
) -> None:
    exc = state.outcome.exception() if state.outcome else None
    _log_event(
        logger,
        logging.WARNING,
        "groq_request_retry",
        model=model,
        request_id=request_id,
        attempt=state.attempt_number,
        error=exc.__class__.__name__ if exc else "unknown",
    )


def _extract_content(response: Any) -> str:
    if response is None or not getattr(response, "choices", None):
        raise GroqInvalidResponseError("Groq returned an empty response.")
    message = response.choices[0].message
    content = getattr(message, "content", None)
    if not content:
        raise GroqInvalidResponseError("Groq returned no message content.")
    return content


def _extract_usage(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if not usage:
        return {}
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
        "total_tokens": getattr(usage, "total_tokens", 0) or 0,
    }


def _parse_json_content(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise GroqInvalidResponseError("Groq returned invalid JSON.") from exc
    if not isinstance(parsed, dict):
        raise GroqInvalidResponseError("Groq JSON response must be an object.")
    return parsed


def _build_json_guard(schema_hint: Mapping[str, Any] | None) -> str:
    schema_snippet = ""
    if schema_hint:
        schema_snippet = f"\nExpected JSON shape: {json.dumps(schema_hint, ensure_ascii=False)}"
    return (
        "Return ONLY a valid JSON object with no extra text, no markdown, and no code fences."
        " Do not invent numbers or business logic. Use the provided analytics context as-is."
        f"{schema_snippet}"
    )


def _get_int_env(key: str, default: int, *, min_value: int | None = None) -> int:
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise GroqConfigurationError(f"{key} must be an integer.") from exc
    if min_value is not None and value < min_value:
        raise GroqConfigurationError(f"{key} must be >= {min_value}.")
    return value


def _get_float_env(
    key: str, default: float, *, min_value: float | None = None
) -> float:
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise GroqConfigurationError(f"{key} must be a number.") from exc
    if min_value is not None and value < min_value:
        raise GroqConfigurationError(f"{key} must be >= {min_value}.")
    return value


def _log_event(
    logger: logging.Logger, level: int, event: str, **fields: Any
) -> None:
    safe_fields = {key: value for key, value in fields.items() if value is not None}
    payload = " ".join(f"{key}={value}" for key, value in safe_fields.items())
    logger.log(level, f"{event} {payload}".strip())
