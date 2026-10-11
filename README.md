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

There are two ways to run it:

- **Replay, on any laptop.** No cluster; setup is a clone and `uv sync`. The agent replays the ratings
  recorded in `bank.json`, and the console shows the map recorded on our cluster.
- **Live.** A kind cluster with the shop, and real faults. About 20-40 minutes the first time,
  mostly image downloads. Tested on Arch Linux (Ryzen 7 6800H, 16 threads, 16 GB RAM).

### 1. Replay on any laptop (Linux, macOS or Windows)

You need git, [uv](https://docs.astral.sh/uv/) and Python 3.12+ (uv installs it if missing).

```bash
git clone https://github.com/StrikerEureka34/Back-propagandist && cd Back-propagandist
uv sync
cp .env.example .env        # then fill in the keys you have (below); empty is fine
uv run pytest -q            # 99 tests, no cluster or keys needed
uv run streamlit run app.py # console at http://localhost:8501; run it from the repo root
```

On the console's **Agent** page, pick **Replay**, tick the faults, and press **Start session**.
Or from a terminal:

```bash
uv run python agent.py --replay bank.json --auto-approve        # every rated fault, budget 8
uv run python agent.py --replay bank.json --pool quote-garbage,cart-wipe,currency-down --budget 3
```

Without `--auto-approve`, the agent asks you to approve each run in the terminal. The report
goes to `runs/session-<time>/report.md`, with `session.json` next to it. A sample is in
`evidence/agent-replay-report.md`.

**AI keys (`.env`).** Every key is optional. A key that's missing is skipped and the next one
in the chain answers:

| Variable | Used for |
|---|---|
| `GROQ_API_KEY` | the planner, the report summary and high-severity fixes (`openai/gpt-oss-120b`) |
| `GROQ_API_KEY_2`, `GROQ_API_KEY_3` | the analyst for each run, and medium/low fixes (`openai/gpt-oss-20b`) |
| `OPENROUTER_API_KEY` | the last fallback for every role (`nvidia/nemotron-3.5-lightning:free`) |

Free keys: [console.groq.com](https://console.groq.com/keys) and
[openrouter.ai](https://openrouter.ai/keys). Groq limits each organization, so a second key from
the same account adds no capacity. **With no keys at all, the agent still runs.** Rules order
the faults, and every text the models would write is marked "(no AI)". Every number comes from
rules either way. Answers are cached in `runs/llm-cache/`, so the same session replayed twice costs nothing.

### 2. Live: build the cluster (once)

You need docker, kubectl, helm, jq, curl, uv, [kind](https://kind.sigs.k8s.io/) v0.33.0 and
[krknctl](https://github.com/krkn-chaos/krknctl) v0.14.2-beta. Tested with docker 29.8,
kubectl 1.37, helm 4.3 and Kubernetes 1.37 nodes. krknctl runs krkn in a Docker container and
pulls its image on first use, so the first fault needs internet.

```bash
kind create cluster --config k8s/kind.yaml        # control plane + 2 workers, ports 8080 and 9090
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm install otel open-telemetry/opentelemetry-demo --version 0.42.3 -n otel-demo \
  --create-namespace -f k8s/otel-values.yaml --wait --timeout 20m
# the catalog-kill fix (#19): helm can't set this, so re-apply it after every install or upgrade
kubectl patch deployment product-catalog -n otel-demo --patch-file k8s/product-catalog-patch.yaml
```

Check that it came up:

```bash
kubectl get nodes                                  # chaos-control-plane, chaos-worker, chaos-worker2: Ready
kubectl get pods -n otel-demo                      # all Running (ad restarting now and then is known, see below)
curl -s -o /dev/null -w "%{http_code}\n" localhost:8080          # 200: the shop
curl -s localhost:9090/-/ready                                    # Prometheus is Ready
uv run python depmap.py --check                    # found 35 of 36 official links, 10 extra
```

Shop, Jaeger and Grafana are at http://localhost:8080 (`/jaeger/ui`, `/grafana`). Prometheus is
at http://localhost:9090. Give the load generator about 5 minutes after install before the
first fault, so there's traffic to compare against.

Short on memory (under 3 GB free)? Follow the comments in `k8s/otel-values.yaml` to switch off
agent, chatbot, mcp and opensearch, then uninstall and install again. The chart can't change
these in place.

### 3. Live: run faults

One fault at a time, across the whole machine. A second run is refused with "another fault is
running". A run also refuses to start while the shop is unhealthy.

```bash
uv run python chaos.py list                            # the failure menu
uv run python chaos.py run catalog-kill                # one fault + kill switch; writes runs/<id>/
uv run python chaos.py run blast-latency+catalog-kill  # a pair under one kill switch
uv run python bank.py run quote-garbage cart-wipe      # rate faults high / medium / low into bank.json
uv run python bank.py run control-payment-failure control-ad-cpu   # the two known-answer controls
uv run python bank.py show                             # the bank, every effect behind each rating
```

- **How long:** about 3-5 minutes per fault in `bank.py`, plus a 5-minute quiet wait first if
  a fault ran recently. A dirty baseline once rated shipping-ship-errors low; the wait is the fix.
- **Rate faults by name, not with `bank.py run all`.** `all` includes `traffic-spike`, whose
  slowness and error limits are switched off on purpose, so only the blast-radius check or a
  manual stop ends it early.
- **Controls:** `control-payment-failure` must rate high and `control-ad-cpu` low. If either
  fails, the measurement is broken, not the shop. `bank.py show` marks pass or FAIL.

### 4. Live: an agent session

```bash
uv run python agent.py --pool shipping-ship-errors,quote-garbage,currency-down,catalog-db-cutoff,cart-wipe --budget 5
```

Or use the console's **Agent** page (Live): pick the pool, then approve, skip or stop each run
on its card. Drag the queue to change the order. **Emergency stop** ends the whole session.

- `--pairs` also lets the planner queue code-checked pairs. It only queues one when it expects
  the pair to show something neither fault shows alone.
- The analyst can add up to 2 follow-up faults per session. You still approve each one.
- Plan on 5-15 minutes per run, because each rating waits for the damage to clear.
- The output goes to `runs/session-<time>/`: `report.md`, `session.json`, `progress.json`, and
  `agent.log` when started from the console. A recorded live session is in
  `evidence/agent-live-session-1/`.

### Stop anything, at any time

`touch runs/STOP` from any terminal, Ctrl+C, or Emergency stop on the Agent page. The runner
kills krkn, removes its containers and helper pods, and clears a node network fault krkn
left behind. The next session or bank run clears the STOP file itself.

### If something goes wrong

| What you see | What to do |
|---|---|
| `another fault is running (...)` | A run is still going, maybe in another terminal or the console. Wait for it, or `touch runs/STOP`. |
| `shop not healthy ... refusing to inject` | The last fault hasn't cleared yet. Wait, check `kubectl get pods -n otel-demo`, then run again. |
| `refused a+b: ...` | That pair is forbidden by `judge.py`: a control, two broad faults, or the same target twice. |
| The `ad` pod keeps restarting | Known. It runs out of memory (limit 300Mi) on its own; see #12. Ad cells in the bank are noise and only low tier. |
| A hard crash left something behind | `docker ps -a \| grep krknctl` (remove with `docker rm -f`), `kubectl get pods -n default` (krkn helper pods), and `docker exec chaos-worker tc qdisc show` (a leftover `netem` slows the backend node). |
| catalog-kill rates high again | The preStop patch was lost by a helm upgrade. Re-run the `kubectl patch` line in step 2. |
| The console shows old behaviour after a pull | Restart Streamlit; it doesn't reload modules other than the page. |
| The theme is missing | Streamlit was started outside the repo root. |
| `rate limited, waiting N s` | Groq's free tier. The agent waits up to 60 s, then falls back to the next key. |
| Windows | Replay and the console work. Live faults and the run lock need Linux. |

## What's where

```
app.py              the console (Streamlit): dependency map, risk table
pages/              console pages: Live run (shop health, per-service damage, the bank),
                    Agent (pick faults, approve each run, results ranked by leverage)
agent.py            the agent: planner (Groq gpt-oss-120b) + analysts (gpt-oss-20b), you approve every run
judge.py            the rules: leverage, resilience score, root causes, safe pairs, evidence check on AI notes
depmap.py           builds the dependency map and the risk flags
chaos.py            runs a krkn experiment, watches it, stops it, cleans up
bank.py, bank.json  rates each fault high / medium / low from measured effects
heat.py             the heatmaps on the Live run page
agent_flow.py/.html the animated agent diagram on the Agent page
experiments.toml    the failure menu and each one's stop limits
scenarios/          krkn scenario files (service hijacking)
k8s/                kind cluster config + shop install settings
tests/              tests: map, kill switch, run lock, pairs, bank rules, agent, heatmaps
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
| high | **shipping-ship-errors**: shipping fails after the charge → checkout errors 83 % while every card is charged. **quote-garbage**: a 200 OK with a wrong body → checkout errors 58 %. **currency-down**: frontend traffic 16.6 → 6.3 req/s. **blast-loss**: 10 % packet loss → checkout errors 56 %. **catalog-db-cutoff**: frontend p95 → 15 s. **cart-wipe**: carts lost |
| medium | **blast-latency**: +200 ms → checkout p95 48 → 3,650 ms. **cpu-starve**: 100 % CPU. **recommendation-cutoff** |
| low | **catalog-kill** (high before the fix: 2 replicas + preStop, `evidence/catalog-kill-fix/`), payment-kill, kafka-outage, blast-memory |
| pairs | blast-latency+catalog-kill → medium (the fix holds on a slow network). blast-latency+catalog-db-cutoff, cart-wipe+traffic-spike → high |
| controls | paymentFailure → high ✓, adHighCpu → low ✓ (both on 2026-10-10) |

`uv run python bank.py show` prints every effect behind each rating.
