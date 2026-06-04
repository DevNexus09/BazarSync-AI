from __future__ import annotations


import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

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
    Production-safe Playwright browser manager for Celery workers.

    Key design:
    - No global singleton (Celery-safe)
    - One browser per worker process
    - Safe async lifecycle handling
    """

    def __init__(self, config: BrowserConfig | None = None) -> None:
        self._config = config or BrowserConfig()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._browser_lock = asyncio.Lock()
        self._initialized_pid: int | None = None

    def _chromium_launch_args(self) -> list[str]:
        return [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-blink-features=AutomationControlled",
        ]

    # -----------------------------
    # Browser lifecycle
    # -----------------------------
    async def _ensure_browser(self) -> None:
        async with self._browser_lock:
            current_pid = os.getpid()

            if self._initialized_pid is not None and self._initialized_pid != current_pid:
                if self._browser:
                    try:
                        await self._browser.close()
                    except Error as exc:
                        logger.warning("Failed to close forked browser: %s", exc)
                    self._browser = None

                if self._playwright:
                    try:
                        await self._playwright.stop()
                    except Error as exc:
                        logger.warning("Failed to stop Playwright after fork: %s", exc)
                    self._playwright = None

                self._initialized_pid = None

            # Reuse healthy browser
            if self._browser and self._browser.is_connected():
                self._initialized_pid = current_pid
                return

            # Cleanup stale browser
            if self._browser:
                try:
                    await self._browser.close()
                except Error as exc:
                    logger.warning("Failed to close stale browser: %s", exc)
                self._browser = None

            # Start Playwright once per process
            if self._playwright is None:
                try:
                    self._playwright = await async_playwright().start()
                except Exception as exc:
                    logger.exception("Failed to start Playwright runtime")
                    raise BrowserError("Playwright initialization failed") from exc

            # Launch Chromium (IMPORTANT: no executable_path)
            try:
                launch_options: dict[str, object] = {
                    "headless": self._config.headless,
                    "args": self._chromium_launch_args(),
                }
                if self._config.proxy:
                    launch_options["proxy"] = self._config.proxy

                self._browser = await self._playwright.chromium.launch(**launch_options)
                self._initialized_pid = current_pid
            except Error as exc:
                logger.exception("Failed to launch Playwright browser")
                raise BrowserError("Failed to launch Playwright browser") from exc

    # -----------------------------
    # Browser Context (scraping)
    # -----------------------------
    async def new_context(
        self,
        *,
        user_agent: str,
        extra_headers: dict[str, str] | None = None,
    ) -> BrowserContext:
        await self._ensure_browser()

        if not self._browser:
            raise BrowserError("Browser is unavailable")

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
            raise BrowserError("Playwright not initialized")

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
                logger.warning("Failed to dispose request context: %s", exc)

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
                await page.close()
            except Error as exc:
                logger.warning("Failed to close page: %s", exc)
            try:
                await context.close()
            except Error as exc:
                logger.warning("Failed to close context: %s", exc)

    # -----------------------------
    # Shutdown
    # -----------------------------
    async def close(self) -> None:
        if self._browser:
            try:
                await self._browser.close()
            except Error as exc:
                logger.warning("Failed to close browser: %s", exc)
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Error as exc:
                logger.warning("Failed to stop Playwright: %s", exc)
            self._playwright = None