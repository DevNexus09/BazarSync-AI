from __future__ import annotations

import threading
import time

from app.services.rag_reranker_service import RagRerankerService


class _LengthModel:
    def __init__(self, delay_s: float = 0.0) -> None:
        self.delay_s = delay_s

    def predict(self, pairs):
        time.sleep(self.delay_s)
        return [float(len(text)) for _, text in pairs]


def _loaded(model) -> RagRerankerService:
    service = RagRerankerService(loader=lambda: model)
    service.score("warm", ["x"], budget_ms=1000)
    assert service.wait_until_loaded(timeout_s=2)
    return service


def test_reranker_skips_while_model_loading():
    release = threading.Event()

    def slow_loader():
        release.wait(5)
        return _LengthModel()

    service = RagRerankerService(loader=slow_loader)
    started = time.perf_counter()
    assert service.score("q", ["aa", "b"], budget_ms=1000) is None
    assert (time.perf_counter() - started) < 0.05
    release.set()
    assert service.wait_until_loaded(timeout_s=2)
    assert service.score("q", ["aa", "b"], budget_ms=1000) == [2.0, 1.0]


def test_reranker_returns_none_over_budget():
    service = _loaded(_LengthModel(delay_s=0.03))
    assert service.score("q", [f"text {i}" for i in range(12)], budget_ms=40) is None


def test_reranker_returns_none_when_load_fails():
    calls = []

    def broken_loader():
        calls.append(1)
        raise RuntimeError("model missing")

    service = RagRerankerService(loader=broken_loader)
    assert service.score("q", ["a"], budget_ms=1000) is None
    service.wait_until_loaded(timeout_s=2)
    assert service.score("q", ["a"], budget_ms=1000) is None
    assert len(calls) == 1


def test_reranker_scores_align_with_texts():
    service = _loaded(_LengthModel())
    assert service.score("q", ["abc", "a", "ab", "abcde", "abcd"], budget_ms=1000) == [3.0, 1.0, 2.0, 5.0, 4.0]


def test_reranker_empty_texts_returns_none():
    service = _loaded(_LengthModel())
    assert service.score("q", [], budget_ms=1000) is None


class _CountingModel(_LengthModel):
    def __init__(self, delay_s: float = 0.0) -> None:
        super().__init__(delay_s)
        self.calls = 0

    def predict(self, pairs):
        self.calls += 1
        return super().predict(pairs)


def test_reranker_skips_batch_predicted_over_budget():
    model = _CountingModel(delay_s=0.03)
    service = _loaded(model)
    model.calls = 0
    assert service.score("q", [f"text {i}" for i in range(8)], budget_ms=45) is None
    assert model.calls == 1  # the second 30 ms batch would end past 45 ms, so it never starts


def test_reranker_returns_none_when_model_busy():
    started, release = threading.Event(), threading.Event()

    class BlockingModel:
        def predict(self, pairs):
            started.set()
            release.wait(5)
            return [1.0 for _ in pairs]

    service = _loaded(BlockingModel())
    # _loaded's warm call already returned; now occupy the model from another thread.
    worker = threading.Thread(target=service.score, args=("q", ["a"]), kwargs={"budget_ms": 10_000})
    started.clear()
    worker.start()
    assert started.wait(2)
    began = time.perf_counter()
    assert service.score("q", ["b"], budget_ms=10_000) is None
    assert (time.perf_counter() - began) < 0.05
    release.set()
    worker.join(2)


def test_default_loader_never_downloads():
    from unittest.mock import patch

    captured = {}

    class FakeCrossEncoder:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

    with patch("sentence_transformers.CrossEncoder", FakeCrossEncoder):
        RagRerankerService(model_name="any/model")._load_cross_encoder()
    assert captured.get("local_files_only") is True
