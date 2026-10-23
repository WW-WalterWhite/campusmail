"""CampusMail Streamlit interface. Run with:  streamlit run app.py

This file sets up what every page shares (look, theme, saved profile and settings) and the
navigation; the pages themselves are in views/.
"""

from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path

import streamlit as st

from campusmail import theme, userdata
from campusmail.dates import HKT
from campusmail.llm import DEFAULT_MODEL

ASSETS = Path(__file__).parent / "assets"

st.set_page_config(page_title="CampusMail", page_icon="📬", layout="wide")
st.html(f"<style>{(ASSETS / 'campusmail.css').read_text(encoding='utf-8')}</style>")
st.logo(str(ASSETS / "logo.svg"), size="large")

state = st.session_state
if "profile" not in state:
    state.profile = userdata.load_profile()
    state.settings = userdata.load_settings()
state.logo = "data:image/svg+xml;base64," + base64.b64encode((ASSETS / "logo.svg").read_bytes()).decode()
state.setdefault("messages", None)
state.setdefault("source_name", None)
state.setdefault("last_upload_id", None)
state.setdefault("run", None)
state.setdefault("corrections", {})
state.setdefault("courses_text", ", ".join(state.profile["courses"]))
state.setdefault("engine", state.settings["engine"])
state.setdefault("ollama_model", state.settings["ollama_model"] or DEFAULT_MODEL)
state.setdefault("ref_date", datetime.now(HKT).date())
state.setdefault("ref_time", datetime.now(HKT).time().replace(second=0, microsecond=0))
# Streamlit forgets a widget's value when its page is not shown; re-assigning keeps the inbox
# controls as they were when the user comes back from Profile or Settings.
for key in ("courses_text", "engine", "ollama_model", "ref_date", "ref_time", "mail_service", "mail_days",
            "mail_limit"):
    if key in state:
        state[key] = state[key]

if theme.apply(state.settings["theme"]):
    st.rerun()

page = st.navigation([
    st.Page("views/inbox.py", title="Inbox", icon=":material/inbox:", default=True),
    st.Page("views/profile.py", title="Profile", icon=":material/badge:"),
    st.Page("views/settings.py", title="Settings", icon=":material/settings:"),
])
page.run()
