"""Deterministic priority policy (times in UTC+8). The model never sets the priority."""

from __future__ import annotations

from datetime import datetime, timedelta

from .dates import format_dt
from .models import Extraction, Message, Priority, Result

HIGH_WINDOW = timedelta(hours=48)


def decide(
    message: Message,
    extraction: Extraction,
    deadline: datetime | None,
    has_time: bool,
    review_reasons: list[str],
    courses: set[str],
    now: datetime,
) -> Result:
    result = Result(message, extraction, Priority.LOW, [], deadline, has_time, review_reasons=list(review_reasons))
    if review_reasons:
        result.priority = Priority.REVIEW
        result.reasons = list(review_reasons)
        return result
    if deadline is not None and not has_time:
        result.assumptions.append("No time was given, so the deadline is treated as the start of that day (00:00).")

    enrolled = extraction.course in courses if extraction.course else False
    course_note = ""
    if extraction.course and not enrolled:
        course_note = f" ({extraction.course} is not in your course list)"
    due = format_dt(deadline, has_time)

    if extraction.category == "schedule_change" and enrolled:
        if deadline is not None and now - HIGH_WINDOW <= deadline <= now + HIGH_WINDOW:
            result.priority = Priority.HIGH
            result.reasons.append(f"Schedule change for your course {extraction.course} affecting {due}, within 48 hours.")
        else:
            result.priority = Priority.MEDIUM
            result.reasons.append(f"Schedule change for your course {extraction.course}" + (f" affecting {due}." if deadline else "."))
        return result

    if extraction.action_required:
        if deadline is not None and deadline < now:
            result.priority = Priority.HIGH
            result.overdue = True
            result.reasons.append(f"Overdue: the action was due {due}{course_note}.")
        elif deadline is not None and deadline <= now + HIGH_WINDOW:
            result.priority = Priority.HIGH
            result.reasons.append(f"Action due {due}, within 48 hours{course_note}.")
        elif deadline is not None:
            result.priority = Priority.MEDIUM
            result.reasons.append(f"Action due {due}, more than 48 hours away{course_note}.")
        else:
            result.priority = Priority.MEDIUM
            result.reasons.append(f"Action required with no stated deadline{course_note}.")
        return result

    if enrolled:
        result.priority = Priority.MEDIUM
        result.reasons.append(f"Update for your course {extraction.course}; no action required.")
        return result

    result.priority = Priority.LOW
    result.reasons.append("General information with no required action" + (course_note or "") + ".")
    return result


def apply_correction(result: Result, priority: Priority | None, deadline: datetime | None, now: datetime) -> Result:
    """A student's manual correction always wins over the policy, and is labelled as such."""
    if deadline is not None:
        result.deadline, result.deadline_has_time = deadline, True
        result.overdue = deadline < now and result.extraction is not None and result.extraction.action_required
        result.assumptions = []
    if priority is not None:
        result.priority = priority
    result.corrected = True
    result.reasons = ["Corrected by you."] + [r for r in result.reasons if r != "Corrected by you."]
    return result
