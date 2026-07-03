# BazarSync AI Current Chat And Implementation Summary

Date: 2026-07-02

This document summarizes the main work discussed and implemented in the current Codex chat. It is intended as a practical handoff note for local development, testing, and future continuation.

## Project Stack Identified

- Backend: FastAPI, SQLAlchemy, Alembic, Celery, Redis, Socket.IO, PostgreSQL-compatible models and migrations.
- Frontend: Vite React with TypeScript, React Router, Tailwind CSS, TanStack Query, Axios API client.
- Authentication: Seller-scoped authenticated backend APIs.
- Background jobs: Celery tasks for scraper, competitor intelligence, inventory intelligence, pricing analytics, and related workflows.

## Phase 5: Competitor Intelligence

Implemented and iterated on competitor intelligence features:

- Competitor snapshot processing after scrape runs.
- Competitor event engine for:
  - PRICE_DROP
  - PRICE_RISE
  - OUT_OF_STOCK
  - BACK_IN_STOCK
  - NEW_COMPETITOR
  - COMPETITOR_REMOVED
- Competitor ranking system with score components:
  - Price score
  - Rating score
  - Review score
  - Availability score
  - Total score
  - Market rank
- Market opportunity engine.
- Phase 5 orchestration workflow.
- Redis and Socket.IO dashboard update delivery.
- Dashboard summary and feed APIs.
- Frontend competitor intelligence widgets.

Frontend changes requested and handled during the chat:

- Competitor intelligence card moved to the competitor page instead of the main dashboard.
- Competitor activity feed removed.
- Empty placeholder picture/card removed.
- Top 10 competitor card removed.
- Competitor score added into the competitor list.
- Competitor list ordered by ranking/score.
- Scrape button updated to show scraping state and success feedback.
- Phase 5 label text removed from the competitor intelligence header.
- Analytics page removed while keeping Pricing Analytics page.

## Phase 6: Inventory Intelligence

Implemented inventory intelligence foundations:

- Inventory history system.
- Sales velocity engine.
- Stockout prediction engine.
- Reorder recommendation engine.
- Inventory risk scoring.
- Telegram inventory alerts.
- Phase 6 daily orchestration workflow.
- Inventory intelligence summary APIs.
- Product-level inventory intelligence APIs.
- Reorder list and risk list APIs.

Key behavior:

- Inventory snapshots are immutable daily records.
- Sales velocity is based on valid completed or fulfilled sales, not page views or inventory decline.
- Stockout prediction uses inventory position and sales velocity.
- Reorder recommendations and risk assessments are versioned and auditable.
- Telegram alerts are deduplicated and respect cooldown logic.

## Phase 7: Pricing Policy, Analytics, And Recommendations

Implemented pricing intelligence foundations:

- Pricing policy and marketplace fee foundation.
- Deterministic pricing calculator.
- Margin protection layer.
- Pricing analytics snapshots.
- Demand-response estimation.
- Dynamic price recommendation service.
- Revenue simulation backend APIs.
- Groq-powered AI explanation backend support with safe fallback behavior.
- Frontend Revenue Simulator card added under the existing Pricing Analytics page.

Important pricing principles:

- No recommendation should bypass the margin guard.
- Missing cost, fee, currency, or policy data fails closed.
- Recommendations are not automatically applied.
- Historical analytics and recommendation records are preserved.
- Groq API key is used server-side only.

## Pricing Analytics Card Logic

The top Pricing Analytics card calls:

```http
POST /api/v1/products/{product_id}/pricing/simulate
```

Frontend source:

```text
frontend/src/services/pricing-simulator-service.ts
frontend/src/pages/pricing/pricing-page.tsx
```

Backend source:

```text
backend/app/api/v1/revenue_simulator.py
backend/app/services/revenue_simulator_service.py
backend/app/services/pricing_analytics_service.py
backend/app/services/margin_guard.py
backend/app/services/demand_response_service.py
```

### User Inputs

The card sends:

```json
{
  "candidate_prices": [405, 427.5, 450, 472.5, 495],
  "forecast_horizon_days": 30
}
```

### Backend Inputs Loaded Automatically

The backend also loads:

- Selected seller-owned product.
- Current product selling price.
- Product unit cost.
- Pricing policy.
- Marketplace fee policy.
- Latest pricing analytics snapshot, or generates one if missing.
- Latest sales velocity or demand estimate.
- Latest competitor scrape data when available.
- Latest inventory snapshot when available.
- Latest inventory risk when available.

### Main Simulation Formula

For each candidate price:

```text
expected_units =
baseline_units * (candidate_price / current_price) ^ elasticity
```

Then:

```text
expected_revenue = candidate_price * expected_units
expected_profit = unit_profit * expected_units
revenue_impact = expected_revenue - baseline_revenue
profit_impact = expected_profit - baseline_profit
```

### Baseline Units Selection

The backend chooses baseline demand in this order:

```text
1. pricing_analytics.recent_net_sales
2. pricing_analytics.daily_sales_rate * forecast_horizon_days
3. demand_response.baseline_units * forecast_horizon_days
4. null if none exists
```

### Margin Guard Checks

Each candidate price is validated before revenue/profit projection.

The margin guard checks:

- Product cost exists.
- Fee policy exists.
- Currency is supported.
- Candidate price is above minimum safe price.
- Unit profit is not negative.
- Margin is above minimum margin.
- Unit profit is above minimum unit profit.
- Candidate does not exceed maximum allowed price increase/decrease.
- Candidate matches marketplace price increment.
- Candidate is within absolute minimum and maximum price limits.

If a candidate fails the margin guard, the frontend displays it as blocked and does not project revenue or profit for that candidate.

### Best Scenario Logic

The frontend chooses the best allowed scenario by:

```text
1. Keeping only allowed scenarios.
2. Keeping only scenarios with expected profit.
3. Sorting by highest expected profit.
4. Showing the first result as the best allowed profit scenario.
```

## Recent Issue Fixed

Problem:

The Pricing Analytics page returned:

```text
422 Unprocessable Content
Pricing analytics snapshot is required before simulation.
```

Cause:

The simulator required an existing pricing analytics snapshot.

Fix:

The backend simulator now tries to generate a pricing analytics snapshot automatically when one does not exist.

Updated file:

```text
backend/app/services/revenue_simulator_service.py
```

Regression test added:

```text
backend/tests/test_revenue_simulator_service.py
```

Validation run:

```bash
cd backend
./venv/bin/python -m pytest tests/test_revenue_simulator_service.py tests/test_public_pricing_simulator_api.py
```

Result:

```text
9 passed
```

## Local Runtime Notes Discussed

Backend:

```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Celery worker:

```bash
cd backend
source venv/bin/activate
celery -A app.core.celery_app worker --loglevel=info
```

Redis must be running for Celery and real-time features.

## Telegram Webhook Note

The backend logs this when no Telegram webhook URL is configured:

```text
telegram_webhook_not_configured reason=missing TELEGRAM_WEBHOOK_URL
```

When using ngrok, set the webhook base URL in environment configuration using the ngrok HTTPS URL, for example:

```env
TELEGRAM_WEBHOOK_URL=https://batboy-thigh-extras.ngrok-free.dev
```

The exact webhook path should match the backend Telegram route if the application expects the full callback URL.

## Known Follow-Up Areas

- Verify all Alembic migrations upgrade and downgrade cleanly after the latest Phase 7 files.
- Confirm Redis is running before scraper, Celery, and Socket.IO tests.
- Confirm product records have valid `selling_price` and `cost_price`.
- Confirm pricing and fee policies exist for products before expecting full pricing analytics output.
- Confirm sales records contain enough usable data for historical elasticity; current fallback demand logic may be used when historical price observations are insufficient.
- Continue checking seller isolation for all newly added APIs.
