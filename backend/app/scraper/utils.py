from __future__ import annotations

import asyncio
import logging
import random
import re
from decimal import Decimal
from typing import TypeVar
from urllib.parse import quote_plus, unquote, urljoin, urlsplit

from app.scraper.schemas.scraped_product import StockStatus
from app.scraper.constants import DARAZ_BASE_URL, DARAZ_SEARCH_PATH, RANDOM_DELAY_RANGE

logger = logging.getLogger(__name__)
T = TypeVar("T")

_AMOUNT = r"(?:\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})+,\d{3}|\d+)(?:\.\d{1,2})?"
_PRICE = re.compile(rf"(?:BDT\s*|৳\s*|Tk\.?\s*)?({_AMOUNT})(?:\s*BDT)?", re.I)
_COUNT = re.compile(rf"({_AMOUNT})\s*([km]?)\+?", re.I)


def first_present(primary: T | None, fallback: T | None) -> T | None:
    return primary if primary is not None and primary != "" else fallback


def sanitize_query(query: str) -> str:
    return normalize_text(query)


def build_search_url(query: str, *, ajax: bool = False) -> str:
    encoded = quote_plus(query)
    suffix = "&ajax=true" if ajax else ""
    return f"{DARAZ_BASE_URL}{DARAZ_SEARCH_PATH}?q={encoded}{suffix}"


def to_absolute_url(url: str) -> str:
    try:
        return urljoin(DARAZ_BASE_URL, url) if url else ""
    except ValueError:
        return ""


def is_daraz_product_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        path = unquote(parsed.path)
        return (
            parsed.scheme == "https"
            and parsed.netloc == urlsplit(DARAZ_BASE_URL).netloc
            and path.startswith("/products/")
            and "\\" not in path
            and not {".", ".."}.intersection(path.split("/"))
        )
    except ValueError:
        return False


def normalize_text(text: str | None) -> str:
    return re.sub(r"\s+", " ", text).strip() if isinstance(text, str) else ""


def _numeric_text(value: str | None) -> str:
    text = normalize_text(value)
    if text.lower() in {"n/a", "unavailable", "-", "—"}:
        logger.debug("Daraz marked a numeric field unavailable.")
        return ""
    return text


def parse_price(value: str | None) -> Decimal | None:
    text = _numeric_text(value)
    if not text:
        return None
    match = _PRICE.fullmatch(text)
    if match and (price := Decimal(match[1].replace(",", ""))) <= Decimal("9999999999.99"):
        return price
    logger.debug("Invalid Daraz price.")
    return None


def parse_compact_number(value: str | None) -> int | None:
    text = _numeric_text(value).lower()
    if not text:
        return None
    match = _COUNT.fullmatch(text.removeprefix("(").removesuffix(")").strip())
    if match and ("." not in match[1] or match[2]):
        multiplier = {"": 1, "k": 1_000, "m": 1_000_000}[match[2]]
        digits = match[1].replace(",", "")
        if len(digits) <= 14:
            number = int(Decimal(digits) * multiplier)
            if number <= 2_147_483_647:
                return number
    logger.debug("Invalid Daraz count.")
    return None


def parse_rating(value: str | None) -> float | None:
    text = _numeric_text(value)
    if not text:
        return None
    if re.fullmatch(r"\d(?:\.\d+)?", text) and (rating := float(text)) <= 5:
        return rating
    logger.debug("Invalid Daraz rating.")
    return None


def parse_discount_percentage(value: str | None) -> int | None:
    text = _numeric_text(value)
    if not text:
        return None
    # Daraz uses a leading minus sign to denote a discount.
    if re.fullmatch(r"-?\d{1,3}\s*%?", text):
        discount = int(text.rstrip("%").strip().removeprefix("-"))
        if discount <= 100:
            return discount
    logger.debug("Invalid Daraz discount.")
    return None


def normalize_sold_count(value: str | None) -> str | None:
    text = normalize_text(value).lower().removesuffix("sold").strip()
    return text if parse_compact_number(text) is not None else None


def build_headers(user_agent: str) -> dict[str, str]:
    return {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,bn-BD;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": user_agent,
    }


async def random_delay() -> None:
    await asyncio.sleep(random.uniform(*RANDOM_DELAY_RANGE))


def normalize_stock_status(value: str | None) -> StockStatus:
    text = re.sub(r"[\s_-]+", " ", normalize_text(value)).lower()
    if text in {"out of stock", "sold out", "unavailable", "currently unavailable", "not available", "not in stock"}:
        return "OUT_OF_STOCK"
    if text in {"in stock", "available", "low stock", "limited stock", "in stock online"}:
        return "IN_STOCK"
    if re.fullmatch(r"only [1-9]\d* left(?: in stock)?", text):
        return "IN_STOCK"
    return "UNKNOWN"
