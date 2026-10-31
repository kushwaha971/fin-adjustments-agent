# Agentic financial statement generation — architecture

## 1. The problem is not one problem

"Generate the financials" is at least seven jobs, and they need different
levels of reliability:

| # | Sub-problem | Nature | Can it be wrong? |
|---|---|---|---|
| 1 | Ingest + normalise ERP exports (SAP, NetSuite) | parsing | No: schema errors stop the run |
| 2 | Map ERP accounts to the COA | judgement on new/odd codes, lookup otherwise | Only with a human sign-off |
| 3 | FX translation | arithmetic + rate policy | No |
| 4 | Validate and post manual adjustments | rules + explanation | No for the decision, yes for the wording |
| 5 | Intercompany elimination | matching + rules | No |
| 6 | Build BS / P&L / CF / SOCIE | arithmetic over a mapping | No |
| 7 | Verify and reconcile (TB balances, BS balances, CF ties to cash, SOCIE ties to BS equity, prior-period roll-forward) | arithmetic | No |
| 8 | Explain exceptions to finance users | language | Yes, if it is checked |

Most of this is deterministic. The LLM earns its keep in three narrow places:
**proposing** mappings for accounts that have never been seen (2), **reading**
free text (JE descriptions, memos, controller notes) to say what an entry is
trying to do (4), and **explaining** exceptions in plain English (8). It never
produces a number that goes on a statement.

## 2. Topology: a pipeline with a few LLM tools, not a swarm

```
           ┌───────────── deterministic pipeline (the "orchestrator" is plain code) ─────────────┐
inputs ──► Ingest ──► Mapper ──► FX ──► Adjustments ──► IC elim ──► Statement builder ──► Verifier ──► outputs
              │          │                    │                                              │
              │     [LLM: propose]      [LLM: explain]                                 [fail → stop,
              │          │                    │                                         report, no output]
              └──────────┴──── exception queue (human review) ◄──────────────────────────┘
```

* The orchestrator is ordinary code: a fixed order of stages, every stage a pure
  function of its inputs. An LLM planner would add non-determinism to the one
  part that has no reason to vary.
* LLM calls are **tools inside a stage**, with a typed input and output, and
  their output is checked before anything uses it.
* Anything a stage cannot decide goes to an **exception queue** with the
  evidence attached. A person resolves it, and their decision is stored as
  configuration (a mapping rule, an approved JE), so the next run is fully
  deterministic again.

Why not an orchestrator agent with Mapper/Adjuster/Builder/Validator sub-agents?
Because the order of steps never changes and the success criteria are
arithmetic. Agents are useful when the path is unknown; here the path is known
and the risk is in the data. Four agents talking to each other would give four
places to hallucinate and a trace nobody can audit.

## 3. Where the line sits between code and LLM

| Decision | Who | Why |
|---|---|---|
| Is this JE balanced, in period, on postable accounts? | code | It is a rule. |
| Accept / quarantine / reject | code, from findings | Has to be reproducible and defensible to an auditor. |
| Which COA node does an unseen ERP account belong to? | LLM **proposes** with confidence + reasoning; code checks it is a real postable leaf with a compatible type/normal balance; a human approves below a confidence threshold, and every first-time mapping is reviewed | A hallucinated mapping silently moves money between statements. |
| Is the FX reval amount right? | code recomputes it | Arithmetic. |
| What does "Reclass conference travel from old code" mean? | LLM may summarise intent | Helps the reviewer; never posts. |
| Explaining a rejection | LLM writes it; code rejects text with numbers not in the findings; template fallback | Wording is the only place a mistake is cheap, and even then we check it. |

## 4. Failure modes and what the system does

| Failure | Detection | Handling |
|---|---|---|
| Hallucinated mapping | Proposed code must exist, be a leaf, and match statement/normal balance; the mapping table is versioned | Below threshold or first-seen → exception queue. Never auto-applied on first sight. |
| Debits ≠ credits in a JE | Sum check with 0.01 tolerance | Reject; plain-English reason; nothing posted. |
| TB doesn't balance | Sum after translation | Stop before statements; produce an "imbalance walk" that tests each known suspect (missing FX, duplicate rows, suspense) and reports what is left unexplained. |
| Account fits no COA node (9999 Suspense, 6315, 6905) | lookup | Quarantine with nearest-account suggestions; never silently remapped. |
| FX gap (no GBP period-end rate) | rate lookup per row by statement type | Default: block and leave the row out, loudly. An explicit flag allows period-average fallback, and every affected number is marked provisional. |
| Circular intercompany entry (JE-008) | same account debited and credited | Quarantine: it nets to nothing, so it is either a no-op or a mistake. |
| Duplicate TB row (6310 twice) | (account, currency) key | Quarantine; the walk shows its effect on the gap. |
| Prior-period rename (6905 → 6900?) | prior codes without a current row | Ask; a rename map is configuration and is versioned with the period. |

## 5. Validation and self-correction loop

Before anything is returned:

1. **Input health**: COA structure, TB keys, FX coverage, prior-period continuity.
2. **Per-entry checks** → findings → decision (pure function).
3. **Post** accepted entries, then **re-verify**: accepted adjustments net to
   zero; the TB difference is unchanged by posting; (in the full system) BS
   balances, CF closing cash = BS cash, SOCIE closing = BS equity, prior
   closing = current opening.
4. If a post-check fails, **no statement is produced**. The run returns the
   failing check and the rows involved.

"Self-correction" is deliberately limited. The system may retry an **LLM tool**
(for example, ask again for a mapping when the proposed code does not exist,
feeding back the validator error, at most twice). It may **never correct the
data**: changing an amount or picking an account for the user is a decision for
finance, not for the agent. It proposes the fix and quarantines.

## 6. Audit trail

* Every TB row keeps `file:line`; every JE line keeps `manual_adjustments.json:JE-xxx#lineN`.
* Every ledger balance carries its list of contributing sources and the FX rate
  used (see `output/post_adjustment_tb.csv`, column `sources`).
* A statement cell = sum of COA leaves → each leaf = its sources. Clicking a
  cell walks that tree.
* Run id = hash of the inputs plus config (mapping version, rate policy, code
  version). Same inputs give the same id and the same output (idempotent), so
  a re-run can be diffed.
* Every human override (mapping approved, JE released from quarantine) is
  stored with who, when and why, and becomes an input to the next run.

## 7. The slice built

**Manual adjustments agent**, in `adjuster/`. It loads the messy data unchanged,
reports input defects, decides each JE, explains it, posts the accepted ones
with a trace, and re-verifies. Results on the provided data:

| JE | Decision | Why |
|---|---|---|
| 001, 004, 006, 007, 009, 010 | accept | clean (001 flagged for size: 74% of the accrued-expenses balance) |
| 002 | **reject** | debits 28,500 ≠ credits 25,000 |
| 003 | **quarantine** | booked reval 11,200 matches neither the average (10,730.20) nor the opening (19,809.60) basis |
| 005 | **quarantine** | 6315 not in COA; suggests 6310 |
| 008 | **quarantine** | 2170 debited and credited 320,000: nets to nothing |

Input defects found beyond the ones the brief lists: the 6310 duplicate
(38,500), 9999 suspense not in the COA, the 1290 header with no children,
the 7000 header with no normal balance, 1210 PP&E up 44% on prior, the JE-003
reval amount not reproducible, and retained-earnings movement (2.06M) that
does not match P&L net income (6.0M).
