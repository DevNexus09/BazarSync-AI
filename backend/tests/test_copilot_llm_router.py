from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import anthropic
import httpx2

from app.ai.groq_client import GroqConfigurationError, GroqTimeoutError
from app.ai.llm import (
    CopilotLLMRouter,
    JsonCompletionRequest,
    LLMProviderError,
    LLMResult,
    LLMRoute,
    LLMRouterError,
    build_router_from_settings,
    parse_routes,
)
from app.ai.llm import router as router_module
from app.ai.llm.anthropic_provider import AnthropicProvider
from app.ai.llm.groq_provider import GroqProvider
from app.services.copilot.hybrid_answer_engine import CopilotHybridAnswerEngine, answer_json_schema
from app.services.copilot.intent_classifier import CopilotIntentClassifier
from app.services.copilot.orchestrator import CopilotOrchestrator
from app.services.copilot.question_planner import CopilotQuestionPlanner

from tests.test_copilot_hybrid_answer_engine import _Registry, _tool
from tests.test_copilot_orchestrator import FIXED_NOW, SELLER_ID, _FakeRegistry, _FakeRepository

REQUEST = JsonCompletionRequest(
    messages=[{"role": "system", "content": "System rules."}, {"role": "user", "content": "Facts."}],
    max_tokens=1000,
    schema_hint={"answer": "string"},
    json_schema={"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"], "additionalProperties": False},
    temperature=0.1,
    request_id="req-1",
)


class GroqProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_maps_response_and_keeps_legacy_call_shape(self):
        calls = []

        async def groq(messages, **kwargs):
            calls.append((messages, kwargs))
            return {"model": "llama-test", "content": {"answer": "ok"}, "usage": {"total_tokens": 7}, "latency_ms": 12}

        result = await GroqProvider(groq_json=groq).complete_json(REQUEST, model="llama-test", timeout_s=5)

        self.assertEqual(LLMResult(content={"answer": "ok"}, provider="groq", model="llama-test", usage={"total_tokens": 7}, latency_ms=12), result)
        self.assertEqual({"model": "llama-test", "temperature": 0.1, "max_tokens": 1000, "schema_hint": {"answer": "string"}, "request_id": "req-1"}, calls[0][1])

    async def test_groq_errors_become_provider_errors(self):
        async def timeout(messages, **kwargs):
            raise GroqTimeoutError("slow")

        async def misconfigured(messages, **kwargs):
            raise GroqConfigurationError("no key")

        with self.assertRaises(LLMProviderError) as raised:
            await GroqProvider(groq_json=timeout).complete_json(REQUEST, model="m", timeout_s=5)
        self.assertEqual("GroqTimeoutError", raised.exception.code)
        self.assertTrue(raised.exception.retryable)

        with self.assertRaises(LLMProviderError) as raised:
            await GroqProvider(groq_json=misconfigured).complete_json(REQUEST, model="m", timeout_s=5)
        self.assertFalse(raised.exception.retryable)

    async def test_non_object_content_is_rejected(self):
        async def groq(messages, **kwargs):
            return {"model": "m", "content": "not-json"}

        with self.assertRaises(LLMProviderError) as raised:
            await GroqProvider(groq_json=groq).complete_json(REQUEST, model="m", timeout_s=5)
        self.assertEqual("INVALID_JSON", raised.exception.code)


class _FakeAnthropicClient:
    def __init__(self, *, response=None, error=None) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[str, dict]] = []
        self.closed = False
        self.messages = SimpleNamespace(create=self._create("messages"))
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create("beta")))

    def _create(self, endpoint):
        async def create(**kwargs):
            self.calls.append((endpoint, kwargs))
            if self.error is not None:
                raise self.error
            return self.response

        return create

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.closed = True


def _response(text: str, *, stop_reason: str = "end_turn", model: str = "claude-opus-5-5"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        model=model,
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=400, output_tokens=120, cache_read_input_tokens=0, cache_creation_input_tokens=None),
    )


def _provider(client: _FakeAnthropicClient, **kwargs) -> tuple[AnthropicProvider, list[dict]]:
    factory_calls: list[dict] = []

    def factory(**options):
        factory_calls.append(options)
        return client

    return AnthropicProvider(client_factory=factory, **kwargs), factory_calls


class AnthropicProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_opus_request_uses_structured_output_effort_and_server_fallbacks(self):
        client = _FakeAnthropicClient(response=_response(json.dumps({"answer": "ok"})))
        provider, factory_calls = _provider(client)

        result = await provider.complete_json(REQUEST, model="claude-opus-5-5", timeout_s=7.5)

        endpoint, params = client.calls[0]
        self.assertEqual("beta", endpoint)
        self.assertEqual(["server-side-fallback-2026-07-01"], params["betas"])
        self.assertEqual("default", params["fallbacks"])
        self.assertEqual("System rules.", params["system"])
        self.assertEqual([{"role": "user", "content": "Facts."}], params["messages"])
        self.assertEqual({"effort": "low", "format": {"type": "json_schema", "schema": dict(REQUEST.json_schema)}}, params["output_config"])
        self.assertNotIn("temperature", params)
        self.assertGreaterEqual(params["max_tokens"], 16000)
        self.assertEqual({"timeout": 7.5, "max_retries": 2}, factory_calls[0])
        self.assertTrue(client.closed)
        self.assertEqual({"answer": "ok"}, result.content)
        self.assertEqual({"prompt_tokens": 400, "completion_tokens": 120, "cache_read_input_tokens": 0, "total_tokens": 520}, result.usage)

    async def test_model_without_server_fallback_uses_plain_endpoint(self):
        client = _FakeAnthropicClient(response=_response(json.dumps({"answer": "ok"}), model="claude-haiku-5-5"))
        provider, _ = _provider(client)

        result = await provider.complete_json(REQUEST, model="claude-haiku-5-5", timeout_s=5)

        endpoint, params = client.calls[0]
        self.assertEqual("messages", endpoint)
        self.assertNotIn("fallbacks", params)
        self.assertEqual("claude-haiku-5-5", result.model)

    async def test_served_model_is_recorded_when_fallback_answers(self):
        client = _FakeAnthropicClient(response=_response(json.dumps({"answer": "ok"}), model="claude-opus-5"))
        provider, _ = _provider(client)

        result = await provider.complete_json(REQUEST, model="claude-opus-5-5", timeout_s=5)

        self.assertEqual("claude-opus-5", result.model)

    async def test_stop_reasons_and_bad_json_raise_provider_errors(self):
        cases = [
            (_response("{}", stop_reason="refusal"), "REFUSAL", False),
            (_response('{"answer": "cut', stop_reason="max_tokens"), "MAX_TOKENS", True),
            (_response("not json"), "INVALID_JSON", True),
            (_response("[1, 2]"), "INVALID_JSON", True),
        ]
        for response, code, retryable in cases:
            with self.subTest(code=code):
                provider, _ = _provider(_FakeAnthropicClient(response=response))
                with self.assertRaises(LLMProviderError) as raised:
                    await provider.complete_json(REQUEST, model="claude-opus-5-5", timeout_s=5)
                self.assertEqual(code, raised.exception.code)
                self.assertEqual(retryable, raised.exception.retryable)

    async def test_sdk_errors_are_mapped_without_leaking_details(self):
        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        cases = [
            (anthropic.APITimeoutError(request=request), "TIMEOUT"),
            (anthropic.RateLimitError("rate", response=httpx2.Response(429, request=request), body=None), "RATE_LIMITED"),
            (anthropic.AuthenticationError("bad key", response=httpx2.Response(401, request=request), body=None), "AUTH_FAILED"),
            (anthropic.BadRequestError("bad", response=httpx2.Response(400, request=request), body=None), "BAD_REQUEST"),
            (anthropic.InternalServerError("boom", response=httpx2.Response(500, request=request), body=None), "API_ERROR"),
            (anthropic.APIConnectionError(request=request), "CONNECTION_ERROR"),
        ]
        for error, code in cases:
            with self.subTest(code=code):
                provider, _ = _provider(_FakeAnthropicClient(error=error))
                with self.assertRaises(LLMProviderError) as raised:
                    await provider.complete_json(REQUEST, model="claude-opus-5-5", timeout_s=5)
                self.assertEqual(code, raised.exception.code)
                self.assertNotIn("bad key", str(raised.exception))

    def test_invalid_effort_is_rejected(self):
        with self.assertRaises(ValueError):
            AnthropicProvider(effort="extreme")


class _ScriptedProvider:
    def __init__(self, name: str, outcomes: dict[str, object], *, delay: float = 0.0) -> None:
        self.name = name
        self.outcomes = outcomes
        self.delay = delay
        self.calls: list[tuple[str, float]] = []

    async def complete_json(self, request, *, model, timeout_s):
        self.calls.append((model, timeout_s))
        if self.delay:
            await asyncio.sleep(self.delay)
        outcome = self.outcomes[model]
        if isinstance(outcome, BaseException):
            raise outcome
        return LLMResult(content={"answer": outcome}, provider=self.name, model=model)


class RouterTests(unittest.IsolatedAsyncioTestCase):
    def test_language_routes_come_first_and_unknown_providers_are_dropped(self):
        router = CopilotLLMRouter(
            providers={"groq": _ScriptedProvider("groq", {}), "anthropic": _ScriptedProvider("anthropic", {})},
            default_routes=[LLMRoute("groq", "llama"), LLMRoute("anthropic", "claude-opus-5-5")],
            language_routes={"banglish": [LLMRoute("anthropic", "claude-opus-5-5"), LLMRoute("openai", "gpt")]},
        )

        self.assertEqual(["anthropic:claude-opus-5-5", "groq:llama"], [route.label for route in router.routes_for("banglish")])
        self.assertEqual(["groq:llama", "anthropic:claude-opus-5-5"], [route.label for route in router.routes_for("en")])

    async def test_falls_back_in_order_and_records_attempts(self):
        anthropic_provider = _ScriptedProvider("anthropic", {"claude-opus-5-5": LLMProviderError("no", code="RATE_LIMITED", provider="anthropic")})
        groq_provider = _ScriptedProvider("groq", {"llama": "from groq"})
        router = CopilotLLMRouter(
            providers={"anthropic": anthropic_provider, "groq": groq_provider},
            default_routes=[LLMRoute("anthropic", "claude-opus-5-5"), LLMRoute("groq", "llama")],
        )

        result, attempts = await router.complete_json(REQUEST)

        self.assertEqual({"answer": "from groq"}, result.content)
        self.assertEqual([("anthropic:claude-opus-5-5", "FAILED", "RATE_LIMITED"), ("groq:llama", "SUCCEEDED", None)], [(a.route, a.status, a.code) for a in attempts])

    async def test_unexpected_provider_crash_still_tries_next_route(self):
        router = CopilotLLMRouter(
            providers={"anthropic": _ScriptedProvider("anthropic", {"x": RuntimeError("bug")}), "groq": _ScriptedProvider("groq", {"llama": "ok"})},
            default_routes=[LLMRoute("anthropic", "x"), LLMRoute("groq", "llama")],
        )

        with self.assertLogs("app.ai.llm.router", level="ERROR"):
            result, attempts = await router.complete_json(REQUEST)

        self.assertEqual("ok", result.content["answer"])
        self.assertEqual("RuntimeError", attempts[0].code)

    async def test_one_deadline_bounds_the_whole_chain(self):
        slow = _ScriptedProvider("anthropic", {"slow": "late"}, delay=5)
        backup = _ScriptedProvider("groq", {"llama": "ok"})
        router = CopilotLLMRouter(
            providers={"anthropic": slow, "groq": backup},
            default_routes=[LLMRoute("anthropic", "slow"), LLMRoute("groq", "llama")],
            timeout_seconds=0.3,
        )

        with patch.object(router_module, "MIN_ATTEMPT_SECONDS", 0.05):
            with self.assertRaises(LLMRouterError) as raised:
                await router.complete_json(REQUEST)

        self.assertEqual([("FAILED", "DEADLINE"), ("SKIPPED", "DEADLINE")], [(a.status, a.code) for a in raised.exception.attempts])
        self.assertEqual([], backup.calls)
        self.assertLessEqual(slow.calls[0][1], 0.3)

    async def test_first_route_runs_even_with_a_short_overall_timeout(self):
        provider = _ScriptedProvider("groq", {"llama": "ok"})
        router = CopilotLLMRouter(providers={"groq": provider}, default_routes=[LLMRoute("groq", "llama")], timeout_seconds=0.5)

        result, attempts = await router.complete_json(REQUEST)

        self.assertEqual("ok", result.content["answer"])
        self.assertEqual(["SUCCEEDED"], [attempt.status for attempt in attempts])

    def test_parse_routes(self):
        self.assertEqual([LLMRoute("anthropic", "claude-opus-5-5")], parse_routes("anthropic", default_groq_model=None))
        self.assertEqual(
            [LLMRoute("anthropic", "claude-sonnet-5-5"), LLMRoute("groq", "llama-default")],
            parse_routes(" anthropic:claude-sonnet-5-5 , groq ", default_groq_model="llama-default"),
        )
        self.assertEqual([], parse_routes("groq", default_groq_model=None))
        with self.assertRaises(ValueError):
            parse_routes("openai:gpt-5", default_groq_model=None)

    def test_build_router_from_settings_only_creates_configured_providers(self):
        settings = SimpleNamespace(
            copilot_groq_model="llama-default",
            copilot_llm_answer_routes="groq",
            copilot_llm_answer_routes_en="",
            copilot_llm_answer_routes_bn="anthropic",
            copilot_llm_answer_routes_banglish="anthropic:claude-opus-5-5",
            copilot_anthropic_effort="medium",
            copilot_anthropic_max_tokens=12000,
        )

        router = build_router_from_settings(settings, timeout_seconds=15)

        self.assertEqual({"groq", "anthropic"}, set(router.providers))
        self.assertEqual(15, router.timeout_seconds)
        self.assertEqual(["anthropic:claude-opus-5-5", "groq:llama-default"], [route.label for route in router.routes_for("bn")])
        self.assertEqual(["groq:llama-default"], [route.label for route in router.routes_for("en")])

        groq_only = build_router_from_settings(SimpleNamespace(**{**vars(settings), "copilot_llm_answer_routes_bn": "", "copilot_llm_answer_routes_banglish": ""}), timeout_seconds=15)
        self.assertEqual({"groq"}, set(groq_only.providers))


class _RecordingRouter:
    def __init__(self, *, result: LLMResult | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[JsonCompletionRequest, str | None]] = []

    async def complete_json(self, request, *, reply_language=None, timeout_seconds=None):
        self.calls.append((request, reply_language))
        if self.error is not None:
            raise self.error
        return self.result, [router_module.LLMAttempt(route=f"{self.result.provider}:{self.result.model}", status="SUCCEEDED")]


class EngineRouterTests(unittest.IsolatedAsyncioTestCase):
    async def _answer(self, router, *, reply_language=None):
        question = "What is my revenue?"
        classification = CopilotIntentClassifier(now=FIXED_NOW).classify(seller_id=SELLER_ID, question=question)
        plan = CopilotQuestionPlanner(now=FIXED_NOW).plan(
            seller_id=SELLER_ID,
            question=question,
            language="en",
            conversation_history=[],
            product_id=None,
            from_date=None,
            to_date=None,
            top_k=8,
            include_memory=True,
            business_catalog=None,
            metric_catalog=None,
            tool_registry=_Registry(),
            classification_hint=classification,
            max_tools=6,
        )

        async def legacy_groq(messages, **kwargs):
            raise AssertionError("legacy Groq path must not run when a router is set")

        return await CopilotHybridAnswerEngine(groq_json=legacy_groq, model="unused", timeout_seconds=1, llm_router=router).answer(
            question=question,
            classification=classification,
            plan=plan,
            tool_results=[_tool("get_revenue_summary", {"gross_revenue": "250.00"})],
            missing_data=[],
            reply_language=reply_language,
        )

    async def test_router_answer_is_validated_and_attributed(self):
        payload = {
            "answer": "Revenue is 250.00.",
            "summary": "Revenue is 250.00.",
            "confidence": "HIGH",
            "language": "en",
            "evidence": [{"evidence_id": "get_revenue_summary:1"}],
            "missing_data": [],
            "recommended_next_steps": [],
        }
        router = _RecordingRouter(result=LLMResult(content=payload, provider="anthropic", model="claude-opus-5-5", usage={"total_tokens": 520}))

        result = await self._answer(router, reply_language="en")

        self.assertIsNone(result.validation_error)
        self.assertEqual("anthropic/claude-opus-5-5", result.model_id)
        self.assertEqual({"total_tokens": 520}, result.token_usage)
        self.assertEqual("SUCCEEDED", result.llm_attempts[0].status)
        request, reply_language = router.calls[0]
        self.assertEqual("en", reply_language)
        self.assertEqual(["en", "bn", "banglish"], request.json_schema["properties"]["language"]["enum"])

    async def test_router_failure_falls_back_to_template_with_attempts(self):
        attempts = [router_module.LLMAttempt(route="anthropic:claude-opus-5-5", status="FAILED", code="TIMEOUT")]
        result = await self._answer(_RecordingRouter(error=LLMRouterError("none", attempts=attempts)))

        self.assertIsNone(result.model_id)
        self.assertEqual("LLMRouterError", result.validation_error)
        self.assertEqual(tuple(attempts), result.llm_attempts)
        self.assertTrue(result.payload["answer"])

    async def test_unsupported_number_from_router_model_is_still_rejected(self):
        payload = {
            "answer": "Revenue is 9999.",
            "summary": "Revenue is 9999.",
            "confidence": "HIGH",
            "language": "en",
            "evidence": [{"evidence_id": "get_revenue_summary:1"}],
            "missing_data": [],
            "recommended_next_steps": [],
        }
        result = await self._answer(_RecordingRouter(result=LLMResult(content=payload, provider="anthropic", model="claude-opus-5-5")))

        self.assertIn("Unsupported numeric claim: 9999", result.validation_error or "")

    def test_strict_schema_requires_every_property_and_forbids_extras(self):
        for multilingual in (False, True):
            schema = answer_json_schema(multilingual=multilingual)
            self.assertEqual(set(schema["properties"]), set(schema["required"]))
            self.assertFalse(schema["additionalProperties"])
            self.assertFalse(schema["properties"]["evidence"]["items"]["additionalProperties"])


class OrchestratorRouterFlagTests(unittest.TestCase):
    def _orchestrator(self, **settings_overrides):
        defaults = {"copilot_llm_router_enabled": False, "copilot_llm_answer_routes": "groq"}
        defaults.update(settings_overrides)
        with patch.multiple("app.services.copilot.orchestrator.settings", **defaults):
            return CopilotOrchestrator(repository=_FakeRepository(), tool_registry=_FakeRegistry(), model="llama-test")

    def test_flag_off_keeps_legacy_engine(self):
        self.assertIsNone(self._orchestrator()._hybrid_answer_engine._llm_router)

    def test_flag_on_builds_router_around_the_configured_groq_call(self):
        router = self._orchestrator(copilot_llm_router_enabled=True)._hybrid_answer_engine._llm_router
        self.assertIsNotNone(router)
        self.assertEqual({"groq"}, set(router.providers))

    def test_misconfigured_route_falls_back_to_legacy_engine(self):
        with self.assertLogs("app.services.copilot.orchestrator", level="ERROR"):
            orchestrator = self._orchestrator(copilot_llm_router_enabled=True, copilot_llm_answer_routes="openai:gpt-5")
        self.assertIsNone(orchestrator._hybrid_answer_engine._llm_router)


if __name__ == "__main__":
    unittest.main()
