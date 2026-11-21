# Task 16 · Forecast-aware inventory planning

## Demand and lead time

The specialized reorder worker and DecisionOrchestrator use the same planner when `FORECAST_AWARE_REORDER_ENABLED=true`. The planner accepts the approved active or previous Task 14 model for the same seller, product, Dhaka forecast window, and exact supplier lead time. The released forecast horizons are 7, 14, and 30 days. Intermittent demand, unsupported lead times, or unavailable inference use eligible recorded sales velocity. Insufficient demand, missing supplier lead time, or missing, stale, or inconsistent inventory produces an evidence-limited HOLD. A verified zero or an approved zero without an applicable upper bound produces HOLD with zero units.

Forecast units cover the full business days beginning tomorrow. The estimate excludes the balance of the current day. Timing and inventory cover are indicative and use the average forecast units per day, or recorded velocity in fallback. The product field supplies the fixed supplier lead time. The current models provide no verified supplier delivery-time distribution or separate backorder count.

## Inventory and order constraints

Available stock is on-hand minus reservations. Effective inventory position adds confirmed outstanding units once. The explicit confirmed quantity takes precedence over the seller's `confirmed_incoming_quantity` product specification. Snapshot incoming is informational and the existing `mark-ordered` action changes the recommendation status. Neither supplies a remaining purchase-order balance.

An optional seller-declared `confirmed_incoming_date` is an ISO date for the full declared quantity. Orders dated beyond the lead plus review window count in inventory position and space requirements, with their replenishment credit deferred beyond the current buying cycle. Undated or overdue confirmed units reduce the purchase quantity to avoid repeat orders, and are flagged for receipt review if current stock is short. Timing and lead-time risk comparisons use available stock. The planner does not assume that a pending receipt prevents an earlier stockout.

| Output | Calculation |
| --- | --- |
| Expected lead-time demand | Approved total for the exact horizon, or recorded daily velocity times supplier lead time |
| Reorder point | Round up the greater of the applicable validated upper demand bound and the point demand plus the configured time buffer |
| Safety stock | Reorder point minus rounded-up expected lead-time demand |
| Coverage and timing | Estimate days of available stock at the indicated daily rate. Reorder review is due today at or below the reorder point. Above it, round down the days until the threshold. |
| Target stock | Round up protection demand plus the review-period allowance at the average daily rate |
| Order quantity | Target less available stock and credited receipts, floored at zero. Apply MOQ before rounding up to the pack size. Apply the lowest order cap rounded down to a pack. Return zero if the capped order cannot meet MOQ. |

The existing product specifications `minimum_order_quantity` or `moq`, `pack_size` or `case_size`, `safety_buffer_days`, and `review_period_days` remain supported. Optional product specifications are `maximum_stock`, `storage_capacity_units` and `reorder_budget_bdt`. Capacity checks count physical on-hand and confirmed receipts, including reserved stock that has yet to leave storage. Budget divides the stated BDT amount by the recorded product unit cost, excludes unrecorded charges, and floors the result to whole units. A missing unit cost or invalid supplied constraint produces an evidence-limited HOLD. All orders are advisory.

## Validation and service level

`REORDER_TARGET_SERVICE_LEVEL` defaults to `0.90` and accepts levels above 0.50 and below 1.00. A bound qualifies when its nominal level and the one-sided 95% Wilson lower limit of later observed upper-bound coverage meet the configured objective. Validation uses separate, nonoverlapping product-horizon windows. At least 20 calibration windows and 20 independent evaluation windows are required, with the model checksum, split, outcome cutoff, and lineage pinned in the approved registry. The sample minimum alone does not qualify an interval.

Use the offline `validate_reorder_bound` helper in `forecast_interval_service.py` with archived Task 13 `IntervalSample` rows for the exact CatBoost artifact. Supply `seller_id`, `product_id`, `horizon_days`, `model_sha256`, `test_start_date`, and the desired `nominal_level`. The helper fits the Task 13 residual radius before the split and scores upper-bound exceedances on separate, closed windows after the split. Add the serialized result to that horizon artifact's optional `reorder_calibrations` array and pin the registry through the [Task 14 approval process](task-14-forecast-inference.md). Older manifests remain readable.

With insufficient calibration the approved point may still replace historical velocity, and the configured time buffer supplies safety stock. Evidence reports the uncertainty status and whether available stock covers a validated upper bound when one exists. A historical coverage statistic or interval is not a calibrated probability of a stockout for the current order, so `stockout_probability` remains null. The specialized confidence score is a rule score for the advisory workflow.

## Rollout, replay and compatibility

Set `FORECAST_AWARE_REORDER_ENABLED=true` consistently on the backend and worker. The flag defaults off and restores the legacy path when disabled. Use the existing `FORECAST_ML_MODE=enabled`, registry SHA-256 pin, artifact root, and optional dedicated inference interpreter to activate approved inference. Live capture uses a seller-scoped, read-only PostgreSQL transaction with statement timeouts and bounded native inference.

Routes, response fields, and database schemas retain their existing contracts. Legacy numeric fields keep their required types. Evidence-limited rows identify unavailable estimates with nulls and reason codes in `evidence`. Forecast-aware rows add model, interval validation, sales fallback, inventory, constraint, and rounding evidence. The row's revision key fingerprints material inputs, the accepted forecast version, demand and uncertainty, and the computed planning result for idempotent retry. Capture timestamps alone do not change the revision. A changed approved forecast or planning result can publish a fresh same-day plan. Changed supplier terms can create a fresh same-day row. Earlier pending forecast-aware rows for that day expire atomically while preserving their history and any recorded ORDERED status. Inventory risk assessments link the latest same-day plan into the existing dashboard list. Changing the base calculation version deliberately requests a new revision when business inputs are already recorded.

## Verification

All 16 Task 16 cases passed. They cover no stock, observed and approved zero, intermittent demand, high demand, long or missing lead times, reserved and incoming stock, MOQ, packs, storage limits, budget, invalid constraints, uncertainty, missing forecasts, seller scope, concurrent replay, the specialized risk list after a supplier change, and the generic API and worker path. The focused regression passed 216 tests.

On Python 3.14.4 with disposable PostgreSQL and Redis, the full backend suite passed 1,009 tests and 809 subtests. It reproduced the 24 existing Copilot orchestrator failures. The three optional StatsForecast skips passed in a separate 31-case run. Scoped Ruff and core planning and inference mypy passed. The wider scoped mypy run reported five existing findings in adjacent product, inventory risk, and repository code.

Verification used fixture forecasts, archived test windows, PostgreSQL capture, and the existing native inference tests. Model accuracy, demand-bound coverage, and supplier delivery-time uncertainty on real seller data remain unverified.
