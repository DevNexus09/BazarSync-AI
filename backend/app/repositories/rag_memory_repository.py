from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import bindparam, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.vector_type import _to_pgvector_literal
from app.models.rag_memory import (
    RagMemoryChunk,
    RagMemoryDocument,
    RagMemoryEmbeddingStatus,
    RagMemorySourceType,
)
from app.schemas.rag_memory import RagMemoryChunkCreate, RagMemoryDocumentCreate


class RagMemoryDimensionError(ValueError):
    """Raised before insertion when an embedding has the wrong dimension."""


class RagMemoryRepository:
    def __init__(self, db: Session, *, embedding_dimension: int | None = None) -> None:
        self._db = db
        self.embedding_dimension = embedding_dimension

    def create_memory_document(self, payload: RagMemoryDocumentCreate) -> tuple[RagMemoryDocument, bool]:
        existing = self.get_by_source(
            seller_id=payload.seller_id,
            source_table=payload.source_table,
            source_id=payload.source_id,
            source_version=payload.source_version,
            content_hash=payload.content_hash,
            include_deleted=True,
        )
        if existing:
            return existing, False

        document = RagMemoryDocument(**payload.model_dump())
        self._db.add(document)
        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            existing = self.get_by_source(
                seller_id=payload.seller_id,
                source_table=payload.source_table,
                source_id=payload.source_id,
                source_version=payload.source_version,
                content_hash=payload.content_hash,
                include_deleted=True,
            )
            if existing:
                return existing, False
            raise
        self._db.refresh(document)
        return document, True

    def create_chunks(self, payloads: Sequence[RagMemoryChunkCreate]) -> list[RagMemoryChunk]:
        chunks: list[RagMemoryChunk] = []
        for payload in payloads:
            self._validate_payload_dimension(payload)
            chunk = RagMemoryChunk(**payload.model_dump())
            self._db.add(chunk)
            chunks.append(chunk)
        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            raise
        for chunk in chunks:
            self._db.refresh(chunk)
        return chunks

    def count_chunks_for_document(self, document_id: UUID) -> int:
        statement = select(func.count()).select_from(RagMemoryChunk).where(
            RagMemoryChunk.memory_document_id == document_id,
            RagMemoryChunk.deleted_at.is_(None),
        )
        return int(self._db.execute(statement).scalar_one() or 0)

    def get_by_source(
        self,
        *,
        seller_id: UUID,
        source_table: str,
        source_id: str,
        source_version: str | None = None,
        content_hash: str | None = None,
        include_deleted: bool = False,
    ) -> RagMemoryDocument | None:
        statement = select(RagMemoryDocument).where(
            RagMemoryDocument.seller_id == seller_id,
            RagMemoryDocument.source_table == source_table,
            RagMemoryDocument.source_id == source_id,
        )
        if source_version is not None:
            statement = statement.where(RagMemoryDocument.source_version == source_version)
        if content_hash is not None:
            statement = statement.where(RagMemoryDocument.content_hash == content_hash)
        if not include_deleted:
            statement = statement.where(RagMemoryDocument.deleted_at.is_(None))
        return self._db.execute(
            statement.order_by(RagMemoryDocument.event_time.desc().nullslast(), RagMemoryDocument.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    def get_documents_by_ids(self, *, seller_id: UUID, document_ids: Sequence[UUID]) -> dict[UUID, RagMemoryDocument]:
        if not document_ids:
            return {}
        rows = self._db.execute(
            select(RagMemoryDocument).where(
                RagMemoryDocument.seller_id == seller_id,
                RagMemoryDocument.id.in_(set(document_ids)),
                RagMemoryDocument.deleted_at.is_(None),
            )
        ).scalars().all()
        return {row.id: row for row in rows}

    def mark_stale(
        self,
        *,
        seller_id: UUID,
        source_table: str,
        source_id: str,
    ) -> int:
        result = self._db.execute(
            update(RagMemoryDocument)
            .where(
                RagMemoryDocument.seller_id == seller_id,
                RagMemoryDocument.source_table == source_table,
                RagMemoryDocument.source_id == source_id,
                RagMemoryDocument.deleted_at.is_(None),
            )
            .values(embedding_status=RagMemoryEmbeddingStatus.STALE, updated_at=func.now())
        )
        self._db.commit()
        return int(result.rowcount or 0)

    def soft_delete_by_source(
        self,
        *,
        seller_id: UUID,
        source_table: str,
        source_id: str,
        deleted_at: datetime | None = None,
    ) -> int:
        timestamp = deleted_at or datetime.now(timezone.utc)
        document_ids = [
            row[0]
            for row in self._db.execute(
                select(RagMemoryDocument.id).where(
                    RagMemoryDocument.seller_id == seller_id,
                    RagMemoryDocument.source_table == source_table,
                    RagMemoryDocument.source_id == source_id,
                    RagMemoryDocument.deleted_at.is_(None),
                )
            ).all()
        ]
        if not document_ids:
            return 0
        chunk_result = self._db.execute(
            update(RagMemoryChunk)
            .where(
                RagMemoryChunk.seller_id == seller_id,
                RagMemoryChunk.memory_document_id.in_(document_ids),
                RagMemoryChunk.deleted_at.is_(None),
            )
            .values(deleted_at=timestamp)
        )
        del chunk_result
        doc_result = self._db.execute(
            update(RagMemoryDocument)
            .where(RagMemoryDocument.id.in_(document_ids))
            .values(deleted_at=timestamp, updated_at=func.now())
        )
        self._db.commit()
        return int(doc_result.rowcount or 0)

    def find_unembedded_chunks(
        self,
        *,
        seller_id: UUID | None = None,
        source_type: RagMemorySourceType | None = None,
        limit: int = 100,
    ) -> list[RagMemoryChunk]:
        statement = (
            select(RagMemoryChunk)
            .join(RagMemoryDocument, RagMemoryChunk.memory_document_id == RagMemoryDocument.id)
            .where(
                RagMemoryChunk.deleted_at.is_(None),
                RagMemoryDocument.deleted_at.is_(None),
                RagMemoryChunk.embedding_status.in_(
                    [RagMemoryEmbeddingStatus.PENDING, RagMemoryEmbeddingStatus.STALE, RagMemoryEmbeddingStatus.FAILED]
                ),
                RagMemoryDocument.embedding_status.in_(
                    [RagMemoryEmbeddingStatus.PENDING, RagMemoryEmbeddingStatus.STALE, RagMemoryEmbeddingStatus.FAILED]
                ),
            )
            .order_by(RagMemoryChunk.created_at.asc(), RagMemoryChunk.id.asc())
            .limit(limit)
        )
        if seller_id is not None:
            statement = statement.where(RagMemoryChunk.seller_id == seller_id)
        if source_type is not None:
            statement = statement.where(RagMemoryChunk.source_type == source_type)
        return self._db.execute(statement).scalars().all()

    def vector_search(
        self,
        *,
        seller_id: UUID,
        query_embedding: Sequence[float],
        product_id: UUID | None = None,
        source_types: Sequence[RagMemorySourceType] | None = None,
        from_event_time: datetime | None = None,
        to_event_time: datetime | None = None,
        include_stale: bool = False,
        limit: int = 10,
    ) -> list[tuple[RagMemoryChunk, float]]:
        self._validate_vector(query_embedding)
        source_values = [source_type.value for source_type in source_types or []]

        # "<=>" (cosine) matches the vector_cosine_ops HNSW index; "<->" (L2) is the legacy default.
        operator = "<=>" if settings.rag_cosine_distance_enabled else "<->"
        query = f"""
            SELECT c.id, c.embedding {operator} CAST(:query_embedding AS vector) AS distance
            FROM rag_memory_chunks c
            JOIN rag_memory_documents d ON d.id = c.memory_document_id
            WHERE c.seller_id = :seller_id
              AND c.deleted_at IS NULL
              AND d.deleted_at IS NULL
              AND c.embedding IS NOT NULL
              AND c.embedding_status != 'FAILED'
              AND d.embedding_status != 'FAILED'
              AND (:include_stale = true OR c.embedding_status = 'EMBEDDED')
              AND (:include_stale = true OR d.embedding_status = 'EMBEDDED')
              AND (:product_id IS NULL OR c.product_id = :product_id)
              AND (:from_event_time IS NULL OR c.event_time >= :from_event_time)
              AND (:to_event_time IS NULL OR c.event_time <= :to_event_time)
              AND (:source_types_disabled = true OR c.source_type::text IN :source_types)
            ORDER BY c.embedding {operator} CAST(:query_embedding AS vector), c.event_time DESC NULLS LAST, c.created_at DESC
            LIMIT :limit
        """
        statement = text(query).bindparams(bindparam("source_types", expanding=True))
        params = {
            "seller_id": seller_id,
            "product_id": product_id,
            "from_event_time": from_event_time,
            "to_event_time": to_event_time,
            "include_stale": include_stale,
            "source_types_disabled": not bool(source_values),
            "query_embedding": _to_pgvector_literal(query_embedding),
            "limit": limit,
            "source_types": source_values or ["__none__"],
        }
        rows = self._db.execute(
            statement,
            params,
        ).all()
        if not rows:
            return []
        chunk_ids = [row.id for row in rows]
        chunks = {
            chunk.id: chunk
            for chunk in self._db.execute(
                select(RagMemoryChunk).where(
                    RagMemoryChunk.seller_id == seller_id,
                    RagMemoryChunk.id.in_(chunk_ids),
                    RagMemoryChunk.deleted_at.is_(None),
                )
            ).scalars().all()
        }
        return [(chunks[row.id], float(row.distance)) for row in rows if row.id in chunks]

    def keyword_search(
        self,
        *,
        seller_id: UUID,
        keywords: Sequence[str],
        product_id: UUID | None = None,
        source_types: Sequence[RagMemorySourceType] | None = None,
        from_event_time: datetime | None = None,
        to_event_time: datetime | None = None,
        include_stale: bool = False,
        limit: int = 50,
    ) -> list[RagMemoryChunk]:
        terms = [term.strip() for term in keywords if term and term.strip()]
        if not terms:
            return []
        statement = (
            select(RagMemoryChunk)
            .join(RagMemoryDocument, RagMemoryChunk.memory_document_id == RagMemoryDocument.id)
            .where(
                RagMemoryChunk.seller_id == seller_id,
                RagMemoryChunk.deleted_at.is_(None),
                RagMemoryDocument.deleted_at.is_(None),
                RagMemoryChunk.embedding_status != RagMemoryEmbeddingStatus.FAILED,
                RagMemoryDocument.embedding_status != RagMemoryEmbeddingStatus.FAILED,
            )
        )
        if not include_stale:
            statement = statement.where(
                RagMemoryChunk.embedding_status == RagMemoryEmbeddingStatus.EMBEDDED,
                RagMemoryDocument.embedding_status == RagMemoryEmbeddingStatus.EMBEDDED,
            )
        if product_id is not None:
            statement = statement.where(RagMemoryChunk.product_id == product_id)
        if source_types:
            statement = statement.where(RagMemoryChunk.source_type.in_(source_types))
        if from_event_time is not None:
            statement = statement.where(RagMemoryChunk.event_time >= from_event_time)
        if to_event_time is not None:
            statement = statement.where(RagMemoryChunk.event_time <= to_event_time)

        predicates = []
        for term in terms:
            pattern = f"%{term}%"
            predicates.append(RagMemoryChunk.chunk_text.ilike(pattern))
        statement = statement.where(or_(*predicates)).order_by(
            RagMemoryChunk.event_time.desc().nullslast(),
            RagMemoryChunk.created_at.desc(),
            RagMemoryChunk.id.desc(),
        )
        return self._db.execute(statement.limit(limit)).scalars().all()

    def count_searchable_chunks(
        self,
        *,
        seller_id: UUID,
        source_type: RagMemorySourceType | None = None,
    ) -> int:
        statement = select(func.count()).select_from(RagMemoryChunk).where(
            RagMemoryChunk.seller_id == seller_id,
            RagMemoryChunk.deleted_at.is_(None),
            RagMemoryChunk.embedding.is_not(None),
            RagMemoryChunk.embedding_status == RagMemoryEmbeddingStatus.EMBEDDED,
        )
        statement = statement.join(RagMemoryDocument, RagMemoryChunk.memory_document_id == RagMemoryDocument.id).where(
            RagMemoryDocument.deleted_at.is_(None)
        )
        if source_type is not None:
            statement = statement.where(RagMemoryChunk.source_type == source_type)
        return int(self._db.execute(statement).scalar_one() or 0)

    def hybrid_metadata_filter_search(
        self,
        *,
        seller_id: UUID,
        product_id: UUID | None = None,
        source_types: Sequence[RagMemorySourceType] | None = None,
        metadata_contains: dict | None = None,
        from_event_time: datetime | None = None,
        to_event_time: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[RagMemoryChunk], int]:
        statement = select(RagMemoryChunk).join(
            RagMemoryDocument,
            RagMemoryChunk.memory_document_id == RagMemoryDocument.id,
        ).where(
            RagMemoryChunk.seller_id == seller_id,
            RagMemoryChunk.deleted_at.is_(None),
            RagMemoryDocument.deleted_at.is_(None),
        )
        if product_id is not None:
            statement = statement.where(RagMemoryChunk.product_id == product_id)
        if source_types:
            statement = statement.where(RagMemoryChunk.source_type.in_(source_types))
        if metadata_contains:
            statement = statement.where(RagMemoryChunk.metadata_json.contains(metadata_contains))
        if from_event_time:
            statement = statement.where(RagMemoryChunk.event_time >= from_event_time)
        if to_event_time:
            statement = statement.where(RagMemoryChunk.event_time <= to_event_time)

        total = self._db.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
        rows = self._db.execute(
            statement.order_by(
                RagMemoryChunk.event_time.desc().nullslast(),
                RagMemoryChunk.created_at.desc(),
                RagMemoryChunk.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        ).scalars().all()
        return rows, total

    def _validate_payload_dimension(self, payload: RagMemoryChunkCreate) -> None:
        if payload.embedding is None:
            return
        self._validate_vector(payload.embedding)
        if payload.embedding_dimension is not None and payload.embedding_dimension != len(payload.embedding):
            raise RagMemoryDimensionError(
                f"embedding_dimension must match vector length {len(payload.embedding)}, got {payload.embedding_dimension}"
            )

    def _validate_vector(self, embedding: Sequence[float]) -> None:
        if not embedding:
            raise RagMemoryDimensionError("Embedding vector cannot be empty")
        if self.embedding_dimension is not None and len(embedding) != self.embedding_dimension:
            raise RagMemoryDimensionError(
                f"Embedding vector dimension mismatch: expected {self.embedding_dimension}, got {len(embedding)}"
            )

    def mark_chunks_embedded(
        self,
        *,
        updates: Sequence[tuple[UUID, Sequence[float], str, int, str, datetime]],
    ) -> int:
        count = 0
        for chunk_id, embedding, model, dimension, version, embedded_at in updates:
            self._validate_vector(embedding)
            if len(embedding) != dimension:
                raise RagMemoryDimensionError(
                    f"embedding_dimension must match vector length {len(embedding)}, got {dimension}"
                )
            result = self._db.execute(
                update(RagMemoryChunk)
                .where(RagMemoryChunk.id == chunk_id, RagMemoryChunk.deleted_at.is_(None))
                .values(
                    embedding=list(embedding),
                    embedding_model=model,
                    embedding_dimension=dimension,
                    embedding_version=version,
                    embedded_at=embedded_at,
                    embedding_status=RagMemoryEmbeddingStatus.EMBEDDED,
                    embedding_failure_reason=None,
                )
            )
            count += int(result.rowcount or 0)
        self._db.commit()
        return count

    def mark_chunks_failed(
        self,
        *,
        chunk_ids: Sequence[UUID],
        failure_reason: str,
    ) -> int:
        if not chunk_ids:
            return 0
        result = self._db.execute(
            update(RagMemoryChunk)
            .where(RagMemoryChunk.id.in_(chunk_ids), RagMemoryChunk.deleted_at.is_(None))
            .values(
                embedding_status=RagMemoryEmbeddingStatus.FAILED,
                embedding_failure_reason=failure_reason[:255],
                embedding=None,
                embedding_model=None,
                embedding_dimension=None,
                embedding_version=None,
                embedded_at=None,
            )
        )
        self._db.commit()
        return int(result.rowcount or 0)

    def update_document_embedding_statuses(self, *, document_ids: Sequence[UUID]) -> int:
        count = 0
        for document_id in set(document_ids):
            statuses = self._db.execute(
                select(RagMemoryChunk.embedding_status).where(
                    RagMemoryChunk.memory_document_id == document_id,
                    RagMemoryChunk.deleted_at.is_(None),
                )
            ).scalars().all()
            if not statuses:
                continue
            if all(status == RagMemoryEmbeddingStatus.EMBEDDED for status in statuses):
                status = RagMemoryEmbeddingStatus.EMBEDDED
            elif any(status == RagMemoryEmbeddingStatus.FAILED for status in statuses):
                status = RagMemoryEmbeddingStatus.FAILED
            else:
                status = RagMemoryEmbeddingStatus.PENDING
            result = self._db.execute(
                update(RagMemoryDocument)
                .where(RagMemoryDocument.id == document_id, RagMemoryDocument.deleted_at.is_(None))
                .values(embedding_status=status, updated_at=func.now())
            )
            count += int(result.rowcount or 0)
        self._db.commit()
        return count
