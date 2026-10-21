"""Cloud engines and mailbox import, with the network replaced by fakes."""

import base64
import json

import pytest

from campusmail import llm, mailbox, pipeline
from campusmail.extraction import SCHEMA
from campusmail.models import Priority
from conftest import COURSES, NOW, make_message
from test_ai_path import LAB, answer


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status
        self.text = json.dumps(payload)

    def json(self):
        return self.payload


@pytest.fixture
def posted(monkeypatch):
    calls = []

    def install(payload, status=200):
        def fake_post(url, headers, json, timeout):
            calls.append({"url": url, "headers": headers, "json": json})
            return FakeResponse(payload, status)
        monkeypatch.setattr(llm.requests, "post", fake_post)
        return calls
    return install


# ---------------------------------------------------------------- cloud engines

def test_openai_compatible_schema_mode(posted):
    calls = posted({"choices": [{"message": {"content": json.dumps(answer())}}]})
    client = llm.cloud_client("OpenAI", "sk-test")
    run = pipeline.run([make_message(LAB)], COURSES, NOW, client)
    assert run.mode == pipeline.MODE_AI and run.results[0].priority is Priority.HIGH
    request = calls[0]
    assert request["url"] == "https://api.openai.com/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer sk-test"
    assert request["json"]["response_format"]["json_schema"]["schema"] == SCHEMA
    assert "temperature" not in request["json"]


def test_json_object_mode_puts_schema_in_prompt(posted):
    calls = posted({"choices": [{"message": {"content": json.dumps(answer())}}]})
    llm.cloud_client("DeepSeek", "key").complete("SYSTEM", "USER", SCHEMA)
    body = calls[0]["json"]
    assert body["response_format"] == {"type": "json_object"}
    assert "JSON schema" in body["messages"][0]["content"] and body["temperature"] == 0


def test_anthropic_structured_output(posted):
    calls = posted({"content": [{"type": "text", "text": json.dumps(answer())}], "stop_reason": "end_turn"})
    client = llm.cloud_client("Anthropic (Claude)", "key")
    run = pipeline.run([make_message(LAB)], COURSES, NOW, client)
    assert run.results[0].priority is Priority.HIGH
    request = calls[0]["json"]
    assert calls[0]["headers"]["x-api-key"] == "key"
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert request["output_config"]["format"]["schema"]["additionalProperties"] is False
    # Current Claude models reject forced tool calls and a non-default temperature.
    assert "tool_choice" not in request and "temperature" not in request
    assert request["max_tokens"] >= 16000


@pytest.mark.parametrize("provider,payload", [
    ("Anthropic (Claude)", {"content": [], "stop_reason": "refusal"}),
    ("OpenAI", {"choices": [{"message": {"content": None, "refusal": "no"}}]}),
])
def test_refusal_sends_one_message_to_review(posted, provider, payload):
    posted(payload)
    run = pipeline.run([make_message(LAB)], COURSES, NOW, llm.cloud_client(provider, "key"))
    assert run.mode == pipeline.MODE_AI and run.results[0].priority is Priority.REVIEW


def test_rejected_key_falls_back_to_rules_view(posted):
    posted({"error": "bad key"}, status=401)
    run = pipeline.run([make_message(LAB)], COURSES, NOW, llm.cloud_client("OpenAI", "wrong"))
    assert run.mode == pipeline.MODE_RULES and "rejected the API key" in run.notice
    assert "wrong" not in run.notice  # the key is never echoed


def test_missing_key_or_base_url_is_explained():
    with pytest.raises(llm.LLMUnavailable, match="No API key"):
        llm.cloud_client("OpenAI", "")
    with pytest.raises(llm.LLMUnavailable, match="base URL"):
        llm.cloud_client("Other OpenAI-compatible", "key", "some-model")


# ---------------------------------------------------------------- mailbox import

class FakeSession:
    def __init__(self, routes):
        self.routes, self.requests = routes, []

    def get(self, url, headers, timeout, params=None):
        self.requests.append((url, headers, params))
        for suffix, payload in self.routes.items():
            if url.endswith(suffix):
                return FakeResponse(payload) if not isinstance(payload, int) else FakeResponse({}, payload)
        raise AssertionError(f"unexpected URL {url}")


def test_outlook_fetch_converts_and_validates():
    session = FakeSession({"/me/mailFolders/inbox/messages": {"value": [
        {"id": "AAMk1", "receivedDateTime": "2026-09-30T01:00:00Z", "subject": "COMP3297 lab",
         "body": {"contentType": "text", "content": LAB + "\n\nOn Mon, 28 Sep 2026, Tutor wrote:\n> old text"},
         "conversationId": "c1", "webLink": "https://outlook.office.com/owa/?ItemID=AAMk1"},
        {"id": "AAMk2", "receivedDateTime": "2026-09-30T02:00:00Z", "subject": "Long",
         "body": {"contentType": "html", "content": "<p>" + "word " * 700 + "</p>"}},
    ]}})
    messages = mailbox.outlook_fetch("token", limit=30, days=7, session=session)
    first, second = messages
    assert first.message_id == "o01" and first.body == LAB and first.problems == []
    assert first.notes and first.link.startswith("https://outlook.office.com")
    assert first.received.utcoffset().total_seconds() == 8 * 3600
    assert any("limit" in p for p in second.problems)  # same 3,000-character rule as CSV
    url, headers, params = session.requests[0]
    assert headers["Authorization"] == "Bearer token"
    assert params["$top"] == "30" and "receivedDateTime ge" in params["$filter"]


def test_gmail_fetch_prefers_plain_text():
    encode = lambda s: base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")
    session = FakeSession({
        "/messages": {"messages": [{"id": "abc"}]},
        "/messages/abc": {"id": "abc", "threadId": "t", "internalDate": "1790730000000", "payload": {
            "mimeType": "multipart/alternative",
            "headers": [{"name": "Subject", "value": "COMP3297 lab"}],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": encode(LAB)}},
                {"mimeType": "text/html", "body": {"data": encode("<b>html version</b>")}},
            ]}},
    })
    [m] = mailbox.gmail_fetch("token", session=session)
    assert m.message_id == "g01" and m.subject == "COMP3297 lab" and m.body == LAB
    assert m.link.endswith("#all/abc")
    assert session.requests[0][2]["q"].startswith("in:inbox newer_than:")


def test_mail_errors_are_readable():
    session = FakeSession({"/me/mailFolders/inbox/messages": 403})
    with pytest.raises(mailbox.MailboxError, match="approve the app"):
        mailbox.outlook_fetch("token", session=session)
    with pytest.raises(mailbox.MailboxError, match="app ID"):
        mailbox.outlook_start_sign_in("")
    with pytest.raises(mailbox.MailboxError, match="not found"):
        mailbox.gmail_sign_in("does/not/exist.json")


def test_html_and_quote_cleanup():
    text = mailbox.html_to_text("<style>x{}</style><p>Submit by <b>1 October</b>.</p><p>Thanks &amp; bye</p>")
    assert "x{}" not in text and "Submit by 1 October." in text and "Thanks & bye" in text
    body, removed = mailbox.clean_body("New text.\n\nFrom: Tutor\nSent: Monday\nOld text")
    assert body == "New text." and removed
    assert mailbox.html_to_text("<p>a &amp;lt; b</p>").strip() == "a &lt; b"  # decoded once only


def test_inline_reply_is_kept_and_only_trailing_quote_removed():
    inline = "My answer:\n> Can we submit late?\nNo, the deadline is 1 October.\n"
    assert mailbox.clean_body(inline) == ("My answer:\n> Can we submit late?\nNo, the deadline is 1 October.", False)
    body, removed = mailbox.clean_body("Thanks, see you.\n\n> old line 1\n> old line 2\n")
    assert body == "Thanks, see you." and removed


def test_forwarded_email_is_kept_whole():
    text = "FYI\n\nFrom: Course Office\nSent: Monday\nSubmit the form by 1 October."
    msg = mailbox._message("o01", "2026-09-30T10:00:00Z", "FW: Form deadline", text, False, None, None)
    assert "Submit the form by 1 October." in msg.body and not msg.notes


def test_device_flow_wait_is_capped():
    class App:
        def acquire_token_by_device_flow(self, flow):
            self.flow = flow
            return {"access_token": "t"}
    app = App()
    import time
    assert mailbox.outlook_finish_sign_in(app, {"expires_at": time.time() + 900}) == "t"
    assert app.flow["expires_at"] <= time.time() + 91
