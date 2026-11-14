from __future__ import annotations

import asyncio
import json
import logging
import os
import ssl
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

from app.scraper.constants import HttpxConfig
from app.scraper.exceptions import PageLoadError, ParseError, PermanentAccessError, RequestTimeoutError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: httpx.Headers
    body: bytes
    encoding: str

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";", 1)[0].strip().lower()

    def json_object(self) -> dict[str, Any] | None:
        media_type = self.content_type
        if media_type != "application/json" and not media_type.endswith("+json"):
            return None
        try:
            value = json.loads(self.body, parse_float=Decimal)
        except (ValueError, RecursionError):
            return None
        return value if isinstance(value, dict) else None

    def text(self) -> str:
        return self.body.decode(self.encoding, errors="replace")


class DarazHttpClient:
    """One pooled HTTP client owned by the scrape's event loop."""

    def __init__(self, client: httpx.AsyncClient, config: HttpxConfig) -> None:
        self._client = client
        self._config = config

    @classmethod
    @asynccontextmanager
    async def open(
        cls, headers: dict[str, str], *, config: HttpxConfig | None = None,
    ) -> AsyncIterator[DarazHttpClient]:
        config = config or HttpxConfig()
        start = time.monotonic()
        client = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(
                connect=config.connect_timeout, read=config.read_timeout,
                write=config.write_timeout, pool=config.pool_timeout,
            ),
            limits=httpx.Limits(
                max_connections=config.max_connections,
                max_keepalive_connections=config.max_keepalive_connections,
            ),
            follow_redirects=False,
            trust_env=False,
        )
        try:
            async with client:
                logger.debug("daraz_httpx_open pid=%s max_connections=%s", os.getpid(), config.max_connections)
                yield cls(client, config)
        finally:
            if client.is_closed:
                logger.debug("daraz_httpx_closed pid=%s elapsed_ms=%.1f", os.getpid(), (time.monotonic() - start) * 1000)

    async def get(self, url: str) -> HttpResponse:
        try:
            async with asyncio.timeout(self._config.total_timeout):
                async with self._client.stream("GET", url) as response:
                    body = bytearray()
                    # Status and challenge headers take precedence over body validation.
                    if response.is_success and response.headers.get("cf-mitigated", "").lower() != "challenge":
                        async for chunk in response.aiter_bytes():
                            if len(body) + len(chunk) > self._config.max_response_bytes:
                                raise ParseError("Daraz HTTPX response exceeded the size limit.")
                            body.extend(chunk)
                    return HttpResponse(
                        response.status_code, response.headers, bytes(body), response.encoding or "utf-8",
                    )
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise RequestTimeoutError("Daraz HTTPX request timed out.") from exc
        except httpx.RequestError as exc:
            if _certificate_error(exc):
                raise PermanentAccessError("Daraz TLS certificate validation failed.") from exc
            raise PageLoadError("Daraz HTTPX request failed.") from exc


def _certificate_error(exc: BaseException) -> bool:
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, ssl.SSLCertVerificationError):
            return True
        current = current.__cause__
    return False
