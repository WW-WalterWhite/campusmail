# CampusMail

**Email priority sorter and AI summarizer for university students.** AILT9019 (AI Literacy II) team project, HKU, 2026–27 Semester 1.

Import a small batch of course emails, enter your course codes, and CampusMail gives you an
**explained priority list** (Needs review / High / Medium / Low) and a **digest** where every
summary is linked to exact quotations from the original email. By default everything runs on
your own computer with a local Qwen3 4B model through [Ollama](https://ollama.com): no API key,
no paid account, no uploads.

Optional extras: a **cloud model** (OpenAI, Claude, DeepSeek, Qwen cloud or any OpenAI-compatible
API) for stronger extraction, and **read-only import from Outlook / HKU mail or Gmail** instead of
a CSV file. Both are off unless you choose them; see [Optional: cloud models](#optional-cloud-models)
and [Optional: import from Outlook or Gmail](#optional-import-from-outlook-or-gmail).

> CampusMail never sends, deletes or changes emails, never opens links or attachments, and can
> miss or misread messages. **Check the original email before acting.**

## Quick start

### 1. Prerequisites (once)

- **Python 3.11 or newer** (3.12 or 3.13 recommended) from <https://www.python.org/downloads/>. On Windows, tick
  *"Add python.exe to PATH"* in the installer.
- **Ollama 0.9 or newer** from <https://ollama.com/download>. Install it and leave it running (on Windows and
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

What it looks like (sample inbox, rules-only view):

| Overview | A review item shows the original email | High items explain why |
|---|---|---|
| ![Overview](docs/screenshots/overview.png) | ![Review item](docs/screenshots/review_item.png) | ![High items](docs/screenshots/high_items.png) |

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

## Optional: cloud models

Choose **Cloud AI (API key)** under Engine, pick a provider and paste an API key (or set the
environment variable before starting the app). The key is kept in memory for the session only.

| provider | key variable | default model (editable) | structured output |
|---|---|---|---|
| OpenAI | `OPENAI_API_KEY` | `gpt-4.1-mini` | JSON schema |
| Anthropic (Claude) | `ANTHROPIC_API_KEY` | `claude-haiku-5-5` | forced tool call with the schema |
| DeepSeek | `DEEPSEEK_API_KEY` | `deepseek-chat` | JSON mode |
| Qwen (Alibaba Cloud Model Studio, international) | `DASHSCOPE_API_KEY` | `qwen-plus` | JSON mode |
| Other OpenAI-compatible | `CAMPUSMAIL_API_KEY` | you enter model and base URL | JSON mode |

Model names change often; if a provider rejects one, type a current name from its model list.

What stays the same: the cloud model only extracts and summarizes. Its answer goes through the
same validation, repair attempt, evidence checks and priority policy as the local model, and if
the provider fails (bad key, quota, timeout) you get the "AI unavailable" notice and the
rules-only view.

What changes: **the email subject and body are sent to the provider**, so the app asks you to
tick a confirmation box before every cloud run. Use synthetic or redacted emails for
development and evaluation, and check the provider's data-retention policy before sending real
mail. Each run of 30 messages costs roughly a few US cents with the small models above.

To evaluate a cloud model: `python eval/evaluate.py --engine cloud --provider "Anthropic (Claude)"`
(the key comes from the environment variable in the table).

## Optional: import from Outlook or Gmail

Open **Import from Outlook or Gmail** in the sidebar, sign in, and CampusMail fetches up to 30
recent inbox messages. Access is **read-only** (`Mail.Read` for Microsoft, `gmail.readonly` for
Google), so the app cannot send, delete or change mail. Tokens and messages stay in memory for
the session; **Clear session** forgets them. Long quoted reply chains below a reply are left
out (and labelled); everything else goes through the same checks as a CSV import.

Each team needs to register the app once with Microsoft and/or Google. It is free.

### Outlook / HKU mail (Microsoft 365)

1. Go to <https://entra.microsoft.com> → **App registrations** → **New registration**.
   Name: `CampusMail`. Supported account types: *Accounts in any organizational directory and
   personal Microsoft accounts*. Leave the redirect URI empty. Register.
2. In the new app: **Authentication** → *Advanced settings* → **Allow public client flows: Yes** → Save.
3. **API permissions** → Add a permission → Microsoft Graph → *Delegated* → `Mail.Read` → Add.
4. Copy the **Application (client) ID** from the Overview page. Either paste it into the sidebar,
   or set it before starting the app: `set CAMPUSMAIL_MS_CLIENT_ID=<id>` (Windows) /
   `export CAMPUSMAIL_MS_CLIENT_ID=<id>` (macOS/Linux).
5. In CampusMail press **Sign in with Microsoft**, open the link shown, enter the code, sign in,
   then press **I have signed in: fetch mail**.

**HKU accounts:** if sign-in says the app *needs admin approval*, the university only allows
approved apps to read mail. You can then use a personal Outlook.com account for the demo, or ask
ITS for consent. To limit sign-in to one organisation, set `CAMPUSMAIL_MS_TENANT` to its tenant
ID (default `common`).

### Gmail

1. Go to <https://console.cloud.google.com>, create a project, and enable the **Gmail API**
   (APIs & Services → Library).
2. **OAuth consent screen**: User type *External*, keep it in *Testing*, and add each team
   member's Gmail address under **Test users** (only test users can sign in).
3. **Credentials** → Create credentials → **OAuth client ID** → Application type *Desktop app*.
   Download the JSON file and save it as `secrets/google_client_secret.json` in the CampusMail
   folder (`secrets/` is git-ignored; never commit it). Another location can be set with
   `CAMPUSMAIL_GOOGLE_CLIENT_FILE`.
4. In CampusMail press **Sign in with Google**. A browser tab opens; Google warns that the app is
   unverified (expected for a testing app): choose *Continue*, allow read access, then return to
   CampusMail.

## How it works

```
Import → validate → extract with AI → check evidence → rank → summarize → review
```

| stage | file | what it does |
|---|---|---|
| Import & validate | `campusmail/importer.py` | CSV checks, 30-message and 3,000-character limits, English check |
| Mailbox import (optional) | `campusmail/mailbox.py` | read-only Outlook (Microsoft Graph) and Gmail fetch, HTML to text, quoted-reply removal |
| AI extraction | `campusmail/extraction.py`, `campusmail/llm.py` | Qwen3 4B via Ollama (or an optional cloud model) with a JSON schema, one repair attempt |
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
| `CAMPUSMAIL_TIMEOUT` | `120` | seconds to wait for one model answer (the first answer, which also loads the model, may take up to 300 s) |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY`, `CAMPUSMAIL_API_KEY` | none | cloud engine keys (optional) |
| `CAMPUSMAIL_MS_CLIENT_ID`, `CAMPUSMAIL_MS_TENANT` | none, `common` | Microsoft app registration for Outlook import |
| `CAMPUSMAIL_GOOGLE_CLIENT_FILE` | `secrets/google_client_secret.json` | Google OAuth client file for Gmail import |

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

The tests need no Ollama, API key or mail account: a scripted client, a fake Ollama server and
fake HTTP responses stand in for the model, the cloud APIs and the mail services. They cover date
parsing, CSV validation, the priority policy (including the outline's worked examples), the
repair attempt, evidence checks against invented quotes and deadlines, the AI-unavailable
fallback and the fail-safe cases (prompt injection, mail-action requests, ambiguous dates,
oversized and malformed input, model failure).

## Status and limitations

**Works now:** CSV import and validation, optional read-only Outlook/Gmail import, optional cloud
engines, course profile, Ollama extraction with schema-constrained
output and one repair attempt, evidence checks, explained priority bands, review queue,
evidence-linked summaries, manual corrections, text digest export, rules-only fallback,
evaluation script and automated tests.

**Not yet / known limits:**

- The 40-message development set has draft labels that the team still has to check, and the
  80-message locked test set does not exist yet. No accuracy figures are claimed.
- Laptop feasibility (time per message, RAM) still has to be measured on team members' machines.
- The cloud engines and mailbox import are tested against recorded API shapes, not live
  accounts; the first real sign-in and the first paid API call still need to be tried by the team.
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
