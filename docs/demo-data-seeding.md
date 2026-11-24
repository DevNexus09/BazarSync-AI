# Demo store data seeding

## Identity

The demo seller is **Watch Wise - Choice**, modelled on the public Daraz Bangladesh store
<https://www.daraz.com.bd/blzdnq-selection/>.

| Field | Value |
| --- | --- |
| Email | `bazardemo@gmail.com` |
| Phone | `+8801617390260` |
| Shop / business name | Watch Wise - Choice |
| Industry | Watches & Clocks, Dhaka |

The password is never stored in the repository. Supply it through `DEMO_SELLER_PASSWORD` when
creating the account. It is hashed with the production bcrypt implementation and never reset on
reruns.

Catalog fields (titles, brands, specifications, observed prices, listing IDs and URLs) come from 25
public listings of that store, reviewed on 24 November 2026. Everything else is synthetic demo
business data: stock, cost prices, orders, buyers, receipts, fees, visibility, expenses, competitor
comparisons and promotions. No real order, customer or supplier data is used.

The seed is an explicit CLI operation. It is not run by application startup, Alembic, Celery or
deployment. It sends no email, OTP, SMS, Telegram message or marketplace request.

## Safety model

- Dry-run is the default. Writes require `--apply`.
- Writes are allowed only when `APP_ENV` is `development` or `test` and PostgreSQL is local.
- An existing `bazardemo@gmail.com` account without the `demo_seed_records` ownership marker
  aborts the transaction.
- Every seeded seller/product/policy is marked with `demo-watch-wise-v1`. Ordinary sellers are
  never updated or deleted.

## Manifest

[demo_watch_wise_products.json](../backend/seed_data/demo_watch_wise_products.json) holds the 25
listings in SKU order (`WW-001-…` to `WW-025-…`). The comprehensive seed assigns scenarios
`P01`–`P25` in that order, so keep it sorted. Categories: Men's, Women's, Kids' and Couple
watches, and Table & Alarm Clocks. Unverified sizes, colours and materials are listed in
`missing_fields`; ratings, review and sold counts are not imported.

## Commands

From `backend/`, in order:

```bash
PYTHONPATH=. venv/bin/python scripts/seed_demo_store.py --validate
PYTHONPATH=. venv/bin/python scripts/seed_demo_store.py --dry-run
```

```bash
read -s DEMO_SELLER_PASSWORD
export DEMO_SELLER_PASSWORD
PYTHONPATH=. venv/bin/python scripts/seed_demo_store.py --apply
unset DEMO_SELLER_PASSWORD
```

```bash
PYTHONPATH=. venv/bin/python scripts/seed_comprehensive_demo.py \
  --apply --as-of 2026-11-24 --skip-external-services
```

```bash
PYTHONPATH=. venv/bin/python scripts/seed_copilot_demo_extras.py --apply --as-of 2026-11-24
```

## What each stage writes

1. **Catalog** (`seed_demo_store.py`): seller profile, 25 ACTIVE products with description,
   category, cost and selling price, stock, supplier lead time, minimum margin and specifications,
   an opening inventory snapshot, per-product pricing policies (Daraz Bangladesh, BDT, 12% minimum
   margin, ৳10 minimum unit profit, −15%/+20% movement limits, min/max price, ৳1 step, 24h
   cooldown, objective, effective dates) and marketplace fees: product-level for watches (10%
   commission, 1.5% payment fee, ৳5 per unit, ৳3 other variable cost) and one category-level
   policy for Table & Alarm Clocks (12% commission). `WW-002-OLV-2872` deliberately has **no fee
   policy** so MarginGuard shows the missing-evidence case.
2. **Comprehensive** (`seed_comprehensive_demo.py`, see
   [comprehensive demo seeding](comprehensive-demo-seeding.md)): 120 days of orders with 15-digit
   order numbers, listing IDs, Dhaka timestamps and whole-taka prices at several price levels;
   COMPLETED/FULFILLED plus CANCELLED and FAILED_PAYMENT orders that are excluded from demand;
   COMPLETE coverage for 24 products and UNKNOWN coverage for `WW-015-OLV-1020` (insufficient
   evidence case); the reorder keys `quantity_reserved`, `confirmed_incoming_quantity`,
   `minimum_order_quantity` and `pack_size`; 45 daily inventory snapshots; two PO-numbered
   receipts per product (four are 150–220 days old for dead-stock and capital recovery); price
   history; promotions; competitor runs; and every analytics workflow.
3. **Extras** (`seed_copilot_demo_extras.py`): Daraz listings with real listing IDs and URLs,
   ratings, buyer references and delivery districts on orders, 90 days of daily visibility
   metrics that track each product's orders, monthly expenses, supplier bills and the store
   scorecard.

Demand patterns differ by product: steady, rising, declining, seasonal, intermittent, no recent
sales, out of stock, sparse and new arrival.

## Telegram

The seed does not create a Telegram connection, because alerts, daily snapshots and the test
alert need a real chat. Log in as the demo seller, open **Profile → Telegram**, and follow the
connect link to the BazarSync bot.
