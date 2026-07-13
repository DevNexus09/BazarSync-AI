"""add copilot storage

Revision ID: f7a8b9c0d1e2
Revises: e4f5a6b7c8d9
Create Date: 2026-07-05 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "f7a8b9c0d1e2"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


CONVERSATION_STATUS_VALUES = ("ACTIVE", "ARCHIVED", "DELETED")
MESSAGE_ROLE_VALUES = ("USER", "ASSISTANT", "SYSTEM", "TOOL")
TOOL_CALL_STATUS_VALUES = ("REQUESTED", "RUNNING", "SUCCEEDED", "FAILED", "BLOCKED", "SKIPPED")
ACTION_TYPE_VALUES = (
    "PRICE_CHANGE",
    "PROMOTION_PLAN",
    "REORDER_PLAN",
    "SEO_FIX",
    "BUNDLE_PLAN",
    "DISCOUNT_PLAN",
    "MANUAL_REVIEW",
)
ACTION_PROPOSAL_STATUS_VALUES = (
    "PROPOSED",
    "APPROVED",
    "REJECTED",
    "EXPIRED",
    "EXECUTION_NOT_IMPLEMENTED",
    "EXECUTED",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    enum_names = {enum["name"] for enum in inspector.get_enums()}
    if "copilot_conversation_status" not in enum_names:
        postgresql.ENUM(*CONVERSATION_STATUS_VALUES, name="copilot_conversation_status").create(bind, checkfirst=True)
    if "copilot_message_role" not in enum_names:
        postgresql.ENUM(*MESSAGE_ROLE_VALUES, name="copilot_message_role").create(bind, checkfirst=True)
    if "copilot_tool_call_status" not in enum_names:
        postgresql.ENUM(*TOOL_CALL_STATUS_VALUES, name="copilot_tool_call_status").create(bind, checkfirst=True)
    if "copilot_action_type" not in enum_names:
        postgresql.ENUM(*ACTION_TYPE_VALUES, name="copilot_action_type").create(bind, checkfirst=True)
    if "copilot_action_proposal_status" not in enum_names:
        postgresql.ENUM(*ACTION_PROPOSAL_STATUS_VALUES, name="copilot_action_proposal_status").create(
            bind,
            checkfirst=True,
        )

    table_names = set(inspector.get_table_names())
    if "copilot_conversations" not in table_names:
        op.create_table(
            "copilot_conversations",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("title", sa.String(length=255), nullable=True),
            sa.Column(
                "status",
                postgresql.ENUM(*CONVERSATION_STATUS_VALUES, name="copilot_conversation_status", create_type=False),
                nullable=False,
                server_default="ACTIVE",
            ),
            sa.Column("language", sa.String(length=16), nullable=False, server_default="en"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_copilot_conversations_seller_id", "copilot_conversations", ["seller_id"])
        op.create_index("ix_copilot_conversations_user_id", "copilot_conversations", ["user_id"])
        op.create_index("ix_copilot_conversations_status", "copilot_conversations", ["status"])
        op.create_index("ix_copilot_conversations_created_at", "copilot_conversations", ["created_at"])
        op.create_index("ix_copilot_conversations_seller_updated", "copilot_conversations", ["seller_id", "updated_at"])

    table_names = set(sa.inspect(bind).get_table_names())
    if "copilot_messages" not in table_names:
        op.create_table(
            "copilot_messages",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "role",
                postgresql.ENUM(*MESSAGE_ROLE_VALUES, name="copilot_message_role", create_type=False),
                nullable=False,
            ),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("language", sa.String(length=16), nullable=False, server_default="en"),
            sa.Column("answer_confidence", sa.String(length=20), nullable=True),
            sa.Column("model_id", sa.String(length=160), nullable=True),
            sa.Column("prompt_version", sa.String(length=80), nullable=True),
            sa.Column("token_usage_json", postgresql.JSONB(), nullable=True),
            sa.Column("evidence_json", postgresql.JSONB(), nullable=True),
            sa.Column("missing_context_json", postgresql.JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["conversation_id"], ["copilot_conversations.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_copilot_messages_seller_id", "copilot_messages", ["seller_id"])
        op.create_index("ix_copilot_messages_conversation_id", "copilot_messages", ["conversation_id"])
        op.create_index("ix_copilot_messages_created_at", "copilot_messages", ["created_at"])
        op.create_index(
            "ix_copilot_messages_seller_conversation_created",
            "copilot_messages",
            ["seller_id", "conversation_id", "created_at"],
        )

    table_names = set(sa.inspect(bind).get_table_names())
    if "copilot_tool_calls" not in table_names:
        op.create_table(
            "copilot_tool_calls",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("tool_name", sa.String(length=120), nullable=False),
            sa.Column("tool_version", sa.String(length=80), nullable=False, server_default="v1"),
            sa.Column("tool_args_json", postgresql.JSONB(), nullable=True),
            sa.Column("tool_result_summary_json", postgresql.JSONB(), nullable=True),
            sa.Column(
                "status",
                postgresql.ENUM(*TOOL_CALL_STATUS_VALUES, name="copilot_tool_call_status", create_type=False),
                nullable=False,
                server_default="REQUESTED",
            ),
            sa.Column("error_code", sa.String(length=80), nullable=True),
            sa.Column("error_message", sa.String(length=255), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["conversation_id"], ["copilot_conversations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["message_id"], ["copilot_messages.id"], ondelete="SET NULL"),
        )
        op.create_index("ix_copilot_tool_calls_seller_id", "copilot_tool_calls", ["seller_id"])
        op.create_index("ix_copilot_tool_calls_conversation_id", "copilot_tool_calls", ["conversation_id"])
        op.create_index("ix_copilot_tool_calls_message_id", "copilot_tool_calls", ["message_id"])
        op.create_index("ix_copilot_tool_calls_status", "copilot_tool_calls", ["status"])
        op.create_index("ix_copilot_tool_calls_created_at", "copilot_tool_calls", ["created_at"])
        op.create_index("ix_copilot_tool_calls_seller_created", "copilot_tool_calls", ["seller_id", "created_at"])

    table_names = set(sa.inspect(bind).get_table_names())
    if "copilot_action_proposals" not in table_names:
        op.create_table(
            "copilot_action_proposals",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "action_type",
                postgresql.ENUM(*ACTION_TYPE_VALUES, name="copilot_action_type", create_type=False),
                nullable=False,
            ),
            sa.Column("proposed_payload_json", postgresql.JSONB(), nullable=False),
            sa.Column("safety_checks_json", postgresql.JSONB(), nullable=True),
            sa.Column("expected_impact_json", postgresql.JSONB(), nullable=True),
            sa.Column("evidence_json", postgresql.JSONB(), nullable=True),
            sa.Column(
                "status",
                postgresql.ENUM(
                    *ACTION_PROPOSAL_STATUS_VALUES,
                    name="copilot_action_proposal_status",
                    create_type=False,
                ),
                nullable=False,
                server_default="PROPOSED",
            ),
            sa.Column("requires_confirmation", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["conversation_id"], ["copilot_conversations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["message_id"], ["copilot_messages.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        )
        op.create_index("ix_copilot_action_proposals_seller_id", "copilot_action_proposals", ["seller_id"])
        op.create_index("ix_copilot_action_proposals_conversation_id", "copilot_action_proposals", ["conversation_id"])
        op.create_index("ix_copilot_action_proposals_message_id", "copilot_action_proposals", ["message_id"])
        op.create_index("ix_copilot_action_proposals_product_id", "copilot_action_proposals", ["product_id"])
        op.create_index("ix_copilot_action_proposals_status", "copilot_action_proposals", ["status"])
        op.create_index("ix_copilot_action_proposals_action_type", "copilot_action_proposals", ["action_type"])
        op.create_index("ix_copilot_action_proposals_created_at", "copilot_action_proposals", ["created_at"])
        op.create_index(
            "ix_copilot_action_proposals_seller_status",
            "copilot_action_proposals",
            ["seller_id", "status"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    table_names = set(sa.inspect(bind).get_table_names())

    if "copilot_action_proposals" in table_names:
        op.drop_index("ix_copilot_action_proposals_seller_status", table_name="copilot_action_proposals")
        op.drop_index("ix_copilot_action_proposals_created_at", table_name="copilot_action_proposals")
        op.drop_index("ix_copilot_action_proposals_action_type", table_name="copilot_action_proposals")
        op.drop_index("ix_copilot_action_proposals_status", table_name="copilot_action_proposals")
        op.drop_index("ix_copilot_action_proposals_product_id", table_name="copilot_action_proposals")
        op.drop_index("ix_copilot_action_proposals_message_id", table_name="copilot_action_proposals")
        op.drop_index("ix_copilot_action_proposals_conversation_id", table_name="copilot_action_proposals")
        op.drop_index("ix_copilot_action_proposals_seller_id", table_name="copilot_action_proposals")
        op.drop_table("copilot_action_proposals")

    table_names = set(sa.inspect(bind).get_table_names())
    if "copilot_tool_calls" in table_names:
        op.drop_index("ix_copilot_tool_calls_seller_created", table_name="copilot_tool_calls")
        op.drop_index("ix_copilot_tool_calls_created_at", table_name="copilot_tool_calls")
        op.drop_index("ix_copilot_tool_calls_status", table_name="copilot_tool_calls")
        op.drop_index("ix_copilot_tool_calls_message_id", table_name="copilot_tool_calls")
        op.drop_index("ix_copilot_tool_calls_conversation_id", table_name="copilot_tool_calls")
        op.drop_index("ix_copilot_tool_calls_seller_id", table_name="copilot_tool_calls")
        op.drop_table("copilot_tool_calls")

    table_names = set(sa.inspect(bind).get_table_names())
    if "copilot_messages" in table_names:
        op.drop_index("ix_copilot_messages_seller_conversation_created", table_name="copilot_messages")
        op.drop_index("ix_copilot_messages_created_at", table_name="copilot_messages")
        op.drop_index("ix_copilot_messages_conversation_id", table_name="copilot_messages")
        op.drop_index("ix_copilot_messages_seller_id", table_name="copilot_messages")
        op.drop_table("copilot_messages")

    table_names = set(sa.inspect(bind).get_table_names())
    if "copilot_conversations" in table_names:
        op.drop_index("ix_copilot_conversations_seller_updated", table_name="copilot_conversations")
        op.drop_index("ix_copilot_conversations_created_at", table_name="copilot_conversations")
        op.drop_index("ix_copilot_conversations_status", table_name="copilot_conversations")
        op.drop_index("ix_copilot_conversations_user_id", table_name="copilot_conversations")
        op.drop_index("ix_copilot_conversations_seller_id", table_name="copilot_conversations")
        op.drop_table("copilot_conversations")

    enum_names = {enum["name"] for enum in sa.inspect(bind).get_enums()}
    for enum_name in (
        "copilot_action_proposal_status",
        "copilot_action_type",
        "copilot_tool_call_status",
        "copilot_message_role",
        "copilot_conversation_status",
    ):
        if enum_name in enum_names:
            postgresql.ENUM(name=enum_name).drop(bind, checkfirst=True)
