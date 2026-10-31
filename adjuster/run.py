"""Entry point: python -m adjuster.run [--inputs DIR] [--out DIR] [--llm] [--fx-fallback]"""

import argparse
import csv
import hashlib
import json
from decimal import Decimal
from pathlib import Path

from . import checks
from .explain import explain
from .loaders import load_adjustments, load_coa, load_fx, load_tb
from .posting import build_ledger, ledger_rows, post, totals


def _hash_inputs(folder: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(folder.glob("*")):
        if p.suffix in (".csv", ".json"):
            h.update(p.name.encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def _as_dict(f: checks.Finding) -> dict:
    return {"code": f.code, "severity": f.severity, "subject": f.subject,
            "message": f.message, "facts": f.facts}


def run(inputs: Path, out: Path, use_llm: bool = False, fx_fallback: bool = False) -> dict:
    coa = load_coa(inputs / "chart_of_accounts.csv")
    tb = load_tb(inputs / "trial_balance.csv")
    prior = load_tb(inputs / "prior_period_tb.csv")
    fx = load_fx(inputs / "fx_rates.csv")
    batch = load_adjustments(inputs / "manual_adjustments.json")

    # 1. input health - reported, never silently fixed
    input_findings = checks.check_coa(coa)
    input_findings += checks.check_tb(tb, coa, "current TB")
    input_findings += checks.check_tb(prior, coa, "prior TB")
    input_findings += checks.check_against_prior(tb, prior, coa)
    translated, fx_findings = checks.translate(tb, coa, fx, batch["functional_currency"], fx_fallback)
    input_findings += fx_findings
    input_findings += checks.check_tb_balances(translated, "trial_balance.csv")

    # 2. each journal entry on its own
    ledger = build_ledger(translated, coa)
    tb_balance = {code: a["pre"] for code, a in ledger.items()}
    tb_native = {}
    for r in tb:
        tb_native[(r.code, r.currency)] = tb_native.get((r.code, r.currency), Decimal("0")) + r.debit - r.credit

    decisions, accepted, seen = [], [], set()
    for je in batch["entries"]:
        found = checks.check_entry(je, coa, tb_balance, fx, tb_native, seen)
        decision = checks.decide(found)
        if decision == "accept":
            accepted.append(je)
        decisions.append({
            "id": je.id, "description": je.description, "date": je.date, "source": je.source,
            "debit": str(je.total_debit), "credit": str(je.total_credit),
            "decision": decision, "findings": [_as_dict(f) for f in found],
            "explanation": explain(je.id, je.description, decision, found, use_llm),
        })

    # 3. post accepted entries and re-check the result
    post(ledger, accepted, coa)
    t = totals(ledger)
    post_checks = []
    if abs(t["adj"]) > checks.TOLERANCE:
        # cannot happen if the checks above are right - this is the guard on the guard
        post_checks.append("accepted adjustments do not net to zero: " + str(t["adj"]))
    tb_imbalance = t["pre"]

    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "run_id": _hash_inputs(inputs), "period": batch["period"],
        "fx_fallback_used": fx_fallback, "llm_used": use_llm,
        "counts": {k: sum(d["decision"] == k for d in decisions)
                   for k in ("accept", "quarantine", "reject")},
        "tb_imbalance_before_adjustments": str(tb_imbalance),
        "tb_imbalance_after_adjustments": str(t["post"]),
        "post_checks_failed": post_checks,
        "tb_imbalance_walk": checks.imbalance_walk(translated, input_findings, fx),
    }
    (out / "decisions.json").write_text(json.dumps({"summary": summary, "entries": decisions}, indent=2))
    (out / "input_findings.json").write_text(json.dumps([_as_dict(f) for f in input_findings], indent=2))
    with open(out / "post_adjustment_tb.csv", "w", newline="") as f:
        rows = ledger_rows(ledger)
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (out / "report.md").write_text(_report(summary, input_findings, decisions))
    return summary


def _report(summary, input_findings, decisions) -> str:
    lines = [f"# Adjustments review - {summary['period']}", "",
             f"Run id `{summary['run_id']}` (hash of the inputs - same inputs, same id, same result).", "",
             f"**{summary['counts']['accept']} accepted, {summary['counts']['quarantine']} on hold, "
             f"{summary['counts']['reject']} rejected.**", "",
             f"Trial balance difference before adjustments: {Decimal(summary['tb_imbalance_before_adjustments']):,.2f} USD  ",
             f"After accepted adjustments: {Decimal(summary['tb_imbalance_after_adjustments']):,.2f} USD", ""]
    lines += ["## Why the trial balance does not balance", "",
              "Hypotheses only - none of these are posted.", "",
              "| Step | Change | Remaining gap |", "|---|---:|---:|"]
    for w in summary["tb_imbalance_walk"]:
        lines.append(f"| {w['step']} | {w['change']} | {w['gap']} |")
    lines.append("")
    if summary["post_checks_failed"]:
        lines += ["**Post-posting checks FAILED:**"] + [f"- {p}" for p in summary["post_checks_failed"]] + [""]
    lines += ["## Journal entries", ""]
    for d in decisions:
        lines += [f"### {d['id']} - {d['decision'].upper()}", "", d["explanation"]["text"], ""]
    lines += ["## Problems in the inputs", "", "| Severity | Where | Issue |", "|---|---|---|"]
    order = {checks.BLOCK: 0, checks.NEEDS_HUMAN: 1, checks.WARN: 2}
    for f in sorted(input_findings, key=lambda f: order[f.severity]):
        lines.append(f"| {f.severity} | {f.subject} | {f.message} |")
    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser(description="Validate and post a batch of manual adjustments.")
    p.add_argument("--inputs", default="inputs", type=Path)
    p.add_argument("--out", default="output", type=Path)
    p.add_argument("--llm", action="store_true", help="word explanations with Claude (needs ANTHROPIC_API_KEY)")
    p.add_argument("--fx-fallback", action="store_true",
                   help="use period_average when a period_end rate is missing (flagged)")
    args = p.parse_args()
    s = run(args.inputs, args.out, args.llm, args.fx_fallback)
    print(json.dumps(s, indent=2))


if __name__ == "__main__":
    main()
