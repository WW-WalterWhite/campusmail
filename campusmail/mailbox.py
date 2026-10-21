"""Read-only import from a signed-in Outlook (Microsoft 365, including HKU mail) or Gmail account.

- Only read permissions are requested (Microsoft Graph `Mail.Read`, Gmail `gmail.readonly`),
  so CampusMail cannot send, delete or change mail even if it tried.
- Tokens and messages live in memory for the current session only; nothing is written to disk.
- Fetched messages go through the same checks as CSV rows (length, English, empty body).

Setup (an app registration with Microsoft and/or Google) is described in the README.
"""

from __future__ import annotations

import base64
import html
import os
import re
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
MS_CLIENT_ID = os.environ.get("CAMPUSMAIL_MS_CLIENT_ID", "")
# "organizations" = work/school accounts such as HKU; "common" also allows personal Outlook.com.
MS_AUTHORITY = "https://login.microsoftonline.com/" + os.environ.get("CAMPUSMAIL_MS_TENANT", "common")
GOOGLE_CLIENT_FILE = Path(os.environ.get("CAMPUSMAIL_GOOGLE_CLIENT_FILE", "secrets/google_client_secret.json"))
TIMEOUT = 30


class MailboxError(RuntimeError):
    """Sign-in or fetching failed; the message is safe to show to the user."""


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
    parser = _TextExtractor()
    parser.feed(markup)
    return html.unescape("".join(parser.parts))


# Start of an earlier message quoted below a reply.
QUOTE_START = re.compile(
    r"^(?:On .{5,120} wrote:\s*$|-{2,}\s*Original Message\s*-{2,}|From: .+\n(?:Sent|Date): .+)",
    re.M | re.I,
)


def clean_body(text: str) -> tuple[str, bool]:
    """Normalise whitespace and drop quoted earlier messages from a reply.

    Returns (body, quoted_history_removed). Only the earlier, quoted messages are removed; the
    new text of the email is kept whole, so the "never truncate" rule still holds for it.
    """
    text = text.replace("\r\n", "\n").replace("\xa0", " ")
    removed = False
    m = QUOTE_START.search(text)
    if m and m.start() > 0:
        text, removed = text[:m.start()], True
    lines = [line.rstrip() for line in text.split("\n")]
    if any(line.startswith(">") for line in lines):
        lines, removed = [line for line in lines if not line.startswith(">")], True
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return text, removed


def _message(short_id: str, received: str, subject: str, raw_body: str, is_html: bool,
             thread_id: str | None, link: str | None) -> Message:
    body, removed = clean_body(html_to_text(raw_body) if is_html else raw_body)
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

    client_id = client_id or MS_CLIENT_ID
    if not client_id:
        raise MailboxError("No Microsoft app ID. Set CAMPUSMAIL_MS_CLIENT_ID or enter it in the sidebar (see README).")
    app = msal.PublicClientApplication(client_id, authority=authority, token_cache=msal.TokenCache())
    flow = app.initiate_device_flow(scopes=MS_SCOPES)
    if "user_code" not in flow:
        raise MailboxError(f"Microsoft sign-in could not start: {flow.get('error_description', flow)}")
    return app, flow


def outlook_finish_sign_in(app, flow) -> str:
    """Wait until the user has entered the code in the browser; returns an access token."""
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise MailboxError(f"Microsoft sign-in failed: {result.get('error_description', result.get('error'))}")
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

def gmail_sign_in(client_file: Path = GOOGLE_CLIENT_FILE) -> str:
    """Opens Google's sign-in page in the browser and waits for consent; returns an access token."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not Path(client_file).exists():
        raise MailboxError(f"Google client file not found at {client_file}. See the README for how to create it.")
    flow = InstalledAppFlow.from_client_secrets_file(str(client_file), scopes=GMAIL_SCOPES)
    try:
        credentials = flow.run_local_server(port=0, open_browser=True, timeout_seconds=300)
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
    messages = []
    for i, ref in enumerate(listing.get("messages", [])[:limit], start=1):
        item = _get(session, f"{GMAIL}/messages/{ref['id']}", token, params={"format": "full"})
        payload = item.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
        received = datetime.fromtimestamp(int(item.get("internalDate", "0")) / 1000, timezone.utc).isoformat()
        raw, is_html = _gmail_body(payload)
        messages.append(_message(
            f"g{i:02d}", received, headers.get("subject", ""), raw, is_html,
            item.get("threadId"), f"https://mail.google.com/mail/u/0/#all/{ref['id']}",
        ))
    return messages
