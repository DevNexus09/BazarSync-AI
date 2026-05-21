from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import Awaitable, Callable, Iterable, TypeVar
from urllib.parse import quote_plus, urljoin

from fake_useragent import UserAgent
from fake_useragent.errors import FakeUserAgentError

from app.scraper.constants import (
    DARAZ_BASE_URL,
    DARAZ_SEARCH_PATH,
    RANDOM_DELAY_RANGE,
    RETRY_BASE_DELAY,
    RETRY_MAX_DELAY,
    USER_AGENT_FALLBACKS,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


def sanitize_query(query: str) -> str:
    cleaned = re.sub(r"\s+", " ", query).strip()
    return cleaned


def build_search_url(query: str, *, ajax: bool = False) -> str:
    encoded = quote_plus(query)
    suffix = "&ajax=true" if ajax else ""
    return f"{DARAZ_BASE_URL}{DARAZ_SEARCH_PATH}?q={encoded}{suffix}"


def to_absolute_url(url: str) -> str:
    if not url:
        return ""
    return urljoin(DARAZ_BASE_URL, url)


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def parse_price(value: str | None) -> float:
    if not value:
        return 0.0
    cleaned = re.sub(r"[^\d.]", "", value)
    if not cleaned:
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_int(value: str | None) -> int:
    if not value:
        return 0
    cleaned = re.sub(r"[^\d]", "", value)
    if not cleaned:
        return 0
    try:
        return int(cleaned)
    except ValueError:
        return 0


def parse_compact_number(value: str | None) -> int:
    if not value:
        return 0
    cleaned = normalize_text(value).lower()
    match = re.search(r"(\d+(?:\.\d+)?)\s*([km]?)", cleaned)
    if not match:
        return parse_int(cleaned)
    magnitude = match.group(2)
    multiplier = 1
    if magnitude == "k":
        multiplier = 1_000
    elif magnitude == "m":
        multiplier = 1_000_000
    try:
        return int(float(match.group(1)) * multiplier)
    except ValueError:
        return 0


def parse_float(value: str | None) -> float:
    if not value:
        return 0.0
    cleaned = re.sub(r"[^\d.]", "", value)
    if not cleaned:
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_discount_percentage(value: str | None) -> int:
    if not value:
        return 0
    cleaned = re.sub(r"[^\d]", "", value)
    if not cleaned:
        return 0
    try:
        return int(cleaned)
    except ValueError:
        return 0


def normalize_sold_count(value: str | None) -> str:
    if not value:
        return ""
    cleaned = normalize_text(value).lower()
    cleaned = cleaned.replace("sold", "").strip()
    return cleaned


def parse_sold_count_number(value: str | None) -> int:
    cleaned = normalize_sold_count(value)
    return parse_compact_number(cleaned)


def get_random_user_agent() -> str:
    try:
        return UserAgent().random
    except FakeUserAgentError as exc:
        logger.warning("Failed to fetch random user-agent: %s", exc)
        return random.choice(USER_AGENT_FALLBACKS)


def build_headers(user_agent: str) -> dict[str, str]:
    return {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,bn-BD;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": user_agent,
    }


async def random_delay(
    min_seconds: float | None = None,
    max_seconds: float | None = None,
) -> None:
    low, high = RANDOM_DELAY_RANGE
    wait_min = min_seconds if min_seconds is not None else low
    wait_max = max_seconds if max_seconds is not None else high
    await asyncio.sleep(random.uniform(wait_min, wait_max))


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    retries: int,
    exceptions: Iterable[type[BaseException]],
    base_delay: float = RETRY_BASE_DELAY,
    max_delay: float = RETRY_MAX_DELAY,
) -> T:
    attempt = 0
    while True:
        try:
            return await operation()
        except tuple(exceptions) as exc:
            attempt += 1
            if attempt > retries:
                raise
            backoff = min(max_delay, base_delay * (2 ** (attempt - 1)))
            jittered = backoff * random.uniform(0.8, 1.2)
            logger.warning("Retrying after error: %s (attempt %s/%s)", exc, attempt, retries)
            await asyncio.sleep(jittered)
