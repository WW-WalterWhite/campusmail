"""One-command benchmark for the status sheet and the final report.

    python eval/benchmark.py                 # rules + local model on the sample, dev and challenge sets
    python eval/benchmark.py --quick         # sample inbox only (about a minute)
    python eval/benchmark.py --model qwen3:1.7b

Runs the rules baseline and the local model on each bundled set and writes, under results/:
- benchmark_<time>.md: a results table, the mismatches and the setup, ready to paste;
- one CSV + JSON per engine and set (the same files evaluate.py --out writes).
The sample inbox is run three times so the timing is a median, not one lucky run.
If Ollama is not running, it still writes the rules results and says what to fix.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluate import ROOT, SETS, evaluate_set, write_outputs  # noqa: E402

from campusmail.extraction import PROMPT_VERSION  # noqa: E402
from campusmail.llm import DEFAULT_MODEL, OllamaClient  # noqa: E402

SAMPLE_REPEATS = 3


def table_row(engine: str, set_name: str, report: dict) -> str:
    t = report["timing"]
    per_message = t["median_message_seconds"]
    gate = report.get("safety_gate", "n/a").upper()
    if report.get("deadline_errors"):
        gate += f" ({', '.join(report['deadline_errors'])})"
    return (f"| {engine} | {set_name} | {report['macro_f1']:.3f} | {report['high_recalled']}/{report['high_total']} | "
            f"{report['review_flagged']}/{report['review_total']} | "
            f"{report.get('deadlines_recovered', '-')}/{report.get('deadlines_total', '-')} | {gate} | "
            f"{per_message if per_message is not None else '-'} |")


def mismatch_lines(report: dict, run, labels: dict) -> list[str]:
    by_id = {r.message.message_id: r for r in run.results}
    return [f"- `{m}`: expected {labels[m]['expected_priority']}, got {by_id[m].priority.value} "
            f"({'; '.join(by_id[m].reasons)})" for m in report["mismatches"]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=None, help=f"Ollama model (default: {DEFAULT_MODEL})")
    parser.add_argument("--quick", action="store_true", help="sample inbox only")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "results")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    profile = json.loads((ROOT / "data/sample_profile.json").read_text(encoding="utf-8"))
    sets = ["sample"] if args.quick else ["sample", "dev", "challenge"]
    stamp = datetime.now().strftime("%Y%m%d_%H%M")

    client = OllamaClient(model=args.model or DEFAULT_MODEL)
    ready, status = client.status()
    print(status)
    engines = [("rules", None)] + ([(client.name, client)] if ready else [])

    rows, details = [], []
    for set_name in sets:
        inbox, labels_path = (ROOT / p for p in SETS[set_name])
        for engine, engine_client in engines:
            repeat = SAMPLE_REPEATS if engine_client and set_name == "sample" else 1
            print(f"\n{engine} on {set_name} ({repeat} run{'s' if repeat > 1 else ''})...", flush=True)
            report, run, labels = evaluate_set(inbox, labels_path, profile, engine_client, repeat,
                                               log=lambda line: print("  " + line, flush=True))
            if run.notice:
                # The model stopped answering part-way: these are rules results, so don't label them as AI.
                print(f"  NOTICE: {run.notice}")
                engine = f"{engine} (fell back to rules)"
            safe = "rules" if engine_client is None else "model"
            write_outputs(args.out_dir / f"{set_name}_{safe}_{stamp}", report, run, labels)
            rows.append(table_row(engine, set_name, report))
            print("  " + rows[-1])
            details += [f"\n### {engine} on {set_name}", *(mismatch_lines(report, run, labels) or ["- no mismatches"])]

    lines = [
        f"# CampusMail benchmark, {datetime.now():%Y-%m-%d %H:%M}",
        "",
        "| engine | set | macro-F1 | High → High | review flagged | deadlines | safety gate | median s/message |",
        "|---|---|---|---|---|---|---|---|",
        *rows,
        "",
        "Macro-F1 is over messages labelled High/Medium/Low. A \"Needs review\" prediction counts as a High miss.",
        "The safety gate fails if any shown deadline is not in the labels (invented or wrong).",
        "Labels for the dev and challenge sets are drafts, and the rules were adjusted after seeing those sets,",
        "so the rules scores there are optimistic. Only the locked test set gives a fair comparison",
        "(see docs/EVALUATION.md).",
        "",
        "## Mismatches",
        *details,
        "",
        "## Setup",
        f"- Model: {client.name if ready else 'not available: ' + status}",
        f"- Prompt version: {PROMPT_VERSION}",
        f"- Python {platform.python_version()} on {platform.platform()}",
        f"- Processor: {platform.processor() or platform.machine()}",
    ]
    report_path = args.out_dir / f"benchmark_{stamp}.md"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nSaved {report_path}")
    if not ready:
        print("The local model was not tested. Start Ollama (and run setup again if the model is missing), "
              "then run the benchmark again.")
        sys.exit(1)


if __name__ == "__main__":
    main()
