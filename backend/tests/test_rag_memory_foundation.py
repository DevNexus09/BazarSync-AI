from __future__ import annotations

from pathlib import Path
import importlib.util
import unittest
from uuid import uuid4

from app.models.rag_memory import RagQueryLog, RagMemoryChunk, RagMemoryDocument, RagMemorySourceType
from app.repositories.rag_memory_repository import RagMemoryDimensionError, RagMemoryRepository
from app.schemas.rag_memory import RagMemoryChunkCreate


class _EmptyResult:
    def all(self):
        return []

    def scalar_one(self):
        return 0

    def scalars(self):
        return self


class _CaptureSession:
    def __init__(self) -> None:
        self.calls: list[tuple[object, dict | None]] = []

    def execute(self, statement, params=None):
        self.calls.append((statement, params))
        return _EmptyResult()


def _load_migration_module():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "e4f5a6b7c8d9_add_rag_memory_storage.py"
    )
    spec = importlib.util.spec_from_file_location("rag_memory_migration", migration_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class RagMemoryFoundationTests(unittest.TestCase):
    def test_migration_is_reversible_and_enables_pgvector(self):
        migration = _load_migration_module()

        self.assertEqual("e4f5a6b7c8d9", migration.revision)
        self.assertEqual("d3e4f5a6b7c8", migration.down_revision)
        source = Path(migration.__file__).read_text()
        self.assertIn("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions", source)
        self.assertIn("DROP INDEX IF EXISTS ix_rag_memory_chunks_embedding_hnsw", source)
        self.assertIn("op.drop_table(\"rag_memory_chunks\")", source)
        self.assertIn("op.drop_table(\"rag_memory_documents\")", source)
        self.assertIn("rag_query_logs", source)

    def test_duplicate_constraints_are_declared_on_models(self):
        document_constraints = {constraint.name for constraint in RagMemoryDocument.__table__.constraints}
        chunk_constraints = {constraint.name for constraint in RagMemoryChunk.__table__.constraints}

        self.assertIn("uq_rag_memory_documents_source_hash", document_constraints)
        self.assertIn("uq_rag_memory_chunks_document_index_hash", chunk_constraints)

    def test_query_log_audit_model_is_declared(self):
        self.assertEqual("rag_query_logs", RagQueryLog.__tablename__)
        column_names = {column.name for column in RagQueryLog.__table__.columns}
        self.assertIn("seller_id", column_names)
        self.assertIn("evidence_ids", column_names)
        self.assertIn("prompt_version", column_names)

    def test_vector_dimension_validation_rejects_wrong_size_when_configured(self):
        repository = RagMemoryRepository(_CaptureSession(), embedding_dimension=3)
        with self.assertRaises(RagMemoryDimensionError):
            repository.vector_search(seller_id=uuid4(), query_embedding=[0.1, 0.2])

    def test_vector_search_is_seller_scoped_and_supports_source_filters(self):
        session = _CaptureSession()
        repository = RagMemoryRepository(session)
        seller_id = uuid4()
        product_id = uuid4()

        result = repository.vector_search(
            seller_id=seller_id,
            product_id=product_id,
            source_types=[RagMemorySourceType.PRODUCT_PROFILE],
            query_embedding=[0.01, 0.02, 0.03],
            limit=5,
        )

        self.assertEqual([], result)
        statement, params = session.calls[0]
        sql = str(statement)
        self.assertIn("JOIN rag_memory_documents", sql)
        self.assertIn("WHERE c.seller_id = :seller_id", sql)
        self.assertIn("d.deleted_at IS NULL", sql)
        self.assertIn("c.source_type::text IN", sql)
        self.assertEqual(seller_id, params["seller_id"])
        self.assertEqual(product_id, params["product_id"])
        self.assertEqual(["PRODUCT_PROFILE"], params["source_types"])

    def test_hybrid_metadata_filter_search_keeps_seller_filter(self):
        session = _CaptureSession()
        repository = RagMemoryRepository(session)
        seller_id = uuid4()

        rows, total = repository.hybrid_metadata_filter_search(
            seller_id=seller_id,
            metadata_contains={"source": "pricing"},
        )

        self.assertEqual([], rows)
        self.assertEqual(0, total)
        first_statement, _ = session.calls[0]
        compiled = str(first_statement)
        self.assertIn("rag_memory_chunks.seller_id", compiled)
        self.assertIn("rag_memory_documents.deleted_at", compiled)
        self.assertIn("rag_memory_chunks.metadata_json", compiled)


if __name__ == "__main__":
    unittest.main()
