# Back-propagandist

We break a real online shop on purpose, watch what happens, and stop the damage before it
spreads. The shop is the [OpenTelemetry Astronomy Shop](https://github.com/open-telemetry/opentelemetry-demo)
(about 20 services, Apache-2.0). The breaking is done by [krkn](https://github.com/krkn-chaos/krkn).
Everything runs in a local Kubernetes cluster (kind) on one laptop.

## How it works

```
1. MAP      depmap.py      who calls whom (Jaeger traces) + what talks to the databases (config)
                           → flags the risky parts: no disk, many dependents
2. PICK     experiments.toml   a fixed menu of failures; a person picks and starts each run
                           (next: an AI ranks this menu using the map)
3. BREAK    chaos.py       krkn injects the failure
4. WATCH    chaos.py       a pretend customer checks the shop every second
   + STOP                  too slow, too many errors, something else breaks, or too long → stop
5. MEASURE  runs/<id>/     impact, how fast it stopped, how fast the shop recovered
```

The map found 35 of the 36 links in the shop's official architecture diagram, plus 10 real
ones the diagram leaves out. Biggest single point of failure: the feature-flag service (flagd),
which 13 services depend on.

## The traffic spike

We hit the shop's front door with 2 attacker pods sending 1,000 requests a second each.

- Normally the shop answers in about 15 ms.
- Under the spike it slowed to 454 ms, with the worst request close to 2 seconds.
- The kill switch noticed 2.6 s after the first slow answer and shut the attack down in 0.7 s.
- The shop was back to normal 1.9 s later. None of our checks failed.

We ran it again with the slowness and error limits switched off. The attack kept going,
customers started getting timeouts, and the flood of traces crashed Jaeger (out of memory).
The blast-radius check caught that and stopped the run at 52 s. Without any stop at all,
it would have run its full 2 minutes.

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
uv run pytest -q                       # tests (Linux)
```

Shop, Jaeger and Grafana: http://localhost:8080 (`/jaeger/ui`, `/grafana`).
Prometheus: http://localhost:9090.

## What's where

```
app.py              the console (Streamlit): dependency map, risk table
depmap.py           builds the dependency map and the risk flags
chaos.py            runs a krkn experiment, watches it, stops it, cleans up
experiments.toml    the failure menu and each one's stop limits
k8s/                kind cluster config + shop install settings
tests/              tests for the map and the kill switch
docs/               problem statement, official diagram edges, progress notes
evidence/           results from our runs on the cluster
runs/               output of each run (local only)
```

## Three other failures

| Failure | What krkn did | What we saw |
|---|---|---|
| Cart wipe | killed the cart database (Valkey) | back in 0.9 s, but every cart was empty: it keeps carts in memory only |
| Kafka outage | killed the order queue | back in 0.5 s. The real damage is quieter: the shop charges the card first and queues the order last, so orders can skip the fraud check. Not measured yet |
| CPU starve | burned 80% of the CPU for 60 s | no slowdown at all: the shop has CPU to spare |
