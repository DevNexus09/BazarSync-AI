from __future__ import annotations

import hashlib
import re

from app.core.config import settings
from app.models.rag_memory import RagMemoryDocument
from app.schemas.rag_memory import RagMemoryChunkCreate


class RagChunkingError(ValueError):
    pass


class RagChunkingService:
    def __init__(
        self,
        *,
        max_chunk_chars: int | None = None,
        overlap_chars: int | None = None,
        chunking_version: str | None = None,
    ) -> None:
        self.max_chunk_chars = max_chunk_chars if max_chunk_chars is not None else settings.rag_max_chunk_chars
        self.overlap_chars = overlap_chars if overlap_chars is not None else settings.rag_chunk_overlap_chars
        self.chunking_version = chunking_version or settings.rag_chunking_version
        if self.max_chunk_chars <= 0:
            raise RagChunkingError("max_chunk_chars must be positive")
        if self.overlap_chars < 0:
            raise RagChunkingError("overlap_chars cannot be negative")
        if self.overlap_chars >= self.max_chunk_chars:
            raise RagChunkingError("overlap_chars must be smaller than max_chunk_chars")

    def chunk_document(self, document: RagMemoryDocument) -> list[RagMemoryChunkCreate]:
        text = _normalize_whitespace(document.content_text)
        if not text:
            raise RagChunkingError("Cannot chunk empty memory document content")

        chunks = self.chunk_text(text)
        payloads: list[RagMemoryChunkCreate] = []
        for index, chunk_text in enumerate(chunks):
            content_hash = hashlib.sha256(
                f"{document.content_hash}:{self.chunking_version}:{index}:{chunk_text}".encode("utf-8")
            ).hexdigest()
            metadata = dict(document.metadata_json or {})
            metadata.update(
                {
                    "document_title": document.title,
                    "source_table": document.source_table,
                    "source_id": document.source_id,
                    "source_version": document.source_version,
                    "document_content_hash": document.content_hash,
                    "chunking_version": self.chunking_version,
                }
            )
            payloads.append(
                RagMemoryChunkCreate(
                    seller_id=document.seller_id,
                    memory_document_id=document.id,
                    product_id=document.product_id,
                    source_type=document.source_type,
                    chunk_index=index,
                    chunk_text=chunk_text,
                    token_estimate=self.estimate_tokens_or_length(chunk_text),
                    metadata_json=metadata,
                    event_time=document.event_time,
                    content_hash=content_hash,
                )
            )
        return payloads

    def chunk_text(self, text: str) -> list[str]:
        normalized = _normalize_whitespace(text)
        if not normalized:
            raise RagChunkingError("Cannot chunk empty text")
        if len(normalized) <= self.max_chunk_chars:
            return [normalized]

        chunks: list[str] = []
        start = 0
        while start < len(normalized):
            end = min(start + self.max_chunk_chars, len(normalized))
            if end < len(normalized):
                end = _best_boundary(normalized, start, end)
            chunk = normalized[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(normalized):
                break
            next_start = max(0, end - self.overlap_chars)
            if next_start <= start:
                next_start = end
            start = _advance_to_safe_start(normalized, next_start)
        return chunks

    def estimate_tokens_or_length(self, text: str) -> int:
        normalized = _normalize_whitespace(text)
        if not normalized:
            return 0
        return max(1, len(re.findall(r"\S+", normalized)))


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _best_boundary(text: str, start: int, proposed_end: int) -> int:
    window_start = max(start + 1, proposed_end - 180)
    candidates = [
        text.rfind(". ", window_start, proposed_end),
        text.rfind("; ", window_start, proposed_end),
        text.rfind(", ", window_start, proposed_end),
        text.rfind(" ", window_start, proposed_end),
    ]
    boundary = max(candidates)
    if boundary <= start:
        return proposed_end
    return boundary + 1


def _advance_to_safe_start(text: str, start: int) -> int:
    while start < len(text) and text[start].isspace():
        start += 1
    while start < len(text) and start > 0 and text[start - 1].isalnum() and text[start].isalnum():
        start += 1
    return start
