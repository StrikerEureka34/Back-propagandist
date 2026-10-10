# Progress (Day 1)

## Done
- Plan: OTel Astronomy Shop on kind + krkn (#2). Menu: `experiments.toml`
- Smoke test on the Arch box: G1–G4 PASS (PR #3, `evidence/smoke-test.md`)
- Dependency map `depmap.py` (#4): Jaeger calls + env-var edges + risk flags, coverage check vs the official diagram

## In progress / next
- #5 `chaos.py` + kill switch (TanmayBnz)
- #6 `observe.py`: needs the Prometheus label names from the Arch box
- #7 AI planner: needs the OpenRouter key + model name
- 15:30 UI polish (#12), 17:00 Demo 1

## Dependency map: what we found
**About the map**
- Jaeger doesn't see data stores (Valkey, Kafka, Postgres emit no traces). We get those 12 edges from env vars instead
- Our monitoring stack showed up as services, and opamp-server was flagged "hub". It's now excluded: breaking it would blind the kill switch. `chaos.py` must refuse these targets too
- "single-replica" was on every node, so it only added noise. Hidden from the picture, still in the data
- flagd-ui runs inside the flagd pod (sidecar), so it can't be its own node. It's the one documented edge we can't map
- The load generator appears twice: `load-generator` (from config) and `frontend-web` (its browser traffic in traces)
- Coverage vs the official diagram, live (`refs/dependency-map.json`): **35/36** found, only flagd-ui missing; 10 extra real edges (test fixture: 30/36)

**About the shop (resilience risks)**
- Every service runs 1 replica
- valkey-cart (carts), kafka (orders), astronomy-db (DB) have no volume → data lost on restart
- flagd: 10+ dependents. 7 of them aren't in the official diagram (agent, checkout, email, frontend, load-generator, product-catalog, shipping)
- kafka: 3 dependents. Checkout charges the card first and publishes to Kafka last, so an outage means orders that are never fraud-checked
- product-catalog is the busiest backend (3,984 calls from frontend in the live window), so it's the obvious traffic-spike target
