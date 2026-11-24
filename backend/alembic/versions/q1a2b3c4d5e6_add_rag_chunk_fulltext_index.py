"""add full-text index on rag memory chunk text

Revision ID: q1a2b3c4d5e6
Revises: p0d1e2f3a4b5

Additive only: one GIN expression index used by RAG_FULLTEXT_KEYWORD_ENABLED keyword search.
The 'simple' config does no stemming, so SKUs, English words and Bengali-script tokens all match as typed.
Built CONCURRENTLY so writes to rag_memory_chunks are not blocked while it builds.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "q1a2b3c4d5e6"
down_revision: str | None = "p0d1e2f3a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_rag_memory_chunks_chunk_text_fts"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME} "
            "ON rag_memory_chunks USING gin (to_tsvector('simple', chunk_text))"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}")
