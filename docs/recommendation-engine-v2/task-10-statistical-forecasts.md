# Task 10 · Statistical demand benchmarks

`StatisticalForecastService` consumes a single-product Task 9 origin snapshot. It uses the feature builder's point-in-time validation and calendar-aligned eligible sales series from Task 8. The result is a nonnegative expected total for the 7-, 14-, or 30-day horizon. As in Task 9, target day one is the first Dhaka business day after the feature date. This estimate uses recorded net sales as a proxy for demand. The backtest keeps realized net sales in a separate outcome field and makes no adjustment for unmet demand.

## Forecasts and fallback

The default lookback is 90 business days, bounded at 366. Use the contiguous eligible history ending on the day before the feature date. A missing date, unknown stockout state, or observed stockout breaks the series. Explicit zeros contribute normally. An artifact that marks invalid or negative sales eligible is rejected. The service returns a null estimate and `INSUFFICIENT` below the configurable 14-day minimum by default. Reliable all-zero history can produce an observed-evidence forecast of zero.

| Candidate | Rule |
| --- | --- |
| Naive | Repeat the latest eligible daily value over the horizon. |
| Weekly seasonal naive | Repeat the last weekly profile on the corresponding Dhaka weekdays. Require at least 21 contiguous days and in-sample lag-7 error at most 80% of lag-1 error over identical days. Require positive lag-1 error. The feature date is skipped when selecting target weekdays. |
| Moving average | Use the mean of the last seven eligible days as the daily forecast. |
| Simple exponential smoothing | Smooth daily sales with fixed alpha 0.3 after at least 14 eligible days, with fewer than 50% zeros. |
| Croston Classic, Croston SBA, Croston Optimized, TSB, and ADIDA | Optional StatsForecast comparisons. Require at least 28 contiguous days, at least 50% zeros, and at least two positive observations. TSB uses 0.2 for both smoothing parameters. |

The thresholds are configurable via `BaselineConfig`. Automatic selection prefers qualified weekly seasonal naive, then moving average. If the configured minimum is met but the moving window is too short, it returns a labelled naive fallback. Explicit model requests report inapplicability or unavailability without substitution. The automatic rule uses only origin history and does not select a winner from test outcomes.

`ForecastResult` carries the requested and applied model, model and feature versions, seller/product scope, origin, cutoff, target range, history length, estimate, evidence status, and fallback reason. Its timestamps are UTC. Set `generated_at` explicitly to replay identical serialized rows. The backtest uses the simulated origin as the generation time.

## Running the offline comparison

Use an authorized operator context and one seller per invocation. Archive Task 9 origin snapshots before each prediction and pair them with separate Task 8 outcome extracts for the same owned product. Capture up to 90 preceding days for the default lookback. Task 9 capture-time checks also apply to backtests with retroactive extract cutoffs. Outcome files may cover several origins for the same product. The evaluator reads them independently of model selection.

An evaluation manifest contains one offset-aware origin per product and Dhaka business date. The evaluator rejects conflicting eligible outcomes for the same product-day across the supplied extracts. Paths resolve relative to the manifest. An optional `config` object overrides `BaselineConfig` fields.

```json
{
  "config": {"minimum_history_days": 14, "lookback_days": 90},
  "cases": [
    {"forecast_origin": "2026-11-10T08:00:00+06:00", "snapshot": "inputs/nov-10.json", "outcomes": "inputs/outcomes.json"},
    {"forecast_origin": "2026-11-17T08:00:00+06:00", "snapshot": "inputs/nov-17.json", "outcomes": "inputs/outcomes.json"}
  ]
}
```

From the backend directory, use the authorized seller UUID in `SELLER_ID`.

```sh
python -m scripts.backtest_statistical_forecasts \
  --seller-id "$SELLER_ID" --manifest /private/seller-export/evaluation.json \
  > /private/seller-export/comparison.json
```

Add `--statsforecast` to evaluate the five intermittent candidates. Install StatsForecast into a disposable evaluation environment with the backend dependencies available. The service pins the benchmark implementation to version 2.1.1 and reports the NumPy, SciPy, and CoreForecast versions used.

```sh
python -m pip install --only-binary=:all: statsforecast==2.1.1
```

Python 3.14.4 ran the optional models locally. Wheel-only resolution succeeded for Linux x86-64 and ARM64 CPython 3.14. The production image is based on Playwright's floating `python:latest` tag. These checks cover the isolated optional evaluation environment and wheel availability. StatsForecast is outside the application image requirements. [StatsForecast release files](https://pypi.org/project/statsforecast/2.1.1/) · [Model reference](https://nixtlaverse.nixtla.io/statsforecast/src/core/models.html)

## Reading the report

Each model and horizon is evaluated on the same supplied origins. The report retains chronological folds and produces aggregates for the whole set and each represented cohort. It counts forecasts, mature eligible targets, scored pairs, and scores with a valid MASE scale. Read coverage alongside error metrics because candidates can abstain on different folds. The realized total is null if any horizon day lacks an eligible outcome. Adjacent origins can have overlapping target windows.

Cohorts are assigned from origin information in this order. Use `new` for products under 30 business days old, `unknown` when history is insufficient, `zero_demand` for all-zero history, `intermittent` for a zero fraction of at least 50%, then `high_volume` for mean daily sales of at least five units and `low_volume` otherwise.

| Metric | Definition |
| --- | --- |
| MAE | Mean absolute error of predicted versus observed horizon totals. |
| WAPE | Sum of absolute errors divided by sum of observed totals, multiplied by 100. Null when the sum of observed totals is zero. |
| MASE | Mean absolute scaled error. For each origin, scale by the mean absolute difference between adjacent, non-overlapping in-sample blocks of horizon length. Blocks align to the end of the eligible history. Use only folds whose scale is positive. |
| Bias | Mean predicted total minus observed total, in units. Positive indicates overforecasting. |

The automated evaluation uses isolated fixtures to verify the calculations. Model comparisons for real products depend on the seller's archived origins and eligible outcomes.
