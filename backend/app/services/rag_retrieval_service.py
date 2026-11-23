from __future__ import annotations

from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import re
import threading
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.rag_memory import RagMemoryChunk, RagMemoryDocument, RagMemorySourceType
from app.repositories.rag_memory_repository import RagMemoryRepository
from app.services.rag_embedding_service import RagEmbeddingService
from app.services.rag_reranker_service import RagRerankerService
from app.services.rag_memory_source_registry import get_rag_source_definition, implemented_source_types
from app.services.rag_observability import elapsed_ms, increment_metric, log_event, now_ms, record_rag_retrieval_quality

import logging


NO_CONTEXT_MESSAGE = "I could not find enough seller-specific history to answer this reliably."
MAX_RETRIEVAL_TOP_K = 20
RRF_K = 60
# Scales reciprocal rank fusion into [0, 1] (rank 1 in both lists), so the existing boosts keep their weight.
RRF_SCALE = (RRF_K + 1) / 2
QUESTION_SOURCE_TYPE_BOOST = 1.15

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
    # RRF only: a whole-word match on 2+ keywords (a product name) or on a SKU-like token.
    keyword_specific: bool = False
    recency_boost: float = 0.0
    source_type_weight: float = 1.0
    product_match_boost: float = 0.0
    business_importance_boost: float = 0.0
    final_score: float = 0.0
    rerank_score: float | None = None


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
        reranker: RagRerankerService | None = None,
    ) -> None:
        if repository is None and db is None:
            raise ValueError("RagRetrievalService requires a repository or database session")
        self._repository = repository or RagMemoryRepository(db)  # type: ignore[arg-type]
        self._embedding_service = embedding_service or RagEmbeddingService()
        self._source_type_weights = source_type_weights or DEFAULT_SOURCE_TYPE_WEIGHTS
        self._now = now
        self._reranker = reranker

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
        keyword_terms: Sequence[str] | None = None,
    ) -> RagRetrievalResult:
        """``keyword_terms``: extra English words for keyword matching (a Bangla/Banglish question's
        translation, supplied by the Copilot); the question itself still drives the vector search."""
        start_ms = now_ms()
        normalized_question = (question or "").strip()
        extra_terms = tuple(keyword_terms or ())
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
        # Question terms boost likely source types; only an explicit caller filter narrows the search.
        boosted_source_types = (
            set(_source_types_for_question(" ".join([normalized_question, *extra_terms])) or [])
            if settings.rag_rrf_enabled and not requested_source_types
            else set()
        )
        if requested_source_types and not inferred_source_types:
            return self._no_context(
                [f"Requested RAG sources are not implemented: {', '.join(unimplemented_requested)}."],
                seller_id=seller_id,
                start_ms=start_ms,
            )

        query_embedding = _cached_query_embedding(self._embedding_service, seller_id=seller_id, text=normalized_question)
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
            keyword_terms=extra_terms,
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
            boosted_source_types=boosted_source_types,
            keyword_terms=extra_terms,
        )
        if settings.rag_reranker_enabled and ranked:
            ranked = self._rerank(normalized_question, ranked)
        # With RRF, exact keyword hits (SKUs, product names) survive; the floor applies to vector-only matches.
        filtered = [
            item
            for item in ranked
            if item.similarity_score >= min_similarity or (settings.rag_rrf_enabled and item.keyword_specific)
        ]
        if settings.rag_max_chunks_per_group > 0:
            filtered = _cap_per_group(filtered, settings.rag_max_chunks_per_group)
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

    def _rerank(self, question: str, ranked: list[_RankedChunk]) -> list[_RankedChunk]:
        """Reorder the top candidates by cross-encoder score; keep the order when scores are unavailable.

        Only the order changes: the similarity floor applied afterwards still decides what is admitted.
        """
        if self._reranker is None:
            self._reranker = RagRerankerService()
        head = ranked[: max(1, settings.rag_reranker_candidates)]
        start_ms = now_ms()
        scores = self._reranker.score(question, [item.chunk.chunk_text for item in head], budget_ms=settings.rag_reranker_budget_ms)
        log_event(logger, logging.INFO, "rag_rerank", applied=scores is not None, candidates=len(head), duration_ms=elapsed_ms(start_ms))
        if scores is None:
            return ranked
        for item, score in zip(head, scores):
            item.rerank_score = score
        reordered = sorted(head, key=lambda item: -(item.rerank_score or 0.0))  # stable: ties keep hybrid order
        return reordered + ranked[len(head) :]

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
        keyword_terms: Sequence[str] = (),
    ) -> list[RagMemoryChunk]:
        if not enabled:
            return []
        keywords = _keywords(question, keyword_terms)
        return self._repository.keyword_search(
            seller_id=seller_id,
            keywords=keywords,
            product_id=product_id,
            source_types=source_types,
            from_event_time=from_event_time,
            to_event_time=to_event_time,
            include_stale=include_stale,
            limit=limit,
            ranked=settings.rag_fulltext_keyword_enabled,
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
        boosted_source_types: set[RagMemorySourceType] | frozenset[RagMemorySourceType] = frozenset(),
        keyword_terms: Sequence[str] = (),
    ) -> list[_RankedChunk]:
        ranked_by_id: dict[UUID, _RankedChunk] = {}
        for index, (chunk, distance) in enumerate(vector_rows):
            ranked_by_id[chunk.id] = _RankedChunk(
                chunk=chunk,
                similarity_score=_similarity_from_distance(distance),
                vector_rank=index,
            )
        keywords = _keywords(question, keyword_terms)
        use_rrf = settings.rag_rrf_enabled
        for chunk in keyword_rows:
            item = ranked_by_id.get(chunk.id)
            if item is None:
                item = _RankedChunk(chunk=chunk, similarity_score=0.0, vector_rank=None)
                ranked_by_id[chunk.id] = item
            if use_rrf:
                # The SQL prefilter is a substring ILIKE ("paris" hits "comparison"); rank on whole words only.
                matched = _whole_word_matches(chunk.chunk_text, keywords)
                item.keyword_score = max(item.keyword_score, min(0.12, 0.03 * len(matched)))
                item.keyword_specific = item.keyword_specific or len(matched) >= 2 or any(any(ch.isdigit() for ch in word) for word in matched)
            else:
                item.keyword_score = max(item.keyword_score, _keyword_score(chunk.chunk_text, keywords))

        ranked = list(ranked_by_id.values())
        if use_recency_boost:
            ranked = self.apply_recency_boost(ranked)
        if use_source_type_weights:
            ranked = self.apply_source_type_weights(ranked)
            for item in ranked:
                if item.chunk.source_type in boosted_source_types:
                    item.source_type_weight *= QUESTION_SOURCE_TYPE_BOOST
        keyword_ranks: dict[UUID, int] = {}
        if use_rrf:
            # Stable sort keeps the repository order among equal keyword scores.
            by_keyword = sorted((item for item in ranked if item.keyword_score > 0), key=lambda item: -item.keyword_score)
            keyword_ranks = {item.chunk.id: rank for rank, item in enumerate(by_keyword, start=1)}
        for item in ranked:
            if product_id is not None and item.chunk.product_id == product_id:
                item.product_match_boost = 0.05
            item.business_importance_boost = _business_importance_boost(item.chunk.metadata_json or {})
            if use_rrf:
                fused = 0.0
                if item.vector_rank is not None:
                    fused += 1 / (RRF_K + item.vector_rank + 1)
                if item.chunk.id in keyword_ranks:
                    fused += 1 / (RRF_K + keyword_ranks[item.chunk.id])
                base = fused * RRF_SCALE
            else:
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
    if settings.rag_cosine_distance_enabled:
        # Cosine distance is 1 - cosine similarity, so the floor in RAG_MIN_SIMILARITY means what it says.
        return max(0.0, min(1.0, 1.0 - distance))
    return max(0.0, min(1.0, 1.0 / (1.0 + distance)))


_QUERY_EMBEDDING_CACHE: OrderedDict[tuple[str, str, str], list[float]] = OrderedDict()
_QUERY_EMBEDDING_LOCK = threading.Lock()


def _cached_query_embedding(embedding_service: RagEmbeddingService, *, seller_id: UUID, text: str) -> list[float]:
    """Seller-scoped LRU for question embeddings (RAG_QUERY_EMBEDDING_CACHE_SIZE; 0 disables it).

    Repeated and follow-up questions skip the CPU embedding; the key includes the
    seller and the embedding model so no entry is shared across sellers or models.
    """
    size = settings.rag_query_embedding_cache_size
    if size <= 0:
        return embedding_service.embed_text(text)
    key = (str(seller_id), str(getattr(embedding_service, "model_name", "")), text)
    with _QUERY_EMBEDDING_LOCK:
        cached = _QUERY_EMBEDDING_CACHE.get(key)
        if cached is not None:
            _QUERY_EMBEDDING_CACHE.move_to_end(key)
            return list(cached)
    vector = embedding_service.embed_text(text)
    with _QUERY_EMBEDDING_LOCK:
        _QUERY_EMBEDDING_CACHE[key] = list(vector)
        while len(_QUERY_EMBEDDING_CACHE) > size:
            _QUERY_EMBEDDING_CACHE.popitem(last=False)
    return vector


BENGALI_WORD_RE = re.compile(r"[\u0980-\u09FF]{2,}")
BENGALI_STOPWORDS = frozenset({"আমার", "আমি", "আমাদের", "কেন", "কি", "কী", "এই", "সেই", "গত", "করে", "হয়েছে", "কত", "কোন", "এবং", "বা"})


def _cap_per_group(items: list[_RankedChunk], max_per_group: int) -> list[_RankedChunk]:
    """Keep the first ``max_per_group`` items of each (source type, product) group in order, then the rest.

    Skipped items are appended rather than dropped, so they still fill top_k when nothing else qualifies.
    """
    if max_per_group <= 0:
        return items
    counts: dict[tuple[object, object], int] = {}
    kept: list[_RankedChunk] = []
    deferred: list[_RankedChunk] = []
    for item in items:
        key = (item.chunk.source_type, item.chunk.product_id)
        counts[key] = counts.get(key, 0) + 1
        (kept if counts[key] <= max_per_group else deferred).append(item)
    return kept + deferred


MAX_EXTRA_KEYWORDS = 4


def _keywords(question: str, extra_terms: Sequence[str] = ()) -> list[str]:
    """Question keywords (alphabetical, at most 8), then up to 4 new ``extra_terms`` appended after them."""
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
    if settings.copilot_multilingual_enabled:
        # Bengali-script keywords (ASCII-only extraction gave Bangla questions no keyword boost).
        words += [word for word in BENGALI_WORD_RE.findall(question) if word not in BENGALI_STOPWORDS]
    keywords = sorted({word for word in words if word not in stopwords})[:8]
    extras = (term.strip().lower() for term in extra_terms)
    fresh = [term for term in dict.fromkeys(extras) if len(term) >= 3 and term not in stopwords and term not in keywords]
    return keywords + fresh[:MAX_EXTRA_KEYWORDS]


def _source_types_for_question(question: str) -> list[RagMemorySourceType] | None:
    """Source types a question is likely about. Callers use it as a ranking boost, never a filter."""
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
        # Word-start match: "rank" must not fire on "frankly", nor "action" on "transaction".
        if any(re.search(rf"\b{re.escape(term)}", text) for term in terms):
            selected.extend(source_types)
    return list(dict.fromkeys(selected)) or None


def _whole_word_matches(text: str, keywords: list[str]) -> list[str]:
    normalized = text.lower()
    return [keyword for keyword in keywords if re.search(rf"(?<![\w-]){re.escape(keyword)}(?![\w-])", normalized)]


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
