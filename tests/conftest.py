import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from campusmail.dates import HKT  # noqa: E402
from campusmail.models import Message  # noqa: E402

# Wednesday 30 September 2026, 10:00 Hong Kong time: the example in the project outline.
NOW = datetime(2026, 9, 30, 10, 0, tzinfo=HKT)
COURSES = {"COMP3297", "AILT9019"}


def make_message(body: str, subject: str = "Notice", message_id: str = "x1", received: datetime = NOW) -> Message:
    return Message(message_id=message_id, received=received, subject=subject, body=body)


@pytest.fixture
def now():
    return NOW


@pytest.fixture(autouse=True)
def isolated_user_files(tmp_path, monkeypatch):
    """Tests never read or write the developer's real profile, settings or sign-in setup."""
    from campusmail import mailbox, theme, userdata
    monkeypatch.setattr(userdata, "DATA_DIR", tmp_path / "private")
    monkeypatch.setattr(mailbox, "LOCAL_DIR", tmp_path / "secrets")
    monkeypatch.setattr(mailbox, "BUILTIN_DIR", tmp_path / "sign_in")
    monkeypatch.delenv("CAMPUSMAIL_GOOGLE_CLIENT_FILE", raising=False)
    monkeypatch.delenv("CAMPUSMAIL_MS_CLIENT_ID", raising=False)
    yield tmp_path
    theme.apply(theme.MATCH)  # the theme switch changes Streamlit's global config
