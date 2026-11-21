# BazarSync AI engineering contract

BazarSync AI is an existing FastAPI, SQLAlchemy, Celery, PostgreSQL and React application. Read the affected routes, schemas, models, migrations, workers, UI callers and tests before changing behavior. Check Git status first and preserve unrelated work. For recommendation changes, start with the [architecture baseline](docs/recommendation-engine-v2/architecture-baseline.md), [compatibility contract](docs/recommendation-engine-v2/compatibility-contract.md) and [implementation progress](docs/recommendation-engine-v2/implementation-progress.md).

## Recommendation work

- Derive seller identity from authenticated context. Verify ownership at API and worker boundaries and scope all reads, writes, caches, events and RAG operations to the seller.
- Preserve existing routes, response contracts, recommendation history and specialized pricing, inventory, reorder and dead-stock workflows. Use additive migrations and keep older rows readable. Never reset a database or destroy records to migrate.
- Reuse existing typed service and repository patterns. Use Decimal for money, preserve units and currency, and distinguish unavailable evidence from observed zero. Record source, freshness, calculation version and assumptions for new outputs.
- Apply MarginGuard to the exact price candidate with its applicable marketplace policy and fee data. Keep deterministic decisions authoritative and limit the LLM to explaining verified evidence. Recommendation generation and acknowledgment must never change live marketplace price or stock.
- Gate major changes behind explicit, default-off feature flags. Keep training and out-of-time evaluation outside request handlers. Confirm Python 3.14 and deployment image compatibility before adding dependencies.
- Use atomic writes where needed, bounded network calls and retry-safe Celery execution. Correlate task attempts with durable outputs so redelivery cannot create duplicate business effects.
- For runtime changes, add targeted unit, integration and regression tests, including seller isolation, missing evidence, guard rejection and replay where applicable. Run relevant suites, lint and type checks, review the complete scoped diff and record actual outcomes and blockers.
