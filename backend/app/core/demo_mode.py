"""Public demo guard: demo-session tokens may read everything but only run safe, additive actions."""

from __future__ import annotations

import re

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.security import decode_access_token
from app.services.password_reset_rate_limiter import (
    PasswordResetRateLimiter,
    PasswordResetRateLimitExceeded,
)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Writes a demo visitor may make: copilot chat, RAG questions, and generation/simulation
# endpoints that only add recommendation rows. Nothing here changes products, stock,
# policies, live marketplace prices or shared recommendation status.
DEMO_ALLOWED_WRITES = tuple(
    re.compile(pattern)
    for pattern in (
        r"^/copilot/conversations$",
        r"^/copilot/ask(/stream)?$",
        r"^/copilot/messages/[^/]+/feedback$",
        r"^/rag/[^/]+$",
        r"^/recommendations/generate/[^/]+$",
        r"^/products/[^/]+/pricing/(recommendations|analytics|simulate|simulate/explain)$",
        r"^/products/[^/]+/dead-stock/(recovery-simulations|recalculate)$",
        r"^/pricing-policies/products/[^/]+/minimum-safe-price/preview$",
        r"^/inventory-intelligence/products/[^/]+/workflow$",
    )
)

demo_rate_limiter = PasswordResetRateLimiter()


def client_ip(request: Request) -> str:
    # Free hosts (Hugging Face Spaces) sit behind a proxy, so the socket peer is the proxy.
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    return first or (request.client.host if request.client else "unknown")


def is_demo_token(request: Request) -> bool:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        return False
    try:
        return decode_access_token(token).get("demo") is True
    except Exception:
        return False  # invalid tokens are rejected later by get_current_seller


def is_allowed_demo_write(path: str) -> bool:
    prefix = settings.api_v1_prefix.rstrip("/")
    if prefix and path.startswith(prefix):
        path = path[len(prefix):]
    path = path.rstrip("/") or "/"
    return any(pattern.match(path) for pattern in DEMO_ALLOWED_WRITES)


def consume_demo_quota(scope: str, ip: str, per_ip_limit: int, global_limit: int | None = None) -> bool:
    try:
        demo_rate_limiter._consume(f"demo:{scope}:ip:{ip}", per_ip_limit, 3600)
        if global_limit is not None:
            demo_rate_limiter._consume(f"demo:{scope}:all", global_limit, 3600)
    except PasswordResetRateLimitExceeded:
        return False
    return True


def install_demo_guard(app: FastAPI) -> None:
    @app.middleware("http")
    async def demo_guard(request: Request, call_next):
        if request.method in SAFE_METHODS or not is_demo_token(request):
            return await call_next(request)
        if not is_allowed_demo_write(request.url.path):
            return JSONResponse(
                status_code=403,
                content={"detail": "This action is disabled in the BazarSync demo. Sign up to use it on your own store."},
            )
        if not consume_demo_quota(
            "actions",
            client_ip(request),
            settings.demo_max_actions_per_ip_per_hour,
            settings.demo_max_actions_per_hour,
        ):
            return JSONResponse(
                status_code=429,
                content={"detail": "Demo limit reached for now. Please try again in a little while."},
                headers={"Retry-After": "3600"},
            )
        return await call_next(request)
