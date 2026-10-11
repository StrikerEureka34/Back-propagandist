# Chaos session report

2026-10-10 21:50 UTC · 12 faults picked · budget 6 · 3 run · stopped: a person stopped the session

Every number comes from `judge.py` rules over the measured effects. The text comes from the models that answered: planner gpt-oss-120b, analysts gpt-oss-20b, fixes gpt-oss-120b, summary gpt-oss-120b. A person approved each run.

## Summary

The top leverage fault is cart-wipe+traffic-spike, which causes loss of cart state. We should fix it first by persisting cart state with Valkey AOF and a PVC. The next high‑leverage pairs are blast‑latency+catalog‑db‑cutoff and quote‑garbage, but they rank behind the cart issue. No faults were rated low, so nothing stayed healthy.

## Scores

- **Resilience score** (krkn's formula over customer SLOs, this pool): **44/100**
- **Root causes found by mild or targeted faults:** 1 (breaks:checkout)
- **Planner hit rate** (predicted tier = measured): 2/3, planned with the bank's earlier ratings

## Findings, ranked by leverage

| # | Fault | Tier | Strength | Leverage | SLO points | Broken SLOs | Root cause | Decided by | Why (analyst) | Evidence check |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `cart-wipe+traffic-spike` | high | pair | 3 ÷ 2 = 1.5 | 5/15 | customers get answers, no data lost, the shop stays up, customers aren't 2x slower | loses-state | cart items 1 -> 0 | No persistence, pod removal races with traffic, causing state wipe and checkout failures. | 70% (model's own 85%) |
| 2 | `blast-latency+catalog-db-cutoff` | high | pair | 3 ÷ 2 = 1.5 | 4/15 | customers get answers, the shop recovers, the shop stays up, customers aren't 2x slower, nothing else restarts | slow-recovery | shop not healthy 120 s after the fault | Product catalog DB unreachable and added 200ms latency forced checkout to exceed deadlines, raising error rate. | 100% (model's own 85%) |
| 3 | `quote-garbage` | high | targeted | 3 ÷ 2 = 1.5 | 11/15 | customers get answers, other services answer | breaks:checkout | checkout errors 0% -> 59% (10/17 calls) | Malformed quote prevented shipping step; checkout charges applied, errors reported, no refunds. | 80% (model's own 90%) |

**Evidence check, what failed:**
- `quote-garbage`: only 17 checkout calls in the window: a small sample
- `cart-wipe+traffic-spike`: names no service that broke

## How the scores work

- **Leverage** = impact ÷ fault strength. Impact is the bank's measured tier (high 3, medium 2, low 1); strength is how hard we pushed (mild 1, targeted 2, broad 3; a pair adds its two). A big effect from a small fault ranks first, and "broke everything, everything broke" sinks.
- **Resilience score** = SLO points held ÷ points possible × 100: krkn's formula (critical SLOs 3 points, warnings 1) over SLOs that measure what customers feel: customers get answers (3 pts); no data lost (3 pts); the shop recovers (3 pts); the shop stays up (3 pts); other services answer (1 pt); customers aren't 2x slower (1 pt); nothing else restarts (1 pt). A customer page 10x slower than usual, or over 2 s, also breaks "customers get answers". We don't use krkn's built-in score: it gave 100/100 to a fault that made the shop 66x slower (docs/decisions-and-lessons.md).
- **Evidence check** on each analyst note, from rules: it starts at 100%; -40 for each claim the measurement disproves ("no data loss" when carts were lost), -30 if the note names nothing that broke, -20 if an error ratio rests on fewer than 20 calls, -10 if it cites no evidence. The model's own estimate is shown next to it, unchecked.
- **Planner hit rate** = predicted tier equals measured tier. In replay the planner plans blind; live, it sees the bank's earlier ratings, so a high hit rate there is partly memory.

## Fixes, one per root cause

**loses-state**: `cart-wipe+traffic-spike`
- Fix: Persist cart state with Valkey AOF and PVC
- Change: Start Valkey with --appendonly yes, attach a local‑path PVC; add a PVC for astronomy‑db
- Verify with: `cart-wipe` · model's own estimate 93% · from the fix catalog

**slow-recovery**: `blast-latency+catalog-db-cutoff`
- Fix: Add a second replica and a PodDisruptionBudget; enable gRPC keepalive and capped reconnect backoff.
- Change: replicas: 2; PDB minAvailable 1; client reconnect settings
- Verify with: `catalog-kill` · model's own estimate 85% · from the fix catalog

**breaks:checkout**: `quote-garbage`
- Fix: Add response validation on shipping quote call; on malformed quote, reject checkout with clear error or use cached quote
- Change: Validate quote API response; if invalid, return error or fallback to default shipping cost
- Verify with: `quote-garbage` · model's own estimate 92% · from the fix catalog

## Stayed healthy (rated low)

- none

## Runs, in the planner's order

| # | Fault | Hypothesis (planner) | Predicted (planner's own confidence) | Measured | Held? (analyst) |
|---|---|---|---|---|---|
| 1 | `quote-garbage` | Malformed shipping quote triggers checkout error after charge, with no refund. | high (87%) | high | True |
| 2 | `blast-latency+catalog-db-cutoff` | Combined latency and DB cutoff exceed checkout deadline, amplifying failures beyond each alone. | high (80%) | high | True |
| 3 | `cart-wipe+traffic-spike` | Under load, cart wipe race more often loses cart data, causing checkout failures unseen alone. | medium (70%) | high | True |

## Suggested next

- `catalog-db-cutoff`: Check DB loss alone without added latency. (suggested by the analyst after blast-latency+catalog-db-cutoff, model's own estimate 85%)
- `cart-wipe`: test cart wipe without load (suggested by the analyst after cart-wipe+traffic-spike, model's own estimate 85%)
- `cpu-starve`: 100 % CPU on backend node causes timeouts across services, increasing error rates. (suggested by the planner, stopped before it ran, model's own estimate 65%)
- `kafka-outage`: Kafka pod kill blocks order publishing, leading to lost orders after checkout. (suggested by the planner, stopped before it ran, model's own estimate 60%)
- `payment-kill`: Payment service termination prevents charge, aborting checkout. (suggested by the planner, stopped before it ran, model's own estimate 60%)
- `recommendation-cutoff`: Blocking recommendation ingress slows frontend recommendations, minor checkout impact. (suggested by the planner, stopped before it ran, model's own estimate 55%)
- `catalog-kill`: Killing catalog pod causes product lookup failures, aborting checkout. (suggested by the planner, stopped before it ran, model's own estimate 60%)
- `blast-memory`: Memory pressure on node creates GC pauses, slightly increasing latency. (suggested by the planner, stopped before it ran, model's own estimate 50%)


## Ideas (not runnable until someone adds them to `experiments.toml`)

- session-token‑expiry+load‑burst: tokens expire under load causing auth failures.
- config‑drift+feature‑flag‑toggle: mismatched config leads to inconsistent feature behavior.
- network‑partition+service‑mesh‑retry: mesh retries flood downstream services during partition.

## Not run

- cart-wipe (not approved)
- catalog-db-cutoff (not approved)
- blast-loss (not approved)
- traffic-spike (not approved)
- blast-latency (not approved)
