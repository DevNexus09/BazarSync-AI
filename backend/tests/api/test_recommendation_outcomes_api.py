from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import recommendation_outcomes as api_module
from app.core.config import settings
from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db

SELLER = uuid4()


class FakeService:
    calls: list = []

    def __init__(self, db) -> None:
        pass

    def track_record(self, *, seller_id, recommendation_type):
        self.calls.append((seller_id, recommendation_type.value))
        return {"recommendation_type": recommendation_type.value, "outcomes": 21, "hit_rate": 0.81, "reliable": True}


def client(monkeypatch, enabled: bool) -> TestClient:
    monkeypatch.setattr(settings, "recommendation_outcomes_enabled", enabled)
    monkeypatch.setattr(api_module, "RecommendationOutcomeService", FakeService)
    FakeService.calls = []
    app = FastAPI()
    app.include_router(api_module.router)
    app.dependency_overrides[get_current_seller] = lambda: type("S", (), {"id": SELLER})()
    app.dependency_overrides[get_db] = lambda: object()
    return TestClient(app)


def test_track_record_is_scoped_to_the_signed_in_seller(monkeypatch):
    response = client(monkeypatch, True).get("/recommendation-outcomes/track-record", params={"recommendation_type": "REORDER"})
    assert response.json() == {"enabled": True, "recommendation_type": "REORDER", "outcomes": 21, "hit_rate": 0.81, "reliable": True}
    assert FakeService.calls == [(SELLER, "REORDER")]


def test_disabled_flag_reports_disabled_without_reading(monkeypatch):
    response = client(monkeypatch, False).get("/recommendation-outcomes/track-record", params={"recommendation_type": "PRICING"})
    assert response.json() == {"enabled": False, "recommendation_type": "PRICING"}
    assert FakeService.calls == []


def test_unknown_type_is_rejected(monkeypatch):
    assert client(monkeypatch, True).get("/recommendation-outcomes/track-record", params={"recommendation_type": "BOGUS"}).status_code == 422
