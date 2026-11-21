# Task 8 · Historical business dataset

The offline export produces a versioned JSON artifact for one authorized seller. Each row has a unique `(seller_id, product_id, business_date)` key. The artifact includes the requested date range, extract cutoff, feature allowlist, rows, and quality summary. Monetary Decimals are serialized as JSON strings. Optional scalar fields use JSON null for unknown values.

## Generating an extract

Run from the backend directory with the configured PostgreSQL connection and an operator authorized to export the specified seller's data. Use seller-scoped output locations with restricted access. The CLI is a trusted operator boundary. A seller ID identifies the authorized job scope, and possession of that ID grants no authorization. The service takes the authorized seller ID from its caller and checks ownership on product selection and source reads. There is no API endpoint or scheduled job for this export.

```sh
HISTORICAL_DATASET_EXPORT_ENABLED=true python -m scripts.export_historical_dataset \
  --seller-id <authorized-seller-uuid> \
  --start-date 2026-09-01 --end-date 2026-09-30 \
  --as-of 2026-10-08T00:00:00+06:00 \
  --output /private/seller-export/2026-09.json
```

Replace the seller placeholder with its UUID. The parent output directory must exist. `--product-id` can limit the export to one owned product. Each run accepts 1–366 closed business days and uses a read-only, repeatable-read transaction. The completed JSON file is installed by atomic replacement. The schema needs no migration.

Append by exporting each new date partition. Rebuild older partitions when a delayed import or source correction warrants it. Key the partitions by seller, product scope, date range, dataset version, and extract cutoff. Replace the previous version of an overlapping partition as a unit. Rows for equivalent partitions match a larger extract against the same source state and cutoff. Compare summaries per partition because counts and consecutive runs describe that partition. For large catalogs, use smaller date ranges or single-product partitions to limit memory use.

Keep the original artifact for reproducibility across later updates and deletions. The same parameters and source state produce identical bytes. The live tables lack version histories for some mutable values, including sales status and return counters, so a later re-export cannot reconstruct every earlier source state.

## Time and data contract

`Asia/Dhaka` defines the business day from local midnight inclusive to the following midnight exclusive. The artifact serializes timestamps in UTC. `prediction_cutoff` is the opening of that day. Only the fields in `prediction_feature_fields` are suitable as same-day inputs. The extract's product roster is selection metadata, and a product can have historical sales before it was added to BazarSync. The requested grid keeps empty and missing dates visible.

`sold_at` assigns transactions to days. `SalesRecord.created_at` is the import or recording time. `as_of_timestamp` is the explicit upper bound for sales recording and coverage availability. It can follow the prediction cutoff so delayed imports can supply outcome labels. Current status and return counters are read from the extract snapshot and attributed to the original sale date. Sources lack return event timestamps, and a historical as-of export does not establish when those counters or statuses became known. Keep sales, stock, transaction prices, sales coverage, eligibility, quality flags, and provenance out of the same-day feature set.

| Field | Meaning |
| --- | --- |
| `seller_id`, `product_id`, `business_date` | Canonical key. The grid contains every requested date for each selected seller product created by the extract cutoff. |
| `observed_units_sold` | Net units from recorded `COMPLETED` and `FULFILLED` lines, less the two return/restock counters per the sales velocity convention. Partial coverage can still supply observed units on a day with valid lines. A fully returned valid line contributes zero net units. |
| `valid_order_count` | Zero when product-wide coverage establishes that no valid orders occurred. Null for valid sale lines because the transactional schema carries an opaque unique line reference and has no distinct order ID. |
| `returned_or_cancelled_units` | Return and refunded/restocked units for valid lines plus full cancelled quantity. A cancelled line contributes its quantity once, including when it carries return counters. Pending, failed-payment, and test orders contribute no sales or removals. |
| `effective_selling_price`, `currency` | Net-unit-weighted transaction price. Every remaining unit must have a valid transaction price and a single common currency. A consistent transaction line total can supply a missing unit price. Current-price estimates and offer-price history are excluded from the transaction price. Mixed currencies produce null price and currency, with a quality flag. |
| `on_hand_stock`, `stockout_indicator` | Same-day outcome diagnostics. On-hand is the last reliable observation recorded by day close. Any qualifying observation of zero or negative available stock marks a censored day. False means positive availability at the observed times and gives no guarantee about the whole day. Null represents UNKNOWN. Dates derive from the capture timestamp. The pipeline excludes synthetic baseline backfills and observations recorded after the day closed. |
| `promotion_indicator` | Null. Promotion plans and estimated results do not establish live marketplace execution. |
| `category`, `brand` | Opening features, populated when the currently stored product version predates the cutoff. Brand requires an explicit, unambiguous product specification. Unsnapshotted older metadata is unknown after a later product edit. |
| `marketplace` | A transaction outcome attribute. All included sale lines must link unambiguously to one marketplace using listings recorded by sale time. Ambiguous or absent marketplace evidence yields null. |
| `competitor_prices` | Opening features grouped by marketplace and currency with count, minimum, maximum, and mean. Use the latest qualified observation per marketplace listing from the previous seven days. The verified field observation, capture, snapshot record, and completed seller/product scrape run must all predate opening. Require a stable listing identity and a match score of at least 0.65. Empty means no qualifying data. |
| `sales_coverage_complete` | A declared product-wide COMPLETE coverage interval was recorded by the extract cutoff and after the business day closed. The newest overlapping product-wide declaration governs, ordered by creation, import, or update availability, whichever is latest. A conflict at that time leaves coverage unknown. Import coverage dates are interpreted as inclusive UTC dates, matching the importer's default. The interval must span every UTC date intersecting the Dhaka day. Seller-wide batches can mix products, and marketplace-only batches leave other marketplaces unverified. |
| `forecast_label_eligible` | Requires an observed label, complete coverage, positive inventory evidence with no observed stockout, and no unresolved, unkeyed, duplicate, or invalid sales on the day. Eligibility describes label quality. Consecutive history lengths are reported for downstream model-specific decisions. |
| `data_quality_flags`, `source_ids`, `as_of_timestamp` | Sorted row-level quality codes, applied source table IDs, and the extract cutoff. The independent prediction cutoff makes feature availability explicit. |

The importer enforces unique non-null seller/source references. Reuse a stable reference for each source line across imports. Unkeyed records cannot prove replay identity and are quarantined. Invalid rows include nonpositive sold quantities, negative return counters, returns exceeding the sold quantity, and records whose import time precedes their transaction time. Incomplete coverage or unresolved lines prevent an empty bucket from becoming a presumed zero. Explicit test orders and derived sales velocity are excluded. The sources have no other general-purpose synthetic sales marker, so import only real seller transactions when using this pipeline.

## Quality report

The export validates the row count and exact ordered key grid, including missing dates and duplicate keys. It also checks for negative output quantities. Its quality report includes selected product coverage, observed days per product, requested history length, per-field missingness, inventory and censored day counts, invalid and duplicate record counts, unkeyed imports, category distribution by product-day, and eligible days and longest eligible runs by product. Import retries already rejected by the transactional table leave no duplicate rows for the export to count.
