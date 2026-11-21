# Task 11 · CatBoost demand forecasting

Task 11 adds a CPU-only, offline training and evaluation path. It does not add a FastAPI route, Celery task, scheduler entry, feature flag, recommendation input, or database migration. A trained model cannot affect live pricing, inventory, reorder, dead-stock, or general recommendation decisions.

## Dependency and execution environment

The application Dockerfile currently uses a floating Playwright image for the API and general Celery worker. CatBoost is intentionally absent from that image and from `backend/requirements.txt`. Training uses `backend/Dockerfile.training`, CPython 3.14, `libgomp1`, explicit CPU thread limits, and the fully pinned `backend/requirements-training.txt` set. The training image does not install CUDA or request CatBoost GPU execution.

CatBoost 1.2.10 was selected because it publishes CPython 3.14 binary wheels for macOS universal2 and Linux manylinux2014 on both x86-64 and ARM64. Local verification used macOS ARM64, CPython 3.14.4, and the pinned NumPy 2.4.6, pandas 3.0.3, and SciPy 1.17.1 runtime. The dependency smoke performs a small CPU Poisson fit and validates a finite, nonnegative prediction. Linux wheel resolution is checked independently for both deployment architectures. A container build remains a required release check when a Docker daemon is available; this workspace has no Docker or Podman executable.

```sh
cd backend
python -m pip install --only-binary=:all: -r requirements-training.txt
python -m scripts.verify_catboost_environment
```

The dedicated image can be built and exercised without starting an API or a general-purpose worker:

```sh
docker build -f backend/Dockerfile.training -t bazarsync-forecast-training backend
docker run --rm --cpus=2 --memory=4g bazarsync-forecast-training
```

## Model design

The pipeline trains one direct `CatBoostRegressor` for each 7-, 14-, and 30-day total. Direct models match Task 9's explicit horizon targets and permit horizon-specific validation and rejection. The fixture validates this initial architecture. A direct-versus-multi-step comparison on representative historical data remains unmeasured.

The [Phase 4 audit](phase-4-release-readiness.md) supersedes the original fixture comparison below for release decisions. The training path now restricts CatBoost fitting and holdout scoring to regular verified histories, and it compares against the Task 12 inference fallback on those same rows. Optional `baseline_policy` points to an earlier seller-scoped policy frozen before all replay origins. Each run records the input hashes and timestamps in `lineage.json` and binds its digest into the evaluation and model metadata.

The bounded candidate set compares RMSE, MAE, Poisson, and Tweedie (`variance_power=1.5`) at depth 4, plus one depth-6 RMSE candidate. Every candidate uses the same deterministic seed, no bootstrap sampling, zero random strength, CPU execution, and bounded threads. Rolling validation chooses the lowest MAE candidate and median early-stopped tree count. This is deliberately not a large grid search. Count-oriented losses are candidates, not assumptions; a regression loss can win independently for each horizon.

Task 9's version and schema digest are mandatory. Numerical nulls remain IEEE NaN for CatBoost's native missing-value handling. Category, brand, currency, competitor-market signature, and quality flags are native categorical columns with explicit missing tokens. CatBoost processes the rows in chronological order and derives categorical counts from the training pool. Competitor price summaries use the product's known offer currency. Counts, ages, and market signatures retain evidence from all observed groups. The feature names and categorical set are written into every model's metadata.

## Chronological training and holdout policy

Input cases use the same archived seller-scoped source snapshots and mature Task 8 outcomes as the Phase 3 backtest. The command rebuilds each Task 9 training example through `ForecastFeatureBuilder`, preserving training/inference parity.

For each horizon:

1. Sort by prediction business date; never shuffle or randomly split rows.
2. Reserve the latest configured prediction dates as the final untouched test period. Dates with missing labels still count toward this period.
3. Admit a development row only when its target ends before the test start date and the label extract was available before the first test origin. Overlapping targets and late label extracts are excluded.
4. Apply both checks at each validation boundary when constructing expanding rolling-origin folds inside development data.
5. Tune candidates on validation folds only. Fit the serialized model on eligible development rows with the chosen fixed tree count. Never refit on the final test labels.

Seller scope, unique product/origin/horizon keys, complete eligible targets, post-origin outcome maturity, Task 9 schema identity, and target-calendar shape are validated before training. Insufficient data produces an explicit `INSUFFICIENT_DATA` result and no model file for that horizon.

## Evaluation and selection

The report contains CatBoost and Phase 3 baseline MAE, WAPE when total actual demand is positive, MASE when an in-sample scale is positive, and signed bias by horizon, category, and Phase 3 cohort. Per-group scored row counts show where a model or baseline abstained. The manifest accepts a Task 10 `baseline_config`. Set `enable_statsforecast` to true to include the optional intermittent benchmarks in an environment with the [Task 10 StatsForecast installation](task-10-statistical-forecasts.md).

CatBoost receives `SELECTED` for a horizon only when its untouched-test MAE is strictly lower than the best Phase 3 baseline scored on the same full set of rows. Otherwise the result is `BASELINE_RETAINED`. A synthetic report always sets `production_selection_allowed=false`. Production selection requires an authorized `historical_holdout` manifest and a documented improvement.

The archived synthetic run trained and loaded all three models. Phase 3 baselines won all three holdouts. CatBoost MAE was 14.2038, 29.0016, and 62.2398 units at 7, 14, and 30 days. The best full-coverage baseline MAE was 0, 0.75, and 3.75 units on the same rows.

## Output validation and serialization

Each `.cbm` model has adjacent metadata recording the seller, horizon, CatBoost and Python versions, platform, Task 9 schema/version, ordered features, categorical columns, parameters, loss, origin range, row count, evaluation scope, holdout decision, and SHA-256 model digest. Writes use temporary files and atomic replacement.

The loader checks seller scope, dependency version, feature schema, model checksum, horizon, and exact inference shape. A cold start returns no estimate with `INSUFFICIENT_FEATURE_HISTORY`. A model exception, checksum mismatch, NaN, infinity, or negative prediction raises an error; none is converted to a zero-demand forecast. A reliable learned zero remains valid.

## Training command

The manifest follows the Phase 3 archived-case shape and adds `scope` plus an optional training configuration:

```json
{
  "scope": "historical_holdout",
  "cases": [
    {
      "forecast_origin": "2026-09-01T06:00:00Z",
      "snapshot": "origins/2026-09-01.json",
      "outcomes": "outcomes/2026-09-01.json"
    }
  ]
}
```

Run from `backend` in the dedicated environment:

```sh
python -m scripts.train_catboost_forecasts \
  --seller-id <authorized-seller-uuid> \
  --manifest /private/seller-scope/training-manifest.json \
  --output-dir /private/seller-scope/catboost-run-2026-11-16
```

The operator boundary must authorize the seller and protect both source and output locations. Use a new run directory under an existing private parent directory. The Phase 3 audit found no eligible seller history in the configured local database. The checked Task 11 report uses archived synthetic fixtures, with four scored test rows per horizon.

## Verification artifacts

- `artifacts/task-11-synthetic/evaluation.json`: chronological synthetic evaluation with explicit non-production scope.
- `artifacts/task-11-synthetic/*.metadata.json` and `*.cbm`: loadable smoke models for all three horizons.
- `artifacts/task-11-dependency-smoke.json`: actual local dependency and CPU training smoke result.

Release verification must still build and run `Dockerfile.training` on the deployed container platform and repeat the historical holdout evaluation on authorized seller archives. Do not enable any live consumer as part of that check.
