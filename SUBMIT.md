# Findings report

Sample output from the sandbox: the OpenTelemetry Astronomy Shop on a kind cluster, broken by krkn.
- Every number comes from `judge.py` rules over measured effects ([how the scores work](docs/scoring.md)).
- The text comes from `gpt-oss-120b` (planner, fixer, summary) and `gpt-oss-20b` (analysts).
- A person approved every run.

## The demo run

2026-10-11 03:30 UTC · 2 faults, to fit the 3-minute video · resilience score **67/100** ·
[raw report](evidence/agent-live-session-4/report.md)

| # | Weakness | What broke | Tier | Leverage | Fix |
|---|---|---|---|---|---|
| 1 | The catalog loses its database (`catalog-db-cutoff`) | frontend-proxy p95 33 → 2,234 ms; the shop stops answering | high | 3 ÷ 2 = 1.5 | in product-catalog: a ~1 s query timeout, a circuit breaker, and the last good catalog served from memory |
| 2 | Customers charged, then no order (`shipping-ship-errors`) | checkout errors 0 % → 91 % (20 of 22 calls), after the card is charged | high | 3 ÷ 2 = 1.5 | reserve shipping before charging, or refund when shipping fails |

To verify either fix, re-run the same fault and check that its tier drops.

**Insights**
- **Small pushes, big damage.** Each fault hit only one service, yet both rated high, and each run found a different root cause.
- **The costliest flaw:** checkout charges the card before it ships, and has no refund.
- **One stuck dependency takes the shop down.** product-catalog has no query timeout, so dropped database packets hang every product request.
- **A person stayed in control.**
  - catalog-kill was queued but not approved, so it never ran.
  - A person corrected fix 1: the fixer's draft pointed at recommendation calls.
- **The AI held up:** both analyst notes passed the evidence check at 100 %, and the planner predicted both tiers right.
- **Both fixes need changes to the shop's code, so they stay recommendations.** The one fix that needed only config is verified: catalog-kill, with 2 replicas and a preStop, went from high to low in 3 runs of 3 ([evidence](evidence/catalog-kill-fix/README.md)).

## Three more runs

These sessions ran on the same cluster, but they were too long for the 3-minute video.

| Run (UTC) | Faults | Score | Insight | Report |
|---|---|---|---|---|
| 2026-10-11 02:59 | catalog-db-cutoff, catalog-kill, shipping-ship-errors, blast-loss | 73/100 | 10 % packet loss alone made checkout 9 s slow: the top leverage (2.0). After its fix, catalog-kill rated medium, a tier below its old high. | [session 3](evidence/agent-live-session-3/report.md) |
| 2026-10-10 21:50 | quote-garbage, blast-latency + catalog-db-cutoff, cart-wipe + traffic-spike | 44/100 | A 200 OK with a wrong body broke 59 % of checkouts while the shop looked healthy. The latency + database pair left the shop unhealthy 120 s later, which neither fault did alone. | [session 2](evidence/agent-live-session-2/report.md) |
| 2026-10-10 20:28 | blast-loss, cart-wipe, blast-latency | 80/100 | Carts live in memory only, so one pod restart empties every cart. | [session 1](evidence/agent-live-session-1/report.md) |

- **Across all four runs**, mild and targeted faults found 3 distinct root causes: checkout breaks, carts are lost, and the catalog loses its database.
- **Older report formats:**
  - Session 2's pair leverage predates fix `a305be8`. Corrected, the pairs are 0.6 and 1.0, so quote-garbage ranks first.
  - Session 1's analysts ran on `nemotron`, since replaced by `gpt-oss-20b`.
