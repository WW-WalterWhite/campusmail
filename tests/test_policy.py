"""Evidence checks and the priority policy, using the outline's worked example (10:00, 30 Sep)."""

from datetime import datetime

from campusmail import pipeline
from campusmail.dates import HKT
from campusmail.models import Priority
from campusmail.priority import apply_correction
from campusmail.rules import extract_with_rules
from conftest import COURSES, NOW, make_message


def rules_priority(body, subject="Notice"):
    [result] = pipeline.run([make_message(body, subject)], COURSES, NOW).results
    return result


def test_outline_examples():
    assert rules_priority("Submit the lab report by 17:00 on 1 October.").priority is Priority.HIGH
    assert rules_priority("Optional seminar next month.").priority is Priority.LOW
    review = rules_priority("Please submit soon.")
    assert review.priority is Priority.REVIEW and review.deadline is None


def test_action_more_than_48h_away_is_medium():
    assert rules_priority("Submit the essay by 23:59 on 9 October.").priority is Priority.MEDIUM


def test_overdue_is_high_and_marked():
    r = rules_priority("The quiz was due 29 September 08:00. You must complete it.")
    assert r.priority is Priority.HIGH and r.overdue


def test_date_without_time_is_start_of_day_and_labelled():
    r = rules_priority("Please submit the form by 2 October.")
    assert r.deadline == datetime(2026, 10, 2, 0, 0, tzinfo=HKT)
    assert r.assumptions and "00:00" in r.assumptions[0]


def test_enrolled_schedule_change_within_48h_is_high():
    r = rules_priority("COMP3297 tutorial has been moved to 1 October at 14:30.", "COMP3297 tutorial")
    assert r.priority is Priority.HIGH
    other = rules_priority("ECON1210 tutorial has been moved to 1 October at 14:30.", "ECON1210 tutorial")
    assert other.priority is Priority.LOW  # not the student's course


def test_enrolled_course_update_is_medium():
    assert rules_priority("Lecture slides for AILT9019 are now on Moodle.").priority is Priority.MEDIUM


def test_urgent_word_alone_does_not_decide():
    r = rules_priority("Come along to the welcome party, everyone is welcome to join.", "URGENT!!! party")
    assert r.priority is Priority.LOW


def test_conflicting_dates_go_to_review():
    r = rules_priority("Submit the report by 2 October. Correction: an earlier email said 5 October.")
    assert r.priority is Priority.REVIEW


def test_review_sits_above_high_and_bands_sort_by_deadline():
    messages = [
        make_message("Submit part B by 18:00 on 1 October.", message_id="b"),
        make_message("Submit part A by 09:00 on 1 October.", message_id="a"),
        make_message("Please reply soon.", message_id="r"),
    ]
    run = pipeline.run(messages, COURSES, NOW)
    order = [r.message.message_id for r in sorted(run.results, key=lambda r: r.sort_key)]
    assert order == ["r", "a", "b"]


def test_manual_correction_overrides_policy():
    r = rules_priority("Optional seminar next month.")
    apply_correction(r, Priority.HIGH, datetime(2026, 10, 1, 9, 0, tzinfo=HKT), NOW)
    assert r.priority is Priority.HIGH and r.corrected and r.deadline.day == 1


def test_rules_quotes_are_copied_from_the_email():
    message = make_message("Dear class,\nPlease submit the lab report by 17:00 on 1 October.\nRegards")
    x = extract_with_rules(message)
    assert all(q in message.body for q in x.quotes)
    assert x.quotes == ["Please submit the lab report by 17:00 on 1 October."]
