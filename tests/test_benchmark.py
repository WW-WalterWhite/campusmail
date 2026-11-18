"""The one-command benchmark: report layout and honest labelling when the model drops out."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))

import benchmark  # noqa: E402

from campusmail.llm import LLMUnavailable  # noqa: E402


class DroppingClient:
    name = "fake-model"

    def __init__(self, model=None):
        pass

    def status(self):
        return True, "ready"

    def complete(self, system, user, schema):
        raise LLMUnavailable("stopped")


def test_writes_report_and_labels_fallback(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(benchmark, "OllamaClient", DroppingClient)
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "--quick", "--out-dir", str(tmp_path)])
    benchmark.main()
    report = next(tmp_path.glob("benchmark_*.md")).read_text(encoding="utf-8")
    assert "| rules | sample | 1.000 |" in report
    # A run where the model stopped answering is rules output and must not be reported as AI.
    assert "| fake-model (fell back to rules) | sample |" in report
    assert len(list(tmp_path.glob("sample_*.csv"))) == 2


def test_without_ollama_still_writes_rules_and_exits_nonzero(tmp_path, monkeypatch):
    class Offline(DroppingClient):
        def status(self):
            return False, "Ollama is not running."
    monkeypatch.setattr(benchmark, "OllamaClient", Offline)
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "--quick", "--out-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc:
        benchmark.main()
    assert exc.value.code == 1
    assert "not available: Ollama is not running." in next(tmp_path.glob("benchmark_*.md")).read_text(encoding="utf-8")
