# Evaluation data and results

All messages are synthetic. Nothing here comes from a real inbox.

## Datasets

| set | files | messages | status |
|---|---|---|---|
| Sample inbox | `data/sample_inbox.csv`, `data/sample_labels.csv` | 13 | demo data shown in the app |
| Development set | `data/dev_set.csv`, `data/dev_labels.csv` | 40 (10 per class) | **draft labels written by an AI assistant**; two team members must label it independently and resolve disagreements |
| Challenge set | `data/challenge_set.csv`, `data/challenge_labels.csv` | 16 | harder phrasing; written after the dev set to check how well the rules generalise |
| Locked test set | not in the repository yet | 80 (20 per class) | **must be written and labelled by the team** and frozen before any prompt tuning |

Every set uses the profile in `data/sample_profile.json` (courses AILT9019, COMP3297, ECON1210,
CCST9017; reference time Wed 21 Oct 2026 10:00 UTC+8). Labels follow the priority policy in the
README, and `expected_deadline` gives the deadline the app should show (blank for none).

## Rules baseline: what the numbers mean

The rules baseline now scores perfectly on all three bundled sets, **but those scores say little**:
the same person wrote the messages, wrote the labels and then fixed the rules where they failed.
The honest measure is the first run on data the rules had not seen:

| set (first run, before any rule changes) | macro-F1 | High → High | review flagged |
|---|---|---|---|
| Development set | 0.933 | 8/10 (after fixing one wrong label) | 8/10 |
| Challenge set | **0.766** | **2/5** | **2/4** |

The challenge-set run shows the expected weakness of keyword rules: they missed `Due: 22 Oct, 11:59 PM`,
dates written `22.10.2026`, an "online instead of in person" schedule change and an "ASAP" request.
These parser gaps were then fixed because the rules are also the app's fallback when the AI is
unavailable. The locked test set is where the baseline and the model must be compared.

## How to run

```bash
python eval/evaluate.py --set dev                                   # rules baseline
python eval/evaluate.py --set dev --engine ollama --repeat 5 --out results/dev_qwen3
```

`--repeat 5` gives the median and slowest run times needed for the reliability target (10 warm
messages within 2 minutes). `--out` writes a per-message CSV and a JSON summary (`results/` is
git-ignored; copy the numbers you report into the final report).

## Results to fill in

| engine | set | macro-F1 | High → High | review | deadlines | safety gate | median s/message |
|---|---|---|---|---|---|---|---|
| rules | dev | | | | | | |
| Qwen3 4B (Ollama) | dev | | | | | | |
| rules | locked test | | | | | | |
| Qwen3 4B (Ollama) | locked test | | | | | | |
