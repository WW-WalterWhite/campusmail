"""CampusMail Streamlit interface. Run with:  streamlit run app.py"""

from __future__ import annotations

import copy
import re
import json
from datetime import datetime
from pathlib import Path

import streamlit as st

from campusmail import pipeline
from campusmail.dates import HKT, format_dt
from campusmail.digest import DISCLAIMER, render_text
from campusmail.importer import CSVImportError, load_csv, parse_course_list, parse_received
from campusmail.llm import DEFAULT_MODEL, OllamaClient
from campusmail.models import Priority
from campusmail.priority import apply_correction

DATA = Path(__file__).parent / "data"
SAMPLE_INBOX = DATA / "sample_inbox.csv"
SAMPLE_PROFILE = json.loads((DATA / "sample_profile.json").read_text(encoding="utf-8"))
ENGINE_AI = "Local AI (Ollama)"
ENGINE_RULES = "Rules only (no AI)"
BADGE = {Priority.REVIEW: "🟣", Priority.HIGH: "🔴", Priority.MEDIUM: "🟠", Priority.LOW: "⚪"}

st.set_page_config(page_title="CampusMail", page_icon="📬", layout="wide")
state = st.session_state
state.setdefault("messages", None)
state.setdefault("source_name", None)
state.setdefault("last_upload_id", None)
state.setdefault("run", None)
state.setdefault("corrections", {})
state.setdefault("courses_text", "")
state.setdefault("ref_date", datetime.now(HKT).date())
state.setdefault("ref_time", datetime.now(HKT).time().replace(second=0, microsecond=0))


def anchor(message_id: str) -> str:
    return "msg-" + re.sub(r"[^a-z0-9]+", "-", message_id.lower())


def load_messages(data: bytes, name: str) -> None:
    try:
        state.messages = load_csv(data)
        state.source_name = name
    except CSVImportError as exc:
        state.messages = None
        st.sidebar.error(str(exc))
    state.run = None
    state.corrections = {}


def use_sample_profile() -> None:
    state.courses_text = ", ".join(SAMPLE_PROFILE["courses"])
    ref = parse_received(SAMPLE_PROFILE["reference_time"])
    state.ref_date, state.ref_time = ref.date(), ref.time()


def clear_session() -> None:
    for key in list(state.keys()):
        del state[key]


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("1. Inbox")
    if st.button("Load sample inbox", width="stretch"):
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

    st.header("2. Your courses")
    if st.button("Use sample course profile", width="stretch"):
        use_sample_profile()
    st.text_area("Course codes", key="courses_text", placeholder="e.g. COMP3297, AILT9019", height=80)
    st.caption("Reference time (Hong Kong time, UTC+8)")
    col_d, col_t = st.columns(2)
    col_d.date_input("Date", key="ref_date", label_visibility="collapsed")
    col_t.time_input("Time", key="ref_time", label_visibility="collapsed", step=300)

    st.header("3. Engine")
    engine = st.radio("Extraction engine", [ENGINE_AI, ENGINE_RULES], label_visibility="collapsed")
    client = None
    if engine == ENGINE_AI:
        model = st.text_input("Ollama model", value=DEFAULT_MODEL)
        client = OllamaClient(model=model)
        ready, status = client.status()
        (st.success if ready else st.warning)(status)

    st.divider()
    if st.button("Clear session", width="stretch", help="Forget the inbox, results and corrections."):
        clear_session()
        st.rerun()
    st.caption("Everything runs on this computer. Nothing is uploaded or logged.")

# ---------------------------------------------------------------- main
st.title("📬 CampusMail")
st.caption("Email priority sorter and AI summarizer for students. " + DISCLAIMER)

courses = parse_course_list(state.courses_text)
now = datetime.combine(state.ref_date, state.ref_time, tzinfo=HKT)

if state.messages is None:
    st.info("Start with **Load sample inbox** in the sidebar, or import your own CSV.")
    st.stop()

st.write(f"**{len(state.messages)} messages** from {state.source_name}. "
         f"Courses: {', '.join(courses) if courses else 'none entered'}. Reference time: {now:%a %d %b %Y %H:%M}.")

if st.button("Sort and summarize", type="primary"):
    bar = st.progress(0.0, text="Starting…")

    def progress(i: int, total: int) -> None:
        bar.progress(i / total, text=f"Reading message {i + 1} of {total}…")

    state.run = pipeline.run(state.messages, courses, now, client, progress)
    state.corrections = {}
    bar.empty()

if state.run is None:
    st.stop()

# Re-apply the student's corrections on a copy, so changing one updates the digest immediately.
run: pipeline.Run = copy.deepcopy(state.run)
for result in run.results:
    fix = state.corrections.get(result.message.message_id)
    if fix:
        apply_correction(result, fix.get("priority"), fix.get("deadline"), now)

if run.notice:
    st.error(run.notice, icon="⚠️")
if run.mode == pipeline.MODE_RULES:
    st.warning("**Rules-only view.** Priorities come from keyword and date rules, and the "
               "“key sentences” are copied from each email. There are no AI summaries.")
else:
    st.success(f"Processed by {run.model_name} in {run.seconds:.1f} s.")

groups = run.by_priority()
cols = st.columns(4)
for col, priority in zip(cols, Priority):
    col.metric(f"{BADGE[priority]} {priority.value}", len(groups[priority]))


def correction_form(result) -> None:
    mid = result.message.message_id
    with st.popover("Correct priority or deadline"), st.form(f"fix-{mid}", border=False):
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
    if mid in state.corrections and st.button("Undo correction", key=f"undo-{mid}"):
        del state.corrections[mid]
        st.rerun()


def show_result(result) -> None:
    m, x = result.message, result.extraction
    flags = (" · OVERDUE" if result.overdue else "") + (" · corrected" if result.corrected else "")
    title = f"{BADGE[result.priority]} [{m.message_id}] {m.subject or '(no subject)'}{flags}"
    with st.expander(title, expanded=result.priority in (Priority.REVIEW, Priority.HIGH)):
        for reason in result.reasons:
            st.markdown(f"**Why:** {reason}")
        for note in result.notes:
            st.warning(note, icon="🧵")
        for note in result.assumptions:
            st.caption(f"Assumption: {note}")
        if x is not None and result.priority is not Priority.REVIEW:
            if x.action_text:
                st.markdown(f"**Action:** {x.action_text}")
            if result.deadline:
                st.markdown(f"**Deadline:** {format_dt(result.deadline, result.deadline_has_time)}")
            if x.source == "model":
                st.markdown(f"**Summary:** {x.summary}")
            else:
                st.markdown("**Key sentences** (copied from the email by the rules, no AI summary):")
            for q in x.quotes:
                st.markdown(f"> “{q}”  \n> — [{m.message_id}](#{anchor(m.message_id)})")
        else:
            st.markdown("No summary is shown for messages that need review. The original email:")
            with st.container(border=True):
                st.text(m.body if len(m.body) <= 1200 else m.body[:1200] + " …")
            if len(m.body) > 1200:
                st.markdown(f"[Read the whole email](#{anchor(m.message_id)})")
        correction_form(result)


for priority in Priority:
    if groups[priority]:
        st.subheader(f"{BADGE[priority]} {priority.value}")
        for result in groups[priority]:
            show_result(result)

st.download_button(
    "Export digest (.txt)", render_text(run, now), file_name="campusmail_digest.txt", mime="text/plain",
)

st.divider()
st.subheader("Original messages", anchor="originals")
for m in state.messages:
    st.markdown(f"##### {m.message_id}: {m.subject or '(no subject)'}")
    st.html(f'<span id="{anchor(m.message_id)}"></span>')
    received = m.received.strftime("%a %d %b %Y %H:%M") if m.received else "unknown"
    with st.expander(f"Received {received}" + (f" · thread {m.thread_id}" if m.thread_id else ""), expanded=False):
        st.text(m.body)
