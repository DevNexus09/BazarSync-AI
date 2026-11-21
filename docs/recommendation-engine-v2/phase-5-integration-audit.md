# Phase 5 integration audit

Audited Tasks 15–19 on 19 November 2026 against the current working tree.

The enabled Phase 5 recommendation path passed the checks below after two integration regressions were corrected. Whole-application verification is PARTIAL because the full backend suite still has 24 existing Copilot failures. Production model accuracy, external Groq service availability and the Linux deployment image remain outside the verified results.

## Corrections

### Reorder plans after a forecast change

The forecast-aware reorder revision originally fingerprinted product, inventory, sales and supplier settings while omitting the accepted forecast and computed planning result. An approved replacement could change a calculated order from 170 to 340 units while retaining the same revision. The repository would then return the previously saved plan.

The revision now includes demand source, forecast version, lead-time demand, uncertainty evidence, quantity, reorder point, target and insufficiency status. Forecast capture timestamps stay outside that identity. Tests prove stable replay after recapture and fresh publication when the supported demand changes. PostgreSQL tests verify the previous open recommendation expires, the replacement remains open, and replay creates no further row. Existing ordered records retain their lifecycle behavior.

### Final explanations on the dashboard

The dashboard preferred a cached completed-job result when its recommendation creation time equalled the latest API result. Optional Groq enhancement updates the same saved row, so a newer validated explanation could remain hidden.

Equal creation times now resolve using the fetch/update time of each query. The final recommendation event invalidates the authenticated seller's recommendation and durable-job queries. Other sellers' caches stay untouched. Terminal-state interval polling stays stopped. Regression tests cover both cache invalidation and display of a refreshed explanation for the same record.

### Backend type checks

The audit also resolved 14 type findings in the affected services. Database-backed pricing operations now obtain a required Session through a checked accessor. Pricing history returns its declared list type. Realtime dashboard insights are converted to their declared Pydantic payload type before serialization. Pure pricing calculations still support construction without a database.

## Safety and integration results

| Requirement | Result | Evidence and scope |
| --- | --- | --- |
| Exact-candidate MarginGuard | PASS for the recommendation paths | Candidate quotes check cost, effective fees, margin, unit profit, price bounds, change limits and increments. Final orchestration refreshes the product, inventory and pricing terms and checks exact selected prices again. Tests exercise missing fees, negative margins, changed fees, stale evidence and increment rounding. |
| Price response and elasticity | PASS with Task 15 enabled | Approved demand supplies a baseline stock-exposure signal. Historical associations retain variation and confounding evidence. Candidate response remains UNKNOWN, candidate units and expected economics remain unavailable, and pricing holds. |
| Promotion response | PASS with Task 17 enabled | Discount and flash-sale alternatives retain guard verdicts. Sales response remains unknown. Cash recovery and holding costs are deterministic scenarios with explicit quantities. Invalid and overlapping campaign outcomes cannot supply causal uplift. |
| Reorder arithmetic | PASS with Task 16 enabled | Available stock excludes reservations, confirmed incoming receives one credit, and quantities respect MOQ, pack, physical capacity, budget and planning limits. Missing evidence yields a limited recommendation. Approved demand and fallback demand retain separate provenance. |
| Forecast uncertainty | PASS | Unvalidated empirical intervals do not become calibrated intervals or stockout probabilities. The exact lead-time bound must satisfy its validation contract. Stockout probability remains unavailable. |
| LLM factual claims | PASS with Task 18 enabled | Strict Pydantic selection accepts only approved Bangla sentences and known metric keys. Numeric values are rendered from validated evidence. Forged numerical claims, contradictory wording and extra fields are rejected. Product injection text is excluded from the prompt. |
| Groq fallback and persistence | PASS | Missing keys, invalid output and timeout use a verified template. Recommendation, durable completion and initial RAG outbox commit before optional provider work. A real worker timeout test reached the frontend successfully. |
| Original specialized services | PASS in regression tests | Pricing, reorder, recovery, capital scenarios, status transitions, history and rollback tests passed in the full run. The generic orchestrator adapts their outputs without creating duplicate specialized records. |
| Historical records and API contracts | PASS | Public enums and reasoning_bn remain compatible. Old snapshots and specialized versions remain readable. Optional dashboard evidence is omitted when disabled or unsupported. |
| Frontend legacy/v2 compatibility | PASS | Adapter and page tests cover old, enhanced, malformed and unavailable evidence, loading, errors, retry, terminal jobs, low confidence, missing horizons, zero observations and expired sessions. |
| Seller isolation and replay | PASS | Signed authentication, foreign-seller API denial, worker ownership checks, scoped evidence, idempotency and replay tests passed. The final-event cache refresh includes the authenticated seller key. |
| Marketplace mutation | PASS for the audited flows | Generation and acknowledgment update advisory records and outbox state. Tests preserve recorded product price and stock. The full browser run left price 500 BDT and stock 30 unchanged. |

These safety results describe the enabled Phase 5 path. Disabling the relevant flags deliberately restores the original specialized and explanation behavior. Historical regression elasticity, configured heuristic assumptions and free-text legacy LLM explanations do not acquire the new validation guarantees through the dashboard flag.

## Full browser delivery

A temporary local harness exercised the production frontend bundle against the real authenticated recommendation and product routes, PostgreSQL, an isolated Redis instance and a separate Celery solo worker. It enabled the Phase 5 service flags and the frontend evidence flag. It used seeded business records and disabled approved-model inference, then forced the optional Groq call to time out. No external marketplace or LLM request was made.

The signed seller generated a durable job from the browser. The worker evaluated pricing, reorder and recovery, persisted the decision and Bangla template, and returned the completed result through the job/latest APIs.

The seeded product had 30 on-hand units, 5 reserved units and 4 confirmed incoming units. Available stock was 25 and inventory position was 29. Recorded sales supplied the daily fallback rate. Target stock rounded up to 57, leaving 28 raw units to order. MOQ 12 and pack size 6 produced the displayed 30-unit recommendation. A separate combined API regression supplies an approved 70-unit lead-time forecast and a 10,000 BDT budget at 200 BDT per unit. Its supported order is capped to 48 units after pack rounding.

The browser displayed REORDER, the verified Bangla quantity, evidence timestamps, recorded available stock, demand-source labels, supporting listing advice, the unavailable forecast horizons and pricing alternatives with unknown sales response. Repeating the submission key left exactly one recommendation, one job and one RAG outbox row.

Chrome checks passed at 375px and 1280px. They verified mobile stacking, three desktop horizon columns, absence of horizontal document overflow, Enter-key access to the pricing disclosure, and no additional interval polling after completion. Screenshots were visually reviewed. Redis publication of the final recommendation event succeeded. Socket.IO browser delivery was covered through hook tests rather than a live browser subscription in this harness.

Approved forecast integration uses fixtures in the permanent tests. The existing native model and inference regressions also ran. These checks establish integration behavior with known inputs and do not measure forecast accuracy or promotion response on actual seller data.

## Commands and outcomes

The application environment used CPython 3.14 and the existing backend virtual environment. PostgreSQL tests used disposable schemas and Redis checks used a separate Unix socket instance with persistence disabled.

| Check | Outcome |
| --- | --- |
| Full backend pytest | 1,037 passed, 809 subtests passed, 24 failed, 4 skipped |
| Combined Phase 5 API and forecast-aware reorder regression | 20 passed |
| Scoped Ruff across the 19 reviewed service/schema modules and new backend tests | Passed |
| Scoped mypy across 19 service/schema modules, with follow-imports=silent and ignore-missing-imports | Passed |
| Backend compileall | Passed |
| Frontend lint | Passed |
| Frontend typecheck | Passed |
| Frontend tests | 108 passed in 23 files |
| Production frontend build | Passed |
| Git diff whitespace checks | Passed |

The full backend command was run from backend.

```sh
BAZARSYNC_TEST_POSTGRES_URL=postgresql+psycopg2:///postgres \
BAZARSYNC_TEST_REDIS_URL=unix:///tmp/bazarsync-phase5-redis/redis.sock \
venv/bin/python -m pytest -q -rs --tb=short
```

The PostgreSQL recommendation fixture creates and drops unique schemas. The Redis URL above refers to the temporary audit instance, which must be started before reproducing the command.

The permanent combined regression lives in test_phase5_recommendation_integration.py. It covers simultaneous Phase 5 flags, genuine signed authentication, forged LLM claims, RAG text, forecast availability, constrained quantities, unchanged product price/stock, duplicate worker delivery and request-key replay.

## Remaining gates

The 24 full-suite failures are all in test_copilot_orchestrator.py. Their exact test-name set matches the stored Task 18 full-run failure set. The Copilot orchestrator and its test file have no changes in this audit. Failures include expected tool selection, conversation context and proposal assertions, including the existing unsafe-price-proposal assertion. Whole-application Copilot safety cannot be certified from this failing suite. It remains a release blocker.

Three skips require the optional StatsForecast installation. One historical export test requires BAZARSYNC_HISTORICAL_TEST_POSTGRES_URL, distinct from the recommendation fixtures' PostgreSQL setting. The historical export test creates its own tables and was not directed at an existing database.

The build retains CSS @theme/@utility minification warnings, stale Browserslist data and a bundle above the warning threshold. Tests retain Node's experimental localStorage warning. Backend tests report an existing HTTP 422 constant deprecation warning.

No container runtime is available for a deployment image build. The earlier fresh-install migration blocker remains documented in the architecture/progress baseline. This audit changes no migrations and does not revalidate fresh database installation. Existing deployed-database history compatibility is covered by the record and API regression tests.

All Phase 5 rollout flags retain their default false values. No production model approval or live marketplace action was performed.
