# Back-propagandist

We break a real online shop on purpose, watch what happens, and stop the damage before it
spreads. The shop is the [OpenTelemetry Astronomy Shop](https://github.com/open-telemetry/opentelemetry-demo)
(about 20 services, Apache-2.0). The breaking is done by [krkn](https://github.com/krkn-chaos/krkn).
Everything runs in a local Kubernetes cluster (kind) on one laptop.

## The whole workflow

```
 Jaeger traces + cluster config
            │
            ▼
 1 MAP      depmap.py ──────────────────────► console (app.py)
            │ risky targets
            ▼
 2 PICK     a person picks the pool ─► the planner (AI) orders it ─► a person approves each run
            │
            ▼
 3 BREAK    chaos.py ─► krknctl ─► krkn ─► kills a pod, or starts attacker / CPU-hog pods
            │
            ▼
 4 WATCH    one check per second + "did any other pod break?"
            │
            ├── limit hit, or a person says stop
            │        ▼
            │   5 STOP   kill krkn, remove its pods
            │        │
            ▼        ▼
 6 MEASURE  runs/<id>/summary.json: impact, time to stop, time to recover
            bank.py: every service from Prometheus → high / medium / low (bank.json)
```

| Step | What happens | Who does it |
|---|---|---|
| 1 Map | Reads who calls whom from Jaeger traces, and how each service reaches the databases from its config. Flags the risky parts: no disk, many dependents. | us (`depmap.py`) |
| 2 Pick | A person picks faults from the bank. The planner orders them by expected leverage, with a hypothesis each, and a person approves every run. An analyst explains each result as it comes in, and fixers propose one fix per root cause. | a person + the agent (`agent.py`) |
| 3 Break | `chaos.py` starts `krknctl`, which runs krkn in its own container. krkn talks to Kubernetes and kills a pod, or starts attacker or CPU-hog pods. | krkn |
| 4 Watch | Every second, one test request to the shop, like a customer would make, plus a check that no other pod broke. | us (`chaos.py`) |
| 5 Stop | Too slow, too many errors, another pod down, running too long, or a person says stop: kill krkn, remove its pods. | us (`chaos.py`) |
| 6 Measure | Wait until the shop is normal again, then write down the impact, the time to stop and the time to recover. Killed pods are restarted by Kubernetes, and krkn times that. The fault bank also rates the fault high / medium / low from every service's metrics. | us + krkn |

The map found 35 of the 36 links in the shop's official architecture diagram, plus 10 real
ones the diagram leaves out. Biggest single point of failure: the feature-flag service (flagd),
which 13 services depend on. You can see the map and the risk table in the console, and the
per-service slowdown in Jaeger's Monitor tab.

## How we measure

- **Before:** 5 checks of the shop give its normal speed (the baseline). If the shop is already
  unhealthy, the run refuses to start.
- **During:** one check per second while krkn runs gives the impact: how many checks, how many
  failed, the near-worst wait (p95) and the worst one.
- **After:** checks continue until 5 in a row are normal again. That's the recovery time.
- Every check is logged in `runs/<id>/events.jsonl`, and `summary.json` is computed from it,
  so every number can be traced back to the log.
- **Every service:** for the fault bank, `bank.py` compares each service's errors, p95 and
  throughput (from traces in Prometheus), plus CPU, memory and restarts, with the 5 minutes
  before the fault.

## Where it runs

```
Laptop (16 CPU threads, 16 GB RAM)
└── Docker
    ├── chaos-control-plane   Kubernetes itself
    ├── chaos-worker          "blast": the backend services; node faults hit this one
    ├── chaos-worker2         "steady": monitoring, frontend, flagd, load generator
    └── krknctl-…             krkn, only while an experiment runs
```

kind fakes the Kubernetes "nodes" as Docker containers, so they all share the laptop's CPU
and memory. Two workers give network faults a real network to slow between the frontend and
the backends. Keeping monitoring on the steady node means a fault never blinds the kill switch.

## The traffic spike

We hit the shop's front door with 2 attacker pods sending 1,000 requests a second each.

- Normally the shop answers in about 15 ms.
- Under the spike it slowed to 454 ms, with the worst request close to 2 seconds.
- The kill switch noticed 2.6 s after the first slow answer and shut the attack down in 0.7 s.
- The shop was back to normal 1.9 s later. None of our checks failed.

We ran it again with the slowness and error limits switched off. The attack kept going,
customers started getting timeouts, and the flood of traces crashed Jaeger (out of memory).
The blast-radius check caught that and stopped the run at 52 s. Without any stop at all,
it would have run its full 2 minutes. Its slowness and error limits are now switched off, so
the fault bank sees the full effect: only the blast-radius check and a manual stop end it early.

You can stop any run yourself: `touch runs/STOP` from another terminal, or Ctrl+C.

## Run it

Tested on Arch Linux (Ryzen 7 6800H, 16 GB RAM).

**You need:** docker, kubectl, helm, jq, curl, [uv](https://docs.astral.sh/uv/),
[kind](https://kind.sigs.k8s.io/) v0.33.0 and [krknctl](https://github.com/krkn-chaos/krknctl) v0.14.2-beta.

```bash
# cluster + shop (first time ~20-40 min, mostly image downloads)
kind create cluster --config k8s/kind.yaml
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm install otel open-telemetry/opentelemetry-demo --version 0.42.3 -n otel-demo \
  --create-namespace -f k8s/otel-values.yaml --wait --timeout 20m

uv sync
uv run python depmap.py --check        # dependency map vs the official diagram
uv run streamlit run app.py            # console with the map: http://localhost:8501
uv run python chaos.py list            # the failure menu
uv run python chaos.py run traffic-spike
uv run python bank.py run all          # rate every fault (~3-5 min each)
uv run python bank.py show             # the fault bank, by tier
uv run python agent.py --replay bank.json --auto-approve   # the agent over recorded ratings, no cluster
uv run python agent.py --pool blast-loss,cart-wipe --budget 8   # live: you approve every run
uv run pytest -q                       # tests (Linux)
```

Shop, Jaeger and Grafana: http://localhost:8080 (`/jaeger/ui`, `/grafana`).
Prometheus: http://localhost:9090.

## What's where

```
app.py              the console (Streamlit): dependency map, risk table
pages/              console pages: Live run (shop health, per-service damage, the bank),
                    Agent (pick faults, approve each run, results ranked by leverage)
agent.py            the agent: planner + sub-agents (LangGraph), you approve every run
judge.py            the rules: leverage, resilience score, root causes, safe pairs
depmap.py           builds the dependency map and the risk flags
chaos.py            runs a krkn experiment, watches it, stops it, cleans up
bank.py, bank.json  rates each fault high / medium / low from measured effects
experiments.toml    the failure menu and each one's stop limits
scenarios/          krkn scenario files (service hijacking)
k8s/                kind cluster config + shop install settings
tests/              tests for the map and the kill switch
docs/               problem statement, official diagram edges, progress notes
evidence/           results from our runs on the cluster
runs/               output of each run (local only)
```

## The fault bank

Every fault is injected from outside the app by krkn, measured, and rated:
- **high:** customers hit errors or lose data, or the shop doesn't recover
- **medium:** another service errors, or the customer-facing side is 2x slower
- **low:** anything less

Two of the shop's own planted bugs are known-answer controls. If they don't rate as expected,
the measurement is broken, not the shop.

| Tier | Faults (measured on the 2-worker cluster) |
|---|---|
| high | **blast-loss**: 10 % packet loss → checkout errors 56 %. **quote-garbage**: a 200 OK with a wrong body → checkout errors 58 %. **catalog-kill**: shop not healthy 120 s later. **catalog-db-cutoff**: frontend p95 → 15 s. **cart-wipe**: carts lost |
| medium | **blast-latency**: +200 ms → checkout p95 48 → 3,650 ms. **cpu-starve**: 100 % CPU. **recommendation-cutoff** |
| low | payment-kill, kafka-outage, blast-memory |
| controls | paymentFailure → high ✓, adHighCpu → low ✓ |

`uv run python bank.py show` prints every effect behind each rating.
