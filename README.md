# BazarSync AI

Bangla-first AI commerce intelligence for marketplace sellers.

BazarSync AI gives Daraz and other marketplace sellers one dashboard for products, competitors, pricing, inventory, sales, dead stock, alerts and recommendations. Deterministic backend services do every financial and operational calculation. Language models only explain verified evidence, through a seller-scoped Business Copilot that answers in English, Bangla or Banglish.

> **Full-stack application.** Run the FastAPI API, Celery worker (and beat, if schedules are on), PostgreSQL with pgvector, Redis and the Vite frontend as separate services unless your host supports the full stack.

## Contents

- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Repository Structure](#repository-structure)
- [Local Development](#local-development)
- [Demo Data](#demo-data)
- [Configuration](#configuration)
- [Feature Flags](#feature-flags)
- [Database and Migrations](#database-and-migrations)
- [Business Copilot and RAG Memory](#business-copilot-and-rag-memory)
- [Recommendation Engine v2 and Forecasting](#recommendation-engine-v2-and-forecasting)
- [Competitor Data from Daraz](#competitor-data-from-daraz)
- [Telegram Alerts](#telegram-alerts)
- [Testing and Evaluation](#testing-and-evaluation)
- [Deployment](#deployment)
- [Security](#security)
- [Troubleshooting](#troubleshooting)
- [Documentation](#documentation)
- [License](#license)

## Features

### Seller dashboard

- Product catalog, listings, visibility metrics and stock-in receipts.
- Competitor monitoring: rankings, price events, market opportunities and product matching.
- Pricing analytics: fee policies, MarginGuard checks, revenue simulation and dynamic pricing recommendations.
- Inventory intelligence: sales velocity, stockout prediction, reorder plans, aging and risk.
- Sales import with unit price, line total, status, currency and coverage tracking.
- Revenue and estimated profit computed in the backend with `Decimal`.
- Dead-stock classification, capital recovery estimates and recovery plans.
- Recommendations with saved evidence, a track record of outcomes, alerts and realtime activity over Socket.IO.

### Recommendation engine v2

- Durable, retry-safe generation jobs with status polling.
- Evidence collection and validation: competitor freshness, business signals, inventory and price age limits.
- MarginGuard applied to every exact price candidate with its marketplace fee policy.
- Decision orchestration and action scoring, with a shadow mode for comparison.
- Statistical demand forecasts, demand regimes and prediction intervals. Optional CatBoost models run in an isolated inference container.
- Forecast-assisted pricing, forecast-aware reorder planning and evidence-driven dead-stock recovery.
- Bangla explanations limited to approved wording and verified metrics.
- Outcome tracking that measures whether past recommendations worked.

Generating or acknowledging a recommendation never changes a live marketplace price or stock level.

### Business Copilot 2.x

- Chat widget and full-page mode, scoped to the signed-in seller.
- Deterministic planner that picks allowlisted, read-only tools and metrics.
- Generic `query_business_records` tool: lists or aggregates sales, stock-ins, inventory, prices, promotions, alerts, recommendations, competitor snapshots and products, with exact totals and Asia/Dhaka date buckets.
- English, Bangla and Banglish detection with same-language replies.
- Provider router across Groq, Anthropic Claude and OpenAI-compatible APIs (OpenAI, Gemini, OpenRouter), with fallbacks inside one timeout.
- Bounded agent loop, conversation memory, answer repair and suggested follow-ups.
- Streaming progress over Server-Sent Events, per-message feedback and per-seller rate limits.
- A validator that rejects unsupported numbers, claims or evidence. Every answer carries evidence, confidence, freshness and what is not recorded.
- Action proposals for price changes, promotions and reorders. Approval is internal only; nothing is sent to the marketplace.

### RAG memory

- Seller-scoped memory documents and chunks for products, sales, inventory, stock-ins, pricing, competitors, recommendations, alerts, promotions and Copilot history.
- pgvector search with BGE-M3 embeddings (local SentenceTransformers).
- Optional hybrid retrieval: reciprocal rank fusion of vector and keyword search, full-text keywords, English keyword translation for Bangla and Banglish, and a BGE reranker.
- Outbox-based indexing with retries, leases and backoff; stale and deleted documents are excluded.

### Integrations

- Telegram connection, alerts and product snapshots.
- Authorized Daraz search and detail acquisition with rate limits and a circuit breaker.
- Password reset by email (SMTP).
- Celery workers and beat schedules for scraping, inventory, dead stock, outcomes and RAG indexing.

## Architecture

```mermaid
flowchart TD
    UI["React + Vite frontend"] --> API["FastAPI backend"]
    API --> Auth["JWT seller auth"]
    API --> DB[("PostgreSQL + pgvector")]
    API --> Redis[("Redis")]
    Redis --> Worker["Celery worker + beat"]
    Worker --> DB
    Worker --> Daraz["Daraz (authorized scraping)"]
    Worker --> Telegram["Telegram Bot API"]
    API --> LLM["LLM providers<br/>Groq · Claude · OpenAI-compatible<br/>backend only"]
    Forecast["Forecast inference container<br/>no network, read-only models"] -.-> DB

    subgraph Copilot["Business Copilot"]
      Planner["Question planner"]
      Tools["Allowlisted tools + metrics"]
      RAG["Seller-scoped RAG retrieval"]
      Router["LLM router"]
      Validator["Response validator"]
    end

    API --> Planner --> Tools
    Tools --> RAG
    Tools --> Router --> Validator --> API
```

Copilot request path:

```text
Seller question
  -> language detection and planner
  -> allowlisted tools + MetricExecutionService (seller-scoped, deterministic)
  -> seller-scoped RAG memory retrieval
  -> LLM router explains the returned facts
  -> validator checks numbers, claims and evidence
  -> frontend widget (JSON or SSE stream)
```

The Copilot never generates or runs SQL, never exposes provider keys, never changes marketplace state and never skips seller ownership checks.

## Tech Stack

| Layer | Stack |
| --- | --- |
| Backend | Python 3.14, FastAPI, SQLAlchemy, Alembic, Pydantic, Celery, Redis, python-socketio |
| Data | PostgreSQL, pgvector |
| AI | Groq, Anthropic and OpenAI-compatible SDKs; SentenceTransformers (BGE-M3, BGE reranker); scikit-learn, SciPy |
| Forecasting | Statistical forecasters in the API; CatBoost in a separate CPU-only training and inference image |
| Scraping | httpx, Playwright, BeautifulSoup, lxml |
| Frontend | React 19, Vite 8, TypeScript 6, Tailwind CSS, shadcn/Radix UI, TanStack Query and Table, React Router 7, Recharts, Framer Motion, Zod, Socket.IO client |
| Testing | pytest, Vitest, Testing Library |

## Repository Structure

```text
.
├── backend/
│   ├── alembic/                  # Additive database migrations
│   ├── app/
│   │   ├── ai/                   # LLM providers, router, prompts, Bangla explanations
│   │   ├── analytics/            # Pricing, stock and metric engines
│   │   ├── api/                  # FastAPI routes (api/v1)
│   │   ├── core/                 # Settings, security, Celery, Socket.IO
│   │   ├── db/                   # Sessions and vector helpers
│   │   ├── models/               # SQLAlchemy models
│   │   ├── repositories/         # Data access
│   │   ├── schemas/              # Pydantic schemas
│   │   ├── scraper/              # Daraz acquisition, parsing and matching
│   │   ├── services/             # Business, recommendation, forecast, Copilot and RAG services
│   │   ├── tasks/                # Celery tasks
│   │   └── main.py               # FastAPI entrypoint
│   ├── scripts/                  # Setup checks, seeding, backtests, training, evaluation
│   ├── tests/                    # Unit, integration, API and evaluation tests
│   ├── Dockerfile.inference      # Isolated forecast inference image
│   ├── Dockerfile.training       # CPU-only CatBoost training image
│   ├── requirements.txt
│   └── requirements-training.txt
├── frontend/
│   └── src/
│       ├── components/           # UI components
│       ├── hooks/                # React Query and UI hooks
│       ├── pages/                # Route pages
│       ├── routes/               # Router and navigation
│       ├── services/             # API clients
│       ├── types/
│       └── utils/
├── docs/                         # Design notes, task records and evaluations
├── Dockerfile                    # API and worker image (Playwright base)
├── docker-compose.yml            # API, worker and Redis
└── docker-compose.forecast.yml   # Optional forecast inference profile
```

## Local Development

### Prerequisites

- Python 3.14
- Node.js and npm
- PostgreSQL with the pgvector extension
- Redis
- Optional: an API key for Groq, Anthropic, Gemini, OpenAI or OpenRouter
- Optional: a Telegram bot token

### 1. Clone and configure

```bash
git clone https://github.com/DevNexus09/BazarSync-AI.git
cd BazarSync-AI
cp .env.example .env
```

`.env.example` holds the optional settings and feature flags. Add these required values yourself:

```env
APP_ENV=development
DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@localhost:5432/bazarsync_ai
JWT_SECRET_KEY=replace_with_a_long_random_secret
REDIS_URL=redis://127.0.0.1:6379/0
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
```

### 2. Start Redis

```bash
docker compose up -d redis
```

### 3. Backend

```bash
cd backend
python3.14 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python scripts/check_local_setup.py
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- API: `http://127.0.0.1:8000`
- OpenAPI docs: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/api/v1/health`

### 4. Celery worker

In a second terminal, from `backend/` with the virtualenv active:

```bash
celery -A app.core.celery_app:celery_app worker --loglevel=info
```

Scheduled jobs also need beat. Beat only registers the schedules whose flags are on:

```bash
celery -A app.core.celery_app:celery_app beat --loglevel=info
```

### 5. Frontend

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

## Demo Data

Seeding writes only to a local `development` or `test` database and performs no scraping, marketplace update or Telegram delivery.

1. **Catalog seed.** Creates the demo footwear seller and its 15 products. See [demo data seeding](docs/demo-data-seeding.md).

   ```bash
   cd backend
   PYTHONPATH=. venv/bin/python scripts/seed_demo_footwear_store.py --dry-run
   ```

2. **Comprehensive seed.** Adds sales, inventory, pricing, competitor, recommendation and RAG evidence for that seller. It is a dry run unless you pass `--apply`. See [comprehensive demo seeding](docs/comprehensive-demo-seeding.md).

   ```bash
   cd backend
   PYTHONPATH=. venv/bin/python scripts/seed_comprehensive_demo.py \
     --apply --email demo1@gmail.com --as-of 2026-11-21 --skip-external-services
   ```

## Configuration

`.env.example` documents every optional setting with comments. The main groups are below.

### Core backend

| Variable | Required | Notes |
| --- | --- | --- |
| `APP_ENV` | Recommended | `development`, `test` or a production name. |
| `DATABASE_URL` | Yes | SQLAlchemy URL. An async URL is derived from it. |
| `JWT_SECRET_KEY` | Yes | Long random value, backend only. |
| `JWT_ALGORITHM` | No | Defaults to `HS256`. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | Defaults to `60`. |
| `CORS_ORIGINS` | Production | Comma-separated frontend origins. |
| `DB_BOOTSTRAP_ON_STARTUP` | No | Development helper. Use migrations in production. |
| `REDIS_URL`, `REDIS_BROKER_URL` | Recommended | Broker falls back to `REDIS_URL`. |

### Frontend

| Variable | Notes |
| --- | --- |
| `VITE_API_BASE_URL` | Public API base URL ending in `/api/v1`. Required. |
| `VITE_RECOMMENDATION_DASHBOARD_V2` | Recommendation evidence dashboard. |
| `VITE_PRICING_V2_UI`, `VITE_INVENTORY_V2_UI` | Redesigned pricing and inventory pages. |

Never put a secret in a `VITE_*` variable; everything with that prefix is shipped to the browser.

### AI providers

| Variable | Notes |
| --- | --- |
| `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_COPILOT_MODEL` | Groq. `GROQ_COPILOT_MODEL` falls back to `GROQ_MODEL`. |
| `ANTHROPIC_API_KEY` | Claude routes in the Copilot router. |
| `GEMINI_API_KEY`, `GEMINI_BASE_URL` | Gemini through its OpenAI-compatible endpoint. |
| `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL` | OpenRouter. |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` | OpenAI or another compatible endpoint. |
| `COPILOT_LLM_ANSWER_ROUTES[_EN\|_BN\|_BANGLISH]` | Comma-separated `provider:model` routes tried in order, for example `gemini:gemini-3.5-flash-lite,groq`. |
| `RAG_GROQ_MODEL` | Model for grounded `/rag/ask` answers. |

### RAG

| Variable | Notes |
| --- | --- |
| `RAG_ENABLED` | Enables the authenticated RAG endpoint. |
| `RAG_EMBEDDING_MODEL`, `RAG_EMBEDDING_DEVICE` | Default `BAAI/bge-m3`; device `cpu`, `mps` or another accelerator. |
| `RAG_RETRIEVAL_TOP_K`, `RAG_MIN_SIMILARITY` | Retrieval bounds. |
| `RAG_RERANKER_MODEL` | Default `BAAI/bge-reranker-v2-m3`. |
| `RAG_OUTBOX_*` | Indexing batch size, attempts, backoff and lease. |

### Scraping

| Variable | Notes |
| --- | --- |
| `DARAZ_SCRAPING_AUTHORIZED` | Default `false`. Enable only with authorization covering the configured Daraz paths. |
| `SCRAPER_HTTPX_ENABLED` | Default `true`. Set `false` to start with the Playwright strategy. |
| `SCRAPER_DETAIL_CONCURRENCY` | Detail pages per scrape. |
| `SCRAPER_DARAZ_MIN_INTERVAL_SECONDS`, `SCRAPER_DARAZ_MAX_IN_FLIGHT`, `SCRAPER_DARAZ_BUDGET_PER_MINUTE` | Shared limits across workers on the same Redis. Set to your authorized quota. |
| `SCRAPER_DARAZ_CIRCUIT_*` | Circuit breaker after repeated failures. |
| `SIMILARITY_*` | Product matching model and thresholds. |

### Email and Telegram

| Variable | Notes |
| --- | --- |
| `PASSWORD_RESET_CODE_SECRET` | Required outside development and test. |
| `EMAIL_PROVIDER`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM_EMAIL`, `SMTP_USERNAME`, `SMTP_PASSWORD` | Use `smtp` outside local development. |
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather. |
| `TELEGRAM_WEBHOOK_URL` | Public HTTPS URL ending in `/api/v1/telegram/webhook`. Registered on startup when set. |
| `TELEGRAM_WEBHOOK_SECRET` | Validates Telegram's secret token header. |

## Feature Flags

Major features ship behind flags that are **off by default**. With every flag off, request paths and response contracts match earlier releases; new response fields come back null or empty.

| Area | Flags |
| --- | --- |
| Recommendation jobs and evidence | `RECOMMENDATION_JOBS_ENABLED`, `RECOMMENDATION_EVIDENCE_ENABLED`, `RECOMMENDATION_VALIDATION_ENABLED`, `RECOMMENDATION_BUSINESS_SIGNALS_ENABLED`, `RECOMMENDATION_DASHBOARD_EVIDENCE_ENABLED` |
| Decisions | `RECOMMENDATION_ORCHESTRATION_ENABLED`, `RECOMMENDATION_ORCHESTRATION_SHADOW_ENABLED`, `RECOMMENDATION_ACTION_EVALUATION_ENABLED`, `RECOMMENDATION_OUTCOMES_ENABLED` |
| Forecast-driven actions | `FORECAST_ASSISTED_PRICING_ENABLED`, `FORECAST_ASSISTED_PRICING_SELECTION_ENABLED`, `FORECAST_AWARE_REORDER_ENABLED`, `FORECAST_AWARE_REORDER_SHADOW_ENABLED`, `EVIDENCE_DRIVEN_RECOVERY_ENABLED`, `DEMAND_RESPONSE_POOLING_ENABLED`, `VARIABILITY_SAFETY_STOCK_ENABLED` |
| Explanations | `RECOMMENDATION_EXPLANATION_ENABLED`, `RECOMMENDATION_EXPLANATION_GROQ_ENABLED` |
| Copilot | `COPILOT_MULTILINGUAL_ENABLED`, `COPILOT_LLM_ROUTER_ENABLED`, `COPILOT_AGENT_LOOP_ENABLED`, `COPILOT_CONVERSATION_MEMORY_ENABLED`, `COPILOT_ANSWER_REPAIR_ENABLED`, `COPILOT_FOLLOW_UPS_ENABLED`, `COPILOT_PARALLEL_TOOLS_ENABLED`, `COPILOT_LLM_PLANNER_FALLBACK_ENABLED`, `COPILOT_STREAMING_ENABLED`, `COPILOT_STRICT_SAFETY_PLANNING_ENABLED` |
| RAG retrieval | `RAG_RRF_ENABLED`, `RAG_FULLTEXT_KEYWORD_ENABLED`, `RAG_KEYWORD_TRANSLATION_ENABLED`, `RAG_RERANKER_ENABLED` |
| Schedules | `SCRAPER_SCHEDULE_ENABLED`, `SCRAPER_ADAPTIVE_ENABLED`, `INVENTORY_INTELLIGENCE_SCHEDULE_ENABLED`, `DEAD_STOCK_WORKFLOW_SCHEDULE_ENABLED`, `RAG_MEMORY_SCHEDULE_ENABLED` |
| Data export | `HISTORICAL_DATASET_EXPORT_ENABLED` |

Turn flags on in staging first and check the related task notes in [docs/recommendation-engine-v2](docs/recommendation-engine-v2/implementation-progress.md) or [docs/copilot](docs/copilot/business-copilot-v2.md).

## Database and Migrations

From `backend/` with the virtualenv active:

```bash
python -m alembic upgrade head
```

Migrations are additive and keep older rows readable. When you change the schema, check that the latest migration reverses cleanly:

```bash
python -m alembic downgrade -1
python -m alembic upgrade head
```

RAG memory needs pgvector. The migration tries Supabase's extension schema first, then the default schema:

```sql
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS vector;
```

Use a pgvector-enabled PostgreSQL image, or install pgvector for your PostgreSQL version, before running migrations.

## Business Copilot and RAG Memory

Safety rules the Copilot follows:

- Seller identity comes from the authenticated request; product actions check ownership.
- Models never query the database, write SQL or see other sellers' data.
- Only registered tools and metrics run. Seller IDs proposed by a model are discarded.
- Money is calculated in the backend with `Decimal`. Profit is blocked or marked partial when cost or fee policy is missing, and mixed currencies produce no money figure.
- Current database facts override older memory.
- Prompt-injection and override requests are refused when strict safety planning is on.
- Marketplace changes are proposals only.

Endpoints (prefix `/api/v1`):

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/copilot/ask` | Ask a question (`language`: `en`, `bn`, or `banglish` when multilingual is on). |
| `POST` | `/copilot/ask/stream` | Same answer over SSE, with progress `stage` events. |
| `GET`, `POST` | `/copilot/conversations` | List or create conversations. |
| `GET` | `/copilot/conversations/{conversation_id}` | Conversation with message metadata. |
| `POST` | `/copilot/messages/{message_id}/feedback` | Thumbs up or down with an optional reason. |
| `GET` | `/copilot/capabilities`, `/copilot/tools`, `/copilot/health` | Features, tools and status. |
| `GET`, `POST` | `/copilot/action-proposals[/{id}/approve\|reject]` | Review internal action proposals. |
| `POST` | `/rag/ask` | Grounded answer from seller memory. |
| `GET` | `/rag/coverage`, `/rag/health` | Memory coverage and status. |

Key modules live in `backend/app/services/copilot/`, `backend/app/ai/llm/` (provider router) and `backend/app/services/rag_*.py`.

## Recommendation Engine v2 and Forecasting

Deterministic services decide; the LLM only explains verified evidence. Read the [architecture baseline](docs/recommendation-engine-v2/architecture-baseline.md), [compatibility contract](docs/recommendation-engine-v2/compatibility-contract.md) and [implementation progress](docs/recommendation-engine-v2/implementation-progress.md) before changing this area.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/recommendations/generate/{product_id}` | Queue a recommendation job. |
| `GET` | `/recommendations/jobs/{job_id}` | Job status. |
| `GET` | `/recommendations/products/{product_id}/job` | Latest job for a product. |
| `GET` | `/recommendations/latest/{product_id}` | Latest recommendation with evidence. |
| `GET` | `/recommendation-outcomes/track-record` | How past recommendations performed. |

Forecasting layers:

1. **Historical dataset and features.** `scripts/export_historical_dataset.py` builds point-in-time training data.
2. **Statistical forecasts.** Demand regimes pick a forecaster per product and horizon, or abstain when evidence is thin. Prediction intervals carry calibration provenance.
3. **CatBoost (optional, offline).** Trained in a separate CPU-only environment, never in a request handler:

   ```bash
   cd backend
   pip install -r requirements-training.txt   # in a separate virtualenv
   python scripts/verify_catboost_environment.py
   python scripts/train_catboost_forecasts.py --help
   ```

4. **Isolated inference.** `docker-compose.forecast.yml` runs approved models with no network, a read-only filesystem and SHA-256-pinned artifacts. `FORECAST_ML_MODE` is `disabled` (default) or `shadow`; the statistical forecast stays authoritative. See [task 14](docs/recommendation-engine-v2/task-14-forecast-inference.md).

   ```bash
   FORECAST_ML_MODE=shadow docker compose -f docker-compose.forecast.yml --profile forecast \
     run --rm forecast-inference --seller-id <seller-uuid> \
     --snapshot /inputs/snapshot.json --origin 2026-11-16T06:00:00Z --horizon 7
   ```

> **Status.** The latest [production-readiness audit](docs/recommendation-engine-v2/production-readiness-audit.md) records **NO-GO** for enabling the v2 path in production, and CatBoost has a no-go at every horizon. Keep these flags off in production until the open items are closed.

## Competitor Data from Daraz

Competitor acquisition runs in Celery and only when `DARAZ_SCRAPING_AUTHORIZED=true`. It tries httpx first and falls back to Playwright, shares rate limits across workers through Redis, and opens a circuit breaker after repeated failures. Product matching combines title, attributes and embedding similarity with confidence thresholds. See [Daraz scraping](docs/daraz-scraping.md), [matching](docs/daraz-matching.md) and [operations](docs/daraz-operations.md).

## Telegram Alerts

Telegram supports connection management, inventory alerts with cooldowns and retries, and product intelligence snapshots.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/telegram/send-product-snapshot \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"product_id":"PRODUCT_UUID"}'
```

## Testing and Evaluation

### Backend

From `backend/` with the virtualenv active:

```bash
pytest -q
pytest tests/test_copilot_*.py tests/api/test_copilot.py tests/api/test_rag.py -q
ruff check .
ruff format --check .
mypy app
```

Some integration tests need a disposable PostgreSQL database; optional StatsForecast tests are skipped when it is not installed. Tests pin Copilot and RAG flags to code defaults, so a local `.env` does not change their behavior.

### Frontend

From `frontend/`:

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

### Evaluation scripts

These scripts only read business data. Some write their reports under `backend/artifacts/`.

| Script | Measures |
| --- | --- |
| `scripts/evaluate_copilot.py`, `scripts/copilot_eval.py` | Copilot answer accuracy and safety on a golden question set. |
| `scripts/evaluate_rag_retrieval.py` | Retrieval recall and MRR in English, Bangla and Banglish ([results](docs/copilot/rag-retrieval-eval.md)). |
| `scripts/evaluate_daraz_matching.py` | Competitor product matching quality. |
| `scripts/backtest_*.py` | Forecast, regime and interval backtests. |
| `scripts/reorder_shadow_report.py` | Forecast-aware reorder versus the current planner. |

## Deployment

### Services

- Frontend: static hosting such as Vercel, Netlify or Cloudflare Pages (`frontend/vercel.json` is included).
- Backend API and Celery worker: any container platform, using the root `Dockerfile`.
- Celery beat: one instance, only if schedules are enabled.
- PostgreSQL with pgvector, and Redis.
- Optional: forecast inference container from `docker-compose.forecast.yml`.

### Docker Compose

`docker-compose.yml` runs the API, worker and Redis. PostgreSQL and beat are provisioned separately.

```bash
docker compose up --build
```

### Backend checklist

1. Set `APP_ENV`, `DATABASE_URL`, `CORS_ORIGINS` and Redis variables.
2. Set strong `JWT_SECRET_KEY` and `PASSWORD_RESET_CODE_SECRET`.
3. Make sure pgvector is available, then run `alembic upgrade head`.
4. Set LLM provider keys on the backend only.
5. Configure SMTP and Telegram if those features are on.
6. Review every feature flag; leave unaudited ones off.
7. Run backend tests and the migration downgrade/upgrade check before release.

### Frontend checklist

1. Set `VITE_API_BASE_URL` to the public API URL.
2. Run lint, typecheck, tests and build.
3. Deploy `frontend/dist`.

## Security

- The frontend stores JWTs in `localStorage`. For production, prefer httpOnly secure cookies or another mitigated strategy, and set a strict CSP.
- LLM, SMTP, Telegram and database credentials stay on the backend.
- Never expose service keys, database URLs, embeddings, raw prompts or stack traces to the frontend.
- Enforce seller isolation in every route, worker task, cache, event and RAG query.
- Marketplace changes stay behind an explicit, tested execution layer. Copilot approval and recommendation acknowledgment are internal only.
- Validate imported business data before analytics use.
- Scrape Daraz only within written authorization and the configured quota.

## Troubleshooting

**Redis connection refused** (`Error 61 connecting to localhost:6379`): start Redis with `docker compose up -d redis` or `redis-server`.

**pgvector migration fails**: install pgvector or use a pgvector-enabled PostgreSQL image, then rerun `python -m alembic upgrade head` from `backend/`.

**Copilot answers look generic or inconsistent**: no LLM provider is reachable, so the deterministic fallback answers. Set a provider key and check `GET /api/v1/copilot/health`. `scripts/copilot_eval.py` reproduces the fallback.

**Scheduled jobs never run**: start Celery beat and turn on the matching `*_SCHEDULE_ENABLED` flag.

**Scrapes are skipped**: `DARAZ_SCRAPING_AUTHORIZED` is `false`, or the circuit breaker is open after repeated failures.

**Frontend cannot reach the backend**: check `VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1` and `CORS_ORIGINS`, then restart the Vite dev server.

## Documentation

| Topic | Location |
| --- | --- |
| Recommendation engine v2 | [docs/recommendation-engine-v2](docs/recommendation-engine-v2/implementation-progress.md) |
| Business Copilot 2.x | [docs/copilot/business-copilot-v2.md](docs/copilot/business-copilot-v2.md) |
| Multilingual evaluation | [docs/copilot/multilingual-eval.md](docs/copilot/multilingual-eval.md) |
| RAG retrieval evaluation | [docs/copilot/rag-retrieval-eval.md](docs/copilot/rag-retrieval-eval.md) |
| Pricing and inventory plan | [docs/pricing-inventory-improvement-plan.md](docs/pricing-inventory-improvement-plan.md) |
| Daraz scraping, matching, operations | [docs/daraz-scraping.md](docs/daraz-scraping.md) |
| Demo seeding | [docs/demo-data-seeding.md](docs/demo-data-seeding.md), [docs/comprehensive-demo-seeding.md](docs/comprehensive-demo-seeding.md) |
| Engineering contract | [AGENTS.md](AGENTS.md) |

## License

Released under the [MIT License](LICENSE).
