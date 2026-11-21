from __future__ import annotations

from typing import Any, Awaitable, Callable, Mapping

from app.ai.groq_client import GroqAPIError, GroqConfigurationError, generate_json_completion
from app.ai.llm.base import JsonCompletionRequest, LLMProviderError, LLMResult

GroqJsonCallable = Callable[..., Awaitable[Mapping[str, Any]]]


class GroqProvider:
    """Adapter over the existing Groq JSON client, which keeps its own tenacity retries."""

    name = "groq"

    def __init__(self, *, groq_json: GroqJsonCallable | None = None) -> None:
        self._groq_json = groq_json or generate_json_completion

    async def complete_json(self, request: JsonCompletionRequest, *, model: str, timeout_s: float) -> LLMResult:
        del timeout_s  # The router bounds the call; the Groq client applies its own per-attempt timeout.
        try:
            response = await self._groq_json(
                list(request.messages),
                model=model,
                temperature=0.1 if request.temperature is None else request.temperature,
                max_tokens=request.max_tokens,
                schema_hint=request.schema_hint,
                request_id=request.request_id,
            )
        except GroqAPIError as exc:
            raise LLMProviderError(
                str(exc),
                code=exc.__class__.__name__,
                provider=self.name,
                retryable=not isinstance(exc, GroqConfigurationError),
            ) from exc
        content = response.get("content")
        if not isinstance(content, dict):
            raise LLMProviderError("Groq returned a non-object JSON payload.", code="INVALID_JSON", provider=self.name)
        usage = response.get("usage")
        if not isinstance(usage, Mapping):
            usage = {}
        return LLMResult(
            content=content,
            provider=self.name,
            model=str(response.get("model") or model),
            usage={key: int(value) for key, value in usage.items() if isinstance(value, int)},
            latency_ms=int(response.get("latency_ms") or 0),
        )
