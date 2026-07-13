from __future__ import annotations

from datetime import date, datetime
import logging
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.copilot import (
    CopilotActionProposalStatus,
    CopilotActionType,
    CopilotConversationStatus,
    CopilotMessageRole,
    CopilotToolCallStatus,
)
from app.models.rag_memory import RagMemorySourceType
from app.services.copilot.query_constraints import BusinessDomainKey


COPILOT_QUESTION_MAX_LENGTH = 2000
COPILOT_TOP_K_MAX = 20
COPILOT_MAX_DATE_RANGE_DAYS = 366
COPILOT_LEGACY_SOURCE_TYPES_REMOVAL_TARGET = "2026-10-01"

logger = logging.getLogger(__name__)


class CopilotConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    language: str = Field(default="en", min_length=2, max_length=16)
    metadata_json: dict[str, Any] | None = None


class CopilotConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    seller_id: UUID
    user_id: UUID | None
    title: str | None
    last_message_preview: str | None = None
    status: CopilotConversationStatus
    language: str
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    message_count: int = 0
    last_confidence: str | None = None
    metadata_json: dict[str, Any] | None


class CopilotConversationListResponse(BaseModel):
    items: list[CopilotConversationResponse]
    total: int
    limit: int
    offset: int


class CopilotMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    seller_id: UUID
    conversation_id: UUID
    role: CopilotMessageRole
    content: str
    language: str
    answer_confidence: str | None
    model_id: str | None
    prompt_version: str | None
    token_usage_json: dict[str, Any] | None
    evidence_json: dict[str, Any] | list[Any] | None
    missing_context_json: dict[str, Any] | list[Any] | None
    missing_data_json: dict[str, Any] | list[Any] | None = None
    data_freshness_json: dict[str, Any] | list[Any] | None = None
    tools_used_json: dict[str, Any] | list[Any] | None = None
    domains_used_json: dict[str, Any] | list[Any] | None = None
    recommended_next_steps_json: dict[str, Any] | list[Any] | None = None
    action_proposal_json: dict[str, Any] | list[Any] | None = None
    response_metadata_json: dict[str, Any] | None = None
    answer: str | None = None
    summary: str | None = None
    confidence: str | None = None
    question_type: str | None = None
    domains_used: list[str] = Field(default_factory=list)
    tools_used: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    missing_data: list[dict[str, Any] | str] = Field(default_factory=list)
    data_freshness: list[dict[str, Any]] = Field(default_factory=list)
    recommended_next_steps: list[str] = Field(default_factory=list)
    action_proposal: dict[str, Any] | None = None
    created_at: datetime


class CopilotConversationDetailResponse(BaseModel):
    conversation: CopilotConversationResponse
    messages: list[CopilotMessageResponse]


class CopilotToolCallResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    seller_id: UUID
    conversation_id: UUID
    message_id: UUID | None
    tool_name: str
    tool_version: str
    tool_args_json: dict[str, Any] | None
    tool_result_summary_json: dict[str, Any] | list[Any] | None
    status: CopilotToolCallStatus
    error_code: str | None
    error_message: str | None
    duration_ms: int | None = None
    evidence_count: int | None = None
    missing_data_count: int | None = None
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime


class CopilotActionProposalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    seller_id: UUID
    conversation_id: UUID
    message_id: UUID
    product_id: UUID | None
    action_type: CopilotActionType
    proposed_payload_json: dict[str, Any]
    safety_checks_json: dict[str, Any] | list[Any] | None
    expected_impact_json: dict[str, Any] | None
    evidence_json: dict[str, Any] | list[Any] | None
    status: CopilotActionProposalStatus
    requires_confirmation: bool
    created_at: datetime
    approved_at: datetime | None
    rejected_at: datetime | None
    executed_at: datetime | None
    expires_at: datetime | None


class CopilotActionProposalListResponse(BaseModel):
    items: list[CopilotActionProposalResponse]
    total: int
    limit: int
    offset: int


class CopilotActionProposalTransitionResponse(BaseModel):
    proposal: CopilotActionProposalResponse
    message: str
    executed: bool = False


class CopilotAskRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "description": (
                "Copilot ask request. source_types is a transitional legacy field; "
                "new clients must use include_current_data, include_memory, and memory_source_types."
            )
        },
    )

    conversation_id: UUID | None = None
    question: str = Field(min_length=1, max_length=COPILOT_QUESTION_MAX_LENGTH)
    product_id: UUID | None = None
    language: str = Field(default="auto", pattern="^(auto|en|bn)$")
    from_date: date | None = None
    to_date: date | None = None
    domain_filters: list[BusinessDomainKey] | None = None
    include_current_data: bool = True
    include_memory: bool = True
    memory_source_types: list[RagMemorySourceType] | None = None
    top_k: int = Field(default=8, ge=1, le=COPILOT_TOP_K_MAX)
    debug: bool = False
    source_types: list[str] | None = Field(
        default=None,
        description=(
            "Deprecated compatibility field. Use memory_source_types for RAG source filters. "
            f"Removal target: {COPILOT_LEGACY_SOURCE_TYPES_REMOVAL_TARGET}."
        ),
    )
    include_tool_trace: bool = False

    @field_validator("question")
    @classmethod
    def _question_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value

    @field_validator("from_date", "to_date", mode="before")
    @classmethod
    def _parse_iso_date_or_datetime(cls, value: Any) -> date | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            candidate = value.strip()
            if not candidate:
                return None
            if candidate.endswith("Z"):
                candidate = f"{candidate[:-1]}+00:00"
            try:
                return date.fromisoformat(candidate)
            except ValueError:
                try:
                    return datetime.fromisoformat(candidate).date()
                except ValueError as exc:
                    raise ValueError("must be an ISO date or datetime") from exc
        return value

    @model_validator(mode="after")
    def _validate_request_contract(self) -> "CopilotAskRequest":
        if self.from_date and self.to_date:
            if self.from_date > self.to_date:
                raise ValueError("from_date must be on or before to_date")
            if (self.to_date - self.from_date).days > COPILOT_MAX_DATE_RANGE_DAYS:
                raise ValueError(f"date range must not exceed {COPILOT_MAX_DATE_RANGE_DAYS} days")

        if self.source_types:
            self._apply_legacy_source_types()
        return self

    def _apply_legacy_source_types(self) -> None:
        logger.warning(
            "copilot_source_types_deprecated removal_target=%s",
            COPILOT_LEGACY_SOURCE_TYPES_REMOVAL_TARGET,
        )
        raw_values = [str(item).strip() for item in self.source_types or [] if str(item).strip()]
        legacy_modes = {item.casefold() for item in raw_values}
        has_current_mode = bool(legacy_modes & {"database", "current"})
        has_memory_mode = "memory" in legacy_modes

        if legacy_modes and legacy_modes <= {"database", "current", "memory"}:
            if "include_current_data" not in self.model_fields_set:
                self.include_current_data = has_current_mode
            if "include_memory" not in self.model_fields_set:
                self.include_memory = has_memory_mode
            return

        if has_current_mode and "include_current_data" not in self.model_fields_set:
            self.include_current_data = True
        if has_memory_mode and "include_memory" not in self.model_fields_set:
            self.include_memory = True

        parsed: list[RagMemorySourceType] = []
        for item in raw_values:
            if item.casefold() in {"database", "current", "memory"}:
                continue
            try:
                parsed.append(RagMemorySourceType(item))
            except ValueError as exc:
                raise ValueError(
                    "source_types is deprecated; use memory_source_types with actual RAG memory source enum values"
                ) from exc
        if parsed and self.memory_source_types is None:
            self.memory_source_types = parsed
        if parsed and "include_memory" not in self.model_fields_set:
            self.include_memory = True


class CopilotToolUsedResponse(BaseModel):
    name: str
    status: str
    evidence_count: int | None = None
    error: dict[str, Any] | None = None


class CopilotApiAskResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    answer: str
    summary: str
    confidence: str
    language: str
    intent: str
    question_type: str | None = None
    domains_used: list[str] = Field(default_factory=list)
    tools_used: list[CopilotToolUsedResponse]
    evidence: list[dict[str, Any]]
    missing_data: list[dict[str, Any] | str]
    data_freshness: list[dict[str, Any]] = Field(default_factory=list)
    recommended_next_steps: list[str]
    action_proposal: dict[str, Any] | None = None
    debug: dict[str, Any] | None = None


class CopilotAskResponse(BaseModel):
    conversation: CopilotConversationResponse
    user_message: CopilotMessageResponse
    assistant_message: CopilotMessageResponse
    answer: str
    confidence: str
    language: str
    evidence: list[dict[str, Any]]
    evidence_ids: list[str]
    missing_context: list[str]
    recommended_next_steps: list[str]
    tool_calls: list[CopilotToolCallResponse] = Field(default_factory=list)
    action_proposals: list[CopilotActionProposalResponse] = Field(default_factory=list)


class CopilotSearchResponse(BaseModel):
    items: list[CopilotMessageResponse]
    total: int
    limit: int
    offset: int


class CopilotToolMetadataResponse(BaseModel):
    name: str
    domain: list[str] = Field(default_factory=list)
    description: str
    input_fields: list[str] = Field(default_factory=list)
    safety_level: str
    requires_confirmation: bool
    allowed_in_read_only_mode: bool


class CopilotToolsResponse(BaseModel):
    tools: list[CopilotToolMetadataResponse]


class CopilotErrorResponse(BaseModel):
    detail: str
    error_code: str
