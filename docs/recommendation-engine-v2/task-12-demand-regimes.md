# Task 12 · Demand regimes and sparse-history forecasts

The offline `RegimeForecastService` consumes seller-scoped Task 9 origin snapshots and optionally a Task 12 selection policy. It returns a `RegimeForecast` containing the existing `ForecastResult` contract, regime evidence, selection reason, and attempted ranked methods. The model name identifies the actual baseline or the additive `historical_mean` method. The horizon, origin, cutoff, and availability fields follow Task 10. FastAPI, Celery, and recommendation orchestration continue on their existing paths.

## Evidence and classification

The classifier validates the archived capture and uses Task 8 eligible net sales. The lookback is 90 calendar days by default and capped at 366. It reports available and contiguous days, missing dates, stockout-censored days, and other unreliable days within the catalog product's age. Frequency, actual calendar intervals between positive observations, and population variance use the uninterrupted eligible tail. Unknown observations break the tail. A verified zero contributes to the tail, its frequency, and its variance. With fewer than two positive observations the interval is unknown.

| Regime | Evidence |
| --- | --- |
| Insufficient history | Fewer than 14 contiguous eligible days, or a higher configured minimum. A tail with zero or one positive day needs at least 28 contiguous eligible days. |
| Intermittent | With sufficient history, at most one positive observation or a zero-sales fraction at or above the configured Task 10 threshold, 50% by default. The evidence distinguishes verified all-zero history. |
| Potentially declining | At least 56 contiguous eligible days. The prior 28 days must include at least 14 positive days. Each of the two most recent 14-day blocks must average at most half the prior 28-day rate. This is a sustained reduction signal. Obsolescence requires independent product lifecycle evidence. |
| Regular | Remaining sufficient histories with frequent positive observations. |

## Method selection and fallback

Fit a policy offline using the same archived case manifest as [Task 10](task-10-statistical-forecasts.md). Every candidate forecasts from its pre-origin snapshot. A case is scored only when every target day is eligible. The backtest rejects duplicate product/date origins and conflicting observed outcomes. Candidates compete with the historical mean on the same rows within each regime and horizon. A candidate qualifies only if it covers the entire scored group, achieves strictly lower MAE, and the group contains at least four origin dates with nonoverlapping target windows. Ties among qualifying candidates sort by model name. The artifact records per-method coverage and MAE, eligible origins, supporting dates, baseline configuration, optional StatsForecast versions, and the latest input availability timestamp. For an independent evaluation, replay a later archive that starts after the policy's availability timestamp.

| Regime | Candidates | Fallback |
| --- | --- | --- |
| Insufficient | None | Explicit insufficient-data status and null units. This includes a new product with no usable sales. |
| Intermittent | Seasonal naive and, with Task 10’s optional StatsForecast environment, Croston Classic, SBA, Optimized, TSB, and ADIDA. | Mean rate over the full verified tail. A sufficiently long all-zero tail goes directly to an observed-zero forecast. |
| Potentially declining | Moving average and optional TSB where the Phase 3 eligibility rules allow it. | Mean rate over the recent 28 eligible days. |
| Regular | Moving average, seasonal naive, and exponential smoothing. | Mean rate over the full verified tail. |

Inference tries the qualified candidates in rank order. A candidate that abstains or requires a different installed StatsForecast runtime is skipped. The service falls back to the product mean when no usable ranking remains, even if the optional model package is absent. The mean is in units per day and is multiplied by the requested horizon. There is no positive lower bound. The forecast and ranking expose no category-level pooling. Task 11's synthetic run retained the statistical baselines across all horizons, so CatBoost stays outside this policy. Any later comparison would need a seller-scoped artifact trained before the evaluated origins and proven on real holdouts.

Inference scans one validated product snapshot, considers a finite candidate list for one horizon, and performs no training search, database access, or network calls. Statistical candidates reuse the Phase 3 estimators on the bounded history. A policy from a different seller raises a scope error. A policy with future evidence or an incompatible baseline configuration falls back to the seller product's history.

## Running a backtest

Use the authorized seller's archived captures and mature Task 8 outcome extracts. Run from `backend` and store output in that seller's private directory.

```sh
python -m scripts.backtest_demand_regimes \
  --seller-id <authorized-seller-uuid> \
  --manifest /private/seller-scope/backtest-manifest.json \
  > /private/seller-scope/demand-regime-policy.json
```

Add `--statsforecast` in the optional Task 10 evaluation environment to include the intermittent estimators. Load output with `RegimeSelectionPolicy.model_validate_json` and pass it to `RegimeForecastService.forecast` with the seller's source snapshot and forecast origin. The policy file is an offline operator artifact and should stay with its source archive. Fixture tests cover later-origin replay, deterministic rankings, seasonal and moving-average winners, fallback after method abstention, and seller isolation. Real seller performance remains unevaluated.
