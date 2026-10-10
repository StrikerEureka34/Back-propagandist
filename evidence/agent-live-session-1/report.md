# Chaos session report

2026-10-10 20:28 UTC · 8 faults picked · budget 3 · 3 run

Every number comes from `judge.py` rules over the measured effects. The text comes from the models that answered: planner gpt-oss-120b, analysts nemotron-3.5-lightning, fixes gpt-oss-120b, summary gpt-oss-120b. Each shows its own confidence. A person approved each run.

## Summary

Blast‑loss is the biggest leverage point. Fix checkout timeouts first. Cart‑wipe is the weakest fault. Checkout delays held the system.

## Scores

- **Resilience score** (krkn's formula, this pool): **80/100**
- **Root causes found by mild or targeted faults:** 2 (breaks:checkout, loses-state)
- **Planner hit rate** (predicted tier = measured): 3/3

## Findings, ranked by leverage (impact ÷ fault strength)

| # | Fault | Tier | Strength | Leverage | Root cause | What broke | Why (analyst) | Conf. | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `blast-loss` | high | mild | 3.0 | breaks:checkout | checkout errors 0% -> 8% (2/26 calls); checkout p95 48 -> 8125 ms | Checkout sequences charge card then ship; packet loss blocks shipping/quote calls, causing errors and p95 spikes, per service-facts. | 0.6 | bank.json:blast-loss, service-facts |
| 2 | `blast-latency` | medium | mild | 2.0 | breaks:checkout (repeat) | agent p95 195 -> 990 ms; checkout p95 48 -> 1880 ms | Checkout pipeline calls backend services through blast node; latency piled up sequentially, spiking checkout 39x while root-cause tag breaks:checkout confirmed critical path. | 0.6 | bank.json:blast-latency, service-facts |
| 3 | `cart-wipe` | high | targeted | 1.5 | loses-state | cart items 1 -> 0 | valkey-cart has no volume (memory only); pod loss immediately loses cart state with no persistent impact, per service-facts | 0.6 | bank.json:cart-wipe, service-facts |

## Fixes, one per root cause

**breaks:checkout**: `blast-loss`, `blast-latency`
- Fix: Add per‑call timeouts, retries with backoff + jitter on checkout dependencies; run independent calls in parallel.
- Change: Configure checkout client library with timeout, retry policy, jitter; parallelize quote and payment calls.
- Verify with: `blast-loss` · confidence 0.9 · from the fix catalog

**loses-state**: `cart-wipe`
- Fix: Persist cart state by enabling Valkey AOF and adding PVCs
- Change: Run Valkey with --appendonly yes, mount a local‑path PVC; create a PVC for astronomy‑db
- Verify with: `cart-wipe` · confidence 0.9 · from the fix catalog

## Held up (rated low)

- none

## Runs, in the planner's order

| # | Fault | Hypothesis (planner) | Predicted | Measured | Held? (analyst) | Conf. |
|---|---|---|---|---|---|---|
| 1 | `blast-loss` | 10 % packet loss on the backend node will cause checkout and payment RPC failures, reducing completed orders. | high | high | True | 0.9 |
| 2 | `cart-wipe` | Killing the valkey‑cart pod wipes all in‑memory carts, leading customers to abandon their purchases. | high | high | True | 0.85 |
| 3 | `blast-latency` | Adding +200 ms latency on all backend egress will increase checkout latency, causing higher cart abandonment. | medium | medium | True | 0.75 |

## Suggested next

- `blast-memory`: not ranked by the planner: added by rules, mildest fault first (over the run budget)
- `kafka-outage`: not ranked by the planner: added by rules, mildest fault first (over the run budget)
- `payment-kill`: not ranked by the planner: added by rules, mildest fault first (over the run budget)
- `recommendation-cutoff`: not ranked by the planner: added by rules, mildest fault first (over the run budget)
- `cpu-starve`: not ranked by the planner: added by rules, mildest fault first (over the run budget)


## Ideas (not runnable until someone adds them to `experiments.toml`)

- Simulate network partition on checkout services
- Inject CPU spike on cart service to test resilience
