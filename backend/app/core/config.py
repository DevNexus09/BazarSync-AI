from __future__ import annotations

import os
from pydantic import BaseModel, Field
from dotenv import load_dotenv


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _require_env(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


class Settings(BaseModel):
    # Centralized settings keep environment concerns out of business logic.
    app_name: str = "BazarSync AI"
    env: str = "development"
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=list)
    database_url: str
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    supabase_url: str | None = None
    supabase_key: str | None = None
    redis_broker_url: str | None = None

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv()
        data = {
            "app_name": os.getenv("APP_NAME", "BazarSync AI"),
            "env": os.getenv("APP_ENV", "development"),
            "api_v1_prefix": os.getenv("API_V1_PREFIX", "/api/v1"),
            "cors_origins": _split_csv(os.getenv("CORS_ORIGINS", "http://localhost:5173")),
            "database_url": _require_env("DATABASE_URL"),
            "jwt_secret_key": _require_env("JWT_SECRET_KEY"),
            "jwt_algorithm": os.getenv("JWT_ALGORITHM", "HS256"),
            "access_token_expire_minutes": int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")),
            "supabase_url": os.getenv("SUPABASE_URL"),
            "supabase_key": os.getenv("SUPABASE_KEY"),
            "redis_broker_url": os.getenv("REDIS_BROKER_URL"),
        }
        return cls.model_validate(data)


settings = Settings.load()
