from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Final

MARKETPLACE_NAME: Final = "Daraz Bangladesh"
DARAZ_BASE_URL: Final = "https://www.daraz.com.bd"
DARAZ_SEARCH_PATH: Final = "/catalog/"

DEFAULT_MAX_RESULTS: Final = 15
WEIGHTED_RATING_C: Final = 75
WEIGHTS: Final = {
    "sold": 0.30,
    "revenue": 0.25,
    "weighted_rating": 0.20,
    "rating_count": 0.15,
    "discount": 0.10,
}
def _read_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _read_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


SIMILARITY_MODEL_NAME: Final = os.getenv("SIMILARITY_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2")
SIMILARITY_THRESHOLD: Final = _read_float_env("SIMILARITY_THRESHOLD", 0.65)
SIMILARITY_BATCH_SIZE: Final = _read_int_env("SIMILARITY_BATCH_SIZE", 32)

DEFAULT_TIMEOUT_MS: Final = 30_000
NAVIGATION_TIMEOUT_MS: Final = 45_000
AJAX_TIMEOUT_MS: Final = 45_000
RETRY_ATTEMPTS: Final = 3
RETRY_BASE_DELAY: Final = 1.0
RETRY_MAX_DELAY: Final = 8.0

RANDOM_DELAY_RANGE: Final = (0.6, 1.8)

DEFAULT_VIEWPORT: Final = {"width": 1366, "height": 768}
LOCALE: Final = "en-BD"
TIMEZONE_ID: Final = "Asia/Dhaka"

USER_AGENT_FALLBACKS: Final = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]


@dataclass(frozen=True)
class BrowserConfig:
    headless: bool = True
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    navigation_timeout_ms: int = NAVIGATION_TIMEOUT_MS
    proxy: dict[str, str] | None = None
