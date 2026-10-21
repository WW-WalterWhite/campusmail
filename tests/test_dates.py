from datetime import datetime

from campusmail.dates import HKT, find_dates, has_vague_timing, parse_iso
from conftest import NOW


def test_day_month_with_time():
    [m] = find_dates("Submit the lab report by 17:00 on 1 October", NOW)
    assert m.value == datetime(2026, 10, 1, 17, 0, tzinfo=HKT)
    assert m.has_time


def test_month_day_and_pm_time():
    [m] = find_dates("Due Oct 2nd at 5pm.", NOW)
    assert m.value == datetime(2026, 10, 2, 17, 0, tzinfo=HKT)


def test_numeric_dates_are_day_month():
    [m] = find_dates("Deadline 3/10/2026 23:59", NOW)
    assert (m.value.day, m.value.month, m.value.hour) == (3, 10, 23)


def test_relative_words_use_received_time():
    tomorrow = find_dates("Reply by tomorrow noon", NOW)[0]
    assert tomorrow.value == datetime(2026, 10, 1, 12, 0, tzinfo=HKT)
    friday = find_dates("Hand in on Friday", NOW)[0]  # NOW is a Wednesday
    assert friday.value.date().isoformat() == "2026-10-02" and not friday.has_time


def test_year_wraps_to_nearest():
    [m] = find_dates("Exam on 5 January", datetime(2026, 12, 20, tzinfo=HKT))
    assert m.value.year == 2027


def test_time_in_other_sentence_is_not_attached():
    [m] = find_dates("Submit by 1 October. The lecture starts at 10:00.", NOW)
    assert not m.has_time


def test_foreign_time_zone_is_flagged():
    [m] = find_dates("Register by 23 October 12:00 GMT.", NOW)
    assert m.foreign_tz
    [m] = find_dates("Register by 23 October 12:00 (GMT+8).", NOW)
    assert not m.foreign_tz


def test_vague_and_iso():
    assert has_vague_timing("Please submit soon")
    assert not has_vague_timing("Submit by 1 October")
    assert parse_iso("2026-10-01") == (datetime(2026, 10, 1, tzinfo=HKT), False)
    assert parse_iso("2026-10-01T09:00:00Z")[0] == datetime(2026, 10, 1, 17, 0, tzinfo=HKT)
    assert parse_iso("next Friday") == (None, False)
