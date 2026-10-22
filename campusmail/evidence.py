"""Evidence checks: code, not the model, decides whether an extraction is supported by the email."""

from __future__ import annotations

import re
from datetime import datetime

from .dates import FOREIGN_TZ_PATTERN, TIME_PATTERN, _parse_time, find_dates, parse_iso
from .importer import normalise_course
from .models import Extraction, Message

# Phrases that try to steer an AI or ask for mail actions. Their presence never changes the
# priority by itself; it sends the message to review so a person reads the original.
INJECTION_PATTERN = re.compile(
    r"\b(?:ignore (?:all |any )?(?:previous|prior|above) (?:instructions|rules)|system prompt|"
    r"you are (?:now )?(?:an? )?(?:ai|assistant|chatbot)|as an ai|(?:assistant|ai|chatbot)[,:]\s|"
    r"mark this (?:email|message) as (?:high|urgent|top)|"
    r"(?:forward|send|delete|reply to) (?:all|every|this|these|your) (?:emails?|messages?|inbox|contacts))",
    re.I,
)


def _plain_quotes(text: str) -> str:
    # One-for-one replacements, so positions in the result match the original.
    return text.translate(str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"'}))


def locate(quote: str, message: Message) -> tuple[int, int] | None:
    """Span of the quote in message.text, ignoring case, whitespace and curly quotes."""
    # A quote shortened with "..." must still match each part, in order.
    parts = [p.strip(" .\"'").split() for p in re.split(r"\.\.\.|\u2026", _plain_quotes(quote))]
    parts = [p for p in parts if p]
    if not parts:
        return None
    source = _plain_quotes(message.text)
    start, pos = None, 0
    for words in parts:
        m = re.compile(r"\s+".join(re.escape(w) for w in words), re.I).search(source, pos)
        if not m:
            return None
        start = m.start() if start is None else start
        pos = m.end()
    return start, pos


def quote_in_source(quote: str, message: Message) -> bool:
    return locate(quote, message) is not None


def check(extraction: Extraction, message: Message) -> tuple[list[str], datetime | None, bool]:
    """Return (review reasons, verified deadline, deadline has a time)."""
    reasons: list[str] = []

    if INJECTION_PATTERN.search(message.text):
        reasons.append("The email contains instructions aimed at an AI or asks for mail actions; read the original.")

    if not extraction.quotes:
        reasons.append("No supporting quotation was given.")
    for quote in extraction.quotes:
        if not quote_in_source(quote, message):
            reasons.append(f"Quotation not found in the email: “{quote[:80]}”.")

    if extraction.course:
        code = normalise_course(extraction.course)
        found = {normalise_course(m) for m in re.findall(r"[A-Za-z]{4}\s?\d{4}", message.text)}
        if code is None or code not in found:
            reasons.append(f"Course {extraction.course} is not written in the email.")
        else:
            extraction.course = code

    if extraction.deadline_status == "vague" and (extraction.action_required or extraction.category == "schedule_change"):
        reasons.append("Timing is vague (e.g. “soon”); no date was invented.")
    if extraction.deadline_status == "conflicting":
        reasons.append("The email gives conflicting dates.")

    deadline, has_time = None, False
    if extraction.deadline:
        deadline, has_time = _verify_deadline(extraction, message, reasons)
    elif extraction.deadline_status == "explicit":
        reasons.append("Marked as having an explicit deadline but no date was given.")
    if extraction.source == "model":
        reasons += check_summary(extraction.summary, message)
    return reasons, deadline, has_time


NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?%?")


def check_summary(summary: str, message: Message) -> list[str]:
    """Dates, times and numbers in the model's summary must also be in the email.

    This is a cheap guard against invented facts: the summary is free text, so its quotes are
    checked elsewhere, but a wrong day, time or figure in the summary would still mislead.
    """
    problems = []
    source_dates = {d.value.date() for d in find_dates(message.text, message.received)}
    taken: list[tuple[int, int]] = []
    for d in find_dates(summary, message.received):
        taken.append((d.start, d.end))
        if d.value.date() not in source_dates:
            problems.append(f"The summary mentions {d.text!r}, a date not found in the email.")
    source_times = {_parse_time(m) for m in TIME_PATTERN.finditer(message.text)}
    for m in TIME_PATTERN.finditer(summary):
        if any(m.start() < e and s < m.end() for s, e in taken):
            continue
        taken.append((m.start(), m.end()))
        if _parse_time(m) not in source_times:
            problems.append(f"The summary mentions the time {m.group(0)!r}, which is not in the email.")
    source_text = message.text
    for m in NUMBER.finditer(summary):
        if any(m.start() < e and s < m.end() for s, e in taken):
            continue
        if m.group(0).rstrip("%") not in source_text:
            problems.append(f"The summary mentions the number {m.group(0)!r}, which is not in the email.")
    return problems


def _verify_deadline(extraction: Extraction, message: Message, reasons: list[str]) -> tuple[datetime | None, bool]:
    claimed, has_time = parse_iso(extraction.deadline)
    if claimed is None:
        reasons.append("Deadline is not a valid date.")
        return None, False
    quote = extraction.deadline_quote
    if not quote or not quote_in_source(quote, message):
        reasons.append("The deadline has no exact supporting quotation in the email.")
        return None, False

    # Read dates from the whole email and keep those inside the quoted span, so "Friday" is
    # resolved against the received time and a time written just outside the quote still counts.
    q_start, q_end = locate(quote, message)
    text = message.text
    if FOREIGN_TZ_PATTERN.search(text, max(0, q_start - 30), q_end + 40):
        reasons.append("The deadline uses a time zone other than Hong Kong time.")
        return None, False
    found = [d for d in find_dates(text, message.received) if d.start < q_end and q_start < d.end]
    if not found:
        reasons.append(f"Could not confirm the deadline date from \u201c{quote[:60]}\u201d.")
        return None, False
    same_day = [d for d in found if d.value.date() == claimed.date()]
    if not same_day:
        reasons.append(f"Deadline {claimed:%d %b} does not match the email (“{quote[:60]}”).")
        return None, False
    match = same_day[0]
    if match.weekday_mismatch:
        reasons.append(f"The weekday and the date in \u201c{match.text}\u201d disagree; check which one is right.")
        return None, False
    if has_time and match.has_time and match.value != claimed:
        reasons.append(f"Deadline time {claimed:%H:%M} does not match the email ({match.value:%H:%M}).")
        return None, False
    if has_time and not match.has_time:
        has_time = False  # the model added a time the email does not state; keep the date only
        claimed = match.value
    if not has_time and match.has_time:
        claimed, has_time = match.value, True
    return claimed, has_time
