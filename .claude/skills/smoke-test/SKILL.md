---
name: smoke-test
description: Day-1 go/no-go smoke test on the Arch box - brings up a kind cluster with the OpenTelemetry Astronomy Shop, then proves krkn can break and restore it (gates G1-G4), and posts the result table to the PR. Use when the user says "smoke test", "run the smoke test", or runs /smoke-test.
---

# smoke-test

Proves the plan in issue #2 works on this machine before we build on it.
Run the steps in order. Per gate: at most 2 attempts at a fix, then record
FAIL with the error and move on. If G1 fails, stop and report.

Rules:
- Touch only the kind cluster `chaos` and files in `evidence/`. Nothing else.
- Commands that need `sudo`: ask the user to run them with the `!` prefix.
- Each Bash call starts a fresh shell, so run every gate as one command block.
- Write down how long each step took. The report needs it.

## Downloads: this is the complete list
Install exactly these. Nothing else is needed.
1. pacman packages: `docker kubectl helm jq curl`
2. `kind` binary from `github.com/kubernetes-sigs/kind` releases (command in step 0)
3. `krknctl` binary from `github.com/krkn-chaos/krknctl` releases (command in step 0)
4. One helm repo: `https://open-telemetry.github.io/opentelemetry-helm-charts`. The
   `opentelemetry-demo` chart bundles Jaeger, Prometheus, Grafana, OpenSearch and the collector.

These images download automatically. Don't pull them by hand, except the two krkn
images in step 1:
- `kindest/node`, by `kind create cluster`
- the shop and its bundled tools, by `helm install`
- `containers.krkn-chaos.dev/krkn-chaos/krkn-hub:pod-scenarios` and `:pod-network-filter`, by krknctl
- `quay.io/krkn-chaos/krkn-network-chaos`, pulled by the kind node during G4

**Do NOT** clone or install any of these:
- the source repos of krkn, krkn-hub, krkn-ai, krknctl, opentelemetry-demo or Ditto
- krkn-ai, pip/uv packages, podman, minikube, docker-compose
- a separate Prometheus, Jaeger, Grafana or kube-prometheus-stack

## 0. Prerequisites
Check `docker kubectl helm jq curl kind krknctl` with `command -v`. If any are missing:
- Ask the user to run `! sudo pacman -S --needed docker kubectl helm jq curl`,
  `! sudo systemctl enable --now docker` and `! sudo usermod -aG docker $USER`.
  After the last one they must log out and back in.
- kind: `mkdir -p ~/.local/bin && curl -Lo ~/.local/bin/kind https://github.com/kubernetes-sigs/kind/releases/latest/download/kind-linux-amd64 && chmod +x ~/.local/bin/kind`
- krknctl: `tag=$(curl -s https://api.github.com/repos/krkn-chaos/krknctl/releases/latest | jq -r .tag_name) && curl -L "https://krkn-chaos.gateway.scarf.sh/krknctl-${tag}-linux-amd64.tar.gz" | tar -xz -C ~/.local/bin krknctl`
- `~/.local/bin` must be on `PATH`. Confirm the daemon runs: `docker info`.
- If `sysctl -n fs.inotify.max_user_instances` is below 512, ask the user to run
  `! sudo sysctl fs.inotify.max_user_watches=524288 fs.inotify.max_user_instances=512`.
  kind fails with many pods without it.

## 1. Cluster and app
```bash
mkdir -p evidence
kind get clusters | grep -qx chaos || kind create cluster --config k8s/kind.yaml
kubectl config use-context kind-chaos
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update open-telemetry
helm status otel -n otel-demo >/dev/null 2>&1 || \
  helm install otel open-telemetry/opentelemetry-demo -n otel-demo --create-namespace \
    -f k8s/otel-values.yaml --wait --timeout 20m
```
Image pulls take most of the time. Pull the two krkn images in the background meanwhile:
`docker pull containers.krkn-chaos.dev/krkn-chaos/krkn-hub:pod-scenarios` and
`docker pull containers.krkn-chaos.dev/krkn-chaos/krkn-hub:pod-network-filter`.

## G1: app healthy, memory headroom
```bash
kubectl wait --for=condition=Ready pods --all -n otel-demo \
  --field-selector=status.phase!=Succeeded --timeout=5m
kubectl get pods -n otel-demo -o wide | tee evidence/pods.txt
curl -s -o /dev/null -w 'shop %{http_code}\n' localhost:8080/
free -m | awk '/^Mem:/{print "available MiB", $7}'
```
PASS: all pods Ready, the shop returns 200, more than 3072 MiB available.
Low memory: apply the trim block in `k8s/otel-values.yaml` (once).

## G2: dependency map from Jaeger
The load generator needs 1-2 minutes to create traces. Poll every 10 s for up to 3 minutes:
```bash
curl -s "localhost:8080/jaeger/ui/api/dependencies?endTs=$(date +%s%3N)&lookback=900000" \
  | jq -r '.data[] | "\(.parent) -> \(.child) \(.callCount)"' | sort | tee evidence/jaeger-deps.txt
```
If that path returns 404, try `localhost:8080/jaeger/api/dependencies`.
PASS: at least one edge. Also save, for later pieces (info only):
```bash
curl -s 'localhost:9090/api/v1/query?query=up' | jq '.data.result | length'
curl -s localhost:9090/api/v1/label/__name__/values | jq -r '.data[]' \
  | grep -iE 'span|duration|calls' | tee evidence/prom-metrics.txt | head -20
```

## G3: krkn kills payment, the pod recovers
First check the label selects a pod:
`kubectl get pods -n otel-demo -l opentelemetry.io/name=payment`. If not, use
`--show-labels` to find the right one.
```bash
before=$(kubectl get pods -n otel-demo -l opentelemetry.io/name=payment -o jsonpath='{.items[0].metadata.name}')
krknctl run pod-scenarios --kubeconfig ~/.kube/config --namespace '^otel-demo$' \
  --pod-label 'opentelemetry.io/name=payment' --disruption-count 1 \
  --expected-recovery-time 120 2>&1 | tee evidence/g3-krkn.log
echo "krknctl exit ${PIPESTATUS[0]}"
kubectl wait --for=condition=Ready pod -l opentelemetry.io/name=payment -n otel-demo --timeout=120s
after=$(kubectl get pods -n otel-demo -l opentelemetry.io/name=payment -o jsonpath='{.items[0].metadata.name}')
echo "before=$before after=$after"
grep -oE '"(total_recovery_time|pod_rescheduling_time|pod_readiness_time)": *[0-9.]+' evidence/g3-krkn.log
```
PASS: exit 0, the pod name changed, the new pod is Ready. Report the recovery times.
If krknctl returns right away, follow the container with
`docker logs -f $(docker ps -lq --filter name=krknctl)`.

## G4: krkn cuts product-catalog off from Postgres, the shop degrades, then restores
Check `curl -s -o /dev/null -w '%{http_code}' localhost:8080/api/products` returns 200 first.
Run this as one block:
```bash
( while true; do echo "$(date +%s) $(curl -s -o /dev/null -m 5 -w '%{http_code} %{time_total}' localhost:8080/api/products)"; sleep 1; done ) > evidence/g4-probe.log &
PROBE=$!; sleep 10
krknctl run pod-network-filter --kubeconfig ~/.kube/config --namespace otel-demo \
  --pod-selector 'opentelemetry.io/name=product-catalog' \
  --ingress false --egress true --ports 5432 --chaos-duration 60 2>&1 | tee evidence/g4-krkn.log
echo "krknctl exit ${PIPESTATUS[0]}"
sleep 20; kill $PROBE
echo "degraded probes: $(awk '$2!=200 || $3>2' evidence/g4-probe.log | wc -l)"
echo "last 5 ok: $(tail -5 evidence/g4-probe.log | awk '$2==200' | wc -l)"
kubectl get pods -A | grep -i krkn || echo "no leftover krkn pods"
```
PASS: exit 0, at least 1 degraded probe, last 5 probes OK, no leftover krkn pods.
Ran fine but no degraded probes? The catalog may cache the products. Try once
more, blocking traffic into the catalog: use `--ingress true --egress false` and
`--ports $(kubectl get svc product-catalog -n otel-demo -o jsonpath='{.spec.ports[0].port}')`.

## Report
Write `evidence/smoke-test.md`:

| Gate | Result | Numbers |
|---|---|---|
| G1 | PASS/FAIL | pods Ready x/y, available MiB, install minutes |
| G2 | | edge count, 3 sample edges |
| G3 | | recovery times, before → after pod |
| G4 | | degraded probes, max latency, recovery seconds |

Then add notes:
- Versions: `kind version`, `kubectl version --client`, `helm version --short`,
  `krknctl --version`, chart version from `helm list -n otel-demo`.
- Anything odd, and which fallback you used.

Then commit `evidence/` to this branch, push, and run
`gh pr comment $(gh pr view --json number -q .number) --body-file evidence/smoke-test.md`.
Leave the cluster running; piece #4 needs it. Delete it only if asked:
`kind delete cluster --name chaos`.
