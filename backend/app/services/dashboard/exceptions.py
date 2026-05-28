from __future__ import annotations


class DashboardServiceError(Exception):
    status_code = 400
    error_code = "dashboard_error"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class InvalidSortFieldError(DashboardServiceError):
    status_code = 400
    error_code = "invalid_sort_field"


class PaginationOverflowError(DashboardServiceError):
    status_code = 400
    error_code = "pagination_overflow"


class DashboardDatabaseError(DashboardServiceError):
    status_code = 500
    error_code = "dashboard_database_error"
