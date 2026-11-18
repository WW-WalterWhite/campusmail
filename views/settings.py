"""Settings page: appearance, defaults, the one-time sign-in setup and saved data."""

from __future__ import annotations

import streamlit as st

from campusmail import mailbox, theme, userdata
from campusmail.llm import DEFAULT_MODEL

state = st.session_state
settings = state.settings


def save(**changes) -> None:
    state.settings = userdata.save_settings({**state.settings, **changes})


def change_theme() -> None:
    if not state.theme_choice:  # clicking the selected option again clears it; keep the saved one
        state.theme_choice = state.settings["theme"]
        return
    save(theme=state.theme_choice)
    theme.apply(state.theme_choice)
    state.theme_changed = True


def delete_saved_data() -> None:
    userdata.delete_all()
    state.profile, state.settings = userdata.load_profile(), userdata.load_settings()
    state.theme_choice = state.settings["theme"]
    theme.apply(state.settings["theme"])
    state.theme_changed = True
    st.toast("Saved profile and settings deleted.", icon=":material/check_circle:")


state.setdefault("theme_choice", settings["theme"])
if state.pop("theme_changed", False):
    st.rerun()  # so the browser receives the new colours


st.title(":material/settings: Settings")

with st.container(border=True):
    st.subheader(":material/contrast: Appearance")
    st.segmented_control("Theme", userdata.THEMES, key="theme_choice", on_change=change_theme,
                         help="Saved on this computer.")

with st.container(border=True):
    st.subheader(":material/tune: Defaults")
    with st.form("defaults_form", border=False):
        left, right = st.columns(2)
        engine = left.selectbox("Engine when CampusMail starts", userdata.ENGINES,
                                index=userdata.ENGINES.index(settings["engine"]))
        model = right.text_input("Local AI model", value=settings["ollama_model"] or DEFAULT_MODEL)
        days = left.number_input("Days of mail to fetch from Gmail or Outlook", 1, 60, settings["days_back"])
        if st.form_submit_button("Save defaults", icon=":material/save:"):
            save(engine=engine, ollama_model=model.strip(), days_back=int(days))
            state.engine, state.ollama_model = engine, model.strip() or DEFAULT_MODEL
            st.toast("Defaults saved.", icon=":material/check_circle:")

with st.container(border=True):
    st.subheader(":material/key: Sign-in setup")
    google, microsoft = mailbox.google_client_file(), mailbox.ms_client_id()
    left, right = st.columns(2)
    left.markdown("**Gmail:** " + (f":green-badge[Ready · {google[1]}]" if google else ":orange-badge[Not set up]"))
    right.markdown("**Outlook:** " + (f":green-badge[Ready · {microsoft[1]}]" if microsoft[0]
                                       else ":orange-badge[Not set up]"))
    st.caption("When this shows Ready, users just press Sign in and approve read-only access in the browser "
               "window that opens. Nobody handles files.")
    with st.expander("For the developer: add the app's registration (once)", icon=":material/build:",
                     expanded=not google):
        st.markdown("Register CampusMail once with Google (and optionally Microsoft) as described in the "
                    "[README](https://github.com/WW-WalterWhite/campusmail#optional-import-from-outlook-or-gmail), "
                    "then add the result here.")
        where = st.radio("Save it", ["Built into this copy of CampusMail", "Only on this computer"], horizontal=True,
                         help="Built in: stored in campusmail/sign_in/, so every copy made from this folder or "
                              "repository signs in without setup. Keep the repository private.")
        built_in = where.startswith("Built")
        upload = st.file_uploader("Google: the Desktop app client file (.json)", type=["json"],
                                  key="google_client_upload")
        if upload is not None and state.get("google_upload_id") != upload.file_id:
            state.google_upload_id = upload.file_id
            try:
                mailbox.save_google_client(upload.getvalue(), built_in=built_in)
                st.toast("Gmail sign-in is ready.", icon=":material/check_circle:")
                st.rerun()
            except mailbox.MailboxError as exc:
                st.error(str(exc))
        app_id = st.text_input("Microsoft: Application (client) ID", placeholder="1a2b3c4d-1234-5678-9abc-1234567890ab")
        if st.button("Save Microsoft app ID", disabled=not app_id.strip()):
            try:
                mailbox.save_ms_client_id(app_id, built_in=built_in)
                st.rerun()
            except mailbox.MailboxError as exc:
                st.error(str(exc))
        if (google and google[1] == "this computer") or microsoft[1] == "this computer":
            if st.button("Remove the setup saved on this computer", icon=":material/delete:"):
                mailbox.forget_google_client()
                mailbox.forget_ms_client_id()
                st.rerun()

with st.container(border=True):
    st.subheader(":material/shield_person: Your data")
    st.markdown("CampusMail saves only your profile and these settings, on this computer, in the `private/` "
                "folder. Emails, sign-ins and results are kept in memory and forgotten when you press "
                "**Clear session** or close the app.")
    st.button("Delete my saved profile and settings", icon=":material/delete_forever:", on_click=delete_saved_data)
