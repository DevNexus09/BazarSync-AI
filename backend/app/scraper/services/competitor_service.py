from __future__ import annotations

from app.scraper.browser import BrowserManager
from app.scraper.daraz_scraper import DarazScraper
from app.scraper.schemas import ScrapeResponse


async def scrape_daraz_competitors(
    *,
    product_title: str,
) -> ScrapeResponse:
    browser_manager = BrowserManager()
    await browser_manager._ensure_browser()
    try:
        scraper = DarazScraper(browser_manager)
        return await scraper.scrape(product_title=product_title)
    finally:
        await browser_manager.close()
