from __future__ import annotations

from dataclasses import dataclass
import calendar
from datetime import date, datetime, timedelta
import re
from typing import Any
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class ParsedDateRange:
    from_date: date
    to_date: date
    source_text: str
    # True when the question named no period and default_period() was used.
    defaulted: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "from_date": self.from_date.isoformat(),
            "to_date": self.to_date.isoformat(),
            "source_text": self.source_text,
        }
        if self.defaulted:
            payload["defaulted"] = True
        return payload


def default_period(today: date) -> ParsedDateRange:
    """The one window every tool uses when the question names no period."""
    return ParsedDateRange(today - timedelta(days=3650), today, "all recorded history (no period given)", defaulted=True)


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
        today = self.today()
        explicit = _parse_iso_range(normalized)
        if explicit:
            return _validated_range(explicit[0], explicit[1], explicit[2])
        relative = _parse_latin_period(normalized, today)
        if relative:
            return DateRangeParseResult(relative)

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

    def today(self) -> date:
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


MONTHS = {name.casefold(): index for index, name in enumerate(calendar.month_name) if name}
# "may" is also an English modal verb, so it counts only before a month marker or a year.
MONTH_RE = re.compile(
    r"\b(" + "|".join(name for name in MONTHS if name != "may") + r"|may(?=\s+(?:er|e|mash\w*|month|\d{4})\b))\b"
    r"(?:\s+(\d{4}))?(?:.*?\b(?:prothom|first)\s+(\d{1,2})\s*(?:din|dine|days?)\b)?"
)
LAST_N_DAYS_RE = re.compile(r"\b(?:last|goto|shesh|past)\s+(\d{1,4})\s*(?:din|dine|days?)\b")
# Ordered: the first pattern that matches wins.
RELATIVE_PERIODS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:ei\s*shoptah\w*|this week)\b"), "this week"),
    (re.compile(r"\b(?:goto\s*shoptah\w*|last week)\b"), "last week"),
    (re.compile(r"\b(?:goto\s*mash\w*|last month)\b"), "last month"),
    (re.compile(r"\b(?:gotokal|yesterday)\b"), "yesterday"),
    (re.compile(r"\b(?:aj|ajke|ajker|today)\b"), "today"),
    (re.compile(r"\b(?:ei\s*mash\w*|this month)\b"), "this month"),
    (re.compile(r"\b(?:ei\s*bochor\w*|this year)\b"), "this year"),
)


def _parse_latin_period(normalized: str, today: date) -> ParsedDateRange | None:
    """Banglish and English periods; the seller's week starts on Monday."""
    month = MONTH_RE.search(normalized)
    if month:
        index = MONTHS[month.group(1)]
        # A bare month name is the most recent such month that is not in the future.
        year = int(month.group(2)) if month.group(2) else today.year - (1 if index > today.month else 0)
        start = date(year, index, 1)
        end = date(year, index, calendar.monthrange(year, index)[1])
        label = f"{calendar.month_name[index]} {year}"
        if month.group(3):
            end = min(end, start + timedelta(days=max(1, int(month.group(3))) - 1))
            label = f"first {month.group(3)} days of {label}"
        end = min(end, today)
        return ParsedDateRange(start, end, label) if start <= end else None
    days = LAST_N_DAYS_RE.search(normalized)
    if days and int(days.group(1)) > 0:
        count = int(days.group(1))
        return ParsedDateRange(today - timedelta(days=count - 1), today, f"last {count} days")
    for pattern, label in RELATIVE_PERIODS:
        if not pattern.search(normalized):
            continue
        monday = today - timedelta(days=today.weekday())
        if label == "this week":
            return ParsedDateRange(monday, today, label)
        if label == "last week":
            return ParsedDateRange(monday - timedelta(days=7), monday - timedelta(days=1), label)
        if label == "last month":
            last_prev = today.replace(day=1) - timedelta(days=1)
            return ParsedDateRange(last_prev.replace(day=1), last_prev, label)
        if label == "yesterday":
            return ParsedDateRange(today - timedelta(days=1), today - timedelta(days=1), label)
        if label == "today":
            return ParsedDateRange(today, today, label)
        if label == "this month":
            return ParsedDateRange(today.replace(day=1), today, label)
        return ParsedDateRange(today.replace(month=1, day=1), today, label)
    return None


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)
