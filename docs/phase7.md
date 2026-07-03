# Phase 7 Pricing Policy and Fee Foundation

Phase 7 creates the deterministic pricing constraints that future recommendation engines should use before suggesting price changes.

## Data Model

`pricing_policies` stores seller-owned product pricing constraints by marketplace and effective period.

Key fields:

- `seller_id`
- `product_id`
- `marketplace`
- `currency`
- `minimum_margin_rate`
- `minimum_unit_profit`
- `maximum_price_decrease_rate`
- `maximum_price_increase_rate`
- `minimum_allowed_price`
- `maximum_allowed_price`
- `price_increment`
- `recommendation_cooldown_hours`
- `objective`
- `is_active`
- `effective_from`
- `effective_to`

`marketplace_fee_policies` stores auditable marketplace fee inputs. Fee rows are versioned and effective-dated so historical calculations can be explained later.

Key fields:

- `seller_id`
- `product_id`, nullable for seller or category defaults
- `marketplace`
- `category`
- `currency`
- `percentage_commission_rate`
- `payment_fee_rate`
- `fixed_per_order_fee`
- `fixed_per_unit_fee`
- `fulfilment_fee`
- `shipping_subsidy`
- `other_variable_cost`
- `source`
- `version`
- `is_active`
- `effective_from`
- `effective_to`

Effective fee lookup priority is:

1. Product-specific fee policy
2. Category fee policy
3. Seller-level marketplace default

## Pricing Objective

Supported policy objectives:

- `MAXIMIZE_EXPECTED_PROFIT`
- `MAXIMIZE_REVENUE_WITH_MARGIN_FLOOR`
- `PROTECT_INVENTORY`
- `CLEAR_EXCESS_STOCK`

The default objective is `MAXIMIZE_EXPECTED_PROFIT`.

## Margin Definition

BazarSync AI Phase 7 uses margin as a percentage of selling price.

Definitions:

```text
percentage_fee_amount =
  price * (percentage_commission_rate + payment_fee_rate)

fixed_fees =
  fixed_per_order_fee
  + fixed_per_unit_fee
  + fulfilment_fee
  + shipping_subsidy

unit_profit =
  price
  - percentage_fee_amount
  - fixed_fees
  - unit_cost
  - other_variable_cost

margin_rate =
  unit_profit / price
```

Minimum safe price:

```text
minimum_safe_price =
  (unit_cost + fixed_fees + other_variable_cost)
  / (1 - percentage_fee_rate - minimum_margin_rate)
```

The calculator also enforces `minimum_unit_profit` by taking the higher of the margin-safe price and the unit-profit-safe price.

Validation rule:

```text
percentage_fee_rate + minimum_margin_rate < 1
```

If that rule is not true, no finite safe price can satisfy the policy.

## Currency and Rounding

All calculations use `Decimal`.

For BDT, committed and displayed money values are rounded to two decimal places. Marketplace increment rounding is separate and rounds candidate prices upward to the configured increment.

Intermediate values are not rounded unless the caller explicitly asks for currency or marketplace-increment rounding.

## API Endpoints

All endpoints are seller-authenticated and verify product ownership.

- `GET /api/v1/pricing-policies/products/{product_id}`
- `PUT /api/v1/pricing-policies/products/{product_id}`
- `POST /api/v1/pricing-policies/marketplace-fees`
- `GET /api/v1/pricing-policies/products/{product_id}/fees/effective`
- `POST /api/v1/pricing-policies/products/{product_id}/minimum-safe-price/preview`

## Known Limitations

- Phase 7 does not generate final price recommendations yet. It provides the audited policy and fee foundation for that later step.
- Overlapping effective periods are guarded by active-scope uniqueness and effective-date lookup rules, not by a PostgreSQL exclusion constraint.
- Existing `Product.minimum_margin` values are interpreted as a rate when below `1`, and as a whole percent when `1` or above.

## Phase 7.1 Pricing Analytics Snapshots

`pricing_analytics_snapshots` stores immutable product-level analytics snapshots. Each snapshot combines current product economics, effective fees, competitor market data, latest inventory snapshot, latest sales velocity, inventory risk, freshness evidence, margin calculations, and demand scoring inputs.

Snapshots are idempotent through `dedupe_key`, which is derived from the seller, product, formula version, source record IDs, current price, and unit cost.

Data status values:

- `SUFFICIENT`
- `LIMITED`
- `INSUFFICIENT`
- `STALE`

Freshness settings:

- `PRICING_ANALYTICS_MAX_COMPETITOR_DATA_AGE_HOURS`, default `24`
- `PRICING_ANALYTICS_MAX_INVENTORY_DATA_AGE_HOURS`, default `48`
- `PRICING_ANALYTICS_MAX_VELOCITY_DATA_AGE_HOURS`, default `48`

Demand score settings:

- `PRICING_ANALYTICS_DEMAND_VELOCITY_WEIGHT`, default `45`
- `PRICING_ANALYTICS_DEMAND_RECENT_SALES_WEIGHT`, default `25`
- `PRICING_ANALYTICS_DEMAND_COMPETITOR_AVAILABILITY_WEIGHT`, default `15`
- `PRICING_ANALYTICS_DEMAND_PRODUCT_MATURITY_WEIGHT`, default `15`
- `PRICING_ANALYTICS_DEMAND_VELOCITY_REFERENCE_UNITS_PER_DAY`, default `10`
- `PRICING_ANALYTICS_DEMAND_RECENT_SALES_REFERENCE_UNITS`, default `100`
- `PRICING_ANALYTICS_FORMULA_VERSION`, default `v1`

Demand weights must total `100`.

Market statistics include minimum, maximum, mean, median, first quartile, third quartile, competitor count, in-stock competitor count, weighted market price when ranking scores exist, seller price difference from median, and seller price percentile. Missing, zero, and negative competitor prices are excluded. Phase 7.1 does not remove outliers.

Pricing analytics API endpoints:

- `GET /api/v1/products/{product_id}/pricing/analytics`
- `GET /api/v1/products/{product_id}/pricing/analytics/history`
- `POST /api/v1/products/{product_id}/pricing/analytics`
- `POST /api/v1/pricing/analytics/workflow`

Celery task:

- `pricing_analytics.calculate`

## Phase 7.2 Margin Protection Layer

The margin protection layer is implemented by `MarginGuard`.

No price recommendation should be selected or persisted without margin validation. The recommendation service applies the guard after deterministic analytics creates an action and again immediately before saving the AI-confirmed recommendation.

If the guard cannot validate a `LOWER` or `RAISE` price recommendation, the final recommendation is changed to `HOLD` with low confidence. Guard evidence is stored inside the recommendation context under `margin_guard`.

Guard rejection reasons:

- `BELOW_MINIMUM_SAFE_PRICE`
- `NEGATIVE_UNIT_PROFIT`
- `BELOW_MINIMUM_MARGIN`
- `BELOW_MINIMUM_UNIT_PROFIT`
- `EXCEEDS_MAXIMUM_DECREASE`
- `EXCEEDS_MAXIMUM_INCREASE`
- `BELOW_ABSOLUTE_MINIMUM`
- `ABOVE_ABSOLUTE_MAXIMUM`
- `INVALID_MARKETPLACE_INCREMENT`
- `MISSING_COST_DATA`
- `MISSING_FEE_DATA`
- `INVALID_POLICY`
- `UNSUPPORTED_CURRENCY`

Guard result fields:

- `is_allowed`
- `candidate_price`
- `minimum_safe_price`
- `unit_profit`
- `margin_rate`
- `fee_breakdown`
- `rejection_reasons`
- `policy_version`
- `calculation_version`

Fail-closed behavior:

- Missing cost data blocks price recommendations.
- Missing active fee data blocks price recommendations.
- Unsupported currency blocks price recommendations.
- Invalid policy, such as fee rate plus minimum margin at or above `1`, blocks price recommendations.
- Rejected candidate summaries are stored in recommendation evidence, not as separate high-volume database rows.

## Phase 7.3/7.4 Demand-Response Estimation

The demand-response component estimates expected unit demand at candidate prices without using an opaque ML framework.

Supported methods:

- `HISTORICAL_ELASTICITY`
- `CATEGORY_PRIOR`
- `CONSERVATIVE_HEURISTIC`
- `INSUFFICIENT_DATA`

Historical model:

```text
ln(units + adjustment) =
  intercept + elasticity * ln(price)
```

The default zero-unit adjustment is `1.0`. No unsupported control variables are added in v1.

Historical eligibility checks include:

- Minimum observation count
- Meaningful price variation
- Valid completed or fulfilled sales
- Return and restocked-refund netting
- Sufficient date coverage
- Duplicate observation exclusion
- Data freshness
- Future-data leakage prevention
- Promotion distortion exclusion when promotion is not controlled

Forecast formula:

```text
expected_units =
  baseline_units * (candidate_price / current_price) ^ elasticity
```

Forecasts return lower, central, and upper estimates with a documented uncertainty band and cap.

Settings:

- `DEMAND_RESPONSE_MIN_OBSERVATIONS`, default `6`
- `DEMAND_RESPONSE_MIN_PRICE_VARIATION_RATE`, default `0.05`
- `DEMAND_RESPONSE_MIN_COVERAGE_DAYS`, default `14`
- `DEMAND_RESPONSE_MAX_DATA_AGE_DAYS`, default `45`
- `DEMAND_RESPONSE_ZERO_UNIT_ADJUSTMENT`, default `1.0`
- `DEMAND_RESPONSE_MIN_ELASTICITY`, default `-5.0`
- `DEMAND_RESPONSE_MAX_ELASTICITY`, default `-0.1`
- `DEMAND_RESPONSE_CONSERVATIVE_ELASTICITY_PRIOR`, default `-0.8`
- `DEMAND_RESPONSE_ALLOW_HEURISTIC_FALLBACK`, default `true`
- `DEMAND_RESPONSE_MAX_FORECAST_MULTIPLIER`, default `3.0`
- `DEMAND_RESPONSE_FORMULA_VERSION`, default `v1`

Persistence:

- `demand_elasticity_estimates` stores versioned estimate summaries for audit and reuse.

Current limitation:

- Existing `sales_records` do not store transaction price. The DB-backed estimator therefore cannot learn historical elasticity from current order rows alone. It returns `INSUFFICIENT_DATA` or the explicitly labeled `CONSERVATIVE_HEURISTIC` fallback until transaction-price observations are available.

## Phase 7.3 Dynamic Price Recommendation

Dynamic pricing recommendations are stored in `dynamic_pricing_recommendations`.

Supported actions:

- `PRICE_LOWER`
- `PRICE_RAISE`
- `HOLD`

Insufficient data is represented as recommendation status `INSUFFICIENT_DATA`, not as a pricing action.

Recommendation statuses:

- `OPEN`
- `ACKNOWLEDGED`
- `DISMISSED`
- `EXPIRED`
- `SUPERSEDED`
- `INSUFFICIENT_DATA`

Candidate generation is bounded. The service uses:

- Current price
- Minimum safe price
- Competitor minimum
- Competitor median
- Competitor quartiles
- Configured percentage changes around current price
- Marketplace increment rounding

The service does not generate arbitrary unbounded price grids. Candidates are rounded and deduplicated.

Each candidate is evaluated with:

- Margin protection
- Unit forecast
- Expected revenue
- Expected contribution profit
- Margin rate
- Inventory compatibility
- Market position
- Risk penalties
- Confidence
- Evidence

Objective behavior:

- `MAXIMIZE_EXPECTED_PROFIT`: rank candidates primarily by expected contribution profit.
- `MAXIMIZE_REVENUE_WITH_MARGIN_FLOOR`: rank candidates by expected revenue, but only after margin safety passes.

Penalty factors:

- Low forecast confidence
- Stale competitor data
- Large price change
- Sparse sales history
- High inventory risk
- Candidate outside current market range

Inventory behavior:

- `HIGH` or `CRITICAL` stockout risk penalizes demand-increasing price reductions.
- `LOW` inventory risk can permit controlled lower-price candidates when margins remain safe.
- Inventory status alone does not force a price change.

Safety behavior:

- No automatic price application endpoint exists.
- Recommendation cooldown is enforced.
- Maximum percentage change per recommendation is enforced during candidate generation.
- A configurable minimum improvement threshold is required.
- Candidates rejected by the margin guard are never selected.
- Stale or insufficient analytics returns `HOLD` with `INSUFFICIENT_DATA` status.

Settings:

- `DYNAMIC_PRICING_FORMULA_VERSION`, default `v1`
- `DYNAMIC_PRICING_MIN_IMPROVEMENT_RATE`, default `0.02`
- `DYNAMIC_PRICING_MIN_ACTIONABLE_CHANGE_RATE`, default `0.01`
- `DYNAMIC_PRICING_MAX_CHANGE_RATE`, default `0.15`
- `DYNAMIC_PRICING_EXPIRATION_HOURS`, default `72`

API endpoints:

- `POST /api/v1/products/{product_id}/pricing/recommendations`
- `GET /api/v1/products/{product_id}/pricing/recommendations/latest`
- `GET /api/v1/products/{product_id}/pricing/recommendations`
- `GET /api/v1/pricing/recommendations/{id}`
- `POST /api/v1/pricing/recommendations/{id}/acknowledge`
- `POST /api/v1/pricing/recommendations/{id}/dismiss`
