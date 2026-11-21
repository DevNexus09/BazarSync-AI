from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True, slots=True)
class JsonCompletionRequest:
    """One JSON-only completion. Providers use whichever schema form they support."""

    messages: Sequence[Mapping[str, str]]
    max_tokens: int
    # Loose shape hint (Groq JSON mode adds it to the prompt).
    schema_hint: Mapping[str, Any] | None = None
    # Strict JSON Schema (Anthropic structured outputs). Falls back to the hint when absent.
    json_schema: Mapping[str, Any] | None = None
    # Only providers that still accept sampling parameters use it.
    temperature: float | None = None
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class LLMResult:
    content: dict[str, Any]
    provider: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: int = 0


class LLMProviderError(RuntimeError):
    """A provider call that produced no usable JSON. ``code`` is stable for telemetry."""

    def __init__(self, message: str, *, code: str, provider: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.provider = provider
        self.retryable = retryable


class LLMProvider(Protocol):
    name: str

    async def complete_json(self, request: JsonCompletionRequest, *, model: str, timeout_s: float) -> LLMResult: ...
