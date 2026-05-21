from __future__ import annotations

import logging
from datetime import datetime, timezone
import asyncio
from typing import Any

from playwright.async_api import Error, TimeoutError as PlaywrightTimeoutError

from app.scraper.browser import BrowserManager
from app.scraper.constants import (
    AJAX_TIMEOUT_MS,
    DEFAULT_MAX_RESULTS,
    DEFAULT_TIMEOUT_MS,
    MARKETPLACE_NAME,
    RETRY_ATTEMPTS,
    WEIGHTED_RATING_C,
    WEIGHTS,
)
from app.scraper.exceptions import PageLoadError, ParseError, ScraperError
from app.scraper.parser import DarazParser
from app.scraper.schemas import CompetitorProduct, ScrapeResponse
from app.scraper.utils import (
    build_headers,
    build_search_url,
    get_random_user_agent,
    parse_sold_count_number,
    random_delay,
    retry_async,
    sanitize_query,
)

logger = logging.getLogger(__name__)


class DarazScraper:
    def __init__(self, browser_manager: BrowserManager) -> None:
        self._browser_manager = browser_manager
        self._parser = DarazParser()

    async def scrape(self, product_title: str) -> ScrapeResponse:
        query = sanitize_query(product_title)
        if not query:
            raise ScraperError("Product title cannot be empty.")

        search_url = build_search_url(query)
        ajax_url = build_search_url(query, ajax=True)
        user_agent = get_random_user_agent()
        headers = build_headers(user_agent)

        payload = await self._fetch_ajax_payload(ajax_url, user_agent, headers)
        products_raw: list[dict[str, Any]] = []
        if payload:
            products_raw = self._parser.parse_products_from_json(payload, max_results=None)
        if not products_raw:
            html = await self._fetch_search_html(search_url, user_agent, headers)
            products_raw = self._parser.parse_products(html, max_results=None)

        if not products_raw and payload is None:
            raise ParseError("Daraz returned no products to parse.")

        ranked = self._rank_products(products_raw)
        enriched = await self._enrich_products(ranked[:DEFAULT_MAX_RESULTS], user_agent, headers)
        products = [CompetitorProduct(**item) for item in enriched]

        return ScrapeResponse(
            query=product_title,
            marketplace=MARKETPLACE_NAME,
            scraped_at=datetime.now(timezone.utc),
            total_results=len(products),
            products=products,
        )

    async def _fetch_ajax_payload(
        self,
        ajax_url: str,
        user_agent: str,
        headers: dict[str, str],
    ) -> dict[str, Any] | None:
        async def _load() -> dict[str, Any]:
            async with self._browser_manager.request_context(
                user_agent=user_agent,
                extra_headers=headers,
            ) as context:
                response = await context.get(ajax_url, timeout=AJAX_TIMEOUT_MS)
                if not response.ok:
                    raise PageLoadError("Daraz ajax endpoint returned a non-200 response.")
                return await response.json()

        try:
            return await retry_async(
                _load,
                retries=RETRY_ATTEMPTS,
                exceptions=(PlaywrightTimeoutError, Error, PageLoadError),
            )
        except (PlaywrightTimeoutError, Error, PageLoadError) as exc:
            logger.warning("Failed to fetch Daraz ajax payload: %s", exc)
            return None

    async def _fetch_search_html(
        self,
        url: str,
        user_agent: str,
        headers: dict[str, str],
    ) -> str:
        async def _load() -> str:
            async with self._browser_manager.page(user_agent=user_agent, extra_headers=headers) as page:
                await page.goto(url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
                await random_delay()
                return await page.content()

        try:
            return await retry_async(
                _load,
                retries=RETRY_ATTEMPTS,
                exceptions=(PlaywrightTimeoutError, Error),
            )
        except (PlaywrightTimeoutError, Error) as exc:
            logger.exception("Failed to load Daraz search page.")
            raise PageLoadError("Failed to load Daraz search results.") from exc

    def _rank_products(self, products: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not products:
            return []

        enriched: list[dict[str, Any]] = []
        for item in products:
            price = float(item.get("product_price") or 0)
            original_price = float(item.get("original_price") or 0)
            discount = int(item.get("discount_percentage") or 0)
            if discount == 0 and original_price > 0 and price > 0 and original_price > price:
                discount = int(round((original_price - price) / original_price * 100))
                item["discount_percentage"] = discount

            sold_count = parse_sold_count_number(item.get("sold_count"))
            rating = float(item.get("rating") or 0)
            rating_count = int(item.get("rating_count") or 0)
            weighted_rating = (rating * rating_count) / (rating_count + WEIGHTED_RATING_C) if rating_count >= 0 else 0
            revenue = price * sold_count
            stock_multiplier = self._stock_multiplier(item.get("stock_status"))

            enriched.append(
                {
                    "data": item,
                    "sold_count": sold_count,
                    "revenue": revenue,
                    "weighted_rating": weighted_rating,
                    "rating_count": rating_count,
                    "discount_pct": discount,
                    "stock_multiplier": stock_multiplier,
                }
            )

        normalized = self._normalize_signals(enriched)
        scored = []
        for entry in normalized:
            score = (
                entry["sold_n"] * WEIGHTS["sold"]
                + entry["revenue_n"] * WEIGHTS["revenue"]
                + entry["weighted_rating_n"] * WEIGHTS["weighted_rating"]
                + entry["rating_count_n"] * WEIGHTS["rating_count"]
                + entry["discount_n"] * WEIGHTS["discount"]
            )
            final_score = score * entry["stock_multiplier"]
            entry["data"]["ranking_score"] = round(final_score, 4)
            scored.append((final_score, entry["data"]))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in scored]

    async def _enrich_products(
        self,
        products: list[dict[str, Any]],
        user_agent: str,
        headers: dict[str, str],
    ) -> list[dict[str, Any]]:
        if not products:
            return []

        semaphore = asyncio.Semaphore(3)

        async def _fetch_details(product: dict[str, Any]) -> dict[str, Any]:
            url = product.get("daraz_product_url")
            if not url:
                return product

            async with semaphore:
                try:
                    async with self._browser_manager.page(
                        user_agent=user_agent,
                        extra_headers=headers,
                    ) as page:
                        await page.goto(url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
                        await random_delay()
                        html = await page.content()
                except (PlaywrightTimeoutError, Error) as exc:
                    logger.warning("Failed to load product detail page: %s", exc)
                    return product

            details = self._parser.parse_product_detail(html)
            return {**product, **details}

        tasks = [_fetch_details(item) for item in products]
        return await asyncio.gather(*tasks)

    def _normalize_signals(self, enriched: list[dict[str, Any]]) -> list[dict[str, Any]]:
        def min_max(values: list[float]) -> tuple[float, float]:
            return min(values), max(values)

        def normalize(value: float, min_val: float, max_val: float) -> float:
            if max_val <= min_val:
                return 0.0
            return (value - min_val) / (max_val - min_val)

        sold_values = [float(item["sold_count"]) for item in enriched]
        revenue_values = [float(item["revenue"]) for item in enriched]
        weighted_rating_values = [float(item["weighted_rating"]) for item in enriched]
        rating_count_values = [float(item["rating_count"]) for item in enriched]
        discount_values = [float(item["discount_pct"]) for item in enriched]

        sold_min, sold_max = min_max(sold_values)
        revenue_min, revenue_max = min_max(revenue_values)
        weighted_min, weighted_max = min_max(weighted_rating_values)
        rating_min, rating_max = min_max(rating_count_values)
        discount_min, discount_max = min_max(discount_values)

        normalized = []
        for item in enriched:
            normalized.append(
                {
                    "data": item["data"],
                    "stock_multiplier": item["stock_multiplier"],
                    "sold_n": normalize(item["sold_count"], sold_min, sold_max),
                    "revenue_n": normalize(item["revenue"], revenue_min, revenue_max),
                    "weighted_rating_n": normalize(item["weighted_rating"], weighted_min, weighted_max),
                    "rating_count_n": normalize(item["rating_count"], rating_min, rating_max),
                    "discount_n": normalize(item["discount_pct"], discount_min, discount_max),
                }
            )
        return normalized

    def _stock_multiplier(self, stock_status: str | None) -> float:
        status = (stock_status or "").lower()
        if "out_of_stock" in status or ("out" in status and "stock" in status):
            return 0.0
        if "low" in status:
            return 0.6
        return 1.0
