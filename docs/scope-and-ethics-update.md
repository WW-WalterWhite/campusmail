# Scope and ethics update: cloud models and mailbox import

Draft replacement text for the project outline and the final report, following the team's
decision on 21 October 2026 to add an optional cloud model and read-only Outlook/Gmail import.
Edit freely; the wording below describes what the code actually does.

## Scope decision (for the status sheet)

The mid-term version stays local-only and CSV-only. After the mid-term check, two optional
features are added: (1) cloud language models through an API key, as an alternative to the local
Qwen3 4B model, and (2) read-only import of recent inbox messages from Outlook / Microsoft 365 or
Gmail. The local model and CSV import remain the defaults, and the evaluation compares the
cloud and local models on the same locked test set. Live mailbox access was previously listed as
out of scope; it is now in scope as read-only import only. Sending, replying, deleting,
labelling, calendar changes and auto-replies remain out of scope.

## Replacement for outline §1 "Scope"

English email text for individual students, imported from a CSV file or read-only from the
student's own Outlook or Gmail inbox (up to 30 recent messages). Not an institutional mail
service, emergency alert system or staff correspondence manager.

## Replacement for outline §2 "Not needed" line

Not needed: model training, autonomous agent framework, vector database. Mailbox access is
read-only and limited to fetching recent inbox messages.

## Replacement for outline §5 "Ethics and risks"

CampusMail **does not** send, delete or modify emails, open attachments or links, make decisions
for students, or guarantee every urgent message is detected. Mailbox access uses read-only
permissions (`Mail.Read`, `gmail.readonly`), so these actions are impossible, not just avoided.

- **Privacy (local default):** with the local model, email text never leaves the student's
  computer. Development, evaluation and demos use synthetic data.
- **Privacy (cloud option):** with a cloud model, the subject and body of each email are sent to
  the chosen provider. The app shows which provider will receive the text and requires an explicit
  confirmation before each run. Team policy: cloud models are used only with synthetic or redacted
  email during development and evaluation, and students are told to check the provider's data
  retention terms before using it with real mail.
- **Privacy (mailbox import):** sign-in uses the provider's own OAuth page; CampusMail never sees
  the password. Access tokens and fetched messages are held in memory for the session only, are
  not written to disk or logged, and **Clear session** removes them. The only thing saved is
  the app's own registration (Google client file or Microsoft app ID) in a git-ignored folder,
  so sign-in is one click after a one-time setup. No inbox content is committed to the repository. Real-mail trials are voluntary and use the participant's own
  account on their own computer.
- **Institutional rules:** HKU's Microsoft 365 tenant may require IT approval before any app can
  read mail. The team will not try to bypass this; if consent is not granted, demos use personal
  test accounts with synthetic messages.
- **Cost and access:** the local model needs no paid account. Cloud models need an API key and
  cost money per use; they are optional so that no classmate has to pay to use CampusMail.
- **Wrong summaries / missed deadlines:** unchanged: source text always visible, priorities
  explained, uncertain cases exposed, corrections allowed, "Check the original email before
  acting." The cloud model's output goes through the same evidence checks as the local model.
- **Prompt injection:** email remains untrusted data, separated from instructions. Real mail makes
  this more likely, so injection-style text sends a message to review whichever model is used.
  No model has mail-write, browsing or shell tools.
- **Language:** English only; unsupported languages are flagged.
- **AI-use disclosure:** see `docs/AI_USE_LOG.md`.

## Replacement for outline §6 "Out of scope"

Out of scope: sending or replying to mail, auto-replies, deleting or labelling messages, calendar
changes, attachments, background syncing.

## Evaluation addition (outline §3)

Run the locked test set with the local model, a cloud model and the rules baseline, and report
for each: macro-F1, High recall, review recall, the safety gate (invented actions or deadlines)
and median time per message. Cloud runs use synthetic test messages only.
