# Public demo deployment (free tier)

The free demo runs on three services:

- **Frontend:** Vercel.
- **Backend:** one Hugging Face Docker Space running the API, one Celery worker and Redis.
- **Database:** Neon Postgres.

Visitors click **Experience BazarSync** on the landing page. That calls `POST /api/v1/auth/demo`,
which signs them in as the seeded demo seller (`bazardemo@gmail.com`) with a restricted token.
Visitors never sign up or see a password.

## What a demo visitor can and cannot do

The demo token carries a `demo: true` claim. `app/core/demo_mode.py` checks every request that
uses it:

- **Reads:** every `GET` works, so all dashboards, products, competitors, inventory, pricing
  and recommendation history are visible.
- **Allowed writes:**
  - Copilot chat and message feedback.
  - RAG questions.
  - Recommendation generation.
  - Pricing recommendations, analytics, simulation and explanation.
  - Dead-stock recovery simulation and recalculation.
  - Minimum-safe-price preview.
  - The per-product inventory workflow.

  These only add rows and never change products, stock, policies or live marketplace prices.
- **Blocked writes (403):** product create, edit and delete; stock-in; sales import; scraping;
  pricing policy and fee changes; acknowledge, dismiss and mark-ordered; Copilot action
  approvals; profile changes; account deletion; Telegram.
- **Limits:**
  - 20 demo sessions per IP per hour.
  - 40 allowed writes per IP per hour.
  - 400 allowed writes per hour across all visitors, which protects the Groq free quota.

  Set them with the `DEMO_MAX_*` environment variables.

If the owner signs in to the same account with its password, the token is normal and has full
access.

## 1. Database (Neon)

1. Create a free Neon project and copy its connection string.
2. Remove the `?sslmode=require&channel_binding=require` suffix. Both psycopg2 and asyncpg
   negotiate TLS by default, and asyncpg rejects those query parameters.
3. From `backend/` on your machine, migrate and seed. Run the commands one at a time:

```bash
export DATABASE_URL='postgresql://USER:PASSWORD@HOST/DBNAME'
```

```bash
PYTHONPATH=. venv/bin/alembic upgrade head
```

```bash
read -s DEMO_SELLER_PASSWORD && export DEMO_SELLER_PASSWORD
```

```bash
PYTHONPATH=. venv/bin/python scripts/seed_demo_store.py --apply
```

```bash
PYTHONPATH=. venv/bin/python scripts/seed_comprehensive_demo.py --apply --as-of 2026-11-24 --skip-external-services
```

```bash
PYTHONPATH=. venv/bin/python scripts/seed_copilot_demo_extras.py --apply --as-of 2026-11-24
```

```bash
unset DATABASE_URL DEMO_SELLER_PASSWORD
```

## 2. Backend (Hugging Face Space)

1. Create a Space with SDK **Docker**, template **Blank** and the free **CPU basic** hardware.
   Use a private Space if you prefer; the API URL still works.
2. From `backend/`, copy the backend into the Space repository. Leave out local secrets and caches:

```bash
git clone https://huggingface.co/spaces/YOUR_USER/bazarsync-demo ../hf-space
```

```bash
rsync -a --delete --exclude .git --exclude venv --exclude tests --exclude artifacts --exclude __pycache__ --exclude .env --exclude dump.rdb --exclude celerybeat-schedule --exclude graphify-out --exclude .mypy_cache --exclude .pytest_cache --exclude .ruff_cache ./ ../hf-space/
```

```bash
cp ../deploy/huggingface/Dockerfile ../deploy/huggingface/start.sh ../deploy/huggingface/README.md ../hf-space/
```

   Then commit and push inside `../hf-space`.

3. In the Space **Settings → Variables and secrets**, add the following.

   Secrets:
   - `DATABASE_URL`: the Neon URL from step 1.
   - `JWT_SECRET_KEY`: a new random value, not your local one.
   - `GROQ_API_KEY`.

   Variables:
   - `APP_ENV=production`
   - `DEMO_MODE_ENABLED=true`
   - `CORS_ORIGINS=https://YOUR-APP.vercel.app`
   - `FRONTEND_URL=https://YOUR-APP.vercel.app`
   - `SCRAPER_SCHEDULE_ENABLED=false`
   - `INVENTORY_INTELLIGENCE_SCHEDULE_ENABLED=false`
   - `DEAD_STOCK_WORKFLOW_SCHEDULE_ENABLED=false`
   - The non-secret `RAG_*`, `COPILOT_*` and `GROQ_*_MODEL` values from your local `.env`.

   Do not set `TELEGRAM_*`, SMTP or OpenRouter keys.
4. Once it builds, open `https://YOUR_USER-bazarsync-demo.hf.space/api/v1/health`.

The free Space sleeps after about 48 hours without traffic. The first visit after that takes
about a minute while it wakes. The landing page tells visitors this after four seconds and
waits up to two minutes.

## 3. Frontend (Vercel)

Import the repository with **Root Directory** `frontend` and set:

- `VITE_API_BASE_URL=https://YOUR_USER-bazarsync-demo.hf.space/api/v1`

`frontend/vercel.json` already rewrites SPA routes.

## Check it

1. Open the Vercel URL and click **Experience BazarSync**. You should land on the dashboard
   with the demo banner.
2. Ask the Copilot a question and generate a recommendation.
3. Try to edit a product. It should fail with "disabled in the BazarSync demo".
4. **Exit demo** returns to the landing page. **Get Started** still uses normal login and
   sign-up.

## Turning it off

Set `DEMO_MODE_ENABLED=false`. `/auth/demo` then returns 404. Demo tokens already issued stay
restricted until they expire (`DEMO_TOKEN_EXPIRE_MINUTES`, default 120).
