from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from playwright.async_api import Error as PlaywrightError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.scraper import browser, daraz_scraper
from app.scraper.acquisition import rate_limit
from app.scraper.acquisition.http_client import DarazHttpClient
from app.scraper.acquisition.rate_limit import CoordinationError, DarazRequestCoordinator
from app.scraper.browser import BrowserManager
from app.scraper.constants import DarazRateConfig, HttpxConfig
from app.scraper.daraz_scraper import DarazScraper
from app.scraper.exceptions import BrowserError, PageLoadError, ParseError, PermanentAccessError, RateLimitError
from app.scraper.schemas.scraped_product import ScrapedProduct
from app.scraper.services import competitor_service

TITLE = "বাংলা tablet"
PRODUCT = "https://www.daraz.com.bd/products/tablet-i1.html"
LISTING = {"name": TITLE, "itemUrl": PRODUCT, "price": "250.00"}
DETAIL = '<div class="product-description">Fixture description</div>'


@asynccontextmanager
async def _scraper(handler, *, config=None):
    manager = Mock()
    config = config or HttpxConfig()
    redis = SimpleNamespace(eval=AsyncMock(return_value=(2, 0)), zrem=AsyncMock())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
        scraper = DarazScraper(manager, redis, http=DarazHttpClient(client, config))
        yield scraper, manager, redis


def test_httpx_uses_existing_query_and_pool_for_details_without_playwright():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/catalog/":
            assert dict(request.url.params) == {"q": TITLE, "ajax": "true"}
            listings = [LISTING, {**LISTING, "itemUrl": f"{PRODUCT}#duplicate"}]
            return httpx.Response(200, json={"mods": {"listItems": listings}})
        return httpx.Response(200, text=DETAIL, headers={"content-type": "text/html"})

    async def run():
        async with _scraper(handler) as (scraper, manager, redis):
            result = await scraper.scrape(TITLE)
            assert result.search_acquisition_method == "httpx"
            assert result.total_results == 2
            assert all(product.detail_acquisition_method == "httpx" for product in result.products)
            assert all(product.product_description == "Fixture description" for product in result.products)
            assert all(product.product_price == 250 for product in result.products)
            assert "search_acquisition_method" not in result.model_dump()
            assert "detail_acquisition_method" not in result.products[0].model_dump()
            assert manager.mock_calls == []
            assert len(requests) == redis.zrem.await_count == 2

    asyncio.run(run())


def test_httpx_empty_results_are_successful_without_any_fallback():
    async def run():
        async with _scraper(lambda _: httpx.Response(200, json={"mods": {"listItems": []}})) as (scraper, manager, _):
            response = await scraper.scrape(TITLE)
            assert response.total_results == 0
            assert response.search_acquisition_method == "httpx"
            assert manager.mock_calls == []

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["malformed", "content_type", "shape", "temporary", "timeout", "unsupported"])
def test_httpx_temporary_or_unsupported_response_uses_playwright_api(mode):
    def handler(request):
        if mode == "timeout":
            raise httpx.ReadTimeout("fixture", request=request)
        return {
            "malformed": httpx.Response(200, content=b"{bad", headers={"content-type": "application/json"}),
            "content_type": httpx.Response(200, content=b'{"mods":{"listItems":[]}}'),
            "shape": httpx.Response(200, json={"mods": {}}),
            "temporary": httpx.Response(503),
            "unsupported": httpx.Response(415),
        }[mode]

    async def run():
        async with _scraper(handler) as (scraper, _, _):
            scraper._fetch_ajax_payload = AsyncMock(return_value={"mods": {"listItems": []}})
            scraper._fetch_search_html = AsyncMock()
            result = await scraper.scrape(TITLE)
            assert result.search_acquisition_method == "playwright_api"
            scraper._fetch_ajax_payload.assert_awaited_once()
            scraper._fetch_search_html.assert_not_awaited()

    asyncio.run(run())


def test_hybrid_falls_back_to_chromium_when_both_ajax_responses_are_unsupported():
    async def run():
        async with _scraper(lambda _: httpx.Response(200, json={})) as (scraper, _, _):
            scraper._fetch_ajax_payload = AsyncMock(return_value={})
            scraper._fetch_search_html = AsyncMock(return_value=(
                f'<div data-qa-locator="product-item"><a title="{TITLE}" href="{PRODUCT}"></a></div>'
            ))
            scraper._fetch_details = AsyncMock(return_value=None)
            assert (await scraper.scrape(TITLE)).search_acquisition_method == "chromium"
            scraper._fetch_ajax_payload.assert_awaited_once()
            scraper._fetch_search_html.assert_awaited_once()

    asyncio.run(run())


def test_dynamic_detail_uses_chromium_only_for_that_detail():
    def handler(request):
        if request.url.path == "/catalog/":
            return httpx.Response(200, json={"mods": {"listItems": [LISTING]}})
        return httpx.Response(200, text="<html><div id='render-target'></div></html>")

    async def run():
        async with _scraper(handler) as (scraper, _, _):
            scraper._fetch_html = AsyncMock(return_value=DETAIL)
            result = await scraper.scrape(TITLE)
            assert result.search_acquisition_method == "httpx"
            assert result.products[0].detail_acquisition_method == "chromium"
            scraper._fetch_html.assert_awaited_once_with(PRODUCT, detail=True)

    asyncio.run(run())


@pytest.mark.parametrize(
    "status,headers,body,error",
    [
        (301, {"location": "/customer/login"}, "", PermanentAccessError),
        (401, {}, "", PermanentAccessError),
        (403, {}, "", PermanentAccessError),
        (429, {"retry-after": "80"}, "", RateLimitError),
        (503, {"retry-after": "80"}, "", PageLoadError),
        (200, {"cf-mitigated": "challenge"}, "", PermanentAccessError),
        (200, {"content-type": "text/html"}, "<title>Verify you are human</title>", PermanentAccessError),
    ],
)
def test_access_restrictions_and_retry_after_stop_the_chain(status, headers, body, error):
    async def run():
        async with _scraper(lambda _: httpx.Response(status, headers=headers, text=body)) as (scraper, manager, redis):
            with pytest.raises(error) as raised:
                await scraper.scrape(TITLE)
            if "retry-after" in headers:
                assert raised.value.retry_after == 80
                assert any(call.args[-1] == 80 for call in redis.eval.await_args_list)
            assert manager.mock_calls == []
            redis.zrem.assert_awaited_once()

    asyncio.run(run())


def test_oversized_httpx_response_does_not_fall_back_to_buffered_playwright():
    async def run():
        async with _scraper(
            lambda _: httpx.Response(200, content=b"x" * 5), config=HttpxConfig(max_response_bytes=4),
        ) as (scraper, manager, redis):
            with pytest.raises(ParseError, match="size limit"):
                await scraper.scrape(TITLE)
            assert manager.mock_calls == []
            redis.zrem.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize("enabled", [True, False])
def test_scrape_service_flag_and_resource_cleanup_across_separate_event_loops(monkeypatch, enabled):
    events = []
    clients = []

    @asynccontextmanager
    async def redis_context():
        events.append("redis_open")
        try:
            yield Mock()
        finally:
            events.append("redis_close")

    def http_client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["timeout"].as_dict() == {"connect": 10, "read": 30, "write": 10, "pool": 10}
        assert kwargs["limits"].max_connections == 10
        client = actual_httpx_client(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
        clients.append(client)
        return client

    actual_httpx_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", http_client)
    monkeypatch.setattr(competitor_service.settings, "daraz_scraping_authorized", True)
    monkeypatch.setattr(competitor_service, "SCRAPER_HTTPX_ENABLED", enabled)
    monkeypatch.setattr(competitor_service.Redis, "from_url", lambda *args, **kwargs: redis_context())
    browser_manager = SimpleNamespace(close=AsyncMock(side_effect=lambda: events.append("browser_close")))
    monkeypatch.setattr(competitor_service, "BrowserManager", lambda: browser_manager)

    def make_scraper(manager, redis, *, http):
        assert (http is not None) is enabled
        return SimpleNamespace(scrape=AsyncMock(side_effect=PageLoadError("fixture")))

    monkeypatch.setattr(competitor_service, "DarazScraper", make_scraper)
    for _ in range(2):
        with pytest.raises(PageLoadError):
            asyncio.run(competitor_service.scrape_daraz_competitors(product_title=TITLE))
    assert events == ["redis_open", "browser_close", "redis_close"] * 2
    assert len(clients) == (2 if enabled else 0)
    assert all(client.is_closed for client in clients)


def test_playwright_api_starts_driver_without_chromium_and_disposes_on_error(monkeypatch):
    api = SimpleNamespace(dispose=AsyncMock())
    playwright = SimpleNamespace(
        request=SimpleNamespace(new_context=AsyncMock(return_value=api)),
        chromium=SimpleNamespace(launch=AsyncMock()),
        stop=AsyncMock(),
    )
    monkeypatch.setattr(browser, "async_playwright", lambda: SimpleNamespace(start=AsyncMock(return_value=playwright)))

    async def run():
        manager = BrowserManager()
        try:
            async with manager.request_context(user_agent="fixture"):
                raise RuntimeError("fixture")
        finally:
            await manager.close()

    with pytest.raises(RuntimeError):
        asyncio.run(run())
    api.dispose.assert_awaited_once()
    playwright.stop.assert_awaited_once()
    playwright.chromium.launch.assert_not_awaited()


def test_cancelled_playwright_start_is_owned_and_closed(monkeypatch):
    async def run():
        starting = asyncio.Event()
        complete = asyncio.Event()
        runtime = SimpleNamespace(stop=AsyncMock())

        async def start():
            starting.set()
            await complete.wait()
            return runtime

        monkeypatch.setattr(browser, "async_playwright", lambda: SimpleNamespace(start=start))
        manager = BrowserManager()

        async def acquire():
            try:
                async with manager.request_context(user_agent="fixture"):
                    pytest.fail("cancelled startup should not open a context")
            finally:
                await manager.close()

        task = asyncio.create_task(acquire())
        await starting.wait()
        task.cancel()
        complete.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        runtime.stop.assert_awaited_once()

    asyncio.run(run())


def test_browser_reuses_connected_instance_within_loop_and_reopens_when_disconnected(monkeypatch):
    first = SimpleNamespace(is_connected=Mock(side_effect=[True, False]), close=AsyncMock())
    second = SimpleNamespace(close=AsyncMock())
    launch = AsyncMock(side_effect=[first, second])
    playwright = SimpleNamespace(chromium=SimpleNamespace(launch=launch), stop=AsyncMock())
    monkeypatch.setattr(browser, "async_playwright", lambda: SimpleNamespace(start=AsyncMock(return_value=playwright)))
    manager = BrowserManager()

    async def run():
        assert await manager._ensure_browser() is first
        assert await manager._ensure_browser() is first
        assert await manager._ensure_browser() is second
        await manager.close()

    asyncio.run(run())
    assert launch.await_count == 2
    first.close.assert_awaited_once()
    second.close.assert_awaited_once()
    playwright.stop.assert_awaited_once()
    with pytest.raises(BrowserError, match="event loops"):
        asyncio.run(manager._ensure_browser())


def test_browser_context_closes_when_page_creation_fails(monkeypatch):
    context = SimpleNamespace(new_page=AsyncMock(side_effect=PlaywrightError("fixture")), close=AsyncMock())
    manager = BrowserManager()
    monkeypatch.setattr(manager, "new_context", AsyncMock(return_value=context))

    async def run():
        async with manager.page(user_agent="fixture"):
            pytest.fail("new_page should have failed")

    with pytest.raises(PlaywrightError):
        asyncio.run(run())
    context.close.assert_awaited_once()


def test_detail_concurrency_and_cancellation_release_in_flight_work(monkeypatch):
    async def run():
        scraper = DarazScraper(Mock(), Mock())
        maximum = 0
        active = 0
        started = 0
        ready = asyncio.Event()

        async def details(url):
            nonlocal maximum, active, started
            active += 1
            started += 1
            maximum = max(maximum, active)
            if active == 3:
                ready.set()
            try:
                await ready.wait()
                if url.endswith("0.html"):
                    raise PermanentAccessError("fixture")
                await asyncio.Future()
            finally:
                active -= 1

        monkeypatch.setattr(daraz_scraper, "DETAILS_CONCURRENCY", 3)
        monkeypatch.setattr(scraper, "_fetch_details", details)
        items = [
            (ScrapedProduct(title="Fixture", product_url=f"https://www.daraz.com.bd/products/{i}.html", search_position=i + 1), 0.0)
            for i in range(8)
        ]
        with pytest.raises(PermanentAccessError):
            await asyncio.wait_for(scraper._enrich_products(items, datetime.now(timezone.utc)), timeout=2)
        assert (maximum, started, active) == (3, 3, 0)

    asyncio.run(run())


def test_redis_outage_fails_closed_before_http_or_browser(monkeypatch):
    http = SimpleNamespace(get=AsyncMock())
    redis = SimpleNamespace(eval=AsyncMock(side_effect=RedisError("fixture")))
    manager = Mock()
    with pytest.raises(CoordinationError):
        asyncio.run(DarazScraper(manager, redis, http=http).scrape(TITLE))
    http.get.assert_not_awaited()
    assert manager.mock_calls == []


def test_cancelled_slot_admission_attempt_releases_possible_redis_lease():
    async def run():
        entered = asyncio.Event()

        async def evaluate(*args):
            entered.set()
            await asyncio.Future()

        redis = SimpleNamespace(eval=AsyncMock(side_effect=evaluate), zrem=AsyncMock())
        coordinator = DarazRequestCoordinator(redis)

        async def enter():
            async with coordinator.slot():
                pytest.fail("no request should start")

        task = asyncio.create_task(enter())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        redis.zrem.assert_awaited_once()
        assert redis.zrem.await_args.args[-1] == redis.eval.await_args.args[5]

    asyncio.run(run())


def test_shared_redis_pacing_concurrency_cooldown_and_cancellation(monkeypatch):
    redis_url = os.environ.get("BAZARSYNC_TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("set BAZARSYNC_TEST_REDIS_URL for a disposable Redis integration check")
    for key in ("_COOLDOWN_KEY", "_START_KEY", "_LEASES_KEY"):
        monkeypatch.setattr(rate_limit, key, f"{getattr(rate_limit, key)}:test:{os.getpid()}")

    async def run():
        config = DarazRateConfig(min_interval=0.025, max_in_flight=1, slot_wait=1)
        async with Redis.from_url(redis_url) as redis_a, Redis.from_url(redis_url) as redis_b:
            first, second = DarazRequestCoordinator(redis_a, config), DarazRequestCoordinator(redis_b, config)
            starts = []
            finished = []

            async def hold(coordinator):
                async with coordinator.slot():
                    starts.append(asyncio.get_running_loop().time())
                    await asyncio.sleep(0.04)
                    finished.append(asyncio.get_running_loop().time())

            try:
                await asyncio.gather(hold(first), hold(second))
                assert starts[1] >= finished[0]
                async with first.slot():
                    start = asyncio.get_running_loop().time()
                async with second.slot():
                    assert asyncio.get_running_loop().time() - start >= 0.020

                entered = asyncio.Event()

                async def wait_for_cancel():
                    async with first.slot():
                        entered.set()
                        await asyncio.Future()

                task = asyncio.create_task(wait_for_cancel())
                await entered.wait()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert await redis_b.zcard(rate_limit._LEASES_KEY) == 0

                await first.defer(4)
                await second.defer(1)
                with pytest.raises(RateLimitError) as exc:
                    async with second.slot():
                        pytest.fail("global cooldown should prevent admission")
                assert exc.value.retry_after >= 3
            finally:
                await redis_a.delete(rate_limit._COOLDOWN_KEY, rate_limit._START_KEY, rate_limit._LEASES_KEY)

    asyncio.run(run())
