"""Inbox page: import, sort and review emails."""

from __future__ import annotations

import copy
import html
import json
import re
from datetime import datetime
from pathlib import Path

import streamlit as st

from campusmail import mailbox, pipeline
from campusmail.dates import HKT, format_dt
from campusmail.digest import DISCLAIMER, render_ics, render_text
from campusmail.importer import CSVImportError, load_csv, parse_course_list, parse_received
from campusmail.llm import CLOUD_PROVIDERS, DEFAULT_MODEL, LLMUnavailable, OllamaClient, cloud_client, key_from_env
from campusmail.models import Priority
from campusmail.priority import apply_correction
from campusmail.ui import md, until
from campusmail.userdata import ENGINES, first_name

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SAMPLE_INBOX = DATA / "sample_inbox.csv"
SAMPLE_PROFILE = json.loads((DATA / "sample_profile.json").read_text(encoding="utf-8"))
ENGINE_AI, ENGINE_CLOUD, ENGINE_RULES = ENGINES
# slug for CSS keys, Streamlit colour name, Material icon, one-line meaning
BAND = {
    Priority.REVIEW: ("review", "violet", "policy", "Check these yourself first"),
    Priority.HIGH: ("high", "red", "priority_high", "Due within 48 hours or overdue"),
    Priority.MEDIUM: ("medium", "orange", "schedule", "Action needed, not urgent"),
    Priority.LOW: ("low", "gray", "inbox", "For information"),
}

state = st.session_state
PROFILE, SETTINGS = state.profile, state.settings
SETTINGS_PAGE = "views/settings.py"


def anchor(message_id: str) -> str:
    return "msg-" + re.sub(r"[^a-z0-9]+", "-", message_id.lower())


def set_messages(messages, name: str, real_mail: bool = False) -> None:
    state.messages = messages
    state.source_name = name
    state.real_mail = real_mail
    state.run = None
    state.corrections = {}


def load_messages(data: bytes, name: str) -> None:
    try:
        set_messages(load_csv(data), name)
    except CSVImportError as exc:
        set_messages(None, None)
        st.sidebar.error(str(exc))


def use_current_time() -> None:
    current = datetime.now(HKT)
    state.ref_date, state.ref_time = current.date(), current.time().replace(second=0, microsecond=0)


def fetch_into_inbox(messages, name: str) -> None:
    set_messages(messages, name, real_mail=True)
    use_current_time()
    st.rerun()


def mailbox_import() -> None:
    """Read-only sign-in in a browser pop-up, then fetch. The token stays in memory for this session only."""
    with st.expander("Connect Gmail or Outlook", icon=":material/mail:", expanded=bool(state.get("ms_flow"))):
        service = st.radio("Account", ["Gmail", "Outlook / HKU (Microsoft 365)"], key="mail_service",
                           horizontal=True)
        c1, c2 = st.columns(2)
        days = c1.number_input("Days back", 1, 60, SETTINGS["days_back"], key="mail_days")
        limit = c2.number_input("Messages", 1, 30, 30, key="mail_limit")
        hint = PROFILE.get("email", "")
        try:
            if service == "Gmail":
                found = mailbox.google_client_file()
                if found is None:
                    st.info("Gmail sign-in is not built into this copy of CampusMail yet. The developer adds it "
                            "once in Settings.", icon=":material/info:")
                    st.page_link(SETTINGS_PAGE, label="Open Settings", icon=":material/settings:")
                elif st.button("Sign in with Google", type="primary", width="stretch", icon=":material/login:"):
                    with st.spinner("A Google sign-in window opened in your browser. Approve read-only access there…"):
                        token = mailbox.gmail_sign_in(found[0], login_hint=hint)
                    with st.spinner("Fetching mail…"):
                        fetch_into_inbox(mailbox.gmail_fetch(token, int(limit), int(days)), "your Gmail inbox")
            else:
                client_id, _ = mailbox.ms_client_id()
                if not client_id:
                    st.info("Outlook sign-in is not built into this copy of CampusMail yet. The developer adds it "
                            "once in Settings. HKU accounts also need HKU IT approval.", icon=":material/info:")
                    st.page_link(SETTINGS_PAGE, label="Open Settings", icon=":material/settings:")
                elif not state.get("ms_flow"):
                    if st.button("Sign in with Microsoft", type="primary", width="stretch", icon=":material/login:"):
                        with st.spinner("A Microsoft sign-in window opened in your browser. Approve read-only "
                                        "access there…"):
                            token = mailbox.outlook_sign_in_popup(client_id, login_hint=hint)
                        with st.spinner("Fetching mail…"):
                            fetch_into_inbox(mailbox.outlook_fetch(token, int(limit), int(days)), "your Outlook inbox")
                    if st.button("No window? Use a code instead", width="stretch"):
                        state.ms_app, state.ms_flow = mailbox.outlook_start_sign_in(client_id)
                        st.rerun()
                else:
                    flow = state.ms_flow
                    st.info(f"Open {flow['verification_uri']} and enter the code **{flow['user_code']}**, "
                            "then press the button below.")
                    if st.button("I have signed in: fetch mail", type="primary", width="stretch"):
                        with st.spinner("Waiting for Microsoft sign-in…"):
                            token = mailbox.outlook_finish_sign_in(state.ms_app, flow)
                        state.ms_flow = state.ms_app = None
                        with st.spinner("Fetching mail…"):
                            fetch_into_inbox(mailbox.outlook_fetch(token, int(limit), int(days)), "your Outlook inbox")
                    if st.button("Cancel sign-in", width="stretch"):
                        state.ms_flow = state.ms_app = None
                        st.rerun()
        except mailbox.MailboxError as exc:
            state.ms_flow = state.ms_app = None
            st.error(str(exc))
        st.caption(":material/lock: Read-only access. CampusMail cannot send, delete or change your mail, "
                   "and it never sees your password.")


def use_sample_profile() -> None:
    state.courses_text = ", ".join(SAMPLE_PROFILE["courses"])
    ref = parse_received(SAMPLE_PROFILE["reference_time"])
    state.ref_date, state.ref_time = ref.date(), ref.time()


def clear_session() -> None:
    """Forget the inbox, results, corrections and sign-in; the saved profile and settings stay."""
    for key in list(state.keys()):
        del state[key]


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.subheader(":material/inbox: 1 · Inbox")
    if st.button("Load sample inbox", width="stretch", icon=":material/science:"):
        load_messages(SAMPLE_INBOX.read_bytes(), "sample inbox (synthetic)")
        use_sample_profile()
    upload = st.file_uploader(
        "Or import a CSV (max 30 messages)", type=["csv"],
        help="Columns: message_id, received (ISO 8601), subject, body, and optional thread_id.",
    )
    # Load each uploaded file once: a rerun keeps the run and corrections, and an edited file
    # with the same name is still picked up because it gets a new file_id.
    if upload is not None and state.last_upload_id != upload.file_id:
        state.last_upload_id = upload.file_id
        load_messages(upload.getvalue(), upload.name)
    mailbox_import()

    st.subheader(":material/school: 2 · Your courses")
    if st.button("Use sample course profile", width="stretch", icon=":material/person:"):
        use_sample_profile()
    st.text_area("Course codes", key="courses_text", placeholder="e.g. COMP3297, AILT9019", height=80)
    if PROFILE["courses"]:
        st.caption("Filled in from your profile.")
    st.page_link("views/profile.py", label="Save your courses in your profile", icon=":material/badge:")
    st.caption("Reference time (Hong Kong time, UTC+8)")
    col_d, col_t = st.columns(2)
    col_d.date_input("Date", key="ref_date", label_visibility="collapsed")
    col_t.time_input("Time", key="ref_time", label_visibility="collapsed", step=300)

    st.subheader(":material/memory: 3 · Engine")
    engine = st.radio("Extraction engine", [ENGINE_AI, ENGINE_CLOUD, ENGINE_RULES], key="engine",
                      label_visibility="collapsed")
    client = None
    cloud_blocked = None  # reason the cloud engine cannot run yet
    if engine == ENGINE_AI:
        model = st.text_input("Ollama model", key="ollama_model")
        client = OllamaClient(model=model)
        ready, status = client.status()
        (st.success if ready else st.warning)(status)
    elif engine == ENGINE_CLOUD:
        provider = st.selectbox("Provider", list(CLOUD_PROVIDERS))
        preset = CLOUD_PROVIDERS[provider]
        model = st.text_input("Model", value=preset["model"], key=f"model-{provider}")
        base_url = None
        if preset["kind"] == "openai" and not preset["base_url"]:
            base_url = st.text_input("Base URL", placeholder="https://…/v1")
        env_key = key_from_env(provider)
        typed_key = st.text_input("API key", type="password", key=f"key-{provider}",
                                  placeholder=f"or set {preset['key_env']}" if not env_key else "using the environment variable",
                                  help="Kept in memory for this session only; never saved or logged.")
        st.warning(f"Email text (subject and body) will be sent to **{provider}** for processing. "
                   "Their data policy applies, and API calls may cost money.")
        consent = st.checkbox(f"I understand and want to send these emails to {provider}", key=f"consent-{provider}")
        try:
            client = cloud_client(provider, typed_key or env_key, model, base_url)
        except LLMUnavailable as exc:
            cloud_blocked = str(exc)
        if not consent:
            cloud_blocked = cloud_blocked or "Tick the box to confirm that the emails may be sent to the provider."

    st.divider()
    if st.button("Clear session", width="stretch", icon=":material/delete_sweep:",
                 help="Forget the inbox, results and corrections."):
        clear_session()
        st.rerun()
    st.caption("Nothing is saved or logged. With Local AI or Rules, everything stays on this computer; "
               "with Cloud AI, email text is sent to the chosen provider.")

# ---------------------------------------------------------------- main
courses = parse_course_list(state.courses_text)
now = datetime.combine(state.ref_date, state.ref_time, tzinfo=HKT)


def chips(items: list[tuple[str, str]]) -> str:
    return '<div class="cm-chips">' + "".join(
        f'<span class="cm-chip">{html.escape(k)} <b>{html.escape(v)}</b></span>' for k, v in items) + "</div>"


greeting = f"Hi {html.escape(first_name(PROFILE))}! " if first_name(PROFILE) else ""
st.html(f'''<div class="cm-hero"><img src="{state.logo}" width="48" height="48" alt=""><div><h1>CampusMail</h1>
<p>{greeting}Find the course emails that need you today, with the reason and the source for every decision.</p>
</div></div>''')

if state.messages is None:
    st.write("")
    steps = [
        (":material/inbox:", "Load emails", "Try the **sample inbox**, import a CSV, or connect Gmail or Outlook "
         "(read-only) in the sidebar."),
        (":material/school:", "Add your courses", "Course codes let CampusMail rank updates about *your* courses "
         "higher. The sample profile fills them in."),
        (":material/auto_awesome:", "Sort and summarize", "Every email gets a priority, a reason and quoted "
         "sources. Unclear ones go to **Needs review**."),
    ]
    for col, (icon, title, text) in zip(st.columns(3), steps):
        with col.container(border=True, height="stretch"):
            st.markdown(f"#### {icon} {title}")
            st.markdown(text)
    st.caption(":material/lock: With Local AI or Rules, nothing leaves this computer, and nothing is saved or logged. "
               + DISCLAIMER)
    st.stop()

engine_label = {ENGINE_AI: f"Local AI · {client.model}" if client else "Local AI",
                ENGINE_CLOUD: "Cloud AI", ENGINE_RULES: "Rules only"}[engine]
st.html(chips([
    ("Inbox", f"{len(state.messages)} messages · {state.source_name}"),
    ("Courses", ", ".join(courses) if courses else "none entered"),
    ("Reference time", f"{now:%a %d %b %Y %H:%M} HKT"),
    ("Engine", engine_label),
]))
if state.get("real_mail"):
    st.caption(":material/lock: These are real emails from your account. They are held in memory only; "
               "**Clear session** forgets them and the sign-in.")

if cloud_blocked:
    st.info(cloud_blocked, icon=":material/key:")
if st.button("Sort and summarize", type="primary", disabled=bool(cloud_blocked), icon=":material/auto_awesome:"):
    bar = st.progress(0.0, text="Starting…")

    def progress(i: int, total: int) -> None:
        bar.progress(i / total, text=f"Reading message {i + 1} of {total}…")

    state.run = pipeline.run(state.messages, courses, now, client, progress)
    state.corrections = {}
    bar.empty()

if state.run is None:
    st.caption(DISCLAIMER)
    st.stop()

# Re-apply the student's corrections on a copy, so changing one updates the digest immediately.
run: pipeline.Run = copy.deepcopy(state.run)
for result in run.results:
    fix = state.corrections.get(result.message.message_id)
    if fix:
        apply_correction(result, fix.get("priority"), fix.get("deadline"), now)

if run.notice:
    st.error(run.notice, icon=":material/warning:")
if run.mode == pipeline.MODE_RULES:
    st.warning("**Rules-only view.** Priorities come from keyword and date rules, and the "
               "“key sentences” are copied from each email. There are no AI summaries.", icon=":material/rule:")
else:
    st.success(f"Processed by {run.model_name} in {run.seconds:.1f} s.", icon=":material/check_circle:")

groups = run.by_priority()
for col, priority in zip(st.columns(4), Priority):
    slug, color, icon, meaning = BAND[priority]
    with col.container(border=True, key=f"band-{slug}"):
        st.metric(f":{color}[:material/{icon}:] {priority.value}", len(groups[priority]))
        st.caption(meaning)
st.caption(":material/info: " + DISCLAIMER)


def correction_form(result) -> None:
    mid = result.message.message_id
    with st.popover("Correct", icon=":material/edit:"), st.form(f"fix-{mid}", border=False):
        c1, c2, c3 = st.columns([2, 2, 1])
        options = [p.value for p in Priority]
        new_priority = c1.selectbox("Priority", options, index=options.index(result.priority.value), key=f"p-{mid}")
        default_dt = result.deadline or now
        c2a, c2b = c2.columns(2)
        new_date = c2a.date_input("Deadline date", value=default_dt.date(), key=f"d-{mid}")
        new_time = c2b.time_input("Time", value=default_dt.time(), key=f"t-{mid}", step=300)
        set_deadline = c3.checkbox("Set deadline", value=False, key=f"sd-{mid}")
        if st.form_submit_button("Apply correction"):
            fix = {"priority": Priority(new_priority)}
            if set_deadline:
                fix["deadline"] = datetime.combine(new_date, new_time, tzinfo=HKT)
            state.corrections[mid] = fix
            st.rerun()


def show_result(result) -> None:
    m, x = result.message, result.extraction
    slug, color, _, _ = BAND[result.priority]
    badges = [f":gray-badge[{md(m.message_id)}]"]
    if result.overdue:
        badges.append(":red-badge[:material/alarm: Overdue]")
    if result.corrected:
        badges.append(":blue-badge[:material/edit: Corrected by you]")
    with st.container(border=True, key=f"card-{slug}-{anchor(m.message_id)}"):
        st.markdown(f"**{md(m.subject or '(no subject)')}** &nbsp;" + " ".join(badges))
        for reason in result.reasons:
            st.markdown(f":{color}[**Why:**] {md(reason)}")
        for note in result.notes:
            st.warning(note, icon=":material/forum:")
        for note in result.assumptions:
            st.caption(f":material/help: Assumption: {note}")
        if x is not None and result.priority is not Priority.REVIEW:
            esc = html.escape
            parts = []
            facts = []
            if x.action_text:
                facts.append(f'<div><p class="cm-label">Action</p><p class="cm-value">{esc(x.action_text)}</p></div>')
            if result.deadline:
                facts.append(f'<div><p class="cm-label">Deadline</p><p class="cm-value"><b>'
                             f'{esc(format_dt(result.deadline, result.deadline_has_time))}</b> · '
                             f'{until(result.deadline, now)}</p></div>')
            if facts:
                parts.append(f'<div class="cm-facts">{"".join(facts)}</div>')
            if x.source == "model":
                parts.append(f'<p class="cm-label">Summary</p><p class="cm-value">{esc(x.summary)}</p>')
            else:
                parts.append('<p class="cm-label">Key sentences (copied by the rules, no AI summary)</p>')
            source = f'<a class="cm-src" href="#{anchor(m.message_id)}">{esc(m.message_id)}</a>'
            parts += [f'<blockquote class="cm-quote">“{esc(q)}” {source}</blockquote>' for q in x.quotes]
            st.html("".join(parts))
        else:
            st.html('<p class="cm-label">Original email (no summary is shown for messages that need review)</p>')
            body = m.body if len(m.body) <= 1200 else m.body[:1200] + " …"
            st.html(f'<div class="cm-original">{html.escape(body)}</div>')
            if len(m.body) > 1200:
                st.markdown(f"[Read the whole email](#{anchor(m.message_id)})")
        left, right, _ = st.columns([1, 1, 4])
        with left:
            correction_form(result)
        if m.message_id in state.corrections and right.button("Undo", key=f"undo-{m.message_id}",
                                                              icon=":material/undo:"):
            del state.corrections[m.message_id]
            st.rerun()


for priority in Priority:
    if not groups[priority]:
        continue
    slug, color, icon, meaning = BAND[priority]
    st.subheader(f":{color}[:material/{icon}:] {priority.value} :{color}-badge[{len(groups[priority])}]",
                 anchor=slug)
    if priority is Priority.LOW:
        with st.expander(f"Show {len(groups[priority])} low-priority messages"):
            for result in groups[priority]:
                show_result(result)
    else:
        for result in groups[priority]:
            show_result(result)

st.subheader(":material/download: Export", anchor="export")
left, right = st.columns(2)
left.download_button(
    "Digest (.txt)", render_text(run, now), file_name="campusmail_digest.txt", mime="text/plain",
    icon=":material/description:", width="stretch",
)
right.download_button(
    "Deadlines for your calendar (.ics)", render_ics(run, now), file_name="campusmail_deadlines.ics",
    mime="text/calendar", icon=":material/event:", width="stretch",
    help="High and Medium items with an upcoming, checked deadline. "
    "Items that need review are left out because their dates could not be verified.",
)

st.divider()
st.subheader(":material/mail: Original messages", anchor="originals")
for m in state.messages:
    st.html(f'<span id="{anchor(m.message_id)}"></span>')
    received = m.received.strftime("%a %d %b %Y %H:%M") if m.received else "unknown"
    thread = f" · thread {m.thread_id}" if m.thread_id and len(m.thread_id) <= 12 else ""
    with st.expander(f"**{md(m.message_id)}** · {md(m.subject or '(no subject)')} · {received}{md(thread)}"):
        if m.link:
            st.markdown(f"[Open in your mailbox]({m.link})")
        for note in m.notes:
            st.caption(note)
        st.text(m.body)
