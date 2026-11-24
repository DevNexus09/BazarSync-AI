#!/bin/sh
# Runs Redis, one Celery worker and the API in one container for the free demo Space.
set -e

redis-server --daemonize yes --save "" --appendonly no
export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"

alembic upgrade head

celery -A app.core.celery_app:celery_app worker --loglevel=info --concurrency=1 --max-tasks-per-child=50 &

exec uvicorn app.main:app --host 0.0.0.0 --port 7860 --proxy-headers --forwarded-allow-ips="*"
