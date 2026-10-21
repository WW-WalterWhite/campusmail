# CampusMail Project Outline

**Email Priority Sorter and AI Summarizer** · AILT9019 project proposal (drafted with AI assistance, as disclosed in the proposal)

Source: `AILT9019 Project Proposal.pdf` (draft milestone, 30 September 2026).

## 1. Background

CampusMail is a local application that helps university students decide which course and campus emails need attention and what actions they require. A student imports a small email batch, selects current courses, and receives an **explained priority list** plus a **concise digest** linked to the original messages.

- **Users:** students handling assignment notices, timetable changes, group work and campus announcements.
- **Problem:** deadlines hide among routine updates; subject keywords cannot reliably separate an optional event from a required submission.
- **Hypothesis (to be tested, not assumed):** context-aware sorting and evidence-linked summaries reduce triage time without increasing missed urgent tasks.
- **Domain customisation:** user-entered course list, action deadlines and timetable changes.
- **Scope:** English email text for individual students. Not an institutional mail service, emergency alert system or staff correspondence manager.

## 2. Pipeline

**Import → validate → extract with AI → check evidence → rank → summarize → review**

Built as a Python app with a Streamlit interface, a local language-model adapter, a deterministic priority policy and an evaluation script. It is a bounded AI workflow: the app controls each stage; the model only extracts and summarizes, never chooses tools or takes external actions.

1. **Request and input.** CSV of up to 30 messages (message ID, received time, subject, plain-text body; optional thread ID), course codes and a reference time. A synthetic sample inbox ships with the app. Messages over 3,000 characters or invalid ones are shown as "Needs review", never silently truncated.
2. **AI extraction.** Local **Qwen3 4B via Ollama** with schema-constrained output. Fields: course, category, action required, action text, explicit deadline, summary (≤ 60 words), exact supporting quotations. Missing info must be null. Model digest, prompt and dependencies are pinned after a laptop feasibility test.
3. **Evidence checks.** Code verifies quotes appear in the source and that deadline and course fields are supported. Every summary sentence carries a message ID and quote. Ambiguous dates, conflicts, unsupported claims or malformed output go to "Needs review". One repair attempt; a second failure stops generation for that message.
4. **Priority policy** (times in UTC+8):
   - **High:** explicit action due within 48 h, or an enrolled-course schedule change within 48 h. Overdue unresolved actions are High and marked overdue.
   - **Medium:** another explicit action, or an enrolled-course update.
   - **Low:** general announcement, no required action.
   - Unknown time zones or unclear dates go to review; a date with no time is treated as the start of that day and labelled as an assumption. Within a band, nearer deadlines first, then newer messages. "Needs review" always sits above the ranked list.
5. **Digest and control.** Summaries grouped by High / Medium / Low with action, deadline, reason and source link. Users can correct priority or deadline and the digest updates. Messages in one thread stay separate in the MVP. Export is a local text digest only.

**Example** (10:00, 30 Sep): "Submit the lab report by 17:00 on 1 October" → High. "Optional seminar next month" → Low. "Please submit soon" → Needs review (no invented date).

Not needed: model training, live mailbox connection, autonomous agent framework, vector database.

## 3. Evaluation and testing

All figures are proposed acceptance targets, not results.

- **Dataset:** 120 synthetic English messages. 40 development; 80 locked test (20 each of High, Medium, Low, Needs review), including near-duplicates, conflicting dates and missing context. Two members label independently and resolve disagreements; the test set is frozen before prompt tuning.
- **Priority quality:** macro-F1 ≥ 0.80 on the 60 High/Medium/Low test messages; ≥ 18/20 High predicted High ("Needs review" counts as an error here); ≥ 18/20 review cases flagged.
- **Summary and extraction:** ≥ 95% of factual claims supported; ≥ 90% of actions and explicit deadlines recovered; any invented action or deadline fails the safety gate; all source links open the correct message.
- **Usefulness:** compare against a keyword/date-rule baseline. Exploratory study with six volunteers, two matched 12-message tasks, counterbalanced: target ≥ 25% lower median triage time with no more missed High messages.
- **Reliability:** warm-model 10-message run within 2 minutes (median and slowest over five runs, RAM, model version). Four of five first-time classmates reach a live result within 10 minutes after prerequisites install.
- **Fail-safe tests (12 cases):** 3 prompt-injection / exfiltration, 3 ambiguous or conflicting deadlines, 2 oversized/malformed inputs, 2 model timeout / invalid output, 2 requests to send or delete email. All must preserve sources, take no external action and show review or refusal. On model failure: explicit "AI unavailable" notice and a labelled rules-only view, no fabricated summary.

## 4. Distribution and accessibility

- GitHub release and project webpage with screenshots, sample data and illustrated setup.
- Windows laptops first. Setup script installs pinned Python dependencies; a launcher opens the browser UI; no code editing needed.
- Local Ollama: no API key or paid service. Qwen3 4B is about a 2.5 GB download; fall back to a smaller model if the feasibility spike requires it.
- **First success:** launch → "Load sample inbox" → select supplied course profile → "Sort and summarize" → see a High deadline and a Needs review message with sources.
- Text labels, keyboard controls and expandable originals for accessibility.

## 5. Ethics and risks

CampusMail **does not** send, delete or modify emails, open attachments or links, make decisions for students, or guarantee every urgent message is detected.

- **Privacy:** synthetic data for development, evaluation and demos; optional personal trials only with redacted, voluntarily supplied text. Local processing, no uploads, no body logs, no committed inbox files; clear-session button.
- **Wrong summaries / missed deadlines:** source text always visible, priorities explained, uncertain cases exposed, corrections allowed, "Check the original email before acting." The word "urgent" or sender prestige alone must not decide priority.
- **Prompt injection:** email is untrusted data, separated from instructions; no mail-write, browsing or shell tools.
- **Language:** English only; unsupported languages are flagged.
- **AI-use disclosure:** proposal drafted with AI assistance; development will log assistant/model use, prompts, accepted changes, human review and testing.

## 6. Checkpoints

**Must-have**

- **M1** A classmate can launch the app and process the included inbox with a real local AI run, no paid account.
- **M2** CSV validation, course profile, explained priority bands, evidence-linked summaries, review queue and manual corrections work end to end.
- **M3** Locked evaluation meets the priority, summary and safety gates, with raw results and limitations published.
- **M4** Fresh-machine walkthrough verifies setup; all course deliverables ready by the final milestone.

**Should-have (extensions only):** thread-level summaries that detect superseded deadlines, bilingual English/Chinese input with separate evaluation, saved local preference profiles. Out of scope: live Gmail/Outlook access, auto-replies, calendar changes.

**Timeline**

| When | Work |
|---|---|
| Weeks 2–3 | Define task and priority rules, draft synthetic examples, test local-model feasibility |
| 30 Sep (W4) | Proposal draft |
| Weeks 4–6 | Mandatory consultation; peer feedback; revised proposal by 10 Oct |
| Weeks 5–7 | Import, extraction, validators, ranking, summaries, source links; 40-message dev set; freeze 80-message test set. End of W6: shrink model or batch if the laptop spike fails |
| 26 Oct (mid-term) | End-to-end live run, a failure case, preliminary dev-set metrics, short issue list |
| Weeks 8–10 | Locked evaluation, usability study, defect fixes, install testing; Friday standups on Ed (W5–10) |
| By 20 Nov (W11–12) | Code and reproducible setup, project webpage, ≤ 3-minute presentation + demo, ≤ 5-page report with Ethics & AI-use disclosure |
| Week 13 | Gallery peer review, People's Choice, closing |

**Roles:** interface/import, AI workflow, evaluation/documentation; a fourth member (if any) leads integration and accessibility. Everyone reviews another component and commits their own work.
