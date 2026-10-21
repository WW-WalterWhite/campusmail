"""The model path, using a scripted client in place of Ollama."""

from campusmail import pipeline
from campusmail.extraction import SYSTEM_PROMPT
from campusmail.llm import LLMUnavailable, OllamaClient, ScriptedClient
from campusmail.models import Priority
from conftest import COURSES, NOW, make_message

LAB = "Please submit the COMP3297 lab report by 17:00 on 1 October."


def answer(**overrides):
    data = {
        "course": "COMP3297", "category": "assignment", "action_required": True,
        "action_text": "Submit the lab report", "deadline": "2026-10-01T17:00:00+08:00",
        "deadline_status": "explicit", "deadline_quote": "by 17:00 on 1 October",
        "summary": "The COMP3297 lab report is due at 17:00 on 1 October.", "quotes": [LAB],
    }
    data.update(overrides)
    return data


def run_one(body, *answers):
    client = ScriptedClient(list(answers))
    run = pipeline.run([make_message(body)], COURSES, NOW, client)
    return run, run.results[0], client


def test_supported_answer_is_ranked_by_policy():
    run, r, _ = run_one(LAB, answer())
    assert run.mode == pipeline.MODE_AI and run.notice is None
    assert r.priority is Priority.HIGH and r.extraction.summary.startswith("The COMP3297")


def test_email_is_wrapped_as_data():
    _, _, client = run_one(LAB, answer())
    system, user = client.calls[0]
    assert system == SYSTEM_PROMPT and "untrusted data" in system
    assert "<email>" in user and LAB in user


def test_one_repair_attempt_then_success():
    _, r, client = run_one(LAB, "not json at all", answer())
    assert len(client.calls) == 2 and "could not be used" in client.calls[1][1]
    assert r.priority is Priority.HIGH


def test_second_invalid_answer_stops_with_review_and_no_summary():
    _, r, client = run_one(LAB, "{}", '{"course": 1}')
    assert len(client.calls) == 2
    assert r.priority is Priority.REVIEW and r.extraction is None
    assert "invalid twice" in r.reasons[0]


def test_over_long_summary_is_invalid():
    _, r, _ = run_one(LAB, answer(summary="word " * 61), answer(summary="word " * 61))
    assert r.priority is Priority.REVIEW


def test_invented_quote_goes_to_review():
    _, r, _ = run_one(LAB, answer(quotes=["The lab report is worth 50% of the grade."]))
    assert r.priority is Priority.REVIEW and "not found" in r.reasons[0]


def test_invented_deadline_goes_to_review():
    _, r, _ = run_one("Please submit the lab report soon.", answer(
        deadline="2026-10-01T17:00:00+08:00", deadline_quote="by 17:00 on 1 October",
        quotes=["Please submit the lab report soon."]))
    assert r.priority is Priority.REVIEW and r.deadline is None


def test_deadline_not_matching_quote_goes_to_review():
    _, r, _ = run_one(LAB, answer(deadline="2026-10-03T17:00:00+08:00"))
    assert r.priority is Priority.REVIEW and "does not match" in r.reasons[0]


def test_unsupported_course_goes_to_review():
    _, r, _ = run_one(LAB, answer(course="ECON1210"))
    assert r.priority is Priority.REVIEW


def test_model_added_time_is_dropped_to_date_only():
    body = "Please submit the COMP3297 form by 1 October."
    _, r, _ = run_one(body, answer(quotes=[body], deadline="2026-10-01T23:59:00+08:00", deadline_quote="by 1 October",
                                    summary="Submit the COMP3297 form by 1 October."))
    assert r.priority is Priority.HIGH and not r.deadline_has_time and r.deadline.hour == 0


def test_model_unavailable_falls_back_to_labelled_rules_view():
    run, r, _ = run_one(LAB, LLMUnavailable("timed out"))
    assert run.mode == pipeline.MODE_RULES
    assert run.notice.startswith("AI unavailable")
    assert r.extraction.source == "rules" and r.priority is Priority.HIGH


def test_ollama_not_running_is_reported(monkeypatch):
    client = OllamaClient(host="http://127.0.0.1:9")  # nothing listens on port 9
    ready, status = client.status()
    assert not ready and "not running" in status
    run = pipeline.run([make_message(LAB)], COURSES, NOW, client)
    assert run.mode == pipeline.MODE_RULES and run.notice


def test_ollama_client_request_and_response_shape():
    """Runs OllamaClient against a tiny fake Ollama server to check the HTTP contract."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen = {}

    class FakeOllama(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, payload):
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._send({"models": [{"name": "qwen3:4b", "model": "qwen3:4b", "digest": "abc123def4567890"}]})

        def do_POST(self):
            seen["request"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self._send({"message": {"role": "assistant", "content": json.dumps(answer())}, "done": True})

    server = HTTPServer(("127.0.0.1", 0), FakeOllama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = OllamaClient(host=f"http://127.0.0.1:{server.server_port}")
        assert client.status() == (True, "qwen3:4b ready (digest abc123def456)")
        run = pipeline.run([make_message(LAB)], COURSES, NOW, client)
    finally:
        server.shutdown()
    request = seen["request"]
    assert request["model"] == "qwen3:4b" and request["stream"] is False
    assert request["format"]["type"] == "object" and request["options"]["temperature"] == 0
    assert run.mode == pipeline.MODE_AI and run.results[0].priority is Priority.HIGH


def test_summary_with_invented_date_or_number_goes_to_review():
    _, r, _ = run_one(LAB, answer(summary="The COMP3297 lab report is due at 17:00 on 2 October."))
    assert r.priority is Priority.REVIEW and "date not found" in r.reasons[0]
    _, r, _ = run_one(LAB, answer(summary="The lab report, worth 20% of the grade, is due 1 October."))
    assert r.priority is Priority.REVIEW and "'20%'" in r.reasons[0]
    _, r, _ = run_one(LAB, answer(summary="The lab report is due at 6pm on 1 October."))
    assert r.priority is Priority.REVIEW and "time" in r.reasons[0]


def test_summary_may_restate_time_in_another_format():
    _, r, _ = run_one(LAB, answer(summary="Submit the COMP3297 lab report by 5pm on 1 Oct."))
    assert r.priority is Priority.HIGH


def test_model_deadline_with_wrong_weekday_goes_to_review():
    body = "Please submit the COMP3297 lab report by 17:00 on Monday 1 October."  # 1 Oct 2026 is a Thursday
    _, r, _ = run_one(body, answer(quotes=[body], deadline_quote="by 17:00 on Monday 1 October"))
    assert r.priority is Priority.REVIEW and "weekday" in r.reasons[0]


def test_reasoning_trace_and_code_fence_are_ignored():
    import json as _json
    wrapped = "<think>The user wants JSON.</think>\n```json\n" + _json.dumps(answer()) + "\n```"
    _, r, client = run_one(LAB, wrapped)
    assert len(client.calls) == 1 and r.priority is Priority.HIGH


def test_quote_shortened_with_ellipsis_still_matches():
    _, r, _ = run_one(LAB, answer(quotes=["Please submit the COMP3297 lab report ... on 1 October."]))
    assert r.priority is Priority.HIGH
    _, r, _ = run_one(LAB, answer(quotes=["Please submit ... the exam paper"]))
    assert r.priority is Priority.REVIEW


class _Resp:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload
        self.text = str(payload)

    def json(self):
        return self._payload


def test_ollama_error_message_is_passed_on(monkeypatch):
    import campusmail.llm as llm_module
    monkeypatch.setattr(llm_module.requests, "post",
                        lambda *a, **k: _Resp(500, {"error": "model requires more system memory (5.1 GiB)"}))
    run = pipeline.run([make_message(LAB)], COURSES, NOW, OllamaClient())
    assert run.mode == pipeline.MODE_RULES and "more system memory" in run.notice


def test_old_ollama_is_reported(monkeypatch):
    import campusmail.llm as llm_module

    def fake_get(url, timeout):
        if url.endswith("/api/version"):
            return _Resp(200, {"version": "0.4.7"})
        return _Resp(200, {"models": [{"name": "qwen3:4b", "model": "qwen3:4b"}]})
    monkeypatch.setattr(llm_module.requests, "get", lambda url, timeout: _ok(fake_get(url, timeout)))
    ready, status = OllamaClient().status()
    assert not ready and "too old" in status


def _ok(resp):
    resp.raise_for_status = lambda: None
    return resp
