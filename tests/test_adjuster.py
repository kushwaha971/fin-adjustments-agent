import json
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path
from unittest import mock

from adjuster import checks, explain
from adjuster.loaders import JELine, JournalEntry, load_coa
from adjuster.run import run

INPUTS = Path(__file__).resolve().parent.parent / "inputs"


def je(id_, *lines, date="2024-12-31", desc="test"):
    return JournalEntry(id_, desc, date, "test", [JELine(a, D(d), D(c), "") for a, d, c in lines])


class EntryChecks(unittest.TestCase):
    def setUp(self):
        self.coa = load_coa(INPUTS / "chart_of_accounts.csv")

    def check(self, entry, seen=None):
        found = checks.check_entry(entry, self.coa, {}, {}, {}, set() if seen is None else seen)
        return checks.decide(found), {f.code for f in found}

    def test_clean_entry_is_accepted(self):
        self.assertEqual(self.check(je("A", ("6400", 100, 0), ("2120", 0, 100))), ("accept", set()))

    def test_unbalanced_entry_is_rejected(self):
        decision, codes = self.check(je("A", ("6300", 28500, 0), ("6310", 0, 25000)))
        self.assertEqual(decision, "reject")
        self.assertIn("JE_UNBALANCED", codes)

    def test_unknown_account_is_held_not_guessed(self):
        """A near-miss code must not be silently remapped to its neighbour."""
        decision, codes = self.check(je("A", ("6315", 10, 0), ("6310", 0, 10)))
        self.assertEqual(decision, "quarantine")
        self.assertIn("JE_UNKNOWN_ACCOUNT", codes)

    def test_same_account_both_sides_is_circular(self):
        decision, codes = self.check(je("A", ("2170", 5, 0), ("2170", 0, 5)))
        self.assertEqual(decision, "quarantine")
        self.assertIn("JE_CIRCULAR", codes)

    def test_header_account_is_rejected(self):
        self.assertEqual(self.check(je("A", ("6000", 5, 0), ("2120", 0, 5)))[0], "reject")

    def test_out_of_period_is_held(self):
        decision, codes = self.check(je("A", ("6400", 5, 0), ("2120", 0, 5), date="2025-01-02"))
        self.assertEqual(decision, "quarantine")

    def test_duplicate_id_is_rejected(self):
        seen = set()
        self.check(je("A", ("6400", 5, 0), ("2120", 0, 5)), seen)
        self.assertIn("JE_DUPLICATE_ID", self.check(je("A", ("6400", 5, 0), ("2120", 0, 5)), seen)[1])


class FxChecks(unittest.TestCase):
    def test_missing_rate_is_not_guessed_by_default(self):
        coa = load_coa(INPUTS / "chart_of_accounts.csv")
        from adjuster.loaders import load_tb, load_fx
        rows = [r for r in load_tb(INPUTS / "trial_balance.csv") if r.currency == "GBP"]
        translated, found = checks.translate(rows, coa, load_fx(INPUTS / "fx_rates.csv"))
        self.assertEqual(translated, [])
        self.assertEqual([f.code for f in found], ["FX_RATE_MISSING"])

    def test_reval_that_no_rate_reproduces_is_held(self):
        entry = je("X", ("1110", 11200, 0), ("7310", 0, 11200), desc="FX revaluation of EUR cash")
        fx = {("EUR", "period_end"): D("1.095"), ("EUR", "period_average"): D("1.082")}
        found = checks._check_fx_reval(entry, fx, {("1110", "EUR"): D("825400")})
        self.assertEqual([f.code for f in found], ["JE_FX_MISMATCH"])

    def test_reval_that_matches_passes(self):
        entry = je("X", ("1110", "10730.20", 0), ("7310", 0, "10730.20"), desc="FX reval EUR")
        fx = {("EUR", "period_end"): D("1.095"), ("EUR", "period_average"): D("1.082")}
        self.assertEqual(checks._check_fx_reval(entry, fx, {("1110", "EUR"): D("825400")}), [])


class Explainer(unittest.TestCase):
    def test_llm_text_with_invented_number_is_thrown_away(self):
        f = checks.Finding("JE_UNBALANCED", checks.BLOCK, "JE-2", "debits 10.00 vs credits 8.00")
        with mock.patch.object(explain, "_llm_explanation", return_value="Off by 99,999."):
            out = explain.explain("JE-2", "x", "reject", [f], use_llm=True)
        self.assertEqual(out["by"], "template")
        self.assertIn("llm_rejected", out)

    def test_llm_failure_falls_back(self):
        f = checks.Finding("JE_UNBALANCED", checks.BLOCK, "JE-2", "debits 10.00 vs credits 8.00")
        with mock.patch.object(explain, "_llm_explanation", side_effect=RuntimeError):
            self.assertEqual(explain.explain("JE-2", "x", "reject", [f], True)["by"], "template")


class EndToEnd(unittest.TestCase):
    def test_provided_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = run(INPUTS, Path(tmp))
            result = json.loads((Path(tmp) / "decisions.json").read_text())
        decisions = {e["id"]: e["decision"] for e in result["entries"]}
        self.assertEqual(decisions["JE-002"], "reject")
        for held in ("JE-003", "JE-005", "JE-008"):
            self.assertEqual(decisions[held], "quarantine", held)
        self.assertEqual(summary["counts"], {"accept": 6, "quarantine": 3, "reject": 1})
        # posting accepted entries must not change the TB difference
        self.assertEqual(summary["tb_imbalance_before_adjustments"],
                         summary["tb_imbalance_after_adjustments"])

    def test_same_inputs_same_run_id(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            self.assertEqual(run(INPUTS, Path(a))["run_id"], run(INPUTS, Path(b))["run_id"])


if __name__ == "__main__":
    unittest.main()
