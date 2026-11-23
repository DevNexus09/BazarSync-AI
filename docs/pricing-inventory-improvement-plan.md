# Pricing analytics and inventory intelligence improvement plan

Status: proposal · Written 2026-11-23 · Branch at time of writing: `feature/copilot-robustness`

This plan is based on reading the code, not the README. It covers four things:

1. Correctness fixes in the calculations.
2. A redesign of the **pricing analytics** frontend.
3. A redesign of the **inventory intelligence** frontend.
4. Model quality and a feedback loop that measures whether recommendations worked.

Every runtime change follows [AGENTS.md](../AGENTS.md): seller identity comes from the authenticated context, migrations are additive only, money is Decimal, new behaviour is behind default-off flags, outputs are versioned, and recommendations never change live price or stock.

---

## 1. Current state (what the code does today)

### 1.1 Inventory pipeline

`sales_velocity` → `stockout_prediction` → `reorder_recommendation` → `inventory_risk` → `inventory_intelligence` (read model) → Telegram alerts.

| Area | Finding | Where |
|---|---|---|
| Velocity | `daily_sales_rate = net_units / window_days` counts the days the product had no stock. Demand on items that sold out is underestimated, so they get reordered too little. | `backend/app/services/sales_velocity_service.py` (`observed_days`) |
| Reorder | Safety stock is a fixed `rate × 3 days` and doesn't reflect how much demand varies. The forecast-aware path exists but `forecast_aware_reorder_enabled=False`. | `backend/app/services/reorder_recommendation_service.py:231` |
| Freshness | The daily workflow schedule is off (`inventory_intelligence_schedule_enabled=False`), so the data is only as fresh as the last manual click. | `backend/app/core/config.py:135`, `core/celery_app.py:74` |
| Actions | `acknowledge`, `mark-ordered` and `dismiss` reorder endpoints exist, but the frontend never calls them. | `backend/app/api/v1/reorder_recommendations.py` |

### 1.2 Pricing pipeline

| Area | Finding | Where |
|---|---|---|
| Demand score | Competitor stock `UNKNOWN` (the scraper default) counts as out of stock, which inflates the demand score. | `pricing_analytics_service.calculate_demand_score` |
| Elasticity | Per-product log-log OLS with no controls (`"controls": []`). Most products fall back to the default value. | `backend/app/services/demand_response_service.py` |
| Forecast-assisted pricing | Always returns `HOLD` with `recommended_target_price=None`. It only collects evidence for now. | `dynamic_pricing_service.build_forecast_assisted_recommendation` |
| Confidence | Hand-picked constants (80/55/25 + bonuses), not calibrated against real results. | `calculate_confidence` |
| Simulator | Hard-coded elasticity `-1.2` and float math, duplicated in Python and TypeScript. | `backend/app/lib/pricing/revenue_simulator.py`, `frontend/src/lib/pricing/revenueSimulator.ts` |
| Not exposed | The frontend never calls `GET /products/{id}/pricing/analytics` or `/pricing/recommendations/*`. | `frontend/src` (no references) |

### 1.3 Frontend UX problems

**Pricing page (`frontend/src/pages/pricing/pricing-page.tsx`)**
- The page is called "Pricing analytics", but all it does is let you **type numbers into a simulator**. It asks for *current price, unit cost and stock*, which the system already stores.
- Without products loaded, the seller must type a raw **product UUID** ("Enter product id").
- Candidate prices go in as free text ("290, 320, 349, 399").
- None of the real analytics (competitor quartiles, market position, margin-safe minimum price, recommendation) is shown.
- `pages/pricing/components/RevenueSimulatorCard.tsx` (486 lines) is not imported anywhere. It's dead code.
- Setup (fee policy, pricing policy) lives on three separate routes with no indication of progress.

**Inventory intelligence page (`frontend/src/pages/inventory-intelligence/inventory-intelligence-page.tsx`, 1,053 lines)**
- One long page holds everything: summary metrics (4) → dead-stock dashboard (5 metric cards, 5 filters, table, age distribution, recovery panel, simulator, triggered rules) → reorder list → product detail (12 fields, including "Version") → data quality → risk list.
- Two separate sets of metric cards (inventory plus dead stock) compete for attention. Nothing says "do this first".
- Internal terms leak into the UI: `calculationVersion`, data status enums, "Triggered rules and evidence".
- `PAGE_LIMIT = 8` with Previous/Next only: no search, no sorting by column.
- Product detail needs a separate product dropdown instead of a click on a table row.
- There are only two shared UI primitives (`components/ui/button.tsx`, `input.tsx`). Every page builds its own cards, badges and selects, so the pages look inconsistent.

---

## 2. Goals and design principles

**Product goal:** in under 10 seconds a seller should know *what to reorder, what to reprice and what is stuck*, and be able to act on it.

Design principles for both redesigns:

1. **Action first, detail on demand.** Open with a short prioritised to-do list, and put the evidence behind a click (drawer).
2. **Never ask for data we already have.** Pick a product, and price, cost, stock and fees fill in automatically.
3. **Plain language.** "Runs out in 6 days", not "days_remaining 6.0000". Internal fields (version, formula, dedupe keys) go under a collapsible "How we calculated this".
4. **Missing data is shown honestly and can be fixed.** "Unavailable" always says why and offers a one-click fix (for example "Add supplier lead time").
5. **One visual system.** Shared card, badge, table, drawer, tabs and empty states, used on both pages.
6. **Bilingual-ready.** All new strings go through an i18n map (same approach as `components/copilot/copilot-i18n.ts`) so Bangla can be added.
7. **Accessible.** Keyboard navigation for tables and drawers, colour is never the only signal (icon and text on every status), WCAG AA contrast, works at 375px width.

---

## 3. Phased plan

| Phase | Scope | Size | Flag |
|---|---|---|---|
| 1 | Correctness fixes (backend) | 1–2 days | `SALES_VELOCITY_CALCULATION_VERSION=v2`, no flag for the bug fix |
| 2 | Shared UI foundation | 2–3 days | none (no behaviour change) |
| 3 | Pricing analytics redesign | 5–7 days | `VITE_PRICING_V2_UI` |
| 4 | Inventory intelligence redesign | 6–8 days | `VITE_INVENTORY_V2_UI` |
| 5 | Model quality | 1–2 weeks | existing and new backend flags |
| 6 | Outcome tracking and calibration | ~1 week | `RECOMMENDATION_OUTCOMES_ENABLED` |

Phases 1 and 2 can run in parallel. Phases 3 and 4 depend on 2. Phases 5 and 6 are independent of the UI.

---

## Phase 1: correctness fixes (backend)

### 1.1 Unknown competitor stock is not "out of stock"
- **Change:** in `calculate_demand_score`, build the availability ratio only from competitors with `IN_STOCK` or `OUT_OF_STOCK`. If none are known, use the neutral score `50` and record `competitor_availability: "unknown"` in the components.
- **Version:** bump `pricing_analytics_formula_version` to `v2`. Old snapshots stay readable.
- **Tests:** all `UNKNOWN` → 50, mixed known/unknown → ratio over known only, regression test for the old bug.

### 1.2 Stockout-aware velocity (`v2`)
- **Change:** in the sales velocity service, subtract the days where `inventory_history.quantity_available <= 0` (for the whole day) from `effective_window_days`. Use the existing inventory history rows. If there's no history for a day, keep that day and write `stock_history_coverage` into the metadata. Missing history is *unknown*, not *in stock*.
- **Version:** `SALES_VELOCITY_CALCULATION_VERSION=v2`. `v1` rows stay readable.
- **Guard:** if more than 80% of the window was stocked out, set the status to `LIMITED` (too few in-stock days to trust).
- **Tests:** 10 of 30 days out of stock → rate uses 20 days. No history → unchanged from v1. Seller isolation.

### 1.3 Turn on the schedule in staging
- Set `INVENTORY_INTELLIGENCE_SCHEDULE_ENABLED=true` in staging only. Check that the Celery beat runs are idempotent (they already use dedupe keys) and that nothing is created twice on redelivery.

**Done when:** targeted pytest passes, ruff and mypy are clean, and the staging run shows the changed velocity on a seeded product that had a stockout.

---

## Phase 2: shared UI foundation

Build once, use on both pages. Put these in `frontend/src/components/ui/`, styled with Tailwind on the existing `glass-panel` tokens in `src/index.css`:

| Component | Purpose |
|---|---|
| `Card`, `CardHeader`, `CardBody` | Replaces the ad-hoc `glass-panel p-4` sections |
| `StatusBadge` | One badge for risk, action and data status. Each status gets an icon, a label and a colour. Mapping lives in one file. |
| `KpiTile` | Label, value, optional delta and a short "what this means" tooltip |
| `DataTable` | Wraps the already-installed `@tanstack/react-table`: column sort, search, page size 10/25/50, sticky header, row click, collapses to cards on mobile |
| `Drawer` | Right-side panel for row details. Full-screen on mobile. Focus trap, Esc closes. |
| `Tabs` | Accessible tabs whose state is kept in the URL (`?tab=reorder`) |
| `EmptyState` / `MissingData` | Explains why there's no data and gives a fix-it button. Generalises `components/dead-stock/MissingDataReason.tsx`. |
| `HowCalculated` | Collapsible block for formula, version, freshness and assumptions |
| `FreshnessPill` | "Updated 2 h ago" / "Stale, refresh" |

Plus:
- `frontend/src/lib/format.ts`: one shared place for currency (BDT, Decimal strings in, never float math for money), numbers, dates and relative time. It replaces the several local `formatDecimal`/`currency` helpers.
- `frontend/src/lib/ui-i18n.ts`: an English string map with Bangla keys reserved.

**Tests:** unit tests for `StatusBadge` mapping, `DataTable` sorting and search, `Drawer` focus and Esc, and `format.ts`.

---

## Phase 3: pricing analytics redesign

### 3.1 Information architecture

```
/app/pricing                      → Pricing overview (all products)
/app/pricing/:productId           → Product pricing workspace
/app/pricing/setup                → Setup checklist (replaces fee-setup / policy-setup / fee-policies hops)
```
The old routes redirect to the new ones. Setup pages are reused inside the checklist, not rewritten.

### 3.2 Pricing overview: "Where can I earn more?"

```
┌ Pricing ───────────────────────────────── Updated 3h ago · [Refresh] ┐
│ Setup 2/3 complete  ▸ Add marketplace fees to unlock safe prices      │  ← only shown when incomplete
├───────────────┬───────────────┬───────────────┬───────────────────────┤
│ Priced above  │ Priced below  │ Margin at     │ Recommendations       │
│ market: 4     │ market: 7     │ risk: 2       │ waiting: 5            │
├───────────────┴───────────────┴───────────────┴───────────────────────┤
│ [Search product…]  [Position ▾] [Action ▾]                            │
│ Product        Your price  Market (median)  Position     Suggestion   │
│ Rice 5kg       ৳ 349       ৳ 320            ▲ 9% above   Lower → ৳329 │
│ Oil 1L         ৳ 180       ৳ 195            ▼ 8% below   Raise → ৳189 │
│ Soap 3-pack    ৳ 120       —                No market data  Hold      │
└───────────────────────────────────────────────────────────────────────┘
```
- Data: the latest `pricing_analytics` snapshot and the latest `dynamic_pricing` recommendation for each product. **Backend addition:** a read-only, seller-scoped, paginated list endpoint `GET /pricing/overview` built on the existing repositories, so the page doesn't make N+1 calls per product.
- A row click opens the product workspace.

### 3.3 Product pricing workspace: "What price should this be?"

```
┌ ← Rice 5kg Pack ─────────────────────────── Updated 3h ago [Refresh] ┐
│ ┌ Recommendation ─────────────────────────────────────────────────┐   │
│ │ Lower to ৳ 329 (from ৳ 349)        Confidence: Medium           │   │
│ │ +12% expected units · +৳ 1,450/mo profit · margin stays 18%     │   │
│ │ Why: you are 9% above the market median; 3 of 5 sellers in stock │   │
│ │ [Mark as applied]  [Dismiss]   How we calculated this ▸         │   │
│ └─────────────────────────────────────────────────────────────────┘   │
│ ┌ Market position ────────────┐ ┌ Profit at each price ─────────────┐ │
│ │ min  Q1   median  Q3   max  │ │  profit ▲      ●                  │ │
│ │ ├────┼──────┼──────┼────┤   │ │        │   ●       ●              │ │
│ │ 299 310   320    335  360   │ │        │ ●            ●           │ │
│ │                  ▲ you 349  │ │        └───────────────▶ price    │ │
│ │ 5 competitors · 3 in stock  │ │  ▒ below safe minimum ৳ 301       │ │
│ └─────────────────────────────┘ └───────────────────────────────────┘ │
│ ┌ What-if simulator ──────────────────────────────────────────────┐   │
│ │ Price  [══════●═════] ৳ 335   (slider, snaps to price_increment) │   │
│ │ Units/mo 112 · Revenue ৳ 37,520 · Profit ৳ 7,840 · Margin 20.9%  │   │
│ │ Using your sales history (elasticity −0.9) | estimated (−1.2) ⓘ  │   │
│ └─────────────────────────────────────────────────────────────────┘   │
│ ▸ Costs & fees (cost ৳ 240, commission 12%, payment 1.5%, …) [Edit]   │
│ ▸ Price history (chart)                                                │
└───────────────────────────────────────────────────────────────────────┘
```

Details:
- **Recommendation card** uses `GET /products/{id}/pricing/recommendations/latest`. The buttons call the existing `acknowledge` and `dismiss` endpoints. The copy says "Mark as applied" because the system never changes the live price (AGENTS.md). Show a note: "Change the price on Daraz yourself."
- **Market position** is a horizontal box plot (Recharts) built from the snapshot's quartiles, with the seller's price marked. With fewer than 3 competitors it switches to a plain list of competitor prices.
- **Profit curve** plots the existing recommendation `candidates` evidence (price → expected profit). The area below the MarginGuard minimum safe price is shaded and marked "not allowed".
- **Simulator:** a slider that snaps to `policy.price_increment` and is bounded by `max_change_rate`. It is pre-filled from the product (no typing). It uses the stored elasticity estimate when there is one and says which source it used. **Backend:** the simulator endpoint moves to Decimal, and the Python and TS copies collapse into one backend implementation. The frontend calls the API, debounced to 300 ms.
- **Costs & fees** shows the effective fee policy from `GET /pricing-policies/products/{id}/fees/effective`, with a link to edit.
- **Missing setup:** if there's no fee policy, the recommendation card is replaced by "Add fees to see a safe price" plus a button (reusing `PricingSetupRequiredCard`).

### 3.4 Setup checklist
A three-step checklist: **Marketplace fees → Pricing policy (minimum margin, price step) → Competitor tracking**. Each step shows Done/To do and opens the existing setup form. Progress is derived from existing endpoints, so nothing new is stored.

### 3.5 Clean-up
- Delete the unused `pages/pricing/components/RevenueSimulatorCard.tsx` and `frontend/src/lib/pricing/revenueSimulator.ts` (plus its test) once the simulator calls the API.
- The old page stays reachable while `VITE_PRICING_V2_UI` is off.

### 3.6 Acceptance criteria
- A seller can see and act on a pricing recommendation in **≤ 2 clicks** from the sidebar, without typing a price, cost or ID.
- Every "unavailable" value states its reason.
- Works at 375px, has keyboard navigation and an axe check with no serious issues.
- Vitest covers: overview table states (loading/empty/error/data), the recommendation card's acknowledge and dismiss calls, the simulator's elasticity-source label, and the missing fee policy state.
- Backend tests: overview endpoint seller isolation, pagination, no-snapshot rows.

---

## Phase 4: inventory intelligence redesign

### 4.1 Information architecture
Split the 1,053-line page into one shell and three tabs. URL-driven, so links from Telegram alerts can deep-link.

```
/app/inventory-intelligence?tab=today       → "Today" (default)
/app/inventory-intelligence?tab=reorder     → Reorder
/app/inventory-intelligence?tab=dead-stock  → Slow & dead stock
/app/inventory-intelligence?product=<id>    → opens product drawer on any tab
```

New file layout (each under ~250 lines):
```
pages/inventory-intelligence/
  inventory-intelligence-page.tsx   (shell: header, tabs, drawer host)
  tabs/TodayTab.tsx
  tabs/ReorderTab.tsx
  tabs/DeadStockTab.tsx
  components/ProductInventoryDrawer.tsx
  components/StockRunwayBar.tsx
  components/DataHealthBanner.tsx
```

### 4.2 "Today" tab: what needs attention now

```
┌ Inventory ──────────────────────────────── Updated 1h ago [Refresh] ┐
│ ⚠ 3 products have no supplier lead time — reorder dates are guesses │ [Fix]
├──────────────┬──────────────┬──────────────┬────────────────────────┤
│ Out of stock │ Runs out     │ Reorder now  │ Cash stuck in          │
│ 2            │ < 7 days: 5  │ 6            │ slow stock: ৳ 84,000   │
├──────────────┴──────────────┴──────────────┴────────────────────────┤
│ To do today                                                         │
│ 🔴 Reorder Oil 1L — runs out in 3 days, lead time 8 days  [Details] │
│ 🔴 Rice 5kg is out of stock                               [Details] │
│ 🟠 Reorder Sugar 1kg — order 120 by 28 Nov               [Details] │
│ 🟡 Soap 3-pack: no sale in 74 days — try 15% off          [Details] │
│                                        View all reorders ▸          │
└─────────────────────────────────────────────────────────────────────┘
```
- Four KPI tiles only (merged from the 4 inventory and 5 dead-stock tiles). Each tile click filters the relevant tab.
- "To do today" is the top 5–8 items, ranked: out of stock > runs out before lead time > reorder deadline ≤ 3 days > dead stock with the highest locked capital. Ranking is done in the frontend from the existing `reorder-list` and dead-stock summary responses (no new endpoint, unless profiling shows it's needed).
- The data health banner replaces the separate "Data quality" panel. It's one line with a fix button and is hidden when everything is healthy.

### 4.3 Reorder tab

```
[Search…] [Urgency ▾] [Category ▾]                         Sort: Urgency ▾
Product      Stock runway                      Order   By       Action
Oil 1L       ███░░░░░░░ 3 d   (lead 8 d)        150     Today    [Ordered ✓] [Dismiss]
Sugar 1kg    ██████░░░░ 9 d   (lead 7 d)        120     28 Nov   [Ordered ✓] [Dismiss]
Flour 2kg    ██████████ 40 d                     —      —        OK
```
- **StockRunwayBar** shows days of stock left against the lead time, so "will I run out before new stock arrives?" is clear at a glance. Red when runway < lead time.
- **Ordered ✓ / Dismiss** call the existing `mark-ordered` / `dismiss` endpoints, with optimistic updates and Undo for 5 seconds.
- DataTable: 25 per page, column sort, search, CSV export of the visible rows (client-side).

### 4.4 Slow & dead stock tab
- Keep the existing dead-stock data, but reduce the 5 filters to **search + one "Show" segmented control** (All / At risk / Dead / Needs review), with the remaining filters under "More filters".
- Columns: Product · Days since last sale · Cash stuck · Suggested action · Expected recovery.
- The age distribution chart moves to a small chart beside the table header.
- The recovery simulator and "Triggered rules and evidence" move into the product drawer.

### 4.5 Product drawer (opened from any row)

```
┌ Oil 1L ────────────────────────────── ✕ ┐
│ 🔴 High risk · runs out 26 Nov           │
│ Stock: 24 available (30 on hand, 6 held) │
│ Selling ~8/day · 12 incoming             │
│ ┌ Recommendation ──────────────────────┐ │
│ │ Order 150 units by today             │ │
│ │ Covers lead time 8 d + 3 d buffer    │ │
│ │ [Mark ordered]  [Dismiss]            │ │
│ └──────────────────────────────────────┘ │
│ Stock trend (30 d)  ▁▂▃▅▃▂▁              │
│ ▸ Recovery options (if slow stock)       │
│ ▸ How we calculated this                 │
│   formula · version · freshness · inputs │
└──────────────────────────────────────────┘
```
- Data: the existing `GET /inventory-intelligence/products/{id}`, plus inventory history for the sparkline (the existing product inventory history route).
- Replaces the `ProductSelect` dropdown and the 12-field `Detail` grid.

### 4.6 Wording changes (examples)

| Today | Redesign |
|---|---|
| Days remaining 6.0000 days | Runs out in 6 days (26 Nov) |
| Insufficient data | Not enough sales yet to predict |
| Locked capital | Cash stuck in stock |
| Calculation version v1 | (moved into "How we calculated this") |
| Triggered rules and evidence | Why we suggest this |

### 4.7 Acceptance criteria
- From the sidebar, a seller can mark a reorder as ordered in **≤ 2 clicks**.
- The default view is no taller than about 1.5 screens on a 1366×768 laptop.
- No internal enum or version string is visible outside "How we calculated this".
- Deep links `?tab=` and `?product=` work. Telegram alert links are updated to use them.
- Existing tests in `inventory-intelligence-page.test.tsx` are moved to the tab components. New tests cover the ranking order of "To do today", optimistic mark-ordered with undo, and the drawer's open/close and focus.

---

## Phase 5: model quality (backend, flagged)

1. **Elasticity pooling.** Estimate one elasticity per category with partial pooling toward it (shrink product estimates by observation count). Add weekday and promotion controls and leave out stockout days. Training runs offline in a Celery task, never in a request handler. New `estimation_method=POOLED_CATEGORY`. Flag: `DEMAND_RESPONSE_POOLING_ENABLED`.
2. **Variability-based safety stock.** `safety_stock = z(service_level) × σ_daily × √lead_time`, using the forecast interval service that already exists. Per-product service level defaults to 95%. Shown in the drawer as "Buffer: 18 units (95% protection)".
3. **Forecast-aware reorder rollout.** Turn on `forecast_aware_reorder_enabled` for an allow-listed set of sellers, and compare against v1 in shadow mode for 2 weeks before widening.
4. **Forecast-assisted pricing.** Move from HOLD-only to selecting from the constraint-safe candidates once the out-of-time evaluation (Task 15 doc) passes.

---

## Phase 6: outcome tracking and calibration

1. A new additive table `recommendation_outcome` with these columns:
   - `seller_id`
   - `recommendation_type` (pricing / reorder / recovery)
   - `recommendation_id`
   - `evaluated_at`
   - `window_days`
   - `predicted_value`
   - `observed_value`
   - `observed_status` (`OBSERVED` / `UNAVAILABLE`)
   - `calculation_version`
   - a unique key on `(recommendation_id, window_days)` so it is idempotent
2. A Celery job runs N days after acknowledge or mark-ordered:
   - **Reorder:** did a stockout happen before the deadline? How did predicted units compare with actual?
   - **Price:** units and profit for 14 days before versus after the seller marked the price as applied.
3. Calibrate the pricing and reorder confidence scores against observed hit rates, so "Medium confidence" means a measured percentage.
4. UI: a small "Track record" line on both pages ("Our reorder dates were right 82% of the time in the last 60 days"). It's shown only once there are at least 20 outcomes.

---

## 4. Testing and verification checklist (every phase)

- Backend: `venv/bin/python -m pytest` on the touched suites, plus `ruff` and `mypy`. Include seller-isolation, missing-evidence and replay/redelivery tests where they apply.
- Frontend: `vitest` for new components and tabs, a TypeScript build, and lint. Manual check at 375px and 1366px, in light and dark themes, with keyboard only.
- Review the complete diff for each phase and record results in `docs/recommendation-engine-v2/implementation-progress.md`.

## 5. Rollout

1. Ship Phase 1 and 2 to staging, then production (low risk).
2. Turn on `VITE_PRICING_V2_UI` / `VITE_INVENTORY_V2_UI` for internal sellers first. Collect feedback for one week. Keep the old pages behind the flag-off path.
3. Remove the old pages and dead code once the flags have been on for everyone for two weeks with no rollback.

## 6. Out of scope

- Auto-repricing or pushing stock or price to the marketplace (forbidden by AGENTS.md).
- A new design-system dependency (Radix/shadcn). The few primitives needed are built on Tailwind plus the installed `@tanstack/react-table` and `recharts`.
- Copilot changes.

## 7. Open questions

1. Should the Bangla translation ship together with the redesign or after it?
2. Is Daraz the only marketplace for v2 pricing screens, or should the market panel support several?
3. Default reorder service level: 95%, or set by each seller?
