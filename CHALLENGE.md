# Day 2: Agentic chaos on the fault bank
**Goal:** an AI that picks experiments from the fault bank and the map, runs them safely (a person
approves each run), explains what broke and how to fix it, and scores resilience without
rewarding "break everything". Statement: `docs/hackathon-problem-statement.md`.
**Success criterion:** one agent session over a person-picked pool (kill switch active, each run approved):
1. **≥3 distinct root causes** rated ≥ medium, each found by a mild or targeted fault, ranked by
   leverage, each with a fix and the run file it cites.
2. **One fix verified:** the same fault re-run after the fix is ≥1 tier lower, and the pool's
   resilience score goes up.
3. **Calibration:** both known-answer controls pass the same day.

- Baseline: Day 1 had no AI ranking and no verified fix.

**Repro:** `uv run python agent.py --pool <ids> --budget 8` (Arch box). On any laptop: `--replay bank.json`
**Rubric:** none supplied. Day-2 checklist: AI planner (map-based, with reasons) · ≥3 failure types run ·
AI findings ranked + fixes + score · stretch: re-run after a fix, live UI, combined failures · 5 deliverables

**Start:** S, then feature freeze S+5:30, code freeze S+7:00, submit S+9:00 (aim 30 min early)

## Two scores, never mixed (krkn-ai's lesson: damage fitness drives toward "destructive" scenarios)
- **Leverage ranks findings:** impact (high 3 / medium 2 / low 1) ÷ fault strength (mild 1 /
  targeted 2 / broad 3). From `bank.json`: blast-loss 3.0 > catalog-kill 1.5 > cpu-starve 0.67
- **The resilience score rates the system:** krkn's formula (critical 3 pts, warning 1 pt;
  passed / total × 100). It's computed over the pool fixed at session start and compared before/after a fix.
- **Guards:** one target per run · no namespace-wide or steady-node faults · kill switch active
  (traffic-spike: blast radius + STOP only, intended) · controls must pass · a person approves each run

## Agent (one fresh sub-agent per task, one after another)
1. orchestrator (Groq `gpt-oss-120b`) ranks the pool + candidate pairs
2. a person approves each run → `bank.measure()`
3. analyst per run (OpenRouter `nemotron`)
4. `judge.py` groups findings by root cause
5. fixer per group (`docs/fix-catalog.md`)
6. orchestrator re-ranks → `report.md`

- **Code** builds the pairs, checks interactions and computes every number.
- **The LLM** ranks, writes hypotheses and explains. Its suggestions only name known faults.

## Pieces (in scope, total 3h15 over 2 lanes)
| Issue | Piece | Files | Est | Parallel |
|---|---|---|---|---|
| #17 | P7 `llm()` providers (done) | `llm.py`, `.env.example`, `tests/test_llm.py` | - | B (StrikerEureka34) |
| #18 | P9 rules: strength, leverage, score, pairs | `judge.py`, `tests/test_judge.py`, `docs/` | 45m | B, parallel with #7 |
| #7 | P8 agent loop + replay runner | `agent.py`, `tests/test_agent.py`, `pyproject.toml` | 1h15 | B, after #17 |
| #20 | P13 combo runner (`chaos.py run a+b`) | `chaos.py`, `bank.py`, `tests/test_chaos_abort.py` | 45m | A (TanmayBnz) |
| #19 | P12 fix + re-run: catalog-kill, replicas 2 | `k8s/otel-values.yaml`, `evidence/` | 30m | A, after #20 |
| #14 | Fault bank (ongoing: krkn-ai candidates, harvest) | `bank.py`, `experiments.toml` | - | A |

Polish #12 (S+5:30–7:00) · Pitch #13 (S+7:00–9:00). Behind at S+3:00? Cut #19, then #20.

## Out of scope
- #16 (one list): parallel injection, exhaustive combinations / genetic ranking, faults that are
  unsafe on kind, two laptops in one cluster, LangChain. None of them moves the criterion.

## Setup (done)
- **kind `chaos`:** control plane + `chaos-worker` ("blast": backends) + `chaos-worker2` ("steady":
  monitoring, frontend). Shop, `/jaeger/ui` and `/grafana` at `localhost:8080`; Prometheus at `:9090`.
- **krknctl v0.14.2-beta:** always pass `--wait-duration 1 --prometheus-url http://localhost:9090`.
- **Fault bank:** 13 entries rated in `bank.json` on 2 workers; both controls pass.
