# Adjustments review - 2024-Q4

Run id `52d31bd35c0ddb5c` (hash of the inputs - same inputs, same id, same result).

**6 accepted, 3 on hold, 1 rejected.**

Trial balance difference before adjustments: -338,687.00 USD  
After accepted adjustments: -338,687.00 USD

## Why the trial balance does not balance

Hypotheses only - none of these are posted.

| Step | Change | Remaining gap |
|---|---:|---:|
| difference as loaded | 0.00 | -338687.00 |
| trial_balance.csv:4: include 412300.00 GBP at average 1.264 | 521147.20 | 182460.20 |
| trial_balance.csv:49: drop the duplicate row | -38500.00 | 143960.20 |
| trial_balance.csv:63: clear the unmapped suspense balance | -12400.00 | 131560.20 |
| UNEXPLAINED - needs the ERP export or the preparer |  | 131560.20 |

## Journal entries

### JE-001 - ACCEPT

JE-001 (Accrue Q4 bonus pool) was accepted and posted.
- Line 2 (2120): 850,000 is 74% of the account's TB balance.
  What to do: No action needed - flagged for reviewer attention because of its size.

### JE-002 - REJECT

JE-002 (Reclassify marketing spend wrongly booked to T&E) was rejected and was not posted.
- Debits 28,500.00 vs credits 25,000.00.
  What to do: Correct the line amounts so debits equal credits and resubmit.

### JE-003 - QUARANTINE

JE-003 (FX revaluation of EUR cash balance to period-end rate) is on hold until someone reviews it.
- Booked 11,200.00; recomputed 19,809.60 from opening, 10,730.20 from period_average.
  What to do: Send the reval calculation so we can see which rate the balance is carried at.

### JE-004 - ACCEPT

JE-004 (Bad debt provision top-up) was accepted and posted.

### JE-005 - QUARANTINE

JE-005 (Reclass conference travel from old code) is on hold until someone reviews it.
- Line 1 (6315): account 6315 is not in the COA.
  What to do: Confirm the right account (or ask for it to be added to the COA), then resubmit.
  Possible accounts: 6310 Travel and Entertainment; 6300 Marketing and Advertising; 6400 Professional Fees

### JE-006 - ACCEPT

JE-006 (Depreciation catch-up — Q4) was accepted and posted.

### JE-007 - ACCEPT

JE-007 (Deferred tax true-up) was accepted and posted.

### JE-008 - QUARANTINE

JE-008 (Intercompany settlement — UK sub) is on hold until someone reviews it.
- Account 2170 is debited 320,000.00 and credited 320,000.00 - the entry nets to nothing.
  What to do: Confirm with the intercompany team what this settlement should move; as written it changes nothing.

### JE-009 - ACCEPT

JE-009 (Accrue legal fees for ongoing litigation) was accepted and posted.

### JE-010 - ACCEPT

JE-010 (Reclass long-term debt current portion) was accepted and posted.

## Problems in the inputs

| Severity | Where | Issue |
|---|---|---|
| block | trial_balance.csv:4 | no period_end rate for GBP; row left untranslated |
| block | trial_balance.csv | credits exceed debits by 338,687.00 after translation |
| needs_human | COA:1150 | cash-flow category for 'Other Current Assets' is TBD |
| needs_human | COA:2170 | cash-flow category for 'Intercompany Payable' is TBD |
| needs_human | trial_balance.csv:49 | 6310/USD also appears at trial_balance.csv:48 |
| needs_human | trial_balance.csv:63 | current TB account 9999 'Suspense - Unmapped' is not in the COA |
| needs_human | prior_period_tb.csv:34 | prior TB account 6905 'Sundry Operating Expenses' is not in the COA |
| needs_human | prior_period_tb.csv:34 | prior-period account 6905 'Sundry Operating Expenses' has no current-period row and is not in the COA (renamed?) |
| warn | COA:1290 | header 'Other Assets' has no child accounts |
| warn | COA:7000 | 'Non-Operating Items' has no normal balance |
| warn | trial_balance.csv:11 | 1210 moved +44% vs prior (11,800,000 -> 17,007,700) |
| warn | trial_balance.csv:22 | 2150 moved +33% vs prior (-315,000 -> -420,000) |
| warn | trial_balance.csv:31 | 3200 moved +40% vs prior (-5,180,000 -> -7,240,000) |
| warn | trial_balance.csv:32 | 3310 moved +89% vs prior (-95,000 -> -180,000) |
