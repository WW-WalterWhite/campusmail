"""Keyword and date rules. This is both the evaluation baseline and the labelled
"rules-only" view shown when the AI is unavailable. It never writes a summary of its own:
it only copies sentences from the email, so it cannot invent facts.
"""

from __future__ import annotations

import re

from .dates import find_dates, has_vague_timing
from .importer import COURSE_CODE
from .models import Extraction, Message

ACTION_PATTERN = re.compile(
    r"\b(?:submit|upload|hand in|complete|register|sign up|enrol|enroll|pay|return|reply|"
    r"confirm|book|must|required to|need to|needs to|please (?:submit|complete|register|confirm|fill|attend)|"
    r"fill (?:in|out)|finali[sz]e|(?:is|are|was|were) due|due(?: by| on| at| before)|deadline)\b|\bdue:",
    re.I,
)
OPTIONAL_PATTERN = re.compile(r"\b(?:optional|if you are interested|welcome to join|feel free|no action (?:is )?(?:needed|required))\b", re.I)
# Sentences that state when something closes or is due, even without an action verb.
TIMING_PATTERN = re.compile(r"\b(?:closes?|due|deadline|by|before|no later than|until)\b", re.I)
CORRECTION_PATTERN = re.compile(r"\b(?:correction|corrected|instead of|not on|typo|earlier email|previous email)\b", re.I)
CATEGORY_RULES = [
    ("schedule_change", r"\b(?:rescheduled|moved to|postponed|cancelled|canceled|change of venue|venue change|room change|now (?:be )?held|make-?up (?:class|lecture|tutorial)|extra (?:class|lecture|tutorial)|"
                        r"(?:held|move[ds]?) online|instead of in person|no (?:class|lecture|tutorial|lab)s?)\b"),
    ("exam", r"\b(?:exam|examination|midterm|mid-term|quiz|test)\b"),
    ("assignment", r"\b(?:assignment|homework|report|essay|lab report|submission|project)\b"),
    ("group_work", r"\b(?:group|team|teammates?|groupmates?)\b"),
    ("registration", r"\b(?:register|registration|enrol|enrolment|enrollment|sign up)\b"),
    ("event", r"\b(?:seminar|workshop|talk|webinar|fair|festival|concert|event)\b"),
    ("admin", r"\b(?:fee|payment|library|account|password|scholarship|visa)\b"),
]


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def extract_with_rules(message: Message) -> Extraction:
    sentences = split_sentences(message.body)
    full = message.text

    course_match = COURSE_CODE.search(full.upper())
    course = f"{course_match.group(1)}{course_match.group(2)}" if course_match else None

    category = "announcement"
    for name, pattern in CATEGORY_RULES:
        if re.search(pattern, full, re.I):
            category = name
            break

    optional = bool(OPTIONAL_PATTERN.search(full))
    action_sentences = [s for s in sentences if ACTION_PATTERN.search(s)]
    action_required = bool(action_sentences) and not optional

    deadline = deadline_quote = None
    deadline_status = "none"
    timing_sentences = action_sentences if action_required else []
    if category == "schedule_change":
        timing_sentences = [s for s in sentences if re.search(CATEGORY_RULES[0][1], s, re.I)] or sentences
    if timing_sentences:
        if CORRECTION_PATTERN.search(full) and category != "schedule_change":
            timing_sentences = sentences  # a correction elsewhere in the email may contradict the date
        found = [(s, d) for s in timing_sentences for d in find_dates(s, message.received)]
        if not found and category != "schedule_change":
            # "The quiz closes on 22/10 at 12:00. You must complete it." puts the date in another sentence.
            found = [(s, d) for s in sentences if TIMING_PATTERN.search(s) for d in find_dates(s, message.received)]
        distinct = {d.value for _, d in found}
        if len(distinct) > 1 and category != "schedule_change" and CORRECTION_PATTERN.search(full):
            deadline_status = "conflicting"
        elif any(d.weekday_mismatch for _, d in found):
            deadline_status = "conflicting"
        elif found:
            # For a schedule change the last date mentioned is usually the new one; for actions
            # the earliest date is the safer choice.
            match = found[-1][1] if category == "schedule_change" else min((d for _, d in found), key=lambda d: d.value)
            deadline = match.value.isoformat() if match.has_time else match.value.date().isoformat()
            deadline_quote = match.text
            deadline_status = "explicit"
        elif has_vague_timing(full):
            deadline_status = "vague"

    # Skip greetings and sign-offs ("Dear class,", "Regards,") when choosing key sentences.
    content = [s for s in sentences if len(s.split()) >= 4]
    quotes = ([s for s in action_sentences if s in content] or content or sentences)[:2]
    summary_words = " ".join(quotes).split()
    summary = " ".join(summary_words[:60])
    return Extraction(
        course=course,
        category=category,
        action_required=action_required,
        action_text=action_sentences[0] if action_required else None,
        deadline=deadline,
        deadline_status=deadline_status,
        summary=summary,
        quotes=quotes,
        deadline_quote=deadline_quote,
        source="rules",
    )
