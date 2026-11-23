"""Keep tests independent of the developer's backend/.env and local Redis.

``Settings.load()`` reads backend/.env, so enabling a rollout flag locally would change
what every orchestrator test exercises. Pin those flags to their code defaults (off);
a test that needs one on sets it explicitly.
"""

import pytest

from app.core.config import settings
from app.services.copilot import rate_limiter

ROLLOUT_FLAGS_OFF = (
    "copilot_llm_router_enabled",
    "copilot_agent_loop_enabled",
    "copilot_always_retrieve_memory",
    "copilot_conversation_memory_enabled",
    "copilot_streaming_enabled",
    "rag_rrf_enabled",
)


@pytest.fixture(autouse=True)
def _rollout_flags_at_code_defaults(monkeypatch):
    for name in ROLLOUT_FLAGS_OFF:
        monkeypatch.setattr(settings, name, False)
    # A running local Redis would share Copilot rate-limit counts across test runs; count in memory instead.
    monkeypatch.setattr(rate_limiter, "redis", None)
    monkeypatch.setattr(rate_limiter.copilot_ask_rate_limiter, "_redis", None)
