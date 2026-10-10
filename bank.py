"""Fault bank: run each experiment, measure what it broke, and rate it high / medium / low.

    uv run python bank.py run payment-failure-100   # or several ids, or: run all
    uv run python bank.py show                      # the bank as a markdown table, by tier

Effects come from Prometheus (per-service span metrics, per-container CPU / memory) over the
fault window, compared with a baseline window taken once before the first fault, plus what
chaos.py measured (shop probe, recovery, cart contents) and pod restarts. Results go to
bank.json, one entry per experiment; the latest run wins. An experiment with `expect` is a
known-answer control: a different tier means the measurement is broken, not the shop.

Tiers:
  high    kill switch tripped, >= 10 % shop probes failed, a customer-facing service
          (frontend, frontend-proxy, checkout) erroring, cart data lost, or no recovery
  medium  another service erroring, a customer-facing service 2x slower, or a pod restarted
  low     anything less: internal slowness, CPU / memory strain, or no detectable effect
"""

import json
import math
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import chaos

BANK = chaos.ROOT / "bank.json"
CUSTOMER_FACING = {"frontend", "frontend-proxy", "checkout"}
SCRAPE_S = 60  # span metrics reach Prometheus once a minute; cAdvisor is scraped once a minute
BASELINE_S = 300
ERR = 0.05  # error ratio that counts as erroring...
MIN_ERRORS = 2  # ...with at least 2 errors, so 1 failed checkout out of 3 isn't "33 %"
SLOW = 2.0  # p95 at least 2x the baseline...
SLOW_MS = 50  # ...and at least 50 ms worse
CPU = 2.0, 0.2  # 2x the baseline and +0.2 cores
MEM = 1.5, 100 * 2**20  # 1.5x the baseline and +100 MiB
SPANS = 'span_kind=~"SPAN_KIND_SERVER|SPAN_KIND_CONSUMER"'
TIERS = ("high", "medium", "low")


def prom(query: str, at: float, key: str) -> dict[str, float]:
    url = f"{chaos.PROM}/api/v1/query?" + urllib.parse.urlencode({"query": query, "time": at})
    with urllib.request.urlopen(url, timeout=10) as r:
        result = json.load(r)["data"]["result"]
    return {x["metric"].get(key, ""): v for x in result if not math.isnan(v := float(x["value"][1]))}


def window(start: float, end: float) -> dict:
    """What every service and container did over [start, end]."""
    w, at = f"{max(round(end - start), SCRAPE_S)}s", end
    calls = prom(f"sum by (service_name) (increase(traces_span_metrics_calls_total{{{SPANS}}}[{w}]))", at, "service_name")
    errors = prom(f'sum by (service_name) (increase(traces_span_metrics_calls_total{{{SPANS},status_code="STATUS_CODE_ERROR"}}[{w}]))', at, "service_name")
    p95 = prom(f"histogram_quantile(0.95, sum by (service_name, le) (increase(traces_span_metrics_duration_milliseconds_bucket{{{SPANS}}}[{w}])))", at, "service_name")
    pods = f'namespace="{chaos.NS}",container!="",container!="POD"'
    return {
        "services": {s: {"calls": round(c), "errors": round(errors.get(s, 0)), "p95_ms": round(p95[s]) if s in p95 else None}
                     for s, c in calls.items() if c >= 1},
        "cpu": prom(f"sum by (container) (rate(container_cpu_usage_seconds_total{{{pods}}}[{w}]))", at, "container"),
        "mem": prom(f"max by (container) (max_over_time(container_memory_working_set_bytes{{{pods}}}[{w}]))", at, "container"),
    }


def effects(before: dict, during: dict, pods_before: dict, pods_after: dict, summary: dict) -> list[dict]:
    """Every change big enough to count, each tagged with what kind of damage it is."""
    out = []
    if summary["aborted"]:
        out.append({"kind": "kill-switch", "what": summary["abort_reason"]})
    imp = summary["impact"]
    if imp["probes"] and imp["failed"] / imp["probes"] >= 0.10:
        out.append({"kind": "shop-down", "what": f"{imp['failed']}/{imp['probes']} shop probes failed"})
    cart = imp.get("cart_items")
    if cart and cart["after"] < cart["before"]:
        out.append({"kind": "data-loss", "what": f"cart items {cart['before']} -> {cart['after']}"})
    if summary["recovery_s"] is None:
        out.append({"kind": "no-recovery", "what": f"shop not healthy {chaos.RECOVER_TIMEOUT_S}s after the fault"})
    for svc, d in sorted(during["services"].items()):
        b = before["services"].get(svc, {"calls": 0, "errors": 0, "p95_ms": None})
        was = b["errors"] / b["calls"] if b["calls"] else 0.0
        now = d["errors"] / d["calls"]
        if d["errors"] >= MIN_ERRORS and now >= ERR and now >= 2 * was:
            out.append({"kind": "errors", "service": svc,
                        "what": f"{svc} errors {was:.0%} -> {now:.0%} ({d['errors']}/{d['calls']} calls)"})
        if d["p95_ms"] and b["p95_ms"] and d["p95_ms"] >= SLOW * b["p95_ms"] and d["p95_ms"] - b["p95_ms"] >= SLOW_MS:
            out.append({"kind": "latency", "service": svc, "what": f"{svc} p95 {b['p95_ms']} -> {d['p95_ms']} ms"})
    for c, now in sorted(during["cpu"].items()):
        was = before["cpu"].get(c, 0.0)
        if now >= CPU[0] * was and now - was >= CPU[1]:
            out.append({"kind": "cpu", "service": c, "what": f"{c} CPU {was:.2f} -> {now:.2f} cores"})
    for c, now in sorted(during["mem"].items()):
        was = before["mem"].get(c, 0.0)
        if now >= MEM[0] * was and now - was >= MEM[1]:
            out.append({"kind": "memory", "service": c, "what": f"{c} memory {was / 2**20:.0f} -> {now / 2**20:.0f} MiB"})
    for name, p in sorted(pods_before.items()):
        after = pods_after.get(name)
        if after is None:
            out.append({"kind": "pod-replaced", "what": f"pod {name} replaced"})
        elif after["restarts"] > p["restarts"]:
            out.append({"kind": "restart", "what": f"pod {name} restarted {after['restarts'] - p['restarts']}x"})
    return out


def tier(effs: list[dict]) -> str:
    kinds = {e["kind"] for e in effs}
    customer = {e["kind"] for e in effs if e.get("service") in CUSTOMER_FACING}
    if kinds & {"kill-switch", "shop-down", "data-loss", "no-recovery"} or "errors" in customer:
        return "high"
    if kinds & {"errors", "restart", "pod-replaced"} or "latency" in customer:
        return "medium"
    return "low"


def load() -> dict:
    return json.loads(BANK.read_text()) if BANK.exists() else {}


def measure(exp_id: str, baseline: dict) -> dict:
    pods_before = chaos.pods()
    summary = chaos.run(exp_id)
    if summary["abort_reason"] in ("STOP file", "Ctrl+C"):
        sys.exit(f"{exp_id} stopped by hand: not rated")
    # the last minute of the fault reaches Prometheus up to SCRAPE_S late
    time.sleep(max(0.0, summary["ended_at"] + SCRAPE_S + 5 - time.time()))
    during = window(summary["started_at"], summary["ended_at"] + SCRAPE_S)
    effs = effects(baseline, during, pods_before, chaos.pods(), summary)
    exp = next(e for e in chaos.load_experiments() if e["id"] == exp_id)
    entry = {
        "tier": tier(effs), "effects": effs,
        "fault": exp.get("note") or exp["scenario"], "scenario": exp["scenario"], "params": exp["params"],
        "recovery_s": summary["recovery_s"], "shop": summary["impact"], "baseline_p95_ms": summary["baseline_p95_ms"],
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if "expect" in exp:
        entry["control"] = {"expected": exp["expect"], "pass": entry["tier"] == exp["expect"]}
    bank = load()
    bank[exp_id] = entry
    BANK.write_text(json.dumps(bank, indent=2) + "\n")
    print(f"\n{exp_id}: {entry['tier'].upper()}")
    for e in effs:
        print(f"  {e['kind']:13} {e['what']}")
    if not entry.get("control", {"pass": True})["pass"]:
        print(f"  CONTROL FAILED: expected {exp['expect']}, the measurement needs fixing")
    return entry


def show() -> str:
    bank = load()
    rows = ["| Tier | Fault | What it is | Effects | Recovery |", "|---|---|---|---|---|"]
    for t in TIERS:
        for exp_id, e in sorted(bank.items()):
            if e["tier"] == t:
                effs = "; ".join(x["what"] for x in e["effects"]) or "no detectable effect"
                rec = "none" if e["recovery_s"] is None else f"{e['recovery_s']} s"
                if "control" in e:
                    effs += f" (control, expected {e['control']['expected']}: {'pass' if e['control']['pass'] else 'FAIL'})"
                rows.append(f"| {t} | {exp_id} | {e['fault']} | {effs} | {rec} |")
    return "\n".join(rows)


if __name__ == "__main__":
    if sys.argv[1:2] == ["show"]:
        print(show())
    elif sys.argv[1:2] == ["run"] and len(sys.argv) > 2:
        ids = [e["id"] for e in chaos.load_experiments()] if sys.argv[2:] == ["all"] else sys.argv[2:]
        # ponytail: one baseline per invocation; re-run soon after another fault and it is dirty
        t0 = time.time()
        baseline = window(t0 - BASELINE_S, t0)
        for exp_id in ids:
            measure(exp_id, baseline)
    else:
        sys.exit(__doc__)
