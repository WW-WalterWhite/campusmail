"""Deterministic English date/time finder used by the rules extractor and the evidence checker.

All times are interpreted in Hong Kong time (UTC+8) unless the text names another zone, in
which case the match is flagged so the message can be sent to review instead of guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

HKT = timezone(timedelta(hours=8), name="UTC+8")

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3, "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}

_MONTH = r"(?P<month>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_DAY = r"(?P<day>[0-3]?\d)(?:st|nd|rd|th)?"
_YEAR = r"(?:,?\s+(?P<year>20\d\d))?"
_WEEKDAY_NAMES = r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tues?|wed|thur?s?|fri|sat|sun"

DATE_PATTERNS = [
    # 1 October 2026, 1st Oct
    re.compile(rf"\b{_DAY}\s+(?:of\s+)?{_MONTH}\b\.?{_YEAR}", re.I),
    # October 1, 2026 / Oct 1st
    re.compile(rf"\b{_MONTH}\.?\s+{_DAY}\b{_YEAR}", re.I),
    # 2026-10-01
    re.compile(r"\b(?P<year>20\d\d)-(?P<month>[01]?\d)-(?P<day>[0-3]?\d)\b"),
    # 1/10/2026 or 1/10 (day/month, Hong Kong convention)
    re.compile(r"\b(?P<day>[0-3]?\d)/(?P<month>[01]?\d)(?:/(?P<year>(?:20)?\d\d))?\b"),
]
RELATIVE_PATTERN = re.compile(
    rf"\b(?P<rel>today|tonight|tomorrow|(?:(?P<mod>this|next|coming)\s+)?(?P<wd>{_WEEKDAY_NAMES}))\b",
    re.I,
)
TIME_PATTERN = re.compile(
    r"\b(?:(?P<h24>[01]?\d|2[0-3])[:.](?P<m24>[0-5]\d)(?:\s*(?P<ap1>[ap])\.?m\.?)?"
    r"|(?P<h12>1[0-2]|0?[1-9])\s*(?P<ap2>[ap])\.?m\.?"
    r"|(?P<word>noon|midday|midnight))\b",
    re.I,
)
# Zones other than Hong Kong time. Their presence makes a deadline unverifiable for us.
FOREIGN_TZ_PATTERN = re.compile(
    r"\b(?:GMT|UTC|BST|CET|CEST|EST|EDT|PST|PDT|CST|JST|AEST|AEDT|IST)(?!\s*\+\s*0?8\b)\b"
    r"|\b(?:london|new york|sydney|tokyo|pacific|eastern)\s+time\b",
    re.I,
)
VAGUE_PATTERN = re.compile(
    r"\b(?:soon|as soon as possible|asap|shortly|in due course|at your earliest convenience|"
    r"later this (?:week|month)|next (?:week|month)|sometime|before long)\b",
    re.I,
)

TIME_WINDOW = 40  # characters around a date in which a time is attached to it


@dataclass(frozen=True)
class DateMatch:
    text: str
    start: int
    end: int
    value: datetime  # timezone-aware, UTC+8
    has_time: bool
    foreign_tz: bool = False


def _year_for(month: int, day: int, ref: datetime) -> int:
    """Pick the year that puts the date closest to the reference time."""
    candidates = []
    for year in (ref.year - 1, ref.year, ref.year + 1):
        try:
            candidates.append(datetime(year, month, day, tzinfo=HKT))
        except ValueError:
            continue
    if not candidates:
        raise ValueError("invalid day/month")
    return min(candidates, key=lambda d: abs(d - ref)).year


def _parse_time(m: re.Match) -> time:
    if m.group("word"):
        return time(0, 0) if m.group("word").lower() == "midnight" else time(12, 0)
    if m.group("h24") is not None:
        hour, minute = int(m.group("h24")), int(m.group("m24"))
        ap = m.group("ap1")
    else:
        hour, minute = int(m.group("h12")), 0
        ap = m.group("ap2")
    if ap:
        ap = ap.lower()
        if hour == 12:
            hour = 0 if ap == "a" else 12
        elif ap == "p":
            hour += 12
    return time(hour, minute)


def _nearest_time(text: str, start: int, end: int, taken: list[tuple[int, int]]) -> re.Match | None:
    s_lo, s_hi = _sentence_bounds(text, start, end)
    lo, hi = max(s_lo, start - TIME_WINDOW), min(s_hi, end + TIME_WINDOW)
    best, best_dist = None, None
    for m in TIME_PATTERN.finditer(text, lo, hi):
        if any(m.start() < e and s < m.end() for s, e in taken):
            continue  # the "time" is part of a date like 1.10 or 1/10
        dist = m.start() - end if m.start() >= end else start - m.end()
        if best_dist is None or dist < best_dist:
            best, best_dist = m, dist
    return best


def _sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """Bounds of the sentence containing text[start:end] (sentences end at . ! ? or newline)."""
    lo = max(text.rfind(c, 0, start) for c in ".!?\n") + 1
    ends = [i for i in (text.find(c, end) for c in "!?\n") if i != -1]
    dot = re.search(r"\.(?:\s|$)", text[end:])
    if dot:
        ends.append(end + dot.start())
    return lo, (min(ends) if ends else len(text))


def find_dates(text: str, ref: datetime) -> list[DateMatch]:
    """Find explicit and relative dates in text, resolved against ref (the email's received time)."""
    ref = ref.astimezone(HKT)
    raw: list[tuple[int, int, date]] = []
    for pattern in DATE_PATTERNS:
        for m in pattern.finditer(text):
            if any(m.start() < e and s < m.end() for s, e, _ in raw):
                continue
            month_raw = m.group("month")
            month = MONTHS.get(month_raw.lower().rstrip(".")) if not month_raw.isdigit() else int(month_raw)
            day = int(m.group("day"))
            if not month or not 1 <= month <= 12 or not 1 <= day <= 31:
                continue
            year_raw = m.group("year")
            try:
                if year_raw:
                    year = int(year_raw) + (2000 if len(year_raw) == 2 else 0)
                    d = date(year, month, day)
                else:
                    d = date(_year_for(month, day, ref), month, day)
            except ValueError:
                continue
            end = m.end()
            if text[end - 1] == "." and month_raw.lower() not in ("jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec"):
                end -= 1  # a full stop after "October" ends the sentence; after "Oct" it is an abbreviation
            raw.append((m.start(), end, d))
    for m in RELATIVE_PATTERN.finditer(text):
        if any(m.start() < e and s < m.end() for s, e, _ in raw):
            continue
        rel = m.group("rel").lower()
        if rel in ("today", "tonight"):
            d = ref.date()
        elif rel == "tomorrow":
            d = ref.date() + timedelta(days=1)
        else:
            # A bare weekday ("Sun") is easy to confuse with ordinary words, so only accept
            # abbreviations when they are capitalised.
            wd_text = m.group("wd")
            if len(wd_text) <= 4 and not wd_text[0].isupper():
                continue
            target = WEEKDAYS[wd_text.lower()]
            delta = (target - ref.weekday()) % 7
            if m.group("mod") and m.group("mod").lower() == "next" and delta == 0:
                delta = 7
            d = ref.date() + timedelta(days=delta)
        raw.append((m.start(), m.end(), d))
    raw.sort()

    taken = [(s, e) for s, e, _ in raw]
    results = []
    for start, end, d in raw:
        tm = _nearest_time(text, start, end, taken)
        s_lo, s_hi = _sentence_bounds(text, start, end)
        foreign = bool(FOREIGN_TZ_PATTERN.search(text, s_lo, s_hi))
        if tm:
            value = datetime.combine(d, _parse_time(tm), tzinfo=HKT)
            span_text = text[min(start, tm.start()):max(end, tm.end())]
        else:
            value = datetime.combine(d, time(0, 0), tzinfo=HKT)
            span_text = text[start:end]
        results.append(DateMatch(span_text, start, end, value, bool(tm), foreign))
    return results


def has_vague_timing(text: str) -> bool:
    return bool(VAGUE_PATTERN.search(text))


def parse_iso(value: str | None) -> tuple[datetime | None, bool]:
    """Parse an ISO 8601 string from the model. Returns (aware datetime in UTC+8, has_time)."""
    if not value:
        return None, False
    value = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return datetime.combine(date.fromisoformat(value), time(0, 0), tzinfo=HKT), False
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None, False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=HKT)
    return dt.astimezone(HKT), True


def format_dt(dt: datetime | None, has_time: bool = True) -> str:
    if dt is None:
        return "none"
    dt = dt.astimezone(HKT)
    return dt.strftime("%a %d %b %Y %H:%M") if has_time else dt.strftime("%a %d %b %Y") + " (no time given, treated as 00:00)"
