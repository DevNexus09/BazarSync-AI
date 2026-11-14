from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from urllib.parse import urldefrag
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.scraper.constants import DARAZ_BASE_URL
from app.scraper.schemas.scraped_product import PARSER_VERSION, DetailExtraction, ProductFields

logger = logging.getLogger(__name__)
_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end
return 0
"""
_WRITE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3])
end
"""
_MAX_ENTRY_BYTES = 64 * 1024


class StableMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observed_at: datetime
    description: str
    brand: str | None = None
    category: str | None = None
    image_url: str | None = None
    specifications: dict[str, str] = Field(default_factory=dict)


class DarazMetadataCache:
    def __init__(self, redis: Redis, seller_id: UUID, ttl: int) -> None:
        self.redis = redis
        self.seller_id = seller_id
        self.ttl = ttl

    def _key(self, url: str) -> str:
        # Preserve the full query because it can select a specific listing variant.
        digest = hashlib.sha256(urldefrag(url).url.encode()).hexdigest()
        return f"bazarsync:scraper:metadata:{DARAZ_BASE_URL}:{PARSER_VERSION}:{self.seller_id}:{{{digest}}}"

    async def _read(self, key: str) -> DetailExtraction | None:
        raw = await self.redis.get(key)
        if not raw or len(raw) > _MAX_ENTRY_BYTES:
            return None
        try:
            entry = StableMetadata.model_validate_json(raw)
            fields = ProductFields.model_validate(entry.model_dump(exclude={"observed_at"}))
        except (ValidationError, ValueError):
            logger.debug("daraz_metadata_cache_invalid")
            return None
        if entry.observed_at.tzinfo is None:
            return None
        age = (datetime.now(timezone.utc) - entry.observed_at).total_seconds()
        if not math.isfinite(age) or not 0 <= age < self.ttl:
            return None
        return DetailExtraction(
            fields=fields, method=None, observed_at=entry.observed_at,
            price_observed_at=None, metadata_cached=True,
        )

    async def fetch(
        self, url: str, live: Callable[[str], Awaitable[DetailExtraction | None]],
    ) -> DetailExtraction | None:
        key = self._key(url)
        lock = key + ":lock"
        token = uuid4().hex
        try:
            if cached := await self._read(key):
                return cached
            acquired = await self.redis.set(lock, token, nx=True, ex=180)
            if not acquired:
                for _ in range(4):
                    await asyncio.sleep(0.1)
                    if cached := await self._read(key):
                        return cached
                # Another run owns the fetch. Fresh search fields remain usable.
                logger.debug("daraz_metadata_cache_fetch_in_progress")
                return None
        except RedisError:
            logger.debug("daraz_metadata_cache_unavailable")
            return await live(url)

        try:
            try:
                if cached := await self._read(key):
                    return cached
            except RedisError:
                logger.debug("daraz_metadata_cache_unavailable")
            result = await live(url)
            if result and result.fields.description and (result.fields.specifications or result.fields.brand):
                stable = StableMetadata.model_validate({
                    **result.fields.model_dump(include={"description", "brand", "category", "image_url", "specifications"}),
                    "observed_at": result.observed_at or datetime.now(timezone.utc),
                })
                value = stable.model_dump_json()
                if len(value.encode()) <= _MAX_ENTRY_BYTES:
                    try:
                        await self.redis.eval(_WRITE, 2, lock, key, token, value, self.ttl)
                    except RedisError:
                        logger.debug("daraz_metadata_cache_write_unavailable")
            return result
        finally:
            try:
                await self.redis.eval(_RELEASE, 1, lock, token)
            except RedisError:
                logger.debug("daraz_metadata_cache_release_unavailable")
