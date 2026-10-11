# Chaos session report

2026-10-11 02:59 UTC · 4 faults picked · budget 4 · 4 run

Every number comes from `judge.py` rules over the measured effects. The text comes from the models that answered: planner gpt-oss-120b, analysts gpt-oss-20b, fixes gpt-oss-120b, summary gpt-oss-120b. A person approved each run.

## Summary

The top leverage point is blast-loss (medium severity, leverage 2.0) which breaks checkout. The most effective first fix is to add per‑call timeouts, exponential‑backoff retries and parallelize independent calls for checkout dependencies. Secondary high‑leverage issues are catalog-db-cutoff and shipping-ship-errors, but they share the same checkout fix. No faults were rated low, so nothing stayed healthy.

## Scores

- **Resilience score** (krkn's formula over customer SLOs, this pool): **73/100**
- **Root causes found by mild or targeted faults:** 2 (breaks:checkout, breaks:frontend-proxy)
- **Planner hit rate** (predicted tier = measured): 2/2, planned with the bank's earlier ratings

## Findings, ranked by leverage

| # | Fault | Tier | Strength | Leverage | SLO points | Broken SLOs | Root cause | Decided by | Why (analyst) | Evidence check |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `blast-loss` | medium | mild | 2 ÷ 1 = 2 | 11/15 | customers get answers, customers aren't 2x slower | breaks:checkout | checkout p95 48 -> 9250 ms | Lost packets delayed shipping request, causing checkout to timeout; other services experienced minor latency. | 100% |
| 2 | `catalog-db-cutoff` | high | targeted | 3 ÷ 2 = 1.5 | 8/15 | customers get answers, the shop stays up, customers aren't 2x slower | breaks:frontend-proxy | frontend-proxy p95 33 -> 2122 ms | Blocking DB traffic made catalog unreadable, frontend proxy returned errors; no retry or fallback. | 100% (model's own 90%) |
| 3 | `shipping-ship-errors` | high | targeted | 3 ÷ 2 = 1.5 | 11/15 | customers get answers, customers aren't 2x slower | breaks:checkout (same cause as #1) | checkout errors 0% -> 82% (18/22 calls) | Shipping service threw 500 after card charge, no refund. | 100% (model's own 80%) |
| 4 | `catalog-kill` | medium | targeted | 2 ÷ 2 = 1 | 14/15 | customers aren't 2x slower | breaks:checkout (same cause as #1) | checkout p95 48 -> 185 ms | Checkout's prepare step called product catalog; its unavailability delayed response. Flagd queried catalog for feature flags, causing 620 ms latency. | 100% (model's own 80%) |

## How the scores work

- **Leverage**: damage ÷ how hard we pushed. Big damage from a small push ranks first.
- **Resilience score**: how many customer checks held, out of 100. Serious checks count 3, minor ones 1. A page 10x slower or over 2 s counts as no answer.
- **Evidence check**: rules compare each AI note with the data. A claim the data disproves costs 40%.
- **Hit rate**: the planner's guesses that came true.

## Fixes, one per root cause

**breaks:checkout**: `blast-loss`, `shipping-ship-errors`, `catalog-kill`
- Fix: Add per-call timeouts, retries with exponential backoff and jitter on checkout dependencies, and parallelize independent calls.
- Change: Update checkout client config to enforce timeouts and retry logic, and restructure prepare step for concurrency.
- Verify with: `blast-loss` · model's own estimate 85% · from the fix catalog

**breaks:frontend-proxy**: `catalog-db-cutoff`
- Fix: Add short timeout and graceful degradation for recommendation calls.
- Change: Configure frontend‑proxy to timeout recommendation requests after 200 ms and render page without recommendations on timeout.
- Verify with: `catalog-db-cutoff` · model's own estimate 86% · from the fix catalog

## Stayed healthy (rated low)

- none

## Runs, in the planner's order

| # | Fault | Hypothesis (planner) | Predicted (planner's own confidence) | Measured | Held? (analyst) |
|---|---|---|---|---|---|
| 1 | `catalog-db-cutoff` | Dropping DB traffic makes product-catalog unreadable, breaking product pages and checkout. | high (85%) | high | True |
| 2 | `catalog-kill` | test catalog pod death for resilience | - | medium | True |
| 3 | `shipping-ship-errors` | Forcing /ship-order 500 returns shipping error after charge, leaving customers billed with undelivered orders. | high (80%) | high | True |
| 4 | `blast-loss` | Check network loss on shipping | - | medium | True |

## Suggested next

- `cart-wipe`: Killing valkey-cart pod erases in‑memory carts, so users lose items before checkout. (suggested by the planner, over the run budget, model's own estimate 70%)
- `recommendation-cutoff`: Blocking recommendation ingress stops suggestions, but product browsing and checkout remain functional. (suggested by the planner, over the run budget, model's own estimate 60%)


## Ideas (not runnable until someone adds them to `experiments.toml`)

- checkout-service overload: simulate spikes to ensure backoff mechanisms trigger.
- recommendation API latency: test graceful degradation thresholds.
