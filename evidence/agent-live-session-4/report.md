# Chaos session report

2026-10-11 03:30 UTC · 4 faults picked · budget 2 · 2 run

Every number comes from `judge.py` rules over the measured effects. The text comes from the models that answered: planner gpt-oss-120b, analysts gpt-oss-20b, fixes gpt-oss-120b, summary gpt-oss-120b. A person approved each run.

## Summary

The weakest point was catalog-db-cutoff, which caused breaks in the frontend-proxy with a leverage of 1.5. Shipping-ship-errors was the second high‑leverage fault affecting checkout. The first fix is to add a short timeout to recommendation calls and fall back when they fail. Next, reserve shipping before charging or refund on shipping failure. No faults remained low‑rated; none stayed healthy.

## Scores

- **Resilience score** (krkn's formula over customer SLOs, this pool): **67/100**
- **Root causes found by mild or targeted faults:** 2 (breaks:checkout, breaks:frontend-proxy)
- **Planner hit rate** (predicted tier = measured): 2/2, planned with the bank's earlier ratings

## Findings, ranked by leverage

| # | Fault | Tier | Strength | Leverage | SLO points | Broken SLOs | Root cause | Decided by | Why (analyst) | Evidence check |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `catalog-db-cutoff` | high | targeted | 3 ÷ 2 = 1.5 | 8/15 | customers get answers, the shop stays up, customers aren't 2x slower | breaks:frontend-proxy | frontend-proxy p95 33 -> 2234 ms | Frontend-proxy could not route to catalog due to DB outage, breaking product retrieval. | 100% (model's own 80%) |
| 2 | `shipping-ship-errors` | high | targeted | 3 ÷ 2 = 1.5 | 12/15 | customers get answers | breaks:checkout | checkout errors 0% -> 91% (20/22 calls) | Shipping service returned errors post‑charge, causing checkout to fail without refund. | 100% (model's own 80%) |

## How the scores work

- **Leverage**: damage ÷ how hard we pushed. Big damage from a small push ranks first.
- **Resilience score**: how many customer checks held, out of 100. Serious checks count 3, minor ones 1. A page 10x slower or over 2 s counts as no answer.
- **Evidence check**: rules compare each AI note with the data. A claim the data disproves costs 40%.
- **Hit rate**: the planner's guesses that came true.

## Fixes, one per root cause

**breaks:frontend-proxy**: `catalog-db-cutoff`
- Fix: Add short timeout to recommendation calls and render page without recommendations when they time out.
- Change: frontend-proxy: set recommendation-call timeout 200 ms, enable graceful degradation fallback.
- Verify with: `catalog-db-cutoff` · model's own estimate 92% · from the fix catalog

**breaks:checkout**: `shipping-ship-errors`
- Fix: Reserve shipping before charging or refund on shipping failure
- Change: Add saga: request shipping quote and reservation prior to payment; if ship fails, trigger refund
- Verify with: `shipping-ship-errors` · model's own estimate 92% · from the fix catalog

## Stayed healthy (rated low)

- none

## Runs, in the planner's order

| # | Fault | Hypothesis (planner) | Predicted (planner's own confidence) | Measured | Held? (analyst) |
|---|---|---|---|---|---|
| 1 | `catalog-db-cutoff` | Checkout aborts early, returning error to user because product data unavailable. | high (85%) | high | True |
| 2 | `shipping-ship-errors` | Card charged then checkout returns shipping error, causing lost money and angry customers. | high (90%) | high | True |

## Suggested next

- `blast-loss`: test network loss impact on shipping (suggested by the planner, over the run budget)
- `blast-latency`: 200 ms added latency inflates response times for all back‑end services. (suggested by the planner, over the run budget, model's own estimate 65%)
- `quote-garbage`: Checkout receives malformed quote but continues, possibly showing wrong shipping cost. (suggested by the planner, over the run budget, model's own estimate 70%)
- `blast-latency+catalog-db-cutoff`: Catalog loss plus node latency causes additional checkout timeouts on other services. (suggested by the planner, over the run budget, model's own estimate 60%)
- `blast-latency+shipping-ship-errors`: Shipping errors combined with latency may prevent charge before shipping call times out. (suggested by the planner, over the run budget, model's own estimate 60%)


## Ideas (not runnable until someone adds them to `experiments.toml`)

- Introduce a fault that simulates recommendation‑service latency spikes.
- Add a payment‑gateway timeout fault to test order rollback.

## Not run

- catalog-kill (not approved)
