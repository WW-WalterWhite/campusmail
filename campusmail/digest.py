"""Plain-text digest export (the only export the MVP offers)."""

from __future__ import annotations

from datetime import datetime

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
            for note in r.assumptions:
                lines.append(f"    Assumption: {note}")
    return "\n".join(lines) + "\n"
