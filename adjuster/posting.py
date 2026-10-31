"""Apply accepted entries to the translated TB and keep the trail.

Every account in the output lists the exact source rows and entry lines
that make up its balance, so a reviewer can go from any number back to
the CSV line or JSON entry it came from.
"""

from collections import defaultdict
from decimal import Decimal
from typing import Dict, List

from .loaders import Account, JournalEntry


def build_ledger(translated, coa: Dict[str, Account]) -> Dict[str, dict]:
    ledger = defaultdict(lambda: {"pre": Decimal("0"), "adj": Decimal("0"), "trace": []})
    for row, usd, note in translated:
        acc = ledger[row.code]
        acc["pre"] += usd
        acc["trace"].append({"from": row.source, "amount": str(usd), "rate": note})
        acc["name"] = coa[row.code].name if row.code in coa else row.name
    return ledger


def post(ledger: Dict[str, dict], entries: List[JournalEntry], coa: Dict[str, Account]):
    for je in entries:
        for i, l in enumerate(je.lines, start=1):
            acc = ledger[l.account]
            acc.setdefault("name", coa[l.account].name if l.account in coa else "?")
            amount = l.debit - l.credit
            acc["adj"] += amount
            acc["trace"].append({"from": f"manual_adjustments.json:{je.id}#line{i}",
                                 "amount": str(amount), "memo": l.memo})
    return ledger


def ledger_rows(ledger: Dict[str, dict]) -> List[dict]:
    rows = []
    for code in sorted(ledger):
        a = ledger[code]
        rows.append({"account_code": code, "account_name": a.get("name", ""),
                     "pre_adjustment": f"{a['pre']:.2f}", "adjustments": f"{a['adj']:.2f}",
                     "post_adjustment": f"{a['pre'] + a['adj']:.2f}",
                     "sources": " | ".join(t["from"] for t in a["trace"])})
    return rows


def totals(ledger: Dict[str, dict]) -> Dict[str, Decimal]:
    pre = sum((a["pre"] for a in ledger.values()), Decimal("0"))
    adj = sum((a["adj"] for a in ledger.values()), Decimal("0"))
    return {"pre": pre, "adj": adj, "post": pre + adj}
