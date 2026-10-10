# Day 1: Chaos on Astronomy Shop
**Goal:** AI-driven chaos engineering: map the app, let AI pick experiments, break it with krkn
safely (kill switch), observe impact and recovery. Statement: `docs/hackathon-problem-statement.md`.
**Success criterion:** kill switch stops a sustained fault ≤ 5 s after the threshold breach and the
shop is back to baseline ≤ 60 s later - baseline: no kill switch (smoke G4 fault ran its full 60 s)
**Repro:** `uv run python chaos.py run traffic-spike` (on the Arch box; cluster `chaos` running)
**Rubric:** none supplied. Day-1 checklist: app running · dependency map · monitoring baseline ·
one failure injected · auto-stop tested · demo with impact visible
**Start:** 11:10 - feature freeze 15:30, code freeze 16:30, Demo 1 17:00 (Day 2 continues)

## Setup (done, PR #3)
- App: OpenTelemetry Astronomy Shop, chart 0.42.3, on kind v0.33.0 (`k8s/`), namespace `otel-demo`
- Shop + `/jaeger/ui` + `/grafana` at `localhost:8080`, Prometheus at `localhost:9090` (Arch box)
- krkn via `krknctl` v0.14.2-beta. Always pass `--wait-duration 1` and `--prometheus-url http://localhost:9090`
- Smoke test `/smoke-test`: G1-G4 PASS, evidence in `evidence/smoke-test.md`

## Flow
map `depmap.py` → AI plan `plan.py` (fixed krkn menu, human approves) → break `chaos.py`
(krknctl + kill switch) → observe `observe.py` → report (Day 2). krkn does every break.

## Experiments (`experiments.yaml`, the contract between lanes)
| id | krkn scenario | shows |
|---|---|---|
| cart-wipe | pod-scenarios, valkey-cart | every cart lost (no volume) |
| traffic-spike | http-load → frontend-proxy | overload; kill-switch demo |
| cpu-starve | node-cpu-hog, worker | slow, nothing down |
| kafka-outage (stretch) | pod-scenarios, kafka | charged orders never fraud-checked |

## Pieces (in scope, total 3.5h over 2 lanes)
| Issue | Piece | Files | Est | Parallel |
|---|---|---|---|---|
| #4 | Dependency map + risk flags | `depmap.py`, `tests/test_depmap.py`, `tests/fixtures/` | 45m | B (StrikerEureka34) |
| #5 | krkn runner + kill switch | `chaos.py`, `experiments.yaml`, `tests/test_chaos_abort.py` | 1.5h | A (TanmayBnz, Arch box) |
| #6 | Baseline + Prometheus metrics | `observe.py`, `tests/test_observe.py` | 45m | B, after #4 |
| #7 | AI planner (OpenRouter `llm()`) | `plan.py`, `llm.py`, `.env.example`, `tests/test_plan.py` | 30m | B, after #4; drop first if behind at 14:45 |
Polish #12 (15:30-16:30) · Pitch #13 (16:30-17:00)

## Out of scope
- #8 krkn-ai has no in-process abort - our watchdog covers it; upstream PR later
- #9 krknctl Ctrl+C skips krkn rollback - we clean up ourselves
- #10 Postgres cut-off only partly degrades the catalog - weak demo signal; report finding
- #11 Full-disk scenario unsafe on kind - would fill the laptop disk

## Day 2 (re-triage)
≥3 failure types incl. slow network (needs 2 workers) and partial dependency failure
(service-hijacking) · krkn-ai genetic search · findings report + resilience score · re-run after fix
· combined failures · 5 deliverables
