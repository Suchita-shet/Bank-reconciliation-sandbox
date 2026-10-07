import json
from pathlib import Path

import pytest

from bankrecon import mcp_server
from bankrecon.engine import reconcile
from bankrecon.scoring import parse_model_json, score_case

CASES = sorted((Path(__file__).resolve().parent.parent / "evals" / "cases").glob("case_*.json"))


def test_dataset_shape():
    assert len(CASES) == 20
    traps = [json.loads(f.read_text())["trap"] for f in CASES]
    assert sum(traps) == 5


@pytest.mark.parametrize("path", CASES, ids=[p.stem for p in CASES])
def test_engine_matches_golden(path):
    case = json.loads(path.read_text())
    assert reconcile(case["bank"], case["ledger"], case["period_end"]) == case["expected"]


def test_scoring_detects_wrong_answer():
    case = json.loads(CASES[0].read_text())
    assert score_case(case["expected"], case["expected"])["exact"]
    wrong = dict(case["expected"], matched=[])
    assert not score_case(wrong, case["expected"])["exact"]
    assert not score_case(None, case["expected"])["parse_ok"]


def test_parse_model_json_handles_fences():
    assert parse_model_json('Here:\n```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_model_json("no json here") is None


@pytest.mark.parametrize("client,name", [
    ("../demo_client_a", "2025-03.json"),
    ("demo_client_a", "../demo_client_b/2025-03.json"),
    ("demo_client_a", "..%2f2025-03.json"),
    ("", "2025-03.json"),
    ("demo_client_a", "notes.txt"),
])
def test_mcp_blocks_path_traversal(client, name):
    with pytest.raises(ValueError):
        mcp_server.load_transactions(client, name)


def test_mcp_tools_work_per_client():
    assert mcp_server.load_transactions("demo_client_a", "2025-03.json")["bank_count"] > 0
    assert mcp_server.match_transactions("demo_client_b", "2025-03.json")["matched_count"] > 0
    assert mcp_server.find_discrepancies("demo_client_a", "2025-03.json")["flags"]
    assert "Exceptions for review" in mcp_server.generate_report("demo_client_b", "2025-03.json")
