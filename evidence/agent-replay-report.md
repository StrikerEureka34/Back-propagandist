# Chaos session report

2026-10-10 19:19 UTC · 11 faults picked · budget 11 · 11 run

Every number comes from `judge.py` rules over the measured effects. The text comes from the models (planner and fixes: Groq gpt-oss-120b; analysts: OpenRouter nemotron; each falls back to the other), with their own confidence. A person approved each run.

## Summary

Blast-loss is weakest; fix checkout timeouts first. Next, address blast-latency and cart-wipe. Slow recovery and frontend issues hold up resilience.

## Scores

- **Resilience score** (krkn's formula, this pool): **78/100**
- **Root causes found by mild or targeted faults:** 5 (breaks:checkout, breaks:frontend, breaks:frontend-proxy, loses-state, slow-recovery)
- **Planner hit rate** (predicted tier = measured): 4/11

## Findings, ranked by leverage (impact ÷ fault strength)

| # | Fault | Tier | Strength | Leverage | Root cause | What broke | Why (analyst) | Conf. | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `blast-loss` | high | mild | 3.0 | breaks:checkout | ad p95 41 -> 287 ms; agent p95 195 -> 390 ms | Packet loss delayed checkout shipping quote and charge steps, causing timeouts. Checkout charges first, then ships; shipping failures post-charge error, no refund. | 0.6 | bank.json:blast-loss, service-facts |
| 2 | `blast-latency` | medium | mild | 2.0 | breaks:checkout (repeat) | agent p95 195 -> 930 ms; checkout p95 48 -> 3650 ms | Added 200ms backend latency propagated through checkout chain: product-catalog, shipping, payment, email. Shopping p95 4ms→384ms amplified effect. | 0.6 | bank.json:blast-latency, service-facts |
| 3 | `cart-wipe` | high | targeted | 1.5 | loses-state | cart items 1 -> 0; ad p95 4 -> 148 ms | Valkey-cart has no persistence; killed pod immediately empties in-memory state, causing cart loss and downstream latency spike per service-facts | 0.6 | bank.json:cart-wipe, service-facts |
| 4 | `quote-garbage` | high | targeted | 1.5 | breaks:checkout (repeat) | agent p95 195 -> 760 ms; checkout errors 0% -> 58% (11/19 calls) | Checkout pipeline requires valid shipping quote; malformed body breaks flow after card charge, causing errors per service-facts. | 0.8 | bank.json:quote-garbage, service-facts |
| 5 | `catalog-db-cutoff` | high | targeted | 1.5 | breaks:frontend | error_rate: 3/3 probes failed in last 5s, limit 50%; recommendation served 0.86 -> 0.27 req/s | Dropped Postgres egress broke catalog queries; frontend fetches products per item, so every /api/products call timed out, causing 9% errors and 15s p95. | 0.6 | bank.json:catalog-db-cutoff, service-facts |
| 6 | `catalog-kill` | high | targeted | 1.5 | slow-recovery | error_rate: 3/3 probes failed in last 5s, limit 50%; 3/26 shop probes failed | service-facts: product-catalog hub; dependent services bear latency/error load, but shop resilience prevents outage. | 0.6 | bank.json:catalog-kill, service-facts |
| 7 | `recommendation-cutoff` | medium | targeted | 1.0 | breaks:frontend-proxy | flagd served 9.53 -> 3.08 req/s; flagd p95 2 -> 3266 ms | frontend-proxy couldn't gracefully handle the interruption, becoming the bottleneck despite recommendation service recovery. | 0.6 | bank.json:recommendation-cutoff, service-facts |
| 8 | `cpu-starve` | medium | broad | 0.67 | breaks:checkout (repeat) | checkout p95 48 -> 330 ms | Saturation increased compute wait; checkout briefly blocked; system resilient per probe data. | 0.6 | bank.json:cpu-starve, service-facts |

## Fixes, one per root cause

**breaks:checkout**: `blast-loss`, `blast-latency`, `quote-garbage`, `cpu-starve`
- Fix: Add per-call timeouts, retries with backoff/jitter on checkout dependencies; parallelize independent calls
- Change: Update checkout config to enforce timeouts and retry logic
- Verify with: `blast-loss` · confidence 0.9 · from the fix catalog

**loses-state**: `cart-wipe`
- Fix: Enable persistence for Valkey and add PVC
- Change: Add --appendonly yes flag and mount a local‑path PVC; also mount PVC for astronomy‑db
- Verify with: `cart-wipe` · confidence 0.85 · from the fix catalog

**breaks:frontend**: `catalog-db-cutoff`
- Fix: Add query timeout, circuit breaker, and cache layer for product catalog
- Change: Set frontend DB timeout <1s, enable circuit breaker, serve from in‑memory cache if DB unavailable
- Verify with: `catalog-db-cutoff` · confidence 0.9 · from the fix catalog

**slow-recovery**: `catalog-kill`
- Fix: Add replicas: 2 and a PodDisruptionBudget; enable gRPC keepalive and capped reconnect backoff for the catalog service.
- Change: catalog deployment yaml: replicas: 2; PDB minAvailable: 1; client config: keepalive 10s, backoff max 5s.
- Verify with: `catalog-kill` · confidence 0.87 · from the fix catalog

**breaks:frontend-proxy**: `recommendation-cutoff`
- Fix: short timeout + graceful degradation: render page without recommendations
- Change: add timeout and fallback render in frontend-proxy for recommendation calls
- Verify with: `recommendation-cutoff` · confidence 0.9 · from the fix catalog

## Held up (rated low)

- `blast-memory`: ad p95 4 -> 64 ms; krkn-hog CPU 0.00 -> 0.38 cores
- `payment-kill`: no detectable effect
- `kafka-outage`: ad p95 4 -> 280 ms

## Runs, in the planner's order

| # | Fault | Hypothesis (planner) | Predicted | Measured | Held? (analyst) | Conf. |
|---|---|---|---|---|---|---|
| 1 | `payment-kill` | If the payment pod is killed, the Checkout API returns an error and no order is created. | high | low | False | 0.95 |
| 2 | `catalog-db-cutoff` | Dropping egress to the catalog DB prevents product lookups, causing Checkout and Frontend failures. | high | high | True | 0.9 |
| 3 | `catalog-kill` | Killing the product‑catalog pod stops product lookup, breaking Checkout and Frontend product pages. | high | high | False | 0.88 |
| 4 | `cart-wipe` | Terminating the valkey‑cart pod empties in‑memory carts, leading Checkout to see an empty cart. | medium | high | True | 0.85 |
| 5 | `kafka-outage` | Killing the Kafka pod makes Checkout’s publish fail, so orders are not persisted nor emailed. | medium | low | True | 0.8 |
| 6 | `quote-garbage` | Returning malformed bodies from quote causes Shipping quote retrieval to fail, aborting Checkout. | medium | high | True | 0.78 |
| 7 | `recommendation-cutoff` | Blocking ingress to recommendation stops suggestions, but does not affect order placement. | low | medium | True | 0.75 |
| 8 | `blast-latency` | Adding 200 ms latency on the backend node slows all API calls, causing timeouts for Checkout. | medium | medium | True | 0.7 |
| 9 | `blast-loss` | Introducing 10 % packet loss on the backend node leads to intermittent request failures during checkout. | medium | high | True | 0.68 |
| 10 | `blast-memory` | Applying 1 GiB memory pressure on the backend node triggers GC pauses, slowing checkout responses. | low | low | False | 0.65 |
| 11 | `cpu-starve` | Running a 100 % CPU hog on the backend node saturates compute, increasing latency for all calls. | low | medium | True | 0.6 |

## Suggested next

- none

## Ideas (not runnable until someone adds them to `experiments.toml`)

- Add chaos that bursts CPU usage on checkout service pods
- Randomly drop Kafka messages to test ad stream resilience
- Introduce intermittent DNS failures for external dependencies
