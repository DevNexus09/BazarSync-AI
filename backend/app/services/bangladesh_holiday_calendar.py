"""Fixed-date entries verified in the Bangladesh government holiday circulars."""

from datetime import date, datetime, timezone

from pydantic import AnyHttpUrl

from app.schemas.forecast_features import BangladeshHolidayCalendar

BANGLADESH_CALENDARS = (
    BangladeshHolidayCalendar(
        version="bd-mopa-2025-fixed-v1",
        source=AnyHttpUrl(
            "https://file-barisal.portal.gov.bd/uploads/e7623ff8-79e5-4a93-83ce-a86abee1c420/671/f00/298/671f00298fe67937412078.pdf"
        ),
        # Conservative availability bound following the 24 October circulation.
        published_at=datetime(2024, 10, 25, tzinfo=timezone.utc),
        holidays={
            date(2025, 2, 21): True,
            date(2025, 3, 26): True,
            date(2025, 4, 14): True,
            date(2025, 5, 1): True,
            date(2025, 12, 16): True,
            date(2025, 12, 25): True,
        },
    ),
    BangladeshHolidayCalendar(
        version="bd-mopa-2026-fixed-v1",
        source=AnyHttpUrl(
            "https://www.dpp.gov.bd/upload_file/gazettes/59216_19984.pdf"
        ),
        # Conservative availability bound following the 12 November gazette.
        published_at=datetime(2025, 11, 13, tzinfo=timezone.utc),
        holidays={
            date(2026, 2, 21): True,
            date(2026, 3, 26): True,
            date(2026, 4, 14): True,
            date(2026, 5, 1): True,
            date(2026, 12, 16): True,
            date(2026, 12, 25): True,
        },
    ),
)
