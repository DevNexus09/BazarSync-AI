"""Cross-encoder reranking for RAG memory retrieval (RAG_RERANKER_ENABLED).

A request never waits for the model: the first call starts loading it on a background thread
and returns None until it is ready. Scoring is time-budgeted, because the Copilot memory tool
discards its whole result when it runs past its runtime limit. Every failure returns None, and
the caller then keeps its existing order.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
import logging
import threading
import time
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

BATCH_SIZE = 4


@dataclass
class _ModelSlot:
    model: Any = None
    failed: bool = False
    thread: threading.Thread | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    # One request scores at a time: concurrent CPU inference slows every request past its budget,
    # and the shared fast tokenizer is not safe to call from several threads.
    predict_lock: threading.Lock = field(default_factory=threading.Lock)


_SLOTS: dict[tuple[str, str, int], _ModelSlot] = {}
_SLOTS_LOCK = threading.Lock()


class RagRerankerService:
    def __init__(
        self,
        *,
        model_name: str | None = None,
        device: str | None = None,
        max_length: int | None = None,
        loader: Callable[[], Any] | None = None,
    ) -> None:
        self.model_name = model_name or settings.rag_reranker_model
        self.device = device or settings.rag_embedding_device
        self.max_length = max_length or settings.rag_reranker_max_length
        if loader is not None:
            # An injected loader gets its own slot, so tests never share the process-wide model.
            self._loader = loader
            self._slot = _ModelSlot()
        else:
            self._loader = self._load_cross_encoder
            key = (self.model_name, self.device, self.max_length)
            with _SLOTS_LOCK:
                self._slot = _SLOTS.setdefault(key, _ModelSlot())

    def score(self, question: str, texts: Sequence[str], *, budget_ms: int) -> list[float] | None:
        """One relevance score per text, or None (not loaded yet, failed, empty input, over budget)."""
        if not texts:
            return None
        self._ensure_loading()
        model = self._slot.model
        if model is None:
            return None
        if not self._slot.predict_lock.acquire(blocking=False):
            logger.info("rag_rerank_busy model=%s", self.model_name)
            return None
        started = time.perf_counter()
        scores: list[float] = []
        try:
            for offset in range(0, len(texts), BATCH_SIZE):
                batch_started = time.perf_counter()
                batch = [(question, text) for text in texts[offset : offset + BATCH_SIZE]]
                scores.extend(float(value) for value in model.predict(batch))
                now = time.perf_counter()
                elapsed_ms = (now - started) * 1000
                more = offset + BATCH_SIZE < len(texts)
                # Stop before a batch that would likely end past the budget, not only after one that did.
                if elapsed_ms > budget_ms or (more and elapsed_ms + (now - batch_started) * 1000 > budget_ms):
                    logger.info("rag_rerank_over_budget scored=%s of=%s budget_ms=%s", len(scores), len(texts), budget_ms)
                    return None
        except Exception:  # noqa: BLE001 - reranking is optional; the hybrid order still answers
            logger.exception("rag_rerank_failed model=%s", self.model_name)
            return None
        finally:
            self._slot.predict_lock.release()
        return scores

    def wait_until_loaded(self, *, timeout_s: float) -> bool:
        """For offline tools (the eval harness, warm-up scripts); request code never calls this."""
        self._ensure_loading()
        thread = self._slot.thread
        if thread is not None:
            thread.join(timeout_s)
        return self._slot.model is not None

    def _ensure_loading(self) -> None:
        slot = self._slot
        with slot.lock:
            if slot.model is not None or slot.failed or slot.thread is not None:
                return
            slot.thread = threading.Thread(target=self._load, name="rag-reranker-load", daemon=True)
            slot.thread.start()

    def _load(self) -> None:
        try:
            model = self._loader()
        except Exception:  # noqa: BLE001 - a missing model disables reranking, it must not break retrieval
            logger.exception("rag_reranker_load_failed model=%s", self.model_name)
            self._slot.failed = True
            return
        self._slot.model = model
        logger.info("rag_reranker_loaded model=%s device=%s", self.model_name, self.device)

    def _load_cross_encoder(self) -> Any:
        from sentence_transformers import CrossEncoder

        # Never download inside the API process; pre-download the model on the host (see rag-retrieval-eval.md).
        return CrossEncoder(self.model_name, device=self.device, max_length=self.max_length, local_files_only=True)
