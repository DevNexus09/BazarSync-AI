# Demo footwear data seeding

## Purpose and identity

The demo seed creates an independent development/test seller named **Demo Footwear Store**. It uses public Bata-store listings on Daraz Bangladesh only as catalog and opening-price references. The demo seller is not Bata, is not affiliated with Bata, and does not contain Bata private business data, addresses, registrations, credentials or wholesale costs.

The seed is an explicit CLI operation. It is not imported by application startup, Alembic, Celery initialization or deployment hooks. It sends no email, OTP, SMS, marketplace request, order, payment, promotion or notification.

## Safety model

- Dry-run is the default. Database writes require `--apply`.
- Writes are allowed only when `APP_ENV` is `development` or `test` and the configured PostgreSQL host is local (localhost, loopback or a Unix socket). There is no production override.
- The seed inspects `demo1@gmail.com` before writing. An existing account without the `demo_seed_records` ownership marker aborts the whole transaction.
- The password is read only from `DEMO_SELLER_PASSWORD`. It is hashed with the production bcrypt implementation and never printed. Reruns never reset it.
- Every seller/product/supporting batch is marked with `demo-footwear-store-v1`. Existing ordinary sellers, products and policies are not updated or deleted.
- The import is one database transaction. Manifest validation happens before persistence.
- `--update-managed-records` may update only products already owned by this seed. There is no global reset command.

Apply migration `m7a8b9c0d1e2` before database-backed dry runs or seeding:

```bash
cd backend
venv/bin/alembic upgrade head
```

The migration adds only `demo_seed_records`; it does not insert demo data.

## Catalog acquisition and manifest

The committed manifest is [demo_footwear_products.json](../backend/seed_data/demo_footwear_products.json). It contains 15 distinct footwear listings observed through BazarSync's authorized Daraz acquisition path on 20 November 2026 (Dhaka time). Each record has a stable listing ID, public listing URL, observed BDT price, timestamp, store identity, provenance, and an explicit missing-field list.

Unverified sizes, colors and materials remain `null`; ratings, review counts and sold counts are deliberately not imported. Concise descriptions are derived from listing titles rather than copied long-form descriptions.

Optional reacquisition is deliberately separate from seeding and produces review candidates, not a trusted manifest:

```bash
cd backend
DARAZ_SCRAPING_AUTHORIZED=true \
REDIS_BROKER_URL=redis://127.0.0.1:6379/0 \
PYTHONPATH=. venv/bin/python scripts/acquire_demo_footwear_candidates.py \
  --confirm-public-acquisition \
  --output /tmp/bata-candidates.json
```

If Daraz blocks or challenges acquisition, stop and manually verify a JSON manifest. Do not bypass the control and do not invent replacement listings.

## Commands

Validate without opening the database:

```bash
cd backend
PYTHONPATH=. venv/bin/python scripts/seed_demo_footwear_store.py --validate
```

Inspect the configured local database without changing it:

```bash
cd backend
PYTHONPATH=. venv/bin/python scripts/seed_demo_footwear_store.py --dry-run
```

Create or safely recognize the managed demo records. Enter the requested local value (`demo1622`) through the environment or a secure shell prompt; do not put it in a tracked file:

```bash
cd backend
read -s DEMO_SELLER_PASSWORD
export DEMO_SELLER_PASSWORD
PYTHONPATH=. venv/bin/python scripts/seed_demo_footwear_store.py --apply
unset DEMO_SELLER_PASSWORD
```

Optional deterministic sales history (150 closed business days):

```bash
cd backend
read -s DEMO_SELLER_PASSWORD
export DEMO_SELLER_PASSWORD
PYTHONPATH=. venv/bin/python scripts/seed_demo_footwear_store.py \
  --apply --with-synthetic-sales
unset DEMO_SELLER_PASSWORD
```

The optional sales use fixed seed `1622` and stable source references, so reruns do not duplicate them. They are operationally visible inside this demo seller, but their coverage source is `SYNTHETIC_DEMO_SEED`; historical forecasting marks `SYNTHETIC_DEMO_SALES` and rejects those rows as ML training labels. They must not be cited as real Daraz activity or forecast accuracy.

Use `--report /safe/local/path/report.json` to save the non-secret result. Rerun the same command safely; omit `--update-managed-records` to preserve any later manual product edits.

## Synthetic business assumptions

Public listings provide product identity, source store, public price, availability signal and image URL. The following fields are synthetic and seller-scoped:

- on-hand, reserved, incoming and inventory age scenarios;
- cost rates (56%–70% of opening selling price), lead times, safety stock, MOQ, pack size and maximum stock;
- a 12% minimum contribution-margin policy, BDT 10 minimum unit profit, 15%/20% change limits and BDT 1 increments;
- an assumed 8% commission plus 2% payment fee, labelled `SYNTHETIC_DEMO_ASSUMPTION`, not an official Daraz fee schedule;
- optional sales patterns and a BDT 0.50 holding-cost assumption.

The public Bata listing ID is stored as reference provenance in product specifications. It is not inserted as this independent seller's marketplace listing, and no competitor observation is fabricated.

## Comprehensive feature showcase

After this 15-product catalog exists, use
[comprehensive-demo-seeding.md](comprehensive-demo-seeding.md) to populate the
existing sales, inventory, competitor, promotion, pricing, recommendation,
dead-stock, and local RAG workflows.

## Login and verification

After an applied local seed, use the existing frontend login form with `demo1@gmail.com` and the password supplied through `DEMO_SELLER_PASSWORD`. Authentication uses the normal JWT path and seller-scoped APIs. Products should appear in the existing product and inventory views. Basic catalog seeding does not generate recommendations or call Groq/Celery. The comprehensive local seed runs deterministic workflows while keeping Groq, Copilot, embeddings, alerts, scraping, and marketplace operations explicitly separate.

## Troubleshooting and cleanup

- `demo_seed_failed ... table demo_seed_records`: apply the additive migration first.
- account conflict: do not rename, overwrite or reset the existing user. Use a different database or resolve ownership administratively.
- remote/production refusal: expected safety behavior; there is no casual override.
- fewer verified products after reacquisition: keep the verified shortfall and do not fabricate records.

No cleanup command is provided. If cleanup is required, implement a separately reviewed administrative operation that verifies `demo_seed_records` ownership and deletes only this seed's seller cascade. Never reset the database.
