"""Drives the Streamlit app headlessly (no browser, no Ollama, no network)."""

import pytest

from conftest import ROOT

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


def engine_radio(at):
    return next(r for r in at.radio if r.label == "Extraction engine")


def button(at, label):
    return next(b for b in at.button if b.label == label)


@pytest.fixture
def app():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    button(at, "Load sample inbox").click().run()
    return at


def test_rules_run_correction_and_export(app):
    engine_radio(app).set_value("Rules only (no AI)").run()
    button(app, "Sort and summarize").click().run()
    assert not app.exception
    assert [m.value for m in app.metric] == ["5", "3", "2", "3"]
    next(s for s in app.selectbox if s.key == "p-m10").set_value("High")
    next(b for b in app.button if b.form_id == "fix-m10").click().run()
    assert [m.value for m in app.metric] == ["5", "4", "2", "2"]
    assert any("m10" in e.label and "corrected" in e.label for e in app.expander)


def test_cloud_engine_needs_key_and_consent(app, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    engine_radio(app).set_value("Cloud AI (API key)").run()
    assert button(app, "Sort and summarize").disabled
    assert any("No API key" in i.value for i in app.info)
    next(t for t in app.text_input if t.label == "API key").input("sk-test").run()
    assert button(app, "Sort and summarize").disabled  # still needs consent
    next(c for c in app.checkbox if c.label.startswith("I understand")).check().run()
    assert not button(app, "Sort and summarize").disabled
