from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, ClassVar

from playwright.async_api import (
    APIRequestContext,
    Browser,
    BrowserContext,
    Error,
    Page,
    Playwright,
    async_playwright,
)

from app.scraper.constants import (
    BrowserConfig,
    DEFAULT_VIEWPORT,
    LOCALE,
    TIMEZONE_ID,
)
from app.scraper.exceptions import BrowserError

logger = logging.getLogger(__name__)


class BrowserManager:
    """
    Production-safe Playwright browser manager.

    IMPORTANT DESIGN CHANGES:
    - NO shared singleton across Celery forks
    - Each instance manages its own browser lifecycle
    - Avoids stale driver + browser mismatch issues
    """

    def __init__(self, config: BrowserConfig | None = None) -> None:
        self._config = config or BrowserConfig()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._browser_lock = asyncio.Lock()

    # -----------------------------
    # Browser lifecycle
    # -----------------------------
    async def _ensure_browser(self) -> None:
        async with self._browser_lock:
            # If browser exists and is healthy → reuse
            if self._browser and self._browser.is_connected():
                return

            # Cleanup stale browser
            if self._browser:
                try:
                    await self._browser.close()
                except Exception:
                    pass
                self._browser = None

            # Start Playwright if needed
            if self._playwright is None:
                self._playwright = await async_playwright().start()

            try:
                self._browser = await self._playwright.chromium.launch(
    headless=True,
    executable_path=None,
    args=[
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
    ],
)
            except Error as exc:
                logger.exception("Failed to launch Playwright browser.")
                raise BrowserError("Failed to launch Playwright browser.") from exc

    # -----------------------------
    # Browser Context (for scraping)
    # -----------------------------
    async def new_context(
        self,
        *,
        user_agent: str,
        extra_headers: dict[str, str] | None = None,
    ) -> BrowserContext:
        await self._ensure_browser()

        if not self._browser:
            raise BrowserError("Playwright browser is unavailable.")

        context = await self._browser.new_context(
            user_agent=user_agent,
            viewport=DEFAULT_VIEWPORT,
            locale=LOCALE,
            timezone_id=TIMEZONE_ID,
            extra_http_headers=extra_headers,
            java_script_enabled=True,
        )

        context.set_default_timeout(self._config.timeout_ms)
        context.set_default_navigation_timeout(self._config.navigation_timeout_ms)

        return context

    # -----------------------------
    # Request context (API calls)
    # -----------------------------
    @asynccontextmanager
    async def request_context(
        self,
        *,
        user_agent: str,
        extra_headers: dict[str, str] | None = None,
    ) -> AsyncIterator[APIRequestContext]:
        await self._ensure_browser()

        if not self._playwright:
            raise BrowserError("Playwright is unavailable.")

        context = await self._playwright.request.new_context(
            user_agent=user_agent,
            extra_http_headers=extra_headers,
        )

        try:
            yield context
        finally:
            try:
                await context.dispose()
            except Error as exc:
                logger.warning("Failed to dispose request context cleanly: %s", exc)

    # -----------------------------
    # Page helper
    # -----------------------------
    @asynccontextmanager
    async def page(
        self,
        *,
        user_agent: str,
        extra_headers: dict[str, str] | None = None,
    ) -> AsyncIterator[Page]:
        context = await self.new_context(
            user_agent=user_agent,
            extra_headers=extra_headers,
        )

        page = await context.new_page()

        try:
            yield page
        finally:
            try:
                await context.close()
            except Error as exc:
                logger.warning("Failed to close browser context cleanly: %s", exc)

    # -----------------------------
    # Shutdown
    # -----------------------------
    async def close(self) -> None:
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None