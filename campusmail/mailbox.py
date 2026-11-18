"""Read-only import from a signed-in Outlook (Microsoft 365, including HKU mail) or Gmail account.

- Only read permissions are requested (Microsoft Graph `Mail.Read`, Gmail `gmail.readonly`),
  so CampusMail cannot send, delete or change mail even if it tried.
- Tokens and messages live in memory for the current session only and are never written to disk.
  The only thing saved is the app's own registration (the Google client file or the Microsoft
  app ID), so that sign-in is a single click after the one-time setup.
- Fetched messages go through the same checks as CSV rows (length, English, empty body).

Where the registration is looked up, first match wins:
1. environment variables (CAMPUSMAIL_GOOGLE_CLIENT_FILE, CAMPUSMAIL_MS_CLIENT_ID);
2. this computer's `secrets/` folder, written by the in-app setup (git-ignored);
3. `campusmail/sign_in/`, the registration built into this copy of the app. When the developer
   puts it there, users only press "Sign in" and approve access in a browser pop-up.
Registering the app with Google or Microsoft is described in the README.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import requests

from .importer import MAX_MESSAGES, content_problems, parse_received
from .models import Message

GRAPH = "https://graph.microsoft.com/v1.0"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
MS_SCOPES = ["Mail.Read"]
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
# "organizations" = work/school accounts such as HKU; "common" also allows personal Outlook.com.
MS_AUTHORITY = "https://login.microsoftonline.com/" + os.environ.get("CAMPUSMAIL_MS_TENANT", "common")
ROOT = Path(__file__).resolve().parent.parent
LOCAL_DIR = ROOT / "secrets"
BUILTIN_DIR = ROOT / "campusmail" / "sign_in"
GOOGLE_FILE_NAME = "google_client.json"
MS_FILE_NAME = "microsoft_client_id.txt"
GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
TIMEOUT = 30


# University tenants such as HKU usually only let IT-approved apps read mail; the browser then says
# "Need admin approval" or "You don't have access", and the app only sees a declined or expired code.
ORG_BLOCK_HINT = ("If the browser said you need admin approval or don't have access, your university only "
                  "allows approved apps to read its mail. Use Gmail or a personal Outlook.com account instead "
                  "(see README), or ask IT to approve the app.")


class MailboxError(RuntimeError):
    """Sign-in or fetching failed; the message is safe to show to the user."""


# ---------------------------------------------------------------- one-time app setup

def google_client_file() -> tuple[Path, str] | None:
    """The Google client file to use and where it came from ("environment", "this computer", "built in")."""
    env = os.environ.get("CAMPUSMAIL_GOOGLE_CLIENT_FILE")
    candidates = ([(Path(env), "environment")] if env else []) + [
        (LOCAL_DIR / GOOGLE_FILE_NAME, "this computer"),
        (LOCAL_DIR / "google_client_secret.json", "this computer"),  # the name earlier README steps used
        (BUILTIN_DIR / GOOGLE_FILE_NAME, "built in"),
    ]
    return next(((path, where) for path, where in candidates if path.is_file()), None)


def parse_google_client(data: bytes | str) -> dict:
    """Check that `data` is the JSON Google gives for a *Desktop app* OAuth client."""
    try:
        info = json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        raise MailboxError("That file is not the JSON file Google lets you download for an OAuth client.") from exc
    if not isinstance(info, dict):
        raise MailboxError("That file is not a Google OAuth client file.")
    if "web" in info:
        raise MailboxError("This client is of type 'Web application'. In Google Cloud, create an OAuth client "
                           "of type 'Desktop app' and use its file instead.")
    installed = info.get("installed")
    if not isinstance(installed, dict) or not installed.get("client_id") or not installed.get("client_secret"):
        raise MailboxError("That file has no Desktop app client in it. Download the JSON of a 'Desktop app' "
                           "OAuth client from Google Cloud.")
    installed.setdefault("auth_uri", "https://accounts.google.com/o/oauth2/auth")
    installed.setdefault("token_uri", "https://oauth2.googleapis.com/token")
    return info


def save_google_client(data: bytes | str, built_in: bool = False) -> str:
    """Validate and save the client file, on this computer only or built into this copy of the app.
    Returns the client ID."""
    info = parse_google_client(data)
    folder = BUILTIN_DIR if built_in else LOCAL_DIR
    folder.mkdir(exist_ok=True)
    (folder / GOOGLE_FILE_NAME).write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info["installed"]["client_id"]


def google_client_id(path: Path) -> str:
    try:
        return parse_google_client(path.read_bytes())["installed"]["client_id"]
    except (OSError, MailboxError):
        return ""


def forget_google_client() -> None:
    """Remove this computer's saved client files (the built-in registration is left alone)."""
    for name in (GOOGLE_FILE_NAME, "google_client_secret.json"):
        (LOCAL_DIR / name).unlink(missing_ok=True)


def ms_client_id() -> tuple[str, str]:
    """The Microsoft app ID and where it came from, or ("", "")."""
    if os.environ.get("CAMPUSMAIL_MS_CLIENT_ID"):
        return os.environ["CAMPUSMAIL_MS_CLIENT_ID"].strip(), "environment"
    for path, where in ((LOCAL_DIR / MS_FILE_NAME, "this computer"), (BUILTIN_DIR / MS_FILE_NAME, "built in")):
        if path.is_file():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value, where
    return "", ""


def forget_ms_client_id() -> None:
    (LOCAL_DIR / MS_FILE_NAME).unlink(missing_ok=True)


def save_ms_client_id(value: str, built_in: bool = False) -> str:
    value = value.strip()
    if not GUID.match(value):
        raise MailboxError("That is not a Microsoft app ID. Copy the 'Application (client) ID' from the app's "
                           "Overview page; it looks like 1a2b3c4d-1234-5678-9abc-1234567890ab.")
    folder = BUILTIN_DIR if built_in else LOCAL_DIR
    folder.mkdir(exist_ok=True)
    (folder / MS_FILE_NAME).write_text(value + "\n", encoding="utf-8")
    return value


# ---------------------------------------------------------------- text cleanup

class _TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "table"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head") and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    # HTMLParser already decodes entities (convert_charrefs); decoding again would turn a
    # literal "&amp;lt;" in the email into "<".
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    return "".join(parser.parts)


# Start of an earlier message quoted below a reply.
QUOTE_START = re.compile(
    r"^(?:On .{5,120} wrote:\s*$|-{2,}\s*Original Message\s*-{2,}|From: .+\n(?:Sent|Date): .+)",
    re.M | re.I,
)


FORWARD_SUBJECT = re.compile(r"^\s*(?:fw|fwd)\s*:", re.I)


def clean_body(text: str, forwarded: bool = False) -> tuple[str, bool]:
    """Normalise whitespace and drop quoted earlier messages from a reply.

    Returns (body, quoted_history_removed). Only the earlier, quoted messages are removed; the
    new text of the email is kept whole, so the "never truncate" rule still holds for it.
    A forwarded email is kept whole: the forwarded part is usually the announcement itself.
    """
    text = text.replace("\r\n", "\n").replace("\xa0", " ")
    removed = False
    m = None if forwarded else QUOTE_START.search(text)
    if m and m.start() > 0:
        text, removed = text[:m.start()], True
    lines = [line.rstrip() for line in text.split("\n")]
    if not forwarded:
        # Only a quoted block at the very end is history. ">" lines between new paragraphs are an
        # inline reply and are kept, so the answer still makes sense.
        end = len(lines)
        while end and (lines[end - 1].startswith(">") or not lines[end - 1].strip()):
            end -= 1
        if any(line.startswith(">") for line in lines[end:]) and end:
            lines, removed = lines[:end], True
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return text, removed


def _message(short_id: str, received: str, subject: str, raw_body: str, is_html: bool,
             thread_id: str | None, link: str | None) -> Message:
    body, removed = clean_body(html_to_text(raw_body) if is_html else raw_body,
                               forwarded=bool(FORWARD_SUBJECT.match(subject)))
    problems = content_problems(subject, body)
    try:
        when = parse_received(received)
    except ValueError:
        when = None
        problems.append("The mailbox did not give a usable received time.")
    message = Message(short_id, when, subject.strip(), body, thread_id, problems, link=link)
    if removed:
        message.notes.append("Quoted earlier messages below the reply were left out.")
    return message


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _get(session, url: str, token: str, **kwargs) -> dict:
    try:
        response = session.get(url, headers={"Authorization": f"Bearer {token}", **kwargs.pop("headers", {})},
                               timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise MailboxError(f"Could not reach the mail service: {exc}") from exc
    if response.status_code == 401:
        raise MailboxError("The sign-in has expired. Sign in again.")
    if response.status_code == 403:
        raise MailboxError("The account did not grant read access to mail (HTTP 403). "
                           "Your organisation may need to approve the app.")
    if response.status_code >= 400:
        raise MailboxError(f"The mail service returned HTTP {response.status_code}.")
    return response.json()


# ---------------------------------------------------------------- Outlook / Microsoft 365

def outlook_start_sign_in(client_id: str = "", authority: str = MS_AUTHORITY):
    """Begin the device-code sign-in. Returns (msal app, flow); show flow["message"] to the user."""
    import msal  # imported here so the rest of the app works without the package

    client_id = (client_id or ms_client_id()[0]).strip()
    if not client_id:
        raise MailboxError("Outlook sign-in is not set up in this copy of CampusMail yet (see Settings).")
    if not GUID.match(client_id):
        raise MailboxError("That is not a Microsoft app ID. Copy the 'Application (client) ID' from the app's "
                           "Overview page.")
    app = msal.PublicClientApplication(client_id, authority=authority, token_cache=msal.TokenCache())
    flow = app.initiate_device_flow(scopes=MS_SCOPES)
    if "user_code" not in flow:
        raise MailboxError(f"Microsoft sign-in could not start: {flow.get('error_description', flow)}")
    return app, flow


def outlook_sign_in_popup(client_id: str = "", authority: str = MS_AUTHORITY, timeout: int = 180,
                          login_hint: str = "") -> str:
    """Open Microsoft's sign-in page in the browser and wait for the user to approve; returns a token.

    Uses the authorization-code flow with PKCE and a http://localhost redirect, which the app
    registration must list under "Mobile and desktop applications" (see README).
    """
    import msal

    client_id = (client_id or ms_client_id()[0]).strip()
    if not client_id:
        raise MailboxError("Outlook sign-in is not set up in this copy of CampusMail yet (see Settings).")
    app = msal.PublicClientApplication(client_id, authority=authority, token_cache=msal.TokenCache())
    try:
        result = app.acquire_token_interactive(MS_SCOPES, prompt="select_account", timeout=timeout,
                                               login_hint=login_hint or None)
    except Exception as exc:  # no browser, port in use, closed window
        raise MailboxError(f"The Microsoft sign-in window did not finish: {exc}. Try 'Use a code instead'.") from exc
    if "access_token" not in result:
        raise MailboxError(f"Microsoft sign-in failed: {result.get('error_description', result.get('error'))} "
                           + ORG_BLOCK_HINT)
    return result["access_token"]


def outlook_finish_sign_in(app, flow) -> str:
    """Wait until the user has entered the code in the browser; returns an access token.

    Called after the user says they entered the code, so wait at most 90 seconds instead of the
    code's full 15-minute life, which would freeze the page.
    """
    flow["expires_at"] = min(flow.get("expires_at", float("inf")), time.time() + 90)
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise MailboxError(f"Microsoft sign-in failed: {result.get('error_description', result.get('error'))} "
                           + ORG_BLOCK_HINT)
    return result["access_token"]


def outlook_fetch(token: str, limit: int = MAX_MESSAGES, days: int = 14, session=None) -> list[Message]:
    session = session or requests.Session()
    params = {
        "$top": str(min(limit, MAX_MESSAGES)),
        "$select": "id,receivedDateTime,subject,body,conversationId,webLink",
        "$orderby": "receivedDateTime desc",
        "$filter": f"receivedDateTime ge {_since(days).strftime('%Y-%m-%dT%H:%M:%SZ')}",
    }
    data = _get(session, f"{GRAPH}/me/mailFolders/inbox/messages", token, params=params,
                headers={"Prefer": 'outlook.body-content-type="text"'})
    messages = []
    for i, item in enumerate(data.get("value", [])[:limit], start=1):
        body = item.get("body") or {}
        messages.append(_message(
            f"o{i:02d}", item.get("receivedDateTime", ""), item.get("subject") or "",
            body.get("content") or "", (body.get("contentType") or "").lower() == "html",
            item.get("conversationId"), item.get("webLink"),
        ))
    return messages


# ---------------------------------------------------------------- Gmail

def gmail_sign_in(client_file: Path | str | None = None, login_hint: str = "") -> str:
    """Opens Google's sign-in page in the browser and waits for consent; returns an access token."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if client_file is None:
        found = google_client_file()
        if found is None:
            raise MailboxError("Gmail sign-in is not set up in this copy of CampusMail yet (see Settings).")
        client_file = found[0]
    if not Path(client_file).exists():
        raise MailboxError(f"Google client file not found at {client_file}. See the README for how to create it.")
    flow = InstalledAppFlow.from_client_secrets_file(str(client_file), scopes=GMAIL_SCOPES)
    try:
        extra = {"login_hint": login_hint} if login_hint else {}
        credentials = flow.run_local_server(port=0, open_browser=True, timeout_seconds=300, **extra)
    except Exception as exc:  # the library raises several types for cancelled or timed-out sign-ins
        raise MailboxError(f"Google sign-in did not finish: {exc}") from exc
    return credentials.token


def _gmail_body(payload: dict) -> tuple[str, bool]:
    """Prefer the text/plain part; fall back to text/html. Returns (raw text, is_html)."""
    plain, rich = [], []

    def walk(part):
        mime = part.get("mimeType", "")
        data = (part.get("body") or {}).get("data")
        if data and mime in ("text/plain", "text/html") and not part.get("filename"):
            text = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
            (plain if mime == "text/plain" else rich).append(text)
        for child in part.get("parts", []) or []:
            walk(child)

    walk(payload)
    if plain:
        return "\n".join(plain), False
    return "\n".join(rich), True


def gmail_fetch(token: str, limit: int = MAX_MESSAGES, days: int = 14, session=None) -> list[Message]:
    session = session or requests.Session()
    listing = _get(session, f"{GMAIL}/messages", token,
                   params={"maxResults": str(min(limit, MAX_MESSAGES)), "q": f"in:inbox newer_than:{days}d"})
    refs = listing.get("messages", [])[:limit]

    def fetch_one(ref: dict) -> dict:
        return _get(session, f"{GMAIL}/messages/{ref['id']}", token, params={"format": "full"})

    # One request per message; a few at a time cuts a 30-message import from ~15 s to a few seconds.
    with ThreadPoolExecutor(max_workers=6) as pool:
        items = list(pool.map(fetch_one, refs))
    messages = []
    for i, (ref, item) in enumerate(zip(refs, items), start=1):
        payload = item.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
        received = datetime.fromtimestamp(int(item.get("internalDate", "0")) / 1000, timezone.utc).isoformat()
        raw, is_html = _gmail_body(payload)
        messages.append(_message(
            f"g{i:02d}", received, headers.get("subject", ""), raw, is_html,
            item.get("threadId"), f"https://mail.google.com/mail/u/0/#all/{ref['id']}",
        ))
    return messages
