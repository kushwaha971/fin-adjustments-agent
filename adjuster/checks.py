"""Deterministic checks. Nothing in this file calls an LLM.

Every check returns Finding objects. The decision for a journal entry
(accept / quarantine / reject) is made only from these findings, so the
same inputs always give the same decision.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List

from .loaders import Account, JournalEntry, TBRow

BLOCK = "block"            # entry cannot be posted as written -> reject
NEEDS_HUMAN = "needs_human"  # may be fine, but a person has to decide -> quarantine
WARN = "warn"              # post it, but tell someone

TOLERANCE = Decimal("0.01")
PERIOD_START, PERIOD_END = "2024-10-01", "2024-12-31"
MATERIALITY_SHARE = Decimal("0.50")   # line > 50% of the account's TB balance
FX_REVAL_TOLERANCE = Decimal("0.01")  # 1% between booked and recomputed reval
PRIOR_VARIANCE = Decimal("0.30")      # BS account moved > 30% vs prior period


@dataclass
class Finding:
    code: str
    severity: str
    subject: str           # "JE-002", "trial_balance.csv:49", "COA:1290" ...
    message: str           # short, technical - the explainer turns it into prose
    facts: dict = field(default_factory=dict)


# --------------------------------------------------------------- COA ---

def check_coa(coa: Dict[str, Account]) -> List[Finding]:
    out = []
    children = defaultdict(list)
    for a in coa.values():
        if a.parent:
            children[a.parent].append(a.code)
            if a.parent not in coa:
                out.append(Finding("COA_BAD_PARENT", WARN, f"COA:{a.code}",
                                   f"parent {a.parent} does not exist"))
    for a in coa.values():
        if a.is_header and not children[a.code]:
            out.append(Finding("COA_EMPTY_HEADER", WARN, f"COA:{a.code}",
                               f"header '{a.name}' has no child accounts"))
        if a.cf_category == "TBD":
            out.append(Finding("COA_AMBIGUOUS_CF", NEEDS_HUMAN, f"COA:{a.code}",
                               f"cash-flow category for '{a.name}' is TBD"))
        if not a.normal_balance:
            out.append(Finding("COA_NO_NORMAL_BALANCE", WARN, f"COA:{a.code}",
                               f"'{a.name}' has no normal balance"))
    return out


# ---------------------------------------------------------------- TB ---

def check_tb(rows: List[TBRow], coa: Dict[str, Account], label: str) -> List[Finding]:
    out = []
    seen = {}
    for r in rows:
        key = (r.code, r.currency)
        if key in seen:
            out.append(Finding("TB_DUPLICATE_ROW", NEEDS_HUMAN, r.source,
                               f"{r.code}/{r.currency} also appears at {seen[key]}",
                               {"first": seen[key], "amount": str(r.debit - r.credit)}))
        else:
            seen[key] = r.source
        acct = coa.get(r.code)
        if acct is None:
            out.append(Finding("TB_ORPHAN_ACCOUNT", NEEDS_HUMAN, r.source,
                               f"{label} account {r.code} '{r.name}' is not in the COA",
                               {"amount": str(r.debit - r.credit)}))
        elif acct.is_header:
            out.append(Finding("TB_POSTS_TO_HEADER", BLOCK, r.source,
                               f"{r.code} is a header and cannot carry a balance"))
        elif acct.name != r.name:
            out.append(Finding("TB_NAME_MISMATCH", WARN, r.source,
                               f"name '{r.name}' differs from COA '{acct.name}'"))
        if r.debit and r.credit:
            out.append(Finding("TB_BOTH_SIDES", WARN, r.source, "row has debit and credit"))
    return out


def translate(rows: List[TBRow], coa: Dict[str, Account], fx: dict,
              functional: str = "USD", fallback_to_average: bool = False):
    """Translate every row to the functional currency.

    BS rows use the period-end rate, PL rows the period average. If a rate
    is missing we do NOT guess unless fallback_to_average is set, and even
    then the row is flagged so it cannot be mistaken for a clean number.
    Returns (list of (row, usd_amount, rate_note)), findings).
    """
    out, findings = [], []
    for r in rows:
        native = r.debit - r.credit
        if r.currency == functional:
            out.append((r, native, "functional"))
            continue
        acct = coa.get(r.code)
        wanted = "period_end" if (acct is None or acct.statement == "BS") else "period_average"
        rate = fx.get((r.currency, wanted))
        if rate is None and fallback_to_average and (r.currency, "period_average") in fx:
            rate = fx[(r.currency, "period_average")]
            findings.append(Finding("FX_FALLBACK_USED", WARN, r.source,
                                    f"no {wanted} rate for {r.currency}; used period_average {rate}",
                                    {"currency": r.currency}))
            out.append((r, (native * rate).quantize(TOLERANCE), f"{r.currency} avg {rate} (FALLBACK)"))
            continue
        if rate is None:
            findings.append(Finding("FX_RATE_MISSING", BLOCK, r.source,
                                    f"no {wanted} rate for {r.currency}; row left untranslated",
                                    {"currency": r.currency, "native": str(native)}))
            continue
        out.append((r, (native * rate).quantize(TOLERANCE), f"{r.currency} {wanted} {rate}"))
    return out, findings


def check_tb_balances(translated, label: str) -> List[Finding]:
    total = sum((amt for _, amt, _ in translated), Decimal("0"))
    if abs(total) > TOLERANCE:
        side = "debits exceed credits" if total > 0 else "credits exceed debits"
        return [Finding("TB_OUT_OF_BALANCE", BLOCK, label,
                        f"{side} by {abs(total):,.2f} after translation",
                        {"difference": str(total)})]
    return []


def imbalance_walk(translated, input_findings: List[Finding], fx: dict) -> List[dict]:
    """Explain the TB difference step by step from things we already found.

    Each step says "if this suspect were resolved this way, the gap would be".
    These are hypotheses for a person to confirm, not corrections - nothing
    here is posted. Whatever is left at the end is honestly unexplained.
    """
    gap = sum((amt for _, amt, _ in translated), Decimal("0"))
    steps = [{"step": "difference as loaded", "change": "0.00", "gap": f"{gap:.2f}"}]

    def add(label, change):
        nonlocal gap
        gap += change
        steps.append({"step": label, "change": f"{change:.2f}", "gap": f"{gap:.2f}"})

    for f in input_findings:
        if f.code == "FX_RATE_MISSING":
            avg = fx.get((f.facts["currency"], "period_average"))
            if avg is not None:
                add(f"{f.subject}: include {f.facts['native']} {f.facts['currency']} at average {avg}",
                    (Decimal(f.facts["native"]) * avg).quantize(TOLERANCE))
    for f in input_findings:
        if f.code == "TB_DUPLICATE_ROW":
            add(f"{f.subject}: drop the duplicate row", -Decimal(f.facts["amount"]))
    for f in input_findings:
        if f.code == "TB_ORPHAN_ACCOUNT" and f.subject.startswith("trial_balance"):
            add(f"{f.subject}: clear the unmapped suspense balance", -Decimal(f.facts["amount"]))
    steps.append({"step": "UNEXPLAINED - needs the ERP export or the preparer",
                  "change": "", "gap": f"{gap:.2f}"})
    return steps


def check_against_prior(current: List[TBRow], prior: List[TBRow],
                        coa: Dict[str, Account]) -> List[Finding]:
    out = []
    cur_codes = {r.code for r in current}
    for r in prior:
        if r.code not in cur_codes:
            out.append(Finding("PRIOR_ACCOUNT_GONE", NEEDS_HUMAN, r.source,
                               f"prior-period account {r.code} '{r.name}' has no current-period row"
                               + ("" if r.code in coa else " and is not in the COA (renamed?)")))
    prior_usd = defaultdict(Decimal)
    for r in prior:
        if r.currency == "USD":
            prior_usd[r.code] += r.debit - r.credit
    for r in current:
        if r.currency != "USD" or r.code not in prior_usd or not prior_usd[r.code]:
            continue
        acct = coa.get(r.code)
        if acct is None or acct.statement != "BS":
            continue
        before, now = prior_usd[r.code], r.debit - r.credit
        # compare sizes, so a credit balance growing reads as growth, not a fall
        change = (abs(now) - abs(before)) / abs(before)
        if abs(change) > PRIOR_VARIANCE:
            out.append(Finding("PRIOR_LARGE_MOVE", WARN, r.source,
                               f"{r.code} moved {change:+.0%} vs prior ({before:,.0f} -> {now:,.0f})"))
    return out


# --------------------------------------------------------------- JEs ---

def check_entry(je: JournalEntry, coa: Dict[str, Account],
                tb_balance: Dict[str, Decimal], fx: dict,
                tb_native: Dict[tuple, Decimal], seen_ids: set) -> List[Finding]:
    out = []
    s = je.id

    if je.id in seen_ids:
        out.append(Finding("JE_DUPLICATE_ID", BLOCK, s, "entry id already used in this batch"))
    seen_ids.add(je.id)

    if len(je.lines) < 2:
        out.append(Finding("JE_TOO_FEW_LINES", BLOCK, s, "an entry needs at least two lines"))

    diff = je.total_debit - je.total_credit
    if abs(diff) > TOLERANCE:
        out.append(Finding("JE_UNBALANCED", BLOCK, s,
                           f"debits {je.total_debit:,.2f} vs credits {je.total_credit:,.2f}",
                           {"debit": str(je.total_debit), "credit": str(je.total_credit),
                            "difference": str(diff)}))

    if not (PERIOD_START <= je.date <= PERIOD_END):
        out.append(Finding("JE_OUT_OF_PERIOD", NEEDS_HUMAN, s,
                           f"dated {je.date}, outside {PERIOD_START}..{PERIOD_END}"))

    for i, l in enumerate(je.lines, start=1):
        where = f"line {i} ({l.account})"
        if l.debit < 0 or l.credit < 0:
            out.append(Finding("JE_NEGATIVE_AMOUNT", BLOCK, s, f"{where} has a negative amount"))
        if l.debit and l.credit:
            out.append(Finding("JE_LINE_BOTH_SIDES", BLOCK, s, f"{where} has debit and credit"))
        if not l.debit and not l.credit:
            out.append(Finding("JE_LINE_ZERO", WARN, s, f"{where} is zero"))
        acct = coa.get(l.account)
        if acct is None:
            out.append(Finding("JE_UNKNOWN_ACCOUNT", NEEDS_HUMAN, s,
                               f"{where}: account {l.account} is not in the COA",
                               {"account": l.account, "amount": str(l.debit or l.credit),
                                "suggestions": nearest_accounts(l.account, coa)}))
        elif acct.is_header:
            out.append(Finding("JE_POSTS_TO_HEADER", BLOCK, s,
                               f"{where}: {l.account} '{acct.name}' is a header"))
        else:
            bal = abs(tb_balance.get(l.account, Decimal("0")))
            amt = l.debit or l.credit
            if bal and amt / bal > MATERIALITY_SHARE:
                out.append(Finding("JE_MATERIAL", WARN, s,
                                   f"{where}: {amt:,.0f} is {amt / bal:.0%} of the account's TB balance"))

    # circular: the same account is debited and credited inside one entry
    by_acct = defaultdict(lambda: [Decimal("0"), Decimal("0")])
    for l in je.lines:
        by_acct[l.account][0] += l.debit
        by_acct[l.account][1] += l.credit
    for acct_code, (dr, cr) in by_acct.items():
        if dr and cr:
            net_zero = all(not (d or c) or a == acct_code for a, (d, c) in by_acct.items()) \
                       and abs(dr - cr) <= TOLERANCE
            out.append(Finding("JE_CIRCULAR", NEEDS_HUMAN, s,
                               f"account {acct_code} is debited {dr:,.2f} and credited {cr:,.2f}"
                               + (" - the entry nets to nothing" if net_zero else ""),
                               {"account": acct_code, "nets_to_zero": net_zero}))

    out.extend(_check_fx_reval(je, fx, tb_native))
    return out


def _check_fx_reval(je: JournalEntry, fx: dict, tb_native: Dict[tuple, Decimal]) -> List[Finding]:
    """If an entry says it revalues a foreign balance, recompute it.

    We do not know which rate the balance is currently carried at, so we try
    each rate we have and only pass the entry if one of them reproduces it.
    """
    text = (je.description + " " + " ".join(l.memo for l in je.lines)).upper()
    if "REVAL" not in text:
        return []
    ccy = next((c for c in ("EUR", "GBP") if c in text), None)
    if ccy is None:
        return []
    native = tb_native.get(("1110", ccy))
    end = fx.get((ccy, "period_end"))
    if native is None or end is None:
        return [Finding("JE_FX_UNVERIFIABLE", NEEDS_HUMAN, je.id,
                        f"cannot recompute the {ccy} revaluation (balance or period-end rate missing)")]
    booked = je.total_debit
    candidates = {}
    for basis in ("opening", "period_average"):
        r = fx.get((ccy, basis))
        if r is not None:
            candidates[basis] = (native * (end - r)).quantize(TOLERANCE)
    for basis, expected in candidates.items():
        if expected and abs(booked - expected) / abs(expected) <= FX_REVAL_TOLERANCE:
            return []
    return [Finding("JE_FX_MISMATCH", NEEDS_HUMAN, je.id,
                    f"booked {booked:,.2f}; recomputed "
                    + ", ".join(f"{v:,.2f} from {k}" for k, v in candidates.items()),
                    {"booked": str(booked), "native_balance": str(native),
                     "period_end_rate": str(end),
                     "recomputed": {k: str(v) for k, v in candidates.items()}})]


def nearest_accounts(code: str, coa: Dict[str, Account], n: int = 3) -> List[str]:
    """Cheap, explainable suggestions for an unknown code: same 3-digit
    prefix first, then numerically closest. Never applied automatically."""
    postable = [a for a in coa.values() if not a.is_header and a.code.isdigit()]
    if not code.isdigit():
        return []
    postable.sort(key=lambda a: (a.code[:3] != code[:3], abs(int(a.code) - int(code))))
    return [f"{a.code} {a.name}" for a in postable[:n]]


def decide(findings: List[Finding]) -> str:
    severities = {f.severity for f in findings}
    if BLOCK in severities:
        return "reject"
    if NEEDS_HUMAN in severities:
        return "quarantine"
    return "accept"
