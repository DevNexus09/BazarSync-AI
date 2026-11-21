# Phase 3 verification · 16 November 2026

**Readiness decision.** The offline data and forecast paths passed validation on disposable fixtures. Real-data forecasting, ML training, and live rollout remain blocked by the absence of eligible local sales and archived forecast origins. These findings apply to the configured local development database and workspace artifacts inspected during this audit.

## Local data readiness

The audit connected only to the configured loopback PostgreSQL database, using a read-only transaction. It counted source tables without reading seller identities or transaction payloads. The historical export flag was off. The workspace contained no real seller forecast-origin or outcome artifacts for rolling evaluation.

| Question | Verified local result |
| --- | --- |
| Eligible products | **0 of 1** catalog products. The database contains two seller accounts. With no inventory history or sales coverage declarations, no product-day can satisfy Task 8 label eligibility. |
| Available sales history | **0 sales records** and **0 observed sales days**. Earliest and latest transaction dates are undefined. There are **0 sales coverage declarations**. |
| Missing-data patterns | Sales, reliable inventory, transaction prices, and recorded price changes are unavailable in the local sources. Inventory history and product price history each contain **0 rows**. An unobserved sales day cannot be counted as a zero-sales day. |
| Cold-start coverage | **1 of 1** products has no recorded sales history. That product cannot meet the default 14 contiguous eligible days. This is a history-based cold-start count. |
| Intermittent-demand coverage | **0 classifiable products** and **0 scored real-data intermittent folds**. Prevalence is unknown. An empty source cannot establish an all-zero or intermittent series. |
| Baseline accuracy | **Unmeasured** for the 7-, 14-, and 30-day horizons. There are no real-data forecast–outcome pairs. MAE, WAPE, MASE, and bias are unavailable. |

The local Alembic revision is `i3c4d5e6f7a8`. Its competitor table lacks `price_observed_at`, `stock_observed_at`, and `match_score`, which current Task 8 reads require. The audit used the actual table counts and schema inspection for local readiness, and exercised the export against the expected schema in disposable PostgreSQL. The local source schema was left at its existing revision.

## Audit findings and fixes

| Area | Finding and verification |
| --- | --- |
| Coverage and missingness | A newer correction could lose to an older declaration if it kept its original import timestamp. Tied declarations could also prove a zero by UUID order. The newest overlapping availability revision now governs, and tied conflicts leave coverage unknown. |
| Sales status and accuracy | Only completed and fulfilled lines contribute net units. Cancelled units are counted once, failed payments and test orders contribute no units, and pending lines block label eligibility. Valid returns follow the existing return and refunded/restocked counter convention. Stable source references and seller/product ownership prevent duplicate and cross-tenant attribution. When a line total is the only price evidence, the calculation now prorates the total directly and avoids a division-then-multiplication rounding error. |
| Competitor evidence | Seller, product, run, and marketplace must agree. Observation and persistence times must precede the relevant cutoff. Regression cases cover delayed publishing, missing observation timestamps, weak matches, and evidence from another seller or marketplace. |
| Historical snapshot integrity | Capture enforces a read-only PostgreSQL transaction with a stable snapshot. A regression test changes a recorded return after capture. The frozen file replays the original features, and a fresh capture of the same past window is rejected for the older origin. |
| Training and inference | Both use the same seller-scoped feature builder and archived pre-origin records. Future outcomes only enter the target calculation. Origins have identical serialized features in inference and evaluation for all three horizons. |
| Backtests | A product can contribute only one origin per Dhaka business day. Overlapping origins with conflicting eligible realized values for the same product-day are rejected. Metrics retain coverage counts and omit WAPE or MASE when their denominators are invalid. A horizon with an incomplete target remains unscored. |

## Isolated accuracy verification

The offline CLI evaluated six synthetic fixture products at two origins each. The cohorts included high volume, low volume, intermittent, all-zero, new, and a product with a history gap. The CLI emitted **360 model–origin–horizon rows** and **210 aggregate comparison groups** covering ten configured models and three horizons. Two CLI runs produced byte-identical reports. The automated test `test_phase3_fixture_rolling_origin_replay` reproduces the same design and checks order-independent replay. Fixture scores verify the mechanics of forecasting and scoring.

| Auto baseline | Forecasted and scored origins | MAE, units | WAPE | MASE, valid folds | Bias, units |
| --- | ---: | ---: | ---: | ---: | ---: |
| 7 days | 8 / 12 | 1.6250 | 9.5588% | 1.2769 on 4 | −0.1250 |
| 14 days | 8 / 12 | 1.6250 | 4.7970% | 1.6500 on 4 | −0.1250 |
| 30 days | 8 / 12 | 3.8036 | 5.2827% | 0.0000 on 2 | +0.4107 |

The two new-product origins and two history-gap origins abstained under the default rules. All five optional StatsForecast intermittent methods scored both intermittent origins at each horizon. At 14 days, fixture MAE was 0.7781 for Croston Classic, 0.7392 for Croston SBA, 0.9619 for Croston Optimized, 2.9986 for TSB, and 1.0000 for ADIDA. These values describe the fixture only. The 30-day auto MASE describes the two folds with a positive scale.

The run used Python 3.14.4, StatsForecast 2.1.1, CoreForecast 0.0.20, NumPy 2.4.6, and SciPy 1.17.1. Use the [offline backtest command](task-10-statistical-forecasts.md) with authorized archives to measure seller performance.

## Automated verification

The focused suite passed **88 tests** with disposable PostgreSQL and optional StatsForecast enabled. It exercised Tasks 8–10 and the sales import, sales analytics, inventory history, competitor snapshot, promotion, and price-history regressions. Scoped Ruff lint and formatting, mypy, and Git whitespace checks passed.

## Current ML limitations

- Point-in-time sales status and return changes cannot be reconstructed from current transactional values. Past training origins need the original captured artifacts. Older artifacts affected by ambiguous coverage should be excluded unless their historical coverage can be verified.
- Product-wide completeness needs reliable date declarations. Marketplace-only coverage is insufficient for a product-wide zero. Sales without stable source references stay outside eligible history. The schema has no distinct order identifier.
- Unknown stockout status and observed stockouts break eligible history. Positive point-in-time stock is evidence at specific observations and cannot establish continuous availability or unmet demand.
- Promotion execution and discount history remain unknown. The verified holiday catalog covers a limited set of dates. Competitor and price features depend on scope, timestamps, and reliable observations.
- Real-data cohort sizes, forecast errors, calibration, and an out-of-time model comparison are unavailable. Those measurements require an authorized data source with eligible history, archived origins, and mature outcomes.

Forecast code remains offline. The production image and real seller workload were outside this verification.
