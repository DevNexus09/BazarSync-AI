# BazarSync AI

Bangla-first AI commerce intelligence for marketplace sellers.

BazarSync AI helps sellers monitor products, competitors, pricing, inventory, revenue, dead stock, promotions, alerts, and business memory from one dashboard. The backend uses deterministic business services for financial and operational calculations, while the Copilot layer combines seller-scoped current data with RAG memory for grounded business answers.

> Production note: this repository is a full-stack application. Deploy the FastAPI backend, worker, PostgreSQL/pgvector database, Redis, and Vite frontend as separate production services unless your hosting platform explicitly supports the full stack.

## Contents

- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Repository Structure](#repository-structure)
- [Local Development](#local-development)
- [Environment Variables](#environment-variables)
- [Database and Migrations](#database-and-migrations)
- [AI Copilot and RAG Memory](#ai-copilot-and-rag-memory)
- [Telegram Alerts](#telegram-alerts)
- [Testing and Quality Gates](#testing-and-quality-gates)
- [Deployment](#deployment)
- [Security Notes](#security-notes)
- [Troubleshooting](#troubleshooting)

## Features

### Seller Dashboard

- Product catalog and marketplace listing management.
- Competitor monitoring, rankings, price events, and market opportunities.
- Inventory intelligence with stockout, reorder, aging, and risk workflows.
- Pricing analytics, MarginGuard checks, dynamic pricing recommendations, and marketplace fee policies.
- Sales import with transaction unit price, line total, status, currency, and sales coverage tracking.
- Revenue and estimated profit analytics with deterministic backend calculations.
- Dead-stock classification, capital recovery estimates, and recovery recommendations.
- Alerts, recommendations, and realtime dashboard activity.

### Universal AI Business Copilot

- Seller-scoped chat widget on dashboard pages.
- Dynamic planner for broad business questions.
- Allowlisted tools and allowlisted metric execution only.
- Hybrid answers from current database facts plus seller-scoped RAG memory.
- Evidence, confidence, missing-data, freshness, tool usage, and action proposal metadata.
- Action proposal flow for price changes, promotions, and reorder plans without live marketplace execution.
- Conversation hydration with rich assistant-message metadata.

### RAG Memory Layer

- Seller-scoped memory documents and chunks.
- Product, sales, inventory, pricing, competitor, recommendation, alert, promotion, and Copilot-history memory sources where implemented.
- pgvector-backed vector search with seller filtering.
- Bounded retrieval with deleted/stale document exclusion by default.
- Local BGE embedding support through SentenceTransformers.

### Notifications and Integrations

- Telegram connection and alert delivery.
- Product intelligence snapshots.
- Celery worker workflows for scheduled and event-driven intelligence jobs.
- Redis-backed async task queue.

## Architecture

```mermaid
flowchart TD
    UI["React + Vite Frontend"] --> API["FastAPI Backend"]
    API --> Auth["JWT Seller Auth"]
    API --> DB[("PostgreSQL + pgvector")]
    API --> Redis[("Redis")]
    Redis --> Worker["Celery Worker"]
    Worker --> DB
    API --> Groq["Groq API<br/>backend only"]
    API --> Telegram["Telegram Bot API"]

    subgraph Copilot["AI Business Copilot"]
      Planner["Question Planner"]
      Catalogs["Business + Metric Catalogs"]
      Tools["Allowlisted Tools"]
      Metrics["MetricExecutionService"]
      RAG["Seller-scoped RAG Retrieval"]
      Validator["Response Validator"]
    end

    API --> Planner
    Planner --> Catalogs
    Catalogs --> Tools
    Tools --> Metrics
    Tools --> RAG
    Metrics --> DB
    RAG --> DB
    Tools --> Validator
    Validator --> API
```

Copilot safety model:

```text
Seller question
  -> planner
  -> business data catalog + metric catalog
  -> allowlisted tools + MetricExecutionService
  -> seller-scoped deterministic analytics
  -> seller-scoped RAG memory retrieval
  -> hybrid answer engine
  -> evidence/confidence/missing-data validation
  -> frontend widget
```

The Copilot must not generate SQL, execute arbitrary SQL, expose the Groq key, directly mutate marketplace state, or bypass seller ownership checks.

## Tech Stack

### Backend

- Python 3.14
- FastAPI
- SQLAlchemy
- Alembic
- PostgreSQL with pgvector for RAG memory
- Redis
- Celery
- Socket.IO
- Groq SDK
- SentenceTransformers / BGE embeddings
- Playwright and scraping utilities

### Frontend

- React 19
- Vite 8
- TypeScript 6
- Tailwind CSS
- TanStack Query
- TanStack Table
- React Router
- Recharts
- Socket.IO client
- Vitest and Testing Library

## Repository Structure

```text
.
├── backend/
│   ├── alembic/                 # Database migrations
│   ├── app/
│   │   ├── api/                 # FastAPI routes
│   │   ├── core/                # Config, security, Celery, Socket.IO
│   │   ├── db/                  # Database session and vector helpers
│   │   ├── models/              # SQLAlchemy models
│   │   ├── repositories/        # Data-access helpers
│   │   ├── schemas/             # Pydantic schemas
│   │   ├── services/            # Business services and Copilot/RAG logic
│   │   ├── tasks/               # Celery tasks
│   │   └── main.py              # FastAPI app entrypoint
│   ├── scripts/                 # Local operational scripts
│   └── tests/                   # Backend test suite
├── frontend/
│   ├── src/
│   │   ├── components/          # UI components
│   │   ├── hooks/               # React Query and UI hooks
│   │   ├── pages/               # Route pages
│   │   ├── routes/              # Router and nav config
│   │   ├── services/            # API clients
│   │   ├── types/               # Frontend types
│   │   └── utils/               # Formatters and helpers
│   └── package.json
├── docs/                        # Phase notes and implementation summaries
├── docker-compose.yml
└── README.md
```

## Local Development

### Prerequisites

- Python 3.14
- Node.js compatible with the frontend lockfile/environment
- npm
- PostgreSQL
- pgvector extension for RAG features
- Redis
- Optional: Telegram bot token
- Optional: Groq API key

### 1. Clone and configure

```bash
git clone https://github.com/DevNexus09/BazarSync-AI.git
cd BazarSync-AI
cp .env.example .env
```

Set at least these backend values in `.env`:

```env
APP_ENV=development
DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@localhost:5432/bazarsync_ai
JWT_SECRET_KEY=replace_with_a_long_random_secret
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
```

### 2. Start Redis

```bash
redis-server
```

Or with Docker:

```bash
docker compose up -d redis
```

### 3. Backend setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python scripts/check_local_setup.py
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Useful backend URLs:

- `http://127.0.0.1:8000`
- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/api/v1/health`

### 4. Celery worker

In a second terminal:

```bash
cd backend
source venv/bin/activate
celery -A app.core.celery_app:celery_app worker --loglevel=info
```

### 5. Frontend setup

In a third terminal:

```bash
cd frontend
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

## Environment Variables

Use `.env.example` as the source of truth. Important groups are listed below.

### Core Backend

| Variable | Required | Notes |
| --- | --- | --- |
| `APP_ENV` | Recommended | `development`, `test`, or production environment name. |
| `DATABASE_URL` | Yes | SQLAlchemy database URL. |
| `JWT_SECRET_KEY` | Yes | Backend-only signing key. Use a long random value. |
| `JWT_ALGORITHM` | No | Defaults to `HS256`. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | Defaults to `60`. |
| `CORS_ORIGINS` | Production | Comma-separated allowed frontend origins. |
| `DB_BOOTSTRAP_ON_STARTUP` | No | Development helper. Prefer migrations in production. |

### Frontend

| Variable | Required | Notes |
| --- | --- | --- |
| `VITE_API_BASE_URL` | Yes | Public FastAPI API base URL, usually ending in `/api/v1`. |

Never define `VITE_GROQ_API_KEY`, `VITE_SUPABASE_KEY`, or any frontend variable containing backend credentials.

### AI and RAG

| Variable | Required | Notes |
| --- | --- | --- |
| `GROQ_API_KEY` | For Groq features | Backend-only. |
| `GROQ_MODEL` | No | Default non-RAG Groq model. |
| `RAG_ENABLED` | No | Enables authenticated RAG endpoint. |
| `RAG_GROQ_MODEL` | For RAG answers | Model used by grounded RAG answer generation. |
| `RAG_EMBEDDING_PROVIDER` | No | Defaults to `local_bge`. |
| `RAG_EMBEDDING_MODEL` | No | Defaults to `BAAI/bge-m3`. |
| `RAG_EMBEDDING_DEVICE` | No | `cpu`, `mps`, or supported accelerator. |
| `RAG_RETRIEVAL_TOP_K` | No | Bounded retrieval default. |
| `RAG_MIN_SIMILARITY` | No | Retrieval threshold. |

### Redis and Celery

| Variable | Required | Notes |
| --- | --- | --- |
| `REDIS_URL` | Recommended | Redis connection URL. |
| `REDIS_BROKER_URL` | Recommended | Celery broker URL; falls back to `REDIS_URL`. |
| `SCRAPER_SCHEDULE_ENABLED` | No | Enables scheduled scraper jobs. |
| `RAG_MEMORY_SCHEDULE_ENABLED` | No | Enables scheduled memory indexing. |
| `INVENTORY_INTELLIGENCE_SCHEDULE_ENABLED` | No | Enables scheduled inventory jobs. |
| `DEAD_STOCK_WORKFLOW_SCHEDULE_ENABLED` | No | Enables scheduled dead-stock workflows. |

### Password Reset Email

| Variable | Required | Notes |
| --- | --- | --- |
| `PASSWORD_RESET_ENABLED` | No | Defaults to enabled. |
| `PASSWORD_RESET_CODE_SECRET` | Production | Required outside development/test. |
| `EMAIL_PROVIDER` | Production | Use `smtp` outside local development. |
| `SMTP_HOST` | Production | SMTP host. |
| `SMTP_FROM_EMAIL` | Production | Sender address. |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | As needed | SMTP credentials. |

### Telegram

| Variable | Required | Notes |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | For Telegram | Bot token from BotFather. |
| `TELEGRAM_WEBHOOK_URL` | Production webhook | Public HTTPS URL ending in `/api/v1/telegram/webhook`. |
| `TELEGRAM_WEBHOOK_SECRET` | Recommended | Telegram secret token validation. |

## Database and Migrations

Run migrations from `backend/`:

```bash
source venv/bin/activate
python -m alembic upgrade head
```

Validate latest migration reversibility when changing schema:

```bash
python -m alembic downgrade -1
python -m alembic upgrade head
```

RAG memory requires PostgreSQL pgvector. The migration attempts Supabase's extension schema first:

```sql
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
```

If unavailable, local PostgreSQL can use:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Use a pgvector-enabled PostgreSQL image or install pgvector for your local PostgreSQL version before running RAG migrations.

## AI Copilot and RAG Memory

The Copilot is designed around production safety rules:

- Seller identity comes from backend authentication context.
- Product-specific actions require product ownership checks.
- Groq never queries the database directly.
- Groq does not generate SQL.
- Arbitrary SQL is not accepted by Copilot.
- Only registered tools and registered metrics can execute.
- Financial calculations are deterministic backend calculations.
- Revenue uses transaction unit price or line total where available.
- Profit is blocked or marked partial when cost or marketplace fee policy is missing.
- Direct current data overrides stale memory.
- RAG memory retrieval is seller-filtered.
- Answers include evidence, confidence, missing data, freshness, tools, and domains when available.
- Marketplace changes are proposals only unless a separate execution layer is explicitly implemented and tested.

Core backend modules:

- `backend/app/services/copilot/question_planner.py`
- `backend/app/services/copilot/tool_registry.py`
- `backend/app/services/copilot/metric_catalog.py`
- `backend/app/services/copilot/metric_execution_service.py`
- `backend/app/services/copilot/hybrid_answer_engine.py`
- `backend/app/services/copilot/copilot_response_validator.py`
- `backend/app/services/rag_retrieval_service.py`
- `backend/app/services/rag_memory_document_builder.py`
- `backend/app/repositories/rag_memory_repository.py`

Main endpoints:

- `POST /api/v1/copilot/ask`
- `GET /api/v1/copilot/conversations`
- `GET /api/v1/copilot/conversations/{conversation_id}`
- `GET /api/v1/copilot/tools`
- `POST /api/v1/rag/ask`
- `GET /api/v1/rag/coverage`

## Telegram Alerts

Telegram support includes connection management, alert delivery, and product intelligence snapshots.

Product snapshot endpoint:

```text
POST /api/v1/telegram/send-product-snapshot
```

Example:

```bash
curl -X POST http://localhost:8000/api/v1/telegram/send-product-snapshot \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"product_id":"PRODUCT_UUID"}'
```

If `TELEGRAM_WEBHOOK_URL` is configured, the backend registers the webhook on startup.

## Testing and Quality Gates

### Backend

Run from `backend/`:

```bash
source venv/bin/activate
pytest -q
pytest tests/api/test_copilot.py tests/api/test_rag.py -q
pytest tests/test_copilot_*.py -q
pytest tests/unit/rag tests/integration/rag -q
```

Optional quality checks if installed/configured:

```bash
ruff check .
ruff format --check .
mypy app
```

### Frontend

Run from `frontend/`:

```bash
npm run lint
npm run typecheck
npm test -- --run
npm run build
```

Current known frontend lint warning: TanStack Table can trigger a React Compiler `react-hooks/incompatible-library` warning in the dashboard competitor table. It is a warning, not a build failure.

## Deployment

### Recommended Production Services

- Frontend static app: Vercel, Netlify, Cloudflare Pages, or equivalent.
- Backend API: container platform, VM, Railway/Fly/Render, ECS, or equivalent.
- PostgreSQL with pgvector.
- Redis.
- Celery worker process.
- Optional Celery beat process if scheduled jobs are enabled.

### Backend Deployment Checklist

1. Set `APP_ENV` to the production environment name.
2. Set strong `JWT_SECRET_KEY` and `PASSWORD_RESET_CODE_SECRET`.
3. Set production `DATABASE_URL`.
4. Ensure pgvector is available before RAG migrations.
5. Run `alembic upgrade head`.
6. Set `CORS_ORIGINS` to the real frontend origin.
7. Set Redis variables for Celery.
8. Configure `GROQ_API_KEY` only on the backend if AI answer generation is enabled.
9. Configure SMTP if password reset is enabled.
10. Configure Telegram webhook variables if Telegram is enabled.
11. Run backend tests and migration downgrade/upgrade validation before release.

### Frontend Deployment Checklist

1. Set `VITE_API_BASE_URL` to the public backend API base URL.
2. Do not set backend secrets as `VITE_*` variables.
3. Run `npm run lint`, `npm run typecheck`, `npm test -- --run`, and `npm run build`.
4. Deploy the generated `frontend/dist` output.

### Docker Compose

The included `docker-compose.yml` provides backend API, worker, and Redis services. It does not replace a production PostgreSQL/pgvector plan.

```bash
docker compose up --build
```

## Security Notes

- Frontend currently stores JWTs in `localStorage`. For production, prefer httpOnly secure cookies or another mitigated token strategy, and enforce a strong CSP.
- Groq and SMTP credentials must remain backend-only.
- Do not expose Supabase service keys, database URLs, embeddings, raw prompts, or internal stack traces to the frontend.
- Use migrations for schema changes in production. Avoid startup bootstrapping in multi-instance deployments.
- Keep seller isolation enforced in every service and query path.
- Marketplace mutations must stay behind explicit, tested execution layers. Copilot approval currently represents internal proposal approval, not live marketplace execution.
- Validate all uploaded/imported business data before analytics use.

## Troubleshooting

### Redis connection refused

If Celery fails with:

```text
Error 61 connecting to localhost:6379. Connection refused.
```

Start Redis:

```bash
redis-server
```

or:

```bash
docker compose up -d redis
```

### pgvector migration failure

Install pgvector or use a pgvector-enabled PostgreSQL image, then rerun:

```bash
cd backend
source venv/bin/activate
python -m alembic upgrade head
```

### Groq unavailable or missing key

The backend should return safe fallback behavior for supported endpoints. Set:

```env
GROQ_API_KEY=...
RAG_GROQ_MODEL=openai/gpt-oss-120b
```

Only set these on the backend.

### Frontend cannot reach backend

Check:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
```

Then restart the Vite dev server.

## License

No license file is currently included in this repository. Add a license before publishing or distributing the project publicly.
