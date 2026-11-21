from __future__ import annotations

from datetime import date, datetime, timezone
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1 import copilot as copilot_api
from app.models.copilot import (
    CopilotActionProposalStatus,
    CopilotActionType,
    CopilotConversationStatus,
    CopilotMessageRole,
)
from app.models.seller import Seller
from app.repositories.copilot_repository import CopilotConversationNotFoundError
from app.schemas.copilot import CopilotAskRequest, CopilotConversationCreate


SELLER_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_SELLER_ID = UUID("00000000-0000-0000-0000-000000000002")
CONVERSATION_ID = UUID("00000000-0000-0000-0000-000000000010")
MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000020")
PRODUCT_ID = UUID("00000000-0000-0000-0000-000000000030")
PROPOSAL_ID = UUID("00000000-0000-0000-0000-000000000040")


class _Obj:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


class _FakeRepo:
    def __init__(self, db) -> None:
        self.db = db

    def create_conversation(self, **kwargs):
        return _conversation(seller_id=kwargs["seller_id"], title=kwargs.get("title"))

    def list_conversations(self, **kwargs):
        return [_conversation(seller_id=kwargs["seller_id"], title="Restock")], 1

    def get_conversation(self, *, seller_id, conversation_id):
        if seller_id != SELLER_ID or conversation_id != CONVERSATION_ID:
            return None
        return _conversation(seller_id=seller_id)

    def list_messages(self, *, seller_id, conversation_id):
        return [
            _message(seller_id=seller_id, conversation_id=conversation_id, content="What should I restock?"),
            _assistant_message(seller_id=seller_id, conversation_id=conversation_id),
        ]

    def search_messages(self, **kwargs):
        return [_message(seller_id=kwargs["seller_id"], conversation_id=CONVERSATION_ID, content="Restock Product A")], 1


class _FakeDb:
    def __init__(self, *, product_owned: bool = True) -> None:
        self.product_owned = product_owned

    def execute(self, statement):
        del statement
        return self

    def scalar_one_or_none(self):
        return PRODUCT_ID if self.product_owned else None


class _FakeOrchestrator:
    def __init__(self, db=None) -> None:
        self.db = db

    async def ask(self, request):
        if request.conversation_id and request.conversation_id != CONVERSATION_ID:
            raise CopilotConversationNotFoundError("Conversation not found for authenticated seller.")
        if request.question == "trigger internal value error":
            raise ValueError("Unrelated internal failure.")
        return _Obj(
            conversation_id=request.conversation_id or CONVERSATION_ID,
            assistant_message_id=MESSAGE_ID,
            answer="Restock Product A based on current evidence.",
            summary="Restock summary.",
            confidence="HIGH",
            language="en",
            intent="RESTOCK_ADVICE",
            tool_trace=[{"tool_name": "get_restock_recommendations", "status": "SUCCEEDED", "internal": "hidden"}],
            tools_used=[{"name": "get_restock_recommendations", "status": "SUCCEEDED", "evidence_count": 1}],
            evidence=[{"evidence_id": "ev-1", "source_type": "tool", "title": "Reorder"}],
            missing_data=[],
            data_freshness=[{"domain": "inventory", "status": "FRESH", "message": "Fresh"}],
            domains_used=["inventory"],
            question_type="RESTOCK",
            recommended_next_steps=["Review supplier lead time."],
            action_proposal=None,
        )


class _CaptureOrchestrator(_FakeOrchestrator):
    last_request = None

    async def ask(self, request):
        type(self).last_request = request
        return await super().ask(request)


class _NoContextOrchestrator(_FakeOrchestrator):
    async def ask(self, request):
        result = await super().ask(request)
        result.answer = "I could not find enough seller-specific history to answer this reliably."
        result.confidence = "NO_CONTEXT"
        result.evidence = []
        result.missing_data = ["No reorder recommendations were found."]
        return result


class _MissingDataOrchestrator(_FakeOrchestrator):
    async def ask(self, request):
        result = await super().ask(request)
        result.confidence = "LOW"
        result.missing_data = ["Sales velocity is missing."]
        return result


class _FakeActionProposalService:
    def __init__(self, db=None) -> None:
        self.db = db

    def list_proposals(self, **kwargs):
        return [_proposal(seller_id=kwargs["seller_id"])], 1

    def get_proposal(self, *, seller_id, proposal_id):
        if seller_id != SELLER_ID or proposal_id != PROPOSAL_ID:
            from app.services.copilot.action_proposal_service import CopilotActionProposalNotFoundError

            raise CopilotActionProposalNotFoundError
        return _proposal(seller_id=seller_id)

    def approve(self, *, seller_id, proposal_id):
        proposal = self.get_proposal(seller_id=seller_id, proposal_id=proposal_id)
        proposal.status = CopilotActionProposalStatus.APPROVED
        proposal.approved_at = datetime.now(timezone.utc)
        return proposal, "Execution is not implemented yet. This proposal has been approved for future execution."

    def reject(self, *, seller_id, proposal_id):
        proposal = self.get_proposal(seller_id=seller_id, proposal_id=proposal_id)
        proposal.status = CopilotActionProposalStatus.REJECTED
        proposal.rejected_at = datetime.now(timezone.utc)
        return proposal, "This proposal has been rejected. No marketplace action was executed."


class CopilotApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.seller = Seller(id=SELLER_ID, email="seller@example.com", password_hash="x")

    def test_create_conversation(self):
        with patch.object(copilot_api, "CopilotRepository", _FakeRepo):
            response = copilot_api.create_conversation(
                CopilotConversationCreate(title="Restock"),
                db=_FakeDb(),
                current_seller=self.seller,
            )

        self.assertEqual(SELLER_ID, response.seller_id)
        self.assertEqual("Restock", response.title)

    async def test_ask_question(self):
        with patch.object(copilot_api, "CopilotOrchestrator", _FakeOrchestrator):
            response = await copilot_api.ask_copilot(
                CopilotAskRequest(question="What should I restock?"),
                db=_FakeDb(),
                current_seller=self.seller,
            )

        self.assertEqual(CONVERSATION_ID, response.conversation_id)
        self.assertEqual(MESSAGE_ID, response.message_id)
        self.assertEqual("RESTOCK_ADVICE", response.intent)
        self.assertEqual("get_restock_recommendations", response.tools_used[0].name)
        self.assertIsNone(response.debug)

    async def test_ask_payload_with_all_supported_fields_reaches_orchestrator(self):
        _CaptureOrchestrator.last_request = None
        payload = CopilotAskRequest(
            conversation_id=CONVERSATION_ID,
            question="What changed in revenue?",
            product_id=PRODUCT_ID,
            language="bn",
            from_date="2026-07-01T08:30:00+06:00",
            to_date="2026-07-12",
            domain_filters=["SALES_REVENUE", "COMPETITOR"],
            include_current_data=False,
            include_memory=True,
            memory_source_types=["SALES_HISTORY", "COMPETITOR_HISTORY"],
            top_k=5,
            debug=True,
        )

        with patch.object(copilot_api, "CopilotOrchestrator", _CaptureOrchestrator):
            response = await copilot_api.ask_copilot(
                payload,
                db=_FakeDb(),
                current_seller=self.seller,
            )

        request = _CaptureOrchestrator.last_request
        self.assertIsNotNone(request)
        self.assertEqual(CONVERSATION_ID, request.conversation_id)
        self.assertEqual(PRODUCT_ID, request.product_id)
        self.assertEqual("bn", request.requested_language)
        self.assertEqual(date(2026, 7, 1), request.from_date)
        self.assertEqual(date(2026, 7, 12), request.to_date)
        self.assertEqual(["SALES_REVENUE", "COMPETITOR"], [domain.value for domain in request.domain_filters])
        self.assertFalse(request.include_current_data)
        self.assertTrue(request.include_memory)
        self.assertEqual(["SALES_HISTORY", "COMPETITOR_HISTORY"], [source.value for source in request.memory_source_types])
        self.assertEqual(5, request.top_k)
        self.assertTrue(request.debug_allowed)
        self.assertIsNotNone(response.debug)

    def test_retrieve_messages(self):
        with patch.object(copilot_api, "CopilotRepository", _FakeRepo):
            response = copilot_api.get_conversation_messages(
                CONVERSATION_ID,
                db=_FakeDb(),
                current_seller=self.seller,
            )

        self.assertEqual(CONVERSATION_ID, response.conversation.id)
        self.assertEqual(CONVERSATION_ID, response.conversation.conversation_id)
        self.assertEqual(2, len(response.messages))
        assistant = response.messages[1]
        self.assertEqual("Restock Product A.", assistant.summary)
        self.assertEqual("HIGH", assistant.confidence)
        self.assertEqual(["inventory"], assistant.domains_used)
        self.assertEqual("get_restock_recommendations", assistant.tools_used[0]["name"])
        self.assertEqual("ev-1", assistant.evidence[0]["evidence_id"])
        self.assertEqual("MISSING_COST", assistant.missing_data[0])
        self.assertEqual("FRESH", assistant.data_freshness[0]["status"])
        self.assertEqual("Review supplier lead time.", assistant.recommended_next_steps[0])
        self.assertEqual("proposal-1", assistant.action_proposal["id"])

    def test_cross_seller_conversation_blocked(self):
        with patch.object(copilot_api, "CopilotRepository", _FakeRepo):
            with self.assertRaises(HTTPException) as raised:
                copilot_api.get_conversation_messages(
                    uuid4(),
                    db=_FakeDb(),
                    current_seller=self.seller,
                )

        self.assertEqual(404, raised.exception.status_code)
        self.assertEqual("conversation_not_found", raised.exception.detail["error_code"])

    async def test_cross_seller_product_blocked(self):
        with patch.object(copilot_api, "CopilotOrchestrator", _FakeOrchestrator):
            with self.assertRaises(HTTPException) as raised:
                await copilot_api.ask_copilot(
                    CopilotAskRequest(question="What should I restock?", product_id=PRODUCT_ID),
                    db=_FakeDb(product_owned=False),
                    current_seller=self.seller,
                )

        self.assertEqual(403, raised.exception.status_code)
        self.assertEqual("product_not_owned", raised.exception.detail["error_code"])

    def test_action_proposal_approve_reject(self):
        with patch.object(copilot_api, "CopilotActionProposalService", _FakeActionProposalService):
            approved = copilot_api.approve_action_proposal(PROPOSAL_ID, db=_FakeDb(), current_seller=self.seller)
            rejected = copilot_api.reject_action_proposal(PROPOSAL_ID, db=_FakeDb(), current_seller=self.seller)

        self.assertEqual(CopilotActionProposalStatus.APPROVED, approved.proposal.status)
        self.assertFalse(approved.executed)
        self.assertIn("Execution is not implemented yet", approved.message)
        self.assertEqual(CopilotActionProposalStatus.REJECTED, rejected.proposal.status)

    def test_invalid_question_length(self):
        with self.assertRaises(ValidationError):
            CopilotAskRequest(question="")

    def test_invalid_date_range_rejected(self):
        with self.assertRaises(ValidationError):
            CopilotAskRequest(question="What changed?", from_date="2026-07-12", to_date="2026-07-01")

    def test_unsupported_domain_rejected(self):
        with self.assertRaises(ValidationError):
            CopilotAskRequest(question="What changed?", domain_filters=["revenue"])

    def test_unsupported_memory_source_rejected(self):
        with self.assertRaises(ValidationError):
            CopilotAskRequest(question="What changed?", memory_source_types=["database"])

    def test_top_k_limit_enforced(self):
        with self.assertRaises(ValidationError):
            CopilotAskRequest(question="What changed?", top_k=21)

    def test_seller_id_cannot_be_supplied_by_client(self):
        with self.assertRaises(ValidationError):
            CopilotAskRequest(question="What changed?", seller_id=OTHER_SELLER_ID)

    def test_legacy_source_types_compatibility_maps_memory_sources(self):
        payload = CopilotAskRequest(question="What changed?", source_types=["SALES_HISTORY"])

        self.assertEqual(["SALES_HISTORY"], [source.value for source in payload.memory_source_types])
        self.assertTrue(payload.include_memory)

    def test_legacy_source_types_modes_only_set_booleans(self):
        payload = CopilotAskRequest(question="What changed?", source_types=["database", "memory"])

        self.assertTrue(payload.include_current_data)
        self.assertTrue(payload.include_memory)
        self.assertIsNone(payload.memory_source_types)

    def test_legacy_source_types_mixed_modes_do_not_become_rag_sources(self):
        payload = CopilotAskRequest(question="What changed?", source_types=["database", "SALES_HISTORY"])

        self.assertTrue(payload.include_current_data)
        self.assertTrue(payload.include_memory)
        self.assertEqual(["SALES_HISTORY"], [source.value for source in payload.memory_source_types])

    async def test_unknown_conversation(self):
        with patch.object(copilot_api, "CopilotOrchestrator", _FakeOrchestrator):
            with self.assertRaises(HTTPException) as raised:
                await copilot_api.ask_copilot(
                    CopilotAskRequest(question="What should I restock?", conversation_id=uuid4()),
                    db=_FakeDb(),
                    current_seller=self.seller,
                )

        self.assertEqual(404, raised.exception.status_code)
        self.assertEqual("conversation_not_found", raised.exception.detail["error_code"])

    async def test_unrelated_value_error_is_not_reported_as_missing_conversation(self):
        with patch.object(copilot_api, "CopilotOrchestrator", _FakeOrchestrator):
            with self.assertRaises(ValueError) as raised:
                await copilot_api.ask_copilot(
                    CopilotAskRequest(question="trigger internal value error"),
                    db=_FakeDb(),
                    current_seller=self.seller,
                )

        self.assertNotIsInstance(raised.exception, HTTPException)
        self.assertEqual("Unrelated internal failure.", str(raised.exception))

    async def test_no_context_answer(self):
        with patch.object(copilot_api, "CopilotOrchestrator", _NoContextOrchestrator):
            response = await copilot_api.ask_copilot(
                CopilotAskRequest(question="What should I restock?"),
                db=_FakeDb(),
                current_seller=self.seller,
            )

        self.assertEqual("NO_CONTEXT", response.confidence)
        self.assertEqual([], response.evidence)
        self.assertTrue(response.missing_data)

    async def test_missing_data_answer(self):
        with patch.object(copilot_api, "CopilotOrchestrator", _MissingDataOrchestrator):
            response = await copilot_api.ask_copilot(
                CopilotAskRequest(question="Why is revenue down?"),
                db=_FakeDb(),
                current_seller=self.seller,
            )

        self.assertEqual(["Sales velocity is missing."], response.missing_data)
        self.assertNotIn("Traceback", response.answer)

    def test_tools_metadata_endpoint(self):
        response = copilot_api.get_available_tools(current_seller=self.seller)

        self.assertTrue(response.tools)
        first = response.tools[0].model_dump()
        self.assertIn("name", first)
        self.assertIn("domain", first)
        self.assertIn("description", first)
        self.assertIn("input_fields", first)
        self.assertIn("safety_level", first)
        self.assertIn("requires_confirmation", first)
        self.assertIn("allowed_in_read_only_mode", first)
        self.assertNotIn("implementation", first)
        self.assertNotIn("handler", first)
        self.assertNotIn("version", first)
        self.assertNotIn("max_runtime_ms", first)
        self.assertNotIn("catalog_metrics", first)
        self.assertNotIn("function", first)
        self.assertNotIn("sql", first)

    def test_search_history(self):
        with patch.object(copilot_api, "CopilotRepository", _FakeRepo):
            response = copilot_api.search_copilot_history(
                q="restock",
                db=_FakeDb(),
                current_seller=self.seller,
                limit=20,
                offset=0,
            )

        self.assertEqual(1, response.total)
        self.assertIn("Restock", response.items[0].content)

    def test_list_conversations_includes_hydration_summary_fields(self):
        with patch.object(copilot_api, "CopilotRepository", _FakeRepo):
            response = copilot_api.list_conversations(db=_FakeDb(), current_seller=self.seller, limit=20, offset=0)

        self.assertEqual(CONVERSATION_ID, response.items[0].conversation_id)
        self.assertEqual(0, response.items[0].message_count)
        self.assertIn("Restock", response.items[0].title)


def _conversation(*, seller_id: UUID, title: str | None = None):
    now = datetime.now(timezone.utc)
    return _Obj(
        id=CONVERSATION_ID,
        seller_id=seller_id,
        user_id=seller_id,
        title=title,
        status=CopilotConversationStatus.ACTIVE,
        language="en",
        created_at=now,
        updated_at=now,
        archived_at=None,
        metadata_json=None,
    )


def _message(*, seller_id: UUID, conversation_id: UUID, content: str):
    return _Obj(
        id=MESSAGE_ID,
        seller_id=seller_id,
        conversation_id=conversation_id,
        role=CopilotMessageRole.USER,
        content=content,
        language="en",
        answer_confidence=None,
        model_id=None,
        prompt_version=None,
        token_usage_json=None,
        evidence_json=None,
        missing_context_json=None,
        missing_data_json=None,
        data_freshness_json=None,
        tools_used_json=None,
        domains_used_json=None,
        recommended_next_steps_json=None,
        action_proposal_json=None,
        response_metadata_json=None,
        created_at=datetime.now(timezone.utc),
    )


def _assistant_message(*, seller_id: UUID, conversation_id: UUID):
    now = datetime.now(timezone.utc)
    return _Obj(
        id=uuid4(),
        seller_id=seller_id,
        conversation_id=conversation_id,
        role=CopilotMessageRole.ASSISTANT,
        content="Restock Product A based on current evidence.",
        language="en",
        answer_confidence="HIGH",
        model_id="model",
        prompt_version="test",
        token_usage_json=None,
        evidence_json=[{"evidence_id": "ev-1", "source_type": "tool", "title": "Reorder"}],
        missing_context_json=["MISSING_COST"],
        missing_data_json=["MISSING_COST"],
        data_freshness_json=[{"domain": "inventory", "status": "FRESH", "message": "Fresh"}],
        tools_used_json=[{"name": "get_restock_recommendations", "status": "SUCCEEDED", "evidence_count": 1}],
        domains_used_json=["inventory"],
        recommended_next_steps_json=["Review supplier lead time."],
        action_proposal_json={"id": "proposal-1", "status": "PROPOSED"},
        response_metadata_json={"summary": "Restock Product A.", "question_type": "RESTOCK"},
        created_at=now,
    )


def _proposal(*, seller_id: UUID):
    now = datetime.now(timezone.utc)
    return _Obj(
        id=PROPOSAL_ID,
        seller_id=seller_id,
        conversation_id=CONVERSATION_ID,
        message_id=MESSAGE_ID,
        product_id=PRODUCT_ID,
        action_type=CopilotActionType.PRICE_CHANGE,
        proposed_payload_json={"execution_enabled": False},
        safety_checks_json={"marketplace_mutation_performed": False},
        expected_impact_json=None,
        evidence_json=[],
        status=CopilotActionProposalStatus.PROPOSED,
        requires_confirmation=True,
        created_at=now,
        approved_at=None,
        rejected_at=None,
        executed_at=None,
        expires_at=None,
    )


if __name__ == "__main__":
    unittest.main()
