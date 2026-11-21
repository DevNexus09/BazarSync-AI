from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import os
import time
from typing import Any, Mapping, Sequence

from app.ai.llm.anthropic_provider import DEFAULT_ANTHROPIC_MODEL
from app.ai.llm.base import JsonCompletionRequest, LLMProvider, LLMProviderError, LLMResult

logger = logging.getLogger(__name__)

# OpenAI-compatible providers: route name -> (API key env var, settings attribute for the base URL).
OPENAI_COMPAT_PROVIDERS = {
    "openai": ("OPENAI_API_KEY", "openai_base_url"),
    "gemini": ("GEMINI_API_KEY", "gemini_base_url"),
}

# Below this, a fallback attempt cannot finish inside the deadline.
MIN_ATTEMPT_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class LLMRoute:
    provider: str
    model: str

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"


@dataclass(frozen=True, slots=True)
class LLMAttempt:
    route: str
    status: str
    code: str | None = None
    latency_ms: int = 0


class LLMRouterError(RuntimeError):
    def __init__(self, message: str, *, attempts: Sequence[LLMAttempt]) -> None:
        super().__init__(message)
        self.attempts = list(attempts)


@dataclass(slots=True)
class CopilotLLMRouter:
    """Pick provider and model per reply language, then fall back in order.

    One overall deadline bounds the whole chain: each attempt gets only the time left,
    so retries inside a provider and the fallback chain cannot stack timeouts.
    """

    providers: Mapping[str, LLMProvider]
    default_routes: Sequence[LLMRoute]
    language_routes: Mapping[str, Sequence[LLMRoute]] = field(default_factory=dict)
    timeout_seconds: float = 20.0

    def routes_for(self, reply_language: str | None) -> list[LLMRoute]:
        primary = list(self.language_routes.get(reply_language or "", ()) or ())
        chain = primary + [route for route in self.default_routes if route not in primary]
        return [route for route in chain if route.provider in self.providers]

    async def complete_json(
        self,
        request: JsonCompletionRequest,
        *,
        reply_language: str | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[LLMResult, list[LLMAttempt]]:
        """``timeout_seconds`` narrows the budget (for example a repair call); it never extends it."""
        budget = self.timeout_seconds if timeout_seconds is None else min(timeout_seconds, self.timeout_seconds)
        deadline = time.monotonic() + budget
        attempts: list[LLMAttempt] = []
        for route in self.routes_for(reply_language):
            remaining = deadline - time.monotonic()
            # The first route always gets the whole budget; only a fallback needs a useful slice of what is left.
            if attempts and remaining < MIN_ATTEMPT_SECONDS:
                attempts.append(LLMAttempt(route=route.label, status="SKIPPED", code="DEADLINE"))
                break
            started = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    self.providers[route.provider].complete_json(request, model=route.model, timeout_s=remaining),
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                attempts.append(LLMAttempt(route=route.label, status="FAILED", code="DEADLINE", latency_ms=_elapsed_ms(started)))
            except LLMProviderError as exc:
                attempts.append(LLMAttempt(route=route.label, status="FAILED", code=exc.code, latency_ms=_elapsed_ms(started)))
            except Exception as exc:  # noqa: BLE001 - an unexpected provider bug must not skip the remaining routes
                logger.exception("copilot_llm_provider_crashed route=%s", route.label)
                attempts.append(LLMAttempt(route=route.label, status="FAILED", code=exc.__class__.__name__, latency_ms=_elapsed_ms(started)))
            else:
                attempts.append(LLMAttempt(route=route.label, status="SUCCEEDED", latency_ms=_elapsed_ms(started)))
                return result, attempts
        raise LLMRouterError("No LLM route produced an answer.", attempts=attempts)


def parse_route(value: str, *, default_groq_model: str | None) -> LLMRoute | None:
    """Parse ``provider:model`` (or a bare provider name) into a route."""
    text = (value or "").strip()
    if not text:
        return None
    provider, _, model = text.partition(":")
    provider = provider.strip().lower()
    model = model.strip()
    if provider == "anthropic":
        return LLMRoute("anthropic", model or DEFAULT_ANTHROPIC_MODEL)
    if provider == "groq":
        resolved = model or default_groq_model
        return LLMRoute("groq", resolved) if resolved else None
    if provider in OPENAI_COMPAT_PROVIDERS:
        # Free-tier model ids change often, so these routes must name their model.
        return LLMRoute(provider, model) if model else None
    raise ValueError(f"Unknown Copilot LLM provider in route {value!r}; expected one of anthropic, gemini, groq, openai.")


def parse_routes(value: str, *, default_groq_model: str | None) -> list[LLMRoute]:
    routes = [parse_route(part, default_groq_model=default_groq_model) for part in (value or "").split(",")]
    return [route for route in routes if route is not None]


def build_router_from_settings(
    settings: Any,
    *,
    timeout_seconds: float,
    groq_provider: LLMProvider | None = None,
    default_groq_model: str | None = None,
) -> CopilotLLMRouter:
    """Build the answer router. Raises ``ValueError`` for an unknown provider in a route."""
    from app.ai.llm.anthropic_provider import AnthropicProvider
    from app.ai.llm.groq_provider import GroqProvider
    from app.ai.llm.openai_compat_provider import OpenAICompatProvider

    groq_model = default_groq_model or settings.copilot_groq_model
    default_routes = parse_routes(settings.copilot_llm_answer_routes, default_groq_model=groq_model) or parse_routes(
        "groq", default_groq_model=groq_model
    )
    language_routes = {
        language: parse_routes(value, default_groq_model=groq_model)
        for language, value in (
            ("en", settings.copilot_llm_answer_routes_en),
            ("bn", settings.copilot_llm_answer_routes_bn),
            ("banglish", settings.copilot_llm_answer_routes_banglish),
        )
        if value
    }
    all_providers = {route.provider for route in default_routes} | {
        route.provider for routes in language_routes.values() for route in routes
    }
    providers: dict[str, LLMProvider] = {}
    if "groq" in all_providers:
        providers["groq"] = groq_provider or GroqProvider()
    if "anthropic" in all_providers:
        providers["anthropic"] = AnthropicProvider(
            effort=settings.copilot_anthropic_effort,
            max_tokens=settings.copilot_anthropic_max_tokens,
        )
    for name, (key_env, base_url_attr) in OPENAI_COMPAT_PROVIDERS.items():
        api_key = os.getenv(key_env, "").strip()
        # A route whose provider has no key is skipped by routes_for(), so the chain moves on.
        if name in all_providers and api_key:
            providers[name] = OpenAICompatProvider(name=name, base_url=getattr(settings, base_url_attr), api_key=api_key)
    return CopilotLLMRouter(
        providers=providers,
        default_routes=default_routes,
        language_routes=language_routes,
        timeout_seconds=timeout_seconds,
    )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
