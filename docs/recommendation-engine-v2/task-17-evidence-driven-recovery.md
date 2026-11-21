# Task 17 · Evidence-driven dead-stock recovery

## Recovery decisions

`EVIDENCE_DRIVEN_RECOVERY_ENABLED` defaults to false. Set it consistently on the API and workers to opt in. The existing assessment, classification rules, actions, API payloads, and recommendation lifecycle serve both modes. Task 17 writes records with `calculation_version=evidence-recovery-v1` using the existing assessment-and-version uniqueness key. Generation replay returns that stored decision. The recommendation and its RAG outbox entry commit together. Disabling the flag restores legacy generation and keeps existing history readable.

| Existing action | Task 17 eligibility |
| --- | --- |
| HOLD | Healthy or newly stocked assessment with no recovery requirement |
| MANUAL_REVIEW | Restricted product, stale or insufficient assessment, or unavailable evidence for every actionable strategy |
| SEO_FIX | Fresh Daraz visibility or listing-quality evidence, or a fresh assessment with a recorded visibility finding |
| DISCOUNT | Old high-risk or dead stock, recent scoped recorded sales evidence, and a current inventory snapshot matching the assessment. The quote must satisfy MarginGuard and the configured discount grid. |
| FLASH_SALE | Discount eligibility, the configured stock minimum and duration, and at least two screened, nonoverlapping campaign outcomes. The resulting entry is manual campaign advice. |
| BUNDLE | Recorded as a rejected alternative until verified companion terms and combined economics are available. A same-category listing establishes neither compatibility nor bundle economics. |

The stock cap is the lesser of assessed eligible units and on-hand units after reservations from the matching snapshot. Linked aging evidence supplies the age when available, with the estimated-age flag retained. The audit records recorded net units, sales days, velocity window, and version. General historical sell-through stays unavailable when the stock offered during that sales window is unknown.

The promotion reader checks up to 50 recent results over 180 days for the seller and product. It verifies marketplace, recorded BDT currency, closed dates, status, nonnegative outcome values and expenses, linked plan scope, and overlapping windows. Earlier plans and recorded results provide descriptive context. A reported offered quantity can support an observed sell-through ratio for that campaign. Seasonality, stockouts, data coverage, concurrent prices, campaign expenditure, and underlying demand can affect outcomes. Candidate sales response and uplift remain unknown.

## Prices, forecasts, and financial scenarios

Every proposed price is rounded through MarginGuard using the effective marketplace increment. The exact resulting price must remain below the current price and within the configured discount grid. The audit preserves the verdict, fee policy version, and rejection reasons. Ranking uses assessment risk, guarded unit margin, listing findings, campaign complexity, and the approved baseline stock-exposure signal. At equal scores, the smaller discount ranks first. A flash-sale proposal ranks behind a comparable discount. The orchestration path can prefer a compatible listing improvement when another engine supplies actionable pricing or reorder advice. Final price and inventory checks remain in the orchestrator.

An approved Task 14 active or previous 30-day forecast supplies product-level baseline demand risk when available. The forecast is scoped to the seller and product and anchored to the current catalog price and a fresh origin. Evidence preserves the version and interval status. A baseline point that covers the eligible stock makes discounting less urgent. It supplies neither promotional sales quantities nor stockout probabilities.

Financial scenarios use Decimal and the guard's rounded per-unit fee quote. They show zero, one, and all eligible units sold as explicit assumptions. The outputs include gross revenue, fees, net cash, contribution, recovered cost basis, remaining inventory cost basis, and the contribution change at the same assumed quantity when the current price is also guard-eligible. Order composition and campaign expenditure are outside the model.

The optional product specification `holding_cost_bdt_per_unit_per_day` supplies the BDT holding cost for the remaining units. The scenario assumes the units sold leave at the start of the window and calculates the holding cost of the remainder over 30 days for a discount or the proposed flash-sale duration. Missing or invalid holding cost leaves this value null.

The capital-estimate worker and simulation API use the same explicit scenarios for Task 17. Expected units and recovered cash remain null on those records. The latest estimate and dashboard associate capital outcomes with the correct Task 17 recommendation, including during the interval before its estimate is calculated. Recovery and acknowledgment are advisory. They leave marketplace promotions and live prices untouched.

## Verification

The 12 Task 17 cases covered new and old stock, missing sales, prior discounts, invalid campaign records, margin rejection, inventory reservations, absent forecasts and holding costs, manual review, atomic outbox writes, capital-estimate linkage, and compatibility with an orchestrated reorder. The focused regression passed 220 tests. Scoped Ruff and mypy checks passed, and the Alembic head remained unchanged. A separate 31-test run covered the optional StatsForecast cases.

The final full backend run used disposable PostgreSQL and Redis. It passed 1,021 tests and 809 subtests, skipped the three optional StatsForecast cases, and reproduced the 24 existing Copilot orchestrator failures.

Forecast-based recovery decisions were tested with fixtures. Promotional response and forecast accuracy on live seller data remain unverified.
