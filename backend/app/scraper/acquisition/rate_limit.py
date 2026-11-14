from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from playwright.async_api import Error as PlaywrightError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.scraper.constants import DarazRateConfig
from app.scraper.exceptions import PageLoadError, RateLimitError

logger = logging.getLogger(__name__)

_COOLDOWN_KEY = "bazarsync:scraper:daraz:retry-after"
_START_KEY = "bazarsync:scraper:daraz:request-spacing"
_LEASES_KEY = "bazarsync:scraper:daraz:in-flight"
# Longer than the maximum 60-second HTTPX deadline and either Playwright timeout.
_LEASE_MS = 90_000

_ACQUIRE = """
local cooldown = redis.call('PTTL', KEYS[1])
if cooldown > 0 then return {0, cooldown} end
local circuit = redis.call('PTTL', KEYS[1] .. ':open')
if circuit > 0 then return {3, circuit} end
local recovery = redis.call('EXISTS', KEYS[1] .. ':recover')
if recovery == 1 then
    local probe = redis.call('PTTL', KEYS[1] .. ':probe')
    if probe > 0 then return {3, probe} end
    if ARGV[6] ~= '1' then return {3, 1000} end
end
local spacing = redis.call('PTTL', KEYS[2])
if spacing > 0 then return {1, spacing} end

local server_time = redis.call('TIME')
local now_ms = server_time[1] * 1000 + math.floor(server_time[2] / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', now_ms)
if redis.call('ZCARD', KEYS[3]) >= tonumber(ARGV[2]) then
    return {1, 100}
end

local budget = KEYS[2] .. ':budget'
redis.call('ZREMRANGEBYSCORE', budget, '-inf', now_ms - 60000)
if redis.call('ZCARD', budget) >= tonumber(ARGV[5]) then
    local oldest = redis.call('ZRANGE', budget, 0, 0, 'WITHSCORES')
    return {4, math.max(1, oldest[2] + 60000 - now_ms)}
end
redis.call('ZADD', budget, now_ms, ARGV[1])
redis.call('PEXPIRE', budget, 60000)
if recovery == 1 and ARGV[6] == '1' then
    redis.call('PSETEX', KEYS[1] .. ':probe', ARGV[4], ARGV[1])
end
redis.call('PSETEX', KEYS[2], ARGV[3], '1')
redis.call('ZADD', KEYS[3], now_ms + tonumber(ARGV[4]), ARGV[1])
redis.call('PEXPIRE', KEYS[3], ARGV[4])
return {2, 0}
"""

_EXTEND_COOLDOWN = """
local delay_ms = tonumber(ARGV[1]) * 1000
if redis.call('PTTL', KEYS[1]) < delay_ms then
    redis.call('PSETEX', KEYS[1], delay_ms, '1')
end
"""


_RECORD_OUTCOME = """
local failures = KEYS[1] .. ':failures'
local opened = KEYS[1] .. ':open'
local recover = KEYS[1] .. ':recover'
local probe = KEYS[1] .. ':probe'
local owns_probe = redis.call('GET', probe) == ARGV[1]
if ARGV[2] == 'failure' then
    local count = redis.call('INCR', failures)
    if count == 1 then redis.call('EXPIRE', failures, ARGV[4]) end
    if owns_probe or count >= tonumber(ARGV[3]) then
        redis.call('SET', opened, '1', 'EX', ARGV[5], 'NX')
        redis.call('SET', recover, '1', 'EX', tonumber(ARGV[5]) + 180)
        redis.call('DEL', failures)
    end
elseif ARGV[2] == 'success' and owns_probe then
    redis.call('DEL', recover, failures)
end
if owns_probe then redis.call('DEL', probe) end
"""


class CircuitOpenError(PageLoadError):
    failure_code = "MARKETPLACE_CIRCUIT_OPEN"


class CoordinationError(PageLoadError):
    """A request could not be admitted safely."""


class DarazRequestCoordinator:
    def __init__(self, redis: Redis, config: DarazRateConfig | None = None) -> None:
        self._redis = redis
        self._config = config or DarazRateConfig()
        self._local_slots = asyncio.Semaphore(self._config.max_in_flight)

    @asynccontextmanager
    async def slot(self, *, track: bool = True) -> AsyncIterator[None]:
        token = uuid4().hex
        loop = asyncio.get_running_loop()
        start = loop.time()
        local_slot = False
        release_lease = False
        try:
            try:
                async with asyncio.timeout(self._config.slot_wait):
                    # Bound Redis admission calls even when a page queues many subresources.
                    await self._local_slots.acquire()
                    local_slot = True
                    while True:
                        release_lease = True  # Cancellation can occur after Redis granted the lease.
                        try:
                            state, delay_ms = await self._redis.eval(
                                _ACQUIRE, 3, _COOLDOWN_KEY, _START_KEY, _LEASES_KEY,
                                token, self._config.max_in_flight, math.ceil(self._config.min_interval * 1000), _LEASE_MS,
                                self._config.budget_per_minute, int(track),
                            )
                        except RedisError:
                            release_lease = False
                            raise
                        release_lease = state == 2
                        if release_lease:
                            break
                        if state == 3:
                            raise CircuitOpenError("Daraz temporary failure circuit is open.", math.ceil(delay_ms / 1000))
                        if state == 0:
                            raise RateLimitError("Daraz cooldown is active.", math.ceil(delay_ms / 1000))
                        if state == 4 and loop.time() - start + delay_ms / 1000 >= self._config.slot_wait:
                            raise CoordinationError("Daraz rolling request budget exhausted.", math.ceil(delay_ms / 1000))
                        await asyncio.sleep(min(delay_ms / 1000, 1.0))
            except (RedisError, TimeoutError) as exc:
                raise CoordinationError("Could not acquire a shared Daraz request slot.") from exc

            logger.debug("daraz_request_slot wait_ms=%.1f", (loop.time() - start) * 1000)
            if not track:
                yield
                return
            outcome = "neutral"
            try:
                yield
                outcome = "success"
            except (PageLoadError, PlaywrightError) as exc:
                if not isinstance(exc, (CoordinationError, RateLimitError, CircuitOpenError)):
                    outcome = "failure"
                raise
            finally:
                try:
                    await self._redis.eval(
                        _RECORD_OUTCOME, 1, _COOLDOWN_KEY, token, outcome, self._config.circuit_failures,
                        self._config.circuit_window, self._config.circuit_cooldown,
                    )
                except RedisError:
                    logger.warning("daraz_circuit_record_unavailable")
        finally:
            try:
                if release_lease:
                    await self._redis.zrem(_LEASES_KEY, token)
            except RedisError:
                logger.warning("daraz_request_slot_release_failed lease_expires_ms=%s", _LEASE_MS, exc_info=True)
            finally:
                if local_slot:
                    self._local_slots.release()

    async def defer(self, delay_seconds: int) -> None:
        try:
            await self._redis.eval(_EXTEND_COOLDOWN, 1, _COOLDOWN_KEY, delay_seconds)
        except RedisError as exc:
            raise CoordinationError("Could not store Daraz cooldown.", delay_seconds) from exc
