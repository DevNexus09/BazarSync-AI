"""Shared evidence eligibility constants without application startup dependencies."""

from app.models.sales_record import SalesRecordStatus

MIN_MATCH = 0.65
VALID_COUNTING_STATUSES = frozenset(
    {SalesRecordStatus.COMPLETED, SalesRecordStatus.FULFILLED}
)
