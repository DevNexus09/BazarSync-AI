# Task 9 · Forecast features

`ForecastFeatureBuilder` works on one seller and one product per snapshot. It reads the validated Task 8 daily dataset and uses the same `build()` path for training and inference. A training example attaches its label in a separate envelope. Account, product, source timestamps, quality flags, and schema metadata sit outside the model input payload.

## Time definitions

| Term | Meaning |
| --- | --- |
| Forecast origin | Offset-aware instant of prediction. The origin is normalized to UTC and must follow the completed source capture. |
| Feature date | The Dhaka business date containing the forecast origin. A 1-day lag refers to the preceding Dhaka date. The entire feature date is excluded from sales lags and rolling calculations. |
| Data cutoff | PostgreSQL wall-clock timestamp sampled after all source reads within the read-only, repeatable-read capture. Inputs from this snapshot are eligible only when the cutoff is strictly earlier than the forecast origin. |
| Extract cutoff | Requested Task 8 `as_of_timestamp`. It bounds sales imports and coverage and must be at or before capture. It also bounds catalog, price-change, and competitor evidence used by this feature version. |
| Forecast horizon | 7, 14, or 30 complete business days beginning the day after the feature date. |
| Prediction target | Sum of Task 8 net sales across the complete horizon. The target is null if any outcome day lacks an eligible label. The example also records how many eligible label days exist. |

Task 8's transactional data includes mutable status and return counters without a version history. Archive origin snapshots as they are captured. Running a fresh export with a backdated extract cutoff gives it a new capture timestamp, so it cannot be used to reconstruct an earlier forecast origin. A Task 8 outcome extract can include later returns or late imports and is used only by the target calculation.

## Capture and build

Use an authorized offline job to produce a single-product bundle. The export remains default-off through `HISTORICAL_DATASET_EXPORT_ENABLED`. Add `--forecast-snapshot` and `--product-id` to the [Task 8 export command](task-8-historical-dataset.md). For a daily build, select the preceding 30 closed Dhaka business dates and an extract cutoff after the last date closes. Run capture before the forecast origin and archive the output with seller-scoped access. The capture includes the Task 8 rows, current catalog version, supporting price-history ID when available, and timestamped competitor observations from the same read-only transaction. Capture enforces repeatable-read or serializable isolation. If the product's current catalog version follows the requested extract cutoff, that capture is rejected.

The caller supplies the seller ID from its authorization context. Load the product's origin snapshot and outcome extract from the authorized seller's storage scope. The service rejects mismatched seller and product rows and duplicate dates. The feature computation reads the snapshots only, and a 30-day history is processed in one rolling pass. There are no model or dataframe dependencies.

```python
from app.schemas.forecast_features import ForecastFeatures, ForecastSourceSnapshot
from app.services.forecast_feature_builder import ForecastFeatureBuilder
from app.services.historical_dataset_service import HistoricalDataset

source = ForecastSourceSnapshot.model_validate_json(origin_file.read_bytes())
builder = ForecastFeatureBuilder(authorized_seller_id=authorized_seller_id)

inference = builder.build(source, forecast_origin=origin, horizon_days=14)
features_file.write_text(inference.model_dump_json(), encoding="utf-8")

outcomes = HistoricalDataset.model_validate_json(outcome_file.read_bytes())
example = builder.build_training_example(
    source, forecast_origin=origin, horizon_days=14, outcomes=outcomes,
)
training_file.write_text(example.model_dump_json(), encoding="utf-8")

feature_schema = ForecastFeatures.model_json_schema()
```

For inference, use the feature row's `features` payload. For fitting later, use that identical payload on `example.feature_row` and take the label from `example.target_net_units`. The serialized row carries the feature version and a required SHA-256 digest of the canonical feature JSON schema. Deserialization rejects a different digest. The hyperparameters of any later forecast, including horizon and required training history, belong in that model's own metadata.

## Feature definitions

| Group | Definitions |
| --- | --- |
| Sales | Lags on calendar offsets 1, 7, 14, and 28. The 7-, 14-, and 30-day windows include net-unit totals, population standard deviation, percentage of observed zero-sales days, and count of eligible days. Numeric aggregates require a full eligible window. Unknown inventory and stockout-censored days are ineligible for sales features under the Task 8 eligibility rule. A known zero remains zero. |
| Product | Category, explicit brand, and age in Dhaka business dates since BazarSync creation. The known offer price is the catalog base price in BDT. The latest base price delta requires a recorded product edit that matches that base price and predates the extract cutoff. Prices on individual marketplace listings have their own scope. |
| Calendar | Day of week (Monday = 0), month, Friday/Saturday weekend, month-end, and public holiday for the feature date and each target day. `target_calendar[i]` describes `target_start_date + i`. |
| Competitor | Latest qualified verified price per marketplace listing within seven days of origin. Both the price observation and its capture, persistence, and completed run must be available before the extract cutoff. Median and count are grouped by marketplace and currency. The newest and oldest observation ages use the actual price observation instant. The absolute gap is base price minus median and is populated only for an unambiguous single group in the same currency. |
| Inventory | Previous-day on-hand and nullable stockout status, plus 30-day counts of days with inventory evidence and days with an observed stockout. The count of evidence days provides the inventory quality denominator. |
| Promotions | Previous-day status passes through from Task 8. Executed promotion data is currently unknown, so status and discount are nullable. |
| Quality | Usable sales days over 30 days, seven complete recent sales days as a minimum sufficiency signal, and flags for gaps, censoring, or missing evidence. Cold starts retain nullable lags and aggregates. |

The bundled holiday catalog covers six verified fixed dates in each of 2025 and 2026. Other days are unknown, including movable dates that require later confirmation. The builder accepts maintained, versioned calendars with explicit true or false values and a publication timestamp. The latest applicable version published strictly before the prediction governs each date. Preserve historical releases and give corrections new versions so they apply only from their publication onward. [2025 government holiday circular](https://file-barisal.portal.gov.bd/uploads/e7623ff8-79e5-4a93-83ce-a86abee1c420/671/f00/298/671f00298fe67937412078.pdf) · [2026 Bangladesh Gazette](https://www.dpp.gov.bd/upload_file/gazettes/59216_19984.pdf)
