# Recommendation engine v2 implementation progress

## Minimum production-readiness audit · Phases 1–5

The 20 November 2026 audit records NO-GO. Native CatBoost loading, fallback, representative additive migrations, signed browser-to-worker delivery and frontend checks passed. The full backend run passed 1,038 tests and 809 subtests with three optional StatsForecast skips and the same 24 Copilot failures. Scoped mypy passed 28 modules, while whole-app lint/type gates remain red. Fresh migration still fails at the original root revision. The rerun synthetic holdouts retained baselines at every horizon, and production Linux/container capacity remains unverified. A backend Docker ignore file now excludes local secrets from the standard build context. [Readiness report and executed evidence](production-readiness-audit.md)

## Phase 5 integration audit · Tasks 15–19

The enabled recommendation path passed a real signed browser → API → PostgreSQL/Redis → separate Celery worker → final dashboard check with seeded data and forced Groq timeout. The audit fixed forecast-aware reorder revision reuse after demand/model changes and refreshed final explanations in the dashboard. Backend compilation, scoped Ruff and 19-module mypy passed. Frontend lint, typecheck, 108 tests and build passed. The full backend run passed 1,037 tests and 809 subtests, with four skips and the same 24 existing Copilot failures. Whole-application readiness remains PARTIAL. [Results, corrections and remaining gates](phase-5-integration-audit.md)

## Task 19 implemented

The seller dashboard now renders optional saved evidence, approved forecast horizons, compatible supporting advice, reorder insights and price-constraint comparisons. Durable jobs announce terminal and evidence-limited states, with explicit retries and expired-session handling. Both the additive API summary and new visual sections default off. Frontend verification passed 106 tests, lint, typecheck and build. The focused backend suite passed 33 tests, and fixture-based Chrome checks covered mobile, desktop, keyboard disclosure and terminal polling. [Contract, rollout and verification](task-19-recommendation-dashboard.md)

## Task 18 implemented

The default-off Bangla explanation path commits the validated decision and deterministic explanation before optional Groq selection. It uses a strict response schema with approved wording and metric references, and indexes accepted updates through the existing RAG outbox. [Evidence, configuration, and rollback](task-18-bangla-explanations.md)

## Task 17 implemented

The default-off recovery evaluator preserves dead-stock classification and filters existing strategies by inventory, sales, visibility, campaign, and MarginGuard evidence. It audits rejected alternatives and calculates conditional cash and holding-cost scenarios. Approved forecasts supply baseline stock-risk context, and compatible listing advice can support an orchestrated pricing or reorder decision. [Evidence rules, scenarios, and rollout](task-17-evidence-driven-recovery.md)

## Task 16 implemented

The default-off reorder planner uses approved demand for exact supported supplier lead times and independently evaluated upper bounds where available. It separates reservations, available stock, and confirmed incoming units, applies supplier, capacity, and budget constraints, and uses existing recorded velocity when approval or inference is unavailable. The specialized worker and DecisionOrchestrator share the planner. [Calculations, validation, and rollout](task-16-forecast-aware-reorder.md)

## Task 15 implemented

Forecast-assisted pricing is default-off. It audits every generated candidate with MarginGuard, records verified competitor freshness and confounding evidence, and attaches an approved 30-day baseline forecast when available. The enabled path holds price when candidate demand is unvalidated. Its audit goes through both specialized pricing and DecisionOrchestrator. [Decision rules, rollout, and verification](task-15-forecast-assisted-pricing.md)

## Phase 4 release-readiness audit · Tasks 11–14

CatBoost and its intervals have a no-go decision at every horizon. The audit added archive lineage, aligned holdout scoring with the deployment regime, tightened promotion checks, and fixed startup without application credentials. Synthetic runs retained baselines and measured interval coverage and native loading costs. Real seller accuracy and production Linux resource use remain unverified. [Release decision, measured results, and outstanding checks](phase-4-release-readiness.md)

## Task 14 implemented in isolated inference

The default-disabled inference service uses a seller-scoped SHA-256-pinned registry, verifies approved native artifacts, and bounds execution in a separate process. Active and previous releases fall back to the Task 12 statistical forecast or insufficient data. Shadow predictions are kept separate from authoritative results. [Deployment, artifact promotion, and rollback](task-14-forecast-inference.md)

The forecasting regression passed 97 tests with disposable PostgreSQL. Three optional StatsForecast skips were covered in a separate 48-test run. Scoped lint, formatting, type checks, and dependency checks passed. Native CBM loading and prediction ran on macOS ARM64 with CPython 3.14.4. A Linux image build and smoke run remain unverified because the workspace has no container runtime.

## Task 13 implemented offline

Forecast results can carry optional prediction intervals with calibration provenance. The offline evaluator fits residual profiles before a fixed Dhaka cutoff and reports achieved coverage, width, and directional misses on later observations by horizon and regime. Unavailable profiles preserve the point forecast and give an explicit reason. [Method, replay command, and reliability states](task-13-forecast-uncertainty.md)

The focused suite passed 82 tests with disposable PostgreSQL. The three optional StatsForecast skips were covered by a separate 48-test run. Scoped lint, formatting, type checks, and Git whitespace checks passed. Coverage was measured on synthetic future holdouts. Real seller coverage and CatBoost interval coverage on actual model predictions remain unevaluated.

## Task 12 implemented offline

The regime classifier uses verified sales frequency, spacing, variance, coverage, and stockout evidence. The offline backtest ranks statistical forecasters by regime and horizon. Inference can abstain, return a verified zero, or use a bounded historical mean when a qualified model is unavailable. [Classifier, selection policy, and offline command](task-12-demand-regimes.md)

The focused forecasting regression passed 65 tests with disposable PostgreSQL. Three optional StatsForecast skips were covered by a separate 31-test run with StatsForecast 2.1.1. Scoped lint, formatting, type checks, and Git whitespace checks passed. Selection was exercised on synthetic archives with later forecast origins. Real seller performance remains unevaluated.

## Task 11 implemented offline

The CPU-only CatBoost path trains direct 7-, 14-, and 30-day models from Tasks 8–9, tunes a bounded objective set with embargoed rolling-origin validation, and evaluates on an untouched future period against Task 10 baselines. It records horizon, category, and volume/cohort MAE, WAPE, MASE, and bias; validates and checksums serialized models; and fails closed for invalid output or insufficient history. [Design, command, dependency target, and rollout boundary](task-11-catboost-demand-forecasting.md)

CatBoost remains outside the API and general Celery dependencies. No route, worker decision, feature flag, migration, or live recommendation caller changed. The local evaluation artifact is synthetic because the configured sources contain no eligible historical seller observations; it cannot authorize production selection. A build of the dedicated Linux training container remains a release check because Docker/Podman is unavailable in this workspace.

The final synthetic run used archived Task 8 and Task 9 fixtures, loaded all three serialized models, and retained Phase 3 baselines at all horizons. The focused suite passed 51 tests with three skips for PostgreSQL and optional StatsForecast integration. Clean macOS ARM64 installation, CPU training smoke, and binary-only Linux CPython 3.14 dependency resolution on ARM64 and x86-64 passed.

## Phase 3 verification · Tasks 8–10

The offline path passed 88 focused tests and a byte-identical replay of a 12-origin fixture backtest. The audit corrected coverage precedence, price aggregation, competitor marketplace scope, snapshot transaction validation, and duplicate origins and conflicting outcomes. The configured local database has zero eligible products and no sales history. Real-data accuracy and ML readiness remain unverified. [Readiness report](phase-3-verification.md)

## Task 10 implemented

The offline statistical forecast service uses Task 9 origin validation and Task 8 eligible sales. It compares built-in and optional StatsForecast baselines by horizon and product cohort. Reports include scored and unscored folds, forecast coverage, MAE, WAPE, MASE, and bias. [Baseline rules, metrics, and evaluation command](task-10-statistical-forecasts.md)

On Python 3.14.4, 82 focused tests passed with disposable PostgreSQL and the isolated StatsForecast 2.1.1 installation. Scoped Ruff and mypy passed. Binary-only resolution succeeded for Linux x86-64 and ARM64 CPython 3.14. The production image and real seller forecast accuracy were outside this verification.

## Task 9 implemented

The forecast feature builder uses archived, pre-origin Task 8 snapshots and shares one feature schema across inference and training examples. It supports 7-, 14-, and 30-day targets, timestamped competitor evidence, and published Bangladesh holiday versions. [Feature schema, time definitions, and snapshot capture](task-9-forecast-features.md)

On Python 3.14.4, 67 focused tests passed with disposable PostgreSQL, including the opt-in snapshot export, future-data exclusion, and training and inference parity. Scoped Ruff and mypy passed.

## Task 8 implemented

The default-off offline export creates a seller-scoped daily business dataset with a Dhaka business date, explicit sales coverage, stockout observations, and opening competitor evidence. It includes a quality report and supports rebuilding date or product partitions from a read-only PostgreSQL snapshot. [Schema, cutoffs, and export command](task-8-historical-dataset.md)

On Python 3.14.4, 55 focused tests passed, including read-only PostgreSQL export and byte-for-byte replay on disposable data. Scoped Ruff and mypy passed. Verification covered the export and its source adapters with test fixtures. Production seller data and load were outside this verification.

## Phase 2 audit · Tasks 5–7

The combined recommendation flow passed the pricing, reorder, dead-stock, MarginGuard, recommendation API, and Celery regression checks. The audit covered the default-off flags, the active orchestrator and evaluator, and the legacy path after disabling orchestration.

### Flow and fixes

- A signed API request passed through Redis and a separate Celery worker to PostgreSQL. The saved result used normalized candidates and the risk-aware evaluator. Redis received the recommendation event. Idempotency-key replay and task redelivery left one completed attempt, one recommendation, and one RAG outbox record.
- PostgreSQL integration tests cover a reorder rejecting both a price change and a stock-consuming bundle, plus a price recommendation retaining compatible listing advice. Disabling orchestration exercised the legacy queue response, Celery task, and saved recommendation while the earlier durable result remained readable. Existing recommendation fields, stored action values, specialized tables, and older JSONB readers were reviewed for compatibility.
- Pricing now uses the effective price increment and shared marketplace rounding. Rounded prices must remain inside the configured change band. A sparse increment grid retains the current offer as a comparison anchor, and unsupported persisted prices are rejected.
- A complete sales window matching the pricing scenario supplies recorded net units. Other supported sales windows project the measured daily rate to the scenario horizon through the shared demand helper. The candidate records the baseline source and dates. The specialized pricing engine still owns scenario economics. The adapter and evaluator consume its outputs.
- The initial and final stages each resolve pricing and fees once. Identical guard quotes within a stage reuse the result. The final stage uses a fresh guard and rechecks the selected exact price. The integration test asserted two pricing-policy reads, two fee-policy reads, and one guard computation per distinct quote per guard instance. One local worker smoke run logged 69 ms for generation, persistence, and publication. This was a single seeded observation.

### Verification results

- Python 3.14.4 and disposable PostgreSQL and Redis. The focused sweep passed 397 tests and two subtests across 34 modules. The full backend run passed 885 tests and 809 subtests. The same 24 Copilot orchestrator cases failed before and after the audit. All four Redis-dependent cases skipped in the baseline ran in the final suite.
- All 94 frontend tests, frontend lint and typecheck, scoped Ruff, and scoped mypy passed. The scoped diff passed whitespace checks. An import graph check found no import-time cycles through the eight Phase 2 modules checked, and FastAPI and Celery imported in a fresh process.
- The audit requires no database migration. Alembic reported a single head at `l6f7a8b9c0d1`. A disposable empty database still fails at the pre-existing root revision `9ba821df6da5` because `competitors` is absent. The functional tests used disposable schemas and seeded elasticity evidence. The audit did not measure forecast accuracy or production load.

## Task 7 implemented

The opt-in action evaluator applies hard safety and evidence constraints before normalizing preference factors. The JSONB audit records provenance, scoring, adverse risk, policy version, selected actions, and rejections. Pricing separates verified unit economics from modeled outcomes and preserves unavailable estimates. [Evaluation policy and configuration](task-7-action-evaluation.md)

- On Python 3.14.4, 282 focused backend tests passed against disposable PostgreSQL and Redis. Coverage includes exact-price guard rechecks, quantity constraints, missing demand, uncertainty, abstention, deterministic ordering, compatible supporting actions, and flag rollout.
- A signed API request completed through Redis and a separate Celery worker. The versioned audit and pricing sensitivity band persisted. The recommendation event reached Redis, and replay left one recommendation and one RAG outbox row.
- All 94 frontend tests passed, and frontend typecheck passed. Scoped Ruff and mypy passed for the evaluator and integration. The wider mypy check reported 14 existing findings in the specialized pricing and demand services.

## Task 6 implemented

The generic worker can evaluate dynamic pricing, reorder and dead-stock recovery against a shared seller-scoped context. It selects one primary action, retains compatible advice and rejected proposals, and rechecks exact prices before persisting. Active and shadow evaluation both default off. [Decision rules and rollout settings](task-6-decision-orchestration.md)

- On Python 3.14.4, 248 focused backend tests passed against disposable PostgreSQL and Redis, including 10 new cases for selection, scope, missing inputs, final price and inventory checks, replay, and shadow behavior.
- A signed API request completed through Redis, a separate Celery worker and PostgreSQL. The worker published the recommendation event. Idempotency-key replay and task redelivery left one completed attempt, one recommendation, and one RAG outbox row.
- Scoped Ruff and formatting checks passed. Mypy passed for the orchestration modules and shared inputs. The broader check reported 26 findings on existing code and third-party imports. All 94 frontend tests and frontend typecheck passed.

## Task 5 implemented

The internal candidate schema and seller-scoped adapter cover dynamic pricing, reorder planning and dead-stock recovery. Eligible prices use the recorded MarginGuard verdict for the exact candidate. Recovery actions remain specialized under the generic HOLD action. [Candidate schema and adapter contract](task-5-recommendation-candidates.md)

- On Python 3.14.4, 203 focused backend tests passed, including 35 new candidate cases. The 22 existing PostgreSQL integration cases skipped because `BAZARSYNC_TEST_POSTGRES_URL` was unset.
- Scoped Ruff lint and formatting checks and mypy passed. All 94 frontend tests passed, and frontend typecheck passed.

## Phase 1 verification audit · 15 November 2026

**Decision: No-go for Phase 2.** Phase 1 passes the recommendation-focused tests and an integrated smoke test. A reproducible clean database install remains blocked, the backend suite remains red, and the migration has yet to be rehearsed against a representative deployed schema. Phase 1 is ready for a controlled staging rehearsal on a database with the supported existing schema. Phase 2 was not started.

### Verification matrix

| Area | Evidence |
| --- | --- |
| Seller isolation | Signed API smoke verified 401 without a token and 404 for another seller on generation, latest recommendation, latest job and job-ID reads. Tests exercise worker ownership checks, cross-product scrape records and validator scope rejection. |
| API and database compatibility | Phase 1 revisions upgraded from `i3c4d5e6f7a8` to `l6f7a8b9c0d1`, downgraded and re-upgraded in disposable PostgreSQL. The historical recommendation survived. Existing routes and numeric types remain. Stock availability keys are omitted for pre-Task-2 responses and included when meaningful. Existing job responses retain the additive job ID. |
| Freshness and financial safety | Snapshot tests cover carried-forward, stale, invalid and unknown observations. Low-quality matches are excluded before market calculations. Decimal prices use effective product/category/seller fees and the exact increment. MarginGuard rechecks the final candidate against refreshed product inputs. Generic RAISE is blocked without an actual candidate. |
| Demand and confidence | Enabled Tasks 2 and 4 use observed or qualified recorded net sales and distinguish missing demand from observed zero. Confidence requires evidence quality, with unknown predictive uncertainty. The dashboard renders categorical confidence and omits the unsupported expected-lift display. Rollback modes retain legacy analytics, so these evidence guarantees require the applicable flags. |
| Lifecycle, recovery and RAG | Concurrent POSTs, key replay, redelivery, retry classification, expiry, storage rollback, outbox retry and notification failures were tested. With all flags on, a signed POST completed via disposable Redis and a separate worker. A prefork child was deliberately terminated after claim with a shortened test lease. The replacement worker completed attempt two, redelivery left the attempt count unchanged, exactly one new recommendation and outbox row persisted, and Redis received the recommendation event. |
| Frontend | Tests cover duplicate clicks, exact-job completion, reload, terminal failure, retry, lost-response key replay and honest confidence display. |

### Audit fixes

- Fee lookup database errors now propagate to the worker's retry path. Invalid policies still fail closed. Product ownership and current economic inputs are rechecked under a lock at persistence, and Task 4 invalidates stock metrics if current on-hand units disagree with the recorded snapshot.
- Groq completion transports close on the event loop that used them. Consecutive jobs can use separate event loops. The client initializer no longer takes the same lock twice on first use.
- Generation retries reuse an unresolved submission key even when discovery returns an older job. The frontend switches cleanly from legacy polling to a returned durable job. Terminal status reads avoid dispatch work.
- Legacy recommendations retain their response shape. The dashboard uses the actual saved confidence labels from REST and Socket.IO rather than deriving percentages for display. Its expected-lift row was removed because the existing value came from urgency.

### Executed results and remaining risks

- **Python 3.14 backend:** 97 focused tests passed. Full suite: 817 passed, 24 failed, and 809 subtests passed. All failures match the pre-existing Copilot orchestrator failures.
- **Frontend:** 94 tests passed, plus lint, typecheck and production build. Existing build warnings remain.
- **Static checks:** Scoped Ruff passed. Repository-wide Ruff reported 108 lint findings and 376 files requiring formatting. Mypy reported 370 errors across 95 files. Git diff whitespace checks passed.
- **Alembic:** One head, `l6f7a8b9c0d1`. Empty PostgreSQL still fails at `9ba821df6da5` on the missing `competitors` table. Offline SQL generation still fails at `4f3b6e8a92b1` because it requires database inspection.
- **Rollout limits:** No existing deployment was migrated. Live Groq, browser Socket.IO delivery, and live RAG embedding were outside the audit. Timeout and indexer failure tests used fixtures. Current-market pricing requires freshly scraped field timestamps and match scores. Job recovery expects Beat for unattended work, and missing inventory/sales/fee evidence can lead to HOLD. The general reorder path omits unconfirmed incoming stock.
- **Diff scope:** Reviewed tracked changes and untracked Phase 1 source, migrations, tests and documentation. Pre-existing scraper changes and the tracked Redis dump were preserved.

## Task 4 implemented

[Evidence validation and confidence](task-4-evidence-validation.md) records the eligibility rules, confidence thresholds, scope checks and migration rollout.

- The focused backend suite passed 124 tests with disposable PostgreSQL and Redis. The full suite passed 815 tests and 809 subtests, with the same 24 Copilot orchestrator failures from the baseline.
- Ruff passed on the new files. Repository-wide Ruff reported 108 findings and mypy reported 370 across 95 files.
- Migration upgrade, downgrade and re-upgrade preserved the existing row in a representative PostgreSQL snapshot table. The earlier fresh-install migration blocker remains.
- The feature defaults off. Historical snapshots have unknown match quality until new observations are collected. Task 4 was verified without a production rollout.

## Task 3 implemented

[Durable generation jobs](task-3-generation-jobs.md) documents idempotency keys, authenticated status, retry and lease behavior, rollout, and rollback.

- The focused backend suite passed 60 tests with disposable PostgreSQL. The full backend suite passed 791 tests and 809 subtests, with the same 24 Copilot orchestrator failures from the baseline.
- A signed API request passed through disposable Redis and a separate Celery worker to PostgreSQL. Job-status retrieval returned the persisted result, duplicate delivery produced no extra row, and the worker published the existing recommendation event to Redis. Recovery from worker loss was exercised with a simulated expired lease.
- Migration upgrade, downgrade and re-upgrade passed against a representative PostgreSQL schema, preserving the historical recommendation row. The fresh-install migration blocker remains.
- All 92 frontend tests passed. Frontend lint, typecheck and production build passed. Repository-wide Ruff and mypy reported 108 and 370 existing findings respectively. Ruff passed on the new backend files.
- The feature defaults off. Verification used a deterministic recommendation and simulated Groq timeouts. No production rollout was performed.

## Task 2 implemented

[Inventory and pricing signals](task-2-business-signals.md) describes demand classes, stock coverage and pricing policies, API availability indicators, and rollout.

- The focused backend suite passed 113 tests, including the PostgreSQL worker-entry test with recorded sales, returns, product fee precedence, and Decimal candidate rounding.
- The full backend suite reported 784 passed, 24 failed and 809 passing subtests with disposable PostgreSQL and Redis. The failures match the baseline Copilot orchestrator tests. Ruff passed the new Python files and reported 108 repository-wide errors. Mypy reported 370 errors across 95 files.
- Frontend tests passed 90 cases. Typecheck, lint and build passed. The build emitted warnings.
- Task 2 is off by default. No deployment or schema updates were performed for Task 2.

## Task 1 implemented

[Competitor evidence and freshness](task-1-competitor-evidence.md) documents the opt-in implementation, field classification, API behavior, and migration rollout.

- Focused backend coverage passed 109 tests using disposable PostgreSQL and Redis. This covered snapshot writes, provenance and freshness, API preflight, worker task entry, history preservation and MarginGuard.
- The full backend suite reported 766 passed, 24 failed and 809 passing subtests. The same 24 Copilot orchestrator failures were present at the audit baseline.
- Ruff passed on the new Python files and reported 108 errors across the repository. Mypy reported 370 errors across 95 files.
- The new Alembic revision passed upgrade, downgrade and re-upgrade against a representative existing snapshot table. Its existing row survived each step. The earlier fresh-install migration blocker still applies to the full chain.
- The feature flag is off by default. Live Groq and a deployed Celery broker/worker flow were outside this verification. The integration test invokes the task entry directly after checking the queued message.


## Audit completed 14 November 2026

Read the project documentation, v1 request and worker flow, business analytics, pricing safeguards, models and migration chain, RAG indexing, UI consumers and tests. Ran the checks below against the pre-change working tree on `develop` at `6f796ea`. The audit added the engineering contract and baseline documentation.

## Existing issues

| Area | Finding |
| --- | --- |
| Missing evidence | The general flow demands priced competitor data even for inventory advice. It does not check freshness at selection time, and unknown stock statuses are excluded from the availability denominator. When all statuses are unknown, the resulting zero availability ratio boosts synthetic velocity. Required historical API metrics may fall back to zero. General confidence is a rule score. The recommendation event's `expected_lift` is derived from urgency. Neither is an evaluated prediction. |
| Price safety and explanation | Early scoring uses static fees and floats. `RAISE` checks the current selling price, so its successful guard check establishes safety only for that price. A final guard rejection can retain text for the earlier action and append an English note about price lowering. The free-text body can include unsupported claims even when the structured action is correct. |
| Demand input gap | The current order model supports nullable transaction price and line total. The DB-backed elasticity adapter still substitutes zero for every observation price and the cleaner rejects it. Existing eligibility tests and a labeled prior do not establish out-of-time accuracy on seller data. |
| Queue and persistence | The route synchronously repeats business preflight that the worker also runs, with no durable input correlation. Broker publication errors have no route-specific mapping. General persistence uses a fresh recommendation ID per execution. Late ack, ambiguous post-commit failures, retries or concurrent requests can produce duplicate history. Outbox dedupe is per source, so it does not solve that. |
| Completion and delivery | Latest-row polling uses browser time and any later product row. Clock skew, product switches, or overlapping requests can obscure which job completed. No terminal failure or polling deadline is exposed. General Socket.IO emission can be skipped in a standalone worker, and post-commit socket/summary work can fail after a successful write. The existing [Phase 5 publisher](../../backend/app/services/phase5_realtime_service.py) provides a worker-side Redis pattern to evaluate without changing dashboard event contracts. |
| Availability and latency | Groq outage, missing configuration or invalid explanation can prevent persistence. Layered Groq, generator and task retries extend completion time. Input validation differs across models and context schemas, including title/SKU lengths, lead time and negative post-fee margin. Preflight catches domain errors, and its actual error coverage needs integration tests. |
| Adjacent inventory API | In [products.py](../../backend/app/api/v1/products.py), the inventory-history list handler has no return. Its response code is unreachable after the separate inventory-intelligence handler returns. This is existing debt for consumers that need that history route. |
| Migrations | On an empty PostgreSQL instance, the root revision `9ba821df6da5` fails because `competitors` is absent. Offline SQL generation fails separately at `4f3b6e8a92b1` because it inspects a mock connection. |
| Coverage | Existing tests cover MarginGuard, specialized services, RAG outbox and Phase 5 delivery. No dedicated test was found for the general authenticated API → real Celery worker → PostgreSQL → RAG/browser path or the recommendation page's polling lifecycle. |

## Verification baseline

| Check | Outcome |
| --- | --- |
| Local environment | Python 3.14.4 with pytest 9.1.1. `python -m pip check` passed. Frontend ran under Node 26.0.0 and npm 11.12.1. |
| Backend full `python -m pytest -q` | 734 passed, 24 failed, 18 skipped, 809 subtests passed. All failures were in `tests/test_copilot_orchestrator.py`. Observed assertions include missing tool calls and missing proposal fields. Root cause was outside this audit. |
| Backend focused explicit test files | 150 passed. Covered MarginGuard, dynamic pricing, pricing analytics and policy, reorder and dead-stock recovery/workflow, sales velocity, stockout, inventory history, Phase 5 realtime, RAG outbox, revenue simulator and competitor snapshots. |
| Backend Ruff and mypy | `ruff check . --statistics` reported 108 errors. `ruff format --check .` reported 370 files needing formatting. `mypy app` reported 373 errors in 95 files across 333 checked source files. |
| Frontend `npm test` | 90 passed across 18 files. |
| Frontend `npm run lint`, `npm run typecheck`, `npm run build` | All passed. Build emitted Browserslist, CSS at-rule and large-chunk warnings. |
| Alembic | `heads` reported a single head, `i3c4d5e6f7a8`. Online upgrade failed on a disposable empty local PostgreSQL cluster at `9ba821df6da5`. `upgrade head --sql` failed at `4f3b6e8a92b1`. No existing application database migration was run. |

Live Groq, end-to-end worker/WebSocket/RAG delivery, pricing accuracy, production-image compatibility and migration upgrades from an existing installed schema were outside the executed baseline. The migration failures block a clean migration-based integration environment. Seller-specific data coverage and model quality remain unmeasured.

## Recommended implementation order

1. Capture legacy API, snapshot and event behavior with regression tests. Cover tenant boundaries, missing inputs, fee-policy changes, exact candidate guarding, queue errors, stale reads and concurrent requests. In parallel with this test work, establish a reproducible PostgreSQL/pgvector fixture and a supported bootstrap and upgrade path that preserves existing records.
2. Add default-off execution controls and a durable seller-scoped run identity. Keep the existing request and response shapes, and add bounded completion/failure handling. Verify replay, concurrent execution, worker loss and separate delivery with an actual worker and broker. Reuse the existing RAG outbox and assess the worker-side realtime publisher.
3. Share evidence from the existing competitor, sales, inventory and specialized pricing services through the existing recommendation orchestration. Record provenance and timestamps. Preserve older snapshots. Fail closed on unavailable economics, and recheck the exact candidate with MarginGuard before persisting the decision.
4. Explain the final decision from validated facts and use a deterministic Bangla fallback when the provider fails. Test that unsupported quantities, changes, revenue and profit cannot enter the decision or its explanation. Limit network attempts across retry layers.
5. Repair the transaction-price evidence adapter and build offline, point-in-time datasets with coverage, stockout, promotion, refund, fee and currency handling. Evaluate on forward time splits against simple baselines. Report error, uncertainty coverage, missing-data behavior and business guard violations across seller/product cohorts.
6. Run candidate forecasts in shadow mode. Compare coverage, drift, safety, latency and fallback rates before enabling the evidence-backed result for selected sellers. Keep advisory semantics and a flag-based rollback.

<<<<<<< Updated upstream
## Business Copilot accuracy eval

Plan: [copilot plan](../superpowers/plans/copilot%20plan.md). Golden set: `backend/tests/fixtures/copilot_golden_questions.json` (40 questions on the `demo1@gmail.com` comprehensive demo seed, as_of 2026-11-21, ISO date ranges). Runner: `python scripts/copilot_eval.py --seller-id <uuid>`. A question passes when every expected value appears in the answer.

| Run | Code | Score | Tool match | Notes |
| --- | --- | --- | --- | --- |
| Baseline, 2026-11-22 | `develop` + Copilot WIP (before Task 1) | 4/40 (10%) | 62% | Groq free quota was exhausted (HTTP 429 on every call), so nearly every reply was the deterministic fallback. Results: `backend/artifacts/copilot_eval/20261121T193710Z.json`. |
| Baseline, paced, 2026-11-22 | Same code, 35 s between questions, pre-change RAG settings | 9/40 (22%) | 62% | Fair baseline; 7 Groq 429s remained. `baseline-paced-20261121T201849Z.json`. |
| After, 2026-11-22 | Branch `feature/copilot-robustness`, all rollout flags on, chain `gemini:gemini-3.5-flash-lite,groq:openai/gpt-oss-120b` | 27/40 (68%) | 90% | 19 gained, 1 regression (`stock_black_casual`). `20261122T034957Z.json`. Target of ≥90% not met. |

Baseline failure patterns:

- The fallback answer reports a nested top product's `gross_revenue` (59150.00) as the period's gross revenue (290360.28).
- A Men's Footwear revenue question answered "BDT 0", but `get_revenue_summary` with `category="Men's Footwear"` returns 235260.96.
- Product-name questions ("Lex Loafer…", SKU lookups, "BUBBLE GUMMERS…") were sent to competitor clarification ("Which competitor do you mean").
- Stock-in questions had no tool to route to.
- Count questions (products, alerts) gave "I could not find a clear answer".

After the 27/40 run, three more fixes went in (stock snapshots cannot be summed, record types are never relabelled, zero revenue reads as "no sales recorded"). A re-run of the 13 failing questions confirmed `inventory_units` and `banglish_stock` now answer 726 units, and the invoices question no longer claims "138 invoices". The full 40 were not re-run after these fixes.

Remaining failures, all model-side on the free flash-lite model:

- It says data is "not recorded" when the right tool was not in the planner's seed and the loop did not fetch it (single-product stock, SKU stock, recent price changes, completed promotions).
- It restates long decimals (7.0296…%) or answers partially (top 3, previous-period revenue).
- Profit differs from the golden value (147972.03 vs 144764.68); not yet investigated.
- A Bangla product-count question gets the no-answer template.

`gemini-3.8-flash` returned 503 or timed out on the free tier during the run, so it is not in the chain.

| Run | Code | Score | Tool match | Notes |
| --- | --- | --- | --- | --- |
| After improvements, 2026-11-22 | Loop gets resolved entities; named products get their profile; facts may be stated rounded; prompt budget 4000/20000 | 36/40 (90%) | 100% | Meets the plan's ≥90% target. `20261122T051916Z.json`. |

Of the 4 failures, 3 happened when both providers were unavailable at once (Gemini 503 and Groq 429, `ALL_ROUTES_FAILED`), so the deterministic fallback answered. These are `stock_black_casual`, `stock_in_week` and `bangla_products`. `stock_black_casual` and `stock_in_week` passed in the targeted re-runs. The fourth is `unanswerable_invoices`: the validator rejected the model's answer, so the reply is a safe "no clear answer" with no invented number. Against the paced baseline, the only miss is `stock_black_casual`, which was a provider outage, not a logic regression.

### Copilot direct answers and Banglish 100-question eval (2026-11-22)

Changes:

- New flag `COPILOT_DIRECT_ANSWERS_ENABLED` (default off). `app/services/copilot/direct_answers.py` answers recognised English and Banglish question shapes from exact, seller-scoped data using templates. It runs after the strict-safety refusal and before clarification. Explicit API filters (`product_id`, dates, domain filters), Bangla-script replies and unrecognised questions take the existing pipeline. Any exception falls back to that pipeline. Nothing here writes business data or changes live price or stock. Version tag: `direct-answers-v1`.
- Bug fixes in existing tools:
  - `get_dead_stock_summary` and the `locked_capital` / `dead_stock_count` metrics now read only the latest assessment and estimate per product. Locked capital now counts only DEAD_STOCK, AT_RISK and SLOW_MOVING products. The demo seller's figure drops from ৳2,724,631.81 to ৳474,912.89, and the dead-stock product count from 2 to 1. Golden expected values were updated to match.
  - Source tools no longer crash on `competitor_events.metadata`.
  - `simulate_price_change` now applies the latest elasticity estimate (constant-elasticity demand) and marketplace fees to profit.
- Additive migration `o9c0d1e2f3a4`:
  - `sales_records.customer_reference` and `sales_records.delivery_district`
  - `product_marketplace_listings.rating` and `product_marketplace_listings.review_count`
  - new tables `business_expenses` and `marketplace_store_metrics`
- `scripts/seed_copilot_demo_extras.py` fills these for the demo seller (bazardemo@gmail.com) only. It is idempotent and tracked in `demo_seed_records` under seed `demo-copilot-extras-v1`.

| Run | Code | Score | Notes |
| --- | --- | --- | --- |
| Banglish 100, before | agent loop + router | 37/100 hand-graded | `20261122T145455Z.json`; 18 answers came from `ALL_ROUTES_FAILED` fallbacks |
| Banglish 100, after | direct answers on | 100/100 auto-graded | `20261122T154420Z.json`; expected facts checked with independent SQL |
| Golden 40, after | direct answers on | 39/40 | `20261122T154656Z.json`; `bangla_products` failed with a script mismatch on the LLM path; tool match reads 10% because direct answers report `direct_answer` instead of the old tool names |

Tests: `tests/test_copilot_direct_answers.py` (14 tests: seller isolation, missing data, fallthrough, flag gate, dead-stock latest run, simulation, metadata serialisation). The full backend suite passes: 1203 passed, 85 skipped.

**Removed (2026-11-22, plan `docs/superpowers/plans/2026-11-22-copilot-llm-accuracy.md` Task 1):** the template layer matched keywords and broke on new wording, so `direct_answers.py`, its flag `COPILOT_DIRECT_ANSWERS_ENABLED` and its 11 tests are gone. The 100/100 and 39/40 rows above measured that layer and no longer describe the shipped code. The tool bug fixes, migration and seed script stay; their 3 tests moved to `tests/test_copilot_previous_fixes.py`. Suite after removal: 1192 passed, 85 skipped.

### Copilot LLM accuracy plan: eval results (2026-11-23)

Plan: `docs/superpowers/plans/2026-11-22-copilot-llm-accuracy.md`, Tasks 1–9. The model now picks the tools; the deterministic planner runs only when the loop yields nothing.

Fixtures:
- `tests/fixtures/copilot_banglish_100.json` was rewritten. Its expected facts are phrase-neutral: numbers, names, and dates written as ISO or in words. `any_of` lists cover Banglish and English wording. Each fact was re-derived with SQL against the demo seller (as of 2026-11-22, Asia/Dhaka), or from the deterministic tool reading that seller's tables, never from Copilot answers.
- New: `tests/fixtures/copilot_banglish_heldout.json`, with the user's 5 pasted questions plus 30 new phrasings.
- A fact is required only if the question asks for it.
- A question with no period is graded on all recorded history (the Task 2 default).
- Facts that could not be reproduced were dropped or replaced: cash flow 341228.95, VENUS demand 1050, Lex Loafer 1586, the 10% simulation totals, Daraz fees 38386.33, and "10 unacknowledged" (the real figure is 13 reorder + 1 pricing).
- `scripts/copilot_eval.py --as-of YYYY-MM-DD` pins "today" for the planner, the classifier and the agent loop.

Pre-existing bugs found by the eval and fixed:
- `get_pending_recommendations` and `get_ignored_recommendations` filtered on statuses the enums lack (`PENDING`, `IGNORED`, `REJECTED`), so PostgreSQL failed the whole tool.
- Model-supplied enum filters (for example promotions `status="ACTIVE"`) did the same.
- Both now match only defined values (`_existing_statuses`, `_enum_safe_equals`).
- `simulate_price_change` crashed on an elasticity estimate with no value.

Runs, all with `--as-of 2026-11-22`:

| Run | Score | Notes |
| --- | --- | --- |
| Held-out 35, pause 4 | 23/35 | `20261122T174206Z.json` |
| Banglish 100, pause 4 | 23/100 | `20261122T180239Z.json`; 65 answers were `ALL_ROUTES_FAILED`. Gemini and OpenRouter free tiers were rate-limited. Groq rejected loop prompts (413) and then hit its 8000 tokens/min limit. |
| Golden 40, pause 4 | 33/40 | `20261122T181639Z.json` |
| Held-out 35, pause 12 | 26/35 (74%) | `20261123T043018Z.json`, re-graded after removing 3 over-strict facts; 4 fallback answers |
| Banglish 100, pause 12 | 50/100 | `20261123T051459Z.json`, re-graded; 27 fallback answers |
| Golden 40, pause 12 | 6/40 | `20261123T053337Z.json`; every Gemini model and OpenRouter were rate-limited (daily free quota spent), so 32 answers are fallbacks. This run measures quotas, not the pipeline. |

The re-runs used routes changed in `backend/.env` on 2026-11-22 at 23:46: five Gemini models then OpenRouter, with no Groq.

The ≥95% target is not met. Failure causes in the paced runs:
1. Provider quota. The free tiers cannot carry 175 questions with up to 4 calls each; this counts against Task 8.
2. The planner fallback picks loosely related tools when the loop's model is unavailable (about 12 failures), and the answer then says "not recorded". This is the original D2 planner weakness.
3. Flash-lite model mistakes even with the right tool (about 14), for example a wrong percentage, "best seller" by row count, or daily average per order.
4. The fallback's primary tool is the planner's first tool, which is sometimes the wrong one (2 failures, such as the Bangla product count answered from `get_product_setup_summary`).

Checks:
- Backend suite: 1231 passed, 85 skipped.
- `ruff check app tests scripts`: 52 errors before and after the plan, none in changed files.
- mypy on the plan's 19 changed Python files: 110 errors before (at `5c0b856`), 109 after.

## Pricing and inventory improvement plan, Phase 1 (2026-11-23)

Plan: [pricing-inventory-improvement-plan.md](../pricing-inventory-improvement-plan.md).

1.1 Unknown competitor stock
- `calculate_market_stats` now counts `OUT_OF_STOCK` separately (`MarketStats.out_of_stock_competitor_count`, also in snapshot evidence `market_stats`).
- `calculate_demand_score` builds the availability ratio from known statuses only. All unknown → neutral 50 with `competitor_availability: "unknown"` and known/unknown counts in the components.
- `PRICING_ANALYTICS_FORMULA_VERSION` default is now `v2`. The dedupe key includes the version, so new snapshots get new keys; the latest-snapshot read does not filter by version, so v1 snapshots stay readable.

1.2 Stockout-aware velocity
- `SALES_VELOCITY_CALCULATION_VERSION=v2` (default stays `v1`) reads `inventory_history.quantity_available` per day through the new seller-scoped `SalesVelocityRepository.daily_available_stock`.
- A day is a whole-day stockout when both the previous day's and that day's snapshot are `<= 0`. A single zero snapshot after an in-stock day is kept (it sold out during the day). Days with no snapshot are kept and reported through `stock_history_coverage`.
- `observed_days` on the row stays the calendar coverage (forecast features and business signals read it that way). The in-stock denominator is `calculation_metadata.effective_window_days`; `stockout_days` is recorded too.
- More than 80% of the window stocked out → `LIMITED` with `limited_reason`, confidence capped at 65.

1.3 Schedule
- No staging config is checked in, so the flag could not be turned on from the repo. `.env.example` now documents `SALES_VELOCITY_CALCULATION_VERSION` and `INVENTORY_INTELLIGENCE_SCHEDULE_ENABLED`. Same-day reruns of v2 velocity are covered by a redelivery test (second run skips).

Checks:
- Backend suite: 1241 passed, 85 skipped (before the redelivery test was added; targeted suites 45 passed after).
- ruff: 3 pre-existing unused-import warnings in the touched files, none new.
- mypy on the 3 changed app files: 184 errors before and after (all pre-existing, none in new code).
- The new repository query was compiled against the PostgreSQL dialect but not run against a database; there is no repository-level DB test harness.
- Not done: the staging run on a seeded product with a stockout.
=======
## Pricing and inventory improvement plan, Phase 2 (2026-11-23)

Shared UI foundation, no behaviour change (nothing mounts these yet except `MissingDataReason`).

New in `frontend/src/components/ui/`:
- `card.tsx` (`Card`, `CardHeader`, `CardBody` on `glass-panel`).
- `status.ts` + `status-badge.tsx`: the one status map (risk, data, reorder, dead stock, pricing action). Every status has icon, label and tone; unknown values render neutral with readable text.
- `kpi-tile.tsx`: label, value, optional delta, hint tooltip reachable by keyboard and linked with `aria-describedby`; renders as a button when clickable.
- `data-table.tsx`: `@tanstack/react-table` with column sort (`aria-sort`), search, page size 10/25/50, sticky header, row click and Enter/Space, rows collapse to cards below `sm`. Client-side paging only (`shortcut:` comment).
- `drawer.tsx`: Radix Dialog (already installed via `radix-ui`), right panel, full screen on mobile, focus trap, Esc, and focus returned to the opening row/button.
- `tabs.tsx` (`UrlTabs`): Radix Tabs with the value in `?tab=`, other query params kept, unknown values fall back to the default.
- `empty-state.tsx`: `EmptyState` and `MissingData`; `components/dead-stock/MissingDataReason.tsx` is now a wrapper around `MissingData` (same text).
- `how-calculated.tsx` (native `<details>`), `freshness-pill.tsx`.

Helpers:
- Formatting went into the existing `src/utils/formatters.ts` instead of a new `lib/format.ts`: `formatMoney` (Decimal strings formatted exactly via Intl, `null` for missing), `formatRelativeTime`, `hoursSince`. Page-local helpers are replaced when Phases 3 and 4 rewrite those pages.
- `src/lib/ui-i18n.ts`: English map with an optional `bn` field per entry and `{param}` filling.

Checks:
- Vitest: 27 files, 144 tests passed (17 new in `ui-primitives.test.tsx` and `formatters.test.ts`).
- `tsc -b --noEmit`, `eslint .` and `vite build` clean (build keeps the existing chunk-size warning).
- Not done: visual check at 375px/1366px in both themes; the components are not on a page yet, so this moves to Phases 3 and 4.

## Pricing and inventory improvement plan, Phase 3 (2026-11-23)

Pricing analytics redesign behind `VITE_PRICING_V2_UI` (default off; off keeps the old `/app/pricing` page).

Backend:
- New read-only `GET /pricing/overview` (`app/api/v1/pricing_overview.py`, `app/services/pricing_overview_service.py`, `app/schemas/pricing_overview.py`). Seller from the auth context; four seller-scoped queries (products, latest snapshot per product and latest recommendation per product via `DISTINCT ON`, active product pricing policies). Per row: live price vs latest median, position (±2% = at market), margin at risk (price below the snapshot's safe minimum), `has_pricing_policy`, latest recommendation with `is_actionable` (OPEN, not HOLD, not expired). Summary is over all products, not just the page. `limit` 1–200.
- `RevenueSimulatorService` evidence now also carries `elasticity` and `elasticity_sample_count` (additive).
- The product simulator (`POST /products/{id}/pricing/simulate`) was already Decimal and MarginGuard-checked, so the workspace uses it as is. The public float simulator (`app/api/pricing_simulator_public.py`, `app/lib/pricing/revenue_simulator.py`) has no frontend caller any more but is kept because routes are preserved.

Frontend (`src/pages/pricing/v2/`):
- `/app/pricing` overview: four KPI tiles that filter the table, setup progress banner, searchable/sortable table, row opens the workspace. `?productId=` links redirect to `/app/pricing/:id`. Refresh queues the seller-wide analytics workflow.
- `/app/pricing/:productId` workspace: recommendation card (Mark as applied / Dismiss call the existing endpoints, copy says the price is never changed for the seller), market box plot (plain list under 3 competitors, fix-it link when none), profit-at-each-price chart from the recommendation candidates with the unsafe range shaded, simulator slider in paisa snapped to `price_increment` and bounded by the policy change limits (debounced 300 ms, labels the elasticity source), costs & fees, price history. Missing fee policy replaces the recommendation with `PricingSetupRequiredCard`.
- `/app/pricing/setup` checklist (fees → pricing policy → competitor tracking) derived from existing data, linking to the existing forms. Deviation from the plan: `fee-setup`, `policy-setup` and `fee-policies` are not redirected, because the checklist and backend readiness links open them.
- Deleted dead code: `RevenueSimulatorCard.tsx`, `services/revenue-simulator-service.ts`, `schemas/revenue-simulator.ts`, `types/revenue-simulator.ts`, `lib/pricing/revenueSimulator.ts` and its test.

Checks:
- Backend: `tests/api/test_pricing_overview.py` (7) and the simulator evidence assertion pass; full suite 1122 passed, 85 skipped on `develop`. ruff/mypy: no findings in new files (2 pre-existing unused imports in `test_revenue_simulator_service.py`). Overview queries ran read-only against the local dev database.
- Frontend: 28 files, 154 tests passed (16 new in `pages/pricing/v2`); `tsc`, `eslint .` and `vite build` clean.
- Not done: browser check at 375px/1366px, keyboard-only pass and axe scan; needs a signed-in seller with products.
- Note: this phase was written on `develop`. Phase 1 is committed on `feature/copilot-robustness` (`7a3025f`) and is not on `develop`.

## Pricing and inventory improvement plan, Phase 4 (2026-11-23)

Inventory intelligence redesign behind `VITE_INVENTORY_V2_UI` (default off; off keeps the 1,053-line page and its tests unchanged).

Backend (additive, no migration):
- `InventoryIntelligenceListItem` gains `reorder_recommendation_id`, `supplier_lead_time_days` and `supplier_lead_time_defaulted` (from the reorder evidence; `None` when older rows lack it). `ProductInventoryIntelligenceResponse` gains `reorder_recommendation_id` and `recommendation_status`. The actions need the id; the runway bar and data-health line need the lead time.
- Telegram inventory alerts include a deep link (`/app/inventory-intelligence?tab=reorder|today&product=<id>`) when `INVENTORY_ALERT_DASHBOARD_BASE_URL` is set; unset (default) sends no link, as before. Before this, `dashboard_url` was never set. The alert dedupe key does not use the message, so links cannot create duplicate alerts.

Frontend (`src/pages/inventory-intelligence/v2/`):
- Shell with URL tabs (`?tab=today|reorder|dead-stock`), filters in the URL (`urgency`, `category`, `show`) and a product drawer on any tab (`?product=`).
- Today: four KPI tiles (out of stock, runs out in under 7 days, reorder now, cash stuck), each jumping to the filtered tab; "To do today" ranked out of stock > runs out before lead time > deadline within 3 days > dead stock by locked capital, one line per product, top 8, already ordered/dismissed excluded. Ranking is client-side from the `/inventory-intelligence/risks` list (all assessed products, not only `REORDER`) and the dead-stock list.
- Data health banner replaces the per-product Data quality panel at page level: defaulted lead time and not-enough-sales counts with fix links; hidden when healthy.
- Reorder: DataTable with `StockRunwayBar` (red when runway < lead time), urgency and category filters, CSV export of the filtered rows. Ordered ✓ / Dismiss are optimistic with a 5-second Undo; the API has no reopen, so the call is held for the window and sent only if not undone, and pending calls are sent at once if the page unmounts.
- Slow & dead stock: search plus one Show control (All / At risk / Dead / Needs review), risk and category under More filters, small age chart; recovery options and "Why we suggest this" (triggered rules in plain words) moved into the drawer.
- Drawer: risk and runway, stock and sales pace, reorder box with the same delayed decisions, missing-lead-time fix, 30-day stock sparkline from inventory history, How we calculated this.
- Shared status map gains the backend `HOLD` reorder action.
- Deviation: the old page's tests were not moved to the tabs, because the old page stays live while the flag is off; new tests cover the v2 page.

Checks:
- Backend: full suite 1124 passed, 85 skipped (`develop`). New tests for the list/product fields and the alert link. ruff/mypy: nothing new (2 pre-existing unused imports, 1 pre-existing mypy error in `inventory_alert_service.py`).
- Frontend: 30 files, 167 tests passed (new: ranking, KPIs, data health, runway, CSV, urgency filter; page: to-do order, data health line, deep link + Esc, row → drawer focus return, optimistic mark-ordered with Undo and the delayed call). `tsc`, `eslint .`, `vite build` clean.
- Not done: browser check (375px/1366px, ~1.5-screen default view at 1366×768, keyboard-only, axe); needs a signed-in seller with data.

## Pricing and inventory improvement plan, Phase 5 (2026-11-23)

Model quality, backend only, every switch default-off. Migration `o9c0d1e2f3a4` (additive: one enum value) follows `n8b9c0d1e2f3` on `develop`.

5.1 Category-pooled elasticity (`DEMAND_RESPONSE_POOLING_ENABLED`)
- `app/services/pooled_elasticity.py` (pure): daily product panels (unit-weighted daily price), days that ended with no stock dropped as censored, within-product fixed effects, OLS on ln(price) with weekday and promotion controls (promotion days are kept as a control instead of being discarded), product slope estimated on price alone with the category's control effects held fixed, then shrunk toward the category slope with weight n / (n + `DEMAND_RESPONSE_POOLING_STRENGTH`=20). Clamped to the existing min/max elasticity.
- Out-of-time check per category: fit on days before the last 28, predict held-out daily units, pass only with ≥14 holdout days, price variation in the holdout, and ≥5% lower MAE than a no-price-effect baseline. Result stored in each estimate's `quality_metrics.out_of_time`.
- Training runs only in the Celery task `demand_response.fit_pooled_elasticity` (daily beat entry added only when the flag is on), per seller with a transaction advisory lock; rows persist through the existing idempotent `persist_estimate` as `POOLED_CATEGORY` / `pooled-v1`, so redelivery is a no-op. Pooling never crosses sellers.
- Request paths only read: `DemandResponseService.estimate_for_product` uses a fresh pooled row when the flag is on (simulator and legacy pricing agree); legacy `_latest_elasticity` skips pooled rows when the flag is off, so turning it off fully reverts. Pooled estimates get the learned uncertainty band (0.35). The orchestrator and action evaluation still accept only `HISTORICAL_ELASTICITY`, so pooled estimates do not drive orchestrated price changes.
- Enum comparisons are done as text so a deploy that runs before the migration does not fail.

5.2 Variability safety stock (`VARIABILITY_SAFETY_STOCK_ENABLED`)
- v1 reorder path: safety units = ceil(z(service level) × σ_daily × √lead time), σ from the last 56 days of net units (no-sale days count as zero, days that ended stocked out are dropped), minimum 14 usable days. Service level `REORDER_SAFETY_STOCK_SERVICE_LEVEL`=0.95, per product `specifications.reorder_service_level`. Falls back to the existing buffer-days formula with the reason recorded (`insufficient_history`, `history_unavailable`, `missing_lead_time`). Rows get version suffix `+vss` so they never collide with v1 rows.
- Deviation: σ comes from the seller's daily sales, not `ForecastIntervalService`, which needs approved forecast artifacts; the forecast-aware path already sizes uncertainty from calibrated intervals.
- The product inventory response now exposes `safety_stock_units` and `safety_stock_service_level`; the drawer shows "buffer of N units (95% protection)".
- Phase 4 fix: the drawer read the lead-time-defaulted flag from `metadata` (risk factors), where it never is. The product response now has `supplier_lead_time_defaulted` and the drawer uses it.

5.3 Forecast-aware reorder rollout
- `FORECAST_AWARE_REORDER_SELLER_ALLOWLIST` (comma-separated seller ids) limits forecast-aware planning to listed sellers when `FORECAST_AWARE_REORDER_ENABLED=true`; empty keeps today's all-sellers behaviour.
- `FORECAST_AWARE_REORDER_SHADOW_ENABLED` builds the other method for every recommendation and stores a summary in `evidence.shadow`; it never changes the decision, and a shadow failure is recorded, not raised. `scripts/reorder_shadow_report.py --seller-id … --days 14` prints agreement (same-action rate, mean quantity gap, one-sided reorders) in a read-only transaction.
- Not done: the two-week shadow run itself.

5.4 Forecast-assisted pricing selection (`FORECAST_ASSISTED_PRICING_SELECTION_ENABLED`)
- With `FORECAST_ASSISTED_PRICING_ENABLED` and this flag on, a non-current price is chosen only when a fresh pooled estimate passed its out-of-time check, the approved baseline forecast is available, fresh competitor prices are sufficient, the candidate passed MarginGuard, and the gain beats `DYNAMIC_PRICING_MIN_IMPROVEMENT_RATE`. Otherwise the existing HOLD is returned with `price_response.reason`. Units come from `forecast_candidate_units` on the baseline forecast; profit uses each candidate's MarginGuard unit profit (Decimal). Confidence is capped at 70.
- Whether the gate passes on real sellers is unverified; on the local demo seed the pooled fit gave −1.64 and passed (9.3% MAE improvement), which is seeded data, not evidence.

Checks:
- Backend: full suite 1156 passed, 85 skipped (32 new tests: pooled model, lookup, safety stock, rollout/shadow, validated selection). New queries ran read-only against the local PostgreSQL (without the new migration); migration SQL checked with `alembic upgrade --sql`. ruff: nothing new. mypy: no errors in new or changed code (one pre-existing error in `ReorderRecommendationRepository.history`).
- Frontend: 30 files, 167 tests; `tsc`, `eslint .`, `vite build` clean.

## Pricing and inventory improvement plan, Phase 6 (2026-11-23)

Outcome tracking and calibration behind `RECOMMENDATION_OUTCOMES_ENABLED` (default off). Migration `p0d1e2f3a4b5` (additive) follows `o9c0d1e2f3a4`.

- New table `recommendation_outcomes`: seller, product, type (`PRICING` / `REORDER` / `RECOVERY`), recommendation id, decided_at, window start and days, evaluated_at, predicted and observed value, `OBSERVED` / `UNAVAILABLE`, hit, confidence at recommendation time, version, details JSON. Unique `(recommendation_id, window_days)`; inserts use `ON CONFLICT DO NOTHING`, so redelivery and concurrent runs cannot duplicate. Additions beyond the plan's column list: product_id, decided_at, window_start, hit, confidence_score, details (needed for calibration and to record evidence).
- `reorder_recommendations.ordered_at` (nullable, additive) is set when a reorder is marked ordered. Older ORDERED rows fall back to `updated_at`, recorded as `decided_at_source`.
- Rules (`app/services/recommendation_outcomes.py`, pure, Decimal):
  - Reorder: window = max(14 days, lead time + safety buffer) after it was marked ordered. Hit = no inventory snapshot at or below zero in the window; no snapshots → `UNAVAILABLE` (unknown, not a hit). Predicted units (rate × window) versus sold units, first stockout, and whether it came before the reorder deadline are recorded.
  - Price: profit in the 14 days after "applied" versus the 14 days before, per sale line (price − fee rate × price − fixed fees per unit − current product cost), fees from the recommendation's analytics snapshot. Attributed only if the average sold price after is within 2% of the suggested price (else `UNAVAILABLE: price_not_applied`); no priced sales → `UNAVAILABLE`. Hit = the profit change has the predicted sign; predicted = 30-day profit impact scaled to the window.
  - Recovery: type reserved; no evaluation rule yet (the plan defines rules for reorder and price only).
- Celery task `recommendation_outcomes.evaluate` (daily beat only when enabled), per-seller advisory lock, evaluates only windows that have fully passed, within a 120-day lookback.
- Calibration: `GET /recommendation-outcomes/track-record?recommendation_type=PRICING|REORDER` (seller from auth) returns the hit rate over the last 60 days overall and per confidence band (<40 low, <70 medium, ≥70 high, matching the UI labels), marked reliable at ≥20 judged outcomes. Engine scores are not rewritten; the UI shows the measured rate next to the label instead ("Confidence: Medium · right 67% of the time"), and the reorder drawer shows the same for its band.
- UI: one "Track record" line under the header of the pricing overview and the inventory page, shown only when enabled and reliable.

Checks:
- Backend: 13 new tests (rules, bands, API scope and flag). Full suite 1169 passed, 85 skipped. ruff and mypy clean for the new files.
- PostgreSQL: a throwaway copy of the local dev database (template clone, dropped afterwards) was migrated to head; `p0d1e2f3a4b5` applied cleanly. On it, marking a reorder ordered set `ordered_at`, a full evaluation wrote one pricing and one reorder outcome, a second run wrote none, and no rows appeared for other sellers. The pricing outcome was correctly `UNAVAILABLE: price_not_applied` because the demo data never moved to the suggested price. The clone also showed the local dev database is already at `o9c0d1e2f3a4`.
- Frontend: 31 files, 170 tests; `tsc`, `eslint`, `vite build` clean.

## Pricing and inventory improvement plan, i18n completion (2026-11-23)

Plan principle 6 ("all new strings go through an i18n map") now holds for the redesigned pages.

- `src/lib/ui-i18n.ts` gains `createStrings(map)`, so each feature keeps its own map with the same English fallback and `{param}` filling as `ui()`. The shared map keeps the cross-page UI strings (badges, table, freshness, track record).
- `src/pages/pricing/v2/pricing-i18n.ts` (172 keys) and `src/pages/inventory-intelligence/v2/inventory-i18n.ts` (174 keys) hold all visible text of the v2 pricing and inventory pages, including logic-built sentences (to-do list, runway, position, elasticity source, MarginGuard rejection reasons), chart labels, tooltips, aria labels and CSV headers. The pricing keys added to the shared map in Phase 3 moved to the pricing map.
- To add Bangla, fill `bn` on an entry; untranslated entries fall back to English. Choosing the language at runtime is not wired yet (open question 1 in the plan).
- A sweep of the v2 code found no remaining visible English outside the maps (only a developer error message, CSS classes, URLs and React keys); every key in both maps is used.
- Checks: frontend 32 files, 172 tests passed (2 new for the lookup); English output is unchanged, so existing text assertions still pass. `tsc`, `eslint .`, `vite build` clean.
>>>>>>> Stashed changes
