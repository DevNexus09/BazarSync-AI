# Task 13 · Forecast uncertainty

The offline interval service augments `ForecastResult` and `MLForecastResult` with an optional `prediction_interval`. The point remains in `expected_units`, and `model_version` continues to identify the point forecaster. The interval carries its bounds, nominal level, method, calibration origin period, outcome availability, sample count, and reliability status. Plain forecast serialization omits the interval field when no augmentation was requested.

## Method and interpretation

The first method uses the empirical quantile of absolute out-of-time forecast errors. This works with the existing statistical and CatBoost point contracts and uses the same expected-unit scale at every step. Quantile regression would require training and validating lower and upper quantile models. Time-series conformal methods such as EnbPI and SPCI were reviewed conceptually. Their guarantees depend on the method and its assumptions about temporal errors. Task 13 uses neither approach and adds no dependency. Local verification used Python 3.14.4, NumPy 2.4.6 and scikit-learn 1.8.0. MAPIE was outside the compatibility and implementation work. [EnbPI paper](https://proceedings.mlr.press/v139/xu21h.html) · [SPCI paper](https://proceedings.mlr.press/v202/xu23r.html)

Each residual profile is specific to one seller, product, horizon, regime, actual selected method, and model and feature versions. The frozen caller context also identifies baseline settings, the optional StatsForecast runtime and any Task 12 method policy. CatBoost profiles additionally bind the model checksum and feature schema checksum. A fallback forecast can receive an interval from a profile for that fallback method. It cannot borrow the winning model's residuals.

Calibration requires at least 20 nonoverlapping, complete target windows within the matching profile and enough observations for the requested rank. Given `n` retained residuals and nominal level `p`, the radius is the larger of one unit and the residual at rank `ceil((n + 1) × p)`. If the rank exceeds `n`, the service omits the interval. Bounds are the point plus or minus the radius, with the lower bound clipped at zero. The one-unit floor prevents a degenerate interval when all observed residuals are zero. It is a conservative engineering floor, and coverage can still deteriorate under changes in demand or data quality.

| Interval status | Meaning |
| --- | --- |
| `empirical_unvalidated` | A matching profile has sufficient historical residuals for an empirical interval. The nominal level is a target. Consult the separate future holdout report for achieved coverage. |
| `uncalibrated` | The artifact is absent, its forecasting context changed, or the forecast predates the calibration boundary. Bounds are absent. |
| `insufficient_data` | The point is unavailable or no sufficiently supported profile matches the point. Bounds are absent. |

## Chronological evaluation

Choose a Dhaka business date as the first test origin. Before that date, use only targets whose last day and outcome-extract cutoff precede the test boundary. Thin calibration rows chronologically within each profile so their target windows do not overlap. Residuals come from archived pre-origin snapshots and complete, eligible Task 8 net-sales records. A fixed Task 12 method-selection policy, if supplied, must have been available before every calibration and test origin. The CatBoost contract can be augmented separately from archived predictions. Supply only predictions from an eligible, frozen model that was available before the corresponding origin.

The later-period report counts eligible outcomes, issued intervals, scored intervals, and excluded calibration rows. It reports empirical coverage, average scored width in units, underprediction frequency (actual above upper bound), and overprediction frequency (actual below lower bound), grouped by horizon and by regime within horizon. Denominators are the scored rows with both a complete outcome and an interval. Missing outcomes and unavailable intervals do not count as hits or misses. Adjacent test windows can overlap, so the metrics are descriptive and do not estimate independent trials.

Fixture evaluation deliberately includes a volatility increase. The 7-day regular-demand fixture covered one of three unseen targets at a 90% nominal level, with one miss on each side. This verifies that a miss is reported even when the interval has enough calibration rows. Real seller coverage has yet to be measured.

## Running the offline replay

Run from `backend` using the [Task 10 case manifest](task-10-statistical-forecasts.md) under the authorized seller's archive. Keep report and calibration artifacts in that seller's private storage.

```sh
python -m scripts.backtest_forecast_intervals \
  --seller-id <authorized-seller-uuid> \
  --manifest /private/seller-scope/interval-cases.json \
  --test-start 2026-10-01 \
  --level 0.90 \
  > /private/seller-scope/interval-report.json
```

Use `--policy` for an earlier Task 12 policy and `--statsforecast` in the matching optional benchmark environment. The command replays the regime forecaster and evaluates intervals without retraining it. Load the report with `IntervalBacktestReport.model_validate_json` and pass its calibration and the same context to `ForecastIntervalService`. For Task 12, derive the context with `regime_forecast_context` and use the regime returned by the current forecast. For an offline CatBoost replay, `backtest_intervals` accepts the existing ML point results with the verified outcomes and their extract cutoffs. The caller supplies a stable forecasting context for that replay.

Interval augmentation is opt-in at the service boundary. The recommendation API, Celery workers, and decision logic continue to consume their existing inputs.
