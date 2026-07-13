from __future__ import annotations

from collections import defaultdict, deque
import logging
import threading
import time

from app.core.config import settings
from app.core.security import hash_security_identifier

try:
    import redis
except ImportError:  # pragma: no cover - dependency is present in normal deployments
    redis = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


class PasswordResetRateLimitExceeded(Exception):
    pass


class PasswordResetRateLimiter:
    def __init__(self, redis_client=None) -> None:
        self._redis = redis_client
        self._local_events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, email: str, request_ip: str) -> None:
        self._consume(
            f"email:{hash_security_identifier(email)}",
            settings.password_reset_max_requests_per_hour,
            3600,
        )
        self._consume(
            f"ip:{hash_security_identifier(request_ip or 'unknown')}",
            settings.password_reset_max_requests_per_ip,
            3600,
        )

    def _consume(self, key: str, limit: int, window_seconds: int) -> None:
        if limit < 1:
            raise PasswordResetRateLimitExceeded

        redis_client = self._get_redis()
        if redis_client is not None:
            try:
                pipeline = redis_client.pipeline()
                pipeline.incr(key)
                pipeline.expire(key, window_seconds)
                count, _ = pipeline.execute()
                if int(count) > limit:
                    raise PasswordResetRateLimitExceeded
                return
            except PasswordResetRateLimitExceeded:
                raise
            except Exception:
                logger.warning(
                    "password_reset_rate_limit_fallback code=REDIS_UNAVAILABLE"
                )

        now = time.monotonic()
        with self._lock:
            events = self._local_events[key]
            cutoff = now - window_seconds
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                raise PasswordResetRateLimitExceeded
            events.append(now)

    def _get_redis(self):
        if self._redis is not None:
            return self._redis
        if redis is None or not settings.redis_broker_url:
            return None
        try:
            self._redis = redis.Redis.from_url(
                settings.redis_broker_url,
                socket_connect_timeout=1,
                socket_timeout=1,
                decode_responses=True,
            )
            return self._redis
        except Exception:
            return None

    def clear_local_state(self) -> None:
        with self._lock:
            self._local_events.clear()


password_reset_rate_limiter = PasswordResetRateLimiter()
