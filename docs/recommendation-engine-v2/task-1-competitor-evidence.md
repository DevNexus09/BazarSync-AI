# Task 1 · Competitor evidence and freshness

## Selection and eligibility

The legacy recommendation flow selects the latest completed scrape by finish time and reads mutable competitor rows currently assigned to it. Scraper upserts can change that assignment and retain earlier price or stock when extraction returns no value. Snapshot persistence uses the observations from that run. The freshness-aware flow reads immutable snapshots for one completed Daraz Bangladesh run, with seller, product, snapshot and competitor joins scoped to that run's product. It never scans earlier runs for substitute market values. A newer successful run with zero matches is an insufficient-evidence result.

The API verifies ownership, selects and validates the run, then passes its ID to Celery. The worker rechecks scope, completion and age for the same run and leaves the recommendation unwritten if the run no longer qualifies. Existing task messages remain compatible. Completing a different scrape changes selection for subsequent requests.

| Status | Treatment |
| --- | --- |
| `FRESH` | An eligible positive finite BDT price or recognized stock status with a timezone-aware field time inside the run's capture window and configured age. |
| `STALE` | A verified in-run observation older than the field limit. |
| `CARRIED_FORWARD` | A field timestamp predates the run, or the current mutable record retains a field missing from its snapshot. Retained values without a verified timestamp carry no observation time. |
| `HISTORICAL` | Earlier valid price-history data exists for a listing whose snapshot has no price. Price history lacks a run ID, and older entries may use capture time as a fallback. It cannot qualify a current value. |
| `MISSING` | No usable field value was recorded. |
| `INVALID` | Invalid price or currency, unrecognized stock label, or a timestamp outside the valid run/capture window. |
| `UNKNOWN` | A value exists with missing or unverifiable field timing. Snapshot capture, run completion and competitor update times cannot supply a field timestamp. |

Current-market statistics only consume fresh prices. Availability uses fresh stock paired with an eligible price from the same listing and run. When no such stock exists, `competitors_oos` is null and the legacy stock heuristic gets no availability adjustment. Its stock-cover output remains heuristic. The freshness-aware flow converts legacy `RAISE` to low-confidence `HOLD` because that rule has no raised price for MarginGuard to validate. Existing price-lowering validation still applies.

With no eligible prices the existing `404 competitor_data_missing` response applies and preflight does not queue work. Successful recommendations store scoped source IDs, evaluation and observation times, limits, coverage, missing fields, rejection reasons and quality flags in `recommendation_context.competitor_evidence`. The existing latest response, dashboard contracts and prior history remain readable. An in-flight run can age out before worker execution. Terminal task status and UI polling changes remain outside Task 1.

## Configuration and rollout

| Environment setting | Default | Trade-off |
| --- | --- | --- |
| `RECOMMENDATION_EVIDENCE_ENABLED` | `false` | Enables strict evidence on new general recommendation requests. Use the same value on web and workers. |
| `RECOMMENDATION_PRICE_MAX_AGE_HOURS` | `24` | A day retains price coverage across daily refreshes. Shorter windows reduce exposure to fast price changes and increase insufficient-evidence responses. |
| `RECOMMENDATION_STOCK_MAX_AGE_HOURS` | `6` | Availability changes faster. Shorter windows remove stale stock signals sooner and produce more null counts. |

Both limits accept positive whole hours up to 8760. Apply additive revision `j4d5e6f7a8b9` before deploying updated snapshot readers and writers. The two nullable columns are necessary because existing snapshot `captured_at` is run-level, stock history has no independent field timestamp, and price history lacks a run FK. New writes use the actual search or detail observation supplying each field. The metadata-only cache supplies neither timestamp. Old rows remain null, without backfill. Deploy web and workers before enabling the flag and allow a new scrape to populate verified evidence. To roll back behavior, disable the flag and let pinned tasks drain. A schema downgrade after reverting application code removes only the two added timestamp columns and their values.
