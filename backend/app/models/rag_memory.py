from __future__ import annotations

from datetime import datetime
from enum import Enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.vector_type import Vector

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.seller import Seller


class RagMemorySourceType(str, Enum):
    COMPETITOR_HISTORY = "COMPETITOR_HISTORY"
    PRICE_HISTORY = "PRICE_HISTORY"
    INVENTORY_HISTORY = "INVENTORY_HISTORY"
    INVENTORY_LIFECYCLE = "INVENTORY_LIFECYCLE"
    SALES_HISTORY = "SALES_HISTORY"
    SALES_REVENUE_SUMMARY = "SALES_REVENUE_SUMMARY"
    RECOMMENDATION = "RECOMMENDATION"
    RECOMMENDATION_HISTORY = "RECOMMENDATION_HISTORY"
    ALERT = "ALERT"
    ALERT_HISTORY = "ALERT_HISTORY"
    PROMOTION_PLAN = "PROMOTION_PLAN"
    PROMOTION_RESULT = "PROMOTION_RESULT"
    SELLER_PRICE_HISTORY = "SELLER_PRICE_HISTORY"
    DEAD_STOCK = "DEAD_STOCK"
    DEAD_STOCK_HISTORY = "DEAD_STOCK_HISTORY"
    SEO = "SEO"
    SEO_VISIBILITY_HISTORY = "SEO_VISIBILITY_HISTORY"
    PRICING_HISTORY = "PRICING_HISTORY"
    COPILOT_HISTORY = "COPILOT_HISTORY"
    ACTION_CENTER = "ACTION_CENTER"
    SUPPORT_LOG = "SUPPORT_LOG"
    PRODUCT_PROFILE = "PRODUCT_PROFILE"
    CUSTOMER_CONTEXT = "CUSTOMER_CONTEXT"


class RagMemorySensitivityLevel(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"


class RagMemoryVisibilityScope(str, Enum):
    SELLER = "SELLER"
    PRODUCT = "PRODUCT"


class RagMemoryEmbeddingStatus(str, Enum):
    PENDING = "PENDING"
    EMBEDDED = "EMBEDDED"
    FAILED = "FAILED"
    STALE = "STALE"


class RagAnswerStatus(str, Enum):
    SUCCESS = "SUCCESS"
    NO_CONTEXT = "NO_CONTEXT"
    FALLBACK = "FALLBACK"
    REJECTED = "REJECTED"


class RagMemoryDocument(Base):
    __tablename__ = "rag_memory_documents"
    __table_args__ = (
        UniqueConstraint(
            "seller_id",
            "source_table",
            "source_id",
            "source_version",
            "content_hash",
            name="uq_rag_memory_documents_source_hash",
        ),
        Index("ix_rag_memory_documents_seller_id", "seller_id"),
        Index("ix_rag_memory_documents_product_id", "product_id"),
        Index("ix_rag_memory_documents_source_type", "source_type"),
        Index("ix_rag_memory_documents_source", "source_table", "source_id"),
        Index("ix_rag_memory_documents_event_time", "event_time"),
        Index("ix_rag_memory_documents_content_hash", "content_hash"),
        Index("ix_rag_memory_documents_embedding_status", "embedding_status"),
        Index("ix_rag_memory_documents_seller_deleted", "seller_id", "deleted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sellers.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=True,
    )
    source_type: Mapped[RagMemorySourceType] = mapped_column(
        SAEnum(RagMemorySourceType, name="rag_memory_source_type"),
        nullable=False,
    )
    source_table: Mapped[str] = mapped_column(String(120), nullable=False)
    source_id: Mapped[str] = mapped_column(String(120), nullable=False)
    source_version: Mapped[str] = mapped_column(String(80), nullable=False, default="v1")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    sensitivity_level: Mapped[RagMemorySensitivityLevel] = mapped_column(
        SAEnum(RagMemorySensitivityLevel, name="rag_memory_sensitivity_level"),
        nullable=False,
        default=RagMemorySensitivityLevel.INTERNAL,
    )
    visibility_scope: Mapped[RagMemoryVisibilityScope] = mapped_column(
        SAEnum(RagMemoryVisibilityScope, name="rag_memory_visibility_scope"),
        nullable=False,
        default=RagMemoryVisibilityScope.SELLER,
    )
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    chunking_version: Mapped[str] = mapped_column(String(80), nullable=False, default="v1")
    embedding_status: Mapped[RagMemoryEmbeddingStatus] = mapped_column(
        SAEnum(RagMemoryEmbeddingStatus, name="rag_memory_embedding_status"),
        nullable=False,
        default=RagMemoryEmbeddingStatus.PENDING,
    )

    seller: Mapped["Seller"] = relationship(back_populates="rag_memory_documents")
    product: Mapped["Product | None"] = relationship(back_populates="rag_memory_documents")
    chunks: Mapped[list["RagMemoryChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )


class RagMemoryChunk(Base):
    __tablename__ = "rag_memory_chunks"
    __table_args__ = (
        UniqueConstraint(
            "memory_document_id",
            "chunk_index",
            "content_hash",
            name="uq_rag_memory_chunks_document_index_hash",
        ),
        Index("ix_rag_memory_chunks_seller_id", "seller_id"),
        Index("ix_rag_memory_chunks_product_id", "product_id"),
        Index("ix_rag_memory_chunks_source_type", "source_type"),
        Index("ix_rag_memory_chunks_event_time", "event_time"),
        Index("ix_rag_memory_chunks_content_hash", "content_hash"),
        Index("ix_rag_memory_chunks_document_id", "memory_document_id"),
        Index("ix_rag_memory_chunks_seller_deleted", "seller_id", "deleted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sellers.id", ondelete="CASCADE"),
        nullable=False,
    )
    memory_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rag_memory_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=True,
    )
    source_type: Mapped[RagMemorySourceType] = mapped_column(
        SAEnum(RagMemorySourceType, name="rag_memory_source_type"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    embedding_status: Mapped[RagMemoryEmbeddingStatus] = mapped_column(
        SAEnum(RagMemoryEmbeddingStatus, name="rag_memory_embedding_status"),
        nullable=False,
        default=RagMemoryEmbeddingStatus.PENDING,
    )
    embedding_failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    seller: Mapped["Seller"] = relationship(back_populates="rag_memory_chunks")
    product: Mapped["Product | None"] = relationship(back_populates="rag_memory_chunks")
    document: Mapped["RagMemoryDocument"] = relationship(back_populates="chunks")


class RagQueryLog(Base):
    __tablename__ = "rag_query_logs"
    __table_args__ = (
        Index("ix_rag_query_logs_seller_created", "seller_id", "created_at"),
        Index("ix_rag_query_logs_user_id", "user_id"),
        Index("ix_rag_query_logs_answer_status", "answer_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sellers.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_question: Mapped[str] = mapped_column(Text, nullable=False)
    retrieval_confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    source_types_used: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    evidence_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    answer_status: Mapped[RagAnswerStatus] = mapped_column(
        SAEnum(RagAnswerStatus, name="rag_answer_status"),
        nullable=False,
    )
    model_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
