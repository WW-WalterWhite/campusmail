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


class _HTTPClient:
    """Shared request handling for the cloud engines."""

    provider = "cloud"

    def __init__(self, api_key: str, model: str, timeout: float = DEFAULT_TIMEOUT):
        if not api_key:
            raise LLMUnavailable(f"No API key for {self.provider}. Enter one in the sidebar or set it as an environment variable.")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.name = f"{self.provider} {model}"

    def _post(self, url: str, headers: dict, payload: dict) -> dict:
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        except requests.Timeout as exc:
            raise LLMUnavailable(f"{self.provider} did not answer within {self.timeout:.0f} s.") from exc
        except requests.RequestException as exc:
            raise LLMUnavailable(f"Could not reach {self.provider}: {exc}") from exc
        if response.status_code in (401, 403):
            raise LLMUnavailable(f"{self.provider} rejected the API key (HTTP {response.status_code}).")
        if response.status_code == 429:
            raise LLMUnavailable(f"{self.provider} rate limit or quota reached (HTTP 429).")
        if response.status_code >= 400:
            # The error body names the problem (e.g. an unknown model) and never contains the key.
            raise LLMUnavailable(f"{self.provider} returned HTTP {response.status_code}: {response.text[:200]}")
        try:
            return response.json()
        except ValueError as exc:
            raise LLMUnavailable(f"{self.provider} returned a response that is not JSON.") from exc


class OpenAICompatibleClient(_HTTPClient):
    """Any provider with an OpenAI-style /chat/completions endpoint: OpenAI, DeepSeek, Qwen
    (Alibaba Cloud Model Studio), and others. `json_mode` is "schema" where the provider supports
    JSON-schema structured output, otherwise "object" (plain JSON mode); either way the
    answer still goes through validate_output and the evidence checks.
    """

    def __init__(self, api_key: str, model: str, base_url: str, provider: str = "OpenAI-compatible API",
                 json_mode: str = "schema", temperature: float | None = 0, timeout: float = DEFAULT_TIMEOUT):
        self.provider = provider
        super().__init__(api_key, model, timeout)
        self.base_url = base_url.rstrip("/")
        self.json_mode = json_mode
        self.temperature = temperature

    def complete(self, system: str, user: str, schema: dict) -> str:
        if self.json_mode == "schema":
            response_format = {"type": "json_schema", "json_schema": {"name": "extraction", "schema": schema}}
        else:
            response_format = {"type": "json_object"}
            # JSON mode needs the shape spelled out in the prompt.
            system = f"{system}\n\nJSON schema:\n{json.dumps(schema)}"
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": response_format,
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        data = self._post(f"{self.base_url}/chat/completions",
                          {"Authorization": f"Bearer {self.api_key}"}, payload)
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable(f"{self.provider} returned an unexpected response.") from exc
        # content is null when the model refuses; validation then sends that one message to review.
        return message.get("content") or "" if isinstance(message, dict) else ""


class AnthropicClient(_HTTPClient):
    """Claude via the Anthropic Messages API, with structured outputs (output_config.format) so the
    answer is JSON that matches the extraction schema.

    No temperature is sent (current Claude models reject a non-default one) and thinking is left
    at the model's default with low effort, which is enough for one short email.
    """

    provider = "Anthropic"
    URL = "https://api.anthropic.com/v1/messages"

    def complete(self, system: str, user: str, schema: dict) -> str:
        payload = {
            "model": self.model,
            "max_tokens": 16000,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": {
                "effort": "low",
                "format": {"type": "json_schema", "schema": {**schema, "additionalProperties": False}},
            },
        }
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        data = self._post(self.URL, headers, payload)
        if not isinstance(data, dict) or not isinstance(data.get("content"), list):
            raise LLMUnavailable("Anthropic returned an unexpected response.")
        # A refusal or a cut-off answer is a problem with this one email, not with the service:
        # return what there is and let validation send the message to review.
        return "".join(b.get("text", "") for b in data["content"] if isinstance(b, dict) and b.get("type") == "text")


# Presets shown in the app. Model names change often: they are only defaults and can be edited
# in the sidebar; check the provider's model list if one is rejected.
CLOUD_PROVIDERS = {
    "OpenAI": {"kind": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-4.1-mini",
               # Some newer OpenAI models only accept the default temperature, so none is sent.
               "json_mode": "schema", "temperature": None, "key_env": "OPENAI_API_KEY"},
    "Anthropic (Claude)": {"kind": "anthropic", "model": "claude-haiku-5-5", "key_env": "ANTHROPIC_API_KEY"},
    "DeepSeek": {"kind": "openai", "base_url": "https://api.deepseek.com", "model": "deepseek-chat",
                 "json_mode": "object", "key_env": "DEEPSEEK_API_KEY"},
    "Qwen (Alibaba Cloud)": {"kind": "openai", "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                             "model": "qwen-plus", "json_mode": "object", "key_env": "DASHSCOPE_API_KEY"},
    "Other OpenAI-compatible": {"kind": "openai", "base_url": "", "model": "", "json_mode": "object",
                                "key_env": "CAMPUSMAIL_API_KEY"},
}


def cloud_client(provider: str, api_key: str, model: str | None = None, base_url: str | None = None):
    preset = CLOUD_PROVIDERS[provider]
    model = model or preset["model"]
    if preset["kind"] == "anthropic":
        return AnthropicClient(api_key, model)
    if not (base_url or preset["base_url"]):
        raise LLMUnavailable("Enter the provider's base URL (ending in /v1 or similar).")
    return OpenAICompatibleClient(api_key, model, base_url or preset["base_url"], provider,
                                  preset["json_mode"], preset.get("temperature", 0))


def key_from_env(provider: str) -> str:
    return os.environ.get(CLOUD_PROVIDERS[provider]["key_env"], "")
