from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from collections import Counter
from collections.abc import Mapping
from contextlib import suppress
from datetime import datetime, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urldefrag, urlsplit

from bs4 import BeautifulSoup, SoupStrainer
from playwright.async_api import Error, Route, TimeoutError as PlaywrightTimeoutError
from redis.asyncio import Redis

from app.scraper.acquisition.http_client import DarazHttpClient, HttpResponse
from app.scraper.acquisition.metadata_cache import DarazMetadataCache
from app.scraper.acquisition.rate_limit import CircuitOpenError, CoordinationError, DarazRequestCoordinator
from app.scraper.browser import BrowserManager
from app.scraper.constants import (
    AJAX_TIMEOUT_MS,
    DARAZ_BASE_URL,
    DARAZ_SEARCH_PATH,
    DETAILS_CONCURRENCY,
    DEFAULT_MAX_RESULTS,
    DEFAULT_TIMEOUT_MS,
    MARKETPLACE_NAME,
    SCRAPER_USER_AGENT,
    WEIGHTED_RATING_C,
    WEIGHTS,
)
from app.scraper.exceptions import (
    PageLoadError,
    ParseError,
    PermanentAccessError,
    RateLimitError,
    RequestTimeoutError,
    ScraperError,
)
from app.scraper.parser import DarazParser, fill_product, to_competitor
from app.scraper.schemas import AcquisitionMethod, CompetitorProduct, ScrapeResponse
from app.scraper.schemas.scraped_product import (
    PARSER_VERSION,
    DetailExtraction,
    ObservationProvenance,
    ScrapedProduct,
    assess_extraction,
)
from app.scraper.similarity import is_obviously_unrelated
from app.scraper.utils import (
    build_headers,
    build_search_url,
    is_daraz_product_url,
    random_delay,
    sanitize_query,
)

logger = logging.getLogger(__name__)


class DarazScraper:
    def __init__(
        self, browser_manager: BrowserManager, redis: Redis, *, http: DarazHttpClient | None = None,
    ) -> None:
        self._browser_manager = browser_manager
        self._requests = DarazRequestCoordinator(redis)
        self._http = http
        self.metadata_cache: DarazMetadataCache | None = None
        self._parser = DarazParser()
        self._headers = build_headers(SCRAPER_USER_AGENT)

    async def scrape(self, product_title: str) -> ScrapeResponse:
        query = sanitize_query(product_title)
        if not query:
            raise ScraperError("Product title cannot be empty.")

        start = time.monotonic()
        products_raw, method = await self._search(query)
        logger.info(
            "daraz_search_acquired method=%s elapsed_ms=%.1f listing_count=%s",
            method, (time.monotonic() - start) * 1000, len(products_raw),
        )
        search_observed_at = datetime.now(timezone.utc)
        ranked = self._rank_products(products_raw)
        promising = [item for item in ranked if not is_obviously_unrelated(query, item[0].title)]
        selected = promising[:DEFAULT_MAX_RESULTS]
        products = await self._enrich_products(selected, search_observed_at)
        details = Counter(item.detail_acquisition_method or "unavailable" for item in products)
        quality = Counter(item.extraction_quality.status for item in products if item.extraction_quality)
        logger.info(
            "daraz_acquisition_complete daraz_parser_version=%s search_method=%s elapsed_ms=%.1f "
            "detail_methods=%s extraction_status=%s relevance_filtered=%s selected=%s",
            PARSER_VERSION, method, (time.monotonic() - start) * 1000, dict(details), dict(quality),
            len(ranked) - len(promising), len(selected),
        )
        return ScrapeResponse(
            query=product_title,
            marketplace=MARKETPLACE_NAME,
            scraped_at=datetime.now(timezone.utc),
            total_results=len(products),
            search_acquisition_method=method,
            products=products,
            raw_listing_count=self._parser.raw_listing_count,
            validated_listing_count=len(products_raw),
        )

    async def _search(self, query: str) -> tuple[list[ScrapedProduct], AcquisitionMethod]:
        ajax_url = build_search_url(query, ajax=True)
        if self._http is not None:
            response = await self._fetch_httpx(ajax_url, ajax=True)
            payload = response.json_object() if response is not None else None
            if payload is not None:
                products = self._parser.extract_ajax(payload, max_results=None)
                if products is not None:
                    return products, "httpx"
            logger.info("daraz_search_fallback from=httpx to=playwright_api")

        payload = await self._fetch_ajax_payload(ajax_url)
        if payload is not None:
            products = self._parser.extract_ajax(payload, max_results=None)
            if products is not None:
                return products, "playwright_api"

        search_url = build_search_url(query)
        if self._http is not None:
            response = await self._fetch_httpx(search_url, ajax=False)
            if response is not None and response.content_type in _HTML_TYPES:
                products = self._parser.extract_html(response.text(), max_results=None)
                if products is not None:
                    return products, "httpx"

        logger.info("daraz_search_fallback to=chromium")
        html = await self._fetch_search_html(search_url)
        products = self._parser.extract_html(html, max_results=None)
        if not products:
            raise ParseError("Daraz search page did not contain recognizable listings.")
        return products, "chromium"

    async def _fetch_httpx(self, url: str, *, ajax: bool, detail: bool = False) -> HttpResponse | None:
        if self._http is None:
            return None

        try:
            async with self._requests.slot():
                response = await self._http.get(url)
                if ajax and _ajax_unsupported(response.status, response.headers.get("retry-after")):
                    _reject_challenge(response.headers)
                    return None
                retry_after = response.headers.get("retry-after")
                if detail and response.status in {404, 410} and not retry_after:
                    _reject_challenge(response.headers)
                    return response
                await self._check_status(response.status, retry_after)
                _reject_challenge(response.headers)
                if response.content_type in _HTML_TYPES or response.body.lstrip().startswith(b"<"):
                    _reject_challenge(response.headers, response.text())
                return response
        except (RateLimitError, CoordinationError, CircuitOpenError):
            raise
        except PageLoadError as exc:
            if exc.retry_after:
                raise
            logger.info("daraz_httpx_temporary_failure failure_code=%s", exc.failure_code)
            return None

    async def _fetch_ajax_payload(self, url: str) -> dict[str, Any] | None:
        try:
            async with self._browser_manager.request_context(
                user_agent=SCRAPER_USER_AGENT, extra_headers=self._headers,
            ) as context:
                async with self._requests.slot():
                    response = await context.get(url, timeout=AJAX_TIMEOUT_MS, max_redirects=0)
                    retry_after = response.headers.get("retry-after")
                    if _ajax_unsupported(response.status, retry_after):
                        _reject_challenge(response.headers)
                        return None
                    await self._check_status(response.status, retry_after)
                    _reject_challenge(response.headers)
                    body = await response.text()
                    try:
                        payload = json.loads(body, parse_float=Decimal)
                    except (ValueError, RecursionError):
                        _reject_challenge(response.headers, body)
                        return None
                    return payload if isinstance(payload, dict) else None
        except PlaywrightTimeoutError as exc:
            raise RequestTimeoutError("Daraz AJAX search timed out.") from exc
        except Error as exc:
            raise PageLoadError("Daraz AJAX search could not be reached.") from exc

    async def _fetch_search_html(self, url: str) -> str:
        try:
            html = await self._fetch_html(url, detail=False)
        except PlaywrightTimeoutError as exc:
            raise RequestTimeoutError("Daraz HTML search timed out.") from exc
        except Error as exc:
            raise PageLoadError("Daraz HTML search could not be reached.") from exc
        if html is None:
            raise ParseError("Daraz HTML search returned no response.")
        return html

    async def _fetch_html(self, url: str, *, detail: bool) -> str | None:
        async with self._browser_manager.page(
            user_agent=SCRAPER_USER_AGENT, extra_headers=self._headers,
        ) as page:
            navigation_error: ScraperError | Error | None = None
            active_handlers: set[asyncio.Task[Any]] = set()
            subresources = 0

            async def restrict_navigation(route: Route) -> None:
                nonlocal navigation_error, subresources
                handler = asyncio.current_task()
                if handler is not None:
                    active_handlers.add(handler)
                request = route.request
                navigation = request.is_navigation_request()
                try:
                    if navigation_error is not None:
                        await route.abort()
                        return
                    target = request.url
                    if navigation:
                        if request.frame != page.main_frame:
                            await route.abort()
                            return
                        if not (is_daraz_product_url(target) if detail else _is_search_url(target)):
                            raise PermanentAccessError("Daraz redirected outside the authorized scrape path.")
                    else:
                        # Scripts and styles can be required for rendering. Skip heavy media and cap
                        # the requests a document can initiate. Browser subresources share the quota.
                        if (
                            request.method != "GET" or urlsplit(target).scheme != "https"
                            or request.resource_type in {"image", "font", "media"}
                            or subresources >= _MAX_BROWSER_SUBRESOURCES
                        ):
                            await route.abort()
                            return
                        subresources += 1

                    async with self._requests.slot(track=navigation):
                        # route.continue_() can follow redirects without invoking this handler again.
                        response = await route.fetch(max_redirects=0, timeout=DEFAULT_TIMEOUT_MS - 1_000)
                        try:
                            retry_after = response.headers.get("retry-after")
                            if navigation and not (detail and response.status in {404, 410} and not retry_after):
                                await self._check_status(response.status, retry_after)
                                _reject_challenge(response.headers)
                            elif not navigation:
                                if _is_marketplace_url(target) and (response.status in {401, 403, 429, 451} or retry_after):
                                    await self._check_status(response.status, retry_after)
                                if 300 <= response.status < 400:
                                    await route.abort()
                                    return
                            await route.fulfill(response=response)
                        finally:
                            await response.dispose()
                except (ScraperError, Error) as exc:
                    if navigation or isinstance(exc, (PermanentAccessError, RateLimitError, CoordinationError)) or (
                        isinstance(exc, PageLoadError) and exc.retry_after and not isinstance(exc, CircuitOpenError)
                    ):
                        navigation_error = exc
                    await route.abort()
                finally:
                    if handler is not None:
                        active_handlers.discard(handler)

            await page.route("**/*", restrict_navigation)
            try:
                try:
                    response = await page.goto(url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
                except Error as exc:
                    if navigation_error is not None:
                        raise navigation_error from exc
                    raise
                if navigation_error is not None:
                    raise navigation_error
                if response is None or (detail and response.status in {404, 410}):
                    return None
                await random_delay()
                if navigation_error is not None:
                    raise navigation_error
                html = await page.content()
                _reject_challenge(response.headers, html)
                return html
            finally:
                try:
                    # Keep routing active until the page is closed so late requests stay paced.
                    with suppress(Error, TimeoutError):
                        async with asyncio.timeout(5):
                            await page.close()
                finally:
                    handlers = list(active_handlers)
                    for handler in handlers:
                        handler.cancel()
                    await asyncio.gather(*handlers, return_exceptions=True)

    async def _check_status(self, status: int, retry_after: str | None) -> None:
        if status in {401, 403, 451}:
            try:
                await self._requests.defer(max(60, _retry_after_seconds(retry_after)))
            except CoordinationError as exc:
                # This response remains permanent even if Redis cannot share the cooldown.
                raise PermanentAccessError(f"Daraz returned HTTP {status}.") from exc
            raise PermanentAccessError(f"Daraz returned HTTP {status}.")
        delay = _retry_after_seconds(retry_after)
        if status == 429 and delay == 0:
            delay = 60
        if delay and status >= 400:
            await self._requests.defer(delay)
        if status == 429:
            raise RateLimitError("Daraz returned HTTP 429.", delay)
        if status == 408:
            raise RequestTimeoutError("Daraz returned HTTP 408.", delay)
        if status >= 500:
            raise PageLoadError(f"Daraz returned HTTP {status}.", delay)
        if not 200 <= status < 300:
            raise PermanentAccessError(f"Daraz returned HTTP {status}.")

    def _rank_products(self, products: list[ScrapedProduct]) -> list[tuple[ScrapedProduct, float]]:
        signals: list[dict[str, float | int | Decimal | None]] = []
        ranked_inputs = []
        for item in products:
            price = item.current_price
            original_price = item.original_price
            discount = item.discount_percentage
            if discount is None and price is not None and original_price is not None and original_price > price:
                discount = round((original_price - price) / original_price * 100)
                item = item.model_copy(update={"discount_percentage": discount})
            ranked_inputs.append(item)

            sold_count = item.sold_count
            rating = item.rating
            rating_count = item.review_count
            signals.append({
                "sold": sold_count,
                "price_weighted_popularity": price * sold_count if price is not None and sold_count is not None else None,
                "weighted_rating": (rating * rating_count) / (rating_count + WEIGHTED_RATING_C)
                if rating is not None and rating_count is not None else None,
                "rating_count": rating_count,
                "discount": discount,
            })

        ranges = {}
        for name in WEIGHTS:
            known = [values[name] for values in signals if values[name] is not None]
            ranges[name] = (min(known), max(known)) if known else (0.0, 0.0)

        ranked = []
        for item, values in zip(ranked_inputs, signals, strict=True):
            score = 0.0
            for name, value in values.items():
                low, high = ranges[name]
                if value is not None and high > low:
                    score += WEIGHTS[name] * float((value - low) / (high - low))
            ranked.append((item, round(score * self._stock_multiplier(item), 4)))
        return sorted(ranked, key=lambda entry: entry[1], reverse=True)

    async def _fetch_details(self, url: str) -> DetailExtraction | None:
        lightweight = None
        if self._http is not None:
            response = await self._fetch_httpx(url, ajax=False, detail=True)
            if response is not None:
                if response.status in {404, 410}:
                    return None
                if response.content_type in _HTML_TYPES:
                    details = self._parser.extract_detail(response.text(), url)
                    if details.field_sources:
                        lightweight = DetailExtraction.observed(details, "httpx")
                        if any((details.description, details.brand, details.category, details.specifications)):
                            return lightweight

        try:
            html = await self._fetch_html(url, detail=True)
        except (PlaywrightTimeoutError, Error) as exc:
            if lightweight is None:
                raise
            logger.warning("daraz_rendered_detail_unavailable error_type=%s", type(exc).__name__)
            return lightweight
        if html:
            details = self._parser.extract_detail(html, url)
            if details.field_sources:
                if lightweight is not None:
                    rendered = DetailExtraction.observed(details, "chromium")
                    return DetailExtraction(
                        fields=fill_product(lightweight.fields, rendered.fields),
                        method="chromium", observed_at=rendered.observed_at,
                        price_observed_at=lightweight.price_observed_at or rendered.price_observed_at,
                        stock_observed_at=(
                            lightweight.stock_observed_at if lightweight.fields.stock_status != "UNKNOWN"
                            else rendered.stock_observed_at
                        ),
                    )
                return DetailExtraction.observed(details, "chromium")
        return lightweight

    async def _enrich_products(
        self, products: list[tuple[ScrapedProduct, float]], search_observed_at: datetime,
    ) -> list[CompetitorProduct]:
        semaphore = asyncio.Semaphore(DETAILS_CONCURRENCY)
        stop = asyncio.Event()

        live_required = {
            urldefrag(item.product_url).url for item, _ in products
            if item.current_price is None or item.stock_status == "UNKNOWN" or not item.seller_name
        }

        async def fetch_details(url: str) -> DetailExtraction | None:
            async with semaphore:
                if stop.is_set():
                    return None
                try:
                    if self.metadata_cache and url not in live_required:
                        return await self.metadata_cache.fetch(url, self._fetch_details)
                    return await self._fetch_details(url)
                except (PermanentAccessError, RateLimitError, CoordinationError, CircuitOpenError):
                    stop.set()
                    raise
                except PageLoadError as exc:
                    if exc.retry_after:
                        stop.set()
                        raise
                    logger.warning("daraz_detail_unavailable error_type=%s", type(exc).__name__)
                except (PlaywrightTimeoutError, Error, ParseError) as exc:
                    logger.warning("daraz_detail_unavailable error_type=%s", type(exc).__name__)
                return None

        urls = [urldefrag(item.product_url).url for item, _ in products]
        tasks = {url: asyncio.create_task(fetch_details(url)) for url in dict.fromkeys(urls) if is_daraz_product_url(url)}
        try:
            await asyncio.gather(*tasks.values())
            results = []
            for (item, score), url in zip(products, urls, strict=True):
                details = tasks[url].result() if url in tasks else None
                method = detail_at = cached_at = None
                price_at = search_observed_at if item.current_price is not None else None
                stock_at = search_observed_at if item.stock_status != "UNKNOWN" else None
                if details is not None:
                    if details.metadata_cached:
                        cached_at = details.observed_at
                    else:
                        method, detail_at = details.method, details.observed_at
                    if price_at is None:
                        price_at = details.price_observed_at
                    if stock_at is None and not details.metadata_cached:
                        stock_at = details.stock_observed_at
                    item = fill_product(item, details.fields)
                results.append(to_competitor(
                    item, ranking_score=score, detail_acquisition_method=method,
                    extraction_quality=assess_extraction(item, self._parser.weights),
                    provenance=ObservationProvenance(
                        search_observed_at=search_observed_at, detail_observed_at=detail_at, metadata_cached_at=cached_at,
                        price_observed_at=price_at, stock_observed_at=stock_at, field_sources=item.field_sources,
                    ),
                ))
            return results
        finally:
            for task in tasks.values():
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)

    @staticmethod
    def _stock_multiplier(item: ScrapedProduct) -> float:
        if item.stock_status == "OUT_OF_STOCK":
            return 0.0
        if "low" in (item.stock_text or "").lower():
            return 0.6
        return 1.0


_TITLE_ONLY = SoupStrainer("title")
_HTML_TYPES = {"text/html", "application/xhtml+xml"}
_MAX_BROWSER_SUBRESOURCES = 48


def _ajax_unsupported(status: int, retry_after: str | None) -> bool:
    return status in {400, 404, 405, 415} and not retry_after


def _is_marketplace_url(url: str) -> bool:
    target = urlsplit(url)
    return target.scheme == "https" and target.netloc == urlsplit(DARAZ_BASE_URL).netloc


def _is_search_url(url: str) -> bool:
    return _is_marketplace_url(url) and urlsplit(url).path == DARAZ_SEARCH_PATH


def _retry_after_seconds(value: str | None) -> int:
    if not value:
        return 0
    value = value.strip()
    try:
        if value.isascii() and value.isdecimal():
            return int(value)
        when = parsedate_to_datetime(value)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0, math.ceil((when - datetime.now(timezone.utc)).total_seconds()))
    except (ValueError, TypeError, OverflowError):
        return 0


def _reject_challenge(headers: Mapping[str, str], html: str = "") -> None:
    if headers.get("cf-mitigated", "").lower() == "challenge":
        raise PermanentAccessError("Daraz requested an access challenge.")
    if html:
        title = BeautifulSoup(html, "lxml", parse_only=_TITLE_ONLY).title
        if title and any(
            marker in title.get_text(" ", strip=True).lower()
            for marker in ("captcha", "access denied", "verify you are human", "just a moment")
        ):
            raise PermanentAccessError("Daraz requested an access challenge.")
