"""Eval harness: raw Claude vs Claude + Skill on the golden dataset.

Online (needs ANTHROPIC_API_KEY in your environment or a .env file):
    python evals/run_eval.py --mode both
    python evals/run_eval.py --mode skill --model <model-id>

Offline harness self-check (no API, no Claude involved):
    python evals/run_eval.py --offline reference   # should score 100%
    python evals/run_eval.py --offline naive       # deliberately weak solver

Both modes receive the same task and output schema. Only the skill mode also
receives the rules in SKILL.md.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bankrecon.engine import FLAG_TYPES, canonical, id_key, reconcile  # noqa: E402
from bankrecon.scoring import parse_model_json, score_case  # noqa: E402

CASES_DIR = ROOT / "evals" / "cases"
RESULTS_DIR = ROOT / "evals" / "results"
SKILL_PATH = ROOT / ".claude" / "skills" / "bank-reconciliation" / "SKILL.md"
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")

RAW_SYSTEM = "You are a helpful accounting assistant."


def load_cases(limit=None):
    files = sorted(CASES_DIR.glob("case_*.json"))
    cases = [json.loads(f.read_text()) for f in files]
    return cases[:limit] if limit else cases


def build_prompt(case: dict) -> str:
    return (
        "Reconcile this bank statement against the general ledger cash account.\n\n"
        f"period_end: {case['period_end']}\n\n"
        f"bank_statement:\n{json.dumps(case['bank'], indent=1)}\n\n"
        f"ledger:\n{json.dumps(case['ledger'], indent=1)}\n\n"
        "Reply with ONLY a JSON object with these keys:\n"
        '  "matched": list of [bank_id, ledger_id] pairs\n'
        '  "unmatched_bank": list of bank ids\n'
        '  "unmatched_ledger": list of ledger ids\n'
        '  "flags": list of {"type": <flag type>, "ids": [ids]}\n'
        f"Flag types: {', '.join(FLAG_TYPES)}."
    )


# ---- offline solvers (harness checks only; these are not Claude) -----------
def solve_reference(case):
    return reconcile(case["bank"], case["ledger"], case["period_end"])


def solve_naive(case):
    """Exact amount match only: no dates, no references, no flags."""
    used, matched = set(), []
    for l in sorted(case["ledger"], key=lambda t: id_key(t["id"])):
        for b in sorted(case["bank"], key=lambda t: id_key(t["id"])):
            if b["id"] not in used and round(b["amount"], 2) == round(l["amount"], 2):
                used.add(b["id"])
                matched.append([b["id"], l["id"]])
                break
    mb = {p[0] for p in matched}
    ml = {p[1] for p in matched}
    return canonical({
        "matched": matched,
        "unmatched_bank": [b["id"] for b in case["bank"] if b["id"] not in mb],
        "unmatched_ledger": [l["id"] for l in case["ledger"] if l["id"] not in ml],
        "flags": [],
    })


# ---- online solver ----------------------------------------------------------
def make_claude_solver(mode: str, model: str):
    try:
        import anthropic
    except ImportError:
        sys.exit("Install dependencies first: pip install -r requirements.txt")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        try:
            from dotenv import load_dotenv
            load_dotenv(ROOT / ".env")
        except ImportError:
            pass
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set. Export it or put it in .env (never paste it in code or chat).")

    client = anthropic.Anthropic()
    system = SKILL_PATH.read_text() if mode == "skill" else RAW_SYSTEM

    def solve(case):
        last_err = None
        for attempt in range(3):
            try:
                resp = client.messages.create(
                    model=model,
                    max_tokens=4096,
                    system=system,
                    messages=[{"role": "user", "content": build_prompt(case)}],
                )
                text = "".join(b.text for b in resp.content if b.type == "text")
                return parse_model_json(text)
            except Exception as e:  # network / rate limit: retry with backoff
                last_err = e
                time.sleep(2 * (attempt + 1))
        print(f"  ! API failed for {case['case_id']}: {last_err}")
        return None

    return solve


# ---- run + report -----------------------------------------------------------
def run(label: str, solve, cases):
    rows = []
    for case in cases:
        pred = solve(case)
        s = score_case(pred, case["expected"])
        rows.append({"case_id": case["case_id"], "name": case["name"], "trap": case["trap"], **s, "prediction": pred})
        print(f"  {case['case_id']:8s} {case['name']:32s} {'PASS' if s['exact'] else 'FAIL'}{'  (trap)' if case['trap'] else ''}")
    n = len(rows)
    traps = [r for r in rows if r["trap"]]
    summary = {
        "label": label,
        "cases": n,
        "exact_pass": sum(r["exact"] for r in rows),
        "accuracy": sum(r["exact"] for r in rows) / n,
        "trap_cases": len(traps),
        "trap_pass": sum(r["exact"] for r in traps),
        "avg_pairs_f1": sum(r["pairs_f1"] for r in rows) / n,
        "avg_flags_f1": sum(r["flags_f1"] for r in rows) / n,
    }
    return summary, rows


def print_summary(summaries):
    print("\n| run | exact pass | accuracy | trap cases passed | pairs F1 | flags F1 |")
    print("|---|---|---|---|---|---|")
    for s in summaries:
        print(f"| {s['label']} | {s['exact_pass']}/{s['cases']} | {s['accuracy']:.0%} | "
              f"{s['trap_pass']}/{s['trap_cases']} | {s['avg_pairs_f1']:.2f} | {s['avg_flags_f1']:.2f} |")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["raw", "skill", "both"], default="both")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--offline", choices=["reference", "naive"], help="harness self-check without the API")
    ap.add_argument("--limit", type=int, help="only run the first N cases")
    args = ap.parse_args()

    cases = load_cases(args.limit)
    runs = []
    if args.offline:
        solver = solve_reference if args.offline == "reference" else solve_naive
        runs.append((f"offline-{args.offline}", solver))
    else:
        modes = ["raw", "skill"] if args.mode == "both" else [args.mode]
        for m in modes:
            runs.append((f"{m} ({args.model})", make_claude_solver(m, args.model)))

    summaries, all_rows = [], {}
    for label, solver in runs:
        print(f"\n== {label} ==")
        summary, rows = run(label, solver, cases)
        summaries.append(summary)
        all_rows[label] = rows
    print_summary(summaries)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"run_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps({"summaries": summaries, "rows": all_rows}, indent=2))
    print(f"\nSaved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
