from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.ai.groq_client import _build_json_guard
from app.ai.llm.base import JsonCompletionRequest, LLMProviderError, LLMResult


class OpenAICompatProvider:
    """JSON-mode chat completions on any OpenAI-compatible endpoint (OpenAI, GitHub Models, Gemini).

    No retries here: the router owns fallback and the overall deadline. The API key is only
    sent as a header and never appears in errors or logs.
    """

    def __init__(self, *, name: str, base_url: str, api_key: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not api_key:
            raise ValueError(f"{name} provider needs an API key.")
        self.name = name
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._transport = transport

    async def complete_json(self, request: JsonCompletionRequest, *, model: str, timeout_s: float) -> LLMResult:
        # JSON mode requires the word "JSON" in the prompt; the guard also carries the expected shape.
        messages = [{"role": "system", "content": _build_json_guard(request.schema_hint)}, *(dict(message) for message in request.messages)]
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": 0.1 if request.temperature is None else request.temperature,
            # Strict schema when the caller has one (answers need every field); plain JSON mode otherwise.
            "response_format": (
                {"type": "json_schema", "json_schema": {"name": "copilot_response", "schema": dict(request.json_schema), "strict": True}}
                if request.json_schema
                else {"type": "json_object"}
            ),
        }
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout_s, transport=self._transport) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=body,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
        except httpx.TimeoutException as exc:
            raise LLMProviderError(f"{self.name} request timed out.", code="TIMEOUT", provider=self.name) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"{self.name} is unreachable.", code="CONNECTION_ERROR", provider=self.name) from exc

        status = response.status_code
        if status == 429:
            raise LLMProviderError(f"{self.name} rate limit or quota reached.", code="RATE_LIMITED", provider=self.name)
        if status in (401, 403):
            raise LLMProviderError(f"{self.name} credentials were rejected.", code="AUTH", provider=self.name, retryable=False)
        if status >= 400:
            raise LLMProviderError(f"{self.name} API error ({status}).", code=f"HTTP_{status}", provider=self.name, retryable=status >= 500)

        try:
            payload = response.json()
            text = payload["choices"][0]["message"]["content"]
            content = json.loads(text)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError(f"{self.name} returned invalid JSON.", code="INVALID_JSON", provider=self.name) from exc
        if not isinstance(content, dict):
            raise LLMProviderError(f"{self.name} JSON must be an object.", code="INVALID_JSON", provider=self.name)
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        return LLMResult(
            content=content,
            provider=self.name,
            model=str(payload.get("model") or model),
            usage={key: value for key, value in usage.items() if isinstance(value, int)},
            latency_ms=int((time.monotonic() - started) * 1000),
        )
