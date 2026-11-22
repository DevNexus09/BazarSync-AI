from __future__ import annotations

import os
from decimal import Decimal
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
    password_reset_enabled: bool = True
    password_reset_code_length: int = 6
    password_reset_code_ttl_minutes: int = 10
    password_reset_max_attempts: int = 5
    password_reset_resend_cooldown_seconds: int = 60
    password_reset_max_requests_per_hour: int = 5
    password_reset_max_requests_per_ip: int = 20
    password_reset_auth_ttl_minutes: int = 15
    password_reset_revoke_sessions: bool = True
    password_reset_code_secret: str = ""
    email_provider: str = "console"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_use_tls: bool = True
    smtp_timeout_seconds: int = 10
    password_reset_email_retry_attempts: int = 2
    bootstrap_db_on_startup: bool = False
    scraper_schedule_enabled: bool = False
    recommendation_jobs_enabled: bool = False
    recommendation_validation_enabled: bool = False
    recommendation_dashboard_evidence_enabled: bool = False
    recommendation_explanation_enabled: bool = False
    recommendation_explanation_groq_enabled: bool = False
    recommendation_explanation_model: str = "openai/gpt-oss-20b"
    recommendation_explanation_temperature: float = Field(default=0.1, ge=0, le=1)
    recommendation_explanation_timeout_seconds: float = Field(default=4, gt=0, le=15)
    recommendation_explanation_max_retries: int = Field(default=0, ge=0, le=2)
    historical_dataset_export_enabled: bool = False
    recommendation_action_evaluation_enabled: bool = False
    recommendation_action_min_score: Decimal = Field(default=Decimal("0.50"), ge=0, le=1)
    recommendation_action_profit_reference_bdt: Decimal = Field(default=Decimal("1000"), gt=0, allow_inf_nan=False)
    recommendation_action_max_adverse_risk: Decimal = Field(default=Decimal("0.60"), ge=0, le=1)
    recommendation_orchestration_enabled: bool = False
    recommendation_orchestration_shadow_enabled: bool = False
    recommendation_evidence_enabled: bool = False
    recommendation_business_signals_enabled: bool = False
    recommendation_inventory_max_age_hours: int = Field(default=48, gt=0, le=8760)
    recommendation_price_max_age_hours: int = Field(default=24, gt=0, le=8760)
    recommendation_stock_max_age_hours: int = Field(default=6, gt=0, le=8760)
    daraz_scraping_authorized: bool = False
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
    forecast_aware_reorder_enabled: bool = False
    reorder_target_service_level: Decimal = Field(default=Decimal("0.90"), gt=0.5, lt=1)
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
    inventory_aging_calculation_version: str = "v1"
    inventory_aging_bucket_edges_days: list[int] = Field(default_factory=lambda: [30, 45, 60, 90, 180])
    dead_stock_calculation_version: str = "v1"
    dead_stock_no_sales_threshold_days: int = 45
    dead_stock_inventory_age_threshold_days: int = 60
    dead_stock_product_age_grace_period_days: int = 30
    dead_stock_slow_velocity_units_per_day: float = 0.25
    dead_stock_strong_velocity_units_per_day: float = 1.0
    dead_stock_excess_coverage_days: int = 90
    dead_stock_age_warning_ratio: float = 0.80
    dead_stock_no_sales_warning_ratio: float = 0.80
    dead_stock_excess_coverage_warning_ratio: float = 0.80
    dead_stock_extreme_age_multiplier: float = 2.0
    dead_stock_extreme_no_sales_multiplier: float = 2.0
    dead_stock_extreme_coverage_multiplier: float = 2.0
    dead_stock_low_visibility_threshold: float = 35.0
    dead_stock_inventory_age_weight: float = 30.0
    dead_stock_no_sales_weight: float = 30.0
    dead_stock_sales_velocity_weight: float = 15.0
    dead_stock_excess_coverage_weight: float = 15.0
    dead_stock_visibility_weight: float = 10.0
    dead_stock_recovery_formula_version: str = "v1"
    evidence_driven_recovery_enabled: bool = False
    dead_stock_recovery_discount_rates: list[float] = Field(default_factory=lambda: [0.05, 0.10, 0.15, 0.20])
    dead_stock_recovery_bundle_min_quantity: int = 5
    dead_stock_recovery_flash_sale_min_quantity: int = 10
    dead_stock_recovery_flash_sale_duration_days: int = 3
    dead_stock_recovery_expiration_days: int = 7
    dead_stock_capital_recovery_formula_version: str = "v1"
    dead_stock_capital_recovery_currency: str = "BDT"
    dead_stock_capital_recovery_default_duration_days: int = 14
    dead_stock_capital_recovery_heuristic_low_sell_through_rate: float = 0.25
    dead_stock_capital_recovery_heuristic_central_sell_through_rate: float = 0.40
    dead_stock_capital_recovery_heuristic_high_sell_through_rate: float = 0.55
    dead_stock_workflow_schedule_enabled: bool = False
    dead_stock_workflow_daily_hour_utc: int = 2
    dead_stock_workflow_daily_minute_utc: int = 15
    dead_stock_workflow_debounce_seconds: int = 300
    dead_stock_alerts_enabled: bool = False
    dead_stock_alert_locked_capital_threshold: float = 10000.0
    dead_stock_alert_additional_age_days: int = 30
    dead_stock_alert_cooldown_hours: int = 24
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
    forecast_assisted_pricing_enabled: bool = False
    dynamic_pricing_min_improvement_rate: float = 0.02
    dynamic_pricing_min_actionable_change_rate: float = 0.01
    dynamic_pricing_max_change_rate: float = 0.15
    dynamic_pricing_expiration_hours: int = 72
    rag_enabled: bool = False
    rag_embedding_provider: str = "local_bge"
    rag_embedding_model: str = "BAAI/bge-m3"
    rag_embedding_batch_size: int = 16
    rag_embedding_device: str = "cpu"
    rag_embedding_normalize: bool = True
    rag_embedding_version: str = "v1"
    rag_chunking_version: str = "v1"
    rag_max_chunk_chars: int = 1500
    rag_chunk_overlap_chars: int = 150
    rag_retrieval_top_k: int = 12
    rag_min_similarity: float = 0.35
    rag_prompt_version: str = "v1"
    rag_groq_model: str | None = None
    rag_unembedded_chunk_batch_size: int = 100
    rag_memory_schedule_enabled: bool = False
    rag_memory_daily_hour_utc: int = 3
    rag_memory_daily_minute_utc: int = 30
    rag_outbox_batch_size: int = 100
    rag_outbox_max_attempts: int = 5
    rag_outbox_initial_backoff_seconds: int = 60
    rag_outbox_max_backoff_seconds: int = 3600
    rag_outbox_processing_lease_seconds: int = 900
    rag_cosine_distance_enabled: bool = False
    rag_rrf_enabled: bool = False
    copilot_groq_model: str | None = None
    copilot_groq_timeout_seconds: float = 20.0
    copilot_overall_timeout_seconds: float = 45.0
    copilot_max_tool_calls: int = 10
    copilot_max_iterations: int = 3
    copilot_planning_message_limit: int = 12
    copilot_planning_character_limit: int = 6000
    copilot_multilingual_enabled: bool = False
    copilot_llm_router_enabled: bool = False
    copilot_llm_answer_routes: str = ""
    copilot_llm_answer_routes_en: str = ""
    copilot_llm_answer_routes_bn: str = ""
    copilot_llm_answer_routes_banglish: str = ""
    copilot_anthropic_effort: str = "low"
    copilot_anthropic_max_tokens: int = 16000
    openai_base_url: str = "https://api.openai.com/v1"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    copilot_prompt_tool_chars: int = 12000
    copilot_prompt_total_chars: int = 48000
    copilot_conversation_memory_enabled: bool = False
    copilot_conversation_memory_turns: int = 4
    copilot_answer_repair_enabled: bool = False
    copilot_follow_ups_enabled: bool = False
    copilot_ask_rate_limit_per_minute: int = 0
    copilot_parallel_tools_enabled: bool = False
    copilot_tool_concurrency: int = 4
    copilot_llm_planner_fallback_enabled: bool = False
    copilot_streaming_enabled: bool = False
    copilot_agent_loop_enabled: bool = False
    copilot_always_retrieve_memory: bool = False
    copilot_strict_safety_planning_enabled: bool = False
    rag_query_embedding_cache_size: int = 0

    @property
    def durable_recommendation_jobs_enabled(self) -> bool:
        return self.recommendation_jobs_enabled or self.recommendation_orchestration_enabled

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv()
        env = os.getenv("APP_ENV", "development")
        bootstrap_default = env == "development"
        scraper_schedule_default = env != "development"
        password_reset_code_secret = os.getenv("PASSWORD_RESET_CODE_SECRET")
        if env not in {"development", "test"} and not password_reset_code_secret:
            raise RuntimeError(
                "Missing required environment variable: PASSWORD_RESET_CODE_SECRET"
            )
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
            "password_reset_enabled": _parse_bool(
                os.getenv("PASSWORD_RESET_ENABLED"), default=True
            ),
            "password_reset_code_length": int(os.getenv("PASSWORD_RESET_CODE_LENGTH", "6")),
            "password_reset_code_ttl_minutes": int(
                os.getenv("PASSWORD_RESET_CODE_TTL_MINUTES", "10")
            ),
            "password_reset_max_attempts": int(
                os.getenv("PASSWORD_RESET_MAX_ATTEMPTS", "5")
            ),
            "password_reset_resend_cooldown_seconds": int(
                os.getenv("PASSWORD_RESET_RESEND_COOLDOWN_SECONDS", "60")
            ),
            "password_reset_max_requests_per_hour": int(
                os.getenv("PASSWORD_RESET_MAX_REQUESTS_PER_HOUR", "5")
            ),
            "password_reset_max_requests_per_ip": int(
                os.getenv("PASSWORD_RESET_MAX_REQUESTS_PER_IP", "20")
            ),
            "password_reset_auth_ttl_minutes": int(
                os.getenv("PASSWORD_RESET_AUTH_TTL_MINUTES", "15")
            ),
            "password_reset_revoke_sessions": _parse_bool(
                os.getenv("PASSWORD_RESET_REVOKE_SESSIONS"), default=True
            ),
            "password_reset_code_secret": password_reset_code_secret
            or os.getenv("JWT_SECRET_KEY", ""),
            "email_provider": os.getenv(
                "EMAIL_PROVIDER", "console" if env == "development" else "smtp"
            ),
            "smtp_host": os.getenv("SMTP_HOST"),
            "smtp_port": int(os.getenv("SMTP_PORT", "587")),
            "smtp_username": os.getenv("SMTP_USERNAME"),
            "smtp_password": os.getenv("SMTP_PASSWORD"),
            "smtp_from_email": os.getenv("SMTP_FROM_EMAIL"),
            "smtp_use_tls": _parse_bool(os.getenv("SMTP_USE_TLS"), default=True),
            "smtp_timeout_seconds": int(os.getenv("SMTP_TIMEOUT_SECONDS", "10")),
            "password_reset_email_retry_attempts": int(
                os.getenv("PASSWORD_RESET_EMAIL_RETRY_ATTEMPTS", "2")
            ),
            "bootstrap_db_on_startup": _parse_bool(
                os.getenv("DB_BOOTSTRAP_ON_STARTUP"),
                default=bootstrap_default,
            ),
            "scraper_schedule_enabled": _parse_bool(
                os.getenv("SCRAPER_SCHEDULE_ENABLED"),
                default=scraper_schedule_default,
            ),
            "recommendation_jobs_enabled": _parse_bool(os.getenv("RECOMMENDATION_JOBS_ENABLED")),
            "recommendation_orchestration_enabled": _parse_bool(os.getenv("RECOMMENDATION_ORCHESTRATION_ENABLED")),
            "recommendation_orchestration_shadow_enabled": _parse_bool(os.getenv("RECOMMENDATION_ORCHESTRATION_SHADOW_ENABLED")),
            "historical_dataset_export_enabled": _parse_bool(os.getenv("HISTORICAL_DATASET_EXPORT_ENABLED")),
            "recommendation_action_evaluation_enabled": _parse_bool(os.getenv("RECOMMENDATION_ACTION_EVALUATION_ENABLED")),
            "recommendation_action_min_score": os.getenv("RECOMMENDATION_ACTION_MIN_SCORE", "0.50"),
            "recommendation_action_profit_reference_bdt": os.getenv("RECOMMENDATION_ACTION_PROFIT_REFERENCE_BDT", "1000"),
            "recommendation_action_max_adverse_risk": os.getenv("RECOMMENDATION_ACTION_MAX_ADVERSE_RISK", "0.60"),
            "recommendation_validation_enabled": _parse_bool(os.getenv("RECOMMENDATION_VALIDATION_ENABLED")),
            "recommendation_dashboard_evidence_enabled": _parse_bool(os.getenv("RECOMMENDATION_DASHBOARD_EVIDENCE_ENABLED")),
            "recommendation_explanation_enabled": _parse_bool(os.getenv("RECOMMENDATION_EXPLANATION_ENABLED")),
            "recommendation_explanation_groq_enabled": _parse_bool(os.getenv("RECOMMENDATION_EXPLANATION_GROQ_ENABLED")),
            "recommendation_explanation_model": os.getenv("RECOMMENDATION_EXPLANATION_MODEL", "openai/gpt-oss-20b"),
            "recommendation_explanation_temperature": os.getenv("RECOMMENDATION_EXPLANATION_TEMPERATURE", "0.1"),
            "recommendation_explanation_timeout_seconds": os.getenv("RECOMMENDATION_EXPLANATION_TIMEOUT_SECONDS", "4"),
            "recommendation_explanation_max_retries": os.getenv("RECOMMENDATION_EXPLANATION_MAX_RETRIES", "0"),
            "recommendation_evidence_enabled": _parse_bool(os.getenv("RECOMMENDATION_EVIDENCE_ENABLED")),
            "recommendation_business_signals_enabled": _parse_bool(
                os.getenv("RECOMMENDATION_BUSINESS_SIGNALS_ENABLED")
            ),
            "recommendation_inventory_max_age_hours": int(os.getenv("RECOMMENDATION_INVENTORY_MAX_AGE_HOURS", "48")),
            "recommendation_price_max_age_hours": int(os.getenv("RECOMMENDATION_PRICE_MAX_AGE_HOURS", "24")),
            "recommendation_stock_max_age_hours": int(os.getenv("RECOMMENDATION_STOCK_MAX_AGE_HOURS", "6")),
            "daraz_scraping_authorized": _parse_bool(
                os.getenv("DARAZ_SCRAPING_AUTHORIZED"), default=False,
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
            "forecast_aware_reorder_enabled": _parse_bool(os.getenv("FORECAST_AWARE_REORDER_ENABLED")),
            "reorder_target_service_level": os.getenv("REORDER_TARGET_SERVICE_LEVEL", "0.90"),
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
            "inventory_aging_calculation_version": os.getenv("INVENTORY_AGING_CALCULATION_VERSION", "v1"),
            "inventory_aging_bucket_edges_days": [
                int(item)
                for item in _split_csv(os.getenv("INVENTORY_AGING_BUCKET_EDGES_DAYS", "30,45,60,90,180"))
            ],
            "dead_stock_calculation_version": os.getenv("DEAD_STOCK_CALCULATION_VERSION", "v1"),
            "dead_stock_no_sales_threshold_days": int(os.getenv("DEAD_STOCK_NO_SALES_THRESHOLD_DAYS", "45")),
            "dead_stock_inventory_age_threshold_days": int(os.getenv("DEAD_STOCK_INVENTORY_AGE_THRESHOLD_DAYS", "60")),
            "dead_stock_product_age_grace_period_days": int(os.getenv("DEAD_STOCK_PRODUCT_AGE_GRACE_PERIOD_DAYS", "30")),
            "dead_stock_slow_velocity_units_per_day": float(os.getenv("DEAD_STOCK_SLOW_VELOCITY_UNITS_PER_DAY", "0.25")),
            "dead_stock_strong_velocity_units_per_day": float(os.getenv("DEAD_STOCK_STRONG_VELOCITY_UNITS_PER_DAY", "1.0")),
            "dead_stock_excess_coverage_days": int(os.getenv("DEAD_STOCK_EXCESS_COVERAGE_DAYS", "90")),
            "dead_stock_age_warning_ratio": float(os.getenv("DEAD_STOCK_AGE_WARNING_RATIO", "0.80")),
            "dead_stock_no_sales_warning_ratio": float(os.getenv("DEAD_STOCK_NO_SALES_WARNING_RATIO", "0.80")),
            "dead_stock_excess_coverage_warning_ratio": float(os.getenv("DEAD_STOCK_EXCESS_COVERAGE_WARNING_RATIO", "0.80")),
            "dead_stock_extreme_age_multiplier": float(os.getenv("DEAD_STOCK_EXTREME_AGE_MULTIPLIER", "2.0")),
            "dead_stock_extreme_no_sales_multiplier": float(os.getenv("DEAD_STOCK_EXTREME_NO_SALES_MULTIPLIER", "2.0")),
            "dead_stock_extreme_coverage_multiplier": float(os.getenv("DEAD_STOCK_EXTREME_COVERAGE_MULTIPLIER", "2.0")),
            "dead_stock_low_visibility_threshold": float(os.getenv("DEAD_STOCK_LOW_VISIBILITY_THRESHOLD", "35.0")),
            "dead_stock_inventory_age_weight": float(os.getenv("DEAD_STOCK_INVENTORY_AGE_WEIGHT", "30.0")),
            "dead_stock_no_sales_weight": float(os.getenv("DEAD_STOCK_NO_SALES_WEIGHT", "30.0")),
            "dead_stock_sales_velocity_weight": float(os.getenv("DEAD_STOCK_SALES_VELOCITY_WEIGHT", "15.0")),
            "dead_stock_excess_coverage_weight": float(os.getenv("DEAD_STOCK_EXCESS_COVERAGE_WEIGHT", "15.0")),
            "dead_stock_visibility_weight": float(os.getenv("DEAD_STOCK_VISIBILITY_WEIGHT", "10.0")),
            "dead_stock_recovery_formula_version": os.getenv("DEAD_STOCK_RECOVERY_FORMULA_VERSION", "v1"),
            "evidence_driven_recovery_enabled": _parse_bool(os.getenv("EVIDENCE_DRIVEN_RECOVERY_ENABLED")),
            "dead_stock_recovery_discount_rates": [
                float(item)
                for item in _split_csv(os.getenv("DEAD_STOCK_RECOVERY_DISCOUNT_RATES", "0.05,0.10,0.15,0.20"))
            ],
            "dead_stock_recovery_bundle_min_quantity": int(os.getenv("DEAD_STOCK_RECOVERY_BUNDLE_MIN_QUANTITY", "5")),
            "dead_stock_recovery_flash_sale_min_quantity": int(os.getenv("DEAD_STOCK_RECOVERY_FLASH_SALE_MIN_QUANTITY", "10")),
            "dead_stock_recovery_flash_sale_duration_days": int(os.getenv("DEAD_STOCK_RECOVERY_FLASH_SALE_DURATION_DAYS", "3")),
            "dead_stock_recovery_expiration_days": int(os.getenv("DEAD_STOCK_RECOVERY_EXPIRATION_DAYS", "7")),
            "dead_stock_capital_recovery_formula_version": os.getenv("DEAD_STOCK_CAPITAL_RECOVERY_FORMULA_VERSION", "v1"),
            "dead_stock_capital_recovery_currency": os.getenv("DEAD_STOCK_CAPITAL_RECOVERY_CURRENCY", "BDT"),
            "dead_stock_capital_recovery_default_duration_days": int(os.getenv("DEAD_STOCK_CAPITAL_RECOVERY_DEFAULT_DURATION_DAYS", "14")),
            "dead_stock_capital_recovery_heuristic_low_sell_through_rate": float(os.getenv("DEAD_STOCK_CAPITAL_RECOVERY_HEURISTIC_LOW_SELL_THROUGH_RATE", "0.25")),
            "dead_stock_capital_recovery_heuristic_central_sell_through_rate": float(os.getenv("DEAD_STOCK_CAPITAL_RECOVERY_HEURISTIC_CENTRAL_SELL_THROUGH_RATE", "0.40")),
            "dead_stock_capital_recovery_heuristic_high_sell_through_rate": float(os.getenv("DEAD_STOCK_CAPITAL_RECOVERY_HEURISTIC_HIGH_SELL_THROUGH_RATE", "0.55")),
            "dead_stock_workflow_schedule_enabled": _parse_bool(
                os.getenv("DEAD_STOCK_WORKFLOW_SCHEDULE_ENABLED"),
                default=False,
            ),
            "dead_stock_workflow_daily_hour_utc": int(os.getenv("DEAD_STOCK_WORKFLOW_DAILY_HOUR_UTC", "2")),
            "dead_stock_workflow_daily_minute_utc": int(os.getenv("DEAD_STOCK_WORKFLOW_DAILY_MINUTE_UTC", "15")),
            "dead_stock_workflow_debounce_seconds": int(os.getenv("DEAD_STOCK_WORKFLOW_DEBOUNCE_SECONDS", "300")),
            "dead_stock_alerts_enabled": _parse_bool(
                os.getenv("DEAD_STOCK_ALERTS_ENABLED"),
                default=False,
            ),
            "dead_stock_alert_locked_capital_threshold": float(os.getenv("DEAD_STOCK_ALERT_LOCKED_CAPITAL_THRESHOLD", "10000.0")),
            "dead_stock_alert_additional_age_days": int(os.getenv("DEAD_STOCK_ALERT_ADDITIONAL_AGE_DAYS", "30")),
            "dead_stock_alert_cooldown_hours": int(os.getenv("DEAD_STOCK_ALERT_COOLDOWN_HOURS", "24")),
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
            "forecast_assisted_pricing_enabled": _parse_bool(os.getenv("FORECAST_ASSISTED_PRICING_ENABLED")),
            "dynamic_pricing_min_improvement_rate": float(os.getenv("DYNAMIC_PRICING_MIN_IMPROVEMENT_RATE", "0.02")),
            "dynamic_pricing_min_actionable_change_rate": float(os.getenv("DYNAMIC_PRICING_MIN_ACTIONABLE_CHANGE_RATE", "0.01")),
            "dynamic_pricing_max_change_rate": float(os.getenv("DYNAMIC_PRICING_MAX_CHANGE_RATE", "0.15")),
            "dynamic_pricing_expiration_hours": int(os.getenv("DYNAMIC_PRICING_EXPIRATION_HOURS", "72")),
            "rag_enabled": _parse_bool(os.getenv("RAG_ENABLED"), default=False),
            "rag_embedding_provider": os.getenv("RAG_EMBEDDING_PROVIDER", "local_bge"),
            "rag_embedding_model": os.getenv("RAG_EMBEDDING_MODEL", "BAAI/bge-m3"),
            "rag_embedding_batch_size": int(os.getenv("RAG_EMBEDDING_BATCH_SIZE", "16")),
            "rag_embedding_device": os.getenv("RAG_EMBEDDING_DEVICE", "cpu"),
            "rag_embedding_normalize": _parse_bool(os.getenv("RAG_EMBEDDING_NORMALIZE"), default=True),
            "rag_embedding_version": os.getenv("RAG_EMBEDDING_VERSION", "v1"),
            "rag_chunking_version": os.getenv("RAG_CHUNKING_VERSION", "v1"),
            "rag_max_chunk_chars": int(os.getenv("RAG_MAX_CHUNK_CHARS", "1500")),
            "rag_chunk_overlap_chars": int(os.getenv("RAG_CHUNK_OVERLAP_CHARS", "150")),
            "rag_retrieval_top_k": int(os.getenv("RAG_RETRIEVAL_TOP_K", "12")),
            "rag_min_similarity": float(os.getenv("RAG_MIN_SIMILARITY", "0.35")),
            "rag_prompt_version": os.getenv("RAG_PROMPT_VERSION", "v1"),
            "rag_groq_model": os.getenv("RAG_GROQ_MODEL"),
            "rag_unembedded_chunk_batch_size": int(os.getenv("RAG_UNEMBEDDED_CHUNK_BATCH_SIZE", "100")),
            "rag_memory_schedule_enabled": _parse_bool(os.getenv("RAG_MEMORY_SCHEDULE_ENABLED"), default=False),
            "rag_memory_daily_hour_utc": int(os.getenv("RAG_MEMORY_DAILY_HOUR_UTC", "3")),
            "rag_memory_daily_minute_utc": int(os.getenv("RAG_MEMORY_DAILY_MINUTE_UTC", "30")),
            "rag_outbox_batch_size": int(os.getenv("RAG_OUTBOX_BATCH_SIZE", "100")),
            "rag_outbox_max_attempts": int(os.getenv("RAG_OUTBOX_MAX_ATTEMPTS", "5")),
            "rag_outbox_initial_backoff_seconds": int(os.getenv("RAG_OUTBOX_INITIAL_BACKOFF_SECONDS", "60")),
            "rag_outbox_max_backoff_seconds": int(os.getenv("RAG_OUTBOX_MAX_BACKOFF_SECONDS", "3600")),
            "rag_outbox_processing_lease_seconds": int(os.getenv("RAG_OUTBOX_PROCESSING_LEASE_SECONDS", "900")),
            "rag_cosine_distance_enabled": _parse_bool(os.getenv("RAG_COSINE_DISTANCE_ENABLED"), default=False),
            "rag_rrf_enabled": _parse_bool(os.getenv("RAG_RRF_ENABLED"), default=False),
            "copilot_groq_model": os.getenv("GROQ_COPILOT_MODEL") or os.getenv("GROQ_MODEL"),
            "copilot_groq_timeout_seconds": float(os.getenv("COPILOT_GROQ_TIMEOUT_SECONDS", "20")),
            "copilot_overall_timeout_seconds": float(os.getenv("COPILOT_OVERALL_TIMEOUT_SECONDS", "45")),
            "copilot_max_tool_calls": int(os.getenv("COPILOT_MAX_TOOL_CALLS", "10")),
            "copilot_max_iterations": int(os.getenv("COPILOT_MAX_ITERATIONS", "3")),
            "copilot_planning_message_limit": int(os.getenv("COPILOT_PLANNING_MESSAGE_LIMIT", "12")),
            "copilot_planning_character_limit": int(os.getenv("COPILOT_PLANNING_CHARACTER_LIMIT", "6000")),
            "copilot_multilingual_enabled": _parse_bool(os.getenv("COPILOT_MULTILINGUAL_ENABLED"), default=False),
            "copilot_llm_router_enabled": _parse_bool(os.getenv("COPILOT_LLM_ROUTER_ENABLED"), default=False),
            "copilot_llm_answer_routes": os.getenv("COPILOT_LLM_ANSWER_ROUTES", ""),
            "copilot_llm_answer_routes_en": os.getenv("COPILOT_LLM_ANSWER_ROUTES_EN", ""),
            "copilot_llm_answer_routes_bn": os.getenv("COPILOT_LLM_ANSWER_ROUTES_BN", ""),
            "copilot_llm_answer_routes_banglish": os.getenv("COPILOT_LLM_ANSWER_ROUTES_BANGLISH", ""),
            "copilot_anthropic_effort": os.getenv("COPILOT_ANTHROPIC_EFFORT", "low"),
            "copilot_anthropic_max_tokens": int(os.getenv("COPILOT_ANTHROPIC_MAX_TOKENS", "16000")),
            "openai_base_url": os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1",
            "gemini_base_url": os.getenv("GEMINI_BASE_URL") or "https://generativelanguage.googleapis.com/v1beta/openai",
            "openrouter_base_url": os.getenv("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1",
            "copilot_prompt_tool_chars": int(os.getenv("COPILOT_PROMPT_TOOL_CHARS", "12000")),
            "copilot_prompt_total_chars": int(os.getenv("COPILOT_PROMPT_TOTAL_CHARS", "48000")),
            "copilot_conversation_memory_enabled": _parse_bool(os.getenv("COPILOT_CONVERSATION_MEMORY_ENABLED"), default=False),
            "copilot_conversation_memory_turns": int(os.getenv("COPILOT_CONVERSATION_MEMORY_TURNS", "4")),
            "copilot_answer_repair_enabled": _parse_bool(os.getenv("COPILOT_ANSWER_REPAIR_ENABLED"), default=False),
            "copilot_follow_ups_enabled": _parse_bool(os.getenv("COPILOT_FOLLOW_UPS_ENABLED"), default=False),
            "copilot_ask_rate_limit_per_minute": int(os.getenv("COPILOT_ASK_RATE_LIMIT_PER_MINUTE", "0")),
            "copilot_parallel_tools_enabled": _parse_bool(os.getenv("COPILOT_PARALLEL_TOOLS_ENABLED"), default=False),
            "copilot_tool_concurrency": int(os.getenv("COPILOT_TOOL_CONCURRENCY", "4")),
            "copilot_llm_planner_fallback_enabled": _parse_bool(os.getenv("COPILOT_LLM_PLANNER_FALLBACK_ENABLED"), default=False),
            "copilot_streaming_enabled": _parse_bool(os.getenv("COPILOT_STREAMING_ENABLED"), default=False),
            "copilot_agent_loop_enabled": _parse_bool(os.getenv("COPILOT_AGENT_LOOP_ENABLED"), default=False),
            "copilot_always_retrieve_memory": _parse_bool(os.getenv("COPILOT_ALWAYS_RETRIEVE_MEMORY"), default=False),
            "copilot_strict_safety_planning_enabled": _parse_bool(os.getenv("COPILOT_STRICT_SAFETY_PLANNING_ENABLED"), default=False),
            "rag_query_embedding_cache_size": int(os.getenv("RAG_QUERY_EMBEDDING_CACHE_SIZE", "0")),
        }
        return cls.model_validate(data)


settings = Settings.load()
