from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

def _read_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _read_unit_env(name: str, default: float) -> float:
    value = _read_float_env(name, default)
    return value if 0 <= value <= 1 else default


def _read_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _read_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


MARKETPLACE_NAME: Final = "Daraz Bangladesh"
DARAZ_BASE_URL: Final = "https://www.daraz.com.bd"
DARAZ_SEARCH_PATH: Final = "/catalog/"

DEFAULT_MAX_RESULTS: Final = max(1, _read_int_env("SCRAPER_MAX_RESULTS", 25))
DETAILS_CONCURRENCY: Final = max(1, min(25, _read_int_env("SCRAPER_DETAIL_CONCURRENCY", 3)))
SCRAPER_METADATA_CACHE_TTL: Final = max(0, min(86400, _read_int_env("SCRAPER_METADATA_CACHE_TTL", 21600)))
SCRAPER_HTTPX_ENABLED: Final = _read_bool_env("SCRAPER_HTTPX_ENABLED", True)
WEIGHTED_RATING_C: Final = 75
WEIGHTS: Final = {
    "sold": 0.30,
    "price_weighted_popularity": 0.25,
    "weighted_rating": 0.20,
    "rating_count": 0.15,
    "discount": 0.10,
}
BASELINE_SIMILARITY_MODEL: Final = "sentence-transformers/all-MiniLM-L6-v2"
SIMILARITY_MODEL_NAME: Final = os.getenv("SIMILARITY_MODEL_NAME", BASELINE_SIMILARITY_MODEL)
SIMILARITY_DEVICE: Final = os.getenv("SIMILARITY_DEVICE", "cpu")
SIMILARITY_THRESHOLD: Final = _read_unit_env("SIMILARITY_THRESHOLD", 0.65)
SIMILARITY_BATCH_SIZE: Final = max(1, min(64, _read_int_env("SIMILARITY_BATCH_SIZE", 32)))
SIMILARITY_VERIFICATION_FLOOR: Final = _read_unit_env("SIMILARITY_VERIFICATION_FLOOR", 0.50)
SIMILARITY_POSSIBLE_THRESHOLD: Final = _read_unit_env("SIMILARITY_POSSIBLE_THRESHOLD", 0.50)
SIMILARITY_VERY_STRONG_THRESHOLD: Final = _read_unit_env("SIMILARITY_VERY_STRONG_THRESHOLD", 0.88)
SIMILARITY_MIN_TITLE_EVIDENCE: Final = _read_unit_env("SIMILARITY_MIN_TITLE_EVIDENCE", 0.55)
SIMILARITY_DIMENSIONS_TOLERANCE: Final = _read_unit_env("SIMILARITY_DIMENSIONS_TOLERANCE", 0.03)

DEFAULT_TIMEOUT_MS: Final = 30_000
NAVIGATION_TIMEOUT_MS: Final = 45_000
AJAX_TIMEOUT_MS: Final = 45_000

RANDOM_DELAY_RANGE: Final = (0.6, 1.8)

DEFAULT_VIEWPORT: Final = {"width": 1366, "height": 768}
LOCALE: Final = "en-BD"
TIMEZONE_ID: Final = "Asia/Dhaka"

SCRAPER_USER_AGENT: Final = "BazarSyncAI/1.0"


@dataclass(frozen=True)
class BrowserConfig:
    headless: bool = _read_bool_env("SCRAPER_HEADLESS", True)
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    navigation_timeout_ms: int = NAVIGATION_TIMEOUT_MS
    proxy: dict[str, str] | None = None


class HttpxConfig(BaseModel):
    model_config = ConfigDict(frozen=True, validate_default=True)

    connect_timeout: float = Field(default=_read_float_env("SCRAPER_HTTPX_CONNECT_TIMEOUT", 10), gt=0, le=60)
    read_timeout: float = Field(default=_read_float_env("SCRAPER_HTTPX_READ_TIMEOUT", 30), gt=0, le=60)
    write_timeout: float = Field(default=_read_float_env("SCRAPER_HTTPX_WRITE_TIMEOUT", 10), gt=0, le=60)
    pool_timeout: float = Field(default=_read_float_env("SCRAPER_HTTPX_POOL_TIMEOUT", 10), gt=0, le=60)
    total_timeout: float = Field(default=_read_float_env("SCRAPER_HTTPX_TOTAL_TIMEOUT", 45), gt=0, le=60)
    max_connections: int = Field(default=_read_int_env("SCRAPER_HTTPX_MAX_CONNECTIONS", 10), ge=1)
    max_keepalive_connections: int = Field(default=_read_int_env("SCRAPER_HTTPX_MAX_KEEPALIVE_CONNECTIONS", 5), ge=0)
    max_response_bytes: int = Field(default=4 * 1024 * 1024, ge=1)

    @model_validator(mode="after")
    def validate_limits(self) -> Self:
        if self.max_keepalive_connections > self.max_connections:
            raise ValueError("HTTPX keep-alive connections cannot exceed max connections.")
        return self


class DarazRateConfig(BaseModel):
    model_config = ConfigDict(frozen=True, validate_default=True)

    min_interval: float = Field(default=_read_float_env("SCRAPER_DARAZ_MIN_INTERVAL_SECONDS", 0.5), gt=0, le=60)
    max_in_flight: int = Field(default=_read_int_env("SCRAPER_DARAZ_MAX_IN_FLIGHT", 3), ge=1)
    budget_per_minute: int = Field(default=_read_int_env("SCRAPER_DARAZ_BUDGET_PER_MINUTE", 120), ge=1, le=3600)
    circuit_failures: int = Field(default=_read_int_env("SCRAPER_DARAZ_CIRCUIT_FAILURES", 5), ge=1, le=100)
    circuit_cooldown: int = Field(default=_read_int_env("SCRAPER_DARAZ_CIRCUIT_COOLDOWN_SECONDS", 120), ge=1, le=3600)
    circuit_window: int = Field(default=_read_int_env("SCRAPER_DARAZ_CIRCUIT_WINDOW_SECONDS", 60), ge=1, le=3600)
    slot_wait: float = Field(default=_read_float_env("SCRAPER_DARAZ_SLOT_WAIT_SECONDS", 20), gt=0, le=60)
