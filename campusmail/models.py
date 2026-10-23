"""Data shared by every pipeline stage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

CATEGORIES = (
    "assignment", "exam", "schedule_change", "group_work", "registration",
    "announcement", "event", "admin", "other",
)
DEADLINE_STATUSES = ("explicit", "none", "vague", "conflicting")


class Priority(str, Enum):
    REVIEW = "Needs review"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


PRIORITY_ORDER = {Priority.REVIEW: 0, Priority.HIGH: 1, Priority.MEDIUM: 2, Priority.LOW: 3}


@dataclass
class Message:
    message_id: str
    received: datetime | None
    subject: str
    body: str
    thread_id: str | None = None
    # Problems found during import. A message with problems is never sent to the model.
    problems: list[str] = field(default_factory=list)
    link: str | None = None  # the message in Outlook/Gmail on the web, for mailbox imports
    notes: list[str] = field(default_factory=list)  # import notes that are not problems

    @property
    def text(self) -> str:
        """The text the model sees and the evidence checker searches."""
        return f"{self.subject}\n{self.body}"


@dataclass
class Extraction:
    """Fields the extractor (model or rules) claims about one message."""
    course: str | None = None
    category: str = "other"
    action_required: bool = False
    action_text: str | None = None
    deadline: str | None = None  # ISO 8601; for schedule changes, the time of the changed session
    deadline_status: str = "none"
    summary: str = ""
    quotes: list[str] = field(default_factory=list)
    deadline_quote: str | None = None
    source: str = "model"  # "model" or "rules"

    @classmethod
    def from_dict(cls, data: dict, source: str = "model") -> "Extraction":
        return cls(
            course=data.get("course") or None,
            category=data.get("category") or "other",
            action_required=bool(data.get("action_required")),
            action_text=data.get("action_text") or None,
            deadline=data.get("deadline") or None,
            deadline_status=data.get("deadline_status") or "none",
            summary=(data.get("summary") or "").strip(),
            quotes=[q for q in (data.get("quotes") or []) if isinstance(q, str) and q.strip()],
            deadline_quote=data.get("deadline_quote") or None,
            source=source,
        )


@dataclass
class Result:
    """One message after evidence checks and the priority policy."""
    message: Message
    extraction: Extraction | None
    priority: Priority
    reasons: list[str]
    deadline: datetime | None = None
    deadline_has_time: bool = False
    overdue: bool = False
    review_reasons: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # e.g. a newer message in the thread
    corrected: bool = False

    @property
    def sort_key(self) -> tuple:
        received = self.message.received.timestamp() if self.message.received else 0
        deadline = self.deadline.timestamp() if self.deadline else float("inf")
        return (PRIORITY_ORDER[self.priority], deadline, -received)
