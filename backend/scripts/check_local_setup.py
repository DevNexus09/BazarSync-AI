from __future__ import annotations

import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.celery_app import redis_url
from app.db.session import engine


def main() -> int:
    redis_ok = _check_redis(redis_url)
    database_ok = _check_database()
    print("")
    if redis_ok and database_ok:
        print("local_setup_ok")
        return 0
    print("local_setup_failed")
    print("")
    if not redis_ok:
        print("Start Redis before running Celery:")
        print("  redis-server")
        print("or:")
        print("  docker compose up -d redis")
    if not database_ok:
        print("Check DATABASE_URL in backend/.env, then run:")
        print("  python -m alembic upgrade head")
    return 1


def _check_redis(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    try:
        with socket.create_connection((host, port), timeout=2) as sock:
            sock.sendall(b"*1\r\n$4\r\nPING\r\n")
            response = sock.recv(64)
    except OSError as exc:
        print(f"redis_check_failed url={_safe_url(url)} error={exc}")
        return False
    if response.startswith(b"+PONG"):
        print(f"redis_check_ok url={_safe_url(url)}")
        return True
    print(f"redis_check_failed url={_safe_url(url)} error=unexpected_response")
    return False


def _check_database() -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        print(f"database_check_failed error={exc.__class__.__name__}")
        return False
    print("database_check_ok")
    return True


def _safe_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.password:
        netloc = parsed.netloc.replace(f":{parsed.password}@", ":***@")
        return parsed._replace(netloc=netloc).geturl()
    return url


if __name__ == "__main__":
    raise SystemExit(main())
