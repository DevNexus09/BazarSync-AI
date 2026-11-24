from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core import demo_mode
from app.core.config import settings
from app.core.security import create_access_token, decode_access_token
from app.dependencies.db import get_db
from app.main import create_app
from app.models.seller import Seller
from app.services.demo_seed_service import DEMO_EMAIL

API = settings.api_v1_prefix


class FakeDemoSession:
    def __init__(self, seller: Seller | None) -> None:
        self.seller = seller

    def scalar(self, statement):
        del statement
        return self.seller


def make_seller() -> Seller:
    return Seller(
        id=uuid4(),
        email=DEMO_EMAIL,
        password_hash="x",
        auth_version=0,
        business_name="Watch Wise - Choice",
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture(autouse=True)
def _fresh_limiter():
    demo_mode.demo_rate_limiter._redis = None
    demo_mode.demo_rate_limiter._get_redis = lambda: None  # keep tests off any local Redis
    demo_mode.demo_rate_limiter.clear_local_state()
    yield
    demo_mode.demo_rate_limiter.clear_local_state()


def client_for(seller: Seller | None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: FakeDemoSession(seller)
    return TestClient(app, raise_server_exceptions=False)


def demo_headers(seller_id: str = "s1") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(subject=seller_id, demo=True)}"}


def test_demo_login_is_404_when_flag_is_off(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode_enabled", False)
    assert client_for(make_seller()).post(f"{API}/auth/demo").status_code == 404


def test_demo_login_issues_restricted_token_for_demo_seller(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode_enabled", True)
    seller = make_seller()
    response = client_for(seller).post(f"{API}/auth/demo")
    assert response.status_code == 200
    body = response.json()
    assert body["seller"]["email"] == DEMO_EMAIL
    claims = decode_access_token(body["access_token"])
    assert claims["sub"] == str(seller.id)
    assert claims["demo"] is True


def test_demo_login_reports_missing_demo_store(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode_enabled", True)
    assert client_for(None).post(f"{API}/auth/demo").status_code == 503


def test_demo_login_is_rate_limited_per_ip(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode_enabled", True)
    monkeypatch.setattr(settings, "demo_max_sessions_per_ip_per_hour", 1)
    client = client_for(make_seller())
    assert client.post(f"{API}/auth/demo").status_code == 200
    assert client.post(f"{API}/auth/demo").status_code == 429


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/products"),
        ("put", "/products/p1"),
        ("delete", "/products/p1"),
        ("post", "/scraper/run/p1"),
        ("post", "/sales/import"),
        ("patch", "/auth/profile"),
        ("post", "/auth/delete-account"),
        ("post", "/pricing/recommendations/r1/acknowledge"),
        ("post", "/reorder-recommendations/r1/mark-ordered"),
        ("post", "/copilot/action-proposals/a1/approve"),
    ],
)
def test_demo_token_cannot_make_destructive_writes(method, path):
    response = getattr(client_for(make_seller()), method)(f"{API}{path}", headers=demo_headers())
    assert response.status_code == 403
    assert "disabled in the BazarSync demo" in response.json()["detail"]


def test_regular_token_is_not_blocked_by_demo_guard():
    headers = {"Authorization": f"Bearer {create_access_token(subject='s1')}"}
    response = client_for(make_seller()).delete(f"{API}/products/p1", headers=headers)
    assert "disabled in the BazarSync demo" not in response.text


def test_demo_token_can_read():
    response = client_for(make_seller()).get(f"{API}/products", headers=demo_headers())
    assert "disabled in the BazarSync demo" not in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/copilot/ask",
        "/copilot/ask/stream",
        "/copilot/conversations",
        "/rag/ask",
        "/recommendations/generate/p1",
        "/products/p1/pricing/recommendations",
        "/products/p1/pricing/simulate/explain",
        "/products/p1/dead-stock/recovery-simulations",
    ],
)
def test_demo_allowlist_covers_exploration_actions(path):
    assert demo_mode.is_allowed_demo_write(f"{API}{path}")


def test_demo_actions_are_rate_limited_per_ip(monkeypatch):
    monkeypatch.setattr(settings, "demo_max_actions_per_ip_per_hour", 1)
    client = client_for(make_seller())
    first = client.post(f"{API}/copilot/ask", headers=demo_headers(), json={})
    assert first.status_code != 429
    second = client.post(f"{API}/copilot/ask", headers=demo_headers(), json={})
    assert second.status_code == 429
