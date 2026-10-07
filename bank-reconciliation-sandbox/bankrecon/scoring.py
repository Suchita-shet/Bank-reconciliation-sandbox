"""Scoring for the eval harness: compare a model answer to the golden output."""
from __future__ import annotations

import json
import re

from .engine import id_key


def parse_model_json(text: str):
    """Extract the first JSON object from a model reply. Returns dict or None."""
    if not text:
        return None
    text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _to_sets(out: dict):
    try:
        pairs = {(p[0], p[1]) for p in out["matched"]}
        ub = set(out["unmatched_bank"])
        ul = set(out["unmatched_ledger"])
        flags = {
            (f["type"], tuple(sorted(f["ids"], key=id_key))) for f in out["flags"]
        }
        return pairs, ub, ul, flags
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def _f1(pred: set, gold: set) -> float:
    if not pred and not gold:
        return 1.0
    tp = len(pred & gold)
    if tp == 0:
        return 0.0
    p, r = tp / len(pred), tp / len(gold)
    return 2 * p * r / (p + r)


def score_case(pred, expected: dict) -> dict:
    """Exact = every part of the answer equals the golden output."""
    gold = _to_sets(expected)
    got = _to_sets(pred) if isinstance(pred, dict) else None
    if got is None:
        return {"exact": False, "pairs_f1": 0.0, "flags_f1": 0.0, "parse_ok": False}
    return {
        "exact": got == gold,
        "pairs_f1": _f1(got[0], gold[0]),
        "flags_f1": _f1(got[3], gold[3]),
        "parse_ok": True,
    }
