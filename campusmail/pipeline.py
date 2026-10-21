"""Import → validate → extract → check evidence → rank. The app and the evaluation script both use this."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from . import evidence
from .extraction import InvalidOutput, extract_with_model
from .llm import LLMClient, LLMUnavailable
from .models import Message, Priority, Result
from .priority import decide
from .rules import extract_with_rules

MODE_AI = "ai"
MODE_RULES = "rules"


@dataclass
class Run:
    results: list[Result]
    mode: str  # "ai" or "rules"
    notice: str | None = None  # shown above the list, e.g. the "AI unavailable" notice
    model_name: str | None = None
    seconds: float = 0.0
    timings: dict[str, float] = field(default_factory=dict)

    def by_priority(self) -> dict[Priority, list[Result]]:
        groups: dict[Priority, list[Result]] = {p: [] for p in Priority}
        for r in sorted(self.results, key=lambda r: r.sort_key):
            groups[r.priority].append(r)
        return groups


def _invalid(message: Message) -> Result:
    return Result(message, None, Priority.REVIEW, list(message.problems), review_reasons=list(message.problems))


def _process(message: Message, extraction, courses: set[str], now: datetime) -> Result:
    reasons, deadline, has_time = evidence.check(extraction, message)
    return decide(message, extraction, deadline, has_time, reasons, courses, now)


def run(
    messages: list[Message],
    courses: set[str] | list[str],
    now: datetime,
    client: LLMClient | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> Run:
    courses = set(courses)
    started = time.perf_counter()
    if client is None:
        return _rules_run(messages, courses, now, started, notice=None)

    results: list[Result] = []
    timings: dict[str, float] = {}
    for index, message in enumerate(messages):
        if progress:
            progress(index, len(messages))
        if message.problems:
            results.append(_invalid(message))
            continue
        t0 = time.perf_counter()
        try:
            extraction = extract_with_model(message, client)
        except LLMUnavailable as exc:
            # No partial AI results: show the whole inbox in the labelled rules-only view instead.
            return _rules_run(messages, courses, now, started,
                              notice=f"AI unavailable: {exc} Showing the rules-only view; it has no AI summaries.")
        except InvalidOutput as exc:
            timings[message.message_id] = time.perf_counter() - t0
            reason = f"{exc}. No summary was generated for this message."
            results.append(Result(message, None, Priority.REVIEW, [reason], review_reasons=[reason]))
            continue
        timings[message.message_id] = time.perf_counter() - t0
        results.append(_process(message, extraction, courses, now))
    return Run(results, MODE_AI, None, client.name, time.perf_counter() - started, timings)


def _rules_run(messages, courses, now, started, notice) -> Run:
    results = [
        _invalid(m) if m.problems else _process(m, extract_with_rules(m), courses, now)
        for m in messages
    ]
    return Run(results, MODE_RULES, notice, "keyword/date rules", time.perf_counter() - started)
