# Reflection

**With 3 months instead of 8 hours.** I would build the mapper first, not the
adjustments slice, because every later stage depends on it. That means a
versioned mapping table per ERP source, LLM proposals with a type and
normal-balance compatibility check, and a review UI where an approval becomes
a rule. Then a real ledger store (Postgres, with append-only posted lines), an
exception queue with owners and SLAs, intercompany matching across entities,
and statement builders that ship only when the BS, CF and SOCIE tie-outs pass.
Tolerances and materiality would come from policy config rather than constants.

**Where this breaks at scale.** Everything is in memory and single-entity.
With thousands of accounts the per-row findings list becomes noise, so findings
need grouping and ranking. Multi-entity consolidation needs entity and
counterparty keys, IC matching across TBs at different rates, CTA calculation,
and minority interest. None of these exist here. The FX reval check identifies
the account by code (1110), and a real one needs a revaluable-accounts
configuration. The circular-IC check only sees one entry, but real circularity
spans entries and entities (A→B→C→A).

**How I used AI tools.** I used Claude Code throughout. It drafted most of the
code, tests and documents from the brief and the data. I steered it, reviewed
what it produced, ran the program and the tests, and worked through every file
until I could explain each decision. Reviewing the first run caught two real
problems, and both were fixed: a sign bug that reported a growing credit
balance as a fall, and a materiality threshold so low that almost every entry
was flagged. The places where AI could lead you wrong are exactly what the
design guards against. The LLM is never allowed to make a decision or produce a
number, and any explanation it writes is thrown away if it mentions a figure
that is not in the findings.

**What I think is underestimated.** Opening balances and period semantics. The
TB doesn't say whether it is quarter-to-date or year-to-date, and retained
earnings in the current TB doesn't roll from the prior TB plus P&L. A system can
pass every arithmetic check and still produce a wrong SOCIE because nobody
pinned down what the opening balance *is*. That question is about accounting,
not about engineering, and it decides whether the statements are right.