# Phase 6 Inventory and Sales Intelligence

## Inventory History

Inventory history is captured at the seller product level because the current product model stores a single `stock_quantity` and does not define warehouses or locations.

Daily inventory snapshots are immutable and unique by `(seller_id, product_id, snapshot_date)`. Available stock is calculated as:

```text
quantity_available = quantity_on_hand - quantity_reserved
```

Incoming stock is preserved when supplied, and inventory position can be derived as:

```text
inventory_position = quantity_on_hand + quantity_incoming - quantity_reserved
```

## Sales Velocity

Sales velocity uses `sales_records` as the authoritative sales input table. It does not infer demand from inventory decline, page views, carts, pending orders, cancelled orders, failed payments, or test orders.

Counted sale statuses:

- `COMPLETED`
- `FULFILLED`

Excluded sale statuses:

- `PENDING`
- `CANCELLED`
- `FAILED_PAYMENT`

Test orders are always excluded.

Net units are calculated per sales record as:

```text
net_units = max(quantity_sold - returned_units - refunded_restocked_units, 0)
```

Refunds that did not return units to inventory are not subtracted from demand velocity.

The default window is 30 calendar days. The denominator is calendar-day demand velocity, not days with sales:

```text
daily_sales_rate = net_units_sold_in_window / effective_window_days
```

For products younger than the configured window:

```text
observed_days = max(1, calendar days since product creation including the as-of date)
effective_window_days = min(window_days, observed_days)
```

If no valid completed or fulfilled sales records exist, the calculation is stored with `INSUFFICIENT` data status and low confidence instead of treating the product as confirmed zero demand.

Confidence score version `v1` is a transparent data-quality score:

```text
50 * observed_window_coverage
+ 30 * valid_record_coverage
+ 20 * sales_data_availability
```

Where:

- `observed_window_coverage = min(observed_days / window_days, 1)`
- `valid_record_coverage = min(valid_sales_records / 10, 1)`
- `sales_data_availability = 1` when at least one valid sales record exists, otherwise `0`

Status rules:

- `SUFFICIENT`: at least one valid sales record and at least seven observed days, unless the configured window is shorter.
- `LIMITED`: at least one valid sales record but too little product age history.
- `INSUFFICIENT`: no valid completed or fulfilled sales records.

## Tasks

- `inventory_history.capture_daily_inventory_snapshots`
- `sales_velocity.calculate_daily_sales_velocity`
- `stockout_predictions.calculate_stockout_predictions`
- `reorder_recommendations.calculate_reorder_recommendations`
- `inventory_risks.calculate_inventory_risks`
- `inventory_intelligence.daily_workflow`
- `inventory_intelligence.recalculate_product`
- `inventory_intelligence.generate_alerts_for_latest_risks`
- `telegram_inventory_alerts.generate_for_risk`
- `telegram_inventory_alerts.deliver`
- `telegram_inventory_alerts.enqueue_due`

The calculation and alert tasks are idempotent and rely on database uniqueness to prevent duplicate daily records, calculations, recommendations and alert outbox rows.

The controlled daily inventory-intelligence workflow runs:

```text
Capture inventory snapshots
-> Calculate sales velocity
-> Calculate stockout predictions
-> Generate reorder recommendations
-> Assess inventory risk
-> Create eligible Telegram alerts
-> Deliver pending alerts
```

The workflow uses Celery immutable chain signatures. Each stage commits its own database records before the next stage starts. Telegram failures are isolated in the alert outbox and do not roll back inventory calculations.

Product-level recalculation is available through `inventory_intelligence.recalculate_product`. Product updates enqueue recalculation only for inventory-relevant changes:

- `stock_quantity`
- `supplier_lead_time`
- inventory-planning specification keys such as `confirmed_incoming_quantity`, `purchase_order_quantity`, `safety_buffer_days`, `minimum_order_quantity`, `pack_size` and related aliases

Metadata-only edits such as title, description, category, color, or other non-inventory specifications do not enqueue recalculation.

Schedule config:

- `INVENTORY_INTELLIGENCE_SCHEDULE_ENABLED`
- `INVENTORY_INTELLIGENCE_DAILY_HOUR_UTC`
- `INVENTORY_INTELLIGENCE_DAILY_MINUTE_UTC`

## Stockout Prediction

Stockout prediction uses the latest inventory snapshot and latest sales velocity calculation available for the seller product.

Core formula:

```text
inventory_position = quantity_on_hand + confirmed_incoming_quantity - quantity_reserved
days_remaining = inventory_position / daily_sales_rate
```

The current repository does not have a purchase-order model or a confirmed incoming-stock flag. Because incoming stock cannot be distinguished as confirmed, production predictions exclude `quantity_incoming` by default. The service can accept an explicit confirmed incoming quantity for future purchase-order integration.

Prediction statuses:

- `PREDICTED`: positive inventory position and positive sufficient sales velocity.
- `ALREADY_OUT_OF_STOCK`: inventory position is zero or negative.
- `NO_RECENT_DEMAND`: sufficient sales data exists but daily sales velocity is zero.
- `INSUFFICIENT_DATA`: no velocity record exists or velocity data is insufficient.

Prediction date policy:

- `predicted_stockout_date` is the seller local business date on which inventory reaches zero.
- Fractional days are rounded down for the date calculation to keep operational warnings conservative.
- Example: 2.5 days remaining on June 29 produces a predicted stockout date of July 1.

Confidence score version `v1` combines explainable data-quality inputs:

```text
60% sales velocity confidence
+ 25% inventory freshness
+ 10% incoming stock reliability
+ 5% observed sales-day coverage
```

`INSUFFICIENT_DATA` predictions are capped at 35 confidence, and `NO_RECENT_DEMAND` predictions are capped at 60.

## API Endpoints

- `GET /products/{product_id}/inventory-history`
- `GET /products/{product_id}/inventory-history/latest`
- `GET /products/{product_id}/sales-velocity`
- `GET /products/{product_id}/sales-velocity/history`
- `GET /products/{product_id}/stockout-prediction`
- `GET /products/{product_id}/stockout-predictions/history`
- `GET /products/{product_id}/reorder-recommendation`
- `GET /products/{product_id}/reorder-recommendations/history`
- `GET /products/{product_id}/inventory-intelligence`
- `POST /reorder-recommendations/{id}/acknowledge`
- `POST /reorder-recommendations/{id}/mark-ordered`
- `POST /reorder-recommendations/{id}/dismiss`
- `GET /inventory-risks`
- `GET /products/{product_id}/inventory-risk`
- `GET /products/{product_id}/inventory-risks/history`
- `GET /inventory-intelligence/summary`
- `GET /inventory-intelligence/reorder-list`
- `GET /inventory-intelligence/risks`
- `GET /inventory-intelligence/products/{product_id}`
- `POST /inventory-intelligence/workflow/daily`
- `POST /inventory-intelligence/products/{product_id}/workflow`

Inventory-intelligence API responses return explicit `null` values for unavailable predictions and do not substitute zero for missing data. Decimal values use the API framework's Decimal serialization, UTC timestamps remain timestamps, and business dates are returned as date fields.

## Reorder Recommendations

Reorder recommendations use current inventory position, daily sales velocity, supplier lead time, safety buffer, review period, confirmed incoming stock, and optional product-specific order settings.

Current product-specific inputs:

- `supplier_lead_time` from the product record
- `minimum_order_quantity` or `moq` from product specifications, if present
- `pack_size` or `case_size` from product specifications, if present
- `safety_buffer_days` from product specifications, if present
- `review_period_days` from product specifications, if present

Configured defaults:

- `REORDER_DEFAULT_SUPPLIER_LEAD_TIME_DAYS`
- `REORDER_DEFAULT_SAFETY_BUFFER_DAYS`
- `REORDER_DEFAULT_REVIEW_PERIOD_DAYS`
- `REORDER_MINIMUM_VELOCITY_CONFIDENCE`
- `REORDER_MAXIMUM_RECOMMENDATION_HORIZON_DAYS`
- `REORDER_CALCULATION_VERSION`

Formulas:

```text
inventory_position = quantity_on_hand + confirmed_incoming_quantity - reserved_quantity
lead_time_demand = daily_sales_rate * supplier_lead_time_days
safety_stock = daily_sales_rate * safety_buffer_days
reorder_point = ceil(daily_sales_rate * (supplier_lead_time_days + safety_buffer_days))
target_stock = ceil(daily_sales_rate * (supplier_lead_time_days + safety_buffer_days + review_period_days))
raw_reorder_quantity = max(0, target_stock - inventory_position)
```

Safety stock in version `v1` is a deterministic buffer, not a statistical safety-stock model.

If pack size exists, positive raw quantity is rounded upward to the nearest pack size. If the adjusted quantity is positive but below minimum order quantity, minimum order quantity is used.

Deadline policy:

```text
days_until_reorder = floor(max(0, inventory_position - reorder_point) / daily_sales_rate)
reorder_deadline = as_of_date + days_until_reorder
```

If inventory position is already at or below the reorder point, the deadline is the as-of date. If demand data is insufficient, no supported reorder recommendation is returned and status is `INSUFFICIENT_DATA`.

## Inventory Risk Scoring

Inventory risk is an explainable score from 0 to 100 and a risk level. It is not a mathematically calibrated stockout probability.

Risk levels:

- `LOW`
- `MEDIUM`
- `HIGH`
- `CRITICAL`

Data statuses:

- `SUFFICIENT`
- `LIMITED`
- `INSUFFICIENT`

Core coverage terms:

```text
required_coverage_days = supplier_lead_time_days + safety_buffer_days
coverage_gap_days = required_coverage_days - days_remaining
```

A positive coverage gap means projected inventory coverage is shorter than required replenishment coverage.

Version `v1` classification:

- `CRITICAL`: inventory position is zero or negative, predicted stockout occurs before supplier lead time, or reorder deadline is today/overdue with a significant coverage gap.
- `HIGH`: days remaining are less than or equal to supplier lead time plus safety buffer.
- `MEDIUM`: coverage is above required coverage but within the review-period horizon.
- `LOW`: coverage exceeds lead time, safety buffer, and review period.
- `INSUFFICIENT`: missing or unreliable prediction data. The system does not assign `LOW` only because prediction data is absent.

Version `v1` score weights:

```text
40% coverage-gap severity
25% current-stock state
20% reorder urgency
10% confidence risk
5% inventory freshness
```

Config:

- `INVENTORY_RISK_CALCULATION_VERSION`
- `INVENTORY_RISK_SIGNIFICANT_COVERAGE_GAP_DAYS`
- `INVENTORY_RISK_MEDIUM_REVIEW_HORIZON_DAYS`
- `INVENTORY_RISK_STALE_INVENTORY_DAYS`

## Telegram Inventory Alerts

Phase 6.6 reuses the existing seller Telegram connection and Telegram delivery service. It does not introduce a second bot integration.

Inventory alerts are persisted first in `telegram_inventory_alerts`; delivery happens afterward. The database outbox is the source of truth, so a Celery retry, worker crash or temporary Telegram failure cannot create duplicate alert records.

Alert types:

- `CRITICAL_RISK`
- `HIGH_RISK`
- `RISK_ESCALATION`
- `REORDER_DEADLINE`
- `DAYS_REMAINING_DROP`
- `OUT_OF_STOCK`

Alert statuses:

- `PENDING`
- `SENDING`
- `SENT`
- `FAILED`
- `CANCELLED`

Deduplication uses a deterministic key containing seller, product, alert type, risk level, reorder recommendation, calculation version and, for material days-remaining drops, the current days-remaining bucket. The table has a unique constraint on `dedupe_key`.

Cooldown policy:

- Repeated `HIGH_RISK` alerts are suppressed during `TELEGRAM_INVENTORY_ALERT_COOLDOWN_HOURS`.
- `CRITICAL_RISK`, `RISK_ESCALATION`, `REORDER_DEADLINE`, `DAYS_REMAINING_DROP` and `OUT_OF_STOCK` alerts bypass the repeated-HIGH cooldown because they represent a new or more urgent operational condition.
- Material days-remaining reduction is controlled by `TELEGRAM_INVENTORY_ALERT_MATERIAL_DAYS_DROP`.

Delivery policy:

- Delivery is skipped and the alert is cancelled when the seller Telegram account is disabled, unlinked or missing a chat ID.
- Successful delivery marks the alert `SENT` and updates the seller Telegram connection's `last_alert_sent_at`.
- Temporary delivery failures store sanitized failure codes such as `rate_limited` or `temporary_network_failure` and schedule bounded exponential backoff.
- Permanent failures store sanitized codes such as `invalid_chat`, `unauthorized` or `payload_invalid`; raw exception text, bot tokens and stack traces are not stored.
- Delivery uses an atomic database status transition from `PENDING` or `FAILED` to `SENDING`, so concurrent workers cannot send the same outbox row twice.

Message construction is centralized in `app.services.telegram.inventory_alert_formatter`. The current template is English-compatible and intentionally simple so future Bangla templates can be added without scattering strings through task code.

Config:

- `TELEGRAM_INVENTORY_ALERT_COOLDOWN_HOURS`
- `TELEGRAM_INVENTORY_ALERT_MATERIAL_DAYS_DROP`
- `TELEGRAM_INVENTORY_ALERT_MAX_ATTEMPTS`
- `TELEGRAM_INVENTORY_ALERT_INITIAL_BACKOFF_SECONDS`
- `TELEGRAM_INVENTORY_ALERT_MAX_BACKOFF_SECONDS`

## Phase 6 Acceptance Fixture

The automated acceptance fixture `tests/test_phase6_acceptance_workflow.py` covers the following product scenario:

```text
Dove Body Lotion
stock = 40
reserved = 0
confirmed incoming = 0
sales velocity = 300 net units / 30 days = 10 units/day
supplier lead time = 8 days
safety buffer = 3 days
review period = 4 days
minimum order quantity = 50
pack size = 10
```

Expected calculations:

```text
days_remaining = 40 / 10 = 4
reorder_point = 10 * (8 + 3) = 110
target_stock = 10 * (8 + 3 + 4) = 150
raw_reorder_quantity = 150 - 40 = 110
recommended_quantity = 110
reorder_deadline = current business date
risk_level = CRITICAL
```

The fixture also verifies healthy stock, no recent demand, insufficient demand data, already-out-of-stock behavior, Telegram alert creation, and retry-safe delivery.
