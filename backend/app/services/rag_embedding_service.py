from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import math
import re
import threading
from typing import Protocol
from uuid import UUID

from app.core.config import settings
from app.models.rag_memory import RagMemoryChunk
from app.repositories.rag_memory_repository import RagMemoryRepository
from app.services.rag_observability import elapsed_ms, increment_metric, log_event, now_ms, observe_latency

logger = logging.getLogger(__name__)


class RagEmbeddingError(RuntimeError):
    pass


class EmbeddingBackend(Protocol):
    def encode(self, texts: list[str], *, normalize_embeddings: bool) -> list[list[float]]:
        ...


@dataclass(slots=True)
class RagEmbeddingResult:
    embedded_count: int = 0
    failed_count: int = 0
    dimension: int | None = None
    model: str | None = None


class LocalBgeBackend:
    def __init__(self, *, model_name: str, device: str) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name, device=device)

    def encode(self, texts: list[str], *, normalize_embeddings: bool) -> list[list[float]]:
        vectors = self._model.encode(
            texts,
            batch_size=len(texts),
            normalize_embeddings=normalize_embeddings,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [[float(value) for value in vector.tolist()] for vector in vectors]


_MODEL_LOCK = threading.Lock()
_MODEL_CACHE: dict[tuple[str, str, str], EmbeddingBackend] = {}


class RagEmbeddingService:
    def __init__(
        self,
        *,
        provider: str | None = None,
        model_name: str | None = None,
        batch_size: int | None = None,
        device: str | None = None,
        normalize: bool | None = None,
        embedding_version: str | None = None,
        backend: EmbeddingBackend | None = None,
        log: logging.Logger | None = None,
    ) -> None:
        self.provider = (provider or settings.rag_embedding_provider).lower()
        self.model_name = model_name or settings.rag_embedding_model
        self.batch_size = batch_size or settings.rag_embedding_batch_size
        self.device = device or settings.rag_embedding_device
        self.normalize = settings.rag_embedding_normalize if normalize is None else normalize
        self.embedding_version = embedding_version or settings.rag_embedding_version
        self._backend = backend
        self._log = log or logger
        if self.batch_size <= 0:
            raise RagEmbeddingError("RAG_EMBEDDING_BATCH_SIZE must be positive")

    def load_model(self) -> EmbeddingBackend:
        if self._backend is not None:
            return self._backend
        if self.provider != "local_bge":
            raise RagEmbeddingError(
                "Only local_bge embedding provider is enabled. Third-party embedding APIs require explicit implementation."
            )
        cache_key = (self.provider, self.model_name, self.device)
        with _MODEL_LOCK:
            backend = _MODEL_CACHE.get(cache_key)
            if backend is None:
                backend = LocalBgeBackend(model_name=self.model_name, device=self.device)
                _MODEL_CACHE[cache_key] = backend
            self._backend = backend
            return backend

    def embed_text(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        normalized = [self.normalize_text(text) for text in texts]
        if any(not text for text in normalized):
            raise RagEmbeddingError("Cannot embed empty text")
        backend = self.load_model()
        vectors = backend.encode(normalized, normalize_embeddings=self.normalize)
        for vector in vectors:
            self.validate_dimension(vector)
        return vectors

    def embed_pending_chunks(
        self,
        *,
        repository: RagMemoryRepository,
        seller_id: UUID | None = None,
        source_type=None,
        limit: int | None = None,
    ) -> RagEmbeddingResult:
        start_ms = now_ms()
        chunks = repository.find_unembedded_chunks(
            seller_id=seller_id,
            source_type=source_type,
            limit=limit or settings.rag_unembedded_chunk_batch_size,
        )
        result = RagEmbeddingResult(model=self.model_name)
        for index in range(0, len(chunks), self.batch_size):
            batch = chunks[index : index + self.batch_size]
            try:
                vectors = self.embed_batch([chunk.chunk_text for chunk in batch])
                updates = []
                embedded_at = datetime.now(timezone.utc)
                for chunk, vector in zip(batch, vectors, strict=True):
                    dimension = len(vector)
                    updates.append(
                        (
                            chunk.id,
                            vector,
                            self.model_name,
                            dimension,
                            self.embedding_version,
                            embedded_at,
                        )
                    )
                    result.dimension = dimension
                result.embedded_count += repository.mark_chunks_embedded(updates=updates)
                repository.update_document_embedding_statuses(
                    document_ids=[chunk.memory_document_id for chunk in batch]
                )
                log_event(
                    self._log,
                    logging.INFO,
                    "rag_embedding_success",
                    chunk_count=len(batch),
                    embedded_count=result.embedded_count,
                    model=self.model_name,
                    dimension=result.dimension,
                    seller_id=seller_id,
                    source_type=getattr(source_type, "value", source_type),
                )
            except Exception as exc:
                reason = _sanitize_failure_reason(exc)
                chunk_ids = [chunk.id for chunk in batch]
                result.failed_count += repository.mark_chunks_failed(
                    chunk_ids=chunk_ids,
                    failure_reason=reason,
                )
                increment_metric("rag_embedding_failures_total", len(chunk_ids))
                repository.update_document_embedding_statuses(
                    document_ids=[chunk.memory_document_id for chunk in batch]
                )
                log_event(
                    self._log,
                    logging.WARNING,
                    "rag_embedding_failure",
                    chunk_count=len(batch),
                    reason=reason,
                    seller_id=seller_id,
                    source_type=getattr(source_type, "value", source_type),
                )
        duration_ms = elapsed_ms(start_ms)
        observe_latency("rag_embedding_job_duration_ms", duration_ms)
        log_event(
            self._log,
            logging.INFO,
            "rag_embedding_job_completed",
            duration_ms=duration_ms,
            embedded=result.embedded_count,
            failed=result.failed_count,
            seller_id=seller_id,
            source_type=getattr(source_type, "value", source_type),
        )
        return result

    def validate_dimension(self, vector: list[float]) -> int:
        if not vector:
            raise RagEmbeddingError("Embedding vector cannot be empty")
        if any(not math.isfinite(value) for value in vector):
            raise RagEmbeddingError("Embedding vector contains non-finite values")
        return len(vector)

    def normalize_text(self, text: str) -> str:
        normalized = re.sub(r"\s+", " ", text or "").strip()
        if len(normalized) > settings.rag_max_chunk_chars:
            normalized = normalized[: settings.rag_max_chunk_chars].strip()
        return normalized

    def estimate_tokens_or_length(self, text: str) -> int:
        normalized = self.normalize_text(text)
        if not normalized:
            return 0
        return max(1, len(re.findall(r"\S+", normalized)))

    def health_check(self) -> dict[str, str | int | bool]:
        vector = self.embed_text("health check")
        return {
            "provider": self.provider,
            "model": self.model_name,
            "device": self.device,
            "normalize": self.normalize,
            "dimension": len(vector),
            "status": "ok",
        }


def _sanitize_failure_reason(exc: BaseException) -> str:
    text = str(exc) or exc.__class__.__name__
    text = re.sub(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*\S+", r"\1=[REDACTED]", text)
    text = re.sub(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[REDACTED_EMAIL]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:255] or "embedding_failed"
