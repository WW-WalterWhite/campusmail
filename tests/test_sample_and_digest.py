import csv
import json
import subprocess
import sys

from campusmail import pipeline
from campusmail.digest import DISCLAIMER, render_ics, render_text
from campusmail.models import Priority
from campusmail.importer import load_csv, parse_received
from conftest import ROOT


def sample_run():
    profile = json.loads((ROOT / "data/sample_profile.json").read_text(encoding="utf-8"))
    now = parse_received(profile["reference_time"])
    messages = load_csv((ROOT / "data/sample_inbox.csv").read_bytes())
    return pipeline.run(messages, profile["courses"], now), now


def test_sample_inbox_matches_labels_in_rules_view():
    run, _ = sample_run()
    with (ROOT / "data/sample_labels.csv").open(encoding="utf-8") as f:
        expected = {row["message_id"]: row["expected_priority"] for row in csv.DictReader(f)}
    assert {r.message.message_id: r.priority.value for r in run.results} == expected


def test_digest_has_sources_reasons_and_disclaimer():
    run, now = sample_run()
    text = render_text(run, now)
    assert DISCLAIMER in text and "rules-only view" in text
    assert text.index("== Needs review") < text.index("== High") < text.index("== Medium") < text.index("== Low")
    assert "Source [m01]" in text and "Why:" in text


def test_evaluation_script_runs():
    out = subprocess.run([sys.executable, str(ROOT / "eval/evaluate.py")], capture_output=True, text=True, check=True)
    assert "Macro-F1" in out.stdout


def test_deadline_gate_logic():
    sys.path.insert(0, str(ROOT / "eval"))
    from evaluate import deadline_matches
    from datetime import datetime
    from campusmail.dates import HKT
    five_pm = datetime(2026, 10, 22, 17, 0, tzinfo=HKT)
    assert deadline_matches("2026-10-22T17:00", five_pm, True)
    assert not deadline_matches("2026-10-22T17:00", five_pm, False)
    assert deadline_matches("2026-10-22", five_pm.replace(hour=0), False)
    assert not deadline_matches("2026-10-22", None, False)


def test_bundled_sets_pass_the_safety_gate(tmp_path):
    for name in ("sample", "dev", "challenge"):
        out = tmp_path / name
        subprocess.run([sys.executable, str(ROOT / "eval/evaluate.py"), "--set", name, "--out", str(out)],
                       capture_output=True, text=True, check=True)
        report = json.loads(out.with_suffix(".json").read_text())
        assert report["safety_gate"] == "pass", name


def test_calendar_has_only_checked_upcoming_deadlines():
    run, now = sample_run()
    ics = render_ics(run, now)
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert all(len(line.encode("utf-8")) <= 75 for line in ics.split("\r\n"))
    expected = [r for r in run.results if r.priority in (Priority.HIGH, Priority.MEDIUM)
                and r.deadline is not None and not r.overdue]
    assert expected and ics.count("BEGIN:VEVENT") == len(expected)
    review_subjects = [r.message.subject for r in run.results if r.priority is Priority.REVIEW]
    unfolded = ics.replace("\r\n ", "")
    assert not any(s and s in unfolded for s in review_subjects)
    # Lab 4 is due 22 Oct 17:00 HKT: the event ends then (09:00 UTC) with a reminder a day before.
    assert "DTEND:20261022T090000Z" in ics and "TRIGGER:-P1D" in ics
    # The moved ECON1210 tutorial starts at 14:30 HKT (06:30 UTC).
    assert "DTSTART:20261022T063000Z" in ics
