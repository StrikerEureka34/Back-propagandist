"""Chaos runner: breaks the shop with krkn (via krknctl) or a flagd failure flag, and stops
itself when it hurts too much.

    uv run python chaos.py list
    uv run python chaos.py run traffic-spike     # writes runs/<id>/{events.jsonl,summary.json,krknctl.log}

Kill switch, checked every second: probe error rate / p95, blast radius (a non-target pod goes
NotReady), max run time, Ctrl+C, or a file named runs/STOP. On abort: switch the flag off, or
kill krknctl, remove its container and delete krkn's helper pods.
"""

import json
import math
import os
import re
import signal
import subprocess
import sys
import time
import tomllib
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
RUNS = ROOT / "runs"
NS = "otel-demo"
PROM = "http://localhost:9090"
SHOP = "http://localhost:8080"
PROBE_TIMEOUT_S = 2
WINDOW_S = 5  # breach looks at the last 5 s of probes, so one slow request can't trip it
MIN_SAMPLES = 3
MIN_HITS = 2  # one failed or slow probe is a blip; the switch needs two inside the window
RECOVER_STREAK = 5  # consecutive healthy probes that count as "back to baseline"
RECOVER_TIMEOUT_S = 120
FLAGD_POD = "opentelemetry.io/name=flagd"
FLAG_FILE = "/app/data/demo.flagd.json"  # shared with flagd, which reloads it in under a second


def load_experiments() -> list[dict]:
    with open(ROOT / "experiments.toml", "rb") as f:
        return tomllib.load(f)["experiment"]


def krkn_command(exp: dict) -> list[str]:
    cmd = ["krknctl", "run", exp["scenario"], "--wait-duration", "1", "--prometheus-url", PROM]
    for flag, value in exp["params"].items():
        if flag.endswith("-file-path"):  # krknctl reads the file itself; give it an absolute path
            value = ROOT / value
        cmd += [f"--{flag}", str(value)]
    return cmd


def with_flag(doc: dict, flag: str, variant: str) -> dict:
    """The flag file with `flag` serving `variant`. A flag with a targeting rule
    (productCatalogFailure: one product only) ignores defaultVariant, so the rule's match
    branch gets the variant instead."""
    f = doc["flags"][flag]
    if variant not in f["variants"]:
        raise ValueError(f"{flag} has no variant {variant!r}; it has {sorted(f['variants'])}")
    rule = f.get("targeting", {}).get("if")
    if rule and len(rule) == 3:
        rule[1] = variant
    else:
        f["defaultVariant"] = variant
    return doc


def set_flag(flag: str, variant: str):
    """Rewrites the flag file in place (same inode, so flagd's file watch keeps firing)."""
    pod = sh("kubectl", "get", "pod", "-n", NS, "-l", FLAGD_POD, "-o", "name").split()[0]
    exec_in = ["kubectl", "exec", "-n", NS, pod, "-c", "flagd-ui", "--"]
    doc = with_flag(json.loads(sh(*exec_in, "cat", FLAG_FILE)), flag, variant)
    subprocess.run(exec_in[:2] + ["-i"] + exec_in[2:] + ["sh", "-c", f"cat > {FLAG_FILE}"],
                   input=json.dumps(doc, indent=2), text=True, check=True, capture_output=True)


def breach(samples: list[tuple], limits: dict) -> str | None:
    """samples: (seconds since start, ok, latency ms). Returns why to abort, or None."""
    if not samples:
        return None
    now = samples[-1][0]
    if now > limits["max_s"]:
        return f"max_s: ran {now:.0f}s, limit {limits['max_s']}s"
    window = [s for s in samples if s[0] > now - WINDOW_S]
    if len(window) < MIN_SAMPLES:
        return None
    failed = sum(1 for s in window if not s[1])
    if failed >= MIN_HITS and failed / len(window) > limits["error_rate"]:
        return f"error_rate: {failed}/{len(window)} probes failed in last {WINDOW_S}s, limit {limits['error_rate']:.0%}"
    slow = sorted(s[2] for s in window)[-MIN_HITS]  # 2nd-slowest probe: ignores a single blip
    if slow > limits["p95_ms"]:
        return f"p95_ms: {MIN_HITS} probes slower than {slow:.0f} ms in last {WINDOW_S}s, limit {limits['p95_ms']} ms"
    return None


def p95_ms(samples: list[tuple]) -> float:
    ms = sorted(s[2] for s in samples)
    return ms[math.ceil(0.95 * len(ms)) - 1] if ms else 0.0


def supervise(proc, limits, probe, blast, cleanup, interval=1.0, stop_file=None, log=None, info=None) -> str | None:
    """Watch a running scenario once per `interval`. On a trigger: kill it, run cleanup, return why."""
    log = log or (lambda **kw: None)
    samples, t0, reason = [], time.monotonic(), None
    try:
        while proc.poll() is None:
            tick = time.monotonic()
            ok, ms = probe()
            samples.append((tick - t0, ok, ms))
            log(event="probe", t=round(tick - t0, 2), ok=ok, ms=round(ms))
            if stop_file and Path(stop_file).exists():
                reason = "STOP file"
            elif (why := breach(samples, limits)):
                reason = why
            elif (why := blast()):
                reason = f"blast radius: {why}"
            if reason:
                break
            time.sleep(max(0, interval - (time.monotonic() - tick)))
    except KeyboardInterrupt:
        reason = "Ctrl+C"
    if reason:
        decided = time.monotonic()
        # first bad/slow probe among the ones the decision was based on (for the "how late" figure)
        bad = [s[0] for s in samples if s[0] > samples[-1][0] - WINDOW_S and (not s[1] or s[2] > limits["p95_ms"])] if samples else []
        log(event="abort", reason=reason)
        kill(proc)
        cleanup()
        if info is not None:
            info["first_bad_to_abort_s"] = round(decided - t0 - bad[0], 1) if bad else None
            info["breach_to_stopped_s"] = round(time.monotonic() - decided, 1)
        log(event="stopped", **(info or {}))
    return reason


def kill(proc):
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # krknctl runs in its own process group
        except ProcessLookupError:
            pass
        proc.wait()


def probe_once(url: str) -> tuple[bool, float]:
    start = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT_S) as r:
            r.read()
            return 200 <= r.status < 400, (time.monotonic() - start) * 1000
    except Exception:
        return False, PROBE_TIMEOUT_S * 1000


def sh(*cmd) -> str:
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def pods() -> dict[str, dict]:
    items = json.loads(sh("kubectl", "get", "pods", "-n", NS, "-o", "json") or '{"items":[]}')["items"]
    return {p["metadata"]["name"]: {
        "labels": p["metadata"].get("labels", {}),
        "ready": any(c["type"] == "Ready" and c["status"] == "True" for c in p["status"].get("conditions", [])),
        "done": p["status"].get("phase") in ("Succeeded", "Failed") or "deletionTimestamp" in p["metadata"],
        "restarts": sum(c.get("restartCount", 0) for c in p["status"].get("containerStatuses", [])),
    } for p in items}


def is_target(target: str, pod: dict) -> bool:
    if target.startswith("node:"):
        return False  # a node fault has no target pod: any NotReady pod is collateral
    key, _, value = target.partition("=")
    return pod["labels"].get(key) == value


def blast_radius(target: str, before: dict):
    """Returns a function that names a pod that was Ready before the run and isn't the target."""
    def check() -> str | None:
        for name, p in pods().items():
            was = before.get(name)  # new pods are krkn's own (or the target's replacement): ignore
            if was and was["ready"] and not p["ready"] and not p["done"] and not is_target(target, p):
                return f"pod {name} NotReady"
    return check


def cleanup_fn(exp: dict, pods_before: dict, containers_before: set):
    def cleanup(aborted: bool = True):
        if exp["scenario"] == "flagd":  # the fault lives in flagd: switching the flag off ends it
            set_flag(exp["params"]["flag"], "off")
            return
        for name in set(sh("docker", "ps", "-a", "--format", "{{.Names}}").split()) - containers_before:
            if name.startswith("krknctl-"):
                sh("docker", "rm", "-f", name)
        # new pods that aren't the target's replacement are krkn's helper/attacker pods
        for name, p in pods().items():
            if name not in pods_before and not is_target(exp["target"], p):
                # force: a graceful delete leaves the load pods firing for their 30 s shutdown
                sh("kubectl", "delete", "pod", name, "-n", NS, "--wait=false", "--grace-period=0", "--force")
        if "service" in exp:  # hijacked Service: krkn restores the selector only if it finishes
            key, _, value = exp["target"].partition("=")
            patch = json.dumps([{"op": "replace", "path": "/spec/selector", "value": {key: value}}])
            sh("kubectl", "patch", "svc", exp["service"], "-n", NS, "--type=json", "-p", patch)
        # A network fault krkn was killed mid-way leaves its rules in the target: replace it. Not after
        # a clean finish (krkn removed them): replacing a pod whose callers' connections were black-holed
        # strands them on a dead IP until TCP gives up, ~15 min (recommendation-cutoff, 2026-10-10).
        if aborted and "network" in exp["scenario"]:
            for name, p in pods().items():
                if is_target(exp["target"], p):
                    sh("kubectl", "delete", "pod", name, "-n", NS, "--wait=false")
    return cleanup


def cart_add(user: str):
    body = json.dumps({"item": {"productId": "OLJCESPC7Z", "quantity": 1}, "userId": user}).encode()
    req = urllib.request.Request(f"{SHOP}/api/cart?currencyCode=USD", body, {"content-type": "application/json"})
    urllib.request.urlopen(req, timeout=10).read()


def cart_items(user: str) -> int:
    with urllib.request.urlopen(f"{SHOP}/api/cart?sessionId={user}&currencyCode=USD", timeout=10) as r:
        return len(json.load(r).get("items", []))


def krkn_failed(log_text: str, aborted: bool, returncode: int | None) -> bool:
    """True when krkn injected nothing. Its exit status isn't enough: node-network-chaos with a broken
    tc command only warns ("tc command returned output") and still exits PASS (blast-latency, 2026-10-10)."""
    # Real tc errors only: with any bandwidth set, tc also prints a harmless "quantum ... is big" warning.
    tc_error = re.search(r"tc command returned output.*(not complete|Illegal|Unknown|Error)", log_text)
    return (bool(re.search(r"Exit Status\s*:\s*FAIL", log_text)) or bool(tc_error)
            or (not aborted and returncode != 0))


def wait_recovered(url: str, baseline_p95: float, log) -> float | None:
    """Seconds until RECOVER_STREAK probes in a row are healthy again, or None if never."""
    limit = max(3 * baseline_p95, 200)
    t0, streak = time.monotonic(), 0
    while time.monotonic() - t0 < RECOVER_TIMEOUT_S:
        ok, ms = probe_once(url)
        streak = streak + 1 if ok and ms <= limit else 0
        log(event="recovery_probe", ok=ok, ms=round(ms), streak=streak)
        if streak >= RECOVER_STREAK:
            return max(0.0, round(time.monotonic() - t0 - RECOVER_STREAK, 1))
        time.sleep(1)
    return None


def run(exp_id: str) -> dict:
    exp = next((e for e in load_experiments() if e["id"] == exp_id), None)
    if not exp:
        sys.exit(f"unknown experiment {exp_id!r}; try: {', '.join(e['id'] for e in load_experiments())}")
    out = RUNS / exp_id
    out.mkdir(parents=True, exist_ok=True)
    events = open(out / "events.jsonl", "w")

    def log(**kw):
        events.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), **kw}) + "\n")
        events.flush()

    url = exp["probe_url"]
    stop_file = RUNS / "STOP"
    stop_file.unlink(missing_ok=True)  # a stale STOP would kill every run
    base = [probe_once(url) for _ in range(5)]
    base_samples = [(i, ok, ms) for i, (ok, ms) in enumerate(base)]
    if not all(ok for ok, _ in base):
        sys.exit(f"shop not healthy at {url}; refusing to inject a fault into a broken app")
    baseline_p95 = p95_ms(base_samples)
    user = f"chaos-{int(time.time())}"
    cart_before = None
    if exp.get("impact") == "cart":
        cart_add(user)
        cart_before = cart_items(user)

    pods_before = pods()
    containers_before = set(sh("docker", "ps", "-a", "--format", "{{.Names}}").split())
    if exp["scenario"] == "flagd":
        # sleep stands in for krknctl: it is the fault's lifetime, so supervise() works unchanged
        cmd = ["sleep", str(exp["params"]["duration"])]
    else:
        cmd = krkn_command(exp)
    log(event="start", id=exp_id, cmd=cmd, baseline_p95_ms=round(baseline_p95))
    print("running:", " ".join(cmd))
    krkn_log = open(out / "krknctl.log", "w")
    started_at = time.time()
    if exp["scenario"] == "flagd":
        set_flag(exp["params"]["flag"], exp["params"]["variant"])
    proc = subprocess.Popen(cmd, stdout=krkn_log, stderr=subprocess.STDOUT, start_new_session=True)
    started = time.monotonic()
    probes = []

    def probe():
        ok, ms = probe_once(url)
        probes.append((time.monotonic() - started, ok, ms))
        return ok, ms

    cleanup = cleanup_fn(exp, pods_before, containers_before)
    info = {}
    reason = supervise(proc, exp["abort_if"], probe, blast_radius(exp["target"], pods_before),
                       cleanup, stop_file=stop_file, log=log, info=info)
    ended = time.monotonic()
    if not reason:
        cleanup(aborted=False)  # finished by itself: still remove krkn's leftovers
    krkn_log.close()
    recovery_s = wait_recovered(url, baseline_p95, log)

    text = (out / "krknctl.log").read_text(errors="replace")
    summary = {
        "id": exp_id, "scenario": exp["scenario"],
        "aborted": bool(reason), "abort_reason": reason, "first_bad_probe_to_abort_s": info.get("first_bad_to_abort_s"),
        "abort_to_stopped_s": info.get("breach_to_stopped_s"),
        "duration_s": round(ended - started, 1),
        "started_at": round(started_at, 1), "ended_at": round(started_at + ended - started, 1),
        "baseline_p95_ms": round(baseline_p95),
        "impact": {"probes": len(probes), "failed": sum(1 for p in probes if not p[1]),
                   "p95_ms": round(p95_ms(probes)), "max_ms": round(max((p[2] for p in probes), default=0))},
        "recovery_s": recovery_s,
        "krkn_exit": proc.returncode,
        "krkn_failed": krkn_failed(text, bool(reason), proc.returncode),
        "krkn": {k: float(v) for k, v in re.findall(
            r'"(total_recovery_time|pod_rescheduling_time|pod_readiness_time)": *([0-9.]+)', text)},
    }
    if cart_before is not None:
        summary["impact"]["cart_items"] = {"before": cart_before, "after": cart_items(user)}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    log(event="end", **summary)
    print(json.dumps(summary, indent=2))
    if summary["krkn_failed"]:
        print("WARNING: krkn itself failed, no fault was injected. See", out / "krknctl.log")
    return summary


if __name__ == "__main__":
    if sys.argv[1:2] == ["list"]:
        for e in load_experiments():
            print(f"{e['id']:21} {e['scenario']:15} {e['target']}")
    elif len(sys.argv) == 3 and sys.argv[1] == "run":
        run(sys.argv[2])
    else:
        sys.exit(__doc__)
