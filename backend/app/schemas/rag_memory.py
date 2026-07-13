from __future__ import annotations

from datetime import datetime
from uuid import UUID
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import settings
from app.models.rag_memory import (
    RagMemoryEmbeddingStatus,
    RagMemorySensitivityLevel,
    RagMemorySourceType,
    RagMemoryVisibilityScope,
)


class RagMemoryDocumentCreate(BaseModel):
    seller_id: UUID
    product_id: UUID | None = None
    source_type: RagMemorySourceType
    source_table: str = Field(min_length=1, max_length=120)
    source_id: str = Field(min_length=1, max_length=120)
    source_version: str = Field(default="v1", min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=255)
    summary_text: str | None = None
    content_text: str = Field(min_length=1)
    language: str = Field(default="en", min_length=2, max_length=16)
    metadata_json: dict[str, Any] | None = None
    sensitivity_level: RagMemorySensitivityLevel = RagMemorySensitivityLevel.INTERNAL
    visibility_scope: RagMemoryVisibilityScope = RagMemoryVisibilityScope.SELLER
    event_time: datetime | None = None
    content_hash: str = Field(min_length=64, max_length=64)
    chunking_version: str = Field(default="v1", min_length=1, max_length=80)
    embedding_status: RagMemoryEmbeddingStatus = RagMemoryEmbeddingStatus.PENDING


class RagMemoryChunkCreate(BaseModel):
    seller_id: UUID
    memory_document_id: UUID
    product_id: UUID | None = None
    source_type: RagMemorySourceType
    chunk_index: int = Field(ge=0)
    chunk_text: str = Field(min_length=1)
    token_estimate: int = Field(ge=0)
    metadata_json: dict[str, Any] | None = None
    event_time: datetime | None = None
    content_hash: str = Field(min_length=64, max_length=64)
    embedding: list[float] | None = None
    embedding_model: str | None = Field(default=None, max_length=160)
    embedding_dimension: int | None = Field(default=None, ge=1)
    embedding_version: str | None = Field(default=None, max_length=80)
    embedded_at: datetime | None = None

    embedding_status: RagMemoryEmbeddingStatus = RagMemoryEmbeddingStatus.PENDING
    embedding_failure_reason: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_embedding_dimension(self) -> "RagMemoryChunkCreate":
        if self.embedding is None:
            if self.embedding_dimension is not None:
                raise ValueError("embedding_dimension must be empty when embedding is empty")
            return self
        if self.embedding_dimension is None:
            raise ValueError("embedding_dimension is required when embedding is present")
        if len(self.embedding) != self.embedding_dimension:
            raise ValueError(
                f"embedding_dimension must match generated vector length; got dimension {self.embedding_dimension} and vector length {len(self.embedding)}"
            )
        return self


class RagMemoryDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    seller_id: UUID
    product_id: UUID | None
    source_type: RagMemorySourceType
    source_table: str
    source_id: str
    source_version: str
    title: str
    summary_text: str | None
    content_text: str
    language: str
    metadata_json: dict[str, Any] | None
    sensitivity_level: RagMemorySensitivityLevel
    visibility_scope: RagMemoryVisibilityScope
    event_time: datetime | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    content_hash: str
    chunking_version: str
    embedding_status: RagMemoryEmbeddingStatus


class RagMemoryChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    seller_id: UUID
    memory_document_id: UUID
    product_id: UUID | None
    source_type: RagMemorySourceType
    chunk_index: int
    chunk_text: str
    token_estimate: int
    metadata_json: dict[str, Any] | None
    event_time: datetime | None
    content_hash: str
    embedding_model: str | None
    embedding_dimension: int | None
    embedding_version: str | None
    embedding_status: RagMemoryEmbeddingStatus
    embedding_failure_reason: str | None
    embedded_at: datetime | None
    created_at: datetime
    deleted_at: datetime | None


class RagMemorySearchResult(BaseModel):
    chunk: RagMemoryChunkResponse
    distance: float | None = None


class RagAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    product_id: UUID | None = None
    source_types: list[RagMemorySourceType] | None = None
    from_event_time: datetime | None = None
    to_event_time: datetime | None = None
    top_k: int = Field(default=settings.rag_retrieval_top_k, ge=1, le=20)
    min_similarity: float = Field(default=settings.rag_min_similarity, ge=0.0, le=1.0)
    include_stale: bool = False


class RagAnswerEvidenceResponse(BaseModel):
    evidence_id: str
    source_type: str
    source_title: str
    event_time: str | None = None


class RagAskResponse(BaseModel):
    answer: str
    summary: str
    evidence: list[RagAnswerEvidenceResponse]
    confidence: str
    missing_context: list[str]
    recommended_next_steps: list[str]
    language: str
    disclaimer: str
    answer_status: str
    model_id: str | None
    prompt_version: str
    evidence_ids: list[str]


class RagErrorResponse(BaseModel):
    success: bool = False
    detail: str
    error_code: str | None = None
