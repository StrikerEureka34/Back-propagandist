## Smoke test result: G1-G4 all PASS (Arch box, 2026-10-10)

| Gate | Result | Numbers |
|---|---|---|
| G1 app healthy, memory | **PASS** | 30/30 pods Ready, shop `localhost:8080` = 200, 4542 MiB available (threshold 3072). Successful install 441 s (first, aborted attempt ~17 min, see below) |
| G2 Jaeger dependency map | **PASS** | 40 edges (24 between different services, rest are self-edges). Samples: `checkout -> payment 1`,`frontend -> checkout 3`,`frontend -> product-catalog 174`. Found on first poll, no wait needed |
| G3 krkn kills `payment` | **PASS** | exit 0, `payment-77776b64b7-958tj` -> `payment-77776b64b7-f9zf4`, new pod Ready. total_recovery 0.569 s, pod_readiness 0.563 s, pod_rescheduling 0.006 s. Whole krknctl run 124 s |
| G4 krkn cuts `product-catalog` off Postgres (:5432 egress, 60 s) | **PASS** | exit 0, 166 probes, **10 degraded** (all HTTP 000 = 5 s client timeout, max latency 5.006 s), degraded probes spread over 54 s, then 81 of 81 later probes clean, last 5 OK, no leftover krkn pods. Whole krknctl run 179 s |

Cluster `chaos` is left running for piece #4. Raw output is in `evidence/`.

### Versions
kind v0.33.0 (node image kindest/node v1.37.0), kubectl client v1.37.1, helm v4.3.0, krknctl v0.14.2-beta, docker 29.8.2, chart `opentelemetry-demo-0.42.3` (app 3.1.0).

### Changes I had to make to get it running
- **helm was not installed and I did not use pacman** (needs sudo). I downloaded the helm v4.3.0 binary into `~/.local/bin` the same way the skill does for kind and krknctl. kind and krknctl came from the skill's own commands. `~/.local/bin` is on PATH.
- **First install attempt was thrown away.** Image pulls kept failing with DNS timeouts (flaky phone hotspot). I stopped it and deleted the cluster to retry later.
- **Second attempt: DNS went stale after switching the network** (hotspot -> USB tethering). The kind nodes kept the old DNS servers, so `ghcr.io` / `docker.io` lookups timed out inside the cluster while the host was fine. Fix: `docker restart chaos-control-plane chaos-worker`. That cut Helm's connection to the API server and the install aborted with `INSTALLATION FAILED ... error from a previous attempt: EOF`, leaving the release in `failed`. Fix: `helm uninstall otel -n otel-demo` then rerun the skill's step 1. The images were already cached, so the reinstall took 441 s.
- I also deleted pods stuck in `ImagePullBackOff` a few times to reset the retry delay. Harmless, they are recreated.
- No fallback paths were needed: Jaeger path `/jaeger/ui/api/dependencies` worked, the `opentelemetry.io/name=payment` label selected a pod, G4 needed no ingress fallback, the memory trim block in `k8s/otel-values.yaml` was not needed.

### Issues to flag
1. **krkn's own resiliency report is not usable.** Both runs print `Failed to parse resiliency report: resiliency report marker not found in logs`, and the report shows `Overall Score 0 / 100`, `SLOs Evaluated 0`. The recovery times above come from the `total_recovery_time` fields in the logs, not from that score. If a later piece needs krkn's score or SLO checks, it will need setup work (not investigated).
2. **G4 degradation is partial and spiky.** Only 10 of ~60 probes in the 60 s fault window failed (and all as 5 s timeouts, not 5xx errors). The shop does not go fully down when product-catalog loses Postgres, so the "before/after" signal is a handful of timeouts. Worth knowing before we build a metric on it. I did not try the ingress variant since the gate passed.
3. **krknctl runs take 2-3 minutes** for a 0.6 s pod recovery (G3: 124 s) and a 60 s fault (G4: 179 s). Not investigated, but it matters for how many experiments we can run in a day.
4. **krknctl is a beta release (v0.14.2-beta)**, and the chart pulls the latest of everything, so this is not pinned and a rerun later may differ.
5. **Install is network-bound.** About 30 images. It only works reliably on a stable connection, and changing network mid-install breaks the kind nodes' DNS as described above.
6. `evidence/prom-metrics.txt` is mostly Kubernetes apiserver metrics (the grep pattern `duration` is too broad). The useful ones for the dependency/latency work are in `evidence/prom-metrics-otel.txt`: `traces_span_metrics_calls_total` and `traces_span_metrics_duration_milliseconds_{bucket,count,sum}`. Prometheus `up` returns 10 series.
