"""Read the input bundle as-is. No cleaning happens here: every oddity is
kept so the checks downstream can see it and report it."""

import csv
import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class Account:
    code: str
    name: str
    type: str
    parent: Optional[str]
    statement: str
    cf_category: str
    normal_balance: str

    @property
    def is_header(self) -> bool:
        return self.type == "Header"


@dataclass
class TBRow:
    source: str  # e.g. "trial_balance.csv:49" - used for audit trail
    code: str
    name: str
    currency: str
    debit: Decimal
    credit: Decimal


@dataclass
class JELine:
    account: str
    debit: Decimal
    credit: Decimal
    memo: str


@dataclass
class JournalEntry:
    id: str
    description: str
    date: str
    source: str
    lines: List[JELine] = field(default_factory=list)

    @property
    def total_debit(self) -> Decimal:
        return sum((l.debit for l in self.lines), Decimal("0"))

    @property
    def total_credit(self) -> Decimal:
        return sum((l.credit for l in self.lines), Decimal("0"))


def _dec(value) -> Decimal:
    # str() first so 0.1 from JSON does not become 0.1000000000000000055...
    return Decimal(str(value or "0"))


def load_coa(path: Path) -> Dict[str, Account]:
    accounts = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            accounts[row["account_code"]] = Account(
                code=row["account_code"],
                name=row["account_name"],
                type=row["account_type"],
                parent=row["parent_code"] or None,
                statement=row["statement"],
                cf_category=row["cf_category"],
                normal_balance=row["normal_balance"],
            )
    return accounts


def load_tb(path: Path) -> List[TBRow]:
    rows = []
    with open(path, newline="") as f:
        # line 1 is the header, so data starts at line 2
        for line_no, row in enumerate(csv.DictReader(f), start=2):
            rows.append(TBRow(
                source=f"{path.name}:{line_no}",
                code=row["account_code"],
                name=row["account_name"],
                currency=row["currency"],
                debit=_dec(row["debit"]),
                credit=_dec(row["credit"]),
            ))
    return rows


def load_fx(path: Path) -> Dict[tuple, Decimal]:
    """Returns {(currency, rate_type): rate}. Missing pairs are simply absent."""
    rates = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rates[(row["currency"], row["rate_type"])] = _dec(row["rate"])
    return rates


def load_adjustments(path: Path) -> dict:
    with open(path) as f:
        raw = json.load(f)
    entries = []
    for e in raw["entries"]:
        je = JournalEntry(e["id"], e["description"], e["date"], e.get("source", ""))
        for l in e["lines"]:
            je.lines.append(JELine(str(l["account"]), _dec(l.get("debit")),
                                   _dec(l.get("credit")), l.get("memo", "")))
        entries.append(je)
    return {"period": raw["period"], "functional_currency": raw["functional_currency"],
            "entries": entries}
