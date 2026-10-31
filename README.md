# Manual adjustments agent

Prototype slice for the AI Agentic Engineer take-home: validates a batch of
manual journal entries against a messy TB, COA and FX rates, decides
accept / quarantine / reject, explains each decision in plain English, posts
the accepted ones with a full audit trail, and re-verifies the result.

Design: [ARCHITECTURE.md](ARCHITECTURE.md) · Questions: [QUESTIONS.md](QUESTIONS.md) · Reflection: [REFLECTION.md](REFLECTION.md)

## Run

Python 3.9+, standard library only.

```bash
python3 -m adjuster.run                 # writes output/
python3 -m adjuster.run --fx-fallback   # use average rate where period-end is missing (flagged)
python3 -m unittest -v                  # 14 tests
```

Optional LLM wording for explanations (decisions are never affected):

```bash
pip install anthropic
export ANTHROPIC_API_KEY=...
python3 -m adjuster.run --llm
```

If the model mentions any number that is not in the findings, its text is
discarded and the template is used. The same happens if the call fails.

## Output

| File | What |
|---|---|
| `output/report.md` | Human-readable: decisions, explanations, TB imbalance walk, input defects |
| `output/decisions.json` | Machine-readable decisions with findings and facts |
| `output/input_findings.json` | Every defect found in the inputs |
| `output/post_adjustment_tb.csv` | Pre / adjustments / post per account, with source rows for each |

## Layout

```
adjuster/loaders.py   read inputs as-is, keep file:line for every row
adjuster/checks.py    all rules (no LLM); findings -> decision
adjuster/explain.py   template + optional LLM wording, with a number check
adjuster/posting.py   apply accepted entries, keep the trace
adjuster/run.py       pipeline + report
```
