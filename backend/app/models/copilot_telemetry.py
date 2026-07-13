from __future__ import annotations

from datetime import datetime
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.copilot import CopilotConversation
    from app.models.seller import Seller


class CopilotRunTelemetry(Base):
    """Bounded, seller-scoped operational facts for one Copilot request.

    This deliberately stores plan and outcome metadata only. The question,
    generated prompt, tool payloads, secrets, and embeddings are not stored.
    """

    __tablename__ = "copilot_run_telemetry"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_copilot_run_telemetry_run_id"),
        CheckConstraint("tools_succeeded >= 0", name="ck_copilot_telemetry_tools_succeeded_nonnegative"),
        CheckConstraint("tools_failed >= 0", name="ck_copilot_telemetry_tools_failed_nonnegative"),
        CheckConstraint("rag_result_count >= 0", name="ck_copilot_telemetry_rag_result_count_nonnegative"),
        CheckConstraint("evidence_count >= 0", name="ck_copilot_telemetry_evidence_count_nonnegative"),
        CheckConstraint("missing_data_count >= 0", name="ck_copilot_telemetry_missing_data_count_nonnegative"),
        Index("ix_copilot_telemetry_seller_created", "seller_id", "created_at"),
        Index("ix_copilot_telemetry_conversation_created", "conversation_id", "created_at"),
        Index("ix_copilot_telemetry_planner_status", "planner_status"),
        Index("ix_copilot_telemetry_result_status", "result_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sellers.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("copilot_conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    request_mode: Mapped[str] = mapped_column(String(24), nullable=False)
    question_type: Mapped[str] = mapped_column(String(64), nullable=False)
    selected_domains_json: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    selected_metrics_json: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    selected_tools_json: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    planner_status: Mapped[str] = mapped_column(String(32), nullable=False)
    planner_fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    clarification_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tools_succeeded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tools_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rag_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rag_result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing_data_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    final_confidence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result_status: Mapped[str] = mapped_column(String(32), nullable=False)
    planner_miss_reasons_json: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    planner_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rag_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    groq_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship()
    conversation: Mapped["CopilotConversation | None"] = relationship()
