"""CSV import and validation. Invalid or oversized messages are kept and flagged, never truncated."""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime

from .dates import HKT
from .models import Message

MAX_MESSAGES = 30
MAX_BODY_CHARS = 3000
REQUIRED_COLUMNS = ("message_id", "received", "subject", "body")
COURSE_CODE = re.compile(r"\b([A-Z]{4})\s?(\d{4})\b")


class CSVImportError(ValueError):
    """The file as a whole cannot be used (wrong columns, too many rows, not CSV)."""


def parse_received(value: str) -> datetime:
    value = value.strip()
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=HKT)  # documented: times without an offset are Hong Kong time
    return dt.astimezone(HKT)


def _non_english(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    non_latin = sum(1 for c in letters if ord(c) > 0x024F)
    return non_latin / len(letters) > 0.2


def load_csv(data: str | bytes, max_messages: int | None = MAX_MESSAGES) -> list[Message]:
    """Parse and validate a CSV. The evaluation script passes max_messages=None for larger sets."""
    if isinstance(data, bytes):
        try:
            data = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise CSVImportError("The file is not UTF-8 text.") from exc
    reader = csv.DictReader(io.StringIO(data))
    columns = [c.strip().lower() for c in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED_COLUMNS if c not in columns]
    if missing:
        raise CSVImportError(f"Missing required column(s): {', '.join(missing)}.")
    try:
        # Extra unnamed cells (a row with too many commas) arrive under the key None; drop them.
        rows = [{k.strip().lower(): (v or "") for k, v in row.items() if k is not None} for row in reader]
    except csv.Error as exc:
        raise CSVImportError(f"The file is not valid CSV: {exc}") from exc
    if max_messages is not None and len(rows) > max_messages:
        raise CSVImportError(f"The file has {len(rows)} messages; the limit is {max_messages}.")

    messages: list[Message] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        problems = []
        message_id = row.get("message_id", "").strip() or f"row-{index}"
        if not row.get("message_id", "").strip():
            problems.append("Missing message ID.")
        elif message_id in seen:
            problems.append("Duplicate message ID.")
            message_id = f"{message_id}#{index}"
        seen.add(message_id)

        received = None
        try:
            received = parse_received(row.get("received", ""))
        except ValueError:
            problems.append("Received time is missing or not ISO 8601 (e.g. 2026-10-21T09:30+08:00).")

        subject = row.get("subject", "").strip()
        body = row.get("body", "").strip()
        problems += content_problems(subject, body)

        messages.append(Message(
            message_id=message_id,
            received=received,
            subject=subject,
            body=body,
            thread_id=row.get("thread_id", "").strip() or None,
            problems=problems,
        ))
    return messages


def content_problems(subject: str, body: str) -> list[str]:
    """Checks shared by every import route (CSV and mailbox)."""
    problems = []
    if not body:
        problems.append("Empty message body.")
    if len(body) > MAX_BODY_CHARS:
        problems.append(f"Body is {len(body)} characters; the limit is {MAX_BODY_CHARS}. Not processed so nothing is cut off.")
    if _non_english(subject + body):
        problems.append("Message does not appear to be in English (only English is supported).")
    return problems


def normalise_course(code: str | None) -> str | None:
    if not code:
        return None
    m = COURSE_CODE.search(code.upper())
    return f"{m.group(1)}{m.group(2)}" if m else None


def parse_course_list(text: str) -> list[str]:
    """Accepts 'COMP3297, AILT 9019' or one code per line."""
    return sorted({f"{a}{b}" for a, b in COURSE_CODE.findall(text.upper())})
