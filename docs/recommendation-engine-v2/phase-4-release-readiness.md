# Phase 4 ML release-readiness audit · 17 November 2026

**CatBoost and empirical prediction intervals are a no-go for production at 7, 14, and 30 days.** Keep the statistical fallback and insufficient-data behavior available in isolated forecasting. Live recommendations continue on their existing path. No seller release was approved.

The configured loopback PostgreSQL database was checked in a read-only transaction. It contained one product and zero rows in sales, sales coverage, inventory history, and product price history. The completed evaluations below use reproducible synthetic archives. Real seller MAE, coverage, and operational suitability remain unmeasured. [Machine-readable audit, including source hashes, full metrics, and timings](artifacts/phase-4-synthetic-audit.json)

## Point forecast results

The replay used 24 archived origins across two fixture products. At each horizon, 12 intermittent rows were excluded from the CatBoost training and scoring cohort by the same regular-demand gate used in inference. There were 10 usable development rows and two untouched, nonoverlapping holdout rows at each horizon. The matched comparison included the Task 12 fallback and Phase 3 native candidates. Validation selected the MAE objective for all three models.

| Horizon | CatBoost MAE | Best matched baseline | Baseline MAE | CatBoost WAPE | Baseline WAPE | CatBoost bias | Decision |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 7 days | 8.8211 | Task 10 Auto and moving average tied | 0.0000 | 24.5031% | 0.0000% | +8.3862 | Baseline retained |
| 14 days | 18.0098 | Task 12 regime fallback | 0.1615 | 24.5031% | 0.2198% | +17.1219 | Baseline retained |
| 30 days | 38.5923 | Task 12 regime fallback | 0.3462 | 24.5031% | 0.2198% | +36.6897 | Baseline retained |

MAE and signed bias are in units. The 7-day MASE was 8.7124 for CatBoost and 0.0000 for either winning baseline. The 14- and 30-day MASE values were undefined because the fixture lacked a positive scale at those horizons. These scores describe the fixture only. All three CatBoost releases lack sufficient historical evidence for production.

## Prediction interval results

A separate later synthetic archive used the actual frozen CatBoost binaries and the Task 12 statistical point forecast. Each matching profile used 20 nonoverlapping calibration windows. The fixed split reserved three later targets per horizon, including a volatility increase. Coverage was one of three at each horizon for both paths at a nominal level of 90%. Each path missed once above and once below its bounds at every horizon.

| Horizon | CatBoost mean width | Statistical mean width | Empirical coverage, both paths |
| --- | ---: | ---: | ---: |
| 7 days | 46 units | 42 units | 1/3 |
| 14 days | 98 units | 84 units | 1/3 |
| 30 days | 210 units | 180 units | 1/3 |

The very small holdout checks scoring and exposes behavior under the fixture's shift. These intervals remain empirical and unvalidated for sellers. The focused suite also covers intermittent and all-zero width behavior, missing calibration and outcomes, wrong horizon, unavailable point estimates, and seller scope.

## Audit findings and fixes

| Area | Evidence and change |
| --- | --- |
| Input lineage | The training command records exact manifest, snapshot, outcome, and optional baseline-policy digests in `lineage.json`, with captured and extract timestamps and dataset versions. The evaluation and resulting model metadata bind the lineage digest. These hashes support replay from preserved archives. Data origin and the production-vs-synthetic designation still depend on trusted operator provenance. |
| Schema compatibility | Both loaders use the same Task 9 encoder. Promotion and native runtime pin its version separately from the Task 9 schema digest. All three restored CBMs passed the feature-name and categorical-index checks. Predictions matched the Task 11 loader in five calls per horizon. |
| Chronological splits | Training and rolling validation exclude crossing targets and labels unavailable at the boundary. Cold starts still reserve prediction dates even when no product rows exist. The promotion path requires at least three nonoverlapping holdout origins for the supported horizon, checks that the date span can contain them, and requires a full-coverage matched comparison against the deployed baseline path. |
| Sparse, declining and cold start | Sparse or declining history stays on the statistical path. Croston, TSB and ADIDA ran in the separate StatsForecast environment. Verified zeros stay distinct from missing dates and stockout censoring. Cold starts return insufficient data. |
| Integrity, rollback and isolation | The runtime verifies independently pinned registry and CBM digests. Tests reject foreign seller scopes, wrong encoder versions, unsafe paths, missing releases, and corrupt binaries. For each horizon the corrupt active artifact routed to the previous release, then to the baseline when the previous artifact was removed. These tests used an ephemeral registry with simulated approval, separate from the accuracy decision. |
| Deployment imports and pins | Offline imports previously reached application settings and could fail in an image without a database URL or JWT secret. The audit separated the shared evidence rules and verified startup without those settings or dotenv. Training and inference images now use the same CPython 3.14.4 base. The clean macOS ARM64 environment passed its CPU smoke check with CatBoost 1.2.10, NumPy 2.4.6, pandas 3.0.3 and SciPy 1.17.1. |

## Operational verification and open release gates

The local measurement timed the inference service call, including the cold native subprocess, integrity checks, load and prediction. It used five serial calls per horizon on macOS ARM64 against 14–21 KB synthetic CBMs.

| Horizon | Median wall time | Maximum wall time |
| --- | ---: | ---: |
| 7 days | 826.36 ms | 910.51 ms |
| 14 days | 762.01 ms | 805.75 ms |
| 30 days | 711.02 ms | 803.97 ms |

The OS reported a maximum child RSS of 145.33 MiB across these calls. This is a process high-water mark from the local smoke run. Linux container memory, sustained concurrency, and production latency remain unmeasured.

The focused suite passed 123 tests with disposable PostgreSQL. Its three optional StatsForecast skips were covered in a separate 48-test run. Scoped Ruff and mypy checks passed. The full pinned dependency set resolved as CPython 3.14 Linux wheels for ARM64 and x86-64. Wheel resolution did not exercise the container runtime.

The workspace has no Docker, Podman or VM runtime. Build and exercise both Linux images on the actual deployment target, including cgroup peak memory, representative artifact sizes and concurrency, cold-start and fallback latency, and timeout behavior. A real seller release additionally needs authorized historical archives with sufficient nested chronological support, a matched baseline improvement on a mature deployment-eligible holdout, and representative interval coverage before using uncertainty in decisions.

To regenerate the synthetic evidence from `backend` in the pinned environment with test dependencies installed:

```sh
PYTHON_DOTENV_DISABLED=1 PYTHONPATH=.:tests python tests/phase4_release_fixture.py
```
