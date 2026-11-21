from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.recommendation import (
    Recommendation,
    RecommendationAction,
    RecommendationConfidence,
)
from app.services.recommendation_service import RecommendationService


def _record():
    return Recommendation(
        product_id=uuid4(),
        action=RecommendationAction.HOLD,
        confidence=RecommendationConfidence.LOW,
        reasoning_bn="বর্তমান দাম রাখুন",
        revenue_opportunity=Decimal(0),
        created_at=datetime.now(timezone.utc),
        recommendation_context={"context": {}},
    )


def test_dashboard_projection_is_optional_and_legacy_safe(monkeypatch):
    row = _record()
    with Session() as session:
        service = RecommendationService(session)
        monkeypatch.setattr(settings, "recommendation_dashboard_evidence_enabled", True)
        assert "dashboard_evidence" not in service.read_result(row).model_dump()
        row.recommendation_context = {
            "evidence_assessment": {"reason_codes": ["INSUFFICIENT_ACTION_EVIDENCE"]}
        }
        evidence = service.read_result(row).dashboard_evidence
        assert evidence and evidence.insufficient_evidence
        monkeypatch.setattr(
            settings, "recommendation_dashboard_evidence_enabled", False
        )
        assert "dashboard_evidence" not in service.read_result(row).model_dump()


def test_only_projects_scoped_approved_evidence_and_no_unvalidated_intervals(
    monkeypatch,
):
    monkeypatch.setattr(settings, "recommendation_dashboard_evidence_enabled", True)
    row = _record()
    seller_id = str(uuid4())
    scope = {"seller_id": seller_id, "product_id": str(row.product_id)}
    point = {
        **scope,
        "model_name": "catboost",
        "model_version": "approved-v1",
        "horizon_days": 7,
        "expected_units": "0",
        "data_cutoff": "2026-11-15T12:00:00Z",
        "prediction_interval": {
            "status": "empirical_unvalidated",
            "lower_bound": "0",
            "upper_bound": "5",
        },
    }

    def evaluation(engine, snapshot, **fields):
        return {
            "candidate": {
                **scope,
                "source_engine": engine,
                "candidate_id": str(uuid4()),
                "evidence": {"snapshot": snapshot},
                **fields,
            }
        }

    pricing = evaluation(
        "dynamic_pricing",
        {
            "baseline_demand_forecast": {
                "status": "AVAILABLE",
                "source": "previous",
                "forecast": point,
            },
            "candidates": [
                {
                    "candidate_price": "400.50",
                    "is_allowed": False,
                    "rejection_reasons": ["BELOW_MINIMUM_MARGIN"],
                },
                {
                    "candidate_price": "405",
                    "is_allowed": True,
                    "eligible_for_price_change": False,
                },
            ],
        },
    )
    recovery = evaluation(
        "dead_stock_recovery",
        {
            "inputs": {
                "baseline_demand": {
                    "status": "APPROVED_BASELINE_ONLY",
                    "source": "active",
                    "forecast": {
                        **point,
                        "horizon_days": 30,
                        "seller_id": str(uuid4()),
                    },
                }
            }
        },
        proposed_parameters={"action": "IMPROVE_LISTING"},
    )
    row.recommendation_context = {
        "analytics": {
            "reason_codes": ["INSUFFICIENT_ACTION_EVIDENCE", "MARGIN_GUARD_BLOCKED"]
        },
        "competitor_evidence": {
            "freshness_status": "STALE",
            "latest_observation_at": "2026-11-15T12:00:00Z",
        },
        "decision_orchestration": {
            "inputs": {
                "seller_id": seller_id,
                "sales": {"status": "INSUFFICIENT", "rate": None},
            },
            "supporting_candidate_ids": [recovery["candidate"]["candidate_id"]],
            "evaluations": [pricing, recovery],
        },
    }
    with Session() as session:
        response = RecommendationService(session).read_result(row)
    evidence = response.dashboard_evidence
    assert evidence and evidence.price_blocked and evidence.insufficient_evidence
    assert evidence.daily_sales_rate is None
    assert len(evidence.forecasts) == 1
    assert evidence.forecasts[0].expected_units == 0
    assert evidence.forecasts[0].prediction_interval is None
    assert evidence.forecasts[0].uncertainty == "empirical_unvalidated"
    assert evidence.pricing_candidates[0].price == Decimal("400.50")
    assert evidence.pricing_candidates[0].rejection_reasons == ["BELOW_MINIMUM_MARGIN"]
    assert evidence.pricing_candidates[1].price_change_eligible is False
    assert evidence.supporting_actions[0].action == "IMPROVE_LISTING"
    assert "decision_orchestration" not in response.model_dump_json()
    assert seller_id not in response.model_dump_json()
