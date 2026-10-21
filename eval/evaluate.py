"""Evaluate CampusMail priorities against hand labels.

    python eval/evaluate.py                       # rules baseline on the sample inbox
    python eval/evaluate.py --engine ollama       # the local model (Ollama must be running)
    python eval/evaluate.py --inbox data/dev.csv --labels data/dev_labels.csv --out results/dev_rules.csv

    python eval/evaluate.py --engine cloud --provider "Anthropic (Claude)"   # key from ANTHROPIC_API_KEY

Labels CSV: message_id, expected_priority (High / Medium / Low / Needs review).
Metrics follow the project outline: macro-F1 over messages labelled High/Medium/Low,
High recall (a "Needs review" prediction counts as a miss) and review recall.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from campusmail import pipeline  # noqa: E402
from campusmail.importer import load_csv, parse_received  # noqa: E402
from campusmail.llm import CLOUD_PROVIDERS, DEFAULT_MODEL, LLMUnavailable, OllamaClient, cloud_client, key_from_env  # noqa: E402
from campusmail.models import Priority  # noqa: E402

BANDS = [Priority.HIGH.value, Priority.MEDIUM.value, Priority.LOW.value]
ALL = [Priority.REVIEW.value] + BANDS


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


def evaluate(expected: dict[str, str], predicted: dict[str, str]) -> dict:
    missing = sorted(set(expected) - set(predicted))
    if missing:
        raise SystemExit(f"Labelled messages missing from the inbox: {', '.join(missing)}")
    banded = [(e, predicted[m]) for m, e in expected.items() if e in BANDS]
    f1 = f1_scores(banded)
    high = [m for m, e in expected.items() if e == Priority.HIGH.value]
    review = [m for m, e in expected.items() if e == Priority.REVIEW.value]
    confusion = {e: {p: 0 for p in ALL} for e in ALL}
    for m, e in expected.items():
        confusion[e][predicted[m]] += 1
    return {
        "n": len(expected),
        "macro_f1": sum(f1.values()) / len(f1),
        "f1": f1,
        "high_recalled": sum(predicted[m] == Priority.HIGH.value for m in high),
        "high_total": len(high),
        "review_flagged": sum(predicted[m] == Priority.REVIEW.value for m in review),
        "review_total": len(review),
        "confusion": confusion,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--inbox", default=ROOT / "data/sample_inbox.csv", type=Path)
    parser.add_argument("--labels", default=ROOT / "data/sample_labels.csv", type=Path)
    parser.add_argument("--profile", default=ROOT / "data/sample_profile.json", type=Path)
    parser.add_argument("--engine", choices=["rules", "ollama", "cloud"], default="rules")
    parser.add_argument("--model", help=f"model name (default: {DEFAULT_MODEL} for Ollama, the provider preset for cloud)")
    parser.add_argument("--provider", choices=list(CLOUD_PROVIDERS), default="OpenAI",
                        help="cloud provider; the API key is read from its environment variable")
    parser.add_argument("--base-url", help="base URL for 'Other OpenAI-compatible'")
    parser.add_argument("--out", type=Path, help="write per-message raw results to this CSV")
    args = parser.parse_args()

    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    now = parse_received(profile["reference_time"])
    messages = load_csv(args.inbox.read_bytes())
    with args.labels.open(newline="", encoding="utf-8") as f:
        expected = {row["message_id"]: row["expected_priority"].strip() for row in csv.DictReader(f)}
    bad = {v for v in expected.values() if v not in ALL}
    if bad:
        raise SystemExit(f"Unknown label(s): {', '.join(sorted(bad))}. Use one of: {', '.join(ALL)}")

    client = None
    if args.engine == "ollama":
        client = OllamaClient(model=args.model or DEFAULT_MODEL)
        ready, status = client.status()
        if not ready:
            raise SystemExit(status)
    elif args.engine == "cloud":
        try:
            client = cloud_client(args.provider, key_from_env(args.provider), args.model, args.base_url)
        except LLMUnavailable as exc:
            raise SystemExit(f"{exc} (expected variable: {CLOUD_PROVIDERS[args.provider]['key_env']})")
        print(f"Sending {args.inbox.name} to {args.provider}.")
    run = pipeline.run(messages, profile["courses"], now, client)
    if run.notice:
        print(f"NOTICE: {run.notice}")
    predicted = {r.message.message_id: r.priority.value for r in run.results}
    report = evaluate(expected, predicted)

    print(f"Engine: {run.model_name}   messages: {report['n']}   time: {run.seconds:.1f} s")
    print(f"Macro-F1 (High/Medium/Low only): {report['macro_f1']:.3f}   "
          + "  ".join(f"{k} {v:.2f}" for k, v in report["f1"].items()))
    print(f"High predicted High: {report['high_recalled']}/{report['high_total']}")
    print(f"Needs review flagged: {report['review_flagged']}/{report['review_total']}")
    print("\nConfusion (rows = expected, columns = predicted):")
    print(f"{'':>14}" + "".join(f"{p:>14}" for p in ALL))
    for e in ALL:
        print(f"{e:>14}" + "".join(f"{report['confusion'][e][p]:>14}" for p in ALL))
    wrong = [m for m, e in expected.items() if predicted[m] != e]
    if wrong:
        print("\nMismatches:")
        for r in run.results:
            if r.message.message_id in wrong:
                print(f"  {r.message.message_id}: expected {expected[r.message.message_id]}, got {r.priority.value} ({'; '.join(r.reasons)})")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["message_id", "expected", "predicted", "deadline", "reasons", "engine", "seconds"])
            for r in run.results:
                mid = r.message.message_id
                writer.writerow([mid, expected.get(mid, ""), r.priority.value,
                                 r.deadline.isoformat() if r.deadline else "", " | ".join(r.reasons),
                                 run.model_name, f"{run.timings.get(mid, 0):.2f}"])
        print(f"\nRaw results written to {args.out}")


if __name__ == "__main__":
    main()
