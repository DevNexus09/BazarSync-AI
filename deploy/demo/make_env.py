"""Write the demo server's settings file from backend/.env; secrets are never printed.

Run from backend/:
    PYTHONPATH=. venv/bin/python ../deploy/demo/make_env.py --domain bazarsync-demo.eastus.cloudapp.azure.com [--frontend URL] [--dry-run]
Writes ~/bazarsync-demo.env (mode 600). Copy it to the server as deploy/demo/.env.
"""

from __future__ import annotations

import argparse
from getpass import getpass
import os
from pathlib import Path
import secrets

from dotenv import dotenv_values

COPY_PREFIXES = ("RAG_", "COPILOT_")
COPY_KEYS = {
    "GROQ_MODEL",
    "GROQ_COPILOT_MODEL",
    "GROQ_TIMEOUT_SECONDS",
    "JWT_ALGORITHM",
    "SIMILARITY_THRESHOLD",
    "RECOMMENDATION_CONFIDENCE_THRESHOLD",
    "PRICE_GAP_ALERT_PERCENT",
    "LOW_STOCK_DAYS_THRESHOLD",
    "SALES_VELOCITY_CALCULATION_VERSION",
}
SECRET_KEYS = ("GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY")
OVERRIDES = {
    "APP_ENV": "development",  # console email; the demo has no SMTP
    "DEMO_MODE_ENABLED": "true",
    "REDIS_URL": "redis://redis:6379/0",
    "RAG_EMBEDDING_DEVICE": "cpu",  # the server has no Apple mps device
    "SIMILARITY_DEVICE": "cpu",
    "SCRAPER_SCHEDULE_ENABLED": "false",
    "INVENTORY_INTELLIGENCE_SCHEDULE_ENABLED": "false",
    "DEAD_STOCK_WORKFLOW_SCHEDULE_ENABLED": "false",
    "RAG_MEMORY_SCHEDULE_ENABLED": "false",
}
OUTPUT = Path.home() / "bazarsync-demo.env"


def build_settings(env: dict[str, str | None], domain: str, frontend: str | None) -> dict[str, str]:
    settings = {
        key: value
        for key, value in env.items()
        if value and (key in COPY_KEYS or key.startswith(COPY_PREFIXES) or key in SECRET_KEYS)
    }
    settings.update(OVERRIDES)
    settings["DEMO_DOMAIN"] = domain
    if frontend:
        settings["CORS_ORIGINS"] = settings["FRONTEND_URL"] = frontend.rstrip("/")
    return settings


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_argument("--domain", required=True, help="Server DNS name, e.g. bazarsync-demo.eastus.cloudapp.azure.com")
    cli.add_argument("--frontend", help="Vercel URL, e.g. https://bazarsync.vercel.app")
    cli.add_argument("--dry-run", action="store_true", help="List the settings without writing.")
    args = cli.parse_args()

    settings = build_settings(dotenv_values(".env"), args.domain.strip(), args.frontend)
    if args.dry_run:
        for key in sorted(settings):
            print(f"{key}=" + ("<hidden>" if key in SECRET_KEYS else settings[key]))
        print("DATABASE_URL=<asked when writing>\nJWT_SECRET_KEY=<generated when writing>")
        return 0

    database_url = getpass("Neon DATABASE_URL (hidden): ").strip()
    if not database_url.startswith("postgresql://") or "?" in database_url:
        print("Use the Neon URL starting with postgresql:// and cut everything from '?' onwards.")
        return 2
    settings["DATABASE_URL"] = database_url
    settings["JWT_SECRET_KEY"] = secrets.token_urlsafe(48)

    unsafe = sorted(key for key, value in settings.items() if "$" in value or "\n" in value)
    if unsafe:
        print("These values contain '$' or a line break, which Docker would misread: " + ", ".join(unsafe))
        return 2

    OUTPUT.write_text("".join(f"{key}={value}\n" for key, value in sorted(settings.items())))
    os.chmod(OUTPUT, 0o600)
    print(f"Wrote {len(settings)} settings to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
