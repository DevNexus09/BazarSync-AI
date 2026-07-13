from __future__ import annotations

from datetime import datetime
from enum import Enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.seller import Seller


class CopilotConversationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"


class CopilotMessageRole(str, Enum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    SYSTEM = "SYSTEM"
    TOOL = "TOOL"


class CopilotToolCallStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"


class CopilotActionType(str, Enum):
    PRICE_CHANGE = "PRICE_CHANGE"
    PROMOTION_PLAN = "PROMOTION_PLAN"
    REORDER_PLAN = "REORDER_PLAN"
    SEO_FIX = "SEO_FIX"
    BUNDLE_PLAN = "BUNDLE_PLAN"
    DISCOUNT_PLAN = "DISCOUNT_PLAN"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class CopilotActionProposalStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    EXECUTION_NOT_IMPLEMENTED = "EXECUTION_NOT_IMPLEMENTED"
    EXECUTED = "EXECUTED"


class CopilotConversation(Base):
    __tablename__ = "copilot_conversations"
    __table_args__ = (
        Index("ix_copilot_conversations_seller_id", "seller_id"),
        Index("ix_copilot_conversations_user_id", "user_id"),
        Index("ix_copilot_conversations_status", "status"),
        Index("ix_copilot_conversations_created_at", "created_at"),
        Index("ix_copilot_conversations_seller_updated", "seller_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sellers.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[CopilotConversationStatus] = mapped_column(
        SAEnum(CopilotConversationStatus, name="copilot_conversation_status"),
        nullable=False,
        default=CopilotConversationStatus.ACTIVE,
    )
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    seller: Mapped["Seller"] = relationship(back_populates="copilot_conversations")
    messages: Mapped[list["CopilotMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
    )
    tool_calls: Mapped[list["CopilotToolCall"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
    )
    action_proposals: Mapped[list["CopilotActionProposal"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
    )

    @property
    def conversation_id(self) -> uuid.UUID:
        return self.id


class CopilotMessage(Base):
    __tablename__ = "copilot_messages"
    __table_args__ = (
        Index("ix_copilot_messages_seller_id", "seller_id"),
        Index("ix_copilot_messages_conversation_id", "conversation_id"),
        Index("ix_copilot_messages_created_at", "created_at"),
        Index("ix_copilot_messages_seller_conversation_created", "seller_id", "conversation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sellers.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("copilot_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[CopilotMessageRole] = mapped_column(
        SAEnum(CopilotMessageRole, name="copilot_message_role"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    answer_confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    token_usage_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    evidence_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB, nullable=True)
    missing_context_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB, nullable=True)
    missing_data_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB, nullable=True)
    data_freshness_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB, nullable=True)
    tools_used_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB, nullable=True)
    domains_used_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB, nullable=True)
    recommended_next_steps_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB, nullable=True)
    action_proposal_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB, nullable=True)
    response_metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship()
    conversation: Mapped["CopilotConversation"] = relationship(back_populates="messages")
    tool_calls: Mapped[list["CopilotToolCall"]] = relationship(back_populates="message")
    action_proposals: Mapped[list["CopilotActionProposal"]] = relationship(back_populates="message")


class CopilotToolCall(Base):
    __tablename__ = "copilot_tool_calls"
    __table_args__ = (
        Index("ix_copilot_tool_calls_seller_id", "seller_id"),
        Index("ix_copilot_tool_calls_conversation_id", "conversation_id"),
        Index("ix_copilot_tool_calls_message_id", "message_id"),
        Index("ix_copilot_tool_calls_status", "status"),
        Index("ix_copilot_tool_calls_created_at", "created_at"),
        Index("ix_copilot_tool_calls_seller_created", "seller_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sellers.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("copilot_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("copilot_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(80), nullable=False, default="v1")
    tool_args_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    tool_result_summary_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[CopilotToolCallStatus] = mapped_column(
        SAEnum(CopilotToolCallStatus, name="copilot_tool_call_status"),
        nullable=False,
        default=CopilotToolCallStatus.REQUESTED,
    )
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    missing_data_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship()
    conversation: Mapped["CopilotConversation"] = relationship(back_populates="tool_calls")
    message: Mapped["CopilotMessage | None"] = relationship(back_populates="tool_calls")


class CopilotActionProposal(Base):
    __tablename__ = "copilot_action_proposals"
    __table_args__ = (
        Index("ix_copilot_action_proposals_seller_id", "seller_id"),
        Index("ix_copilot_action_proposals_conversation_id", "conversation_id"),
        Index("ix_copilot_action_proposals_message_id", "message_id"),
        Index("ix_copilot_action_proposals_product_id", "product_id"),
        Index("ix_copilot_action_proposals_status", "status"),
        Index("ix_copilot_action_proposals_action_type", "action_type"),
        Index("ix_copilot_action_proposals_created_at", "created_at"),
        Index("ix_copilot_action_proposals_seller_status", "seller_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sellers.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("copilot_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("copilot_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
    )
    action_type: Mapped[CopilotActionType] = mapped_column(
        SAEnum(CopilotActionType, name="copilot_action_type"),
        nullable=False,
    )
    proposed_payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    safety_checks_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB, nullable=True)
    expected_impact_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    evidence_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[CopilotActionProposalStatus] = mapped_column(
        SAEnum(CopilotActionProposalStatus, name="copilot_action_proposal_status"),
        nullable=False,
        default=CopilotActionProposalStatus.PROPOSED,
    )
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    seller: Mapped["Seller"] = relationship()
    conversation: Mapped["CopilotConversation"] = relationship(back_populates="action_proposals")
    message: Mapped["CopilotMessage"] = relationship(back_populates="action_proposals")
    product: Mapped["Product | None"] = relationship()
