import csv
import json
import subprocess
import sys

from campusmail import pipeline
from campusmail.digest import DISCLAIMER, render_text
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
