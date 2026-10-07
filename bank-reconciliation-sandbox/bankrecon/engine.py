"""Deterministic reference implementation of the reconciliation rules.

This engine mirrors the rules written in
.claude/skills/bank-reconciliation/SKILL.md. It is used:
  * by the MCP server tools (so Claude gets reliable matching),
  * by the tests, to confirm the golden dataset is internally consistent.

Transactions are dicts: {id, date (YYYY-MM-DD), description, amount, reference}.
Bank ids look like "B1", ledger ids like "L1".
"""
from __future__ import annotations

import re
from datetime import date

DATE_TOLERANCE_DAYS = 3
OUTSTANDING_WINDOW_DAYS = 5
FEE_KEYWORDS = ("fee", "charge", "interest")
FLAG_TYPES = (
    "OUTSTANDING",
    "MISSING_IN_BANK",
    "BANK_ONLY",
    "UNRECORDED_BANK_ITEM",
    "DUPLICATE_LEDGER",
    "DUPLICATE_BANK",
    "SIGN_ERROR",
    "AMOUNT_MISMATCH",
)


def id_key(txn_id: str):
    return (txn_id[0], int(txn_id[1:]))


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _ref(text: str) -> str:
    return (text or "").strip().upper()


def _day(text: str) -> date:
    return date.fromisoformat(text)


def _cents(amount) -> int:
    return int(round(float(amount) * 100))


def _gap(a: dict, b: dict) -> int:
    return abs((_day(a["date"]) - _day(b["date"])).days)


def _sig(t: dict):
    return (t["date"], _cents(t["amount"]), _norm(t["description"]))


def canonical(result: dict) -> dict:
    """Sort and normalise a result so two results can be compared with ==."""
    return {
        "matched": sorted(
            ([b, l] for b, l in result["matched"]),
            key=lambda p: (id_key(p[0]), id_key(p[1])),
        ),
        "unmatched_bank": sorted(set(result["unmatched_bank"]), key=id_key),
        "unmatched_ledger": sorted(set(result["unmatched_ledger"]), key=id_key),
        "flags": sorted(
            (
                {"type": f["type"], "ids": sorted(f["ids"], key=id_key)}
                for f in result["flags"]
            ),
            key=lambda f: (f["type"], [id_key(i) for i in f["ids"]]),
        ),
    }


def reconcile(bank: list, ledger: list, period_end: str) -> dict:
    pe = _day(period_end)
    bank = sorted(bank, key=lambda t: id_key(t["id"]))
    ledger = sorted(ledger, key=lambda t: id_key(t["id"]))
    b_by = {t["id"]: t for t in bank}
    l_by = {t["id"]: t for t in ledger}

    matched: list = []
    flags: list = []
    used_b: set = set()  # matched or flagged
    used_l: set = set()
    matched_b: set = set()
    matched_l: set = set()

    def do_match(b, l):
        matched.append((b["id"], l["id"]))
        used_b.add(b["id"])
        used_l.add(l["id"])
        matched_b.add(b["id"])
        matched_l.add(l["id"])

    def do_flag(kind, *txns):
        flags.append({"type": kind, "ids": [t["id"] for t in txns]})
        for t in txns:
            (used_b if t["id"][0] == "B" else used_l).add(t["id"])

    # Rules 4-7: reference numbers take priority, regardless of date.
    for l in ledger:
        if not _ref(l.get("reference")):
            continue
        for b in bank:
            if b["id"] in used_b or _ref(b.get("reference")) != _ref(l["reference"]):
                continue
            lc, bc = _cents(l["amount"]), _cents(b["amount"])
            if lc == bc:
                do_match(b, l)
            elif lc == -bc:
                do_flag("SIGN_ERROR", b, l)
            else:
                do_flag("AMOUNT_MISMATCH", b, l)
            break

    # Rules 8-10: exact amount, date within tolerance, closest date wins.
    for l in ledger:
        if l["id"] in used_l:
            continue
        best = None
        for b in bank:
            if b["id"] in used_b or _cents(b["amount"]) != _cents(l["amount"]):
                continue
            gap = _gap(b, l)
            if gap > DATE_TOLERANCE_DAYS:
                continue
            key = (gap, id_key(b["id"]))
            if best is None or key < best[0]:
                best = (key, b)
        if best:
            do_match(best[1], l)

    # Rule 11: duplicates of an already matched entry on the same side.
    l_sigs = {_sig(l_by[i]) for i in matched_l}
    for l in ledger:
        if l["id"] not in used_l and _sig(l) in l_sigs:
            do_flag("DUPLICATE_LEDGER", l)
    b_sigs = {_sig(b_by[i]) for i in matched_b}
    for b in bank:
        if b["id"] not in used_b and _sig(b) in b_sigs:
            do_flag("DUPLICATE_BANK", b)

    # Rule 12: sign errors without a reference number.
    for l in ledger:
        if l["id"] in used_l:
            continue
        for b in bank:
            if b["id"] in used_b:
                continue
            if (
                _cents(b["amount"]) == -_cents(l["amount"])
                and _gap(b, l) <= DATE_TOLERANCE_DAYS
                and _norm(b["description"]) == _norm(l["description"])
            ):
                do_flag("SIGN_ERROR", b, l)
                break

    # Rule 13: remaining bank items.
    for b in bank:
        if b["id"] in used_b:
            continue
        desc = _norm(b["description"])
        kind = "BANK_ONLY" if any(k in desc for k in FEE_KEYWORDS) else "UNRECORDED_BANK_ITEM"
        do_flag(kind, b)

    # Rule 14: remaining ledger items.
    for l in ledger:
        if l["id"] in used_l:
            continue
        near_end = (pe - _day(l["date"])).days <= OUTSTANDING_WINDOW_DAYS
        do_flag("OUTSTANDING" if near_end else "MISSING_IN_BANK", l)

    return canonical(
        {
            "matched": matched,
            "unmatched_bank": [b["id"] for b in bank if b["id"] not in matched_b],
            "unmatched_ledger": [l["id"] for l in ledger if l["id"] not in matched_l],
            "flags": flags,
        }
    )
