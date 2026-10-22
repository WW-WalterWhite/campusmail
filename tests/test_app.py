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


def test_mail_setup_is_asked_once_then_sign_in_is_one_click(app, tmp_path, monkeypatch):
    from campusmail import mailbox
    monkeypatch.setattr(mailbox, "LOCAL_DIR", tmp_path / "secrets")
    monkeypatch.setattr(mailbox, "TEAM_DIR", tmp_path / "team_setup")
    monkeypatch.delenv("CAMPUSMAIL_GOOGLE_CLIENT_FILE", raising=False)
    monkeypatch.delenv("CAMPUSMAIL_MS_CLIENT_ID", raising=False)
    account = next(r for r in app.radio if r.label == "Account")
    account.set_value("Gmail").run()
    assert not app.exception
    assert not any(b.label == "Sign in with Google" for b in app.button)
    assert any("One-time setup" in m.value for m in app.markdown)

    mailbox.save_google_client(b'{"installed": {"client_id": "123-abc.apps.googleusercontent.com", "client_secret": "s"}}')
    app.run()
    assert any(b.label == "Sign in with Google" for b in app.button)
    assert any("saved on this computer" in c.value for c in app.caption)

    account.set_value("Outlook / HKU (Microsoft 365)").run()
    assert button(app, "Sign in with Microsoft").disabled  # no app ID yet
    next(t for t in app.text_input if t.label == "Microsoft app ID").input("not-an-id").run()
    button(app, "Sign in with Microsoft").click().run()
    assert any("not a Microsoft app ID" in e.value for e in app.error)
    assert mailbox.ms_client_id() == ("", "")
