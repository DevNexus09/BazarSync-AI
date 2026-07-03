from __future__ import annotations

import os
from pydantic import BaseModel, Field
from dotenv import load_dotenv

DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "https://bazar-sync-ai.vercel.app",
]


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
    bootstrap_db_on_startup: bool = False
    scraper_schedule_enabled: bool = False
    supabase_url: str | None = None
    supabase_key: str | None = None
    redis_broker_url: str | None = None
    socketio_mount_path: str = "/ws"
    socketio_path: str = "socket.io"
    socketio_ping_interval: int = 20
    socketio_ping_timeout: int = 25
    socketio_max_http_buffer_size: int = 1_000_000
    socketio_session_ttl_seconds: int = 300
    socketio_heartbeat_interval: int = 15
    socketio_heartbeat_timeout: int = 60
    competitor_event_min_price_change_absolute: float = 1.0
    competitor_event_min_price_change_percent: float = 1.0
    competitor_removal_consecutive_run_threshold: int = 2
    competitor_ranking_price_weight: float = 35.0
    competitor_ranking_rating_weight: float = 30.0
    competitor_ranking_review_weight: float = 20.0
    competitor_ranking_availability_weight: float = 15.0
    competitor_ranking_formula_version: str = "v1"
    market_opportunity_trigger_impact_weight: float = 30.0
    market_opportunity_competitor_strength_weight: float = 25.0
    market_opportunity_stock_readiness_weight: float = 20.0
    market_opportunity_price_readiness_weight: float = 15.0
    market_opportunity_data_confidence_weight: float = 10.0
    market_opportunity_high_threshold: float = 75.0
    market_opportunity_medium_threshold: float = 45.0
    market_opportunity_window_days: int = 14
    market_opportunity_formula_version: str = "v1"
    phase5_dashboard_summary_window_hours: int = 24
    sales_velocity_default_window_days: int = 30
    sales_velocity_calculation_version: str = "v1"
    stockout_prediction_calculation_version: str = "v1"
    stockout_prediction_use_snapshot_incoming: bool = False
    reorder_default_supplier_lead_time_days: int = 8
    reorder_default_safety_buffer_days: int = 3
    reorder_default_review_period_days: int = 7
    reorder_minimum_velocity_confidence: float = 40.0
    reorder_maximum_recommendation_horizon_days: int = 14
    reorder_calculation_version: str = "v1"
    inventory_risk_calculation_version: str = "v1"
    inventory_risk_significant_coverage_gap_days: float = 1.0
    inventory_risk_medium_review_horizon_days: int = 7
    inventory_risk_stale_inventory_days: int = 3
    telegram_inventory_alert_cooldown_hours: int = 24
    telegram_inventory_alert_material_days_drop: float = 2.0
    telegram_inventory_alert_max_attempts: int = 5
    telegram_inventory_alert_initial_backoff_seconds: int = 60
    telegram_inventory_alert_max_backoff_seconds: int = 3600
    inventory_intelligence_schedule_enabled: bool = False
    inventory_intelligence_daily_hour_utc: int = 1
    inventory_intelligence_daily_minute_utc: int = 15
    pricing_analytics_max_competitor_data_age_hours: int = 24
    pricing_analytics_max_inventory_data_age_hours: int = 48
    pricing_analytics_max_velocity_data_age_hours: int = 48
    pricing_analytics_demand_velocity_weight: float = 45.0
    pricing_analytics_demand_recent_sales_weight: float = 25.0
    pricing_analytics_demand_competitor_availability_weight: float = 15.0
    pricing_analytics_demand_product_maturity_weight: float = 15.0
    pricing_analytics_demand_velocity_reference_units_per_day: float = 10.0
    pricing_analytics_demand_recent_sales_reference_units: int = 100
    pricing_analytics_formula_version: str = "v1"
    demand_response_min_observations: int = 6
    demand_response_min_price_variation_rate: float = 0.05
    demand_response_min_coverage_days: int = 14
    demand_response_max_data_age_days: int = 45
    demand_response_zero_unit_adjustment: float = 1.0
    demand_response_min_elasticity: float = -5.0
    demand_response_max_elasticity: float = -0.1
    demand_response_conservative_elasticity_prior: float = -0.8
    demand_response_allow_heuristic_fallback: bool = True
    demand_response_max_forecast_multiplier: float = 3.0
    demand_response_formula_version: str = "v1"
    dynamic_pricing_formula_version: str = "v1"
    dynamic_pricing_min_improvement_rate: float = 0.02
    dynamic_pricing_min_actionable_change_rate: float = 0.01
    dynamic_pricing_max_change_rate: float = 0.15
    dynamic_pricing_expiration_hours: int = 72

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv()
        env = os.getenv("APP_ENV", "development")
        bootstrap_default = env == "development"
        scraper_schedule_default = env != "development"
        data = {
            "app_name": os.getenv("APP_NAME", "BazarSync AI"),
            "env": env,
            "api_v1_prefix": os.getenv("API_V1_PREFIX", "/api/v1"),
            "cors_origins": _split_csv(
                os.getenv("CORS_ORIGINS", ",".join(DEFAULT_CORS_ORIGINS))
            ),
            "database_url": _require_env("DATABASE_URL"),
            "jwt_secret_key": _require_env("JWT_SECRET_KEY"),
            "jwt_algorithm": os.getenv("JWT_ALGORITHM", "HS256"),
            "access_token_expire_minutes": int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")),
            "bootstrap_db_on_startup": _parse_bool(
                os.getenv("DB_BOOTSTRAP_ON_STARTUP"),
                default=bootstrap_default,
            ),
            "scraper_schedule_enabled": _parse_bool(
                os.getenv("SCRAPER_SCHEDULE_ENABLED"),
                default=scraper_schedule_default,
            ),
            "supabase_url": os.getenv("SUPABASE_URL"),
            "supabase_key": os.getenv("SUPABASE_KEY"),
            "redis_broker_url": os.getenv("REDIS_BROKER_URL") or os.getenv("REDIS_URL"),
            "socketio_mount_path": os.getenv("SOCKETIO_MOUNT_PATH", "/ws"),
            "socketio_path": os.getenv("SOCKETIO_PATH", "socket.io"),
            "socketio_ping_interval": int(os.getenv("SOCKETIO_PING_INTERVAL", "20")),
            "socketio_ping_timeout": int(os.getenv("SOCKETIO_PING_TIMEOUT", "25")),
            "socketio_max_http_buffer_size": int(
                os.getenv("SOCKETIO_MAX_HTTP_BUFFER_SIZE", "1000000")
            ),
            "socketio_session_ttl_seconds": int(
                os.getenv("SOCKETIO_SESSION_TTL_SECONDS", "300")
            ),
            "socketio_heartbeat_interval": int(
                os.getenv("SOCKETIO_HEARTBEAT_INTERVAL", "15")
            ),
            "socketio_heartbeat_timeout": int(
                os.getenv("SOCKETIO_HEARTBEAT_TIMEOUT", "60")
            ),
            "competitor_event_min_price_change_absolute": float(
                os.getenv("COMPETITOR_EVENT_MIN_PRICE_CHANGE_ABSOLUTE", "1.0")
            ),
            "competitor_event_min_price_change_percent": float(
                os.getenv("COMPETITOR_EVENT_MIN_PRICE_CHANGE_PERCENT", "1.0")
            ),
            "competitor_removal_consecutive_run_threshold": int(
                os.getenv("COMPETITOR_REMOVAL_CONSECUTIVE_RUN_THRESHOLD", "2")
            ),
            "competitor_ranking_price_weight": float(
                os.getenv("COMPETITOR_RANKING_PRICE_WEIGHT", "35.0")
            ),
            "competitor_ranking_rating_weight": float(
                os.getenv("COMPETITOR_RANKING_RATING_WEIGHT", "30.0")
            ),
            "competitor_ranking_review_weight": float(
                os.getenv("COMPETITOR_RANKING_REVIEW_WEIGHT", "20.0")
            ),
            "competitor_ranking_availability_weight": float(
                os.getenv("COMPETITOR_RANKING_AVAILABILITY_WEIGHT", "15.0")
            ),
            "competitor_ranking_formula_version": os.getenv(
                "COMPETITOR_RANKING_FORMULA_VERSION", "v1"
            ),
            "market_opportunity_trigger_impact_weight": float(os.getenv("MARKET_OPPORTUNITY_TRIGGER_IMPACT_WEIGHT", "30.0")),
            "market_opportunity_competitor_strength_weight": float(os.getenv("MARKET_OPPORTUNITY_COMPETITOR_STRENGTH_WEIGHT", "25.0")),
            "market_opportunity_stock_readiness_weight": float(os.getenv("MARKET_OPPORTUNITY_STOCK_READINESS_WEIGHT", "20.0")),
            "market_opportunity_price_readiness_weight": float(os.getenv("MARKET_OPPORTUNITY_PRICE_READINESS_WEIGHT", "15.0")),
            "market_opportunity_data_confidence_weight": float(os.getenv("MARKET_OPPORTUNITY_DATA_CONFIDENCE_WEIGHT", "10.0")),
            "market_opportunity_high_threshold": float(os.getenv("MARKET_OPPORTUNITY_HIGH_THRESHOLD", "75.0")),
            "market_opportunity_medium_threshold": float(os.getenv("MARKET_OPPORTUNITY_MEDIUM_THRESHOLD", "45.0")),
            "market_opportunity_window_days": int(os.getenv("MARKET_OPPORTUNITY_WINDOW_DAYS", "14")),
            "market_opportunity_formula_version": os.getenv("MARKET_OPPORTUNITY_FORMULA_VERSION", "v1"),
            "phase5_dashboard_summary_window_hours": int(os.getenv("PHASE5_DASHBOARD_SUMMARY_WINDOW_HOURS", "24")),
            "sales_velocity_default_window_days": int(os.getenv("SALES_VELOCITY_DEFAULT_WINDOW_DAYS", "30")),
            "sales_velocity_calculation_version": os.getenv("SALES_VELOCITY_CALCULATION_VERSION", "v1"),
            "stockout_prediction_calculation_version": os.getenv("STOCKOUT_PREDICTION_CALCULATION_VERSION", "v1"),
            "stockout_prediction_use_snapshot_incoming": _parse_bool(
                os.getenv("STOCKOUT_PREDICTION_USE_SNAPSHOT_INCOMING"),
                default=False,
            ),
            "reorder_default_supplier_lead_time_days": int(os.getenv("REORDER_DEFAULT_SUPPLIER_LEAD_TIME_DAYS", "8")),
            "reorder_default_safety_buffer_days": int(os.getenv("REORDER_DEFAULT_SAFETY_BUFFER_DAYS", "3")),
            "reorder_default_review_period_days": int(os.getenv("REORDER_DEFAULT_REVIEW_PERIOD_DAYS", "7")),
            "reorder_minimum_velocity_confidence": float(os.getenv("REORDER_MINIMUM_VELOCITY_CONFIDENCE", "40.0")),
            "reorder_maximum_recommendation_horizon_days": int(os.getenv("REORDER_MAXIMUM_RECOMMENDATION_HORIZON_DAYS", "14")),
            "reorder_calculation_version": os.getenv("REORDER_CALCULATION_VERSION", "v1"),
            "inventory_risk_calculation_version": os.getenv("INVENTORY_RISK_CALCULATION_VERSION", "v1"),
            "inventory_risk_significant_coverage_gap_days": float(os.getenv("INVENTORY_RISK_SIGNIFICANT_COVERAGE_GAP_DAYS", "1.0")),
            "inventory_risk_medium_review_horizon_days": int(os.getenv("INVENTORY_RISK_MEDIUM_REVIEW_HORIZON_DAYS", "7")),
            "inventory_risk_stale_inventory_days": int(os.getenv("INVENTORY_RISK_STALE_INVENTORY_DAYS", "3")),
            "telegram_inventory_alert_cooldown_hours": int(os.getenv("TELEGRAM_INVENTORY_ALERT_COOLDOWN_HOURS", "24")),
            "telegram_inventory_alert_material_days_drop": float(os.getenv("TELEGRAM_INVENTORY_ALERT_MATERIAL_DAYS_DROP", "2.0")),
            "telegram_inventory_alert_max_attempts": int(os.getenv("TELEGRAM_INVENTORY_ALERT_MAX_ATTEMPTS", "5")),
            "telegram_inventory_alert_initial_backoff_seconds": int(os.getenv("TELEGRAM_INVENTORY_ALERT_INITIAL_BACKOFF_SECONDS", "60")),
            "telegram_inventory_alert_max_backoff_seconds": int(os.getenv("TELEGRAM_INVENTORY_ALERT_MAX_BACKOFF_SECONDS", "3600")),
            "inventory_intelligence_schedule_enabled": _parse_bool(
                os.getenv("INVENTORY_INTELLIGENCE_SCHEDULE_ENABLED"),
                default=scraper_schedule_default,
            ),
            "inventory_intelligence_daily_hour_utc": int(os.getenv("INVENTORY_INTELLIGENCE_DAILY_HOUR_UTC", "1")),
            "inventory_intelligence_daily_minute_utc": int(os.getenv("INVENTORY_INTELLIGENCE_DAILY_MINUTE_UTC", "15")),
            "pricing_analytics_max_competitor_data_age_hours": int(os.getenv("PRICING_ANALYTICS_MAX_COMPETITOR_DATA_AGE_HOURS", "24")),
            "pricing_analytics_max_inventory_data_age_hours": int(os.getenv("PRICING_ANALYTICS_MAX_INVENTORY_DATA_AGE_HOURS", "48")),
            "pricing_analytics_max_velocity_data_age_hours": int(os.getenv("PRICING_ANALYTICS_MAX_VELOCITY_DATA_AGE_HOURS", "48")),
            "pricing_analytics_demand_velocity_weight": float(os.getenv("PRICING_ANALYTICS_DEMAND_VELOCITY_WEIGHT", "45.0")),
            "pricing_analytics_demand_recent_sales_weight": float(os.getenv("PRICING_ANALYTICS_DEMAND_RECENT_SALES_WEIGHT", "25.0")),
            "pricing_analytics_demand_competitor_availability_weight": float(os.getenv("PRICING_ANALYTICS_DEMAND_COMPETITOR_AVAILABILITY_WEIGHT", "15.0")),
            "pricing_analytics_demand_product_maturity_weight": float(os.getenv("PRICING_ANALYTICS_DEMAND_PRODUCT_MATURITY_WEIGHT", "15.0")),
            "pricing_analytics_demand_velocity_reference_units_per_day": float(os.getenv("PRICING_ANALYTICS_DEMAND_VELOCITY_REFERENCE_UNITS_PER_DAY", "10.0")),
            "pricing_analytics_demand_recent_sales_reference_units": int(os.getenv("PRICING_ANALYTICS_DEMAND_RECENT_SALES_REFERENCE_UNITS", "100")),
            "pricing_analytics_formula_version": os.getenv("PRICING_ANALYTICS_FORMULA_VERSION", "v1"),
            "demand_response_min_observations": int(os.getenv("DEMAND_RESPONSE_MIN_OBSERVATIONS", "6")),
            "demand_response_min_price_variation_rate": float(os.getenv("DEMAND_RESPONSE_MIN_PRICE_VARIATION_RATE", "0.05")),
            "demand_response_min_coverage_days": int(os.getenv("DEMAND_RESPONSE_MIN_COVERAGE_DAYS", "14")),
            "demand_response_max_data_age_days": int(os.getenv("DEMAND_RESPONSE_MAX_DATA_AGE_DAYS", "45")),
            "demand_response_zero_unit_adjustment": float(os.getenv("DEMAND_RESPONSE_ZERO_UNIT_ADJUSTMENT", "1.0")),
            "demand_response_min_elasticity": float(os.getenv("DEMAND_RESPONSE_MIN_ELASTICITY", "-5.0")),
            "demand_response_max_elasticity": float(os.getenv("DEMAND_RESPONSE_MAX_ELASTICITY", "-0.1")),
            "demand_response_conservative_elasticity_prior": float(os.getenv("DEMAND_RESPONSE_CONSERVATIVE_ELASTICITY_PRIOR", "-0.8")),
            "demand_response_allow_heuristic_fallback": _parse_bool(
                os.getenv("DEMAND_RESPONSE_ALLOW_HEURISTIC_FALLBACK"),
                default=True,
            ),
            "demand_response_max_forecast_multiplier": float(os.getenv("DEMAND_RESPONSE_MAX_FORECAST_MULTIPLIER", "3.0")),
            "demand_response_formula_version": os.getenv("DEMAND_RESPONSE_FORMULA_VERSION", "v1"),
            "dynamic_pricing_formula_version": os.getenv("DYNAMIC_PRICING_FORMULA_VERSION", "v1"),
            "dynamic_pricing_min_improvement_rate": float(os.getenv("DYNAMIC_PRICING_MIN_IMPROVEMENT_RATE", "0.02")),
            "dynamic_pricing_min_actionable_change_rate": float(os.getenv("DYNAMIC_PRICING_MIN_ACTIONABLE_CHANGE_RATE", "0.01")),
            "dynamic_pricing_max_change_rate": float(os.getenv("DYNAMIC_PRICING_MAX_CHANGE_RATE", "0.15")),
            "dynamic_pricing_expiration_hours": int(os.getenv("DYNAMIC_PRICING_EXPIRATION_HOURS", "72")),
        }
        return cls.model_validate(data)


settings = Settings.load()
