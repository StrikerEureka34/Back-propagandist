# Fix catalog

The fixer agent picks its fix from this table, or says "no catalog match" with a lower
confidence. `cause` is the tag from `judge.cause()`. Every fix names the bank fault that proves it.

| cause | signal in the bank | fix on this stack | verify with |
|---|---|---|---|
| loses-state | `data-loss` (cart items before > after) | give the store a volume: valkey `--appendonly yes` + a PVC (kind's local-path); a PVC for astronomy-db | cart-wipe: items survive |
| slow-recovery | `no-recovery` (shop not healthy 120 s after) | `replicas: 2` + a PodDisruptionBudget for the killed service; clients reconnect fast (gRPC keepalive, a capped reconnect backoff) | catalog-kill: tier drops |
| breaks:checkout, from a lossy or slow network | checkout `errors` / `latency` under blast-loss or blast-latency | per-call timeouts plus retries with backoff and jitter on checkout's dependency calls; run independent calls in parallel | blast-loss, blast-latency |
| breaks:checkout, from a wrong answer | checkout `errors` while the dependency answers 200 (quote-garbage) | validate dependency responses and fail with a clear error, or fall back to a cached or default shipping quote | quote-garbage |
| breaks:checkout, charge before ship | card charged, then `shipping error` returned (service facts) | quote and reserve shipping before charging, or refund when shipping fails (a saga) | shipping-ship-errors |
| breaks:checkout, fire-and-forget event | orders placed but missing in fraud-detection / accounting | outbox pattern: store the event with the order, publish with retries, alert on publish errors | kafka-cut |
| breaks:frontend, a lost database | frontend `errors`, p95 → 15 s under catalog-db-cutoff | DB query timeout well under the frontend's, a circuit breaker, and serving the catalog from a cache while Postgres is down | catalog-db-cutoff |
| breaks:frontend-proxy, a non-critical dependency | frontend-proxy `latency` when recommendation is unreachable | short timeout, and render the page without recommendations (graceful degradation) | recommendation-cutoff |
| breaks:checkout, CPU starvation | checkout `latency` under cpu-starve | CPU requests so checkout keeps its share; a priority class; spread replicas over nodes | cpu-starve |
| strains:<service> | internal `latency` / `cpu` / `memory` only | usually none: the shop absorbed it. Note it as a strength | - |
