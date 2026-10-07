"""MCP server exposing four reconciliation tools to Claude.

Run (stdio):  python -m bankrecon.mcp_server

Client data lives in  <CLIENT_DATA_ROOT>/<client>/<file>.json  (default: data/clients).
Each tool takes a client name and a file name, and the path is resolved inside
that client's folder only. Names are validated and path traversal is rejected,
so a request for one client can never read another client's folder.

The server needs no API keys. Credentials for the eval harness are read from
environment variables (see .env.example), never from code or prompts.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .engine import reconcile

ROOT = Path(os.environ.get("CLIENT_DATA_ROOT", Path(__file__).resolve().parent.parent / "data" / "clients")).resolve()
mcp = FastMCP("bank-reconciliation")

SUGGESTED_ACTION = {
    "BANK_ONLY": "Record the bank fee/interest in the ledger.",
    "UNRECORDED_BANK_ITEM": "Investigate and record the missing ledger entry.",
    "OUTSTANDING": "Timing difference. Expect it to clear next period.",
    "MISSING_IN_BANK": "Stale item. Confirm it was actually paid or received.",
    "DUPLICATE_LEDGER": "Likely a double posting. Reverse the duplicate entry.",
    "DUPLICATE_BANK": "Possible double charge by the bank. Contact the bank.",
    "SIGN_ERROR": "Ledger entry has the wrong sign. Correct the entry.",
    "AMOUNT_MISMATCH": "Amounts differ for the same reference. Check for a keying error.",
}


def _resolve(client: str, filename: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", client or ""):
        raise ValueError("Invalid client name.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.json", filename or ""):
        raise ValueError("Invalid file name.")
    client_dir = (ROOT / client).resolve()
    path = (client_dir / filename).resolve()
    if client_dir.parent != ROOT or client_dir not in path.parents:
        raise ValueError("Path is outside the client folder.")
    if not path.is_file():
        raise FileNotFoundError(f"No file {filename} for client {client}.")
    return path


def _load(client: str, filename: str) -> dict:
    return json.loads(_resolve(client, filename).read_text())


@mcp.tool()
def load_transactions(client: str, filename: str) -> dict:
    """Load a client's bank statement and ledger for one period."""
    data = _load(client, filename)
    return {
        "client": client,
        "period_end": data["period_end"],
        "bank_count": len(data["bank"]),
        "ledger_count": len(data["ledger"]),
        "bank": data["bank"],
        "ledger": data["ledger"],
    }


@mcp.tool()
def match_transactions(client: str, filename: str) -> dict:
    """Match bank and ledger entries using the reconciliation rules."""
    d = _load(client, filename)
    r = reconcile(d["bank"], d["ledger"], d["period_end"])
    return {"matched": r["matched"], "matched_count": len(r["matched"])}


@mcp.tool()
def find_discrepancies(client: str, filename: str) -> dict:
    """List unmatched entries and flags (fees, duplicates, sign errors, ...)."""
    d = _load(client, filename)
    r = reconcile(d["bank"], d["ledger"], d["period_end"])
    return {k: r[k] for k in ("unmatched_bank", "unmatched_ledger", "flags")}


@mcp.tool()
def generate_report(client: str, filename: str) -> str:
    """Generate a markdown reconciliation report for accountant review."""
    d = _load(client, filename)
    r = reconcile(d["bank"], d["ledger"], d["period_end"])
    by_id = {t["id"]: t for t in d["bank"] + d["ledger"]}
    lines = [
        f"# Bank reconciliation: {client}",
        f"Period end: {d['period_end']}",
        f"Matched: {len(r['matched'])} | Exceptions: {len(r['flags'])}",
        "",
        "## Matched",
        "| Bank | Ledger | Amount | Description |",
        "|---|---|---|---|",
    ]
    for b, l in r["matched"]:
        lines.append(f"| {b} | {l} | {by_id[b]['amount']:.2f} | {by_id[l]['description']} |")
    lines += ["", "## Exceptions for review", "| Flag | Items | Amount | Suggested action |", "|---|---|---|---|"]
    for f in r["flags"]:
        amts = ", ".join(f"{by_id[i]['amount']:.2f}" for i in f["ids"])
        lines.append(f"| {f['type']} | {', '.join(f['ids'])} | {amts} | {SUGGESTED_ACTION[f['type']]} |")
    lines += ["", "_First draft generated for accountant review. Not a final reconciliation._"]
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
