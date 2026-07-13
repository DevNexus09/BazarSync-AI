from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import importlib.util
import unittest
from uuid import uuid4

from app.models.copilot import (
    CopilotActionProposal,
    CopilotActionProposalStatus,
    CopilotActionType,
    CopilotConversation,
    CopilotConversationStatus,
    CopilotMessage,
    CopilotMessageRole,
    CopilotToolCall,
    CopilotToolCallStatus,
)
from app.repositories.copilot_repository import CopilotRepository
from app.schemas.copilot import (
    CopilotActionProposalResponse,
    CopilotAskRequest,
    CopilotAskResponse,
    CopilotConversationCreate,
    CopilotConversationResponse,
    CopilotMessageResponse,
    CopilotToolCallResponse,
)


class _ScalarResult:
    def __init__(self, rows=None, scalar=None, rowcount: int = 0) -> None:
        self._rows = rows or []
        self._scalar = scalar
        self.rowcount = rowcount

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar if self._scalar is not None else 0

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _CaptureSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.calls: list[object] = []
        self.commits = 0
        self.refreshed: list[object] = []

    def add(self, item) -> None:
        self.added.append(item)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, item) -> None:
        self.refreshed.append(item)

    def execute(self, statement):
        self.calls.append(statement)
        return _ScalarResult(rowcount=1)


class _PlanningSession:
    def __init__(self, *, conversation=None, messages=None) -> None:
        self.conversation = conversation
        self.messages = messages or []
        self.calls = 0

    def execute(self, statement):
        del statement
        self.calls += 1
        if self.calls == 1:
            return _ScalarResult(scalar=self.conversation)
        return _ScalarResult(rows=self.messages)


def _load_migration_module():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "f7a8b9c0d1e2_add_copilot_storage.py"
    )
    spec = importlib.util.spec_from_file_location("copilot_migration", migration_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class CopilotFoundationTests(unittest.TestCase):
    def test_migration_is_reversible_and_creates_expected_tables(self):
        migration = _load_migration_module()

        self.assertEqual("f7a8b9c0d1e2", migration.revision)
        self.assertEqual("e4f5a6b7c8d9", migration.down_revision)
        source = Path(migration.__file__).read_text()

        for table_name in (
            "copilot_conversations",
            "copilot_messages",
            "copilot_tool_calls",
            "copilot_action_proposals",
        ):
            self.assertIn(table_name, source)
            self.assertIn(f"op.drop_table(\"{table_name}\")", source)

        self.assertIn("copilot_conversation_status", source)
        self.assertIn("copilot_action_proposal_status", source)
        self.assertIn("ForeignKeyConstraint([\"seller_id\"], [\"sellers.id\"]", source)

    def test_models_declare_seller_scope_and_audit_columns(self):
        for model in (CopilotConversation, CopilotMessage, CopilotToolCall, CopilotActionProposal):
            column_names = {column.name for column in model.__table__.columns}
            self.assertIn("seller_id", column_names)
            self.assertIn("created_at", column_names)

        self.assertIn("archived_at", {column.name for column in CopilotConversation.__table__.columns})
        self.assertIn("metadata_json", {column.name for column in CopilotConversation.__table__.columns})
        self.assertIn("tool_args_json", {column.name for column in CopilotToolCall.__table__.columns})
        self.assertIn("proposed_payload_json", {column.name for column in CopilotActionProposal.__table__.columns})

    def test_pydantic_schemas_are_available(self):
        self.assertEqual("en", CopilotConversationCreate().language)
        self.assertEqual(8, CopilotAskRequest(question="What happened?").top_k)

        for schema in (
            CopilotConversationResponse,
            CopilotMessageResponse,
            CopilotAskResponse,
            CopilotToolCallResponse,
            CopilotActionProposalResponse,
        ):
            self.assertTrue(schema)

    def test_create_conversation(self):
        session = _CaptureSession()
        seller_id = uuid4()
        user_id = uuid4()

        conversation = CopilotRepository(session).create_conversation(
            seller_id=seller_id,
            user_id=user_id,
            title="Restock questions",
            language="en",
            metadata_json={"source": "test"},
        )

        self.assertIsInstance(conversation, CopilotConversation)
        self.assertEqual(seller_id, conversation.seller_id)
        self.assertEqual(user_id, conversation.user_id)
        self.assertEqual(CopilotConversationStatus.ACTIVE, conversation.status)
        self.assertEqual(1, session.commits)
        self.assertEqual([conversation], session.refreshed)

    def test_add_message(self):
        session = _CaptureSession()
        seller_id = uuid4()
        conversation_id = uuid4()

        message = CopilotRepository(session).add_message(
            seller_id=seller_id,
            conversation_id=conversation_id,
            role=CopilotMessageRole.USER,
            content="Which products need restock?",
            evidence_json={"evidence_ids": []},
            missing_data_json=["MISSING_INVENTORY"],
            tools_used_json=[{"name": "get_inventory_summary", "status": "SUCCEEDED"}],
            domains_used_json=["inventory"],
            recommended_next_steps_json=["Review stock."],
            response_metadata_json={"summary": "Inventory summary.", "question_type": "INVENTORY"},
        )

        self.assertIsInstance(message, CopilotMessage)
        self.assertEqual(seller_id, message.seller_id)
        self.assertEqual(conversation_id, message.conversation_id)
        self.assertEqual(CopilotMessageRole.USER, message.role)
        self.assertEqual(["MISSING_INVENTORY"], message.missing_data_json)
        self.assertEqual(["inventory"], message.domains_used_json)
        self.assertEqual(1, session.commits)

    def test_store_tool_call(self):
        session = _CaptureSession()
        seller_id = uuid4()
        now = datetime.now(timezone.utc)

        tool_call = CopilotRepository(session).add_tool_call(
            seller_id=seller_id,
            conversation_id=uuid4(),
            message_id=uuid4(),
            tool_name="rag.retrieve_memory",
            started_at=now,
            status=CopilotToolCallStatus.SUCCEEDED,
            tool_args_json={"top_k": 8},
            tool_result_summary_json={"evidence_count": 2},
            duration_ms=12,
            evidence_count=2,
            missing_data_count=1,
            completed_at=now,
        )

        self.assertIsInstance(tool_call, CopilotToolCall)
        self.assertEqual("rag.retrieve_memory", tool_call.tool_name)
        self.assertEqual(CopilotToolCallStatus.SUCCEEDED, tool_call.status)
        self.assertEqual(seller_id, tool_call.seller_id)
        self.assertEqual(12, tool_call.duration_ms)
        self.assertEqual(2, tool_call.evidence_count)
        self.assertEqual(1, tool_call.missing_data_count)

    def test_store_action_proposal_without_execution(self):
        session = _CaptureSession()
        seller_id = uuid4()

        proposal = CopilotRepository(session).add_action_proposal(
            seller_id=seller_id,
            conversation_id=uuid4(),
            message_id=uuid4(),
            product_id=uuid4(),
            action_type=CopilotActionType.REORDER_PLAN,
            proposed_payload_json={"quantity": 10},
            safety_checks_json={"execution_enabled": False},
            expected_impact_json={"note": "estimate from existing recommendation"},
            evidence_json={"evidence_ids": ["ev-1"]},
        )

        self.assertIsInstance(proposal, CopilotActionProposal)
        self.assertEqual(CopilotActionProposalStatus.PROPOSED, proposal.status)
        self.assertTrue(proposal.requires_confirmation)
        self.assertIsNone(proposal.executed_at)

    def test_action_proposal_cannot_be_stored_as_executed_in_mvp(self):
        session = _CaptureSession()

        with self.assertRaisesRegex(ValueError, "execution is not implemented"):
            CopilotRepository(session).add_action_proposal(
                seller_id=uuid4(),
                conversation_id=uuid4(),
                message_id=uuid4(),
                action_type=CopilotActionType.PRICE_CHANGE,
                proposed_payload_json={"new_price": "19.99"},
                status=CopilotActionProposalStatus.EXECUTED,
            )

        self.assertEqual([], session.added)
        self.assertEqual(0, session.commits)

    def test_archive_conversation_is_seller_scoped(self):
        session = _CaptureSession()
        seller_id = uuid4()
        conversation_id = uuid4()

        updated = CopilotRepository(session).archive_conversation(
            seller_id=seller_id,
            conversation_id=conversation_id,
        )

        self.assertEqual(1, updated)
        self.assertEqual(1, session.commits)

    def test_recent_messages_for_planning_are_seller_scoped_sanitized_and_bounded(self):
        seller_id = uuid4()
        conversation_id = uuid4()
        now = datetime.now(timezone.utc)
        conversation = CopilotConversation(id=conversation_id, seller_id=seller_id, user_id=seller_id)
        messages = [
            CopilotMessage(
                id=uuid4(),
                seller_id=seller_id,
                conversation_id=conversation_id,
                role=CopilotMessageRole.USER,
                content="Question with password=super-secret\nTraceback (most recent call last):\nFile \"x.py\", line 1",
                language="en",
                created_at=now,
            ),
            CopilotMessage(
                id=uuid4(),
                seller_id=seller_id,
                conversation_id=conversation_id,
                role=CopilotMessageRole.ASSISTANT,
                content="Revenue answer",
                language="en",
                domains_used_json=["SALES_REVENUE"],
                tools_used_json=[{"name": "get_revenue_summary", "status": "SUCCEEDED", "data": {"raw": "blocked"}}],
                evidence_json=[{"evidence_id": "sales:1", "raw_payload": "blocked"}],
                response_metadata_json={
                    "summary": "Revenue",
                    "raw_tool_payload": {"secret": "blocked"},
                    "planning_context": {
                        "active_metrics": ["gross_revenue"],
                        "last_successful_plan": {"question_type": "ANALYTIC"},
                    },
                },
                created_at=now,
            ),
        ]
        session = _PlanningSession(conversation=conversation, messages=messages)

        rows = CopilotRepository(session).get_recent_messages_for_planning(
            seller_id=seller_id,
            conversation_id=conversation_id,
            message_limit=5,
            character_limit=40,
        )

        self.assertEqual(2, len(rows))
        joined = " ".join(row["content"] for row in rows)
        self.assertNotIn("super-secret", joined)
        self.assertNotIn("Traceback", joined)
        self.assertLessEqual(sum(len(row["content"]) for row in rows), 40)
        assistant_row = next(row for row in rows if row["domains_used"])
        self.assertEqual(["SALES_REVENUE"], assistant_row["domains_used"])
        self.assertEqual([{"name": "get_revenue_summary", "status": "SUCCEEDED", "evidence_count": None}], assistant_row["tools_used"])
        self.assertEqual(["sales:1"], assistant_row["evidence_ids"])
        self.assertNotIn("raw_tool_payload", assistant_row["response_metadata"])

    def test_recent_messages_for_planning_blocks_cross_seller_conversation(self):
        session = _PlanningSession(conversation=None)

        with self.assertRaisesRegex(ValueError, "Conversation not found"):
            CopilotRepository(session).get_recent_messages_for_planning(
                seller_id=uuid4(),
                conversation_id=uuid4(),
            )

    def test_no_cross_seller_reads(self):
        session = _CaptureSession()
        seller_id = uuid4()
        conversation_id = uuid4()
        repository = CopilotRepository(session)

        repository.get_conversation(seller_id=seller_id, conversation_id=conversation_id)
        repository.list_messages(seller_id=seller_id, conversation_id=conversation_id)

        conversation_sql = str(session.calls[0])
        messages_sql = str(session.calls[1])
        self.assertIn("copilot_conversations.seller_id", conversation_sql)
        self.assertIn("copilot_messages.seller_id", messages_sql)
        self.assertIn("copilot_conversations.seller_id", messages_sql)


if __name__ == "__main__":
    unittest.main()
