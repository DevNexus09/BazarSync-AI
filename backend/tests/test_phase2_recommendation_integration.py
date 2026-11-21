from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import event, select, update

from app.api.v1 import recommendations
from app.core.config import settings
from app.models.dead_stock_assessment import DeadStockAssessment
from app.models.demand_elasticity_estimate import DemandElasticityEstimate
from app.models.pricing_policy import PricingPolicy
from app.models.rag_index_outbox import RagIndexOutbox
from app.models.recommendation import Recommendation
from app.services.margin_guard import MarginGuard
from app.tasks import recommendation_tasks
from test_decision_orchestrator import MARKETPLACE, _client, _evaluations, _seed

pytest_plugins = ("test_decision_orchestrator",)


def _generate(client, product_id):
    queued = client.post(
        f"/api/v1/recommendations/generate/{product_id}",
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert queued.status_code == 202, queued.text
    job_id = queued.json()["job_id"]
    recommendation_tasks.run_recommendation_job.run(job_id)
    result = client.get(f"/api/v1/recommendations/jobs/{job_id}").json()
    assert result["status"] == "COMPLETED", result
    return job_id, result["result"]


def test_worker_rejects_both_pricing_and_stock_consuming_recovery_when_reordering(
    decision_db,
    monkeypatch,
):
    monkeypatch.setattr(settings, "recommendation_action_evaluation_enabled", True)
    product, _ = _seed(decision_db, stock=30)
    with decision_db.begin() as session:
        session.execute(
            update(DeadStockAssessment)
            .where(DeadStockAssessment.product_id == product.id)
            .values(eligible_quantity=20, inventory_age_days=240)
        )
    with _client(decision_db, product.seller_id) as client:
        job_id, visible = _generate(client, product.id)
        assert visible["recommendation"]["action"] == "REORDER"
        recommendation_tasks.run_recommendation_job.run(job_id)
    with decision_db() as session:
        row = session.scalars(select(Recommendation)).one()
        session.scalars(select(RagIndexOutbox)).one()
        decision = row.recommendation_context["decision_orchestration"]
    outcomes = _evaluations(decision)
    assert outcomes["reorder"]["candidate"]["evaluation_status"] == "selected"
    assert (
        outcomes["dead_stock_recovery"]["candidate"]["proposed_parameters"]["action"]
        == "BUNDLE"
    )
    for engine in ("dynamic_pricing", "dead_stock_recovery"):
        assert outcomes[engine]["action_evaluation"]["eligible"]
        assert outcomes[engine]["candidate"]["rejection_reasons"] == [
            "INCOMPATIBLE_WITH_PRIMARY_ACTION"
        ]
    assert decision["supporting_candidate_ids"] == []
    assert decision["supporting_advice"][0]["scope"] == "base_price"


def test_worker_uses_sales_horizon_and_effective_increment_then_rolls_back_by_flag(
    decision_db,
    monkeypatch,
):
    monkeypatch.setattr(settings, "recommendation_action_evaluation_enabled", True)
    monkeypatch.setattr(settings, "sales_velocity_default_window_days", 30)
    product, _ = _seed(decision_db, stock=1000)
    with decision_db.begin() as session:
        session.execute(
            update(DemandElasticityEstimate)
            .where(DemandElasticityEstimate.product_id == product.id)
            .values(baseline_units=Decimal("0.5"))
        )
        session.add(
            PricingPolicy(
                seller_id=product.seller_id,
                product_id=product.id,
                marketplace=MARKETPLACE,
                minimum_margin_rate=Decimal("0.10"),
                price_increment=Decimal("0.03"),
                effective_from=datetime.now(timezone.utc) - timedelta(days=1),
            )
        )

    guard_calls = Counter()
    query_counts = Counter()
    original = MarginGuard._validate_candidate

    def track_guard(
        guard, seller_id, owned_product, candidate, marketplace, round_down_to_increment
    ):
        guard_calls[(guard, candidate)] += 1
        return original(
            guard,
            seller_id,
            owned_product,
            candidate,
            marketplace,
            round_down_to_increment,
        )

    def track_sql(_connection, _cursor, sql, _params, _context, _many):
        for table in ("pricing_policies", "marketplace_fee_policies"):
            if f"FROM {table}" in sql:
                query_counts[table] += 1

    monkeypatch.setattr(MarginGuard, "_validate_candidate", track_guard)
    engine = decision_db.kw["bind"]
    with _client(decision_db, product.seller_id) as client:
        event.listen(engine, "before_cursor_execute", track_sql)
        try:
            job_id, active = _generate(client, product.id)
        finally:
            event.remove(engine, "before_cursor_execute", track_sql)
        assert active["recommendation"]["action"] == "RAISE"
        assert set(active["recommendation"]) == {
            "action",
            "confidence",
            "reasoning_bn",
            "revenue_opportunity",
        }
        assert query_counts["pricing_policies"] == 2
        assert query_counts["marketplace_fee_policies"] == 2
        assert max(guard_calls.values()) == 1

        with decision_db() as session:
            row = session.scalars(select(Recommendation)).one()
            decision = row.recommendation_context["decision_orchestration"]
            assert (
                row.suggested_price_min == row.suggested_price_max == Decimal("549.99")
            )
        outcomes = _evaluations(decision)
        pricing = outcomes["dynamic_pricing"]
        baseline = pricing["candidate"]["evidence"]["snapshot"]["selected"][
            "baseline_period"
        ]
        assert Decimal(baseline["baseline_units"]) == 100
        assert baseline["horizon_days"] == 30
        assert baseline["source"] == "observed_window_net_sales"
        assert pricing["candidate"]["candidate_id"] == decision["primary_candidate_id"]
        recovery = outcomes["dead_stock_recovery"]["candidate"]
        assert recovery["proposed_parameters"]["action"] == "SEO_FIX"
        assert recovery["candidate_id"] in decision["supporting_candidate_ids"]

        monkeypatch.setattr(settings, "recommendation_orchestration_enabled", False)
        recommendations.celery_app.send_task.return_value = SimpleNamespace(
            id=str(uuid4())
        )
        queued = client.post(f"/api/v1/recommendations/generate/{product.id}")
        assert queued.status_code == 202
        assert "job_id" not in queued.json()
        published = recommendations.celery_app.send_task.call_args
        assert published.args[0] == "analytics.generate_ai_recommendation"
        recommendation_tasks.generate_ai_recommendation_task.run(
            *published.kwargs["args"],
            **published.kwargs["kwargs"],
        )
        legacy = client.get(f"/api/v1/recommendations/latest/{product.id}").json()
        assert legacy["recommendation"]["action"] == "HOLD"
        assert (
            client.get(f"/api/v1/recommendations/jobs/{job_id}").json()["result"]
            == active
        )

    with decision_db() as session:
        rows = session.scalars(
            select(Recommendation).order_by(Recommendation.created_at)
        ).all()
        assert len(rows) == 2
        assert "decision_orchestration" in rows[0].recommendation_context
        assert "decision_orchestration" not in rows[1].recommendation_context
