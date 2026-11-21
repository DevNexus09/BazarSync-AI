from __future__ import annotations

from contextlib import AsyncExitStack
from uuid import UUID

from redis.asyncio import Redis

from app.core.config import settings
from app.scraper.acquisition.http_client import DarazHttpClient
from app.scraper.acquisition.metadata_cache import DarazMetadataCache
from app.scraper.browser import BrowserManager
from app.scraper.constants import SCRAPER_HTTPX_ENABLED, SCRAPER_METADATA_CACHE_TTL, SCRAPER_USER_AGENT
from app.scraper.daraz_scraper import DarazScraper
from app.scraper.exceptions import DarazAcquisitionDisabledError
from app.scraper.schemas import ScrapeResponse
from app.scraper.utils import build_headers


async def scrape_daraz_competitors(
    *,
    product_title: str,
    seller_id: UUID | None = None,
) -> ScrapeResponse:
    if not settings.daraz_scraping_authorized:
        raise DarazAcquisitionDisabledError("Daraz acquisition has not been authorized in this deployment.")

    from app.core.celery_app import redis_url

    async with AsyncExitStack() as stack:
        redis = await stack.enter_async_context(
            Redis.from_url(redis_url, socket_connect_timeout=3, socket_timeout=3),
        )
        browser_manager = BrowserManager()
        stack.push_async_callback(browser_manager.close)
        http = None
        if SCRAPER_HTTPX_ENABLED:
            http = await stack.enter_async_context(DarazHttpClient.open(build_headers(SCRAPER_USER_AGENT)))
        scraper = DarazScraper(browser_manager, redis, http=http)
        if seller_id is not None and SCRAPER_METADATA_CACHE_TTL:
            scraper.metadata_cache = DarazMetadataCache(redis, seller_id, SCRAPER_METADATA_CACHE_TTL)
        return await scraper.scrape(product_title=product_title)
