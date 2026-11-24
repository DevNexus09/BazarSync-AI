# Comprehensive demo seeding

The comprehensive seed augments the existing `bazardemo@gmail.com` seller
(Watch Wise - Choice) and its 25 products. It preserves product and seller IDs,
assigns products to the stable `P01`–`P25` scenario matrix by `(sku, id)`, and writes only local,
seller-scoped synthetic evidence. Synthetic marketplace URLs use
`https://demo.invalid/`; the command performs no scrape, marketplace update,
Telegram delivery, or external action.

## Safety

- The catalog seed must already have created the demo seller and exactly 25
  products. Run [the catalog seed](demo-data-seeding.md) first on a new local
  database.
- Writes are refused outside `development`/`test` and on non-local PostgreSQL
  hosts.
- `--apply` is required. Dry-run is the default.
- The fixed namespace `demo-comprehensive-v1`, deterministic source references,
  content hashes, run keys, and service uniqueness contracts make an identical
  `--as-of` run idempotent.
- External LLM and embedding execution is not claimed. Use
  `--skip-external-services` for the fully local path; RAG documents and chunks
  are created with truthful pending embedding state.

## Commands

From `backend/`:

```bash
PYTHONPATH=. venv/bin/python scripts/seed_comprehensive_demo.py \
  --apply \
  --email bazardemo@gmail.com \
  --as-of 2026-11-24 \
  --skip-external-services
```

Use the current Dhaka date by omitting `--as-of`. Use an explicit date for a
repeatable classroom demonstration.

Validate the current database without writing:

```bash
PYTHONPATH=. venv/bin/python scripts/seed_comprehensive_demo.py \
  --validate-only \
  --email bazardemo@gmail.com \
  --as-of 2026-11-24 \
  --skip-external-services
```

The command writes database-derived reports to:

- `backend/artifacts/comprehensive-demo-seed-report.json`
- `backend/artifacts/comprehensive-demo-seed-report.md`

Override either location with `--report` or `--markdown-report`.

## Pipeline

The command performs these dependency-ordered stages:

1. Resolve the existing demo seller and exactly 25 products.
2. Apply the centralized P01–P25 inventory, demand, pricing, and evidence
   scenarios without renaming products.
3. Reconcile 120 days of order lines (one line per Daraz order with a 15-digit
   order number, plus cancelled/failed-payment orders that are excluded) and coverage, PO-numbered receipts, 45 daily
   inventory snapshots, receipts, seller price history, completed promotion
   evidence, and one clearly synthetic scheduled promotion proposal.
4. Reconcile four completed synthetic competitor runs per product (five for
   the two continuity/insufficient-data boundary products).
5. Run the real competitor event, ranking, and opportunity services.
6. Run sales velocity, stockout, reorder, inventory risk, aging, dead-stock,
   recovery, and capital-recovery services, then create idempotent pending
   inventory alerts without attempting Telegram delivery.
7. Run pricing analytics, promotion-aware demand response, elasticity,
   MarginGuard, and dynamic-pricing services.
8. Build seller-scoped RAG documents/chunks through the existing backfill and
   chunking services.
9. Query the database for the JSON/Markdown coverage report.

General AI recommendations and Copilot conversations require their configured
providers. The local seed does not fabricate successful Groq answers, tool
calls, embeddings, or Copilot proposal execution. Existing generic
recommendations remain readable, while deterministic pricing, reorder, and
dead-stock recommendations are fully populated locally.

The report exposes these unavailable paths as zero counts. In the verified
local run, generic recommendation jobs, Copilot conversations/tool calls, and
embeddings were not executed; RAG chunks therefore remain truthfully
`PENDING`. Configure the providers and run their normal application workflows
to validate those external paths.

## Verification

```bash
PYTHONPATH=. venv/bin/pytest -q \
  tests/test_comprehensive_demo_seed.py \
  tests/test_product_inventory_history_route.py \
  tests/test_demand_response_service.py \
  tests/test_competitor_event_service.py \
  tests/test_dynamic_pricing_service.py
```

For idempotency, save the first JSON report, run the exact same apply command,
and compare the managed totals. Historical sales, inventory snapshots,
receipts, scrape runs/snapshots/events/rankings/opportunities, analytics,
recommendations, and active RAG document/chunk totals must show zero growth.

