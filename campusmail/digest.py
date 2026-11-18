"""Exports: the plain-text digest and a calendar file (.ics) of the deadlines."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from .dates import HKT, format_dt
from .models import Priority
from .pipeline import MODE_RULES, Run

DISCLAIMER = "Check the original email before acting. CampusMail can miss or misread messages."


def render_text(run: Run, now: datetime) -> str:
    lines = [
        "CampusMail digest",
        f"Reference time: {now.astimezone(HKT):%a %d %b %Y %H:%M} (UTC+8)",
        f"Processed by: {run.model_name}" + (" (rules-only view, no AI summaries)" if run.mode == MODE_RULES else ""),
        DISCLAIMER,
    ]
    if run.notice:
        lines.append(f"NOTICE: {run.notice}")
    for priority, results in run.by_priority().items():
        if not results:
            continue
        lines += ["", f"== {priority.value} ({len(results)}) =="]
        for r in results:
            m, x = r.message, r.extraction
            lines.append(f"- [{m.message_id}] {m.subject}" + ("  (OVERDUE)" if r.overdue else "") + ("  (corrected by you)" if r.corrected else ""))
            if x and priority is not Priority.REVIEW:
                if x.action_text:
                    lines.append(f"    Action: {x.action_text}")
                if r.deadline:
                    lines.append(f"    Deadline: {format_dt(r.deadline, r.deadline_has_time)}")
                label = "Summary" if x.source == "model" else "Key sentences (rules)"
                lines.append(f"    {label}: {x.summary}")
                for q in x.quotes:
                    lines.append(f"    Source [{m.message_id}]: “{q}”")
            for reason in r.reasons:
                lines.append(f"    Why: {reason}")
            for note in r.notes:
                lines.append(f"    Note: {note}")
            for note in r.assumptions:
                lines.append(f"    Assumption: {note}")
    return "\n".join(lines) + "\n"


def _ics_text(value: str) -> str:
    # RFC 5545 text escaping.
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> list[str]:
    """Split a content line into pieces of at most 75 octets, as RFC 5545 requires."""
    pieces, current = [], ""
    for ch in line:
        limit = 75 if not pieces else 74  # continuation lines start with a space
        if len((current + ch).encode("utf-8")) > limit:
            pieces.append(current)
            current = ch
        else:
            current += ch
    pieces.append(current)
    return [pieces[0]] + [" " + p for p in pieces[1:]]


def render_ics(run: Run, now: datetime) -> str:
    """Calendar events for the High and Medium items that have a checked, upcoming deadline.

    Items that need review are left out on purpose: their dates could not be verified. A timed
    deadline becomes a 30-minute event that ends at the deadline, with a reminder a day before; a
    moved class becomes a one-hour event at its new time, with a reminder an hour before; a
    date-only deadline becomes an all-day event.
    """
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//CampusMail//AILT9019//EN", "CALSCALE:GREGORIAN"]
    for priority in (Priority.HIGH, Priority.MEDIUM):
        for r in run.by_priority()[priority]:
            if r.deadline is None or r.overdue or r.deadline < now:
                continue
            m, x = r.message, r.extraction
            title = (x.action_text if x and x.action_text else m.subject) or m.message_id
            uid = hashlib.sha1(f"{m.message_id}|{m.subject}".encode("utf-8")).hexdigest()[:16]
            description = "\n".join([
                f"{priority.value} priority. " + " ".join(r.reasons),
                f"From the email \u201c{m.subject}\u201d ({m.message_id}).",
                DISCLAIMER,
            ])
            event = ["BEGIN:VEVENT", f"UID:{uid}@campusmail", f"DTSTAMP:{stamp}",
                     f"SUMMARY:{_ics_text(title)}", f"DESCRIPTION:{_ics_text(description)}"]
            if m.link:  # opens the email in Outlook or Gmail
                event.append(f"URL:{m.link}")
            if r.deadline_has_time:
                at = r.deadline.astimezone(timezone.utc)
                if x and x.category == "schedule_change":
                    # The time is when the moved session starts; remind an hour before.
                    start, end, alarm = at, at + timedelta(hours=1), "-PT1H"
                else:
                    start, end, alarm = at - timedelta(minutes=30), at, "-P1D"
                event += [f"DTSTART:{start:%Y%m%dT%H%M%SZ}", f"DTEND:{end:%Y%m%dT%H%M%SZ}",
                          "BEGIN:VALARM", "ACTION:DISPLAY", f"TRIGGER:{alarm}",
                          f"DESCRIPTION:{_ics_text(title)}", "END:VALARM"]
            else:
                day = r.deadline.astimezone(HKT).date()
                event += [f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}"]
            event.append("END:VEVENT")
            lines += event
    lines.append("END:VCALENDAR")
    return "".join(piece + "\r\n" for line in lines for piece in _fold(line))
