"""add rag memory storage

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-07-05 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "e4f5a6b7c8d9"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


SOURCE_TYPE_VALUES = (
    "COMPETITOR_HISTORY",
    "PRICE_HISTORY",
    "INVENTORY_HISTORY",
    "SALES_HISTORY",
    "RECOMMENDATION",
    "ALERT",
    "PROMOTION_RESULT",
    "DEAD_STOCK",
    "SEO",
    "ACTION_CENTER",
    "SUPPORT_LOG",
    "PRODUCT_PROFILE",
    "CUSTOMER_CONTEXT",
)
SENSITIVITY_VALUES = ("PUBLIC", "INTERNAL", "CONFIDENTIAL")
VISIBILITY_VALUES = ("SELLER", "PRODUCT")
EMBEDDING_STATUS_VALUES = ("PENDING", "EMBEDDED", "FAILED", "STALE")
ANSWER_STATUS_VALUES = ("SUCCESS", "NO_CONTEXT", "FALLBACK", "REJECTED")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _ensure_vector_extension(bind)
    vector_type = _vector_type_sql(bind)

    enum_names = {enum["name"] for enum in inspector.get_enums()}
    if "rag_memory_source_type" not in enum_names:
        postgresql.ENUM(*SOURCE_TYPE_VALUES, name="rag_memory_source_type").create(bind, checkfirst=True)
    if "rag_memory_sensitivity_level" not in enum_names:
        postgresql.ENUM(*SENSITIVITY_VALUES, name="rag_memory_sensitivity_level").create(bind, checkfirst=True)
    if "rag_memory_visibility_scope" not in enum_names:
        postgresql.ENUM(*VISIBILITY_VALUES, name="rag_memory_visibility_scope").create(bind, checkfirst=True)
    if "rag_memory_embedding_status" not in enum_names:
        postgresql.ENUM(*EMBEDDING_STATUS_VALUES, name="rag_memory_embedding_status").create(bind, checkfirst=True)
    if "rag_answer_status" not in enum_names:
        postgresql.ENUM(*ANSWER_STATUS_VALUES, name="rag_answer_status").create(bind, checkfirst=True)

    table_names = set(inspector.get_table_names())
    if "rag_memory_documents" not in table_names:
        op.create_table(
            "rag_memory_documents",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "source_type",
                postgresql.ENUM(*SOURCE_TYPE_VALUES, name="rag_memory_source_type", create_type=False),
                nullable=False,
            ),
            sa.Column("source_table", sa.String(length=120), nullable=False),
            sa.Column("source_id", sa.String(length=120), nullable=False),
            sa.Column("source_version", sa.String(length=80), nullable=False, server_default="v1"),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("summary_text", sa.Text(), nullable=True),
            sa.Column("content_text", sa.Text(), nullable=False),
            sa.Column("language", sa.String(length=16), nullable=False, server_default="en"),
            sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
            sa.Column(
                "sensitivity_level",
                postgresql.ENUM(*SENSITIVITY_VALUES, name="rag_memory_sensitivity_level", create_type=False),
                nullable=False,
                server_default="INTERNAL",
            ),
            sa.Column(
                "visibility_scope",
                postgresql.ENUM(*VISIBILITY_VALUES, name="rag_memory_visibility_scope", create_type=False),
                nullable=False,
                server_default="SELLER",
            ),
            sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("chunking_version", sa.String(length=80), nullable=False, server_default="v1"),
            sa.Column(
                "embedding_status",
                postgresql.ENUM(*EMBEDDING_STATUS_VALUES, name="rag_memory_embedding_status", create_type=False),
                nullable=False,
                server_default="PENDING",
            ),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "seller_id",
                "source_table",
                "source_id",
                "source_version",
                "content_hash",
                name="uq_rag_memory_documents_source_hash",
            ),
        )
        op.create_index("ix_rag_memory_documents_seller_id", "rag_memory_documents", ["seller_id"])
        op.create_index("ix_rag_memory_documents_product_id", "rag_memory_documents", ["product_id"])
        op.create_index("ix_rag_memory_documents_source_type", "rag_memory_documents", ["source_type"])
        op.create_index("ix_rag_memory_documents_source", "rag_memory_documents", ["source_table", "source_id"])
        op.create_index("ix_rag_memory_documents_event_time", "rag_memory_documents", ["event_time"])
        op.create_index("ix_rag_memory_documents_content_hash", "rag_memory_documents", ["content_hash"])
        op.create_index("ix_rag_memory_documents_embedding_status", "rag_memory_documents", ["embedding_status"])
        op.create_index("ix_rag_memory_documents_seller_deleted", "rag_memory_documents", ["seller_id", "deleted_at"])

    table_names = set(sa.inspect(bind).get_table_names())
    if "rag_memory_chunks" not in table_names:
        op.create_table(
            "rag_memory_chunks",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("memory_document_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "source_type",
                postgresql.ENUM(*SOURCE_TYPE_VALUES, name="rag_memory_source_type", create_type=False),
                nullable=False,
            ),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("chunk_text", sa.Text(), nullable=False),
            sa.Column("token_estimate", sa.Integer(), nullable=False),
            sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
            sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("embedding_model", sa.String(length=160), nullable=True),
            sa.Column("embedding_dimension", sa.Integer(), nullable=True),
            sa.Column("embedding_version", sa.String(length=80), nullable=True),
            sa.Column(
                "embedding_status",
                postgresql.ENUM(*EMBEDDING_STATUS_VALUES, name="rag_memory_embedding_status", create_type=False),
                nullable=False,
                server_default="PENDING",
            ),
            sa.Column("embedding_failure_reason", sa.String(length=255), nullable=True),
            sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["memory_document_id"], ["rag_memory_documents.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "memory_document_id",
                "chunk_index",
                "content_hash",
                name="uq_rag_memory_chunks_document_index_hash",
            ),
            sa.CheckConstraint("chunk_index >= 0", name="ck_rag_memory_chunks_chunk_index_nonnegative"),
            sa.CheckConstraint("token_estimate >= 0", name="ck_rag_memory_chunks_token_estimate_nonnegative"),
            sa.CheckConstraint("embedding_dimension IS NULL OR embedding_dimension > 0", name="ck_rag_memory_chunks_embedding_dimension_positive"),
        )
        op.execute(
            sa.text(
                f"ALTER TABLE rag_memory_chunks "
                f"ADD COLUMN embedding {vector_type} NULL"
            )
        )
        op.create_check_constraint(
            "ck_rag_memory_chunks_embedding_dimension_presence",
            "rag_memory_chunks",
            "(embedding IS NULL AND embedding_dimension IS NULL) OR "
            "(embedding IS NOT NULL AND embedding_dimension IS NOT NULL)",
        )
        op.create_index("ix_rag_memory_chunks_seller_id", "rag_memory_chunks", ["seller_id"])
        op.create_index("ix_rag_memory_chunks_product_id", "rag_memory_chunks", ["product_id"])
        op.create_index("ix_rag_memory_chunks_source_type", "rag_memory_chunks", ["source_type"])
        op.create_index("ix_rag_memory_chunks_event_time", "rag_memory_chunks", ["event_time"])
        op.create_index("ix_rag_memory_chunks_content_hash", "rag_memory_chunks", ["content_hash"])
        op.create_index("ix_rag_memory_chunks_document_id", "rag_memory_chunks", ["memory_document_id"])
        op.create_index("ix_rag_memory_chunks_embedding_status", "rag_memory_chunks", ["embedding_status"])
        op.create_index("ix_rag_memory_chunks_seller_deleted", "rag_memory_chunks", ["seller_id", "deleted_at"])
        _try_create_vector_index(bind, vector_type)

    table_names = set(sa.inspect(bind).get_table_names())
    if "rag_query_logs" not in table_names:
        op.create_table(
            "rag_query_logs",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("question", sa.Text(), nullable=False),
            sa.Column("normalized_question", sa.Text(), nullable=False),
            sa.Column("retrieval_confidence", sa.String(length=20), nullable=False),
            sa.Column("source_types_used", postgresql.JSONB(), nullable=True),
            sa.Column("evidence_ids", postgresql.JSONB(), nullable=True),
            sa.Column(
                "answer_status",
                postgresql.ENUM(*ANSWER_STATUS_VALUES, name="rag_answer_status", create_type=False),
                nullable=False,
            ),
            sa.Column("model_id", sa.String(length=160), nullable=True),
            sa.Column("prompt_version", sa.String(length=80), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_rag_query_logs_seller_created", "rag_query_logs", ["seller_id", "created_at"])
        op.create_index("ix_rag_query_logs_user_id", "rag_query_logs", ["user_id"])
        op.create_index("ix_rag_query_logs_answer_status", "rag_query_logs", ["answer_status"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "rag_query_logs" in table_names:
        op.drop_index("ix_rag_query_logs_answer_status", table_name="rag_query_logs")
        op.drop_index("ix_rag_query_logs_user_id", table_name="rag_query_logs")
        op.drop_index("ix_rag_query_logs_seller_created", table_name="rag_query_logs")
        op.drop_table("rag_query_logs")

    if "rag_memory_chunks" in table_names:
        op.execute("DROP INDEX IF EXISTS ix_rag_memory_chunks_embedding_hnsw")
        op.execute("DROP INDEX IF EXISTS ix_rag_memory_chunks_embedding_status")
        op.drop_index("ix_rag_memory_chunks_seller_deleted", table_name="rag_memory_chunks")
        op.drop_index("ix_rag_memory_chunks_document_id", table_name="rag_memory_chunks")
        op.drop_index("ix_rag_memory_chunks_content_hash", table_name="rag_memory_chunks")
        op.drop_index("ix_rag_memory_chunks_event_time", table_name="rag_memory_chunks")
        op.drop_index("ix_rag_memory_chunks_source_type", table_name="rag_memory_chunks")
        op.drop_index("ix_rag_memory_chunks_product_id", table_name="rag_memory_chunks")
        op.drop_index("ix_rag_memory_chunks_seller_id", table_name="rag_memory_chunks")
        op.drop_table("rag_memory_chunks")

    inspector = sa.inspect(bind)
    if "rag_memory_documents" in set(inspector.get_table_names()):
        op.drop_index("ix_rag_memory_documents_seller_deleted", table_name="rag_memory_documents")
        op.drop_index("ix_rag_memory_documents_embedding_status", table_name="rag_memory_documents")
        op.drop_index("ix_rag_memory_documents_content_hash", table_name="rag_memory_documents")
        op.drop_index("ix_rag_memory_documents_event_time", table_name="rag_memory_documents")
        op.drop_index("ix_rag_memory_documents_source", table_name="rag_memory_documents")
        op.drop_index("ix_rag_memory_documents_source_type", table_name="rag_memory_documents")
        op.drop_index("ix_rag_memory_documents_product_id", table_name="rag_memory_documents")
        op.drop_index("ix_rag_memory_documents_seller_id", table_name="rag_memory_documents")
        op.drop_table("rag_memory_documents")

    enum_names = {enum["name"] for enum in sa.inspect(bind).get_enums()}
    for enum_name in (
        "rag_memory_embedding_status",
        "rag_answer_status",
        "rag_memory_visibility_scope",
        "rag_memory_sensitivity_level",
        "rag_memory_source_type",
    ):
        if enum_name in enum_names:
            postgresql.ENUM(name=enum_name).drop(bind, checkfirst=True)


def _ensure_vector_extension(bind) -> None:
    bind.execute(
        sa.text(
            """
            DO $$
            BEGIN
                CREATE SCHEMA IF NOT EXISTS extensions;
                CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
            EXCEPTION
                WHEN insufficient_privilege OR invalid_schema_name THEN
                    CREATE EXTENSION IF NOT EXISTS vector;
            END
            $$;
            """
        )
    )


def _vector_type_sql(bind) -> str:
    row = bind.execute(
        sa.text(
            """
            SELECT n.nspname AS schema_name
            FROM pg_type t
            JOIN pg_namespace n ON n.oid = t.typnamespace
            WHERE t.typname = 'vector'
            ORDER BY CASE WHEN n.nspname = 'extensions' THEN 0 WHEN n.nspname = 'public' THEN 1 ELSE 2 END
            LIMIT 1
            """
        )
    ).first()
    if row is None:
        raise RuntimeError(
            "pgvector extension is required before creating RAG memory storage. "
            "Install pgvector locally or enable the vector extension in Supabase."
        )
    schema_name = row.schema_name
    return f"{schema_name}.vector"


def _try_create_vector_index(bind, vector_type: str) -> None:
    del vector_type
    bind.execute(
        sa.text(
            """
            DO $$
            BEGIN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_rag_memory_chunks_embedding_hnsw
                    ON rag_memory_chunks
                    USING hnsw (embedding vector_cosine_ops)
                    WHERE deleted_at IS NULL AND embedding IS NOT NULL';
            EXCEPTION
                WHEN undefined_object OR feature_not_supported OR invalid_parameter_value THEN
                    RAISE NOTICE 'Skipping rag_memory_chunks HNSW vector index; exact vector search remains available.';
            END
            $$;
            """
        )
    )
