"""Generate the synthetic golden dataset (20 cases, 5 trap cases).

The expected output of every case is recorded *by construction* while the
transactions are being built. It is NOT computed by bankrecon.engine, so
tests/test_engine.py can cross-check the engine against the golden data.
All data is synthetic. No real client data is used.

Usage:  python scripts/generate_cases.py
"""
from __future__ import annotations

import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bankrecon.engine import canonical, id_key, reconcile  # noqa: E402

PERIOD_END = "2025-03-31"
VENDORS = [
    "Acme Supplies", "Brightway Logistics", "Cedar Office Rentals", "Delta Software",
    "Evergreen Utilities", "Falcon Travel", "Granite Legal", "Harbor Insurance",
    "Ionic Marketing", "Juniper Payroll", "Keystone Telecom", "Lumen Print",
]
CUSTOMERS = ["Northwind Retail", "Orion Health", "Pioneer Foods", "Quartz Labs", "Redwood Studios"]


def shift(day: str, delta: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=delta)).isoformat()


class Case:
    def __init__(self, num: int, name: str, trap: bool = False, note: str = ""):
        self.num, self.name, self.trap, self.note = num, name, trap, note
        self.rng = random.Random(1000 + num)
        self.bank, self.ledger = [], []
        self.exp = {"matched": [], "unmatched_bank": [], "unmatched_ledger": [], "flags": []}
        self._used = set()

    # -- helpers -----------------------------------------------------------
    def amount(self, lo=80, hi=9000, sign=1) -> float:
        while True:
            v = round(self.rng.uniform(lo, hi), 2)
            if v not in self._used:
                self._used.add(v)
                return round(sign * v, 2)

    def day(self, lo=3, hi=22) -> str:
        return f"2025-03-{self.rng.randint(lo, hi):02d}"

    def vendor(self) -> str:
        return self.rng.choice(VENDORS)

    def _b(self, d, desc, amt, ref=""):
        tid = f"B{len(self.bank) + 1}"
        self.bank.append({"id": tid, "date": d, "description": desc, "amount": amt, "reference": ref})
        return tid

    def _l(self, d, desc, amt, ref=""):
        tid = f"L{len(self.ledger) + 1}"
        self.ledger.append({"id": tid, "date": d, "description": desc, "amount": amt, "reference": ref})
        return tid

    def _flag(self, kind, *ids):
        self.exp["flags"].append({"type": kind, "ids": list(ids)})

    # -- scenario builders (each records its own expected result) ----------
    def matched(self, desc=None, amt=None, ldate=None, lag=0, ref="", bdesc=None, bref=None):
        desc = desc or f"Payment {self.vendor()}"
        amt = amt if amt is not None else self.amount(sign=self.rng.choice([1, -1]))
        ldate = ldate or self.day()
        l = self._l(ldate, desc, amt, ref)
        b = self._b(shift(ldate, lag), bdesc or desc, amt, ref if bref is None else bref)
        self.exp["matched"].append([b, l])

    def outstanding(self, desc=None, amt=None, ldate=None):
        l = self._l(ldate or self.day(27, 31), desc or f"Cheque {self.vendor()}", amt if amt is not None else self.amount(sign=-1))
        self.exp["unmatched_ledger"].append(l)
        self._flag("OUTSTANDING", l)

    def missing_in_bank(self, desc=None, amt=None, ldate=None):
        l = self._l(ldate or self.day(3, 12), desc or f"Payment {self.vendor()}", amt if amt is not None else self.amount(sign=-1))
        self.exp["unmatched_ledger"].append(l)
        self._flag("MISSING_IN_BANK", l)

    def bank_only(self, desc, amt, bdate=None):
        b = self._b(bdate or self.day(25, 31), desc, amt)
        self.exp["unmatched_bank"].append(b)
        self._flag("BANK_ONLY", b)

    def unrecorded_bank(self, desc=None, amt=None, bdate=None):
        b = self._b(bdate or self.day(), desc or f"Deposit {self.rng.choice(CUSTOMERS)}", amt if amt is not None else self.amount())
        self.exp["unmatched_bank"].append(b)
        self._flag("UNRECORDED_BANK_ITEM", b)

    def duplicate_ledger(self, desc=None, amt=None, ldate=None, lag=1):
        desc = desc or f"Payment {self.vendor()}"
        amt = amt if amt is not None else self.amount(sign=-1)
        ldate = ldate or self.day()
        l1 = self._l(ldate, desc, amt)
        b = self._b(shift(ldate, lag), desc, amt)
        l2 = self._l(ldate, desc, amt)
        self.exp["matched"].append([b, l1])
        self.exp["unmatched_ledger"].append(l2)
        self._flag("DUPLICATE_LEDGER", l2)

    def duplicate_bank(self, desc=None, amt=None, ldate=None, lag=1):
        desc = desc or f"Deposit {self.rng.choice(CUSTOMERS)}"
        amt = amt if amt is not None else self.amount()
        ldate = ldate or self.day()
        l = self._l(ldate, desc, amt)
        b1 = self._b(shift(ldate, lag), desc, amt)
        b2 = self._b(shift(ldate, lag), desc, amt)
        self.exp["matched"].append([b1, l])
        self.exp["unmatched_bank"].append(b2)
        self._flag("DUPLICATE_BANK", b2)

    def sign_error(self, desc=None, amt=None, d=None, lag=1, ref=""):
        desc = desc or f"Payment {self.vendor()}"
        amt = amt if amt is not None else self.amount()
        d = d or self.day()
        l = self._l(d, desc, amt, ref)          # ledger recorded with the wrong sign
        b = self._b(shift(d, lag), desc, -amt, ref)
        self.exp["unmatched_bank"].append(b)
        self.exp["unmatched_ledger"].append(l)
        self._flag("SIGN_ERROR", b, l)

    def amount_mismatch(self, desc, ledger_amt, bank_amt, d, ref):
        l = self._l(d, desc, ledger_amt, ref)
        b = self._b(shift(d, 2), desc, bank_amt, ref)
        self.exp["unmatched_bank"].append(b)
        self.exp["unmatched_ledger"].append(l)
        self._flag("AMOUNT_MISMATCH", b, l)

    def outside_tolerance(self, desc, amt, ldate, gap):
        """Same amount, but dates too far apart: must NOT be matched."""
        l = self._l(ldate, desc, amt)
        b = self._b(shift(ldate, gap), desc, amt)
        self.exp["unmatched_ledger"].append(l)
        self.exp["unmatched_bank"].append(b)
        self._flag("MISSING_IN_BANK", l)
        self._flag("UNRECORDED_BANK_ITEM", b)

    # -- output -------------------------------------------------------------
    def to_dict(self):
        return {
            "case_id": f"case_{self.num:02d}",
            "name": self.name,
            "trap": self.trap,
            "note": self.note,
            "period_end": PERIOD_END,
            "bank": self.bank,
            "ledger": self.ledger,
            "expected": canonical(self.exp),
        }


def build_cases():
    cases = []

    c = Case(1, "clean_all_match", note="Everything matches on the same day.")
    for _ in range(6):
        c.matched()
    cases.append(c)

    c = Case(2, "bank_fee_and_interest", note="Fee and interest appear only on the bank statement.")
    for _ in range(4):
        c.matched()
    c.bank_only("Monthly service fee", -25.00)
    c.bank_only("Interest earned", c.amount(1, 40))
    cases.append(c)

    c = Case(3, "outstanding_cheques", note="Two cheques issued at month end have not cleared.")
    for _ in range(4):
        c.matched()
    c.outstanding(ldate="2025-03-28")
    c.outstanding(ldate="2025-03-30")
    cases.append(c)

    c = Case(4, "deposit_in_transit", note="A deposit recorded on the last day is not on the statement yet.")
    for _ in range(4):
        c.matched()
    c.outstanding(desc="Deposit Northwind Retail", amt=c.amount(2000, 6000), ldate="2025-03-31")
    cases.append(c)

    c = Case(5, "date_lag_within_tolerance", note="Bank clears 0 to 3 days after the ledger date.")
    for lag in (0, 1, 2, 3, 3):
        c.matched(lag=lag)
    cases.append(c)

    c = Case(6, "same_amount_closest_date", note="Two same-amount pairs: ledger order and closest date decide.")
    l1 = c._l("2025-03-05", "Rent Cedar Office Rentals", -500.00)
    l2 = c._l("2025-03-07", "Rent Cedar Office Rentals", -500.00)
    b1 = c._b("2025-03-07", "Rent Cedar Office Rentals", -500.00)
    b2 = c._b("2025-03-08", "Rent Cedar Office Rentals", -500.00)
    c.exp["matched"] += [[b1, l1], [b2, l2]]
    for _ in range(2):
        c.matched()
    cases.append(c)

    c = Case(7, "reference_priority", note="Cheque cleared 10 days late; the reference number links them.")
    c.matched(desc="Cheque 1042 Granite Legal", amt=c.amount(1000, 3000, -1), ldate="2025-03-05", lag=10, ref="CHQ1042")
    for _ in range(3):
        c.matched()
    cases.append(c)

    c = Case(8, "unrecorded_bank_deposit", note="Customer paid directly; nothing in the ledger yet.")
    for _ in range(4):
        c.matched()
    c.unrecorded_bank(desc="Deposit Quartz Labs", amt=c.amount(1500, 4000))
    cases.append(c)

    c = Case(9, "mixed_month_end", note="A realistic mix of matched and unmatched items.")
    for lag in (0, 1, 0, 2, 1, 0, 3, 1):
        c.matched(lag=lag)
    c.bank_only("Wire transfer fee", -15.00)
    c.bank_only("Interest earned", c.amount(1, 40))
    c.outstanding(ldate="2025-03-29")
    c.outstanding(desc="Deposit Pioneer Foods", amt=c.amount(1000, 5000), ldate="2025-03-31")
    c.unrecorded_bank(desc="Deposit Redwood Studios")
    cases.append(c)

    c = Case(10, "larger_volume", note="30 bank lines with a handful of exceptions.")
    for i in range(25):
        c.matched(lag=i % 4)
    c.bank_only("Account maintenance charge", -30.00)
    c.outstanding(ldate="2025-03-27")
    c.unrecorded_bank()
    c.missing_in_bank()
    c.matched(lag=1)
    cases.append(c)

    c = Case(11, "money_out_only", note="Payments (negative amounts) with mixed lags.")
    for lag in (0, 1, 2, 0, 3):
        c.matched(amt=c.amount(sign=-1), lag=lag)
    cases.append(c)

    c = Case(12, "descriptions_differ", note="Bank descriptions differ from ledger wording; amount and date still decide.")
    c.matched(desc="Payment Acme Supplies", bdesc="ACH DEBIT ACME SUPP 0331", lag=1)
    c.matched(desc="Deposit Orion Health", bdesc="DEP ORION HLTH", lag=0)
    c.matched(desc="Payment Delta Software", bdesc="CARD 4412 DELTASOFT", lag=2)
    c.matched()
    cases.append(c)

    # ---- 5 trap cases ----------------------------------------------------
    c = Case(13, "trap_duplicate_ledger", trap=True, note="Ledger entry posted twice; bank shows it once.")
    for _ in range(3):
        c.matched()
    c.duplicate_ledger(desc="Payment Keystone Telecom", amt=c.amount(300, 900, -1))
    cases.append(c)

    c = Case(14, "trap_duplicate_bank", trap=True, note="Bank charged the same deposit twice.")
    for _ in range(3):
        c.matched()
    c.duplicate_bank(desc="Deposit Northwind Retail", amt=c.amount(800, 2500))
    cases.append(c)

    c = Case(15, "trap_sign_error", trap=True, note="Payment recorded as money in. Same amount, opposite sign.")
    for _ in range(3):
        c.matched()
    c.sign_error(desc="Payment Harbor Insurance", amt=c.amount(400, 1500))
    cases.append(c)

    c = Case(16, "trap_missing_in_bank", trap=True, note="Old ledger payment never reached the bank. Not just timing.")
    for _ in range(3):
        c.matched()
    c.missing_in_bank(desc="Payment Ionic Marketing", ldate="2025-03-04")
    cases.append(c)

    c = Case(17, "trap_amount_transposition", trap=True, note="Digits transposed: 1,234.56 recorded as 1,243.56. Reference links them.")
    for _ in range(3):
        c.matched()
    c.amount_mismatch("Cheque 2210 Juniper Payroll", -1234.56, -1243.56, "2025-03-12", "CHQ2210")
    cases.append(c)

    # ---- edge / composite cases ------------------------------------------
    c = Case(18, "date_tolerance_boundary", note="Gap of 3 days matches; gap of 4 does not.")
    c.matched(lag=3)
    c.outside_tolerance("Payment Lumen Print", c.amount(500, 2000, -1), "2025-03-10", 4)
    c.matched()
    cases.append(c)

    c = Case(19, "outstanding_window_boundary", note="5 days before period end is outstanding; 6 days is not.")
    c.matched()
    c.outstanding(ldate="2025-03-26")        # 5 days before 03-31 -> OUTSTANDING
    c.missing_in_bank(ldate="2025-03-25")    # 6 days before -> MISSING_IN_BANK
    cases.append(c)

    c = Case(20, "composite_month_end", note="Every exception type in one month.")
    for lag in (0, 1, 2):
        c.matched(lag=lag)
    c.matched(desc="Cheque 3301 Evergreen Utilities", amt=c.amount(500, 1500, -1), ldate="2025-03-06", lag=9, ref="CHQ3301")
    c.bank_only("Monthly service fee", -25.00)
    c.outstanding(ldate="2025-03-30")
    c.missing_in_bank()
    c.unrecorded_bank()
    c.duplicate_ledger()
    c.sign_error(ref="INV7788", desc="Invoice 7788 Falcon Travel")
    cases.append(c)

    return cases


def main():
    out_dir = ROOT / "evals" / "cases"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("case_*.json"):
        old.unlink()

    cases = build_cases()
    bad = 0
    for c in cases:
        d = c.to_dict()
        # internal consistency: every id is accounted for exactly once
        ids = {t["id"] for t in d["bank"] + d["ledger"]}
        seen = [i for pair in d["expected"]["matched"] for i in pair]
        seen += d["expected"]["unmatched_bank"] + d["expected"]["unmatched_ledger"]
        assert sorted(seen, key=id_key) == sorted(ids, key=id_key), f"{d['case_id']}: ids not covered once"
        got = reconcile(d["bank"], d["ledger"], d["period_end"])
        if got != d["expected"]:
            bad += 1
            print(f"MISMATCH engine vs golden: {d['case_id']} {d['name']}")
        (out_dir / f"{d['case_id']}_{d['name']}.json").write_text(json.dumps(d, indent=2) + "\n")

    # Demo client folders for the MCP server (no expected answers inside).
    for client, case_no in (("demo_client_a", 9), ("demo_client_b", 20)):
        d = cases[case_no - 1].to_dict()
        payload = {"period_end": d["period_end"], "bank": d["bank"], "ledger": d["ledger"]}
        (ROOT / "data" / "clients" / client / "2025-03.json").write_text(json.dumps(payload, indent=2) + "\n")

    traps = sum(1 for c in cases if c.trap)
    print(f"Wrote {len(cases)} cases ({traps} trap cases). Engine/golden mismatches: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
