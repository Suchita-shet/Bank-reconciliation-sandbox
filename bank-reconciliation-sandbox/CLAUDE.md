# Bank Reconciliation Sandbox (project instructions)

This project automates **one business process: bank reconciliation** for a finance and
accounting team, and measures whether the automation actually works.

## Routing
- Reconcile a bank statement against a ledger -> use the `bank-reconciliation` skill
  (`.claude/skills/bank-reconciliation/SKILL.md`).
- Need reliable matching on a client file -> call the `bank-reconciliation` MCP tools
  (`load_transactions`, `match_transactions`, `find_discrepancies`, `generate_report`).
- Changing a rule or the skill -> run the evals before and after (see below).

## Data rules
- All data in this repo is **synthetic**. Never add real client data.
- One folder per client under `data/clients/<client>/`. Only read inside the folder of the client you were asked about.
- Never print, log or paste credentials. API keys come from environment variables only.

## Output rules
- Reconciliations are first drafts for accountant review. Say so. Never present them as final.
- Never invent transactions or ids. If unsure, leave the item unmatched and flag it.

## Evals
- Golden dataset: `evals/cases/` (20 cases, 5 trap cases). Each has an `expected` answer.
- Run: `python evals/run_eval.py --mode both` (raw Claude vs Claude + skill).
- When a case fails, find the missing/ambiguous rule in SKILL.md, fix it, rerun, and record the change.
  Do not edit the golden answers to make a score go up.
