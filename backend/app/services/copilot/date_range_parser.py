from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class ParsedDateRange:
    from_date: date
    to_date: date
    source_text: str

    def to_dict(self) -> dict[str, str]:
        return {
            "from_date": self.from_date.isoformat(),
            "to_date": self.to_date.isoformat(),
            "source_text": self.source_text,
        }


@dataclass(frozen=True, slots=True)
class DateRangeParseResult:
    date_range: ParsedDateRange | None
    invalid_reason: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.invalid_reason is None


class CopilotDateRangeParser:
    def __init__(self, *, seller_timezone: str = "Asia/Dhaka", now: datetime | None = None) -> None:
        self._timezone = ZoneInfo(seller_timezone)
        self._now = now

    def parse(
        self,
        question: str,
        *,
        explicit_from_date: date | None = None,
        explicit_to_date: date | None = None,
    ) -> DateRangeParseResult:
        if explicit_from_date or explicit_to_date:
            if not explicit_from_date or not explicit_to_date:
                return DateRangeParseResult(None, "Both from_date and to_date are required when an explicit date filter is supplied.")
            return _validated_range(explicit_from_date, explicit_to_date, "explicit date filter")

        normalized = " ".join((question or "").casefold().split())
        today = self._today()
        explicit = _parse_iso_range(normalized)
        if explicit:
            return _validated_range(explicit[0], explicit[1], explicit[2])

        if _contains_any(normalized, ("last week", "গত সপ্তাহ")):
            start = today.fromordinal(today.toordinal() - today.weekday() - 7)
            return DateRangeParseResult(ParsedDateRange(start, start.fromordinal(start.toordinal() + 6), "গত সপ্তাহ" if "গত সপ্তাহ" in normalized else "last week"))
        if _contains_any(normalized, ("last month", "গত মাস")):
            first_this_month = today.replace(day=1)
            last_prev_month = first_this_month.fromordinal(first_this_month.toordinal() - 1)
            return DateRangeParseResult(ParsedDateRange(last_prev_month.replace(day=1), last_prev_month, "গত মাস" if "গত মাস" in normalized else "last month"))
        if _contains_any(normalized, ("yesterday", "গতকাল", "কাল")):
            target = today.fromordinal(today.toordinal() - 1)
            source = "গতকাল" if "গতকাল" in normalized else "কাল" if "কাল" in normalized else "yesterday"
            return DateRangeParseResult(ParsedDateRange(target, target, source))
        if _contains_any(normalized, ("today", "আজ")):
            return DateRangeParseResult(ParsedDateRange(today, today, "আজ" if "আজ" in normalized else "today"))
        if _contains_any(normalized, ("this month", "এই মাস")):
            return DateRangeParseResult(ParsedDateRange(today.replace(day=1), today, "এই মাস" if "এই মাস" in normalized else "this month"))
        return DateRangeParseResult(None)

    def _today(self) -> date:
        if self._now is not None:
            return self._now.astimezone(self._timezone).date() if self._now.tzinfo else self._now.date()
        return datetime.now(self._timezone).date()


ISO_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _parse_iso_range(normalized: str) -> tuple[date, date, str] | None:
    matches = ISO_DATE_RE.findall(normalized)
    if len(matches) < 2:
        return None
    try:
        start = date.fromisoformat(matches[0])
        end = date.fromisoformat(matches[1])
    except ValueError:
        return None
    return start, end, f"{matches[0]} to {matches[1]}"


def _validated_range(start: date, end: date, source_text: str) -> DateRangeParseResult:
    if start > end:
        return DateRangeParseResult(None, "from_date must be on or before to_date")
    return DateRangeParseResult(ParsedDateRange(start, end, source_text))


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)
