from __future__ import annotations

import asyncio
import logging
import os
import time
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
_CLOSE_TIMEOUT_SECONDS = 10


class BrowserManager:
    """Own Playwright and an optional Chromium process for one scrape and loop."""

    def __init__(self, config: BrowserConfig | None = None) -> None:
        self._config = config or BrowserConfig()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._browser_lock = asyncio.Lock()
        self._owner: tuple[int, asyncio.AbstractEventLoop] | None = None

    def _chromium_launch_args(self) -> list[str]:
        return [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-component-extensions-with-background-pages",
            "--disable-background-networking",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-ipc-flooding-protection",
            "--disable-renderer-backgrounding",
            "--js-flags=--max-old-space-size=128",
        ]

    def _check_owner(self) -> None:
        owner = (os.getpid(), asyncio.get_running_loop())
        if self._owner is None:
            self._owner = owner
        elif owner != self._owner:
            raise BrowserError("Playwright cannot be reused across processes or event loops.")

    async def _start_playwright(self) -> Playwright:
        # The caller holds the lifecycle lock.
        if self._playwright is None:
            start = time.monotonic()
            startup = asyncio.create_task(async_playwright().start())
            try:
                self._playwright = await asyncio.shield(startup)
            except asyncio.CancelledError:
                # Keep ownership of a driver that is already starting so close() can stop it.
                try:
                    self._playwright = await asyncio.wait_for(startup, timeout=10)
                except Exception:
                    logger.warning("daraz_playwright_start_cancelled_cleanup_failed", exc_info=True)
                raise
            except Exception as exc:
                raise BrowserError("Playwright initialization failed") from exc
            logger.info("daraz_playwright_started pid=%s elapsed_ms=%.1f", os.getpid(), (time.monotonic() - start) * 1000)
        return self._playwright

    async def _ensure_browser(self) -> Browser:
        self._check_owner()
        async with self._browser_lock:
            if self._browser and self._browser.is_connected():
                return self._browser

            if self._browser:
                logger.warning("daraz_chromium_disconnected pid=%s", os.getpid())
                try:
                    async with asyncio.timeout(_CLOSE_TIMEOUT_SECONDS):
                        await self._browser.close()
                except (Error, TimeoutError):
                    logger.warning("daraz_chromium_stale_close_failed", exc_info=True)
                self._browser = None

            playwright = await self._start_playwright()
            start = time.monotonic()
            try:
                self._browser = await playwright.chromium.launch(
                    headless=self._config.headless,
                    args=self._chromium_launch_args(),
                    proxy=self._config.proxy,
                    timeout=self._config.navigation_timeout_ms,
                )
            except Error as exc:
                raise BrowserError("Failed to launch Playwright browser") from exc
            logger.info("daraz_chromium_started pid=%s elapsed_ms=%.1f", os.getpid(), (time.monotonic() - start) * 1000)
            return self._browser

    # -----------------------------
    # Browser Context (scraping)
    # -----------------------------
    async def new_context(
        self,
        *,
        user_agent: str,
        extra_headers: dict[str, str] | None = None,
    ) -> BrowserContext:
        browser = await self._ensure_browser()
        context = await browser.new_context(
            user_agent=user_agent,
            viewport=DEFAULT_VIEWPORT,
            locale=LOCALE,
            timezone_id=TIMEZONE_ID,
            extra_http_headers=extra_headers,
            java_script_enabled=True,
            service_workers="block",
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
        self._check_owner()
        async with self._browser_lock:
            playwright = await self._start_playwright()

        context = await playwright.request.new_context(
            user_agent=user_agent,
            extra_http_headers=extra_headers,
        )

        logger.debug("daraz_playwright_request_context_open pid=%s", os.getpid())
        try:
            yield context
        finally:
            try:
                async with asyncio.timeout(_CLOSE_TIMEOUT_SECONDS):
                    await context.dispose()
                logger.debug("daraz_playwright_request_context_closed pid=%s", os.getpid())
            except (Error, TimeoutError):
                logger.warning("daraz_playwright_request_context_close_failed", exc_info=True)

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

        logger.debug("daraz_browser_context_open pid=%s", os.getpid())
        try:
            yield await context.new_page()
        finally:
            try:
                async with asyncio.timeout(_CLOSE_TIMEOUT_SECONDS):
                    await context.close()
                logger.debug("daraz_browser_context_closed pid=%s", os.getpid())
            except (Error, TimeoutError):
                logger.warning("daraz_browser_context_close_failed", exc_info=True)

    # -----------------------------
    # Shutdown
    # -----------------------------
    async def close(self) -> None:
        if self._owner is None:
            return
        self._check_owner()
        async with self._browser_lock:
            browser, self._browser = self._browser, None
            playwright, self._playwright = self._playwright, None
            try:
                if browser is not None:
                    try:
                        async with asyncio.timeout(_CLOSE_TIMEOUT_SECONDS):
                            await browser.close()
                        logger.info("daraz_chromium_closed pid=%s", os.getpid())
                    except (Error, TimeoutError):
                        logger.warning("daraz_chromium_close_failed", exc_info=True)
            finally:
                if playwright is not None:
                    try:
                        async with asyncio.timeout(_CLOSE_TIMEOUT_SECONDS):
                            await playwright.stop()
                        logger.info("daraz_playwright_stopped pid=%s", os.getpid())
                    except (Error, TimeoutError):
                        logger.warning("daraz_playwright_stop_failed", exc_info=True)
