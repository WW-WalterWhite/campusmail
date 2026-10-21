"""Evaluate CampusMail against hand labels.

    python eval/evaluate.py                                   # rules baseline on the sample inbox
    python eval/evaluate.py --engine ollama                   # the local model (Ollama must be running)
    python eval/evaluate.py --set dev --engine ollama --repeat 5 --out results/dev_ollama
    python eval/evaluate.py --set dev --engine cloud --provider "Anthropic (Claude)"   # key from ANTHROPIC_API_KEY
    python eval/evaluate.py --inbox my.csv --labels my_labels.csv --profile my_profile.json

Labels CSV: message_id, expected_priority (High / Medium / Low / Needs review) and optionally
expected_deadline (2026-10-22T17:00 with a time, 2026-10-22 for a date only, blank for none).

Metrics follow the project outline:
- macro-F1 over messages labelled High/Medium/Low;
- High recall ("Needs review" counts as a miss) and review recall;
- deadline recovery and the safety gate: any deadline that is not in the labels (invented or
  wrong) fails the gate;
- time per message (median and slowest) over --repeat runs.
With --out PREFIX, writes PREFIX.csv (per message, last run) and PREFIX.json (summary).
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from campusmail import pipeline  # noqa: E402
from campusmail.extraction import PROMPT_VERSION  # noqa: E402
from campusmail.importer import load_csv, parse_received  # noqa: E402
from campusmail.llm import CLOUD_PROVIDERS, DEFAULT_MODEL, LLMUnavailable, OllamaClient, cloud_client, key_from_env  # noqa: E402
from campusmail.models import Priority  # noqa: E402

BANDS = [Priority.HIGH.value, Priority.MEDIUM.value, Priority.LOW.value]
ALL = [Priority.REVIEW.value] + BANDS
SETS = {
    "sample": ("data/sample_inbox.csv", "data/sample_labels.csv"),
    "dev": ("data/dev_set.csv", "data/dev_labels.csv"),
    "challenge": ("data/challenge_set.csv", "data/challenge_labels.csv"),
}


def f1_scores(pairs: list[tuple[str, str]]) -> dict[str, float]:
    scores = {}
    for label in BANDS:
        tp = sum(1 for e, p in pairs if e == label and p == label)
        fp = sum(1 for e, p in pairs if e != label and p == label)
        fn = sum(1 for e, p in pairs if e == label and p != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        scores[label] = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return scores


def deadline_matches(expected: str, predicted: datetime | None, has_time: bool) -> bool:
    if predicted is None:
        return False
    if "T" in expected:
        return has_time and predicted.strftime("%Y-%m-%dT%H:%M") == expected
    return predicted.date().isoformat() == expected and not has_time


def evaluate(labels: dict[str, dict], results: dict[str, "pipeline.Result"]) -> dict:
    missing = sorted(set(labels) - set(results))
    if missing:
        raise SystemExit(f"Labelled messages missing from the inbox: {', '.join(missing)}")
    predicted = {m: results[m].priority.value for m in labels}
    expected = {m: row["expected_priority"] for m, row in labels.items()}
    f1 = f1_scores([(e, predicted[m]) for m, e in expected.items() if e in BANDS])
    high = [m for m, e in expected.items() if e == Priority.HIGH.value]
    review = [m for m, e in expected.items() if e == Priority.REVIEW.value]
    confusion = {e: {p: 0 for p in ALL} for e in ALL}
    for m, e in expected.items():
        confusion[e][predicted[m]] += 1

    report = {
        "n": len(expected),
        "macro_f1": sum(f1.values()) / len(f1),
        "f1": f1,
        "high_recalled": sum(predicted[m] == Priority.HIGH.value for m in high),
        "high_total": len(high),
        "review_flagged": sum(predicted[m] == Priority.REVIEW.value for m in review),
        "review_total": len(review),
        "confusion": confusion,
        "mismatches": [m for m in expected if predicted[m] != expected[m]],
    }
    if any("expected_deadline" in row for row in labels.values()):
        with_deadline = [m for m, row in labels.items() if row.get("expected_deadline")]
        recovered = [m for m in with_deadline
                     if deadline_matches(labels[m]["expected_deadline"], results[m].deadline, results[m].deadline_has_time)]
        # A shown deadline that the labels do not contain is the dangerous error: it is invented or wrong.
        # Messages sent to review show no deadline, so they cannot fail the gate.
        bad = [m for m in labels if results[m].deadline is not None and m not in recovered
               and results[m].priority is not Priority.REVIEW]
        report.update({
            "deadlines_recovered": len(recovered),
            "deadlines_total": len(with_deadline),
            "deadline_errors": bad,
            "safety_gate": "pass" if not bad else "fail",
        })
    return report


def make_client(args):
    if args.engine == "ollama":
        client = OllamaClient(model=args.model or DEFAULT_MODEL)
        ready, status = client.status()
        if not ready:
            raise SystemExit(status)
        print(status)
        return client
    if args.engine == "cloud":
        try:
            client = cloud_client(args.provider, key_from_env(args.provider), args.model, args.base_url)
        except LLMUnavailable as exc:
            raise SystemExit(f"{exc} (expected variable: {CLOUD_PROVIDERS[args.provider]['key_env']})")
        print(f"Sending the messages to {args.provider} ({client.model}).")
        return client
    return None


def print_report(report: dict, results: dict, labels: dict) -> None:
    print(f"Macro-F1 (High/Medium/Low only): {report['macro_f1']:.3f}   "
          + "  ".join(f"{k} {v:.2f}" for k, v in report["f1"].items()))
    print(f"High predicted High: {report['high_recalled']}/{report['high_total']}")
    print(f"Needs review flagged: {report['review_flagged']}/{report['review_total']}")
    if "deadlines_total" in report:
        print(f"Deadlines recovered: {report['deadlines_recovered']}/{report['deadlines_total']}   "
              f"safety gate: {report['safety_gate'].upper()}"
              + (f" (wrong or invented: {', '.join(report['deadline_errors'])})" if report["deadline_errors"] else ""))
    print("\nConfusion (rows = expected, columns = predicted):")
    print(f"{'':>14}" + "".join(f"{p:>14}" for p in ALL))
    for e in ALL:
        print(f"{e:>14}" + "".join(f"{report['confusion'][e][p]:>14}" for p in ALL))
    if report["mismatches"]:
        print("\nMismatches:")
        for m in report["mismatches"]:
            r = results[m]
            print(f"  {m}: expected {labels[m]['expected_priority']}, got {r.priority.value} ({'; '.join(r.reasons)})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", choices=list(SETS), default="sample", help="a bundled dataset")
    parser.add_argument("--inbox", type=Path, help="CSV of messages (overrides --set)")
    parser.add_argument("--labels", type=Path, help="labels CSV (overrides --set)")
    parser.add_argument("--profile", default=ROOT / "data/sample_profile.json", type=Path)
    parser.add_argument("--engine", choices=["rules", "ollama", "cloud"], default="rules")
    parser.add_argument("--model", help=f"model name (default: {DEFAULT_MODEL} for Ollama, the provider preset for cloud)")
    parser.add_argument("--provider", choices=list(CLOUD_PROVIDERS), default="OpenAI",
                        help="cloud provider; the API key is read from its environment variable")
    parser.add_argument("--base-url", help="base URL for 'Other OpenAI-compatible'")
    parser.add_argument("--repeat", type=int, default=1, help="run N times to measure time (scores use the last run)")
    parser.add_argument("--out", type=Path, help="write PREFIX.csv and PREFIX.json")
    args = parser.parse_args()
    # Windows consoles default to a legacy code page; reasons contain curly quotes.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    inbox = args.inbox or ROOT / SETS[args.set][0]
    labels_path = args.labels or ROOT / SETS[args.set][1]
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    now = parse_received(profile["reference_time"])
    messages = load_csv(inbox.read_bytes(), max_messages=None)  # the 30-message cap is a UI limit
    with labels_path.open(newline="", encoding="utf-8") as f:
        labels = {row["message_id"]: {k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)}
    bad = {row["expected_priority"] for row in labels.values()} - set(ALL)
    if bad:
        raise SystemExit(f"Unknown label(s): {', '.join(sorted(bad))}. Use one of: {', '.join(ALL)}")

    client = make_client(args)
    runs = []
    for i in range(max(1, args.repeat)):
        run = pipeline.run(messages, profile["courses"], now, client)
        runs.append(run)
        if args.repeat > 1:
            print(f"run {i + 1}/{args.repeat}: {run.seconds:.1f} s")
    run = runs[-1]
    if run.notice:
        print(f"NOTICE: {run.notice}")
    results = {r.message.message_id: r for r in run.results}
    report = evaluate(labels, results)

    per_message = [t for r in runs for t in r.timings.values()]
    report["timing"] = {
        "runs": len(runs),
        "run_seconds": [round(r.seconds, 2) for r in runs],
        "median_run_seconds": round(statistics.median(r.seconds for r in runs), 2),
        "slowest_run_seconds": round(max(r.seconds for r in runs), 2),
        "median_message_seconds": round(statistics.median(per_message), 2) if per_message else None,
        "slowest_message_seconds": round(max(per_message), 2) if per_message else None,
    }
    report["setup"] = {
        "engine": run.model_name, "mode": run.mode, "prompt_version": PROMPT_VERSION,
        "inbox": inbox.name, "labels": labels_path.name, "python": platform.python_version(),
        "platform": platform.platform(), "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    print(f"Engine: {run.model_name}   set: {inbox.name}   messages: {report['n']}   "
          f"run time (median of {len(runs)}): {report['timing']['median_run_seconds']} s")
    print_report(report, results, labels)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["message_id", "expected", "predicted", "expected_deadline", "deadline",
                             "reasons", "summary", "engine", "seconds"])
            for m, r in results.items():
                writer.writerow([m, labels.get(m, {}).get("expected_priority", ""), r.priority.value,
                                 labels.get(m, {}).get("expected_deadline", ""),
                                 r.deadline.strftime("%Y-%m-%dT%H:%M") if r.deadline else "",
                                 " | ".join(r.reasons), r.extraction.summary if r.extraction else "",
                                 run.model_name, f"{run.timings.get(m, 0):.2f}"])
        args.out.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nResults written to {args.out.with_suffix('.csv')} and {args.out.with_suffix('.json')}")


if __name__ == "__main__":
    main()
