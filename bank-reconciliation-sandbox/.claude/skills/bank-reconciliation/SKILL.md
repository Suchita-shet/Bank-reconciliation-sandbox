---
name: bank-reconciliation
description: Reconcile a bank statement against a general-ledger cash account for one period. Use when asked to reconcile, match bank transactions to ledger entries, find discrepancies, or prepare a first-draft reconciliation for accountant review.
---

# Bank Reconciliation

Produce a reviewable first-draft reconciliation. A human accountant reviews your
output, so be precise and never invent transactions.

## Inputs
- `period_end` (YYYY-MM-DD)
- `bank_statement`: list of `{id, date, description, amount, reference}` (ids `B1`, `B2`, ...)
- `ledger`: list of the same shape (ids `L1`, `L2`, ...)

Amounts are in one currency. Positive = money in, negative = money out, in both sources.

## Rules

### Matching
1. **Amount** must match exactly to the cent.
2. **Date tolerance:** bank and ledger dates must be within 3 calendar days of each other (either direction).
3. **One-to-one:** every transaction is used in at most one match.
4. **Reference first:** before any amount/date matching, handle entries that have a non-empty `reference`. Compare references case-insensitively, ignoring date.
5. Same reference and equal amounts: **match**.
6. Same reference and amounts that are exact opposites: do not match, flag `SIGN_ERROR` on both.
7. Same reference and any other amount difference: do not match, flag `AMOUNT_MISMATCH` on both.
8. **Everything else:** go through ledger entries in ascending id order (L1, L2, L10...). Each takes the unmatched bank entry with the same amount and the smallest date gap; on a tie, the lowest bank id.
9. If no bank entry qualifies, leave the ledger entry unmatched. **Never force a match** outside the tolerance, and never match on description alone.
10. Descriptions are not used for matching. They are only used in rules 11, 12 and 13.

### Exceptions (applied to what is still unmatched, in this order)
11. **Duplicates:** an unmatched entry identical (date, amount, description ignoring case and extra spaces) to an entry that was matched on the same side is a duplicate. Ledger side: `DUPLICATE_LEDGER`. Bank side: `DUPLICATE_BANK`. The duplicate stays unmatched.
12. **Sign error without reference:** an unmatched ledger entry and an unmatched bank entry with opposite amounts, dates within 3 days, and the same description (ignoring case): flag `SIGN_ERROR` on both. Do not match them.
13. **Remaining bank entries:** description contains "fee", "charge" or "interest": `BANK_ONLY` (needs a ledger entry). Otherwise `UNRECORDED_BANK_ITEM`.
14. **Remaining ledger entries:** dated within 5 days of `period_end` (inclusive): `OUTSTANDING` (cheque or deposit still in transit). Older: `MISSING_IN_BANK`.

### Output
15. Every id appears in exactly one place: in a `matched` pair, or in the unmatched lists. Flags annotate unmatched entries; they never remove them from the unmatched lists. Every unmatched entry gets exactly one flag.
16. Sort ids numerically (B2 before B10). Sort `matched` by bank id.
17. Return **only** the JSON object below. No commentary, no totals, no invented ids.

```json
{
  "matched": [["B1", "L1"]],
  "unmatched_bank": ["B3"],
  "unmatched_ledger": ["L4"],
  "flags": [{"type": "BANK_ONLY", "ids": ["B3"]}, {"type": "OUTSTANDING", "ids": ["L4"]}]
}
```

Flag types: `OUTSTANDING`, `MISSING_IN_BANK`, `BANK_ONLY`, `UNRECORDED_BANK_ITEM`,
`DUPLICATE_LEDGER`, `DUPLICATE_BANK`, `SIGN_ERROR`, `AMOUNT_MISMATCH`.
For `SIGN_ERROR` and `AMOUNT_MISMATCH`, `ids` is `[bank_id, ledger_id]`.

## Worked example
period_end 2025-03-31. Bank: B1 03-05 -100.00; B2 03-06 -12.50 "Monthly service fee". Ledger: L1 03-04 -100.00; L2 03-29 -250.00.
Result: L1/B1 match (1 day apart). B2 is `BANK_ONLY`. L2 is `OUTSTANDING` (2 days before period end).

## Before answering, check
- Did every id land in exactly one place?
- Did you apply reference matching before amount/date matching?
- Did you avoid matching anything outside the 3-day tolerance?
- Is the reply only the JSON object?
