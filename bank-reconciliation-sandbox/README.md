# Claude AI Solutions Sandbox: Bank Reconciliation Skill + Eval Suite

A small, Claude-native project for one finance process, **bank reconciliation**, built the way
an AI-native finance team would build it:

- a **Claude Skill** (`SKILL.md`) that encodes the reconciliation rules,
- a `CLAUDE.md` that routes work and sets data rules,
- a **golden dataset** (20 synthetic cases, 5 of them trap cases) with the expected answer for each,
- an **eval harness** that scores **raw Claude vs Claude + Skill** against that dataset,
- an **MCP server** with 4 tools, with per-client data folders and no secrets in code,
- a **Docker sandbox** to run it in.

All data is synthetic. No real client data is used.

## Layout

```
CLAUDE.md                                  routing + data rules
.claude/skills/bank-reconciliation/SKILL.md  the skill (17 rules)
bankrecon/engine.py                        deterministic reference implementation of the rules
bankrecon/scoring.py                       answer parsing + scoring
bankrecon/mcp_server.py                    MCP server (4 tools)
scripts/generate_cases.py                  builds the golden dataset
evals/cases/                               20 golden cases (5 trap cases)
evals/run_eval.py                          raw vs skill benchmark
data/clients/<client>/                     per-client folders used by the MCP tools
MEASUREMENT.md                             how to measure time saved
tests/                                     pytest suite
Dockerfile, .mcp.json, .env.example
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

pytest -q                                   # engine matches golden data, MCP path safety, scoring
python evals/run_eval.py --offline reference   # harness self-check, no API: should be 100%
python evals/run_eval.py --offline naive       # weak solver: should score low

cp .env.example .env                        # then put your key in .env
python evals/run_eval.py --mode both        # raw Claude vs Claude + skill (needs API key)
```

The `--offline` modes only check that the harness works. **They are not Claude results.**
Your before/after numbers come from `--mode both`. Open `evals/results/*.json` to see every
model answer, then read the failures. That is where the learning is.

## How the benchmark is fair (and where it isn't)

Raw and skill runs get the same task, the same JSON output schema and the same flag names.
Only the skill run also gets the rules in `SKILL.md` (the harness loads the file as the system
prompt; in Claude Code it loads automatically from `.claude/skills/`). So the gap measures
the value of the rules. It is a small synthetic benchmark, so treat it as a demonstration of
method, not a general claim about Claude.

## Improving the skill (hill-climbing)

1. Run `--mode skill`, open the results file, find a failing case.
2. Work out which rule was missing or ambiguous in `SKILL.md`.
3. Edit the skill, rerun, and note the score change. Keep a short log of iterations.
4. If you change a rule, change `bankrecon/engine.py` and the affected golden cases together,
   then run `pytest`. Never edit golden answers just to raise a score.

## MCP server

```bash
python -m bankrecon.mcp_server        # stdio server
```

Tools: `load_transactions`, `match_transactions`, `find_discrepancies`, `generate_report`.
Each takes `(client, filename)` and can only read inside `data/clients/<client>/`.
Names are validated and `../` tricks are rejected (tested in `tests/`).
`.mcp.json` registers it for Claude Code. If you use a virtualenv, change `"python"` to the
full path of your venv's python.

## Docker sandbox

```bash
docker build -t bank-recon-sandbox .

# MCP server, read-only filesystem, no extra privileges, client data mounted read-only
docker run --rm -i --read-only --cap-drop ALL \
  -v "$PWD/data/clients:/app/data/clients:ro" bank-recon-sandbox

# Evals, key passed at runtime from .env (never baked into the image)
docker run --rm --env-file .env --read-only --cap-drop ALL \
  -v "$PWD/evals/results:/app/evals/results" bank-recon-sandbox \
  python evals/run_eval.py --mode both
```

Docker isolates the runtime environment. It does not by itself separate one client from another;
that separation here comes from the per-client folders and the MCP path checks.

## Things to know before you rely on this

- **The 17 rules are my encoding of standard reconciliation practice, not a practicing accountant's.**
  The real method is to interview a domain expert and encode how they work. Do a mock interview
  with someone who knows accounting, then add or change rules and golden cases accordingly.
- **The numbers are yours to produce.** Run the evals and use the scores you actually get, even if
  they are less impressive than you hoped. Measure time saved with `MEASUREMENT.md` or don't claim it.
- The default model id in `evals/run_eval.py` is `claude-sonnet-5-5`. If your account uses a
  different id, pass `--model`.
- I could not run the Docker build or the live API evals when preparing this repo. Tests, the offline
  harness checks and a stdio smoke test of the MCP server were run.
- Be ready to explain every file. Reading `engine.py` and `generate_cases.py` closely, and adding a
  rule or a trap case of your own, is the best preparation.
