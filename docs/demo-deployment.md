# Public demo deployment (free tier)

The free demo runs on three services:

- **Frontend:** Vercel.
- **Backend:** one Azure for Students VM running the API, one Celery worker, Redis and Caddy.
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

The Alembic history starts from tables that already existed, so `alembic upgrade head` cannot
build an empty database. Copy the schema from your migrated local database instead, then seed.

1. Create a free Neon project in **AWS US East 1**, near the backend server. Turn
   connection pooling off and copy the connection string.
2. Remove the `?sslmode=require&channel_binding=require` suffix. Both psycopg2 and asyncpg
   negotiate TLS by default, and asyncpg rejects those query parameters.
3. Make sure your local database is current. From `backend/`, in a terminal where
   `DATABASE_URL` is **not** exported:

```bash
PYTHONPATH=. venv/bin/alembic upgrade head
```

4. Dump the local schema only. This copies no data or accounts:

```bash
/opt/homebrew/opt/postgresql@17/bin/pg_dump --schema-only --no-owner --no-privileges "$(grep -E '^DATABASE_URL=' .env | cut -d= -f2-)" > /tmp/bazarsync-schema.sql
```

5. Point this terminal at Neon:

```bash
export DATABASE_URL='postgresql://USER:PASSWORD@HOST/neondb'
```

6. Load the schema, then record the migration version:

```bash
/opt/homebrew/opt/postgresql@17/bin/psql "$DATABASE_URL" -q -v ON_ERROR_STOP=1 -f /tmp/bazarsync-schema.sql
```

```bash
PYTHONPATH=. venv/bin/alembic stamp head
```

7. Seed the demo store:

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

8. Embed the Copilot memory. This takes about 15–30 minutes on an M-series Mac. Without it,
   the Copilot answers "not enough seller-specific history":

```bash
PYTHONPATH=. venv/bin/python -c "
from app.tasks.rag_memory_tasks import rag_embed_pending_chunks as t
while True:
    r = t(limit=200); print(r['embedded_count'], 'embedded,', r['failed_count'], 'failed')
    if not r['embedded_count']: break"
```

9. Clean up:

```bash
unset DATABASE_URL DEMO_SELLER_PASSWORD; rm /tmp/bazarsync-schema.sql
```

## 2. Backend (Azure for Students VM)

One Azure VM runs the stack in `deploy/demo/`: the API, one Celery worker, Redis and Caddy.
Caddy gets a free HTTPS certificate for the VM's Azure DNS name. Azure for Students needs no
credit card. Its $100 credit covers about 2–3 months of a `Standard_B2s` VM. Stopping
(deallocating) the VM in the portal pauses the compute charges.

1. Activate Azure for Students with your university email.
2. On your Mac, create an SSH key:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/azure_bazarsync -C bazarsync-demo
```

3. Create the VM with these settings:
   - Ubuntu Server 24.04 LTS x64, size `Standard_B2s`, region **East US** (near Neon)
   - user `azureuser` with the key from `~/.ssh/azure_bazarsync.pub`
   - inbound ports 22, 80 and 443
   - a 64 GB Standard SSD

   Then, on its public IP, set the DNS name label `bazarsync-demo`. That gives
   `bazarsync-demo.eastus.cloudapp.azure.com`.
4. On the VM, add swap (the B2s has 4 GB of RAM) and install Docker:

```bash
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile && echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 rsync && sudo usermod -aG docker azureuser
```

5. From the repo root on your Mac, create the folders on the VM, then copy the code:

```bash
ssh -i ~/.ssh/azure_bazarsync azureuser@DOMAIN "mkdir -p ~/bazarsync/backend ~/bazarsync/deploy/demo"
```

```bash
rsync -az --delete -e "ssh -i ~/.ssh/azure_bazarsync" --exclude .git --exclude .DS_Store --exclude venv --exclude tests --exclude artifacts --exclude __pycache__ --exclude .env --exclude dump.rdb --exclude celerybeat-schedule --exclude graphify-out --exclude .mypy_cache --exclude .pytest_cache --exclude .ruff_cache backend/ azureuser@DOMAIN:~/bazarsync/backend/
```

```bash
rsync -az -e "ssh -i ~/.ssh/azure_bazarsync" --exclude .env deploy/demo/ azureuser@DOMAIN:~/bazarsync/deploy/demo/
```

6. From `backend/` on your Mac, write the settings file and copy it to the VM. The script asks
   for the Neon URL, generates a JWT secret and never prints secrets:

```bash
PYTHONPATH=. venv/bin/python ../deploy/demo/make_env.py --domain DOMAIN
```

```bash
scp -i ~/.ssh/azure_bazarsync ~/bazarsync-demo.env azureuser@DOMAIN:~/bazarsync/deploy/demo/.env
```

7. On the VM, build and start. The first build takes 15–30 minutes:

```bash
cd ~/bazarsync/deploy/demo && docker compose up -d --build
```

8. Check `https://DOMAIN/api/v1/health`.

To update the backend, repeat step 5, then run `docker compose up -d --build` on the VM. To
change settings, repeat step 6, then run `docker compose up -d`.

## 3. Frontend (Vercel)

Import the repository with **Root Directory** `frontend` and set:

- `VITE_API_BASE_URL=https://DOMAIN/api/v1`

Then repeat backend step 7 with `--frontend https://YOUR-APP.vercel.app` and run
`docker compose up -d` on the VM, so the API accepts requests from the site.

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
