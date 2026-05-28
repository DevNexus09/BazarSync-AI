from __future__ import annotations

from collections.abc import AsyncGenerator
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings


def _build_async_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    return database_url


def _using_pgbouncer(database_url: str) -> bool:
    parsed = urlparse(database_url)
    hostname = (parsed.hostname or "").lower()
    if "pgbouncer" in hostname or "pooler" in hostname:
        return True
    if parsed.port == 6543:
        return True
    query = parse_qs(parsed.query)
    pgbouncer_flag = (query.get("pgbouncer") or [None])[0]
    return str(pgbouncer_flag).lower() in {"1", "true", "yes", "on"}


ASYNC_DATABASE_URL = _build_async_database_url(settings.database_url)
USE_PGBOUNCER = _using_pgbouncer(ASYNC_DATABASE_URL)
ASYNC_CONNECT_ARGS: dict[str, object] = {}
if ASYNC_DATABASE_URL.startswith("postgresql+asyncpg://"):
    # Disable prepared statement caching to avoid pgbouncer transaction-pool conflicts.
    ASYNC_CONNECT_ARGS["statement_cache_size"] = 0
    ASYNC_CONNECT_ARGS["prepared_statement_cache_size"] = 0
    if USE_PGBOUNCER:
        ASYNC_CONNECT_ARGS["prepared_statement_name_func"] = (
            lambda: f"__asyncpg_{uuid4()}__"
        )

engine_kwargs: dict[str, object] = {
    "pool_pre_ping": True,
    "connect_args": ASYNC_CONNECT_ARGS,
}
if USE_PGBOUNCER:
    engine_kwargs["poolclass"] = NullPool
else:
    engine_kwargs["pool_size"] = 5
    engine_kwargs["max_overflow"] = 10

async_engine: AsyncEngine = create_async_engine(ASYNC_DATABASE_URL, **engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
