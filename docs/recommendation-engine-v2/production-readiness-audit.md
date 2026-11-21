# Recommendation Engine 2.0 production-readiness audit

Audited Phases 1–5 on 20 November 2026 against the current working tree.

**Deployment decision is NO-GO.** The recommendation workflow and its safeguards passed the executed integration checks. Fresh installation, the full backend quality gates, production model evidence and target-container verification remain unresolved. Experimental ML remains disabled. [Machine-readable results and chronological replay](artifacts/production-readiness-audit.json)

## Executed checks

| Area | Status | Executed result |
| --- | --- | --- |
| Complete backend tests | FAIL | 1,038 passed, 809 subtests passed, 24 failed, three skipped. All 24 failures match the previous Phase 5 Copilot failure set. |
| Complete frontend tests | PASS | 108 passed across 23 files. |
| Frontend lint, typecheck and production build | PASS | All three commands completed successfully. |
| Scoped backend lint and types | PASS | Ruff passed on the reviewed forecasting, recommendation, financial-safety, explanation and native-runtime modules. Mypy passed across 28 service/schema modules with follow-imports=silent and ignore-missing-imports. |
| Whole application backend lint and types | FAIL | Ruff reported 36 findings in app. Mypy reported 333 errors in 89 files across 371 checked source files. |
| Backend compilation and installed dependencies | PASS | compileall completed for app and scripts. pip check reported no broken requirements. |
| Native CatBoost environment | PASS locally | CPython 3.14.4 ARM64, CatBoost 1.2.10, NumPy 2.4.6, pandas 3.0.3 and SciPy 1.17.1 passed the CPU smoke check. |
| Saved-model loading and prediction | PASS locally | All three CBMs loaded and predicted through the isolated native subprocess. Five predictions per horizon matched the training loader. |
| Artifact integrity and fallback | PASS | Corrupted active artifacts selected the previous release, then the statistical baseline after the previous artifact was removed, at 7, 14 and 30 days. Unit/integration tests also covered absent registries, invalid hashes, scope, unsupported versions, timeout, concurrency, insufficient data and cold start. |
| Chronological holdout evaluation | FAIL for model promotion | CatBoost failed to improve MAE over matched statistical baselines at every horizon. All releases retained baseline status. |
| Fresh database migration | FAIL | Alembic upgrade head failed at existing root revision 9ba821df6da5 because competitors does not exist. |
| Additive upgrade of representative existing schema | PASS | i3c4d5e6f7a8 → l6f7a8b9c0d1, downgrade and re-upgrade completed. Historical recommendation API output stayed identical. |
| Browser → API → broker → worker → database → display | PASS | Real signed authentication, PostgreSQL, isolated Redis, separate Celery solo worker and production frontend bundle completed with seeded fixtures and a forced Groq timeout. |
| Container image build and Linux memory limits | UNVERIFIED | Docker and Podman are unavailable in this workspace. |

The three skipped tests require the optional StatsForecast package. Built-in statistical fallback, native CatBoost and PostgreSQL historical export tests executed. Optional Croston/TSB/ADIDA integration was not rerun in a separate installation during this audit.

## Workflow and safety review

The audit followed historical sales/coverage and inventory reads, Task 9 feature snapshots, statistical and approved native inference, specialized candidate adapters, DecisionOrchestrator, action evaluation, final MarginGuard checks, recommendation/job/RAG persistence, Groq explanation, authenticated job/latest APIs, React Query and the seller dashboard.

| Requirement | Verified behavior |
| --- | --- |
| Historical evidence | Completed business dates, source timestamps, coverage, transaction-price provenance and unavailable-versus-zero rules remain explicit. Historical export replay ran against a separate disposable database. Live capture uses read-only, repeatable-read transactions and statement timeouts. |
| MarginGuard | Exact price candidates retain applicable policy, fee, currency, unit-cost, margin, profit, change-limit and increment checks. Orchestration refreshes economic/inventory inputs before final selection. Rejected alternatives remain in evidence. Missing fees and stale evidence block actionable prices in the guarded path. |
| Pricing and recovery evidence | With the relevant Phase 5 flags enabled, baseline demand does not become price elasticity or promotion response. Unknown response leaves candidate quantities and expected uplift unavailable. Recovery financial outputs remain conditional quantity scenarios. |
| Reorder quantities | Tests covered reservations, confirmed incoming counted once, zero and intermittent demand, lead time, MOQ, pack size, capacity, budgets and unsupported forecasts. Model/demand changes produce a fresh plan revision, while recapture and replay remain idempotent. |
| LLM boundary | The Phase 5 explanation path accepts approved Bangla sentences and supplied metric references. Pydantic validation rejects contradictory actions, unsupported values, extra fields and injected instructions. Important numbers are rendered from validated fields. |
| Groq availability | Missing credentials, invalid JSON, unsupported claims and timeout preserve deterministic Bangla templates. Recommendation, durable completion and the initial outbox commit before optional provider work. Actual external Groq availability and successful live-provider latency were not tested. |
| Durable work | Tests exercised simultaneous submissions, replayed request keys, duplicate deliveries, broker failure, interrupted leases, fenced attempts, visible expiry, transient/permanent failures, database rollback, retry and optional RAG failure. Terminal job polling stops. |
| Seller isolation | API and worker tests reject foreign product/job access. Forecast registries, snapshots, records, caches and outbox state retain seller scope. The browser run used actual signed seller authentication. |
| Compatibility | Legacy and v2 frontend payloads, old snapshots, specialized histories, status transitions and rollback paths passed regression checks. New evidence fields remain additive. |
| Marketplace effects | Generation, explanations and acknowledgment remain advisory. The browser run left product price and stock unchanged. No price, promotion or purchase-order publication was exercised. |

These guarantees apply to their enabled validation/orchestration/Phase 5 paths. Legacy rollback preserves the original heuristic estimates and free-text explanation contract. It does not confer calibrated elasticity, causal promotion response or structured factual validation on historical legacy outputs.

## End-to-end fixture result

The production frontend bundle ran against real recommendation and product routes backed by a disposable PostgreSQL schema and a separate Redis/Celery process. Approved-model inference was disabled for this run, exercising supported sales fallback without a model. The optional Groq call was forced to time out after persistence.

The product had 30 on-hand units, five reserved units and four confirmed incoming units. Available stock was 25 and inventory position was 29. The recorded-sales planning target was 57. The raw order was 28 units, which became 30 after pack-size rounding with MOQ 12 and pack size six. The dashboard displayed REORDER, the verified Bangla quantity, timestamps, supporting listing advice, unknown price response and unavailable forecast horizons.

Repeating the request key left one recommendation, one job and one RAG outbox row. The completed job stopped interval polling. Chrome checks at 375px and 1280px passed mobile stacking, desktop columns, horizontal-overflow and keyboard disclosure checks. Redis publication succeeded. Live Socket.IO browser delivery was not part of this harness, while frontend hook tests covered final-explanation invalidation and seller cache scope.

The fixture harness was temporary and made no external LLM or marketplace requests. Separately, permanent API tests exercised approved forecast fixtures, constrained reorder quantities and forged LLM claims. The full test run also revalidated the earlier reorder revision and final-explanation refresh fixes.

## Forecast evaluation and resource evidence

The existing phase4_release_fixture.py script was executed again. It trained CPU-only CatBoost models from archived synthetic snapshots, preserved chronological boundaries and lineage, and evaluated frozen models against matched statistical baselines on untouched later dates. Its registry approval was simulated inside a temporary model-loading fixture. It was never published as a seller release.

| Horizon | CatBoost MAE | Best matched baseline | Baseline MAE | Independent holdout origins | Result |
| --- | ---: | --- | ---: | ---: | --- |
| 7 days | 8.8211 | Auto / moving average tie | 0.0000 | 2 | Baseline retained |
| 14 days | 18.0098 | Regime fallback | 0.1615 | 2 | Baseline retained |
| 30 days | 38.5923 | Regime fallback | 0.3462 | 2 | Baseline retained |

All scores describe synthetic fixtures. Two independent origins are below the runtime approval gate of three, and MAE improvement is absent. The configured local database was inspected in a read-only transaction and has one product and zero sales, sales-coverage, inventory-history and product-price-history rows. Real seller accuracy remains unmeasured.

The separate later interval replay again covered one of three outcomes per horizon at nominal 90% coverage for both CatBoost and the statistical path. Those bounds remain empirical and unvalidated. They cannot be advertised as calibrated stockout probabilities.

| Horizon | Local median call time | Local maximum call time | Synthetic model size |
| --- | ---: | ---: | ---: |
| 7 days | 912.03 ms | 1,027.36 ms | 14,528 bytes |
| 14 days | 1,038.36 ms | 2,123.40 ms | 16,416 bytes |
| 30 days | 1,492.11 ms | 2,357.86 ms | 20,768 bytes |

The maximum child RSS was 145.94 MiB on macOS ARM64. These observations include process startup, loading and prediction, with other audit tests running on the host. They do not establish production capacity. Default native limits are five wall seconds, four CPU seconds, 1,024 MiB address space on Linux, 32 MiB artifacts and one concurrent native call per service instance. The optional inference container declares a 768 MiB memory ceiling. Parent/API memory, Celery process count, representative artifact size and Linux cgroup peaks remain unmeasured.

## Migrations and historical records

Fresh-install migration failed at the existing root migration's ALTER TABLE competitors operation. No migration was rewritten, no existing database was reset and no production stamp was applied.

The additive upgrade check used a constructed representative pre-v2 schema in a separate disposable database. It seeded a legacy flat-context recommendation and competitor snapshot, removed the three v2 snapshot columns, and stamped only that test schema to i3c4d5e6f7a8. Upgrade to head added nullable observation/match fields and the durable job tables, including their active-job unique index. Legacy recommendation API serialization stayed identical. Downgrade and re-upgrade retained that legacy row and output.

This establishes the additive revisions' behavior on that fixture. An upgrade rehearsal against the actual deployment database backup remains unverified. Fresh installation remains blocked by the original migration baseline.

## Configuration, secrets and containers

The inspected application settings and example defaults keep all experimental recommendation/ML flags off. The current forecast mode is disabled. Flags load at process startup, so API and worker settings need to be applied consistently when selecting the guarded path or rollback. Existing tests covered disabling orchestration and the pricing, reorder, recovery and dashboard enhancements while keeping old records readable.

Required database/JWT configuration remains backend-only. Groq credentials are optional to the template path. Local credential presence and JWT length were checked without printing values. No Groq token/private-key patterns were found in tracked or upgrade source, and the actual local Groq/JWT values were absent from the built frontend bundle. Dotenv files are not tracked. These checks do not establish production credential rotation, entropy or access control.

The one build-safety change is backend/.dockerignore. The standard web/worker Dockerfile uses COPY with the backend build context, which contains a local .env. The new ignore file excludes dotenv files, local virtual environments, bytecode and caches from that context. The dedicated training/inference Docker ignore files already use explicit allowlists. Source checks passed. Actual image-layer inspection is unverified because a container runtime is unavailable.

The existing standard image uses a floating Playwright base tag, while training and inference pin CPython 3.14.4. The standard web/worker image was not built or proven to use the tested interpreter. Its requirements also leave versions unpinned. The native interpreter used by an enabled worker must be available at its configured local absolute path. The optional standalone forecast container is not an automatic RPC connection from the worker. That target deployment wiring remains unverified.

The supplied development Compose file publishes Redis on host port 6379 and supplies no Redis authentication setting. Production network restriction and Redis authentication/TLS need deployment-specific verification. They were not inferred from the isolated local test broker.

For full application startup, the current async database URL adapter recognizes plain postgresql://, postgres:// and postgresql+asyncpg:// forms. A migration-harness attempt that imported application services with an explicit postgresql+psycopg2:// URL failed its async-driver initialization. The representative upgrade then passed using the supported plain PostgreSQL form. Audit fixture URLs remain separate from deployment settings.

## Blocking risks and limits

1. Fresh installation cannot reach Alembic head from an empty database.
2. The complete backend suite retains 24 Copilot failures, including proposal safety assertions. The exact test-name set matches the preceding Phase 5 audit. Whole-application financial safety cannot be certified through this failing gate.
3. Whole-application lint and type checks fail. Unchanged baseline code includes a missing return in the inventory-history route and unreachable references flagged by Ruff. This audit preserved unrelated routes and bulk formatting/type behavior.
4. CatBoost has no supported seller release. Synthetic holdouts retain baselines, sample support is insufficient, local historical data is absent and intervals fail the replay coverage check.
5. Linux image builds, current dependency installation on the target architecture, worker/native-interpreter wiring, representative memory/concurrency and production network/credential controls remain unverified.

The frontend build retains CSS @theme/@utility minification warnings, stale Browserslist data and a large output chunk. Node tests retain the experimental localStorage warning. Backend tests report the existing HTTP 422 constant deprecation warning. These warnings did not fail their respective commands.

No additional recommendation-runtime regression was found in the executed checks. The build-context exclusion is the only implementation change in this audit. No model was activated and no deployment was performed.

## Reproduction

Run frontend lint, typecheck, test and build from frontend using the existing npm scripts. Run backend tests from backend with disposable PostgreSQL/Redis URLs. This audit supplied BAZARSYNC_TEST_POSTGRES_URL for the unique-schema recommendation fixtures, BAZARSYNC_TEST_REDIS_URL for an isolated Unix-socket Redis instance with persistence disabled, and BAZARSYNC_HISTORICAL_TEST_POSTGRES_URL for a separate disposable database.

The forecasting replay command ran from backend.

```sh
PYTHON_DOTENV_DISABLED=1 PYTHONPATH=.:tests \
venv/bin/python tests/phase4_release_fixture.py
```

The archived JSON contains the actual replay output, native versions/timings, lineage and summarized check outcomes. It contains synthetic fixture evidence and no production credentials. Temporary test databases, broker and worker processes were cleaned up after verification.
