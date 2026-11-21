from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from kombu.exceptions import OperationalError as BrokerError
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.ai.recommendation_generator import RecommendationTimeoutError
from app.api.v1 import recommendations
from app.core.config import settings
from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.dependencies.events import get_dashboard_event_emitter
from app.models.rag_index_outbox import RagIndexOutbox
from app.models.recommendation import Recommendation
from app.models.recommendation_job import RecommendationJob
from app.services import recommendation_jobs as lifecycle
from app.services.recommendation_service import (
    AIRecommendationError,
    RecommendationService,
)
from app.tasks import rag_memory_tasks, recommendation_tasks
from test_recommendation_evidence import _product

pytest_plugins = ("test_recommendation_evidence",)


@pytest.fixture
def runtime(db, monkeypatch):
    product = _product(db)
    authenticated = SimpleNamespace(id=product.seller_id)
    timestamp = [datetime.now(timezone.utc)]
    monkeypatch.setattr(lifecycle, "_now", lambda: timestamp[0])
    monkeypatch.setattr(settings, "recommendation_jobs_enabled", True)
    monkeypatch.setattr(recommendation_tasks, "SessionLocal", db)
    monkeypatch.setattr(
        RecommendationService,
        "prepare_recommendation",
        lambda *_args, **_kwargs: (
            {},
            {
                "business_signals_version": 1,
                "action": "HOLD",
                "confidence": 0.0,
                "reason_codes": [],
                "inventory_evidence": {"demand_status": "INSUFFICIENT"},
            },
            None,
        ),
    )
    publish = Mock()
    monkeypatch.setattr(recommendations.celery_app, "send_task", publish)
    notify = AsyncMock(side_effect=RuntimeError("optional delivery failed"))
    monkeypatch.setattr(RecommendationService, "_emit_recommendation_created", notify)

    app = FastAPI()
    app.include_router(recommendations.router, prefix="/api/v1")

    def get_test_session():
        with db() as session:
            yield session

    app.dependency_overrides[get_db] = get_test_session
    app.dependency_overrides[get_current_seller] = lambda: authenticated
    app.dependency_overrides[get_dashboard_event_emitter] = lambda: Mock()

    return SimpleNamespace(
        db=db,
        product=product,
        app=app,
        auth=authenticated,
        publish=publish,
        timestamp=timestamp,
        notify=notify,
    )


def _submit(client, product_id, key=None):
    return client.post(
        f"/api/v1/recommendations/generate/{product_id}",
        headers={"Idempotency-Key": str(key)} if key else {},
    )


def _status(client, job_id):
    return client.get(f"/api/v1/recommendations/jobs/{job_id}")


def test_simultaneous_requests_coalesce_and_keys_survive_completion(runtime):
    first_key, second_key = uuid4(), uuid4()
    barrier = Barrier(2)

    def submit(key):
        with TestClient(runtime.app) as client:
            barrier.wait(timeout=5)
            response = _submit(client, runtime.product.id, key)
            assert response.status_code == 202, response.text
            return response.json()["job_id"]

    with ThreadPoolExecutor(2) as executor:
        first, second = list(executor.map(submit, (first_key, second_key)))
    assert first == second
    runtime.publish.assert_called_once()
    recommendation_tasks.run_recommendation_job.run(first)
    recommendation_tasks.run_recommendation_job.run(first)
    runtime.notify.assert_awaited_once()

    with TestClient(runtime.app) as client:
        completed = _status(client, first).json()
        assert completed["status"] == "COMPLETED"
        assert completed["attempts"] == 1
        assert completed["result"]["recommendation"]["action"] == "HOLD"
        assert _submit(client, runtime.product.id, first_key).json()["job_id"] == first
        assert _submit(client, runtime.product.id, second_key).json()["job_id"] == first
        assert _submit(client, runtime.product.id, uuid4()).json()["job_id"] != first
        assert _status(client, first).json()["result"] == completed["result"]
    with runtime.db() as session:
        assert session.scalar(select(func.count()).select_from(Recommendation)) == 1
        assert session.scalar(select(func.count()).select_from(RagIndexOutbox)) == 1


def test_broker_failure_and_worker_restart_recover_with_a_fenced_attempt(runtime):
    runtime.publish.side_effect = BrokerError("do not expose broker connection")
    with TestClient(runtime.app) as client:
        queued = _submit(client, runtime.product.id).json()
        job_id = queued["job_id"]
        assert _status(client, job_id).json()["status"] == "PENDING"
    runtime.publish.side_effect = None
    runtime.timestamp[0] += lifecycle.DISPATCH_DELAY
    assert recommendation_tasks.recover_recommendation_jobs.run() == 1
    with runtime.db() as session:
        crashed = lifecycle.RecommendationJobs(session).claim(UUID(job_id))
        assert crashed.number == 1
    recommendation_tasks.run_recommendation_job.run(job_id)
    runtime.notify.assert_not_called()
    runtime.timestamp[0] += lifecycle.LEASE
    recommendation_tasks.recover_recommendation_jobs.run()
    recommendation_tasks.run_recommendation_job.run(job_id)
    with runtime.db() as session:
        assert not lifecycle.RecommendationJobs(session).can_complete(crashed)
    with TestClient(runtime.app) as client:
        status = _status(client, job_id).json()
        assert status["status"] == "COMPLETED"
        assert status["attempts"] == 2


def test_expired_pending_job_becomes_visible_failure_and_can_be_retried(runtime):
    with TestClient(runtime.app) as client:
        job_id = _submit(client, runtime.product.id).json()["job_id"]
        runtime.timestamp[0] += lifecycle.JOB_LIFETIME
        failed = _status(client, job_id).json()
        assert failed["status"] == "FAILED"
        assert failed["error_code"] == "generation_expired"
        assert _submit(client, runtime.product.id).json()["job_id"] != job_id


def test_permanent_and_transient_failures_are_sanitized(runtime, monkeypatch):
    def legacy_analytics(*_args, **_kwargs):
        return {}, {}, None

    async def timeout(*_args, **_kwargs):
        raise AIRecommendationError("sensitive prompt") from RecommendationTimeoutError(
            "private upstream", retryable=True
        )

    monkeypatch.setattr(
        RecommendationService, "prepare_recommendation", legacy_analytics
    )
    monkeypatch.setattr(RecommendationService, "generate_ai_recommendation", timeout)
    with TestClient(runtime.app) as client:
        job_id = _submit(client, runtime.product.id).json()["job_id"]
        for attempt in range(lifecycle.MAX_ATTEMPTS):
            recommendation_tasks.run_recommendation_job.run(job_id)
            status = _status(client, job_id).json()
            assert status["attempts"] == attempt + 1
            assert status["status"] == (
                "FAILED" if attempt == lifecycle.MAX_ATTEMPTS - 1 else "PENDING"
            )
            runtime.timestamp[0] += lifecycle.DISPATCH_DELAY
        assert status["error_code"] == "ai_generation_failed"
        assert "private" not in status["error_message"]
        monkeypatch.setattr(
            RecommendationService,
            "generate_ai_recommendation",
            AsyncMock(
                side_effect=recommendations.AnalyticsExecutionError(
                    "private seller data"
                )
            ),
        )
        job_id = _submit(client, runtime.product.id).json()["job_id"]
        recommendation_tasks.run_recommendation_job.run(job_id)
        recommendation_tasks.run_recommendation_job.run(job_id)
        status = _status(client, job_id).json()
        assert (status["status"], status["attempts"], status["error_code"]) == (
            "FAILED",
            1,
            "analytics_failure",
        )


def test_storage_failure_rolls_back_recommendation_and_retries(runtime, monkeypatch):
    from app.services.rag_index_outbox_service import RagIndexOutboxService as Outbox

    enqueue = Outbox.enqueue_upsert
    monkeypatch.setattr(
        Outbox,
        "enqueue_upsert",
        Mock(side_effect=OperationalError("insert", {}, Exception("connection"))),
    )
    with TestClient(runtime.app) as client:
        job_id = _submit(client, runtime.product.id).json()["job_id"]
        recommendation_tasks.run_recommendation_job.run(job_id)
        assert _status(client, job_id).json()["status"] == "PENDING"
        with runtime.db() as session:
            assert session.scalar(select(Recommendation)) is None
        monkeypatch.setattr(Outbox, "enqueue_upsert", enqueue)
        runtime.timestamp[0] += lifecycle.DISPATCH_DELAY
        recommendation_tasks.run_recommendation_job.run(job_id)
        assert _status(client, job_id).json()["status"] == "COMPLETED"


def test_async_rag_failure_and_retry_do_not_change_completed_job(runtime, monkeypatch):
    monkeypatch.setattr(rag_memory_tasks, "SessionLocal", runtime.db)
    index = Mock(side_effect=RuntimeError("index unavailable"))
    monkeypatch.setattr(
        rag_memory_tasks.RagMemoryBackfillService, "reindex_source_record", index
    )
    with TestClient(runtime.app) as client:
        job_id = _submit(client, runtime.product.id).json()["job_id"]
        recommendation_tasks.run_recommendation_job.run(job_id)
        failed = rag_memory_tasks._process_rag_index_outbox_batch(
            seller_id=str(runtime.product.seller_id),
            batch_size=1,
            include_failed=False,
        )
        assert failed["failed_count"] == 1
        assert _status(client, job_id).json()["status"] == "COMPLETED"
        with runtime.db.begin() as session:
            event = session.scalar(select(RagIndexOutbox))
            event.next_attempt_at = datetime.now(timezone.utc)
        index.side_effect = None
        index.return_value = SimpleNamespace(
            failed_count=0, skipped_count=0, soft_deleted_count=0
        )
        recovered = rag_memory_tasks._process_rag_index_outbox_batch(
            seller_id=str(runtime.product.seller_id),
            batch_size=1,
            include_failed=True,
        )
        assert recovered["completed_count"] == 1
        assert _status(client, job_id).json()["status"] == "COMPLETED"


def test_invalid_product_cross_seller_status_and_worker_ownership(runtime):
    other = _product(runtime.db)
    with TestClient(runtime.app) as client:
        assert _submit(client, uuid4()).status_code == 404
        job_id = _submit(client, runtime.product.id).json()["job_id"]
        runtime.auth.id = other.seller_id
        assert _status(client, job_id).status_code == 404
        assert _submit(client, runtime.product.id).status_code == 404
        with runtime.db.begin() as session:
            session.get(RecommendationJob, UUID(job_id)).seller_id = other.seller_id
        recommendation_tasks.run_recommendation_job.run(job_id)
        with runtime.db() as session:
            job = session.get(RecommendationJob, UUID(job_id))
            assert (job.status, job.error_code) == ("FAILED", "product_not_found")
            assert session.scalar(select(Recommendation)) is None
