from __future__ import annotations

import json
import time
from typing import Any, Callable

from app.ai.llm.base import JsonCompletionRequest, LLMProviderError, LLMResult

DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"
# Models that accept the server-side refusal fallback (`fallbacks: "default"`).
SERVER_FALLBACK_MODELS = frozenset({"claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"})
SERVER_FALLBACK_BETA = "server-side-fallback-2026-07-01"
VALID_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})

ClientFactory = Callable[..., Any]


def _default_client_factory(**kwargs: Any) -> Any:
    # Imported lazily so the dependency only matters when an Anthropic route is configured.
    from anthropic import AsyncAnthropic

    return AsyncAnthropic(**kwargs)


class AnthropicProvider:
    """Claude via the official SDK, returning schema-constrained JSON.

    A client is created per call and closed on the same event loop, matching the Groq
    client: Celery runs a fresh loop per task, so a process-wide client would leak
    connections across loops. Credentials come from the SDK's normal resolution
    (``ANTHROPIC_API_KEY`` and friends); nothing is read or logged here.

    Prompt caching is not enabled: the static system prompt is far below the minimum
    cacheable prefix, and the per-request evidence would only add cache-write cost.
    """

    name = "anthropic"

    def __init__(
        self,
        *,
        effort: str = "low",
        max_tokens: int = 16000,
        max_retries: int = 2,
        client_factory: ClientFactory | None = None,
    ) -> None:
        if effort not in VALID_EFFORTS:
            raise ValueError(f"Unsupported Anthropic effort level: {effort}")
        self._effort = effort
        # Thinking is always on for current Claude models and counts toward max_tokens,
        # so the Groq-sized budget (about 1000 tokens) would truncate answers.
        self._max_tokens = max_tokens
        self._max_retries = max_retries
        self._client_factory = client_factory or _default_client_factory

    async def complete_json(self, request: JsonCompletionRequest, *, model: str, timeout_s: float) -> LLMResult:
        import anthropic

        system = "\n\n".join(str(message["content"]) for message in request.messages if message.get("role") == "system")
        messages = [
            {"role": str(message["role"]), "content": str(message["content"])}
            for message in request.messages
            if message.get("role") in {"user", "assistant"}
        ]
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": max(request.max_tokens, self._max_tokens),
            "messages": messages,
            "output_config": {"effort": self._effort},
        }
        if request.json_schema:
            params["output_config"]["format"] = {"type": "json_schema", "schema": dict(request.json_schema)}
        if system:
            params["system"] = system

        started = time.monotonic()
        try:
            async with self._client_factory(timeout=timeout_s, max_retries=self._max_retries) as client:
                if model in SERVER_FALLBACK_MODELS:
                    response = await client.beta.messages.create(**params, betas=[SERVER_FALLBACK_BETA], fallbacks="default")
                else:
                    response = await client.messages.create(**params)
        except anthropic.APITimeoutError as exc:
            raise LLMProviderError("Anthropic request timed out.", code="TIMEOUT", provider=self.name) from exc
        except anthropic.RateLimitError as exc:
            raise LLMProviderError("Anthropic rate limit reached.", code="RATE_LIMITED", provider=self.name) from exc
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise LLMProviderError("Anthropic credentials were rejected.", code="AUTH_FAILED", provider=self.name, retryable=False) from exc
        except anthropic.BadRequestError as exc:
            raise LLMProviderError("Anthropic rejected the request.", code="BAD_REQUEST", provider=self.name, retryable=False) from exc
        except anthropic.APIStatusError as exc:
            raise LLMProviderError(f"Anthropic API error ({exc.status_code}).", code="API_ERROR", provider=self.name) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMProviderError("Anthropic is unreachable.", code="CONNECTION_ERROR", provider=self.name) from exc
        except anthropic.AnthropicError as exc:
            # Covers missing credentials and other client-side SDK errors.
            raise LLMProviderError("Anthropic client is not usable.", code="CLIENT_ERROR", provider=self.name, retryable=False) from exc

        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "refusal":
            raise LLMProviderError("Anthropic declined the request.", code="REFUSAL", provider=self.name, retryable=False)
        if stop_reason == "max_tokens":
            raise LLMProviderError("Anthropic answer hit max_tokens.", code="MAX_TOKENS", provider=self.name)
        text = next((block.text for block in response.content if getattr(block, "type", None) == "text"), None)
        if not text:
            raise LLMProviderError("Anthropic returned no text block.", code="EMPTY_RESPONSE", provider=self.name)
        try:
            content = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMProviderError("Anthropic returned invalid JSON.", code="INVALID_JSON", provider=self.name) from exc
        if not isinstance(content, dict):
            raise LLMProviderError("Anthropic JSON must be an object.", code="INVALID_JSON", provider=self.name)
        return LLMResult(
            content=content,
            provider=self.name,
            # A server-side fallback can serve the turn with another model; record the one that answered.
            model=str(getattr(response, "model", None) or model),
            usage=_usage(getattr(response, "usage", None)),
            latency_ms=int((time.monotonic() - started) * 1000),
        )


def _usage(usage: Any) -> dict[str, int]:
    if usage is None:
        return {}
    values = {
        "prompt_tokens": getattr(usage, "input_tokens", None),
        "completion_tokens": getattr(usage, "output_tokens", None),
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None),
    }
    result = {key: int(value) for key, value in values.items() if isinstance(value, int)}
    if "prompt_tokens" in result or "completion_tokens" in result:
        result["total_tokens"] = result.get("prompt_tokens", 0) + result.get("completion_tokens", 0)
    return result
