from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.scraper.acquisition import rate_limit
from app.scraper.acquisition.metadata_cache import DarazMetadataCache
from app.scraper.acquisition.rate_limit import CircuitOpenError, CoordinationError, DarazRequestCoordinator
from app.scraper.constants import DarazRateConfig
from app.scraper.daraz_scraper import DarazScraper
from app.scraper.exceptions import PageLoadError
from app.scraper.schemas import CompetitorProduct, ScrapeResponse
from app.scraper.schemas.scraped_product import DetailExtraction, ExtractionQuality, ObservationProvenance, ProductFields
from app.scraper.telemetry import ScrapeTelemetry
from app.services.scrape_scheduling import RefreshCandidate, RefreshPolicy, due_at

URL = "https://www.daraz.com.bd/products/fixture.html?variant=1"


def test_due_policy_requires_observed_prices_for_stability_and_applies_failure_cooldown():
    now = datetime.now(timezone.utc)
    policy = RefreshPolicy()
    product, seller = uuid4(), uuid4()
    success = now - timedelta(hours=7)
    assert due_at(RefreshCandidate(product, seller, None, None, 0, 0, 0), policy) is None
    assert due_at(RefreshCandidate(product, seller, success, success, 0, 0, 0), policy) == success + timedelta(hours=6)
    assert due_at(RefreshCandidate(product, seller, success, success, 0, 0, 4), policy) == success + timedelta(hours=12)
    assert due_at(RefreshCandidate(product, seller, success, success, 0, 3, 4), policy) == success + timedelta(hours=3)
    assert due_at(RefreshCandidate(product, seller, success, now, 2, 3, 4), policy) == now + timedelta(hours=12)


def test_metadata_cache_fails_open_for_optional_metadata():
    redis = AsyncMock()
    redis.get.side_effect = RedisError("fixture")
    live = AsyncMock(return_value=None)
    assert asyncio.run(DarazMetadataCache(redis, uuid4(), 60).fetch(URL, live)) is None
    live.assert_awaited_once_with(URL)


def test_telemetry_separates_extraction_quality_and_cache_provenance(caplog):
    now = datetime.now(timezone.utc)
    telemetry = ScrapeTelemetry.start(uuid4(), uuid4(), 2)
    telemetry.acquired(ScrapeResponse(
        query="private fixture query", marketplace="Daraz Bangladesh", scraped_at=now,
        total_results=1, raw_listing_count=3, validated_listing_count=2, search_acquisition_method="httpx",
        products=[CompetitorProduct(
            search_position=1, extraction_quality=ExtractionQuality(status="PARTIAL", score=0.5, missing_important=("stock_status",)),
            provenance=ObservationProvenance(search_observed_at=now, metadata_cached_at=now),
        )],
    ))
    telemetry.matching_status = "success"
    telemetry.competitors_matched = 0
    with caplog.at_level("INFO", logger="app.scraper.telemetry"):
        telemetry.emit(0.2)
    event = json.loads(caplog.records[-1].message)
    assert (event["parser_status"], event["matching_status"], event["retry_count"]) == ("partial", "success", 2)
    assert (event["products_found"], event["products_validated"], event["competitors_matched"]) == (3, 2, 0)
    assert event["metadata_cache_hits"] == 1
    assert event["missing_important"] == {"stock_status": 1}
    assert "private fixture query" not in caplog.records[-1].message


@pytest.fixture
def redis_url(monkeypatch):
    url = os.environ.get("BAZARSYNC_TEST_REDIS_URL")
    if not url:
        pytest.skip("set BAZARSYNC_TEST_REDIS_URL to run disposable Redis tests")
    suffix = uuid4().hex
    for key in ("_COOLDOWN_KEY", "_START_KEY", "_LEASES_KEY"):
        monkeypatch.setattr(rate_limit, key, f"{getattr(rate_limit, key)}:{suffix}")
    return url


def test_metadata_cache_tenant_variant_ttl_and_stampede(redis_url):
    async def run():
        async with Redis.from_url(redis_url) as redis:
            cache = DarazMetadataCache(redis, uuid4(), 60)
            other = DarazMetadataCache(redis, uuid4(), 60)
            entered, release = asyncio.Event(), asyncio.Event()

            async def fetch(_url):
                entered.set()
                await release.wait()
                return DetailExtraction.observed(ProductFields(
                    description="Public metadata", brand="Fixture", current_price=Decimal("99"),
                    stock_status="OUT_OF_STOCK", seller_name="old seller",
                ), "httpx")

            live = AsyncMock(side_effect=fetch)
            first = asyncio.create_task(cache.fetch(URL, live))
            await entered.wait()
            second = asyncio.create_task(cache.fetch(URL + "#ignored", live))
            release.set()
            fresh, hit = await asyncio.gather(first, second)
            assert live.await_count == 1
            assert fresh.fields.current_price == Decimal("99")
            assert hit.metadata_cached and hit.price_observed_at is None
            assert hit.fields.current_price is None and hit.fields.seller_name is None and hit.fields.stock_status == "UNKNOWN"
            assert hit.fields.description == "Public metadata"
            assert cache._key(URL) != other._key(URL)
            assert cache._key(URL) != cache._key(URL.replace("variant=1", "variant=2"))
            assert 0 < await redis.ttl(cache._key(URL)) <= 60
            await redis.delete(cache._key(URL))

    asyncio.run(run())


def test_domain_budget_and_circuit_probe_recovery(redis_url):
    async def run():
        config = DarazRateConfig(
            min_interval=0.001, slot_wait=0.08, budget_per_minute=4,
            circuit_failures=2, circuit_cooldown=2, circuit_window=10,
        )
        async with Redis.from_url(redis_url) as first, Redis.from_url(redis_url) as second:
            a, b = DarazRequestCoordinator(first, config), DarazRequestCoordinator(second, config)
            for worker in (a, b):
                with pytest.raises(PageLoadError, match="upstream"):
                    async with worker.slot():
                        raise PageLoadError("upstream")
            with pytest.raises(CircuitOpenError) as blocked:
                async with a.slot():
                    pytest.fail("network must remain blocked")
            assert blocked.value.retry_after > 0
            await first.delete(rate_limit._COOLDOWN_KEY + ":open")
            async with b.slot():
                with pytest.raises(CircuitOpenError):
                    async with a.slot():
                        pytest.fail("only one recovery probe may run")
            assert not await first.exists(rate_limit._COOLDOWN_KEY + ":recover")
            async with a.slot():
                pass
            with pytest.raises(CoordinationError) as limited:
                async with b.slot():
                    pytest.fail("rolling budget must block a fifth request")
            assert limited.value.retry_after >= 59

    asyncio.run(run())


def test_cached_details_skip_requests_and_keep_live_prices(redis_url):
    async def run():
        async with Redis.from_url(redis_url) as redis:
            scraper = DarazScraper(Mock(), redis)
            scraper.metadata_cache = DarazMetadataCache(redis, uuid4(), 60)
            live = AsyncMock(return_value=DetailExtraction.observed(ProductFields(
                description="Cached description", brand="Fixture", current_price=Decimal("999"),
            ), "httpx"))
            scraper._fetch_details = live
            payloads = [
                {"mods": {"listItems": [{"name": "Fixture", "itemUrl": URL,
                                         "price": price, "sellerName": "store", "inStock": stock}]}}
                for price, stock in [(100, True), (120, False), (None, True)]
            ]
            scraper._fetch_ajax_payload = AsyncMock(side_effect=payloads)
            try:
                first = (await scraper.scrape("Fixture")).products[0]
                second = (await scraper.scrape("Fixture")).products[0]
                third = (await scraper.scrape("Fixture")).products[0]
                assert first.provenance.metadata_cached_at is None
                assert second.provenance.metadata_cached_at is not None
                assert second.provenance.detail_observed_at is None
                assert second.provenance.price_observed_at == second.provenance.search_observed_at
                assert second.product_description == "Cached description"
                assert (first.product_price, second.product_price, third.product_price) == (100, 120, 999)
                assert second.stock_status == "out_of_stock"
                assert live.await_count == 2
            finally:
                await redis.delete(scraper.metadata_cache._key(URL))

    asyncio.run(run())
