"""Small text helpers for the Streamlit page (kept here so they can be tested without Streamlit)."""

from __future__ import annotations

import re
from datetime import datetime

MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|>~:$<])")


def md(text: str) -> str:
    """Escape email text so Streamlit shows it literally instead of as Markdown, colour tags or maths."""
    return MARKDOWN_SPECIAL.sub(r"\\\1", text)


def until(deadline: datetime, now: datetime) -> str:
    """'in 5 h', 'in 3 days' or 'overdue', shown next to a deadline."""
    hours = (deadline - now).total_seconds() / 3600
    if hours < 0:
        return "overdue"
    if hours < 1:
        return "within the hour"
    if hours < 48:
        return f"in {round(hours)} h"
    return f"in {round(hours / 24)} days"
