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
    assert any("m10" in md.value and "Corrected by you" in md.value for md in app.markdown)
    # Email text is shown literally, never interpreted as Markdown.
    assert not app.exception


def test_cloud_engine_needs_key_and_consent(app, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    engine_radio(app).set_value("Cloud AI (API key)").run()
    assert button(app, "Sort and summarize").disabled
    assert any("No API key" in i.value for i in app.info)
    next(t for t in app.text_input if t.label == "API key").input("sk-test").run()
    assert button(app, "Sort and summarize").disabled  # still needs consent
    next(c for c in app.checkbox if c.label.startswith("I understand")).check().run()
    assert not button(app, "Sort and summarize").disabled


def test_users_see_one_sign_in_button_and_no_file_steps(app):
    from campusmail import mailbox
    account = next(r for r in app.radio if r.label == "Account")
    assert not app.exception
    assert not any(b.label == "Sign in with Google" for b in app.button)
    assert any("not built into this copy" in i.value for i in app.info)
    assert not app.get("file_uploader")[1:]  # only the CSV import, no credential upload for users

    mailbox.save_google_client(b'{"installed": {"client_id": "1-a.apps.googleusercontent.com", "client_secret": "s"}}',
                               built_in=True)
    app.run()
    assert any(b.label == "Sign in with Google" for b in app.button)
    account.set_value("Outlook / HKU (Microsoft 365)").run()
    assert any("HKU IT" in i.value for i in app.info)
    mailbox.save_ms_client_id("1a2b3c4d-1234-5678-9abc-1234567890ab", built_in=True)
    app.run()
    assert any(b.label == "Sign in with Microsoft" for b in app.button)
    assert any(b.label.startswith("No window?") for b in app.button)


def test_profile_and_settings_pages(app):
    from campusmail import userdata
    from streamlit import config
    app.switch_page("views/profile.py").run()
    assert not app.exception
    next(t for t in app.text_input if t.label == "Name").input("Chan Tai Man")
    next(t for t in app.text_area if t.label.startswith("Your courses")).input("comp 3297, AILT9019")
    next(b for b in app.button if b.label == "Save profile").click().run()
    assert userdata.load_profile()["courses"] == ["AILT9019", "COMP3297"]

    app.switch_page("views/inbox.py").run()
    assert app.session_state["courses_text"] == "AILT9019, COMP3297"
    assert any("Hi Chan!" in h.proto.body for h in app.get("html"))

    app.switch_page("views/settings.py").run()
    assert not app.exception
    app.get("button_group")[0].set_value("Dark").run()
    assert userdata.load_settings()["theme"] == "Dark"
    assert config.get_option("theme.light.backgroundColor") == config.get_option("theme.dark.backgroundColor")
    next(b for b in app.button if b.label == "Delete my saved profile and settings").click().run()
    assert userdata.load_profile()["name"] == "" and userdata.load_settings()["theme"] == "Match my computer"


def test_email_text_is_escaped_for_markdown():
    from campusmail.ui import md
    escaped = md("**Lab** [click](http://x) :red[hi] $5")
    assert escaped == r"\*\*Lab\*\* \[click\]\(http\://x\) \:red\[hi\] \$5"


def test_time_until_deadline():
    from datetime import timedelta

    from campusmail.ui import until
    from conftest import NOW
    assert until(NOW + timedelta(hours=31), NOW) == "in 31 h"
    assert until(NOW + timedelta(days=5, hours=13), NOW) == "in 6 days"
    assert until(NOW - timedelta(minutes=5), NOW) == "overdue"
