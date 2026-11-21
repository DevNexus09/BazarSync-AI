from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.copilot_feedback import CopilotMessageFeedback
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

SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer\s+[a-z0-9._-]+|password|secret|token|cookie)\s*[:=]\s*\S+"
)
STACK_TRACE_RE = re.compile(r"(?im)^\s*(traceback \(most recent call last\)|file \".*\", line \d+|stack trace:).*$")
MAX_PLANNING_MESSAGE_LIMIT = 50
MAX_PLANNING_CHARACTER_LIMIT = 12_000


class CopilotConversationNotFoundError(ValueError):
    """The conversation does not exist for the authenticated seller."""


class CopilotMessageNotFoundError(ValueError):
    """The assistant message does not exist for the authenticated seller."""


class CopilotRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create_conversation(
        self,
        *,
        seller_id: UUID,
        user_id: UUID | None = None,
        title: str | None = None,
        language: str = "en",
        metadata_json: dict[str, Any] | None = None,
    ) -> CopilotConversation:
        conversation = CopilotConversation(
            seller_id=seller_id,
            user_id=user_id,
            title=title,
            status=CopilotConversationStatus.ACTIVE,
            language=language,
            metadata_json=metadata_json,
        )
        self._db.add(conversation)
        self._db.commit()
        self._db.refresh(conversation)
        return conversation

    def get_conversation(self, *, seller_id: UUID, conversation_id: UUID) -> CopilotConversation | None:
        statement = select(CopilotConversation).where(
            CopilotConversation.seller_id == seller_id,
            CopilotConversation.id == conversation_id,
            CopilotConversation.status != CopilotConversationStatus.DELETED,
        )
        return self._db.execute(statement).scalar_one_or_none()

    def list_conversations(
        self,
        *,
        seller_id: UUID,
        include_archived: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[CopilotConversation], int]:
        statement = select(CopilotConversation).where(
            CopilotConversation.seller_id == seller_id,
            CopilotConversation.status != CopilotConversationStatus.DELETED,
        )
        if not include_archived:
            statement = statement.where(CopilotConversation.status == CopilotConversationStatus.ACTIVE)
        total = self._db.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
        rows = self._db.execute(
            statement.order_by(CopilotConversation.updated_at.desc(), CopilotConversation.id.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
        return rows, int(total or 0)

    def archive_conversation(
        self,
        *,
        seller_id: UUID,
        conversation_id: UUID,
        archived_at: datetime | None = None,
    ) -> int:
        timestamp = archived_at or datetime.now(timezone.utc)
        result = self._db.execute(
            update(CopilotConversation)
            .where(
                CopilotConversation.seller_id == seller_id,
                CopilotConversation.id == conversation_id,
                CopilotConversation.status == CopilotConversationStatus.ACTIVE,
            )
            .values(
                status=CopilotConversationStatus.ARCHIVED,
                archived_at=timestamp,
                updated_at=func.now(),
            )
        )
        self._db.commit()
        return int(result.rowcount or 0)

    def add_message(
        self,
        *,
        seller_id: UUID,
        conversation_id: UUID,
        role: CopilotMessageRole,
        content: str,
        language: str = "en",
        answer_confidence: str | None = None,
        model_id: str | None = None,
        prompt_version: str | None = None,
        token_usage_json: dict[str, Any] | None = None,
        evidence_json: dict[str, Any] | list[Any] | None = None,
        missing_context_json: dict[str, Any] | list[Any] | None = None,
        missing_data_json: dict[str, Any] | list[Any] | None = None,
        data_freshness_json: dict[str, Any] | list[Any] | None = None,
        tools_used_json: dict[str, Any] | list[Any] | None = None,
        domains_used_json: dict[str, Any] | list[Any] | None = None,
        recommended_next_steps_json: dict[str, Any] | list[Any] | None = None,
        action_proposal_json: dict[str, Any] | list[Any] | None = None,
        response_metadata_json: dict[str, Any] | None = None,
    ) -> CopilotMessage:
        message = CopilotMessage(
            seller_id=seller_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            language=language,
            answer_confidence=answer_confidence,
            model_id=model_id,
            prompt_version=prompt_version,
            token_usage_json=token_usage_json,
            evidence_json=evidence_json,
            missing_context_json=missing_context_json,
            missing_data_json=missing_data_json,
            data_freshness_json=data_freshness_json,
            tools_used_json=tools_used_json,
            domains_used_json=domains_used_json,
            recommended_next_steps_json=recommended_next_steps_json,
            action_proposal_json=action_proposal_json,
            response_metadata_json=response_metadata_json,
        )
        self._db.add(message)
        self._db.commit()
        self._db.refresh(message)
        return message

    def list_messages(self, *, seller_id: UUID, conversation_id: UUID) -> list[CopilotMessage]:
        statement = (
            select(CopilotMessage)
            .join(CopilotConversation, CopilotMessage.conversation_id == CopilotConversation.id)
            .where(
                CopilotMessage.seller_id == seller_id,
                CopilotMessage.conversation_id == conversation_id,
                CopilotConversation.seller_id == seller_id,
                CopilotConversation.status != CopilotConversationStatus.DELETED,
            )
            .order_by(CopilotMessage.created_at.asc(), CopilotMessage.id.asc())
        )
        return self._db.execute(statement).scalars().all()

    def upsert_message_feedback(
        self,
        *,
        seller_id: UUID,
        message_id: UUID,
        rating: str,
        reason: str | None = None,
        comment: str | None = None,
    ) -> CopilotMessageFeedback:
        """Record a seller's rating of one of their assistant messages; resubmitting replaces it."""
        message = self._db.execute(
            select(CopilotMessage).where(
                CopilotMessage.id == message_id,
                CopilotMessage.seller_id == seller_id,
                CopilotMessage.role == CopilotMessageRole.ASSISTANT,
            )
        ).scalar_one_or_none()
        if message is None:
            raise CopilotMessageNotFoundError("Assistant message not found for authenticated seller.")
        values = {"rating": rating, "reason": reason, "comment": comment}
        existing = self._feedback_for(seller_id=seller_id, message_id=message_id)
        if existing is None:
            try:
                with self._db.begin_nested():
                    existing = CopilotMessageFeedback(
                        seller_id=seller_id,
                        conversation_id=message.conversation_id,
                        message_id=message_id,
                        **values,
                    )
                    self._db.add(existing)
            except IntegrityError:
                # A concurrent submission created the row first; update that one instead.
                existing = self._feedback_for(seller_id=seller_id, message_id=message_id)
                if existing is None:
                    raise
        for key, value in values.items():
            setattr(existing, key, value)
        self._db.commit()
        self._db.refresh(existing)
        return existing

    def _feedback_for(self, *, seller_id: UUID, message_id: UUID) -> CopilotMessageFeedback | None:
        return self._db.execute(
            select(CopilotMessageFeedback).where(
                CopilotMessageFeedback.seller_id == seller_id,
                CopilotMessageFeedback.message_id == message_id,
            )
        ).scalar_one_or_none()

    def get_recent_messages_for_planning(
        self,
        *,
        seller_id: UUID,
        conversation_id: UUID,
        message_limit: int = 12,
        character_limit: int = 6000,
    ) -> list[dict[str, Any]]:
        conversation = self.get_conversation(seller_id=seller_id, conversation_id=conversation_id)
        if conversation is None:
            raise CopilotConversationNotFoundError("Conversation not found for authenticated seller.")

        bounded_limit = max(1, min(int(message_limit or 1), MAX_PLANNING_MESSAGE_LIMIT))
        bounded_chars = max(1, min(int(character_limit or 1), MAX_PLANNING_CHARACTER_LIMIT))
        statement = (
            select(CopilotMessage)
            .where(
                CopilotMessage.seller_id == seller_id,
                CopilotMessage.conversation_id == conversation_id,
                CopilotMessage.role.in_([CopilotMessageRole.USER, CopilotMessageRole.ASSISTANT]),
            )
            .order_by(CopilotMessage.created_at.desc(), CopilotMessage.id.desc())
            .limit(bounded_limit)
        )
        rows = list(reversed(self._db.execute(statement).scalars().all()))
        messages: list[dict[str, Any]] = []
        remaining = bounded_chars
        for row in rows:
            if remaining <= 0:
                break
            sanitized_content = _sanitize_planning_text(row.content or "")
            if len(sanitized_content) > remaining:
                sanitized_content = sanitized_content[:remaining].rstrip()
            remaining -= len(sanitized_content)
            messages.append(
                {
                    "id": str(row.id),
                    "role": row.role.value,
                    "content": sanitized_content,
                    "language": row.language,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "response_metadata": _safe_response_metadata(row.response_metadata_json),
                    "domains_used": _safe_string_list(row.domains_used_json),
                    "tools_used": _safe_tool_usage(row.tools_used_json),
                    "evidence_ids": _safe_evidence_ids(row.evidence_json),
                    "action_proposal": _safe_action_proposal(row.action_proposal_json),
                }
            )
        return messages

    def search_messages(
        self,
        *,
        seller_id: UUID,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[CopilotMessage], int]:
        normalized = f"%{query.strip()}%"
        statement = (
            select(CopilotMessage)
            .join(CopilotConversation, CopilotMessage.conversation_id == CopilotConversation.id)
            .where(
                CopilotMessage.seller_id == seller_id,
                CopilotConversation.seller_id == seller_id,
                CopilotConversation.status != CopilotConversationStatus.DELETED,
                CopilotMessage.content.ilike(normalized),
            )
        )
        total = self._db.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
        rows = self._db.execute(
            statement.order_by(CopilotMessage.created_at.desc(), CopilotMessage.id.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
        return rows, int(total or 0)

    def add_tool_call(
        self,
        *,
        seller_id: UUID,
        conversation_id: UUID,
        tool_name: str,
        started_at: datetime,
        message_id: UUID | None = None,
        tool_version: str = "v1",
        tool_args_json: dict[str, Any] | None = None,
        tool_result_summary_json: dict[str, Any] | list[Any] | None = None,
        status: CopilotToolCallStatus = CopilotToolCallStatus.REQUESTED,
        error_code: str | None = None,
        error_message: str | None = None,
        duration_ms: int | None = None,
        evidence_count: int | None = None,
        missing_data_count: int | None = None,
        completed_at: datetime | None = None,
    ) -> CopilotToolCall:
        tool_call = CopilotToolCall(
            seller_id=seller_id,
            conversation_id=conversation_id,
            message_id=message_id,
            tool_name=tool_name,
            tool_version=tool_version,
            tool_args_json=tool_args_json,
            tool_result_summary_json=tool_result_summary_json,
            status=status,
            error_code=error_code,
            error_message=error_message,
            duration_ms=duration_ms,
            evidence_count=evidence_count,
            missing_data_count=missing_data_count,
            started_at=started_at,
            completed_at=completed_at,
        )
        self._db.add(tool_call)
        self._db.commit()
        self._db.refresh(tool_call)
        return tool_call

    def add_action_proposal(
        self,
        *,
        seller_id: UUID,
        conversation_id: UUID,
        message_id: UUID,
        action_type: CopilotActionType,
        proposed_payload_json: dict[str, Any],
        product_id: UUID | None = None,
        safety_checks_json: dict[str, Any] | list[Any] | None = None,
        expected_impact_json: dict[str, Any] | None = None,
        evidence_json: dict[str, Any] | list[Any] | None = None,
        status: CopilotActionProposalStatus = CopilotActionProposalStatus.PROPOSED,
        requires_confirmation: bool = True,
        expires_at: datetime | None = None,
    ) -> CopilotActionProposal:
        if status == CopilotActionProposalStatus.EXECUTED:
            raise ValueError("Copilot action execution is not implemented for Phase 13 MVP.")

        proposal = CopilotActionProposal(
            seller_id=seller_id,
            conversation_id=conversation_id,
            message_id=message_id,
            product_id=product_id,
            action_type=action_type,
            proposed_payload_json=proposed_payload_json,
            safety_checks_json=safety_checks_json,
            expected_impact_json=expected_impact_json,
            evidence_json=evidence_json,
            status=status,
            requires_confirmation=requires_confirmation,
            expires_at=expires_at,
        )
        self._db.add(proposal)
        self._db.commit()
        self._db.refresh(proposal)
        return proposal

    def update_message_metadata(
        self,
        *,
        seller_id: UUID,
        message_id: UUID,
        action_proposal_json: dict[str, Any] | list[Any] | None = None,
        response_metadata_json: dict[str, Any] | None = None,
    ) -> None:
        values: dict[str, Any] = {}
        if action_proposal_json is not None:
            values["action_proposal_json"] = action_proposal_json
        if response_metadata_json is not None:
            values["response_metadata_json"] = response_metadata_json
        if not values:
            return
        self._db.execute(
            update(CopilotMessage)
            .where(CopilotMessage.seller_id == seller_id, CopilotMessage.id == message_id)
            .values(**values)
        )
        self._db.commit()

    def update_conversation_title(self, *, seller_id: UUID, conversation_id: UUID, title: str) -> None:
        self._db.execute(
            update(CopilotConversation)
            .where(CopilotConversation.seller_id == seller_id, CopilotConversation.id == conversation_id)
            .values(title=title[:255], updated_at=func.now())
        )
        self._db.commit()

    def list_action_proposals(
        self,
        *,
        seller_id: UUID,
        status: CopilotActionProposalStatus | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[CopilotActionProposal], int]:
        statement = select(CopilotActionProposal).where(CopilotActionProposal.seller_id == seller_id)
        if status is not None:
            statement = statement.where(CopilotActionProposal.status == status)
        total = self._db.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
        rows = self._db.execute(
            statement.order_by(CopilotActionProposal.created_at.desc(), CopilotActionProposal.id.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
        return rows, int(total or 0)

    def get_action_proposal(self, *, seller_id: UUID, proposal_id: UUID) -> CopilotActionProposal | None:
        return self._db.execute(
            select(CopilotActionProposal).where(
                CopilotActionProposal.seller_id == seller_id,
                CopilotActionProposal.id == proposal_id,
            )
        ).scalar_one_or_none()

    def save_action_proposal(self, proposal: CopilotActionProposal) -> CopilotActionProposal:
        self._db.add(proposal)
        self._db.commit()
        self._db.refresh(proposal)
        return proposal


def _sanitize_planning_text(value: str) -> str:
    text = STACK_TRACE_RE.sub("", value or "")
    text = SECRET_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    return "\n".join(line.rstrip() for line in text.splitlines() if line.strip())[:MAX_PLANNING_CHARACTER_LIMIT]


def _safe_response_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed = {
        "summary",
        "question_type",
        "intent",
        "planning_context",
        "last_successful_plan",
        "pending_clarification",
    }
    safe = {key: _safe_json(value[key]) for key in allowed if key in value}
    profile = value.get("language_profile")
    if isinstance(profile, dict):
        # Only the language choice is needed for planning; detector signals stay out of the prompt path.
        safe["language_profile"] = {
            key: str(profile[key])[:16]
            for key in ("input_language", "reply_language", "requested_reply_language", "reply_script", "source")
            if profile.get(key) is not None
        }
    return safe


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:120] for item in value if item is not None][:20]


def _safe_tool_usage(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    safe: list[dict[str, Any]] = []
    for item in value[:20]:
        if not isinstance(item, dict):
            continue
        safe.append(
            {
                "name": str(item.get("name") or item.get("tool_name") or "")[:120],
                "status": str(item.get("status") or "")[:40],
                "evidence_count": item.get("evidence_count"),
            }
        )
    return safe


def _safe_evidence_ids(value: Any) -> list[str]:
    if isinstance(value, dict):
        value = value.get("evidence") or value.get("evidence_ids") or []
    if not isinstance(value, list):
        return []
    ids: list[str] = []
    for item in value[:30]:
        if isinstance(item, dict):
            evidence_id = item.get("evidence_id")
        else:
            evidence_id = item
        if evidence_id:
            ids.append(str(evidence_id)[:160])
    return ids


def _safe_action_proposal(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "id": str(value.get("id") or "")[:80],
        "action_type": str(value.get("action_type") or "")[:80],
        "status": str(value.get("status") or "")[:80],
        "requires_confirmation": bool(value.get("requires_confirmation", True)),
    }


def _safe_json(value: Any) -> Any:
    if isinstance(value, dict):
        blocked = {"raw_tool_payload", "tool_result_summary_json", "embedding", "embedding_vector", "prompt", "system_prompt"}
        return {str(key): _safe_json(item) for key, item in value.items() if str(key) not in blocked}
    if isinstance(value, list):
        return [_safe_json(item) for item in value[:50]]
    if isinstance(value, str):
        return _sanitize_planning_text(value)[:1000]
    return value
