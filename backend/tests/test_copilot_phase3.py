from __future__ import annotations

import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.api.v1 import copilot as copilot_api
from app.db.base import Base
from app.models.copilot import CopilotConversation, CopilotMessage, CopilotMessageRole
from app.models.copilot_feedback import CopilotMessageFeedback
from app.models.seller import Seller
from app.repositories.copilot_repository import CopilotMessageNotFoundError, CopilotRepository, _safe_response_metadata
from app.schemas.copilot import CopilotAskRequest, CopilotMessageFeedbackRequest
from app.services.copilot.context_builder import budget_facts
from app.services.copilot.entity_resolver import CopilotEntityResolver
from app.services.copilot.follow_ups import suggested_follow_ups
from app.services.copilot.hybrid_answer_engine import CopilotHybridAnswerEngine
from app.services.copilot.intent_classifier import CopilotIntent, CopilotIntentClassifier
from app.services.copilot.orchestrator import CopilotOrchestrator, CopilotOrchestratorRequest, _conversation_turns
from app.services.copilot.question_planner import CopilotQuestionPlanner
from app.services.copilot.rate_limiter import CopilotAskRateLimiter, CopilotRateLimitExceeded

from tests.api.test_copilot import _FakeDb
from tests.test_copilot_hybrid_answer_engine import _Registry, _tool
from tests.test_copilot_orchestrator import (
    FIXED_NOW,
    OTHER_SELLER_ID,
    SELLER_ID,
    USER_ID,
    _FakeRegistry,
    _FakeRepository,
    _SellerScopedProductSource,
    _good_groq,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kwargs) -> str:
    return "JSON"


class PromptBudgetTests(unittest.TestCase):
    def test_small_facts_are_unchanged(self):
        facts = {"count_products": {"count": 12}}
        self.assertEqual((facts, []), budget_facts(facts, tool_chars=1000, total_chars=5000))

    def test_long_lists_are_trimmed_but_json_shape_survives(self):
        facts = {"get_inventory_risks": {"items": [{"title": f"Product {index}", "risk": "HIGH"} for index in range(500)]}}

        fitted, truncated = budget_facts(facts, tool_chars=2000, total_chars=50000)

        self.assertEqual(["get_inventory_risks"], truncated)
        self.assertTrue(fitted["get_inventory_risks"]["_truncated"])
        self.assertLess(len(fitted["get_inventory_risks"]["items"]), 500)
        self.assertLessEqual(len(json.dumps(fitted["get_inventory_risks"])), 2000)

    def test_total_budget_drops_memory_before_direct_facts_and_keeps_order(self):
        facts = {
            "retrieve_business_memory": {"chunks": ["x" * 900]},
            "get_revenue_summary": {"gross_revenue": "250.00", "note": "y" * 900},
        }

        fitted, truncated = budget_facts(facts, tool_chars=5000, total_chars=1200)

        self.assertEqual(["retrieve_business_memory", "get_revenue_summary"], list(fitted))
        self.assertEqual("250.00", fitted["get_revenue_summary"]["gross_revenue"])
        self.assertEqual({"_omitted": "prompt length budget"}, fitted["retrieve_business_memory"])
        self.assertEqual(["retrieve_business_memory"], truncated)


class ConversationMemoryTests(unittest.IsolatedAsyncioTestCase):
    def test_turns_use_questions_and_assistant_summaries(self):
        messages = [
            {"role": "USER", "content": "Why did revenue fall last week?"},
            {"role": "ASSISTANT", "content": "Long answer...", "response_metadata": {"summary": "Revenue fell after a stockout."}},
            {"role": "TOOL", "content": "ignored"},
        ]

        self.assertEqual(
            [{"role": "seller", "text": "Why did revenue fall last week?"}, {"role": "copilot", "text": "Revenue fell after a stockout."}],
            _conversation_turns(messages, 4),
        )

    def test_turn_count_is_bounded(self):
        messages = [{"role": "USER", "content": f"q{index}"} for index in range(20)]
        self.assertEqual(4, len(_conversation_turns(messages, 2)))

    async def _two_turns(self, *, enabled: bool):
        repository = _FakeRepository()
        prompts: list = []

        async def groq(messages, **kwargs):
            prompts.append(messages)
            return await _good_groq(messages, **kwargs)

        def orchestrator():
            return CopilotOrchestrator(
                repository=repository,
                classifier=CopilotIntentClassifier(now=FIXED_NOW),
                # "Why that one?" is deliberately vague; strict safety would (correctly) ask which product.
                question_planner=CopilotQuestionPlanner(
                    entity_resolver=CopilotEntityResolver(product_source=_SellerScopedProductSource()), now=FIXED_NOW, strict_safety=False
                ),
                tool_registry=_FakeRegistry(),
                groq_json=groq,
                model="test-model",
                groq_timeout_seconds=1,
                conversation_memory_enabled=enabled,
            )

        first = await orchestrator().ask(CopilotOrchestratorRequest(seller_id=SELLER_ID, user_id=USER_ID, question="What should I restock?"))
        await orchestrator().ask(
            CopilotOrchestratorRequest(seller_id=SELLER_ID, user_id=USER_ID, question="Why that one?", conversation_id=first.conversation_id)
        )
        return prompts

    async def test_follow_up_prompt_carries_earlier_turns_as_untrusted_context(self):
        prompts = await self._two_turns(enabled=True)

        self.assertNotIn("conversation_so_far", prompts[0][1]["content"])
        second_user = prompts[-1][1]["content"]
        self.assertIn("conversation_so_far", second_user)
        self.assertIn("What should I restock?", second_user)
        self.assertIn("not evidence", prompts[-1][0]["content"])

    async def test_memory_off_sends_single_turn_prompt(self):
        prompts = await self._two_turns(enabled=False)

        self.assertNotIn("conversation_so_far", prompts[-1][1]["content"])


class AnswerRepairTests(unittest.IsolatedAsyncioTestCase):
    async def _answer(self, responses: list[dict], *, repair_enabled: bool, timeout: float = 10):
        calls: list = []

        async def groq(messages, **kwargs):
            calls.append(messages)
            return responses[min(len(calls), len(responses)) - 1]

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
        engine = CopilotHybridAnswerEngine(groq_json=groq, model="m", timeout_seconds=timeout, repair_enabled=repair_enabled)
        result = await engine.answer(
            question=question,
            classification=classification,
            plan=plan,
            tool_results=[_tool("get_revenue_summary", {"gross_revenue": "250.00"})],
            missing_data=[],
        )
        return result, calls

    async def test_rejected_answer_is_repaired_once(self):
        result, calls = await self._answer([_response("Revenue is 9999.", usage=10), _response("Revenue is 250.00.", usage=7)], repair_enabled=True)

        self.assertTrue(result.repaired)
        self.assertIsNone(result.validation_error)
        self.assertEqual("Revenue is 250.00.", result.payload["answer"])
        self.assertEqual({"total_tokens": 17}, result.token_usage)
        self.assertEqual(2, len(calls))
        self.assertIn("UNSUPPORTED_NUMBER", calls[1][-1]["content"])
        self.assertEqual("assistant", calls[1][-2]["role"])

    async def test_failed_repair_falls_back_to_template(self):
        result, calls = await self._answer([_response("Revenue is 9999."), _response("Revenue is 8888.")], repair_enabled=True)

        self.assertFalse(result.repaired)
        self.assertIn("8888", result.validation_error or "")
        self.assertEqual(2, len(calls))
        self.assertNotIn("8888", result.payload["answer"])

    async def test_repair_disabled_makes_a_single_call(self):
        result, calls = await self._answer([_response("Revenue is 9999.")], repair_enabled=False)

        self.assertEqual(1, len(calls))
        self.assertIn("9999", result.validation_error or "")

    async def test_no_repair_without_enough_time_left(self):
        result, calls = await self._answer([_response("Revenue is 9999."), _response("Revenue is 250.00.")], repair_enabled=True, timeout=1)

        self.assertEqual(1, len(calls))
        self.assertFalse(result.repaired)


class FollowUpTests(unittest.IsolatedAsyncioTestCase):
    def test_suggestions_follow_reply_language_and_skip_the_asked_question(self):
        english = suggested_follow_ups(CopilotIntent.TODAY_ACTIONS, reply_language="en", question="What should I restock?")
        self.assertNotIn("What should I restock?", english)
        self.assertTrue(english)
        self.assertTrue(all(any("ঀ" <= ch <= "৿" for ch in item) for item in suggested_follow_ups(CopilotIntent.RESTOCK_ADVICE, reply_language="bn")))
        self.assertTrue(all(item.isascii() for item in suggested_follow_ups(CopilotIntent.RESTOCK_ADVICE, reply_language="banglish")))
        self.assertTrue(suggested_follow_ups(CopilotIntent.ACTION_REQUEST_PRICE_CHANGE, reply_language="en"))
        self.assertLessEqual(len(suggested_follow_ups(CopilotIntent.UNKNOWN, reply_language="en")), 3)

    async def test_orchestrator_returns_follow_ups_only_when_enabled(self):
        async def ask():
            return await CopilotOrchestrator(
                repository=_FakeRepository(), tool_registry=_FakeRegistry(), groq_json=_good_groq, model="m", groq_timeout_seconds=1,
                classifier=CopilotIntentClassifier(now=FIXED_NOW),
                question_planner=CopilotQuestionPlanner(entity_resolver=CopilotEntityResolver(product_source=_SellerScopedProductSource()), now=FIXED_NOW),
            ).ask(CopilotOrchestratorRequest(seller_id=SELLER_ID, user_id=USER_ID, question="What should I restock?"))

        with patch.object(copilot_api.settings, "copilot_follow_ups_enabled", True):
            self.assertTrue((await ask()).suggested_follow_ups)
        with patch.object(copilot_api.settings, "copilot_follow_ups_enabled", False):
            self.assertEqual([], (await ask()).suggested_follow_ups)


class FeedbackRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(
            self.engine,
            tables=[Seller.__table__, CopilotConversation.__table__, CopilotMessage.__table__, CopilotMessageFeedback.__table__],
        )
        self.db = Session(self.engine)
        self.seller = Seller(email="seller@example.com", password_hash="hash")
        self.other = Seller(email="other@example.com", password_hash="hash")
        self.db.add_all([self.seller, self.other])
        self.db.flush()
        conversation = CopilotConversation(seller_id=self.seller.id, language="en")
        self.db.add(conversation)
        self.db.flush()
        self.assistant = CopilotMessage(seller_id=self.seller.id, conversation_id=conversation.id, role=CopilotMessageRole.ASSISTANT, content="answer")
        self.user_message = CopilotMessage(seller_id=self.seller.id, conversation_id=conversation.id, role=CopilotMessageRole.USER, content="question")
        self.db.add_all([self.assistant, self.user_message])
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_resubmitting_updates_the_single_row(self):
        repository = CopilotRepository(self.db)
        repository.upsert_message_feedback(seller_id=self.seller.id, message_id=self.assistant.id, rating="UP")
        feedback = repository.upsert_message_feedback(seller_id=self.seller.id, message_id=self.assistant.id, rating="DOWN", reason="wrong_numbers")

        self.assertEqual("DOWN", feedback.rating)
        self.assertEqual("wrong_numbers", feedback.reason)
        self.assertEqual(1, self.db.scalar(select(func.count()).select_from(CopilotMessageFeedback)))

    def test_other_sellers_and_non_assistant_messages_are_not_found(self):
        repository = CopilotRepository(self.db)
        with self.assertRaises(CopilotMessageNotFoundError):
            repository.upsert_message_feedback(seller_id=self.other.id, message_id=self.assistant.id, rating="UP")
        with self.assertRaises(CopilotMessageNotFoundError):
            repository.upsert_message_feedback(seller_id=self.seller.id, message_id=self.user_message.id, rating="UP")
        self.assertEqual(0, self.db.scalar(select(func.count()).select_from(CopilotMessageFeedback)))


class FeedbackApiTests(unittest.TestCase):
    def test_route_uses_authenticated_seller_and_maps_not_found(self):
        seen = {}

        class _Repo:
            def __init__(self, db):
                del db

            def upsert_message_feedback(self, **kwargs):
                seen.update(kwargs)
                if kwargs["message_id"] != MESSAGE_ID:
                    raise CopilotMessageNotFoundError("missing")
                return type("F", (), {"message_id": MESSAGE_ID, "rating": kwargs["rating"], "reason": kwargs["reason"], "updated_at": FIXED_NOW})()

        seller = Seller(id=SELLER_ID, email="seller@example.com", password_hash="x")
        with patch.object(copilot_api, "CopilotRepository", _Repo):
            response = copilot_api.submit_message_feedback(MESSAGE_ID, CopilotMessageFeedbackRequest(rating="down", reason=" too_vague "), db=_FakeDb(), current_seller=seller)
            first_call = dict(seen)
            with self.assertRaises(HTTPException) as raised:
                copilot_api.submit_message_feedback(uuid4(), CopilotMessageFeedbackRequest(rating="up"), db=_FakeDb(), current_seller=seller)

        self.assertEqual("down", response.rating)
        self.assertEqual("DOWN", first_call["rating"])
        self.assertEqual(SELLER_ID, first_call["seller_id"])
        self.assertEqual("too_vague", response.reason)
        self.assertEqual(404, raised.exception.status_code)

    def test_unknown_fields_and_ratings_are_rejected(self):
        with self.assertRaises(ValueError):
            CopilotMessageFeedbackRequest(rating="meh")
        with self.assertRaises(ValueError):
            CopilotMessageFeedbackRequest(rating="up", seller_id=str(OTHER_SELLER_ID))


class RateLimiterTests(unittest.IsolatedAsyncioTestCase):
    def test_limit_per_seller_per_window(self):
        limiter = CopilotAskRateLimiter(limit_per_minute=2, clock=lambda: 120.0)
        limiter.check(SELLER_ID)
        limiter.check(SELLER_ID)
        with self.assertRaises(CopilotRateLimitExceeded) as raised:
            limiter.check(SELLER_ID)
        self.assertEqual(60, raised.exception.retry_after_seconds)
        limiter.check(OTHER_SELLER_ID)

    def test_new_window_resets_and_zero_disables(self):
        now = [10.0]
        limiter = CopilotAskRateLimiter(limit_per_minute=1, clock=lambda: now[0])
        limiter.check(SELLER_ID)
        now[0] = 75.0
        limiter.check(SELLER_ID)
        disabled = CopilotAskRateLimiter(limit_per_minute=0)
        for _ in range(100):
            disabled.check(SELLER_ID)

    def test_redis_failure_falls_back_to_local_counting(self):
        class _BrokenRedis:
            def pipeline(self):
                raise ConnectionError("down")

        limiter = CopilotAskRateLimiter(limit_per_minute=1, redis_client=_BrokenRedis(), clock=lambda: 5.0)
        with self.assertLogs("app.services.copilot.rate_limiter", level="WARNING"):
            limiter.check(SELLER_ID)
            with self.assertRaises(CopilotRateLimitExceeded):
                limiter.check(SELLER_ID)

    async def test_ask_route_returns_429_with_retry_after(self):
        seller = Seller(id=SELLER_ID, email="seller@example.com", password_hash="x")
        limiter = CopilotAskRateLimiter(limit_per_minute=1, clock=lambda: 30.0)
        limiter.check(SELLER_ID)
        with patch.object(copilot_api, "copilot_ask_rate_limiter", limiter):
            with self.assertRaises(HTTPException) as raised:
                await copilot_api.ask_copilot(CopilotAskRequest(question="What should I restock?"), db=_FakeDb(), current_seller=seller)

        self.assertEqual(429, raised.exception.status_code)
        self.assertEqual("30", raised.exception.headers["Retry-After"])
        self.assertEqual("rate_limited", raised.exception.detail["error_code"])


class PlanningMetadataTests(unittest.TestCase):
    def test_language_profile_survives_with_only_safe_fields(self):
        safe = _safe_response_metadata(
            {"summary": "s", "language_profile": {"reply_language": "banglish", "signals": {"banglish_score": 3}, "source": "DETECTED"}, "secret": "x"}
        )

        self.assertEqual({"reply_language": "banglish", "source": "DETECTED"}, safe["language_profile"])
        self.assertNotIn("secret", safe)


MESSAGE_ID = uuid4()


def _response(answer: str, *, usage: int | None = None) -> dict:
    response = {
        "model": "m",
        "content": {
            "answer": answer,
            "summary": answer,
            "confidence": "HIGH",
            "language": "en",
            "evidence": [{"evidence_id": "get_revenue_summary:1"}],
            "missing_data": [],
            "recommended_next_steps": [],
        },
    }
    if usage is not None:
        response["usage"] = {"total_tokens": usage}
    return response


if __name__ == "__main__":
    unittest.main()


# --- Performance, planner fallback and RAG retrieval -------------------------------------------

import asyncio  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

from app.repositories.rag_memory_repository import RagMemoryRepository  # noqa: E402
from app.services import rag_retrieval_service  # noqa: E402
from app.services.copilot.tool_registry import CopilotToolRegistry  # noqa: E402


class _SlowRegistry(_FakeRegistry):
    def __init__(self, delays: dict[str, float]) -> None:
        super().__init__()
        self.delays = delays
        self.threads: set[int] = set()
        self.contexts: list = []
        self._lock = threading.Lock()

    def list_tools(self):
        return CopilotToolRegistry().list_tools()

    def validate_arguments(self, name, arguments):
        return CopilotToolRegistry().validate_arguments(name, arguments)

    def execute(self, *, name, context, arguments):
        with self._lock:
            self.threads.add(threading.get_ident())
            self.contexts.append(context)
        time.sleep(self.delays.get(name, 0.0))
        return super().execute(name=name, context=context, arguments=arguments)


class _NoopDb:
    """Stands in for the request session; telemetry writes go nowhere."""

    def add(self, *_):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass

    def flush(self):
        pass


class _Session:
    def __init__(self, registry: list) -> None:
        self.closed = False
        registry.append(self)

    def close(self) -> None:
        self.closed = True


class ConcurrentToolTests(unittest.IsolatedAsyncioTestCase):
    async def _ask(self, registry, *, overall_timeout: float = 45, question: str = "What should I do today?"):
        sessions: list[_Session] = []
        repository = _FakeRepository()
        orchestrator = CopilotOrchestrator(
            db=_NoopDb(),  # marks that a real DB is present, so each tool gets its own session
            repository=repository,
            classifier=CopilotIntentClassifier(now=FIXED_NOW),
            question_planner=CopilotQuestionPlanner(entity_resolver=CopilotEntityResolver(product_source=_SellerScopedProductSource()), now=FIXED_NOW),
            tool_registry=registry,
            groq_json=_good_groq,
            model="m",
            groq_timeout_seconds=1,
            overall_timeout_seconds=overall_timeout,
            parallel_tools_enabled=True,
            tool_session_factory=lambda: _Session(sessions),
        )
        result = await orchestrator.ask(CopilotOrchestratorRequest(seller_id=SELLER_ID, user_id=USER_ID, question=question))
        return result, repository, sessions

    async def test_tools_overlap_in_threads_and_rows_keep_plan_order(self):
        registry = _SlowRegistry(delays={})
        registry.delays = {"get_today_actions": 0.2, "get_business_overview": 0.2, "get_revenue_summary": 0.2}
        started = time.monotonic()
        _, repository, sessions = await self._ask(registry)
        elapsed = time.monotonic() - started

        planned = [row["tool_name"] for row in repository.tool_calls]
        self.assertEqual("get_today_actions", planned[0])
        self.assertLess(elapsed, 0.55, "three 0.2s tools should overlap")
        self.assertGreater(len(registry.threads), 1)
        self.assertEqual(len(planned), len(sessions))
        self.assertTrue(all(session.closed for session in sessions))
        self.assertTrue(all(context.seller_id == SELLER_ID and context.read_only for context in registry.contexts))
        self.assertEqual({SELLER_ID}, set(repository.seller_ids))

    async def test_overall_budget_interrupts_a_hung_tool(self):
        registry = _SlowRegistry(delays={"get_today_actions": 3.0})
        started = time.monotonic()
        _, repository, _ = await self._ask(registry, overall_timeout=1)

        self.assertLess(time.monotonic() - started, 2.5)
        row = next(row for row in repository.tool_calls if row["tool_name"] == "get_today_actions")
        self.assertEqual("TOOL_TIMEOUT", row["error_code"])


class LlmPlannerFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def _ask(self, suggestion, *, include_memory=True, include_current_data=True):
        registry = _SlowRegistry(delays={})
        prompts = []

        async def groq(messages, **kwargs):
            prompts.append(messages)
            if "route a marketplace seller" in messages[0]["content"]:
                if isinstance(suggestion, Exception):
                    raise suggestion
                return {"model": "m", "content": {"tools": suggestion}}
            return await _good_groq(messages, **kwargs)

        orchestrator = CopilotOrchestrator(
            repository=_FakeRepository(),
            classifier=CopilotIntentClassifier(now=FIXED_NOW),
            question_planner=CopilotQuestionPlanner(entity_resolver=CopilotEntityResolver(product_source=_SellerScopedProductSource()), now=FIXED_NOW),
            tool_registry=registry,
            groq_json=groq,
            model="m",
            groq_timeout_seconds=1,
            llm_planner_fallback_enabled=True,
        )
        await orchestrator.ask(
            CopilotOrchestratorRequest(
                seller_id=SELLER_ID, user_id=USER_ID, question="xyzzy plugh", include_memory=include_memory, include_current_data=include_current_data
            )
        )
        return [call["name"] for call in registry.calls], prompts

    async def test_valid_suggestions_run_and_invented_tools_are_dropped(self):
        names, prompts = await self._ask(["get_inventory_risks", "os.system", "drop_tables", "get_inventory_risks"], include_memory=False)

        self.assertEqual(["get_inventory_risks"], names)
        catalogue = json.loads(prompts[0][1]["content"])["tools"]
        self.assertNotIn("retrieve_business_memory", [tool["name"] for tool in catalogue])
        self.assertNotIn(str(SELLER_ID), prompts[0][1]["content"])

    async def test_model_failure_means_no_extra_tools(self):
        names, _ = await self._ask(RuntimeError("down"), include_memory=False)
        self.assertEqual([], names)

    async def test_fallback_is_not_called_when_the_deterministic_plan_has_tools(self):
        registry = _SlowRegistry(delays={})
        routed = []

        async def groq(messages, **kwargs):
            if "route a marketplace seller" in messages[0]["content"]:
                routed.append(messages)
            return await _good_groq(messages, **kwargs)

        await CopilotOrchestrator(
            repository=_FakeRepository(),
            classifier=CopilotIntentClassifier(now=FIXED_NOW),
            question_planner=CopilotQuestionPlanner(entity_resolver=CopilotEntityResolver(product_source=_SellerScopedProductSource()), now=FIXED_NOW),
            tool_registry=registry,
            groq_json=groq,
            model="m",
            groq_timeout_seconds=1,
            llm_planner_fallback_enabled=True,
        ).ask(CopilotOrchestratorRequest(seller_id=SELLER_ID, user_id=USER_ID, question="What should I restock?"))

        self.assertEqual([], routed)
        self.assertIn("get_restock_recommendations", [call["name"] for call in registry.calls])


class RagRetrievalTuningTests(unittest.TestCase):
    def test_cosine_flag_switches_operator_and_similarity(self):
        class _Db:
            def __init__(self):
                self.sql = []

            def execute(self, statement, params=None):
                self.sql.append(str(statement))
                return self

            def all(self):
                return []

        for enabled, operator in ((False, "<->"), (True, "<=>")):
            db = _Db()
            with patch.object(rag_retrieval_service.settings, "rag_cosine_distance_enabled", enabled):
                RagMemoryRepository(db).vector_search(seller_id=SELLER_ID, query_embedding=[0.1, 0.2])
                similarity = rag_retrieval_service._similarity_from_distance(0.2)
            self.assertIn(f"c.embedding {operator} CAST", db.sql[0])
            self.assertAlmostEqual(0.8 if enabled else 1 / 1.2, similarity)

    def test_query_embedding_cache_is_seller_scoped_and_bounded(self):
        class _Embedder:
            model_name = "bge-test"

            def __init__(self):
                self.calls = 0

            def embed_text(self, text):
                self.calls += 1
                return [float(len(text)), float(self.calls)]

        embedder = _Embedder()
        rag_retrieval_service._QUERY_EMBEDDING_CACHE.clear()
        with patch.object(rag_retrieval_service.settings, "rag_query_embedding_cache_size", 2):
            first = rag_retrieval_service._cached_query_embedding(embedder, seller_id=SELLER_ID, text="sales")
            again = rag_retrieval_service._cached_query_embedding(embedder, seller_id=SELLER_ID, text="sales")
            other_seller = rag_retrieval_service._cached_query_embedding(embedder, seller_id=OTHER_SELLER_ID, text="sales")
            rag_retrieval_service._cached_query_embedding(embedder, seller_id=SELLER_ID, text="stock")
            evicted = rag_retrieval_service._cached_query_embedding(embedder, seller_id=SELLER_ID, text="sales")

        self.assertEqual(first, again)
        self.assertNotEqual(first, other_seller)
        self.assertEqual(5 - 1, embedder.calls)
        self.assertNotEqual(first, evicted)
        rag_retrieval_service._QUERY_EMBEDDING_CACHE.clear()

    def test_cache_disabled_by_default(self):
        class _Embedder:
            model_name = "bge-test"
            calls = 0

            def embed_text(self, text):
                type(self).calls += 1
                return [1.0]

        with patch.object(rag_retrieval_service.settings, "rag_query_embedding_cache_size", 0):
            rag_retrieval_service._cached_query_embedding(_Embedder(), seller_id=SELLER_ID, text="a")
            rag_retrieval_service._cached_query_embedding(_Embedder(), seller_id=SELLER_ID, text="a")
        self.assertEqual(2, _Embedder.calls)


del asyncio


# --- Streaming ------------------------------------------------------------------------------

from app.services.copilot.observability import capability_snapshot  # noqa: E402
from tests.api.test_copilot import _FakeOrchestrator  # noqa: E402


def _parse_sse(chunks: list[str]) -> list[tuple[str, dict]]:
    events = []
    for block in "".join(chunks).strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_orchestrator_emits_stages_in_order_and_survives_a_broken_listener(self):
        events = []

        async def listener(event):
            events.append(event)

        orchestrator = CopilotOrchestrator(
            repository=_FakeRepository(), tool_registry=_FakeRegistry(), groq_json=_good_groq, model="m", groq_timeout_seconds=1,
            classifier=CopilotIntentClassifier(now=FIXED_NOW),
            question_planner=CopilotQuestionPlanner(entity_resolver=CopilotEntityResolver(product_source=_SellerScopedProductSource()), now=FIXED_NOW),
        )
        await orchestrator.ask(CopilotOrchestratorRequest(seller_id=SELLER_ID, user_id=USER_ID, question="What should I restock?"), progress=listener)

        stages = [event["stage"] for event in events]
        self.assertEqual("understanding", stages[0])
        self.assertEqual("planning", stages[1])
        self.assertEqual("writing", stages[-1])
        self.assertIn("tool", stages)
        self.assertIn("Restock recommendations", next(event for event in events if event["stage"] == "planning")["tools"])
        self.assertNotIn("answer", json.dumps(events))

        def broken(event):
            raise RuntimeError("listener bug")

        with self.assertLogs("app.services.copilot.orchestrator", level="WARNING"):
            result = await orchestrator.ask(CopilotOrchestratorRequest(seller_id=SELLER_ID, user_id=USER_ID, question="What should I restock?"), progress=broken)
        self.assertTrue(result.answer)

    async def _stream(self, orchestrator_cls, **payload):
        sessions: list[_Session] = []
        seller = Seller(id=SELLER_ID, email="seller@example.com", password_hash="x")
        with (
            patch.object(copilot_api.settings, "copilot_streaming_enabled", True),
            patch.object(copilot_api, "CopilotOrchestrator", orchestrator_cls),
            patch.object(copilot_api, "_stream_session_factory", lambda: _Session(sessions)),
        ):
            response = await copilot_api.ask_copilot_stream(CopilotAskRequest(question="What should I restock?", **payload), db=_FakeDb(), current_seller=seller)
            chunks = [chunk async for chunk in response.body_iterator]
        return response, _parse_sse(chunks), sessions

    async def test_stream_sends_stages_then_the_same_answer_body_as_ask(self):
        class _ProgressOrchestrator(_FakeOrchestrator):
            async def ask(self, request, progress=None):
                await progress({"stage": "planning", "tools": ["Restock recommendations"]})
                return await super().ask(request)

        response, events, sessions = await self._stream(_ProgressOrchestrator)

        self.assertEqual("text/event-stream", response.media_type)
        self.assertEqual(["stage", "answer"], [name for name, _ in events])
        self.assertEqual("Restock Product A based on current evidence.", events[1][1]["answer"])
        self.assertIn("message_id", events[1][1])
        self.assertTrue(all(session.closed for session in sessions))

    async def test_stream_reports_errors_as_events_without_internal_detail(self):
        class _BrokenOrchestrator(_FakeOrchestrator):
            async def ask(self, request, progress=None):
                raise RuntimeError("database password=secret")

        with self.assertLogs("app.api.v1.copilot", level="ERROR"):
            _, events, sessions = await self._stream(_BrokenOrchestrator)

        self.assertEqual([("error", {"error_code": "copilot_failed", "detail": "Copilot could not answer right now."})], events)
        self.assertTrue(sessions[0].closed)

    async def test_stream_maps_missing_conversation(self):
        class _StreamingFake(_FakeOrchestrator):
            async def ask(self, request, progress=None):
                return await super().ask(request)

        _, events, _ = await self._stream(_StreamingFake, conversation_id=uuid4())
        self.assertEqual("conversation_not_found", events[0][1]["error_code"])

    async def test_stream_is_off_by_default_and_keeps_pre_checks(self):
        seller = Seller(id=SELLER_ID, email="seller@example.com", password_hash="x")
        with patch.object(copilot_api.settings, "copilot_streaming_enabled", False):
            with self.assertRaises(HTTPException) as raised:
                await copilot_api.ask_copilot_stream(CopilotAskRequest(question="hi"), db=_FakeDb(), current_seller=seller)
        self.assertEqual(404, raised.exception.status_code)

        with patch.object(copilot_api.settings, "copilot_streaming_enabled", True):
            with self.assertRaises(HTTPException) as raised:
                await copilot_api.ask_copilot_stream(
                    CopilotAskRequest(question="hi", product_id=uuid4()), db=_FakeDb(product_owned=False), current_seller=seller
                )
        self.assertEqual(403, raised.exception.status_code)

    def test_capabilities_advertise_feature_switches(self):
        with patch.object(copilot_api.settings, "copilot_streaming_enabled", True), patch.object(copilot_api.settings, "copilot_multilingual_enabled", True):
            features = capability_snapshot()["features"]
        self.assertTrue(features["streaming"])
        self.assertIn("banglish", features["languages"])
