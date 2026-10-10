"""Fault bank: run each experiment, measure what it broke, and rate it high / medium / low.

    uv run python bank.py run payment-kill   # or several ids, a pair a+b, or: run all
    uv run python bank.py show                      # the bank as a markdown table, by tier

Effects come from Prometheus (per-service span metrics, per-container CPU / memory) over the
fault window, compared with a baseline window taken once before the first fault, plus what
chaos.py measured (shop probe, recovery, cart contents) and pod restarts. Results go to
bank.json, one entry per experiment; the latest run wins. `bank.py recovery` (also run after every
batch) works out how long each fault's damage lasted after the fault stopped. An experiment with `expect` is a
known-answer control: a different tier means the measurement is broken, not the shop.

Tiers:
  high    kill switch tripped, >= 10 % shop probes failed, a customer-facing service
          (frontend, frontend-proxy, checkout) erroring or serving half its usual traffic,
          cart data lost, or no recovery
  medium  another service erroring or starved of traffic, a customer-facing service 2x slower,
          or a pod restarted

The fault window runs until the shop is healthy again (damage often outlasts the fault).
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
# A rate needs two samples inside the window: with one a minute, anything shorter can come back
# empty (catalog-kill, 90 s window: frontend read "0 req/s" while serving ~20 req/s).
MIN_WINDOW_S = 2 * SCRAPE_S + 30
BASELINE_S = 300
ERR = 0.05  # error ratio that counts as erroring...
MIN_ERRORS = 2  # ...with at least 2 errors, so 1 failed checkout out of 3 isn't "33 %"
SLOW = 2.0  # p95 at least 2x the baseline...
SLOW_MS = 50  # ...and at least 50 ms worse
STARVED = 0.5  # serving half its usual requests/s or less...
MIN_RPS = 0.5  # ...when it usually serves at least this much, so a quiet service isn't "starved"
CPU = 2.0, 0.2  # 2x the baseline and +0.2 cores
MEM = 1.5, 100 * 2**20  # 1.5x the baseline and +100 MiB
SPANS = 'span_kind=~"SPAN_KIND_SERVER|SPAN_KIND_CONSUMER"'
TIERS = ("high", "medium", "low")
METRIC_KINDS = {"errors", "latency", "throughput", "cpu", "memory"}  # effects Prometheus can re-check
RECOVERY_HORIZON_S = 15 * 60
QUIET_RUN = {"aborted": False, "abort_reason": None, "recovery_s": 0.0, "impact": {"probes": 0, "failed": 0}}


def prom(query: str, at: float, key: str) -> dict[str, float]:
    url = f"{chaos.PROM}/api/v1/query?" + urllib.parse.urlencode({"query": query, "time": at})
    with urllib.request.urlopen(url, timeout=10) as r:
        result = json.load(r)["data"]["result"]
    return {x["metric"].get(key, ""): v for x in result if not math.isnan(v := float(x["value"][1]))}


def window(start: float, end: float) -> dict:
    """What every service and container did over [start, end]."""
    secs = max(end - start, MIN_WINDOW_S)
    w, at = f"{round(secs)}s", end
    calls = prom(f"sum by (service_name) (increase(traces_span_metrics_calls_total{{{SPANS}}}[{w}]))", at, "service_name")
    errors = prom(f'sum by (service_name) (increase(traces_span_metrics_calls_total{{{SPANS},status_code="STATUS_CODE_ERROR"}}[{w}]))', at, "service_name")
    p95 = prom(f"histogram_quantile(0.95, sum by (service_name, le) (increase(traces_span_metrics_duration_milliseconds_bucket{{{SPANS}}}[{w}])))", at, "service_name")
    pods = f'namespace="{chaos.NS}",container!="",container!="POD"'
    return {
        "span": [round(start), round(end)],
        "services": {s: {"calls": round(c), "rps": round(c / secs, 2), "errors": round(errors.get(s, 0)),
                         "p95_ms": round(p95[s]) if s in p95 else None}
                     for s, c in calls.items()},  # 0 calls is real silence; absent = no data
        "cpu": prom(f"sum by (container) (rate(container_cpu_usage_seconds_total{{{pods}}}[{w}]))", at, "container"),
        "mem": prom(f"max by (container) (max_over_time(container_memory_working_set_bytes{{{pods}}}[{w}]))", at, "container"),
    }


def effects(before: dict, during: dict, pods_before: dict, pods_after: dict, summary: dict,
            target: str = "") -> list[dict]:
    """Every change big enough to count, each tagged with what kind of damage it is. The target
    pod being killed or replaced is the fault itself, not damage, so only collateral pods count."""
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
        out.append({"kind": "no-recovery", "what": f"shop not healthy {chaos.RECOVER_TIMEOUT_S} s after the fault"})
    target_svcs = {t.partition("=")[2] for t in target.split(",")}  # a pair has two targets
    for svc, b in sorted(before["services"].items()):
        # a service nobody can reach serves nothing: that's the fault on the target, damage elsewhere.
        # Absent from the fault window means no data, not zero traffic.
        d = during["services"].get(svc)
        d_rps = d["rps"] if d else None
        if d and svc not in target_svcs and b.get("rps", 0) >= MIN_RPS and d_rps <= STARVED * b["rps"]:
            out.append({"kind": "throughput", "service": svc, "what": f"{svc} served {b['rps']} -> {d_rps} req/s"})
    for svc, d in sorted(during["services"].items()):
        b = before["services"].get(svc, {"calls": 0, "errors": 0, "p95_ms": None})
        was = b["errors"] / b["calls"] if b["calls"] else 0.0
        now = d["errors"] / d["calls"] if d["calls"] else 0.0
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
        if target and chaos.is_target(target, p):
            continue
        after = pods_after.get(name)
        if after is None:
            out.append({"kind": "pod-replaced", "what": f"pod {name} replaced"})
        elif after["restarts"] > p["restarts"]:
            out.append({"kind": "restart", "what": f"pod {name} restarted {after['restarts'] - p['restarts']}x"})
    return out


def tier(effs: list[dict]) -> str:
    kinds = {e["kind"] for e in effs}
    customer = {e["kind"] for e in effs if e.get("service") in CUSTOMER_FACING}
    if kinds & {"kill-switch", "shop-down", "data-loss", "no-recovery"} or customer & {"errors", "throughput"}:
        return "high"
    if kinds & {"errors", "throughput", "restart", "pod-replaced"} or "latency" in customer:
        return "medium"
    return "low"


def pause(until: float) -> None:
    """Sleeps until `until` (epoch s). A person's stop ends the wait: whatever fault ran is already over,
    and the half-measured run isn't rated."""
    while (left := until - time.time()) > 0:
        if chaos.stop_requested():
            sys.exit("stopped by hand: not rated")
        time.sleep(min(1.0, left))


def wait_healthy(url: str, streak: int = 5, timeout_s: int = 300) -> bool:
    """Before the next fault: the last one's damage may still be healing (catalog-kill took ~3 min)."""
    t0, ok_in_a_row = time.monotonic(), 0
    while time.monotonic() - t0 < timeout_s:
        if chaos.stop_requested():
            sys.exit("stopped by hand: no new fault")
        ok, _ = chaos.probe_once(url)
        ok_in_a_row = ok_in_a_row + 1 if ok else 0
        if ok_in_a_row >= streak:
            return True
        time.sleep(1)
    return False


def recovery(entry: dict, target: str, ended_at: float, until: float, window_fn=None,
             live: bool = False) -> float | None:
    """Seconds after the fault stopped until none of its metric damage is left, re-checked every minute
    over a trailing MIN_WINDOW_S window (so an upper bound, minute-accurate). 0 when the fault left no
    metric damage; None when some was still there at `until` (the next fault, or the horizon)."""
    window_fn = window_fn or window
    damage = {(e["kind"], e.get("service")) for e in entry["effects"] if e["kind"] in METRIC_KINDS}
    if not damage:
        return 0.0
    baseline = window_fn(*entry["windows"]["baseline"])
    t = ended_at + MIN_WINDOW_S
    while t <= until:
        if live:  # measuring as it happens: wait for the minute's metrics to land
            pause(t + 5)
        now = window_fn(t - MIN_WINDOW_S, t)
        left = {(e["kind"], e.get("service")) for e in effects(baseline, now, {}, {}, QUIET_RUN, target)}
        if not damage & left:
            return round(t - ended_at)
        t += SCRAPE_S
    return None


def fill_recovery() -> None:
    """Adds recovered_s to every bank entry, stopping each check where the next fault started."""
    bank = load()
    exps = {e["id"]: e for e in chaos.load_experiments()}
    starts = sorted(e["windows"]["fault"][0] for e in bank.values() if "windows" in e)
    for exp_id, e in bank.items():
        summary_file = chaos.RUNS / exp_id / "summary.json"
        if "windows" not in e or exp_id not in exps or not summary_file.exists() or e.get("recovery_live"):
            continue
        summary = json.loads(summary_file.read_text())
        if abs(summary["started_at"] - e["windows"]["fault"][0]) > 5:
            continue  # runs/ holds a later, unrated run of this experiment
        ended = summary["ended_at"]
        nxt = min((t for t in starts if t > ended), default=float("inf"))
        until = min(nxt, ended + RECOVERY_HORIZON_S, time.time() - SCRAPE_S)
        e["fault_ended_at"] = ended
        e["recovered_s"] = recovery(e, exps[exp_id]["target"], ended, until)
        e["recovery_checked_s"] = round(until - ended)
    BANK.write_text(json.dumps(bank, indent=2) + "\n")


def load() -> dict:
    return json.loads(BANK.read_text()) if BANK.exists() else {}


def measure(exp_id: str, baseline: dict) -> dict:
    """Runs one fault and rates it. Holds the run lock from injection to the end of the rating
    window, so no other fault lands in it."""
    if chaos.stop_requested():  # checked before chaos.run, which clears a stale STOP
        sys.exit("stopped by hand: no new fault")
    with chaos.exclusive(exp_id):
        return _measure(exp_id, baseline)


def _measure(exp_id: str, baseline: dict) -> dict:
    exp = chaos.combined(chaos.find(exp_id))  # one fault, or a pair "a+b"
    pods_before = chaos.pods()
    summary = chaos.run(exp_id)
    if summary["abort_reason"] in ("STOP file", "Ctrl+C"):
        sys.exit(f"{exp_id} stopped by hand: not rated")
    if summary["krkn_failed"]:  # nothing was injected: rating it would bank a false "low"
        print(f"{exp_id}: krkn failed, not rated. See runs/{exp_id}/krknctl.log")
        return {}
    # Damage can outlast the fault (catalog-kill: pod back in seconds, shop broken ~3 min), so the
    # window runs until the shop recovered, plus SCRAPE_S because span metrics arrive a minute late.
    settle = summary["recovery_s"] if summary["recovery_s"] is not None else chaos.RECOVER_TIMEOUT_S
    end = summary["ended_at"] + settle + SCRAPE_S
    pause(end + 5)
    during = window(summary["started_at"], end)
    effs = effects(baseline, during, pods_before, chaos.pods(), summary, exp["target"])
    entry = {
        "tier": tier(effs), "effects": effs,
        "fault": exp.get("note") or exp["scenario"], "scenario": exp["scenario"], "params": exp["params"],
        "recovery_s": summary["recovery_s"], "shop": summary["impact"], "baseline_p95_ms": summary["baseline_p95_ms"],
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "windows": {"baseline": baseline["span"], "fault": during["span"]},  # epoch s, to re-check in Grafana
    }
    # Wait for this fault's damage to clear before the next one, measuring how long it takes. It also
    # means every fault starts on a healed shop.
    entry["fault_ended_at"] = summary["ended_at"]
    entry["recovered_s"] = recovery(entry, exp["target"], summary["ended_at"],
                                    summary["ended_at"] + RECOVERY_HORIZON_S, live=True)
    entry["recovery_checked_s"] = round(time.time() - summary["ended_at"])
    entry["recovery_live"] = True
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


def recovered_text(e: dict) -> str:
    if "recovered_s" not in e:
        return "not checked"
    if e["recovered_s"] is None and e["recovery_checked_s"] < MIN_WINDOW_S:
        return f"not measured (next fault {e['recovery_checked_s']} s later)"
    if e["recovered_s"] is None:
        return f"not within {e['recovery_checked_s'] // 60} min"
    return "-" if e["recovered_s"] == 0 else f"within {math.ceil(e['recovered_s'] / 60)} min"


def show() -> str:
    bank = load()
    rows = ["| Tier | Fault | What it is | Effects | Damage gone | Shop page back |", "|---|---|---|---|---|---|"]
    for t in TIERS:
        for exp_id, e in sorted(bank.items()):
            if e["tier"] == t:
                effs = "; ".join(x["what"] for x in e["effects"]) or "no detectable effect"
                rec = recovered_text(e)
                # the probe only watches /api/products: its figure means something only if that page broke
                hurt = e["shop"]["failed"] or e["shop"]["p95_ms"] > 3 * max(e["baseline_p95_ms"], 1)
                page = "-" if not hurt else ("not in 120 s" if e["recovery_s"] is None else f"{e['recovery_s']} s")
                if "control" in e:
                    effs += f" (control, expected {e['control']['expected']}: {'pass' if e['control']['pass'] else 'FAIL'})"
                rows.append(f"| {t} | {exp_id} | {e['fault']} | {effs} | {rec} | {page} |")
    return "\n".join(rows)


if __name__ == "__main__":
    if sys.argv[1:2] == ["show"]:
        print(show())
    elif sys.argv[1:2] == ["recovery"]:
        fill_recovery()
        print(show())
    elif sys.argv[1:2] == ["run"] and len(sys.argv) > 2:
        ids = [e["id"] for e in chaos.load_experiments()] if sys.argv[2:] == ["all"] else sys.argv[2:]
        # ponytail: one baseline per invocation; re-run soon after another fault and it is dirty
        (chaos.RUNS / "STOP").unlink(missing_ok=True)  # a stop from an earlier run
        t0 = time.time()
        baseline = window(t0 - BASELINE_S, t0)
        for exp_id in ids:
            url = chaos.combined(chaos.find(exp_id))["probe_url"]  # a pair "a+b" too
            if not wait_healthy(url):
                sys.exit(f"shop still unhealthy 5 min after the last fault; stopping before {exp_id}")
            measure(exp_id, baseline)
        fill_recovery()
    else:
        sys.exit(__doc__)
