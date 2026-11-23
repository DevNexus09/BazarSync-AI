from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from uuid import uuid4

from app.models.sales_record import SalesRecordStatus
from app.models.sales_velocity import SalesVelocityDataStatus
from app.services.sales_velocity_service import SalesVelocityService


class FakeSalesVelocityRepository:
    def __init__(self) -> None:
        self.products = []
        self.sales_records = []
        self.velocity_rows = {}
        self.aggregate_call_count = 0
        self.stock = {}
        self.stock_calls = []

    def iter_product_batches(self, *, batch_size, seller_id=None, product_id=None):
        filtered = [
            row
            for row in self.products
            if (seller_id is None or row[0].seller_id == seller_id)
            and (product_id is None or row[0].id == product_id)
        ]
        for index in range(0, len(filtered), batch_size):
            yield filtered[index : index + batch_size]

    def aggregate_sales(self, *, seller_id, product_ids, window_start, window_end):
        self.aggregate_call_count += 1
        result = {}
        for record in self.sales_records:
            if record["seller_id"] != seller_id:
                continue
            if record["product_id"] not in product_ids:
                continue
            if record["status"] not in {SalesRecordStatus.COMPLETED, SalesRecordStatus.FULFILLED}:
                continue
            if record.get("is_test_order", False):
                continue
            if not (window_start <= record["sold_at"] < window_end):
                continue
            bucket = result.setdefault(
                record["product_id"],
                {
                    "gross_units_sold": 0,
                    "returned_units": 0,
                    "net_units_sold": 0,
                    "valid_sales_records": 0,
                    "sales_dates": set(),
                },
            )
            returned = record.get("returned_units", 0) + record.get("refunded_restocked_units", 0)
            bucket["gross_units_sold"] += record.get("quantity_sold", 0)
            bucket["returned_units"] += returned
            bucket["net_units_sold"] += max(record.get("quantity_sold", 0) - returned, 0)
            bucket["valid_sales_records"] += 1
            bucket["sales_dates"].add(record["sold_at"].date())
        return {
            product_id: {
                **values,
                "sales_days": len(values.pop("sales_dates")),
            }
            for product_id, values in result.items()
        }

    def daily_available_stock(self, *, seller_id, product_ids, start_date, end_date):
        self.stock_calls.append((seller_id, tuple(product_ids), start_date, end_date))
        return {
            pid: {day: qty for day, qty in days.items() if start_date <= day <= end_date}
            for (sid, pid), days in self.stock.items()
            if sid == seller_id and pid in product_ids
        }

    def add_idempotent(self, record):
        key = (record.product_id, record.as_of_date, record.window_days, record.calculation_version)
        existing = self.velocity_rows.get(key)
        if existing:
            return existing, False
        self.velocity_rows[key] = record
        return record, True

    def latest(self, *, seller_id, product_id, window_days, calculation_version):
        rows = [
            row
            for row in self.velocity_rows.values()
            if row.seller_id == seller_id and row.product_id == product_id
            and (window_days is None or row.window_days == window_days)
            and (calculation_version is None or row.calculation_version == calculation_version)
        ]
        return sorted(rows, key=lambda row: (row.as_of_date, row.calculated_at), reverse=True)[0] if rows else None

    def history(self, *, seller_id, product_id, from_date, to_date, window_days, calculation_version, order, limit, offset):
        rows = [
            row
            for row in self.velocity_rows.values()
            if row.seller_id == seller_id and row.product_id == product_id
            and (from_date is None or row.as_of_date >= from_date)
            and (to_date is None or row.as_of_date <= to_date)
            and (window_days is None or row.window_days == window_days)
            and (calculation_version is None or row.calculation_version == calculation_version)
        ]
        rows.sort(key=lambda row: row.as_of_date, reverse=order == "desc")
        return rows[offset : offset + limit], len(rows)

    def get_for_date(self, *, seller_id, product_id, as_of_date, window_days, calculation_version):
        row = self.velocity_rows.get((product_id, as_of_date, window_days, calculation_version))
        if row and row.seller_id == seller_id:
            return row
        return None


def seller(seller_id=None, timezone_name=None):
    return SimpleNamespace(id=seller_id or uuid4(), timezone=timezone_name)


def product(owner, *, created_at=None, product_id=None):
    return SimpleNamespace(
        id=product_id or uuid4(),
        seller_id=owner.id,
        seller=owner,
        created_at=created_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def sale(owner, item, *, quantity, sold_at, status=SalesRecordStatus.COMPLETED, returned=0, restocked_refund=0, test=False):
    return {
        "seller_id": owner.id,
        "product_id": item.id,
        "quantity_sold": quantity,
        "sold_at": sold_at,
        "status": status,
        "returned_units": returned,
        "refunded_restocked_units": restocked_refund,
        "is_test_order": test,
    }


class SalesVelocityServiceTests(unittest.TestCase):
    def test_300_units_over_30_days_equals_10_per_day(self):
        owner = seller()
        item = product(owner)
        repo = FakeSalesVelocityRepository()
        repo.sales_records = [
            sale(owner, item, quantity=300, sold_at=datetime(2026, 6, 15, tzinfo=timezone.utc))
        ]
        service = SalesVelocityService(repository=repo, default_window_days=30)

        outcome = service.calculate_for_product(product=item, seller=owner, as_of_date=date(2026, 6, 29))

        self.assertTrue(outcome.created)
        self.assertEqual(300, outcome.record.net_units_sold)
        self.assertEqual("10.0000", str(outcome.record.daily_sales_rate))
        self.assertEqual(SalesVelocityDataStatus.SUFFICIENT, outcome.record.data_status)

    def test_zero_valid_sales_record_is_confirmed_zero(self):
        owner = seller()
        item = product(owner)
        repo = FakeSalesVelocityRepository()
        repo.sales_records = [
            sale(owner, item, quantity=0, sold_at=datetime(2026, 6, 20, tzinfo=timezone.utc))
        ]
        service = SalesVelocityService(repository=repo, default_window_days=30)

        outcome = service.calculate_for_product(product=item, seller=owner, as_of_date=date(2026, 6, 29))

        self.assertEqual(0, outcome.record.net_units_sold)
        self.assertEqual("0.0000", str(outcome.record.daily_sales_rate))
        self.assertEqual(SalesVelocityDataStatus.SUFFICIENT, outcome.record.data_status)

    def test_missing_sales_data_is_insufficient_not_confirmed_demand(self):
        owner = seller()
        item = product(owner)
        service = SalesVelocityService(repository=FakeSalesVelocityRepository(), default_window_days=30)

        outcome = service.calculate_for_product(product=item, seller=owner, as_of_date=date(2026, 6, 29))

        self.assertEqual(0, outcome.record.net_units_sold)
        self.assertEqual(SalesVelocityDataStatus.INSUFFICIENT, outcome.record.data_status)
        self.assertLessEqual(outcome.record.confidence_score, 20)

    def test_product_younger_than_30_days_uses_observed_days(self):
        owner = seller()
        item = product(owner, created_at=datetime(2026, 6, 25, tzinfo=timezone.utc))
        repo = FakeSalesVelocityRepository()
        repo.sales_records = [
            sale(owner, item, quantity=50, sold_at=datetime(2026, 6, 28, tzinfo=timezone.utc))
        ]
        service = SalesVelocityService(repository=repo, default_window_days=30)

        outcome = service.calculate_for_product(product=item, seller=owner, as_of_date=date(2026, 6, 29))

        self.assertEqual(5, outcome.record.observed_days)
        self.assertEqual("10.0000", str(outcome.record.daily_sales_rate))
        self.assertEqual(SalesVelocityDataStatus.LIMITED, outcome.record.data_status)

    def test_cancelled_pending_failed_and_test_orders_are_excluded(self):
        owner = seller()
        item = product(owner)
        repo = FakeSalesVelocityRepository()
        sold_at = datetime(2026, 6, 20, tzinfo=timezone.utc)
        repo.sales_records = [
            sale(owner, item, quantity=10, sold_at=sold_at, status=SalesRecordStatus.CANCELLED),
            sale(owner, item, quantity=10, sold_at=sold_at, status=SalesRecordStatus.PENDING),
            sale(owner, item, quantity=10, sold_at=sold_at, status=SalesRecordStatus.FAILED_PAYMENT),
            sale(owner, item, quantity=10, sold_at=sold_at, test=True),
            sale(owner, item, quantity=5, sold_at=sold_at, status=SalesRecordStatus.FULFILLED),
        ]
        service = SalesVelocityService(repository=repo, default_window_days=30)

        outcome = service.calculate_for_product(product=item, seller=owner, as_of_date=date(2026, 6, 29))

        self.assertEqual(5, outcome.record.net_units_sold)
        self.assertEqual("0.1667", str(outcome.record.daily_sales_rate))

    def test_returns_and_restocked_refunds_are_handled_once(self):
        owner = seller()
        item = product(owner)
        repo = FakeSalesVelocityRepository()
        repo.sales_records = [
            sale(
                owner,
                item,
                quantity=10,
                returned=2,
                restocked_refund=1,
                sold_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
            )
        ]
        service = SalesVelocityService(repository=repo, default_window_days=30)

        outcome = service.calculate_for_product(product=item, seller=owner, as_of_date=date(2026, 6, 29))

        self.assertEqual(10, outcome.record.gross_units_sold)
        self.assertEqual(3, outcome.record.returned_units)
        self.assertEqual(7, outcome.record.net_units_sold)

    def test_refunded_but_not_restocked_does_not_reduce_net_units(self):
        owner = seller()
        item = product(owner)
        repo = FakeSalesVelocityRepository()
        record = sale(owner, item, quantity=10, sold_at=datetime(2026, 6, 20, tzinfo=timezone.utc))
        record["refund_not_restocked_units"] = 4
        repo.sales_records = [record]
        service = SalesVelocityService(repository=repo, default_window_days=30)

        outcome = service.calculate_for_product(product=item, seller=owner, as_of_date=date(2026, 6, 29))

        self.assertEqual(10, outcome.record.net_units_sold)

    def test_fractional_rate_precision(self):
        owner = seller()
        item = product(owner)
        repo = FakeSalesVelocityRepository()
        repo.sales_records = [
            sale(owner, item, quantity=1, sold_at=datetime(2026, 6, 20, tzinfo=timezone.utc))
        ]
        service = SalesVelocityService(repository=repo, default_window_days=30)

        outcome = service.calculate_for_product(product=item, seller=owner, as_of_date=date(2026, 6, 29))

        self.assertEqual("0.0333", str(outcome.record.daily_sales_rate))

    def test_calculation_versioning_and_duplicate_retry(self):
        owner = seller()
        item = product(owner)
        repo = FakeSalesVelocityRepository()
        repo.sales_records = [
            sale(owner, item, quantity=30, sold_at=datetime(2026, 6, 20, tzinfo=timezone.utc))
        ]
        service = SalesVelocityService(repository=repo, default_window_days=30)

        first = service.calculate_for_product(product=item, seller=owner, as_of_date=date(2026, 6, 29), calculation_version="v1")
        duplicate = service.calculate_for_product(product=item, seller=owner, as_of_date=date(2026, 6, 29), calculation_version="v1")
        new_version = service.calculate_for_product(product=item, seller=owner, as_of_date=date(2026, 6, 29), calculation_version="v2")

        self.assertTrue(first.created)
        self.assertFalse(duplicate.created)
        self.assertTrue(new_version.created)
        self.assertEqual(2, len(repo.velocity_rows))

    def test_seller_isolation(self):
        first_seller = seller()
        second_seller = seller()
        item = product(first_seller)
        repo = FakeSalesVelocityRepository()
        repo.sales_records = [
            sale(first_seller, item, quantity=30, sold_at=datetime(2026, 6, 20, tzinfo=timezone.utc)),
            {"seller_id": second_seller.id, "product_id": item.id, "quantity_sold": 300, "sold_at": datetime(2026, 6, 20, tzinfo=timezone.utc), "status": SalesRecordStatus.COMPLETED},
        ]
        service = SalesVelocityService(repository=repo, default_window_days=30)

        outcome = service.calculate_for_product(product=item, seller=first_seller, as_of_date=date(2026, 6, 29))

        self.assertEqual(30, outcome.record.net_units_sold)

    def test_large_batch_uses_grouped_aggregation(self):
        owner = seller()
        items = [product(owner) for _ in range(5)]
        repo = FakeSalesVelocityRepository()
        repo.products = [(item, owner) for item in items]
        repo.sales_records = [
            sale(owner, item, quantity=30, sold_at=datetime(2026, 6, 20, tzinfo=timezone.utc))
            for item in items
        ]
        service = SalesVelocityService(repository=repo, default_window_days=30)

        result = service.calculate_for_batch(batch_size=10, as_of_date=date(2026, 6, 29))

        self.assertEqual(5, result.created_count)
        self.assertEqual(1, repo.aggregate_call_count)

    def test_date_boundary_and_timezone_behavior(self):
        owner = seller(timezone_name="Asia/Dhaka")
        item = product(owner)
        repo = FakeSalesVelocityRepository()
        repo.sales_records = [
            sale(owner, item, quantity=12, sold_at=datetime(2026, 6, 28, 18, 30, tzinfo=timezone.utc))
        ]
        service = SalesVelocityService(repository=repo, default_window_days=1)

        outcome = service.calculate_for_product(product=item, seller=owner, as_of_date=date(2026, 6, 29))

        self.assertEqual(12, outcome.record.net_units_sold)
        self.assertEqual("12.0000", str(outcome.record.daily_sales_rate))


if __name__ == "__main__":
    unittest.main()


class StockoutAwareVelocityTests(unittest.TestCase):
    AS_OF = date(2026, 6, 30)

    def _setup(self, stock_for_day):
        owner = seller()
        item = product(owner)
        repo = FakeSalesVelocityRepository()
        repo.sales_records = [sale(owner, item, quantity=200, sold_at=datetime(2026, 6, 10, tzinfo=timezone.utc))]
        # Window is 1-30 Jun; history also covers 31 May (start of 1 Jun).
        repo.stock[(owner.id, item.id)] = {
            self.AS_OF - timedelta(days=offset): stock_for_day(self.AS_OF - timedelta(days=offset))
            for offset in range(31)
        }
        return owner, item, repo

    def test_ten_stocked_out_days_use_twenty_day_denominator(self):
        # Out of stock 20-30 Jun: 21-30 Jun start and end at zero -> 10 stocked-out days.
        owner, item, repo = self._setup(lambda day: 0 if day >= date(2026, 6, 20) else 5)
        service = SalesVelocityService(repository=repo, default_window_days=30, calculation_version="v2")

        record = service.calculate_for_product(product=item, seller=owner, as_of_date=self.AS_OF).record

        self.assertEqual("10.0000", str(record.daily_sales_rate))
        self.assertEqual(30, record.observed_days)
        self.assertEqual(10, record.calculation_metadata["stockout_days"])
        self.assertEqual(20, record.calculation_metadata["effective_window_days"])
        self.assertEqual("1.0000", record.calculation_metadata["stock_history_coverage"])
        self.assertEqual(SalesVelocityDataStatus.SUFFICIENT, record.data_status)

    def test_no_history_matches_v1(self):
        owner, item, repo = self._setup(lambda day: 0)
        repo.stock = {}
        v2 = SalesVelocityService(repository=repo, default_window_days=30, calculation_version="v2")
        v1 = SalesVelocityService(repository=repo, default_window_days=30, calculation_version="v1")

        r2 = v2.calculate_for_product(product=item, seller=owner, as_of_date=self.AS_OF).record
        r1 = v1.calculate_for_product(product=item, seller=owner, as_of_date=self.AS_OF).record

        self.assertEqual(r1.daily_sales_rate, r2.daily_sales_rate)
        self.assertEqual(0, r2.calculation_metadata["stockout_days"])
        self.assertEqual("0.0000", r2.calculation_metadata["stock_history_coverage"])

    def test_v1_ignores_stock_history(self):
        owner, item, repo = self._setup(lambda day: 0)
        service = SalesVelocityService(repository=repo, default_window_days=30, calculation_version="v1")

        record = service.calculate_for_product(product=item, seller=owner, as_of_date=self.AS_OF).record

        self.assertEqual("6.6667", str(record.daily_sales_rate))
        self.assertEqual([], repo.stock_calls)
        self.assertNotIn("stockout_days", record.calculation_metadata)

    def test_mostly_stocked_out_window_is_limited(self):
        owner, item, repo = self._setup(lambda day: 0 if day <= date(2026, 6, 26) else 5)
        service = SalesVelocityService(repository=repo, default_window_days=30, calculation_version="v2")

        record = service.calculate_for_product(product=item, seller=owner, as_of_date=self.AS_OF).record

        self.assertEqual(26, record.calculation_metadata["stockout_days"])
        self.assertEqual(SalesVelocityDataStatus.LIMITED, record.data_status)
        self.assertEqual("stocked_out_more_than_80_percent_of_window", record.calculation_metadata["limited_reason"])
        self.assertLessEqual(record.confidence_score, 65)

    def test_single_zero_snapshot_after_in_stock_day_is_kept(self):
        # Sold out during 30 Jun: it started the day with stock, so it is not a whole-day stockout.
        owner, item, repo = self._setup(lambda day: 0 if day == self.AS_OF else 5)
        service = SalesVelocityService(repository=repo, default_window_days=30, calculation_version="v2")

        record = service.calculate_for_product(product=item, seller=owner, as_of_date=self.AS_OF).record

        self.assertEqual(0, record.calculation_metadata["stockout_days"])

    def test_batch_reads_stock_only_for_own_seller(self):
        owner, item, repo = self._setup(lambda day: 0 if day >= date(2026, 6, 20) else 5)
        other = seller()
        other_item = product(other)
        repo.stock[(other.id, item.id)] = {day: 5 for day in repo.stock[(owner.id, item.id)]}  # same product id, other seller
        repo.products = [(item, owner), (other_item, other)]
        repo.sales_records.append(sale(other, other_item, quantity=200, sold_at=datetime(2026, 6, 10, tzinfo=timezone.utc)))
        service = SalesVelocityService(repository=repo, default_window_days=30, calculation_version="v2")

        service.calculate_for_batch(as_of_date=self.AS_OF)

        rates = {row.seller_id: str(row.daily_sales_rate) for row in repo.velocity_rows.values()}
        self.assertEqual("10.0000", rates[owner.id])
        self.assertEqual("6.6667", rates[other.id])
        self.assertEqual({owner.id, other.id}, {call[0] for call in repo.stock_calls})

    def test_v2_redelivery_does_not_duplicate(self):
        owner, item, repo = self._setup(lambda day: 0 if day >= date(2026, 6, 20) else 5)
        repo.products = [(item, owner)]
        service = SalesVelocityService(repository=repo, default_window_days=30, calculation_version="v2")

        first = service.calculate_for_batch(as_of_date=self.AS_OF)
        second = service.calculate_for_batch(as_of_date=self.AS_OF)

        self.assertEqual((1, 0), (first.created_count, first.skipped_count))
        self.assertEqual((0, 1), (second.created_count, second.skipped_count))
        self.assertEqual(1, len(repo.velocity_rows))
