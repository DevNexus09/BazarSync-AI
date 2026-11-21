from __future__ import annotations

from collections import defaultdict
import logging
import threading
import time
from uuid import UUID

from app.core.config import settings

try:
    import redis
except ImportError:  # pragma: no cover - dependency is present in normal deployments
    redis = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)
WINDOW_SECONDS = 60


class CopilotRateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("Copilot rate limit reached.")
        self.retry_after_seconds = retry_after_seconds


class CopilotAskRateLimiter:
    """Per-seller fixed-window limit on Copilot questions.

    Redis keeps the count across workers; if Redis is unavailable the limit is applied
    per process instead of being dropped. A limit of 0 disables it.
    """

    def __init__(self, *, limit_per_minute: int | None = None, redis_client=None, clock=time.time) -> None:
        self._limit = settings.copilot_ask_rate_limit_per_minute if limit_per_minute is None else limit_per_minute
        self._redis = redis_client
        self._clock = clock
        self._local: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def check(self, seller_id: UUID) -> None:
        if self._limit <= 0:
            return
        now = self._clock()
        window = int(now // WINDOW_SECONDS)
        retry_after = max(1, int((window + 1) * WINDOW_SECONDS - now))
        key = f"copilot:ask:{seller_id}:{window}"
        count = self._redis_count(key)
        if count is None:
            with self._lock:
                for stale in [item for item in self._local if not item.endswith(f":{window}")]:
                    del self._local[stale]
                self._local[key] += 1
                count = self._local[key]
        if count > self._limit:
            raise CopilotRateLimitExceeded(retry_after)

    def _redis_count(self, key: str) -> int | None:
        client = self._get_redis()
        if client is None:
            return None
        try:
            pipeline = client.pipeline()
            pipeline.incr(key)
            pipeline.expire(key, WINDOW_SECONDS * 2)
            count, _ = pipeline.execute()
            return int(count)
        except Exception:
            logger.warning("copilot_rate_limit_fallback code=REDIS_UNAVAILABLE")
            return None

    def _get_redis(self):
        if self._redis is not None:
            return self._redis
        if redis is None or not settings.redis_broker_url:
            return None
        try:
            self._redis = redis.Redis.from_url(settings.redis_broker_url, socket_connect_timeout=1, socket_timeout=1, decode_responses=True)
        except Exception:
            return None
        return self._redis


copilot_ask_rate_limiter = CopilotAskRateLimiter()
