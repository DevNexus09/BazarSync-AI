from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.dead_stock_dashboard import router
from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.schemas.dead_stock_readiness import (
    DeadStockReadinessCheck,
    DeadStockReadinessResponse,
    DeadStockReadinessStatus,
)


SELLER_A = uuid4()
SELLER_B = uuid4()
PRODUCT_A = uuid4()
PRODUCT_B = uuid4()


class FakeSeller:
    def __init__(self, seller_id):
        self.id = seller_id


def app_with_seller(seller_id=SELLER_A) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_seller] = lambda: FakeSeller(seller_id)
    app.dependency_overrides[get_db] = lambda: object()
    return TestClient(app)


def readiness_for(product_id, *, seller_id=SELLER_A, overrides=None):
    if seller_id != SELLER_A or product_id != PRODUCT_A:
        return None
    checks = {
        "current_stock": check(DeadStockReadinessStatus.OK, None, False),
        "product_cost": check(DeadStockReadinessStatus.MISSING, "MISSING_PRODUCT_COST", True),
        "inventory_age_source": check(DeadStockReadinessStatus.MISSING, "MISSING_INVENTORY_AGE_SOURCE", True),
        "sales_history": check(DeadStockReadinessStatus.MISSING, "MISSING_SALES_HISTORY", False),
        "marketplace_fee_policy": check(DeadStockReadinessStatus.MISSING, "MISSING_MARKETPLACE_FEE_POLICY", True),
        "pricing_policy": check(DeadStockReadinessStatus.MISSING, "MISSING_PRICING_POLICY", True),
        "visibility_data": check(DeadStockReadinessStatus.UNAVAILABLE, "VISIBILITY_DATA_UNAVAILABLE", False),
        "dead_stock_assessment": check(DeadStockReadinessStatus.PENDING_CALCULATION, "MISSING_DEAD_STOCK_ASSESSMENT", False),
        "risk_score": check(DeadStockReadinessStatus.MISSING, "MISSING_RISK_SCORE", False),
        "recovery_recommendation": check(DeadStockReadinessStatus.ACTION_REQUIRED, "MISSING_RECOVERY_RECOMMENDATION", False),
        "capital_recovery_estimate": check(DeadStockReadinessStatus.MISSING, "MISSING_CAPITAL_RECOVERY_ESTIMATE", False),
        "phase9_pipeline": check(DeadStockReadinessStatus.PENDING_CALCULATION, "PHASE9_RECALCULATION_REQUIRED", False),
    }
    if overrides:
        checks.update(overrides)
    return DeadStockReadinessResponse(
        product_id=PRODUCT_A,
        product_name='King Size Premium Bed Sheet 88" x 98"',
        ready=False,
        can_classify_dead_stock=False,
        can_score_risk=False,
        can_estimate_locked_capital=False,
        can_generate_recovery_recommendation=False,
        can_estimate_potential_recovery=False,
        checks=checks,
        blocking_reasons=[item.reason_code for item in checks.values() if item.reason_code and item.blocking],
        non_blocking_reasons=[item.reason_code for item in checks.values() if item.reason_code and not item.blocking],
        next_actions=[
            {
                "key": "add_product_cost",
                "label": "Add product cost",
                "description": "Required to calculate locked capital.",
                "href": f"/app/products/{PRODUCT_A}/edit",
                "implemented": True,
                "priority": 1,
            }
        ],
        recommended_setup_order=["Add product cost or landed cost.", "Run Phase 9 dead stock analysis."],
        last_checked_at=datetime.now(timezone.utc),
    )


def check(status, reason, blocking):
    return DeadStockReadinessCheck(
        status=status,
        reason_code=reason,
        message=reason or "OK",
        blocking=blocking,
        current_value=None,
        next_action=None,
        href=None,
    )


def patch_service(monkeypatch, overrides=None):
    class FakeService:
        def __init__(self, db):
            del db

        def evaluate(self, *, seller_id, product_id):
            return readiness_for(product_id, seller_id=seller_id, overrides=overrides)

    monkeypatch.setattr("app.api.v1.dead_stock_dashboard.DeadStockReadinessService", FakeService)


def test_authenticated_seller_can_read_own_product_readiness(monkeypatch):
    patch_service(monkeypatch)
    response = app_with_seller().get(f"/products/{PRODUCT_A}/dead-stock/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["product_id"] == str(PRODUCT_A)
    assert body["checks"]["product_cost"]["reason_code"] == "MISSING_PRODUCT_COST"
    assert body["checks"]["visibility_data"]["blocking"] is False
    assert body["next_actions"][0]["href"] == f"/app/products/{PRODUCT_A}/edit"


def test_seller_cannot_read_another_sellers_product(monkeypatch):
    patch_service(monkeypatch)
    response = app_with_seller(SELLER_B).get(f"/products/{PRODUCT_A}/dead-stock/readiness")

    assert response.status_code == 404
    assert "traceback" not in response.text.lower()


def test_readiness_reports_setup_statuses(monkeypatch):
    patch_service(
        monkeypatch,
        overrides={
            "inventory_age_source": check(DeadStockReadinessStatus.OK, None, False),
            "sales_history": check(DeadStockReadinessStatus.OK, None, False),
            "pricing_policy": check(DeadStockReadinessStatus.OK, None, False),
            "visibility_data": check(DeadStockReadinessStatus.OK, None, False),
        },
    )
    response = app_with_seller().get(f"/products/{PRODUCT_A}/dead-stock/readiness")

    assert response.status_code == 200
    checks = response.json()["checks"]
    assert checks["inventory_age_source"]["status"] == "OK"
    assert checks["sales_history"]["status"] == "OK"
    assert checks["pricing_policy"]["status"] == "OK"
    assert checks["visibility_data"]["status"] == "OK"


def test_another_product_returns_not_found_without_leaking_data(monkeypatch):
    patch_service(monkeypatch)
    response = app_with_seller().get(f"/products/{PRODUCT_B}/dead-stock/readiness")

    assert response.status_code == 404
    assert str(PRODUCT_A) not in response.text
