"""Language-model adapters.

The pipeline only talks to the small `LLMClient` interface, so the app and the tests run
without Ollama. `OllamaClient` is the real local model; anything else (e.g. a fake in the
tests) only needs a `name` and a `complete()` method.
"""

from __future__ import annotations

import json
import os
from typing import Protocol

import requests

DEFAULT_MODEL = os.environ.get("CAMPUSMAIL_MODEL", "qwen3:4b")
DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_TIMEOUT = float(os.environ.get("CAMPUSMAIL_TIMEOUT", "120"))
FIRST_CALL_TIMEOUT = 300.0
# "think" (Qwen3 without reasoning) needs Ollama 0.9; JSON-schema "format" needs 0.5.
MIN_OLLAMA = (0, 9, 0)


class LLMUnavailable(RuntimeError):
    """The model could not be reached or did not answer in time."""


class LLMClient(Protocol):
    name: str

    def complete(self, system: str, user: str, schema: dict) -> str:
        """Return the model's raw text answer, which should be JSON matching schema."""
        ...


class OllamaClient:
    def __init__(self, model: str = DEFAULT_MODEL, host: str = DEFAULT_HOST, timeout: float = DEFAULT_TIMEOUT):
        self.model = model
        self.host = host.rstrip("/")
        if not self.host.startswith("http"):
            self.host = "http://" + self.host
        self.timeout = timeout
        self.name = f"Ollama {model}"
        self._loaded = False  # the first request also loads the model into memory, which is slow

    def version(self) -> tuple[int, ...] | None:
        try:
            raw = requests.get(f"{self.host}/api/version", timeout=3).json().get("version", "")
            return tuple(int(p) for p in raw.split("-")[0].split(".")[:3])
        except (requests.RequestException, ValueError, AttributeError):
            return None

    def status(self) -> tuple[bool, str]:
        """(ready, explanation). Ready means Ollama answers and the model is pulled."""
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=3)
            response.raise_for_status()
        except requests.RequestException:
            return False, f"Ollama is not running at {self.host}. Start the Ollama app, then reload."
        models = response.json().get("models", [])
        names = {m.get("name") for m in models} | {m.get("model") for m in models}
        wanted = {self.model, f"{self.model}:latest"}
        if not names & wanted:
            return False, f"Model {self.model} is not installed. Run: ollama pull {self.model}"
        version = self.version()
        if version is not None and version < MIN_OLLAMA:
            return False, (f"Ollama {'.'.join(map(str, version))} is too old for structured output. "
                           f"Update it from https://ollama.com/download (0.9 or newer).")
        digest = next((m.get("digest", "")[:12] for m in models if m.get("name") in wanted), "")
        return True, f"{self.model} ready" + (f" (digest {digest})" if digest else "")

    def complete(self, system: str, user: str, schema: dict) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema,  # Ollama structured outputs: decoding is constrained to this JSON schema
            "stream": False,
            "think": False,  # Qwen3: skip the reasoning trace, we only want the JSON
            "options": {"temperature": 0, "seed": 9019},
            "keep_alive": "15m",  # keep the model loaded between runs
        }
        timeout = self.timeout if self._loaded else max(self.timeout, FIRST_CALL_TIMEOUT)
        try:
            response = requests.post(f"{self.host}/api/chat", json=payload, timeout=timeout)
        except requests.Timeout as exc:
            hint = "" if self._loaded else " Loading the model the first time can be slow; try again."
            raise LLMUnavailable(f"The model did not answer within {timeout:.0f} s.{hint}") from exc
        except requests.RequestException as exc:
            raise LLMUnavailable(f"Could not reach Ollama: {exc}") from exc
        if response.status_code >= 400:
            # Ollama explains problems such as "model requires more system memory" in the body.
            try:
                detail = response.json().get("error", "")
            except ValueError:
                detail = response.text[:200]
            raise LLMUnavailable(f"Ollama returned an error: {detail or response.status_code}")
        self._loaded = True
        try:
            return response.json()["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMUnavailable("Ollama returned an unexpected response.") from exc


class ScriptedClient:
    """Returns canned answers in order. Used by tests and fail-safe demos."""

    def __init__(self, answers: list[str | dict | Exception], name: str = "scripted"):
        self.answers = list(answers)
        self.name = name
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, schema: dict) -> str:
        self.calls.append((system, user))
        if not self.answers:
            raise LLMUnavailable("No scripted answer left.")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer if isinstance(answer, str) else json.dumps(answer)
