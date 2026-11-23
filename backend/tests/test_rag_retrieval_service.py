from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.models.rag_memory import RagMemoryEmbeddingStatus, RagMemorySourceType
from app.repositories.rag_memory_repository import RagMemoryRepository
from app.services.rag_memory_source_registry import implemented_source_types
from app.services.rag_retrieval_service import NO_CONTEXT_MESSAGE, RagRetrievalService
from app.services.rag_retrieval_service import settings as rag_retrieval_settings


class FakeEmbeddingService:
    def embed_text(self, text: str) -> list[float]:
        self.last_text = text
        return [0.1, 0.2, 0.3]


class FakeRepository:
    def __init__(self, *, vector_rows=None, keyword_rows=None, documents=None) -> None:
        self.vector_rows = vector_rows or []
        self.keyword_rows = keyword_rows or []
        self.documents = documents or {}
        self.calls = []

    def vector_search(self, **kwargs):
        self.calls.append(("vector_search", kwargs))
        seller_id = kwargs["seller_id"]
        return [(chunk, distance) for chunk, distance in self.vector_rows if chunk.seller_id == seller_id]

    def keyword_search(self, **kwargs):
        self.calls.append(("keyword_search", kwargs))
        seller_id = kwargs["seller_id"]
        return [chunk for chunk in self.keyword_rows if chunk.seller_id == seller_id]

    def get_documents_by_ids(self, *, seller_id, document_ids):
        self.calls.append(("get_documents_by_ids", {"seller_id": seller_id, "document_ids": document_ids}))
        del seller_id
        return {document_id: self.documents[document_id] for document_id in document_ids if document_id in self.documents}


class _EmptyResult:
    def all(self):
        return []

    def scalars(self):
        return self

    def scalar_one(self):
        return 0


class CaptureSession:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((statement, params))
        return _EmptyResult()


def chunk(
    *,
    seller_id=None,
    product_id=None,
    source_type=RagMemorySourceType.ALERT,
    event_time=None,
    text="critical inventory alert for Product A",
    metadata=None,
):
    document_id = uuid4()
    return SimpleNamespace(
        id=uuid4(),
        seller_id=seller_id or uuid4(),
        memory_document_id=document_id,
        product_id=product_id,
        source_type=source_type,
        chunk_index=0,
        chunk_text=text,
        metadata_json=metadata or {},
        event_time=event_time,
        created_at=event_time or datetime(2026, 7, 5, tzinfo=timezone.utc),
        embedding_status=RagMemoryEmbeddingStatus.EMBEDDED,
        deleted_at=None,
    )


def document_for(item):
    return SimpleNamespace(
        id=item.memory_document_id,
        seller_id=item.seller_id,
        product_id=item.product_id,
        source_type=item.source_type,
        source_table="alerts",
        source_id=str(uuid4()),
        title="Alert memory",
        event_time=item.event_time,
    )


class RagRetrievalServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        # Fake distances below are L2 distances; pin the legacy metric regardless of RAG_COSINE_DISTANCE_ENABLED.
        metric = patch.object(rag_retrieval_settings, "rag_cosine_distance_enabled", False)
        metric.start()
        self.addCleanup(metric.stop)

    def test_retrieves_only_seller_own_chunks(self):
        seller_id = uuid4()
        other_seller_id = uuid4()
        owned = chunk(seller_id=seller_id)
        other = chunk(seller_id=other_seller_id, text="other seller alert")
        repo = FakeRepository(
            vector_rows=[(owned, 0.2), (other, 0.01)],
            documents={owned.memory_document_id: document_for(owned)},
        )
        service = RagRetrievalService(repository=repo, embedding_service=FakeEmbeddingService())

        result = service.retrieve_context(seller_id=seller_id, question="inventory alert", min_similarity=0.1)

        self.assertEqual(1, len(result.retrieved_chunks))
        self.assertEqual(owned.id, result.retrieved_chunks[0].chunk_id)
        self.assertEqual(seller_id, repo.calls[0][1]["seller_id"])

    def test_product_source_and_date_filters_are_forwarded(self):
        seller_id = uuid4()
        product_id = uuid4()
        from_date = datetime(2026, 7, 1, tzinfo=timezone.utc)
        to_date = datetime(2026, 7, 31, tzinfo=timezone.utc)
        repo = FakeRepository()
        service = RagRetrievalService(repository=repo, embedding_service=FakeEmbeddingService())

        service.retrieve_context(
            seller_id=seller_id,
            question="price recommendation",
            product_id=product_id,
            source_types=[RagMemorySourceType.PRICE_HISTORY],
            from_event_time=from_date,
            to_event_time=to_date,
        )

        vector_call = repo.calls[0][1]
        keyword_call = repo.calls[1][1]
        self.assertEqual(product_id, vector_call["product_id"])
        self.assertEqual([RagMemorySourceType.PRICE_HISTORY], vector_call["source_types"])
        self.assertEqual(from_date, vector_call["from_event_time"])
        self.assertEqual(to_date, vector_call["to_event_time"])
        self.assertEqual(product_id, keyword_call["product_id"])

    def test_empty_source_filter_forwards_all_implemented_source_types(self):
        seller_id = uuid4()
        repo = FakeRepository()
        service = RagRetrievalService(repository=repo, embedding_service=FakeEmbeddingService())

        service.retrieve_context(seller_id=seller_id, question="sales and competitor history", source_types=[])

        expected = implemented_source_types()
        self.assertEqual(expected, repo.calls[0][1]["source_types"])
        self.assertEqual(expected, repo.calls[1][1]["source_types"])
        self.assertNotIn("database", [item.value.casefold() for item in repo.calls[0][1]["source_types"]])
        self.assertNotIn("memory", [item.value.casefold() for item in repo.calls[0][1]["source_types"]])

    def test_low_similarity_returns_low_confidence(self):
        seller_id = uuid4()
        item = chunk(seller_id=seller_id)
        repo = FakeRepository(
            vector_rows=[(item, 2.0)],
            documents={item.memory_document_id: document_for(item)},
        )
        service = RagRetrievalService(repository=repo, embedding_service=FakeEmbeddingService())

        result = service.retrieve_context(seller_id=seller_id, question="inventory", min_similarity=0.1)

        self.assertEqual("LOW", result.retrieval_confidence)
        self.assertLess(result.retrieved_chunks[0].similarity_score, 0.5)

    def test_no_context_handled_safely(self):
        service = RagRetrievalService(repository=FakeRepository(), embedding_service=FakeEmbeddingService())

        result = service.retrieve_context(seller_id=uuid4(), question="unknown history")

        self.assertEqual("NO_CONTEXT", result.retrieval_confidence)
        self.assertEqual(NO_CONTEXT_MESSAGE, result.message)
        self.assertEqual([], result.retrieved_chunks)

    def test_recency_boost_is_deterministic(self):
        seller_id = uuid4()
        older = chunk(
            seller_id=seller_id,
            event_time=datetime(2026, 6, 1, tzinfo=timezone.utc),
            text="older alert",
        )
        newer = chunk(
            seller_id=seller_id,
            event_time=datetime(2026, 7, 1, tzinfo=timezone.utc),
            text="newer alert",
        )
        repo = FakeRepository(
            vector_rows=[(older, 0.25), (newer, 0.25)],
            documents={
                older.memory_document_id: document_for(older),
                newer.memory_document_id: document_for(newer),
            },
        )
        service = RagRetrievalService(
            repository=repo,
            embedding_service=FakeEmbeddingService(),
            now=datetime(2026, 7, 5, tzinfo=timezone.utc),
        )

        first = service.retrieve_context(seller_id=seller_id, question="alert", min_similarity=0.1)
        second = service.retrieve_context(seller_id=seller_id, question="alert", min_similarity=0.1)

        self.assertEqual(newer.id, first.retrieved_chunks[0].chunk_id)
        self.assertEqual([item.chunk_id for item in first.retrieved_chunks], [item.chunk_id for item in second.retrieved_chunks])
        self.assertEqual([item.final_score for item in first.retrieved_chunks], [item.final_score for item in second.retrieved_chunks])

    def test_ranking_is_stable_with_ties(self):
        seller_id = uuid4()
        first = chunk(seller_id=seller_id, text="same alert")
        second = chunk(seller_id=seller_id, text="same alert")
        ordered = sorted([first, second], key=lambda item: str(item.id))
        repo = FakeRepository(
            vector_rows=[(second, 0.2), (first, 0.2)],
            documents={
                first.memory_document_id: document_for(first),
                second.memory_document_id: document_for(second),
            },
        )
        service = RagRetrievalService(repository=repo, embedding_service=FakeEmbeddingService())

        result = service.retrieve_context(seller_id=seller_id, question="alert", min_similarity=0.1, use_recency_boost=False)

        self.assertEqual([second.id, first.id], [item.chunk_id for item in result.retrieved_chunks])
        self.assertNotEqual([item.id for item in ordered], [])

    def test_vector_sql_excludes_deleted_failed_and_supports_filters(self):
        session = CaptureSession()
        repository = RagMemoryRepository(session)
        seller_id = uuid4()
        product_id = uuid4()

        result = repository.vector_search(
            seller_id=seller_id,
            product_id=product_id,
            source_types=[RagMemorySourceType.ALERT],
            from_event_time=datetime(2026, 7, 1, tzinfo=timezone.utc),
            to_event_time=datetime(2026, 7, 31, tzinfo=timezone.utc),
            query_embedding=[0.1, 0.2, 0.3],
        )

        self.assertEqual([], result)
        statement, params = session.calls[0]
        sql = str(statement)
        self.assertIn("c.seller_id = :seller_id", sql)
        self.assertIn("c.deleted_at IS NULL", sql)
        self.assertIn("d.deleted_at IS NULL", sql)
        self.assertIn("c.embedding_status != 'FAILED'", sql)
        self.assertIn("c.product_id = :product_id", sql)
        self.assertIn("c.event_time >= :from_event_time", sql)
        self.assertEqual(seller_id, params["seller_id"])
        self.assertEqual(product_id, params["product_id"])
        self.assertEqual(["ALERT"], params["source_types"])

    def test_keyword_search_uses_bound_parameters_for_user_terms(self):
        session = CaptureSession()
        repository = RagMemoryRepository(session)
        malicious = "alert%' OR 1=1 --"

        result = repository.keyword_search(seller_id=uuid4(), keywords=[malicious])

        self.assertEqual([], result)
        statement, _ = session.calls[0]
        compiled = str(statement)
        self.assertNotIn(malicious, compiled)
        self.assertIn("lower(rag_memory_chunks.chunk_text)", compiled)


class RagRrfRetrievalTests(unittest.TestCase):
    """RAG_RRF_ENABLED + cosine distance (the HNSW index metric)."""

    def setUp(self) -> None:
        for name, value in (("rag_cosine_distance_enabled", True), ("rag_rrf_enabled", True)):
            flag = patch.object(rag_retrieval_settings, name, value)
            flag.start()
            self.addCleanup(flag.stop)

    def _service(self, repo):
        return RagRetrievalService(repository=repo, embedding_service=FakeEmbeddingService(), now=datetime(2026, 11, 22, tzinfo=timezone.utc))

    def test_keyword_only_exact_sku_hit_is_returned(self):
        seller_id = uuid4()
        sku_chunk = chunk(seller_id=seller_id, source_type=RagMemorySourceType.INVENTORY_LIFECYCLE, text="Black Casual Slip-On Shoe For Men (SKU DEMO-BATA-122185090) received 72 units")
        repo = FakeRepository(keyword_rows=[sku_chunk], documents={sku_chunk.memory_document_id: document_for(sku_chunk)})

        result = self._service(repo).retrieve_context(seller_id=seller_id, question="stock received for demo-bata-122185090", min_similarity=0.45)

        self.assertEqual([sku_chunk.id], [item.chunk_id for item in result.retrieved_chunks])

    def test_keyword_only_hits_need_whole_words_and_a_specific_match(self):
        seller_id = uuid4()
        substring_only = chunk(seller_id=seller_id, text="competitor comparison listing")  # "paris" is inside "comparison"
        one_generic_word = chunk(seller_id=seller_id, text="weekly sales digest")
        product_name = chunk(seller_id=seller_id, text="Lex Loafer in Brown sold 2 units")
        repo = FakeRepository(
            keyword_rows=[substring_only, one_generic_word, product_name],
            documents={item.memory_document_id: document_for(item) for item in (substring_only, one_generic_word, product_name)},
        )

        weather = self._service(repo).retrieve_context(seller_id=seller_id, question="weather in paris tomorrow", min_similarity=0.45)
        loafer = self._service(repo).retrieve_context(seller_id=seller_id, question="lex loafer sales", min_similarity=0.45)

        self.assertEqual([], weather.retrieved_chunks)
        self.assertEqual([product_name.id], [item.chunk_id for item in loafer.retrieved_chunks])

    def test_keyword_only_hit_is_dropped_without_rrf(self):
        seller_id = uuid4()
        sku_chunk = chunk(seller_id=seller_id, text="SKU DEMO-BATA-122185090 received")
        repo = FakeRepository(keyword_rows=[sku_chunk], documents={sku_chunk.memory_document_id: document_for(sku_chunk)})

        with patch.object(rag_retrieval_settings, "rag_rrf_enabled", False):
            result = self._service(repo).retrieve_context(seller_id=seller_id, question="demo-bata-122185090", min_similarity=0.45)

        self.assertEqual([], result.retrieved_chunks)

    def test_cosine_threshold_drops_unrelated_chunk(self):
        seller_id = uuid4()
        unrelated = chunk(seller_id=seller_id, text="weather report")
        related = chunk(seller_id=seller_id, text="sales summary")
        repo = FakeRepository(
            vector_rows=[(related, 0.2), (unrelated, 0.9)],
            documents={item.memory_document_id: document_for(item) for item in (related, unrelated)},
        )

        result = self._service(repo).retrieve_context(seller_id=seller_id, question="zzz", min_similarity=0.45)

        # distance 0.9 -> cosine similarity 0.1, below the floor; distance 0.2 -> 0.8 survives.
        self.assertEqual([related.id], [item.chunk_id for item in result.retrieved_chunks])
        self.assertAlmostEqual(0.8, result.retrieved_chunks[0].similarity_score)

    def test_source_types_boost_not_filter(self):
        seller_id = uuid4()
        inventory = chunk(seller_id=seller_id, source_type=RagMemorySourceType.INVENTORY_HISTORY, text="stock count snapshot")
        sales = chunk(seller_id=seller_id, source_type=RagMemorySourceType.SALES_HISTORY, text="daily sales digest")
        fillers = [chunk(seller_id=seller_id, text=f"unrelated {index}") for index in range(2)]
        # Sales ranks 4th by vector; only the 1.15x question boost lifts it above inventory.
        repo = FakeRepository(
            vector_rows=[(inventory, 0.3), (fillers[0], 0.9), (fillers[1], 0.9), (sales, 0.3)],
            documents={item.memory_document_id: document_for(item) for item in (inventory, sales, *fillers)},
        )

        result = self._service(repo).retrieve_context(seller_id=seller_id, question="what about my order volume", min_similarity=0.45, use_recency_boost=False)

        # "order" routes to sales: the sales chunk is boosted, the inventory chunk is still returned.
        self.assertEqual(implemented_source_types(), repo.calls[0][1]["source_types"])
        self.assertEqual([sales.id, inventory.id], [item.chunk_id for item in result.retrieved_chunks])

    def test_explicit_source_types_still_filter(self):
        repo = FakeRepository()
        self._service(repo).retrieve_context(seller_id=uuid4(), question="order", source_types=[RagMemorySourceType.PRICE_HISTORY])
        self.assertEqual([RagMemorySourceType.PRICE_HISTORY], repo.calls[0][1]["source_types"])

    def test_question_terms_match_whole_words_only(self):
        from app.services.rag_retrieval_service import _source_types_for_question

        self.assertIsNone(_source_types_for_question("frankly this transaction"))
        self.assertIn(RagMemorySourceType.SEO_VISIBILITY_HISTORY, _source_types_for_question("my search rank dropped") or [])

    def test_cross_seller_chunk_never_returned(self):
        seller_id = uuid4()
        foreign = chunk(seller_id=uuid4(), text="SKU DEMO-1 foreign")
        repo = FakeRepository()
        # Simulate a repository bug that leaks another seller's rows on both paths.
        repo.vector_search = lambda **kwargs: [(foreign, 0.0)]
        repo.keyword_search = lambda **kwargs: [foreign]

        result = self._service(repo).retrieve_context(seller_id=seller_id, question="demo-1", min_similarity=0.0)

        self.assertEqual([], result.retrieved_chunks)

    def test_rrf_prefers_items_found_by_both_searches(self):
        seller_id = uuid4()
        both = chunk(seller_id=seller_id, text="lex loafer sales digest")
        vector_only = chunk(seller_id=seller_id, text="footwear summary")
        repo = FakeRepository(
            vector_rows=[(vector_only, 0.1), (both, 0.15)],
            keyword_rows=[both],
            documents={item.memory_document_id: document_for(item) for item in (both, vector_only)},
        )

        result = self._service(repo).retrieve_context(seller_id=seller_id, question="lex loafer", min_similarity=0.45, use_recency_boost=False)

        self.assertEqual([both.id, vector_only.id], [item.chunk_id for item in result.retrieved_chunks])


if __name__ == "__main__":
    unittest.main()


class RagKeywordTermsTests(unittest.TestCase):
    """English keyword terms supplied by the Copilot for Bangla/Banglish questions."""

    def setUp(self) -> None:
        for name, value in (("rag_cosine_distance_enabled", True), ("rag_rrf_enabled", True)):
            flag = patch.object(rag_retrieval_settings, name, value)
            flag.start()
            self.addCleanup(flag.stop)

    def _service(self, repo):
        return RagRetrievalService(repository=repo, embedding_service=FakeEmbeddingService(), now=datetime(2026, 11, 22, tzinfo=timezone.utc))

    @staticmethod
    def _keyword_call(repo):
        return next(kwargs for name, kwargs in repo.calls if name == "keyword_search")

    def test_no_keyword_terms_keeps_existing_keywords(self):
        from app.services.rag_retrieval_service import _keywords

        seller_id = uuid4()
        question = "critical stock alert for DEMO-BATA-1"
        sent = []
        for terms in (None, ()):
            repo = FakeRepository()
            self._service(repo).retrieve_context(seller_id=seller_id, question=question, keyword_terms=terms)
            sent.append(self._keyword_call(repo)["keywords"])
        self.assertEqual(sent[0], sent[1])
        self.assertEqual(_keywords(question), sent[0])

    def test_keyword_terms_reach_keyword_search(self):
        repo = FakeRepository()
        self._service(repo).retrieve_context(seller_id=uuid4(), question="গত সপ্তাহে বিক্রি কেন কমেছে?", keyword_terms=("sales",))
        self.assertIn("sales", self._keyword_call(repo)["keywords"])

    def test_translated_term_ranks_english_chunk(self):
        seller_id = uuid4()
        row = chunk(seller_id=seller_id, source_type=RagMemorySourceType.SALES_HISTORY, text="Comfit sales fell 12 percent for SKU-77 last week")
        repo = FakeRepository(keyword_rows=[row], documents={row.memory_document_id: document_for(row)})

        without = self._service(repo).retrieve_context(seller_id=seller_id, question="sku-77 er bikri koto", min_similarity=0.45)
        with_terms = self._service(repo).retrieve_context(seller_id=seller_id, question="ek product er bikri koto", keyword_terms=("sales", "sku-77"), min_similarity=0.45)
        plain = self._service(repo).retrieve_context(seller_id=seller_id, question="ek product er bikri koto", min_similarity=0.45)

        self.assertEqual([row.id], [item.chunk_id for item in without.retrieved_chunks])  # the SKU alone already matched
        self.assertEqual([row.id], [item.chunk_id for item in with_terms.retrieved_chunks])
        self.assertEqual([], plain.retrieved_chunks)

    def test_keyword_terms_cannot_widen_seller_scope(self):
        seller_id = uuid4()
        other = chunk(seller_id=uuid4(), source_type=RagMemorySourceType.SALES_HISTORY, text="Comfit sales fell for SKU-77")
        repo = FakeRepository(keyword_rows=[other], documents={other.memory_document_id: document_for(other)})

        result = self._service(repo).retrieve_context(seller_id=seller_id, question="bikri", keyword_terms=("sales", "sku-77"), min_similarity=0.45)

        self.assertEqual([], result.retrieved_chunks)


class _FakeReranker:
    def __init__(self, scores=None) -> None:
        self.scores = scores
        self.calls: list[list[str]] = []

    def score(self, question, texts, *, budget_ms):
        self.calls.append(list(texts))
        if self.scores is None:
            return None
        return [self.scores.get(text, 0.0) for text in texts]


class RagRerankerRetrievalTests(unittest.TestCase):
    """RAG_RERANKER_ENABLED: the cross-encoder reorders the top candidates, never admits new ones."""

    def setUp(self) -> None:
        for name, value in (("rag_cosine_distance_enabled", True), ("rag_rrf_enabled", True), ("rag_reranker_enabled", True)):
            flag = patch.object(rag_retrieval_settings, name, value)
            flag.start()
            self.addCleanup(flag.stop)
        self.seller_id = uuid4()
        self.rows = [
            chunk(seller_id=self.seller_id, source_type=RagMemorySourceType.SALES_HISTORY, text=f"memory {name}")
            for name in ("first", "second", "third")
        ]

    def _repo(self, extra_vector_rows=()):
        vector_rows = [(row, distance) for row, distance in zip(self.rows, (0.1, 0.2, 0.3))] + list(extra_vector_rows)
        documents = {row.memory_document_id: document_for(row) for row, _ in vector_rows}
        return FakeRepository(vector_rows=vector_rows, documents=documents)

    def _ids(self, reranker, repo=None):
        service = RagRetrievalService(repository=repo or self._repo(), embedding_service=FakeEmbeddingService(), reranker=reranker, now=datetime(2026, 11, 22, tzinfo=timezone.utc))
        result = service.retrieve_context(seller_id=self.seller_id, question="sales memory", min_similarity=0.45, use_keyword_search=False)
        return [item.chunk_id for item in result.retrieved_chunks]

    def test_reranker_reorders_top_candidates(self):
        reranker = _FakeReranker({"memory first": 0.1, "memory second": 0.5, "memory third": 0.9})
        self.assertEqual([row.id for row in reversed(self.rows)], self._ids(reranker))

    def test_reranker_none_keeps_hybrid_order(self):
        with patch.object(rag_retrieval_settings, "rag_reranker_enabled", False):
            flag_off = self._ids(_FakeReranker())
        self.assertEqual(flag_off, self._ids(_FakeReranker(None)))

    def test_reranker_flag_off_is_never_called(self):
        reranker = _FakeReranker({})
        with patch.object(rag_retrieval_settings, "rag_reranker_enabled", False):
            self._ids(reranker)
        self.assertEqual([], reranker.calls)

    def test_reranker_cannot_admit_below_floor(self):
        weak = chunk(seller_id=self.seller_id, source_type=RagMemorySourceType.SALES_HISTORY, text="memory weak")
        reranker = _FakeReranker({"memory weak": 99.0})
        ids = self._ids(reranker, repo=self._repo([(weak, 0.9)]))
        self.assertNotIn(weak.id, ids)
        self.assertIn("memory weak", reranker.calls[0])  # it was scored, but the similarity floor still applies

    def test_reranker_only_sees_seller_chunks(self):
        other = chunk(seller_id=uuid4(), source_type=RagMemorySourceType.SALES_HISTORY, text="memory other seller")
        reranker = _FakeReranker({})
        self._ids(reranker, repo=self._repo([(other, 0.05)]))
        self.assertNotIn("memory other seller", reranker.calls[0])


class RagFullTextKeywordSearchTests(unittest.TestCase):
    """RAG_FULLTEXT_KEYWORD_ENABLED: ranked, index-backed keyword search instead of recency-ordered ILIKE."""

    @staticmethod
    def _compiled(**kwargs):
        from sqlalchemy.dialects import postgresql

        session = CaptureSession()
        result = RagMemoryRepository(session).keyword_search(**kwargs)
        if not session.calls:
            return result, None, None
        statement, _ = session.calls[0]
        compiled = statement.compile(dialect=postgresql.dialect())
        return result, str(compiled), compiled.params

    def test_fulltext_sql_uses_index_expression_and_rank(self):
        malicious = "sales' | !x & ("
        _, sql, params = self._compiled(seller_id=uuid4(), keywords=[malicious, "sku-77"], ranked=True)
        self.assertIn("to_tsvector", sql)
        self.assertIn("plainto_tsquery", sql)
        self.assertIn("ts_rank_cd", sql)
        self.assertNotIn(malicious, sql)
        self.assertIn(malicious, params.values())

    def test_fulltext_sql_is_seller_scoped(self):
        seller_id = uuid4()
        _, sql, params = self._compiled(seller_id=seller_id, keywords=["sales"], ranked=True)
        self.assertIn("rag_memory_chunks.seller_id =", sql)
        self.assertIn(seller_id, params.values())
        self.assertIn("rag_memory_chunks.deleted_at IS NULL", sql)
        self.assertIn("rag_memory_documents.deleted_at IS NULL", sql)

    def test_fulltext_skips_query_without_terms(self):
        result, sql, _ = self._compiled(seller_id=uuid4(), keywords=["", "  "], ranked=True)
        self.assertEqual([], result)
        self.assertIsNone(sql)

    def test_ilike_path_unchanged_when_flag_off(self):
        _, sql, _ = self._compiled(seller_id=uuid4(), keywords=["sales"])
        self.assertIn("ILIKE", sql.upper())
        self.assertNotIn("to_tsvector", sql)

    def test_service_passes_ranked_flag(self):
        for enabled in (False, True):
            repo = FakeRepository()
            with patch.object(rag_retrieval_settings, "rag_fulltext_keyword_enabled", enabled):
                RagRetrievalService(repository=repo, embedding_service=FakeEmbeddingService()).retrieve_context(seller_id=uuid4(), question="sales for sku-77")
            call = next(kwargs for name, kwargs in repo.calls if name == "keyword_search")
            self.assertIs(enabled, call["ranked"])


class RagGroupCapTests(unittest.TestCase):
    """RAG_MAX_CHUNKS_PER_GROUP: one (source type, product) group cannot fill every result slot."""

    @staticmethod
    def _items(groups):
        from app.services.rag_retrieval_service import _RankedChunk

        return [_RankedChunk(chunk=chunk(source_type=source_type, product_id=product_id, text=f"item {index}"), similarity_score=0.9, vector_rank=index)
                for index, (source_type, product_id) in enumerate(groups)]

    def test_group_cap_zero_is_identity(self):
        from app.services.rag_retrieval_service import _cap_per_group

        product = uuid4()
        items = self._items([(RagMemorySourceType.SALES_HISTORY, product)] * 4)
        self.assertEqual(items, _cap_per_group(items, 0))

    def test_group_cap_promotes_other_groups(self):
        from app.services.rag_retrieval_service import _cap_per_group

        product = uuid4()
        items = self._items([(RagMemorySourceType.SALES_HISTORY, product)] * 5 + [(RagMemorySourceType.INVENTORY_HISTORY, product)])
        capped = _cap_per_group(items, 2)
        self.assertEqual(RagMemorySourceType.INVENTORY_HISTORY, capped[2].chunk.source_type)
        self.assertEqual(len(items), len(capped))
        self.assertEqual([items[0], items[1]], capped[:2])

    def test_group_cap_backfills_when_only_one_group(self):
        from app.services.rag_retrieval_service import _cap_per_group

        product = uuid4()
        items = self._items([(RagMemorySourceType.SALES_HISTORY, product)] * 6)
        self.assertEqual(items[:4], _cap_per_group(items, 2)[:4])

    def test_group_cap_applies_in_retrieval_when_set(self):
        seller_id = uuid4()
        product = uuid4()
        rows = [chunk(seller_id=seller_id, product_id=product, source_type=RagMemorySourceType.SALES_HISTORY, text=f"sales row {i}") for i in range(4)]
        other = chunk(seller_id=seller_id, product_id=product, source_type=RagMemorySourceType.INVENTORY_HISTORY, text="stock row")
        vector_rows = [(row, 0.1 + i * 0.01) for i, row in enumerate(rows)] + [(other, 0.3)]
        repo = FakeRepository(vector_rows=vector_rows, documents={row.memory_document_id: document_for(row) for row, _ in vector_rows})
        service = RagRetrievalService(repository=repo, embedding_service=FakeEmbeddingService(), now=datetime(2026, 11, 22, tzinfo=timezone.utc))
        with patch.object(rag_retrieval_settings, "rag_cosine_distance_enabled", True), patch.object(rag_retrieval_settings, "rag_max_chunks_per_group", 2):
            result = service.retrieve_context(seller_id=seller_id, question="sales", top_k=3, min_similarity=0.45, use_keyword_search=False)
        self.assertIn(other.id, [item.chunk_id for item in result.retrieved_chunks])
