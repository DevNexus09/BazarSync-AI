# Task 15 · Forecast-assisted dynamic pricing

## Decision rules

The specialized pricing endpoint and DecisionOrchestrator share the Task 15 evaluator. The existing generator emits the current-price anchor, increments near the current price, the guard's minimum safe price, and points drawn from verified competitor prices. The generator applies marketplace rounding and the configured change band. MarginGuard evaluates each exact price using the seller's effective product and fee policies, costs, margin and unit profit requirements, absolute price bounds, permitted changes, and increment. The audit records the unit economics and every rejected quote. `constraint_safe_candidate_prices` lists the tested points that passed those checks.

Three evidence records describe different questions.

| Evidence | Meaning |
| --- | --- |
| `baseline_demand_forecast` | A seller-scoped approved 30-day model forecast of product-level net units sold under the observed catalog and history. The record includes model release, feature version, cutoff, forecast origin, horizon, and uncertainty. The point-to-current-stock comparison is a risk signal. Task 14 currently supplies an uncalibrated CatBoost point forecast. |
| `historical_price_demand_association` | Descriptive net sales grouped by observed daily transaction price for BDT sales attributed to Daraz. Sample counts, separate base-price edit days, and relative price span show the available variation. The descriptive review screen requires at least four edit days, three price levels, 28 usable priced days, and 5% price spread. |
| `price_response` | Unknown until seller and product price-response evidence supports candidate quantities. An evidence-supported response would require reliable price variation, comparison under comparable conditions, and separate out-of-time validation with uncertainty and support over the proposed price range. Task 14 model approval and the existing historical regression do not provide that validation. |

Historical checks flag recorded promotion results and unknown promotion coverage, weekly seasonality in verified sales, stockouts and unknown inventory observations, incomplete sales coverage, shifts across consecutive 28-day periods, and possible concurrent competitor movement when aggregate prices around a recorded seller edit can be compared. An aggregate movement can also reflect a change in the listing mix. Transaction-price averages are observable only for priced sales and can reflect differences in order mix.

The enabled path returns `HOLD` with insufficient price-response evidence. Net quantities, revenue, contribution and uplift for alternative prices are unavailable. Unit contribution in each MarginGuard verdict follows the applicable fee terms and uses Decimal arithmetic. The audit has an explicit null `recommended_target_price`. The specialized response retains the current price in the required legacy `recommended_price` field for HOLD. RAG and Copilot read the explicit target when it exists. Orchestration preserves the candidate audit and can still select independently supported inventory and recovery advice.

## Configuration and rollback

Set `FORECAST_ASSISTED_PRICING_ENABLED=true` on the backend API and worker to opt in. The general worker uses the feature through the existing DecisionOrchestrator configuration. The specialized endpoint requires its existing pricing analytics snapshot.

To attach a baseline point forecast, also set `FORECAST_ML_MODE=enabled`, configure the absolute `FORECAST_ARTIFACT_ROOT`, and provide the seller registry pin in `FORECAST_REGISTRY_SHA256`. A deployment process has one registry pin. The directory, pin, and approval must be managed by the operator under the [Task 14 artifact contract](task-14-forecast-inference.md). A supported approved release must include the 30-day artifact and the product must meet the live-history and regime checks. Set `FORECAST_INFERENCE_PYTHON` to the absolute executable in the dedicated inference environment when the native dependencies are separate from the API and worker interpreter. The parent launches the existing isolated native prediction subprocess. No application dependencies are added.

Pricing history is read in an independent, read-only, repeatable-read PostgreSQL transaction. It uses a 90-day window, statement timeouts, and one concurrent capture and inference per process. Busy capture, unavailable history, disabled or shadow inference, and unusable model releases leave the baseline unavailable and preserve the conservative HOLD. No pricing request trains a model.

Disable `FORECAST_ASSISTED_PRICING_ENABLED` to restore legacy generation. The enabled path has a distinct `forecast-pricing-v1` formula version. Replay returns the existing result for the same seller, product, analytics snapshot, and objective. Generate a new analytics snapshot to reevaluate specialized pricing with newly available evidence. Both versions remain in history. Task 15 requires no schema changes. Generation and acknowledgment are advisory and do not publish price or stock changes.

## Verification

The Task 15 suite passed all eight cases on Python 3.14.4. It covered the specialized API and PostgreSQL evidence capture, seller scope, replay and acknowledgment, RAG and Copilot rendering, orchestrated HOLD, flag rollback, guard rejection, model availability, and high and zero baseline forecasts. The focused pricing, forecasting, orchestration, inventory, and RAG suite passed 331 cases with three optional StatsForecast skips. A separate run with StatsForecast 2.1.1 passed 31 cases, including those three.

The full backend suite passed 993 tests and 809 subtests, skipped the same three optional cases in the application environment, and reproduced the 24 existing Copilot orchestrator failures.

Ruff passed for the changed Python files. Mypy passed for forecast evidence, inference, and orchestration. A wider scoped mypy run reported 13 existing session and return type issues in the dynamic pricing service. Verification used disposable PostgreSQL and Redis, seeded forecasts, and the existing native inference regression. Real-seller price-response validation and a production Linux deployment remain unverified.
