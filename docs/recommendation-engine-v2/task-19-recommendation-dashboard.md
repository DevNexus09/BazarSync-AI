# Task 19 seller recommendations dashboard

Implemented and verified on 19 November 2026.

## Seller experience

The existing recommendations route, navigation, product selection and Generate Recommendation workflow remain the entry points. The primary card retains the approved action, confidence enum and Bangla explanation. Optional evidence adds observation timestamps, competitor freshness at generation, inventory and sales evidence, an approved target price and explanations for low confidence, limited sales history, stale competitors and MarginGuard rejection.

Generation announces Not generated, Queued, Processing, Completed, Failed and Insufficient evidence. Insufficient evidence describes a completed recommendation whose saved reasons do not support an action. The durable status queries stop polling at COMPLETED and FAILED. Discovery returning no job also stops polling. Status errors have an explicit retry control. Generation errors retain the retryable Generate workflow. Older backends keep the bounded legacy latest-result polling path. A newer saved result takes precedence over an older completed job. When creation times match, the most recently fetched result wins, including a validated explanation added after job completion. Final recommendation events refresh the authenticated seller's recommendation and job queries.

Seller-session failures disable retries for 401 responses, hide recommendation content and generation controls, and offer sign-in. Query keys and remembered submission IDs include the seller and product. Submission retries preserve unresolved idempotency keys and double-click coalescing.

The demand section uses three compact cards for 7, 14 and 30 days. Missing horizons remain unavailable. Forecasts identify expected net units sold, method, model version, approved active/previous source and data cutoff. Reorder insights appear for selected or supporting reorder candidates. The optional pricing comparison retains constraint outcomes and rejection reasons in an accessible native disclosure. Supporting advice includes compatible recovery strategies and keeping the base price while replenishing.

## Backend compatibility and evidence rules

The current generic response lacked the richer evidence needed by the dashboard. Task 19 adds an optional, typed `dashboard_evidence` summary to the same latest and durable-job result responses. The existing seller ownership checks protect both surfaces. The summary is a projection of the persisted recommendation snapshot. It performs no forecasting or business recomputation.

The summary omits seller identifiers, internal decision inputs, full candidate snapshots, policy records and model artifacts. A record without supported metadata retains its historical response. Disabled summaries are omitted from JSON. Invalid optional evidence falls back to the original readable recommendation. The frontend validates the optional summary with the existing Zod dependency.

Only recorded approved CatBoost forecast envelopes from active/previous model selections are projected. Forecast scope must match the persisted candidate's product and seller. A supported horizon must already exist in the snapshot. The UI never extrapolates between horizons.

Current forecast intervals have empirical_unvalidated, uncalibrated or insufficient_data status. They cannot populate a calibrated interval. The UI displays calibrated bounds only when the API explicitly supplies calibrated status and ordered bounds containing the point estimate. The current projection supplies no such bounds. Validated reorder upper demand bounds retain their own label. Stockout probability remains unavailable because the current planning evidence supplies no calibrated stockout probability.

Observed values, model predictions and heuristic estimates have separate labels. Missing, blank and nonfinite numbers become unavailable. Observed zero remains zero. Legacy revenue opportunity is labelled a heuristic estimate, and a zero placeholder displays as unavailable. Enhanced evidence suppresses that legacy opportunity card. Exact recommended and compared prices use en-BD BDT formatting with up to two decimal places. Existing market metrics retain the shared formatting convention.

All controls remain advisory. Native disclosure keyboard navigation, live status announcements, labelled inputs and alert regions support accessibility. The layout stacks on mobile and uses the existing Tailwind breakpoints, theme and UI components. The compact horizon cards need no chart or dependency addition.

## Rollout and rollback

Both flags default to false.

- Set backend `RECOMMENDATION_DASHBOARD_EVIDENCE_ENABLED=true` to expose the saved evidence summary.
- Set frontend build setting `VITE_RECOMMENDATION_DASHBOARD_V2=true` to render the optional sections. Rebuild the frontend after changing it.
- Existing decision, explanation, forecast and orchestration flags control what evidence is recorded. The dashboard flag does not enable them.
- Disable either dashboard flag to restore the basic presentation. Disabling the backend flag restores its previous response fields. Older records remain readable.

Deploy backend support before enabling the frontend flag. The frontend tolerates responses with absent, unknown or malformed optional evidence. A model's actual approval and evidence availability determine the visible horizons.

## Verification

All required frontend commands passed.

| Check | Result |
| --- | --- |
| `npm run lint` | Passed |
| `npm run typecheck` | Passed |
| `npm test -- --run` | 106 tests passed across 22 files |
| `npm run build` | Passed |
| Backend recommendation, durable-job, orchestration, Phase 2 integration, Bangla explanation and new summary tests | 33 passed |
| Scoped Ruff checks | Passed |
| Scoped backend mypy with `--follow-imports=silent --ignore-missing-imports` | Passed for the new summary service and public response schema |
| `git diff --check` | Passed |

Frontend additions exercise legacy and v2 responses, loading, errors and retry, empty history, a completed job, queued/processing generation, missing horizons, zero demand, low confidence, stale evidence, blocked pricing, malformed evidence, disabled flags, responsive layout classes and session expiration. API adapter tests cover null/blank/nonfinite metrics, preserved financial precision and propagated 401s. Existing polling tests cover terminal failure, persisted job restoration, idempotency and replay.

PostgreSQL integration used unique disposable schemas on the local PostgreSQL server with `BAZARSYNC_TEST_POSTGRES_URL=postgresql+psycopg2:///postgres`. The tests exercise API → durable worker → persisted recommendation → job/latest responses, flag rollback and foreign-seller denial. Initial attempts used an absent test URL and an unavailable psycopg driver. The final psycopg2 run passed all 33 tests.

A temporary Chrome harness served the production bundle with synthetic API fixtures. At 375px it verified vertically stacked horizon cards and no document overflow. At 1280px it verified three horizon columns. Browser checks also exercised generation with an idempotency key, Processing and completed evidence states, Enter-key expansion of pricing comparisons, and no further polling after completion. Screenshots were visually inspected. This is fixture-based presentation verification. Live seller forecast/model availability was not evaluated in this task.

The successful build reports CSS `@theme`/`@utility` minification warnings, an outdated Browserslist database and a large output chunk. The test runner also reports Node's experimental localStorage warning in existing suites.
