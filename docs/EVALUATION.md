# Evaluation Data, Methodology and Measured Results

All messages in this repository are **100% synthetic**; no real inbox data is stored or committed.

## 1. Bundled Datasets

Every split uses the profile in `data/sample_profile.json` (enrolled courses `AILT9019, COMP3297, ECON1210, CCST9017`; reference time `Wed 21 Oct 2026 10:00 UTC+8`).

| Split | Files | Messages | Purpose & Provenance |
|---|---|---|---|
| **Sample inbox** | `data/sample_inbox.csv`, `data/sample_labels.csv` | 13 | Interactive app demo & 3-run warm timing check |
| **Development set** | `data/dev_set.csv`, `data/dev_labels.csv` | 40 (10 / band) | Prompt & validator tuning (`extract-v1` → `extract-v2`) |
| **Challenge set** | `data/challenge_set.csv`, `data/challenge_labels.csv` | 16 | Harder date/mode phrasings (`22.10.2026`, `end of day`, `ASAP`, online shift) |
| **Locked test set** | `data/test_set.csv`, `data/test_labels.csv` | **80 (20 / band)** | **Frozen unseen evaluation set** (natural verbs, thread extensions, near-duplicates & 6 fail-safe trap types) |

## 2. Metrics & Anti-Inflation Rules

- **Macro-F1 (High / Medium / Low):** Computed strictly across messages whose gold label is `High`, `Medium`, or `Low`. Predicting `Needs review` on any of those counts as an error so abstention cannot inflate precision/F1.
- **High Recall & Review Recall:** Exact fraction of urgent `High` messages predicted `High`, and ambiguous/hostile `Needs review` messages correctly flagged.
- **Deadline Safety Gate:** Passes **only** if zero non-review messages display an invented or wrong deadline.

## 3. Measured Results (`Ollama qwen3:4b`, digest `359d7dd4bcda`)

Measured locally on `Windows-11-10.0.26200-SP0` (`Intel64 Family 6 (Windows 11 laptop)`, Python `3.15.1`).

| Engine | Split | Macro-F1 | High → High | Review Flagged | Deadlines | Safety Gate | Median s / msg |
|---|---|---|---|---|---|---|---|
| Keyword/date rules (1st run, pre-fix) | dev (40) | 0.933 | 8/10 | 8/10 | — | PASS | < 0.01 |
| Keyword/date rules (1st run, pre-fix) | challenge (16) | 0.766 | 2/5 | 2/4 | — | PASS | < 0.01 |
| **Keyword/date rules (frozen baseline)** | **locked test (80)** | **0.966** | **18/20** | **20/20** | **30/33** | **PASS** | **< 0.01** |
| Ollama `qwen3:4b` (`extract-v1`, MacBook Air M2 16 GB) | dev (40) | 0.910 | 7/10 | 7/10 | — | FAIL (3 emails) | 14.60 |
| Ollama `qwen3:4b` (`extract-v1`, Windows 11) | dev (40) | 0.930 | 8/10 | 7/10 | 15/16 | FAIL (d26, d32, d39) | 3.59 |
| Ollama `qwen3:4b` (`extract-v2` final) | sample (13 × 3) | 1.000 | 3/3 | 5/5 | 4/4 | PASS | 4.07 |
| Ollama `qwen3:4b` (`extract-v2` final) | dev (40) | 0.967 | 9/10 | 9/10 | 15/16 | PASS | 3.57 |
| Ollama `qwen3:4b` (`extract-v2` final) | challenge (16) | 0.952 | 5/5 | 4/4 | 7/8 | PASS | 3.52 |
| **Ollama `qwen3:4b` (`extract-v2` final)** | **locked test (80)** | **0.974** | **18/20** | **20/20** | **30/33** | **PASS** | **3.66** |

### What Dev-Set Benchmarking Caught (`extract-v1` → `extract-v2`)

Running live `qwen3:4b` on `sample` and `dev` uncovered five real integration bugs that mocked unit tests missed:
1. Summaries restating `UTC+8` triggered false number-hallucination rejections for `'8'`.
2. Qwen3 occasionally emitted the literal string `"null"` instead of JSON `null` for `course`.
3. Event timestamps on optional `Low` announcements remained attached as deadlines, tripping the safety gate.
4. Emails containing explicit date corrections (`30 Oct instead of 28 Oct`) needed deterministic multi-date conflict detection in `evidence.py` rather than relying solely on the model's `deadline_status`.
5. `"end of day"` occasionally decoded as `00:00` instead of `23:59`.

Fixing these deterministic guards in `models.py`, `evidence.py`, `priority.py`, and `extraction.py` before evaluating the frozen 80-message locked test set eliminated all safety-gate failures.

### Locked Test Set Mismatches (`Ollama qwen3:4b`)

- `t09`: expected **High**, predicted **Needs review** — Marked as having an explicit deadline but no date was given.
- `t19`: expected **High**, predicted **Needs review** — The summary mentions the time '08:00', which is not in the email. | The summary mentions the number '2026', which is not in the email. | The summary mentions the number '10', which is not in the email.
- `t30`: expected **Medium**, predicted **Needs review** — Course Econometric Analysis is not written in the email.

## 4. How to Reproduce

```bash
# Fast check without Ollama (rules baseline + 110 automated unit/UI/fail-safe tests)
python -m pytest
python eval/evaluate.py --set test

# Full local Qwen3 4B benchmark across sample (3×), dev (40), challenge (16), and locked test (80)
python eval/benchmark.py
```
