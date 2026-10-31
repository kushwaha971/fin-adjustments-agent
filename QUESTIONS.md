# Clarifying questions

The brief allows three to be emailed before starting. These are the three I
would send, then the ones I answered with an assumption.

1. **FX basis.** At what rate is the EUR cash balance carried before
   revaluation (opening, average, or historical per transaction)? JE-003's
   11,200 matches neither basis I can compute (10,730.20 / 19,809.60). And
   with no GBP period-end rate, may we use the average provisionally, or must
   the close wait for the rate?
2. **Is the TB year-to-date or quarter-only, and is retained earnings already
   rolled?** P&L accounts total 6.0M net income, but retained earnings moved
   2.06M from the prior TB, and the prior TB carries no P&L. This decides the
   SOCIE and the remaining 131,560 TB gap.
3. **Who may release a quarantined entry, and is 6315 → 6310 / 6905 → 6900 a
   rename we can map permanently?** It decides whether a mapping rule is
   configuration (per period) or a one-off approval.

Assumptions made instead of asking:
- BS rows translate at period-end, P&L at period-average, equity at historical (USD here anyway).
- A JE that is wrong *as written* is rejected; one that *might* be right is quarantined.
- Materiality warning at 50% of the account's TB balance (placeholder, should come from policy).
- Tolerance 0.01 USD for balance checks.
