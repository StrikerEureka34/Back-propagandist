"""Dependency map: call edges from Jaeger traces, plus edges to data stores (which emit no
traces) from Kubernetes env vars, with the risk flags the AI planner ranks experiments by.

    uv run python depmap.py          # DOT for st.graphviz_chart
    uv run python depmap.py --json   # nodes + edges for plan.py
"""

import json
import re
import subprocess
import sys
import time
import urllib.request

# ponytail: data stores recognised by port; add a port when a new store type shows up
DATA_PORTS = {5432: "postgres", 6379: "valkey/redis", 9092: "kafka", 27017: "mongodb", 3306: "mysql"}
HUB_CALLERS = 3


def build(jaeger_deps: list[dict], workloads: dict) -> dict:
    """jaeger_deps: Jaeger /api/dependencies `data`; workloads: `kubectl get deploy -o json`."""
    pods = {w["metadata"]["name"]: w["spec"] for w in workloads["items"]}
    edges = {(d["parent"], d["child"]): {"calls": d["callCount"], "source": "jaeger"}
             for d in jaeger_deps if d["parent"] != d["child"]}

    for name, spec in pods.items():
        containers = spec["template"]["spec"]["containers"]
        env = " ".join(e.get("value", "") for c in containers for e in c.get("env", []))
        for other in pods:
            # whole words only: "valkey-cart:6379" must not also match "cart"
            if other != name and re.search(rf"(?<![\w-]){re.escape(other)}(?![\w-])", env):
                edges.setdefault((name, other), {"calls": None, "source": "env"})

    nodes = {}
    for name in sorted(set(pods) | {n for pair in edges for n in pair}):
        spec = pods.get(name)
        callers = sorted(src for src, dst in edges if dst == name)
        flags = []
        store = persistent = None
        if spec:
            pod = spec["template"]["spec"]
            ports = {p["containerPort"] for c in pod["containers"] for p in c.get("ports", [])}
            store = next((DATA_PORTS[p] for p in sorted(ports) if p in DATA_PORTS), None)
            persistent = bool(spec.get("volumeClaimTemplates")) or any(
                "persistentVolumeClaim" in v for v in pod.get("volumes", []))
            if spec.get("replicas", 1) == 1:
                flags.append("single-replica")
            if store and not persistent:
                flags.append("no-persistence")
        if len(callers) >= HUB_CALLERS:
            flags.append("hub")
        nodes[name] = {"replicas": spec.get("replicas", 1) if spec else None, "store": store,
                       "persistent": persistent, "callers": callers, "flags": flags}

    return {"nodes": nodes,
            "edges": [{"from": s, "to": d, **e} for (s, d), e in sorted(edges.items())]}


def to_dot(graph: dict) -> str:
    lines = ["digraph deps {", "  rankdir=LR;"]
    for name, n in graph["nodes"].items():
        label = "\\n".join([name, *n["flags"]])
        shape = "cylinder" if n["store"] else "box"
        bold = ", penwidth=2" if "no-persistence" in n["flags"] or "hub" in n["flags"] else ""
        lines.append(f'  "{name}" [shape={shape}, label="{label}"{bold}];')
    for e in graph["edges"]:
        attr = f'label="{e["calls"]}"' if e["source"] == "jaeger" else "style=dashed"
        lines.append(f'  "{e["from"]}" -> "{e["to"]}" [{attr}];')
    return "\n".join(lines + ["}"])


def fetch(shop: str = "http://localhost:8080", namespace: str = "otel-demo",
          lookback_min: int = 15) -> tuple[list[dict], dict]:
    url = (f"{shop}/jaeger/ui/api/dependencies"
           f"?endTs={int(time.time() * 1000)}&lookback={lookback_min * 60_000}")
    with urllib.request.urlopen(url, timeout=10) as r:
        deps = json.load(r)["data"]
    out = subprocess.run(["kubectl", "get", "deploy,statefulset", "-n", namespace, "-o", "json"],
                         check=True, capture_output=True, text=True).stdout
    return deps, json.loads(out)


if __name__ == "__main__":
    g = build(*fetch())
    print(json.dumps(g, indent=1) if "--json" in sys.argv else to_dot(g))
