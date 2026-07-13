from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import re
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.rag_memory import RagMemoryChunk, RagMemoryDocument, RagMemorySourceType
from app.repositories.rag_memory_repository import RagMemoryRepository
from app.services.rag_embedding_service import RagEmbeddingService
from app.services.rag_memory_source_registry import get_rag_source_definition, implemented_source_types
from app.services.rag_observability import elapsed_ms, increment_metric, log_event, now_ms, record_rag_retrieval_quality

import logging


NO_CONTEXT_MESSAGE = "I could not find enough seller-specific history to answer this reliably."
MAX_RETRIEVAL_TOP_K = 20

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RagEvidence:
    evidence_id: str
    chunk_id: UUID
    memory_document_id: UUID
    source_type: RagMemorySourceType
    product_id: UUID | None
    event_time: datetime | None
    chunk_text: str
    similarity_score: float
    final_score: float
    source_table: str | None = None
    source_id: str | None = None
    metadata_json: dict | None = None
    is_stale: bool = False


@dataclass(slots=True)
class RagRetrievalResult:
    retrieved_chunks: list[RagEvidence]
    source_documents: list[dict]
    similarity_scores: dict[str, float]
    evidence_ids: list[str]
    retrieval_confidence: str
    missing_data_notes: list[str] = field(default_factory=list)
    message: str | None = None
    explanation: dict = field(default_factory=dict)


@dataclass(slots=True)
class _RankedChunk:
    chunk: RagMemoryChunk
    similarity_score: float
    vector_rank: int | None
    keyword_score: float = 0.0
    recency_boost: float = 0.0
    source_type_weight: float = 1.0
    product_match_boost: float = 0.0
    business_importance_boost: float = 0.0
    final_score: float = 0.0


DEFAULT_SOURCE_TYPE_WEIGHTS: dict[RagMemorySourceType, float] = {
    RagMemorySourceType.ALERT: 1.08,
    RagMemorySourceType.ALERT_HISTORY: 1.08,
    RagMemorySourceType.RECOMMENDATION: 1.08,
    RagMemorySourceType.RECOMMENDATION_HISTORY: 1.08,
    RagMemorySourceType.PRICE_HISTORY: 1.05,
    RagMemorySourceType.PRICING_HISTORY: 1.06,
    RagMemorySourceType.INVENTORY_HISTORY: 1.04,
    RagMemorySourceType.INVENTORY_LIFECYCLE: 1.06,
    RagMemorySourceType.COMPETITOR_HISTORY: 1.03,
    RagMemorySourceType.SALES_HISTORY: 1.06,
    RagMemorySourceType.SALES_REVENUE_SUMMARY: 1.07,
    RagMemorySourceType.DEAD_STOCK_HISTORY: 1.05,
    RagMemorySourceType.SEO_VISIBILITY_HISTORY: 1.04,
    RagMemorySourceType.PRODUCT_PROFILE: 1.03,
    RagMemorySourceType.COPILOT_HISTORY: 1.02,
    RagMemorySourceType.PROMOTION_RESULT: 1.02,
}


class RagRetrievalService:
    def __init__(
        self,
        db: Session | None = None,
        *,
        repository: RagMemoryRepository | None = None,
        embedding_service: RagEmbeddingService | None = None,
        source_type_weights: dict[RagMemorySourceType, float] | None = None,
        now: datetime | None = None,
    ) -> None:
        if repository is None and db is None:
            raise ValueError("RagRetrievalService requires a repository or database session")
        self._repository = repository or RagMemoryRepository(db)  # type: ignore[arg-type]
        self._embedding_service = embedding_service or RagEmbeddingService()
        self._source_type_weights = source_type_weights or DEFAULT_SOURCE_TYPE_WEIGHTS
        self._now = now

    def retrieve_context(
        self,
        *,
        seller_id: UUID,
        question: str,
        product_id: UUID | None = None,
        source_types: list[RagMemorySourceType] | None = None,
        from_event_time: datetime | None = None,
        to_event_time: datetime | None = None,
        top_k: int | None = None,
        min_similarity: float | None = None,
        include_stale: bool = False,
        use_keyword_search: bool = True,
        use_recency_boost: bool = True,
        use_source_type_weights: bool = True,
    ) -> RagRetrievalResult:
        start_ms = now_ms()
        normalized_question = (question or "").strip()
        if not normalized_question:
            return self._no_context(["Question is empty."], seller_id=seller_id, start_ms=start_ms)
        top_k = max(1, min(int(top_k or settings.rag_retrieval_top_k), MAX_RETRIEVAL_TOP_K))
        min_similarity = settings.rag_min_similarity if min_similarity is None else min_similarity
        requested_source_types = list(source_types or [])
        unimplemented_requested = [
            source_type.value
            for source_type in requested_source_types
            if not get_rag_source_definition(source_type).implemented
        ]
        inferred_source_types = (
            [source_type for source_type in requested_source_types if get_rag_source_definition(source_type).implemented]
            if requested_source_types
            else implemented_source_types()
        )
        if requested_source_types and not inferred_source_types:
            return self._no_context(
                [f"Requested RAG sources are not implemented: {', '.join(unimplemented_requested)}."],
                seller_id=seller_id,
                start_ms=start_ms,
            )

        query_embedding = self._embedding_service.embed_text(normalized_question)
        vector_rows = self.vector_search(
            seller_id=seller_id,
            query_embedding=query_embedding,
            product_id=product_id,
            source_types=inferred_source_types,
            from_event_time=from_event_time,
            to_event_time=to_event_time,
            top_k=max(top_k * 4, top_k),
            include_stale=include_stale,
        )
        vector_result_count = len(vector_rows)
        vector_rows = self._filter_vector_rows_for_seller(seller_id=seller_id, rows=vector_rows)
        keyword_rows = self.keyword_search_optional(
            seller_id=seller_id,
            question=normalized_question,
            product_id=product_id,
            source_types=inferred_source_types,
            from_event_time=from_event_time,
            to_event_time=to_event_time,
            include_stale=include_stale,
            limit=max(top_k * 4, top_k),
            enabled=use_keyword_search,
        )
        keyword_result_count = len(keyword_rows)
        keyword_rows = self._filter_chunks_for_seller(seller_id=seller_id, chunks=keyword_rows)
        ranked = self.hybrid_rank(
            vector_rows=vector_rows,
            keyword_rows=keyword_rows,
            question=normalized_question,
            product_id=product_id,
            use_recency_boost=use_recency_boost,
            use_source_type_weights=use_source_type_weights,
        )
        filtered = [item for item in ranked if item.similarity_score >= min_similarity]
        selected = filtered[:top_k]
        if not selected:
            record_rag_retrieval_quality(
                keyword_result_count=keyword_result_count,
                vector_result_count=vector_result_count,
                fused_result_count=len(ranked),
                final_context_count=0,
                top_score=None,
                average_score=None,
                filtered_by_seller_count=(vector_result_count - len(vector_rows)) + (keyword_result_count - len(keyword_rows)),
                stale_result_count=0,
                duration_ms=elapsed_ms(start_ms),
            )
            no_context_notes = ["No seller-specific memory chunks met the similarity threshold."]
            if ranked:
                no_context_notes.append("Relevant memory may exist, but the match was weak.")
            if unimplemented_requested:
                no_context_notes.append(f"Requested RAG sources are not implemented: {', '.join(unimplemented_requested)}.")
            return self._no_context(no_context_notes, seller_id=seller_id, start_ms=start_ms, quality_recorded=True)

        documents = self.group_by_source_document(seller_id=seller_id, ranked_chunks=selected)
        evidence = self.build_evidence_list(selected, documents)
        confidence = self._confidence(evidence)
        notes: list[str] = []
        if unimplemented_requested:
            notes.append(f"Requested RAG sources are not implemented: {', '.join(unimplemented_requested)}.")
        if len(evidence) < 2:
            notes.append("Only one supporting memory chunk was found.")
        if requested_source_types:
            found_types = {item.source_type for item in evidence}
            missing_types = [source_type.value for source_type in requested_source_types if source_type not in found_types]
            if missing_types:
                notes.append(f"No retrieved evidence for requested or inferred source types: {', '.join(missing_types)}.")
        stale_count = sum(1 for item in evidence if item.is_stale)
        if stale_count:
            notes.append(f"{stale_count} retrieved evidence item(s) are stale; verify against current dashboard data.")
        duration_ms = elapsed_ms(start_ms)
        scores = [item.similarity_score for item in evidence]
        record_rag_retrieval_quality(
            keyword_result_count=keyword_result_count,
            vector_result_count=vector_result_count,
            fused_result_count=len(ranked),
            final_context_count=len(evidence),
            top_score=max(scores) if scores else None,
            average_score=(sum(scores) / len(scores)) if scores else None,
            filtered_by_seller_count=(vector_result_count - len(vector_rows)) + (keyword_result_count - len(keyword_rows)),
            stale_result_count=stale_count,
            duration_ms=duration_ms,
        )
        log_event(
            logger,
            logging.INFO,
            "rag_retrieval_query",
            seller_id=seller_id,
            product_id=product_id,
            source_types=",".join(source_type.value for source_type in inferred_source_types or []),
            top_k=top_k,
            returned=len(evidence),
            confidence=confidence,
            duration_ms=duration_ms,
        )
        return RagRetrievalResult(
            retrieved_chunks=evidence,
            source_documents=list(documents.values()),
            similarity_scores={str(item.chunk_id): item.similarity_score for item in evidence},
            evidence_ids=[item.evidence_id for item in evidence],
            retrieval_confidence=confidence,
            missing_data_notes=notes,
            message=None if confidence != "NO_CONTEXT" else NO_CONTEXT_MESSAGE,
            explanation=self.explain_retrieval(selected, top_k=top_k, min_similarity=min_similarity),
        )

    def vector_search(
        self,
        *,
        seller_id: UUID,
        query_embedding: list[float],
        product_id: UUID | None = None,
        source_types: list[RagMemorySourceType] | None = None,
        from_event_time: datetime | None = None,
        to_event_time: datetime | None = None,
        top_k: int = 8,
        include_stale: bool = False,
    ) -> list[tuple[RagMemoryChunk, float]]:
        return self._repository.vector_search(
            seller_id=seller_id,
            query_embedding=query_embedding,
            product_id=product_id,
            source_types=source_types,
            from_event_time=from_event_time,
            to_event_time=to_event_time,
            include_stale=include_stale,
            limit=top_k,
        )

    def keyword_search_optional(
        self,
        *,
        seller_id: UUID,
        question: str,
        product_id: UUID | None = None,
        source_types: list[RagMemorySourceType] | None = None,
        from_event_time: datetime | None = None,
        to_event_time: datetime | None = None,
        include_stale: bool = False,
        limit: int = 50,
        enabled: bool = True,
    ) -> list[RagMemoryChunk]:
        if not enabled:
            return []
        keywords = _keywords(question)
        return self._repository.keyword_search(
            seller_id=seller_id,
            keywords=keywords,
            product_id=product_id,
            source_types=source_types,
            from_event_time=from_event_time,
            to_event_time=to_event_time,
            include_stale=include_stale,
            limit=limit,
        )

    def hybrid_rank(
        self,
        *,
        vector_rows: list[tuple[RagMemoryChunk, float]],
        keyword_rows: list[RagMemoryChunk],
        question: str,
        product_id: UUID | None = None,
        use_recency_boost: bool = True,
        use_source_type_weights: bool = True,
    ) -> list[_RankedChunk]:
        ranked_by_id: dict[UUID, _RankedChunk] = {}
        for index, (chunk, distance) in enumerate(vector_rows):
            ranked_by_id[chunk.id] = _RankedChunk(
                chunk=chunk,
                similarity_score=_similarity_from_distance(distance),
                vector_rank=index,
            )
        keywords = _keywords(question)
        for chunk in keyword_rows:
            item = ranked_by_id.get(chunk.id)
            if item is None:
                item = _RankedChunk(chunk=chunk, similarity_score=0.0, vector_rank=None)
                ranked_by_id[chunk.id] = item
            item.keyword_score = max(item.keyword_score, _keyword_score(chunk.chunk_text, keywords))

        ranked = list(ranked_by_id.values())
        if use_recency_boost:
            ranked = self.apply_recency_boost(ranked)
        if use_source_type_weights:
            ranked = self.apply_source_type_weights(ranked)
        for item in ranked:
            if product_id is not None and item.chunk.product_id == product_id:
                item.product_match_boost = 0.05
            item.business_importance_boost = _business_importance_boost(item.chunk.metadata_json or {})
            base = item.similarity_score + min(item.keyword_score, 0.12)
            item.final_score = (
                base * item.source_type_weight
                + item.recency_boost
                + item.product_match_boost
                + item.business_importance_boost
            )
        return sorted(
            ranked,
            key=lambda item: (
                -item.final_score,
                item.vector_rank if item.vector_rank is not None else 10_000,
                item.chunk.event_time or datetime.min.replace(tzinfo=timezone.utc),
                str(item.chunk.id),
            ),
        )

    def apply_recency_boost(self, ranked_chunks: list[_RankedChunk]) -> list[_RankedChunk]:
        now = self._now or datetime.now(timezone.utc)
        for item in ranked_chunks:
            if item.chunk.event_time is None:
                item.recency_boost = 0.0
                continue
            event_time = item.chunk.event_time
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=timezone.utc)
            age_days = max(0.0, (now - event_time).total_seconds() / 86400)
            item.recency_boost = round(0.08 * math.exp(-age_days / 45), 6)
        return ranked_chunks

    def apply_source_type_weights(self, ranked_chunks: list[_RankedChunk]) -> list[_RankedChunk]:
        for item in ranked_chunks:
            item.source_type_weight = self._source_type_weights.get(item.chunk.source_type, 1.0)
        return ranked_chunks

    def group_by_source_document(
        self,
        *,
        seller_id: UUID,
        ranked_chunks: list[_RankedChunk],
    ) -> dict[UUID, dict]:
        document_ids = [item.chunk.memory_document_id for item in ranked_chunks]
        documents = self._repository.get_documents_by_ids(seller_id=seller_id, document_ids=document_ids)
        grouped: dict[UUID, dict] = {}
        for item in ranked_chunks:
            document = documents.get(item.chunk.memory_document_id) or getattr(item.chunk, "document", None)
            grouped[item.chunk.memory_document_id] = _document_payload(item.chunk, document)
        return grouped

    def build_evidence_list(
        self,
        ranked_chunks: list[_RankedChunk],
        documents: dict[UUID, dict],
    ) -> list[RagEvidence]:
        evidence: list[RagEvidence] = []
        for index, item in enumerate(ranked_chunks, start=1):
            doc = documents.get(item.chunk.memory_document_id, {})
            evidence.append(
                RagEvidence(
                    evidence_id=f"rag:{item.chunk.memory_document_id}:{item.chunk.id}",
                    chunk_id=item.chunk.id,
                    memory_document_id=item.chunk.memory_document_id,
                    source_type=item.chunk.source_type,
                    product_id=item.chunk.product_id,
                    event_time=item.chunk.event_time,
                    chunk_text=item.chunk.chunk_text,
                    similarity_score=round(item.similarity_score, 6),
                    final_score=round(item.final_score, 6),
                    source_table=doc.get("source_table"),
                    source_id=doc.get("source_id"),
                    metadata_json=item.chunk.metadata_json,
                    is_stale=_is_stale(item.chunk.event_time, now=self._now),
                )
            )
            del index
        return evidence

    def explain_retrieval(self, ranked_chunks: list[_RankedChunk], *, top_k: int, min_similarity: float) -> dict:
        return {
            "top_k": top_k,
            "min_similarity": min_similarity,
            "ranked_count": len(ranked_chunks),
            "ranking_features": [
                "similarity_score",
                "keyword_score",
                "recency_boost",
                "source_type_weight",
                "product_match_boost",
                "business_importance_boost",
            ],
        }

    def _confidence(self, evidence: list[RagEvidence]) -> str:
        if not evidence:
            return "NO_CONTEXT"
        best = evidence[0].similarity_score
        if best >= 0.72 and len(evidence) >= 2:
            return "HIGH"
        if best >= 0.50:
            return "MEDIUM"
        return "LOW"

    def _filter_vector_rows_for_seller(
        self,
        *,
        seller_id: UUID,
        rows: list[tuple[RagMemoryChunk, float]],
    ) -> list[tuple[RagMemoryChunk, float]]:
        filtered = []
        for chunk, distance in rows:
            if getattr(chunk, "seller_id", seller_id) != seller_id:
                increment_metric("rag_cross_tenant_blocked_total")
                log_event(
                    logger,
                    logging.WARNING,
                    "rag_cross_seller_access_denied",
                    seller_id=seller_id,
                    chunk_id=getattr(chunk, "id", None),
                    chunk_seller_id=getattr(chunk, "seller_id", None),
                )
                continue
            filtered.append((chunk, distance))
        return filtered

    def _filter_chunks_for_seller(self, *, seller_id: UUID, chunks: list[RagMemoryChunk]) -> list[RagMemoryChunk]:
        filtered = []
        for chunk in chunks:
            if getattr(chunk, "seller_id", seller_id) != seller_id:
                increment_metric("rag_cross_tenant_blocked_total")
                log_event(
                    logger,
                    logging.WARNING,
                    "rag_cross_seller_access_denied",
                    seller_id=seller_id,
                    chunk_id=getattr(chunk, "id", None),
                    chunk_seller_id=getattr(chunk, "seller_id", None),
                )
                continue
            filtered.append(chunk)
        return filtered

    def _no_context(
        self,
        notes: list[str],
        *,
        seller_id: UUID | None = None,
        start_ms: float | None = None,
        quality_recorded: bool = False,
    ) -> RagRetrievalResult:
        increment_metric("rag_no_context_total")
        duration_ms = elapsed_ms(start_ms) if start_ms is not None else None
        if duration_ms is not None and not quality_recorded:
            record_rag_retrieval_quality(
                keyword_result_count=0,
                vector_result_count=0,
                fused_result_count=0,
                final_context_count=0,
                top_score=None,
                average_score=None,
                filtered_by_seller_count=0,
                stale_result_count=0,
                duration_ms=duration_ms,
            )
        log_event(
            logger,
            logging.INFO,
            "rag_retrieval_no_context",
            seller_id=seller_id,
            duration_ms=duration_ms,
            notes=";".join(notes),
        )
        return RagRetrievalResult(
            retrieved_chunks=[],
            source_documents=[],
            similarity_scores={},
            evidence_ids=[],
            retrieval_confidence="NO_CONTEXT",
            missing_data_notes=notes,
            message=NO_CONTEXT_MESSAGE,
            explanation={"ranked_count": 0},
        )


def _similarity_from_distance(distance: float) -> float:
    if distance < 0:
        distance = 0.0
    return max(0.0, min(1.0, 1.0 / (1.0 + distance)))


def _keywords(question: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}", question.lower())
    stopwords = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "what",
        "when",
        "where",
        "seller",
        "product",
        "history",
    }
    return sorted({word for word in words if word not in stopwords})[:8]


def _source_types_for_question(question: str) -> list[RagMemorySourceType] | None:
    text = question.lower()
    selected: list[RagMemorySourceType] = []
    rules = (
        (("sale", "revenue", "order", "aov", "profit"), (RagMemorySourceType.SALES_HISTORY, RagMemorySourceType.SALES_REVENUE_SUMMARY)),
        (("stock", "inventory", "reorder", "stockout", "velocity"), (RagMemorySourceType.INVENTORY_LIFECYCLE, RagMemorySourceType.INVENTORY_HISTORY)),
        (("price", "pricing", "margin", "fee", "elasticity"), (RagMemorySourceType.PRICING_HISTORY, RagMemorySourceType.PRICE_HISTORY)),
        (("competitor", "market", "ranking", "scrape"), (RagMemorySourceType.COMPETITOR_HISTORY,)),
        (("dead stock", "aging", "locked capital", "recovery"), (RagMemorySourceType.DEAD_STOCK_HISTORY,)),
        (("seo", "visibility", "impression", "click", "rank"), (RagMemorySourceType.SEO_VISIBILITY_HISTORY,)),
        (("alert", "telegram", "notification"), (RagMemorySourceType.ALERT_HISTORY, RagMemorySourceType.ALERT)),
        (("recommendation", "action", "suggest"), (RagMemorySourceType.RECOMMENDATION_HISTORY, RagMemorySourceType.RECOMMENDATION)),
        (("product", "sku", "catalog"), (RagMemorySourceType.PRODUCT_PROFILE,)),
        (("copilot", "asked", "conversation"), (RagMemorySourceType.COPILOT_HISTORY,)),
    )
    for terms, source_types in rules:
        if any(term in text for term in terms):
            selected.extend(source_types)
    return list(dict.fromkeys(selected)) or None


def _keyword_score(text: str, keywords: list[str]) -> float:
    if not keywords:
        return 0.0
    normalized = text.lower()
    matches = sum(1 for keyword in keywords if keyword in normalized)
    return min(0.12, 0.03 * matches)


def _business_importance_boost(metadata: dict) -> float:
    for key in ("business_importance", "importance_score", "opportunity_score", "risk_score", "urgency_score"):
        value = metadata.get(key)
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if numeric > 1:
            numeric = numeric / 100
        return max(0.0, min(0.06, numeric * 0.06))
    severity = str(metadata.get("severity") or metadata.get("urgency_level") or "").upper()
    if severity in {"CRITICAL", "HIGH"}:
        return 0.04
    if severity == "MEDIUM":
        return 0.02
    return 0.0


def _is_stale(event_time: datetime | None, *, now: datetime | None = None, max_age_days: int = 90) -> bool:
    if event_time is None:
        return False
    current = now or datetime.now(timezone.utc)
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return (current - event_time).days > max_age_days


def _document_payload(chunk: RagMemoryChunk, document: RagMemoryDocument | None) -> dict:
    if document is None:
        return {
            "id": chunk.memory_document_id,
            "source_type": chunk.source_type,
            "product_id": chunk.product_id,
            "source_table": None,
            "source_id": None,
            "title": None,
            "event_time": chunk.event_time,
        }
    return {
        "id": document.id,
        "source_type": document.source_type,
        "product_id": document.product_id,
        "source_table": document.source_table,
        "source_id": document.source_id,
        "title": document.title,
        "event_time": document.event_time,
    }
