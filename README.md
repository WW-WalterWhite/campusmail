# CampusMail

**Email priority sorter and AI summarizer for university students.** AILT9019 (AI Literacy II) team project, HKU, 2026–27 Semester 1.

Import a small batch of course emails, enter your course codes, and CampusMail gives you an
**explained priority list** (Needs review / High / Medium / Low) and a **digest** where every
summary is linked to exact quotations from the original email. Everything runs on your own
computer with a local Qwen3 4B model through [Ollama](https://ollama.com): no API key, no paid
account, no uploads.

> CampusMail never sends, deletes or changes emails, never opens links or attachments, and can
> miss or misread messages. **Check the original email before acting.**

## Quick start

### 1. Prerequisites (once)

- **Python 3.11 or newer** (3.12 or 3.13 recommended) from <https://www.python.org/downloads/>. On Windows, tick
  *"Add python.exe to PATH"* in the installer.
- **Ollama** from <https://ollama.com/download>. Install it and leave it running (on Windows and
  macOS it sits in the system tray / menu bar).

### 2. Setup (once)

- **Windows:** double-click `setup.bat`.
- **macOS / Linux:** run `./setup.sh` in a terminal.

The script creates a virtual environment in `.venv`, installs the pinned dependencies from
`requirements.txt` and runs `ollama pull qwen3:4b` (about 2.5 GB, first time only).

Manual equivalent:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
ollama pull qwen3:4b
```

### 3. Run

- **Windows:** double-click `run.bat`.
- **macOS / Linux:** `./run.sh`
- Or, with the virtual environment active: `streamlit run app.py`

Your browser opens at <http://localhost:8501>.

## Core path (what to do and what you should see)

1. Click **Load sample inbox** in the sidebar. This also fills in the sample course profile
   (`AILT9019, COMP3297, ECON1210, CCST9017`) and the reference time
   **Wed 21 Oct 2026 10:00 (UTC+8)**, so results are reproducible.
2. Under **Engine**, keep **Local AI (Ollama)**. A green box should say `qwen3:4b ready`.
   If it is yellow, follow its instruction (start Ollama, or `ollama pull qwen3:4b`).
3. Click **Sort and summarize**. A warm model takes a few seconds per message.
4. Check the result:
   - **Needs review** sits at the top. It should include `m03` ("submit … soon": vague timing,
     no invented date), `m08` (an email that tries to instruct the AI), `m11` (deadline in GMT),
     `m07` (conflicting dates) and `m13` (not English).
   - **High** should include `m01` (lab report due 17:00 on 22 Oct, within 48 hours), `m04`
     (ECON1210 tutorial moved to tomorrow) and `m09` (an overdue quiz, marked OVERDUE).
   - `m10` says "URGENT!!!" in the subject but is an optional fair, so it should be **Low**:
     the word "urgent" alone never decides priority.
   - Each item shows **Why** (the rule that placed it), the summary, and quotations linked to the
     original message at the bottom of the page.
5. Open any item and use **Apply correction** to change its priority or deadline; the list and
   the digest update immediately. **Export digest (.txt)** saves a plain-text digest.
6. **Clear session** forgets the inbox, results and corrections.

The expected labels for the sample inbox are in `data/sample_labels.csv`. With the rules
engine the sample matches them exactly (this is a smoke test, not an evaluation result: the
sample was written by the developers). Model results may differ; that is what the evaluation
script measures.

### Without Ollama

Choose **Rules only (no AI)** under Engine. If you pick Local AI and the model cannot be
reached or times out, CampusMail shows an explicit **"AI unavailable"** notice and switches to the
labelled rules-only view. That view uses keyword and date rules, copies key sentences from the
email instead of writing summaries, and never fabricates a summary.

## Importing your own emails

A UTF-8 CSV with up to **30 messages** and these columns:

| column | required | example |
|---|---|---|
| `message_id` | yes | `m01` |
| `received` | yes | `2026-10-21T08:15:00+08:00` (ISO 8601; without an offset it is read as Hong Kong time) |
| `subject` | yes | `COMP3297 Lab 4 report submission` |
| `body` | yes | plain text, up to 3,000 characters |
| `thread_id` | no | `t01` |

Messages that are too long, empty, badly dated, duplicated or not in English are shown as
**Needs review** with the reason and are never sent to the model or truncated. Please use
synthetic or redacted text only, and do not commit real inbox files (`*.inbox.csv` and
`private/` are git-ignored).

## How it works

```
Import → validate → extract with AI → check evidence → rank → summarize → review
```

| stage | file | what it does |
|---|---|---|
| Import & validate | `campusmail/importer.py` | CSV checks, 30-message and 3,000-character limits, English check |
| AI extraction | `campusmail/extraction.py`, `campusmail/llm.py` | Qwen3 4B via Ollama with a JSON schema (structured output), temperature 0, one repair attempt |
| Evidence checks | `campusmail/evidence.py` | quotes must appear in the email; the deadline must match a date inside its quote; the course must be written in the email; injection-style text is flagged |
| Priority policy | `campusmail/priority.py` | deterministic rules below; the model never sets priority |
| Rules baseline / fallback | `campusmail/rules.py`, `campusmail/dates.py` | keyword and date rules, used for the rules-only view and as the evaluation baseline |
| Digest | `campusmail/digest.py` | grouped plain-text export |
| UI | `app.py` | Streamlit interface |

The model only extracts and summarizes. The app controls every stage, and it has no tools for
sending, deleting, browsing or running commands. Email text is passed to the model as
delimited untrusted data.

**Priority policy** (times in UTC+8, reference time chosen in the sidebar):

- **Needs review** (always at the top): invalid input, vague or conflicting timing, a deadline in
  another time zone, a quote or deadline the code cannot find in the email, an unsupported
  course, injection-style text, or model output that is invalid twice.
- **High:** an explicit action due within 48 hours, an overdue action (marked OVERDUE), or a
  schedule change for one of your courses within 48 hours.
- **Medium:** any other explicit action, or an update for one of your courses.
- **Low:** general announcements with no required action.
- A date with no time is treated as 00:00 that day and labelled as an assumption. Within a band,
  nearer deadlines come first, then newer messages.

## Configuration

| environment variable | default | meaning |
|---|---|---|
| `CAMPUSMAIL_MODEL` | `qwen3:4b` | Ollama model tag (e.g. `qwen3:1.7b` on a slow laptop) |
| `OLLAMA_HOST` | `http://localhost:11434` | where Ollama listens |
| `CAMPUSMAIL_TIMEOUT` | `120` | seconds to wait for one model answer |

You can also type a different model name in the sidebar.

## Evaluation

```bash
python eval/evaluate.py                                   # rules baseline on the sample inbox
python eval/evaluate.py --set dev                         # the 40-message development set
python eval/evaluate.py --set dev --engine ollama --repeat 5 --out results/dev_qwen3
python eval/evaluate.py --inbox my.csv --labels my_labels.csv   # your own labelled set
```

It prints macro-F1 over messages labelled High/Medium/Low, how many High messages were predicted
High (a "Needs review" prediction counts as a miss), how many review cases were flagged,
deadline recovery with the **safety gate** (any invented or wrong deadline fails it), run and
per-message times, a confusion matrix and the mismatches. Labels CSV columns:
`message_id, expected_priority, expected_deadline` (the last is optional).

See [docs/EVALUATION.md](docs/EVALUATION.md) for the bundled datasets, how much their scores can
be trusted, and the results table to fill in.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The tests do not need Ollama: a scripted client stands in for the model. They cover date
parsing, CSV validation, the priority policy (including the outline's worked examples), the
repair attempt, evidence checks against invented quotes and deadlines, the AI-unavailable
fallback and the fail-safe cases (prompt injection, mail-action requests, ambiguous dates,
oversized and malformed input, model failure).

## Status and limitations

**Works now:** CSV import and validation, course profile, Ollama extraction with schema-constrained
output and one repair attempt, evidence checks, explained priority bands, review queue,
evidence-linked summaries, manual corrections, text digest export, rules-only fallback,
evaluation script and automated tests.

**Not yet / known limits:**

- The 40-message development set has draft labels that the team still has to check, and the
  80-message locked test set does not exist yet. No accuracy figures are claimed.
- Laptop feasibility (time per message, RAM) still has to be measured on team members' machines.
- English only. Messages in one thread are treated separately (no superseded-deadline detection).
- The date checker understands common English formats (`1 October`, `Oct 1`, `1/10`, `22.10.2026`, `2026-10-01`, `end of day`,
  `today`, `tomorrow`, weekday names). Other phrasings send the message to review rather than
  being guessed.
- The injection check is a phrase list. It catches common patterns, not all of them; it only
  ever moves a message to review.

## Repository layout

```
app.py                 Streamlit app
campusmail/            pipeline modules (see "How it works")
data/                  synthetic sample inbox, labels and course profile
eval/evaluate.py       evaluation script (docs/EVALUATION.md explains the datasets)
tests/                 pytest suite
docs/AI_USE_LOG.md     log of AI assistance used in development
setup.bat / run.bat    Windows setup and launcher (setup.sh / run.sh for macOS and Linux)
```
