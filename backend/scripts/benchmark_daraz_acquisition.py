"""Benchmark real clients and Chromium against loopback fixtures only."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import threading
import time
from contextlib import AsyncExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from app.scraper import daraz_scraper, utils
from app.scraper import parser as daraz_parser
from app.scraper.acquisition.http_client import DarazHttpClient
from app.scraper.browser import BrowserManager
from app.scraper.constants import SCRAPER_USER_AGENT
from app.scraper.exceptions import PermanentAccessError
from app.scraper.utils import build_headers

TITLE = "Fixture tablet"
COUNT = 5
MODES = ("legacy_eager_api", "playwright_api", "httpx", "chromium_fallback", "hybrid_fallback")


class FixtureServer(ThreadingHTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), FixtureHandler)
        self.base_url = f"http://127.0.0.1:{self.server_port}"
        self.mode = ""
        self.requests: list[int] = []
        self.guard = threading.Lock()


class FixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: FixtureServer

    def log_message(self, *args) -> None:
        pass

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        with self.server.guard:
            self.server.requests.append(self.client_address[1])

        # Simulate the same small upstream processing cost for each request.
        time.sleep(0.01)
        mode = self.server.mode
        if url.path == "/catalog/":
            params = parse_qs(url.query)
            if params.get("q") != [TITLE]:
                self.respond(400, "text/plain", "wrong query")
                return
            if mode == "blocked":
                self.respond(403, "text/plain", "blocked")
                return
            if params.get("ajax") == ["true"]:
                rows = [] if mode in {"chromium_fallback", "hybrid_fallback"} else [
                    {"name": f"{TITLE} {i}", "itemUrl": f"/products/{i}.html", "price": 250 + i}
                    for i in range(COUNT)
                ]
                payload = {"mods": {"listItems": rows}} if rows else {"mods": {}}
                self.respond(200, "application/json", json.dumps(payload))
                return

            cards = "".join(
                f'<div data-qa-locator="product-item"><a title="{TITLE} {i}" href="/products/{i}.html"></a>'
                f'<span class="price">৳{250 + i}</span></div>'
                for i in range(COUNT)
            )
            # Only the rendered document contains card nodes.
            self.respond(200, "text/html", f"<body><script>document.body.innerHTML={json.dumps(cards)}</script></body>")
        elif url.path.startswith("/products/"):
            i = url.path.rsplit("/", 1)[-1].split(".", 1)[0]
            self.respond(200, "text/html", f'<div class="product-description">Fixture detail {i}</div>')
        else:
            self.respond(404, "text/plain", "missing fixture")

    def respond(self, status: int, media_type: str, content: str) -> None:
        body = content.encode()
        self.send_response(status)
        self.send_header("Content-Type", f"{media_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


class FixtureRedis:
    async def eval(self, *_args) -> tuple[int, int]:
        return 2, 0

    async def zrem(self, *_args) -> None:
        pass


class TimedBrowser(BrowserManager):
    def __init__(self) -> None:
        super().__init__()
        self.first_browser_ms = 0.0
        self.launched = None

    async def _ensure_browser(self):
        start = time.perf_counter()
        instance = await super()._ensure_browser()
        if self.launched is None:
            self.first_browser_ms = (time.perf_counter() - start) * 1000
            self.launched = instance
        return instance


class TimedScraper(daraz_scraper.DarazScraper):
    search_ms = 0.0

    async def _search(self, query):
        start = time.perf_counter()
        result = await super()._search(query)
        self.search_ms = (time.perf_counter() - start) * 1000
        return result


async def trial(server: FixtureServer, mode: str) -> dict:
    server.mode = mode
    server.requests.clear()
    browser = TimedBrowser()
    start = time.perf_counter()
    async with AsyncExitStack() as stack:
        stack.push_async_callback(browser.close)
        http = None
        if mode in {"httpx", "hybrid_fallback", "blocked"}:
            http = await stack.enter_async_context(DarazHttpClient.open(build_headers(SCRAPER_USER_AGENT)))
        scraper = TimedScraper(browser, FixtureRedis(), http=http)
        if mode == "legacy_eager_api":
            # Reproduce the previous eager launch before the AJAX API request.
            await browser._ensure_browser()
        if mode == "blocked":
            try:
                await scraper.scrape(TITLE)
            except PermanentAccessError:
                pass
            else:
                raise AssertionError("The blocked fixture did not stop acquisition.")
            assert browser._playwright is None
            assert len(server.requests) == 1
            return {"requests": 1, "fallbacks": 0, "chromium_launches": 0}

        response = await scraper.scrape(TITLE)
        expected_method = (
            "chromium" if mode in {"chromium_fallback", "hybrid_fallback"} else
            "httpx" if mode == "httpx" else "playwright_api"
        )
        assert response.search_acquisition_method == expected_method
        assert sorted(row.product_price for row in response.products) == list(range(250, 250 + COUNT))
        assert sorted(row.product_description for row in response.products) == [f"Fixture detail {i}" for i in range(COUNT)]
        if browser.launched is not None:
            assert not browser.launched.contexts, "Browser contexts leaked."
    if browser.launched is not None:
        assert not browser.launched.is_connected(), "Browser remained connected."
    if http is not None:
        assert http._client.is_closed, "HTTPX client was not closed."
    assert browser._playwright is None, "Playwright driver remained attached."
    sockets = len(set(server.requests))
    return {
        "search_ms": scraper.search_ms + (browser.first_browser_ms if mode == "legacy_eager_api" else 0),
        "total_ms": (time.perf_counter() - start) * 1000,
        "browser_startup_ms": browser.first_browser_ms,
        "requests": len(server.requests),
        "tcp_connections": sockets,
        "reused_requests": len(server.requests) - sockets,
        "complete_listings": response.total_results,
    }


def summarize(samples: list[dict]) -> dict:
    output = {key: round(statistics.mean(row[key] for row in samples), 2) for key in samples[0]}
    for key in ("search_ms", "total_ms"):
        ordered = sorted(row[key] for row in samples)
        output[f"{key}_p95"] = round(ordered[math.ceil(len(ordered) * 0.95) - 1], 2)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", default=12, type=int)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    with FixtureServer() as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        # This process talks only to the loopback fixture. Exercise the same URL-building,
        # transport, parsing and rendering code without changing production authorization.
        utils.DARAZ_BASE_URL = server.base_url
        daraz_scraper._is_search_url = lambda url: url == utils.build_search_url(TITLE)
        def is_fixture_product(url: str) -> bool:
            return url.startswith(f"{server.base_url}/products/")

        daraz_parser.is_daraz_product_url = is_fixture_product
        daraz_scraper.is_daraz_product_url = is_fixture_product

        async def fixture_settle() -> None:
            await asyncio.sleep(0.02)

        daraz_scraper.random_delay = fixture_settle
        try:
            samples = {mode: [] for mode in MODES}
            for _ in range(args.runs):
                for mode in MODES:
                    samples[mode].append(asyncio.run(trial(server, mode)))
            output = {mode: summarize(rows) for mode, rows in samples.items()}
            output["blocked_fixture"] = asyncio.run(trial(server, "blocked"))
            print(json.dumps({"runs_per_mode": args.runs, "results": output}, indent=2))
        finally:
            server.shutdown()
            thread.join()


if __name__ == "__main__":
    main()
