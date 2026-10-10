"""Live shop health: probes the shop every second so a fault is visible while it runs, and reads
every service's traces from Prometheus, so faults the probe can't see (payment, checkout, a
starved frontend) show up too.

Run an experiment in a terminal (uv run python chaos.py run traffic-spike) and watch this page.
The probe here is independent of the runner, so the chart moves even if the runner is not running.
"""

import json
import time

import pandas as pd
import streamlit as st

import bank
import chaos

URL = f"{chaos.SHOP}/api/products"
SECONDS_SHOWN = 120
KRKN_PODS = ("http-load-", "cpu-hog-", "memory-hog-", "pod-filter-")  # krkn's own helper pods are not the shop
# The kill-switch p95 limit, drawn on the chart. Above the 2000 ms probe cap it can never trip (switch off), so no line.
LIMIT_MS = next(e for e in chaos.load_experiments() if e["id"] == "traffic-spike")["abort_if"]["p95_ms"]
NO_RUN = {"aborted": False, "abort_reason": None, "recovery_s": 0.0, "impact": {"probes": 0, "failed": 0}}

st.set_page_config(page_title="Live shop health", layout="wide")
title_col, stop_col = st.columns([8, 4], vertical_alignment="center")
title_col.title("Live shop health")
st.caption(f"One request to `{URL}` every second. Run an experiment in a terminal and watch.")

if stop_col.button("Stop the running experiment", type="primary"):
    chaos.RUNS.mkdir(exist_ok=True)
    (chaos.RUNS / "STOP").write_text("")
    st.info("Stop requested. The runner kills the fault and cleans up within about a second.")


def last_run() -> str:
    """One sentence about the most recent run, read from its event log."""
    logs = sorted(chaos.RUNS.glob("*/events.jsonl"), key=lambda p: p.stat().st_mtime)
    if not logs:
        return "No experiment has run yet."
    events = [json.loads(line) for line in logs[-1].read_text().splitlines() if line]
    name = logs[-1].parent.name
    aborts = [e for e in events if e["event"] == "abort"]
    ends = [e for e in events if e["event"] == "end"]
    if ends:
        e = ends[-1]
        how = f"stopped by the kill switch ({e['abort_reason']})" if e["aborted"] else "finished by itself"
        return f"Last run: {name}, {how}, {e['duration_s']} s, shop back to normal {e['recovery_s']} s later."
    if aborts:
        return f"{name}: stopping now ({aborts[-1]['reason']})."
    if time.time() - logs[-1].stat().st_mtime < 5:
        return f"{name} is running."
    return f"{name}: no recent activity."


@st.fragment(run_every=1)
def live():
    history = st.session_state.setdefault("history", [])
    ok, ms = chaos.probe_once(URL)
    now = time.monotonic()
    history.append((now, ok, ms))
    del history[:-SECONDS_SHOWN]
    recent = [h for h in history if h[0] > now - 30]
    pods = chaos.pods()
    live_pods = {n: p for n, p in pods.items() if not p["done"] and not n.startswith(KRKN_PODS)}
    not_ready = sorted(n for n, p in live_pods.items() if not p["ready"])
    service = lambda n: live_pods[n]["labels"].get("opentelemetry.io/name", n)  # pod hash is noise
    restarted = sorted(f"{service(n)} ({p['restarts']}x)" for n, p in live_pods.items() if p["restarts"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Latest answer", f"{ms:.0f} ms" if ok else "failed")
    c2.metric("Slowest, last 30 s", f"{max(h[2] for h in recent):.0f} ms")
    c3.metric("Failed, last 30 s", sum(1 for h in recent if not h[1]))
    c4.metric("Services ready", f"{len(live_pods) - len(not_ready)} / {len(live_pods)}")

    with st.container(border=True):
        st.write(last_run())
        if not_ready:
            st.write("Not ready: " + ", ".join(service(n) for n in not_ready))
        if restarted:
            st.write("Restarted: " + ", ".join(restarted))

    frame = pd.DataFrame({"Response time (ms)": [round(h[2], 1) for h in history]},
                         index=pd.Index([round(h[0] - now) for h in history], name="Seconds ago"))
    if LIMIT_MS <= chaos.PROBE_TIMEOUT_S * 1000:
        frame["Kill-switch limit (ms)"] = LIMIT_MS
    st.line_chart(frame, x_label="Seconds ago", y_label="Response time (ms)", height=240)
    st.caption("A request that fails or times out is drawn at 2000 ms.")



@st.cache_data(ttl=15, show_spinner=False)
def service_windows() -> tuple[dict, dict]:
    """Usual = 15 to 5 min ago; now = the last 3 min (span metrics arrive once a minute)."""
    t = time.time()
    return bank.window(t - 900, t - 300), bank.window(t - 180, t)


def pair(now, usual) -> str:
    """"now / usual" in one cell; "-" where a service had no traffic."""
    return " / ".join("-" if v is None else f"{v:g}" for v in (now, usual))


def pct(d: dict) -> float | None:
    return round(100 * d["errors"] / d["calls"], 1) if d.get("calls") else None


@st.fragment(run_every=15)
def services():
    st.subheader("Every service, from traces")
    try:
        usual, now = service_windows()
    except OSError:
        st.warning(f"Prometheus at {chaos.PROM} is not answering, so per-service health is unavailable.")
        return
    effs = bank.effects(usual, now, {}, {}, NO_RUN)
    flagged = {e.get("service") for e in effs}
    left, right = st.columns([7, 5])
    with right:
        with st.container(border=True):
            st.metric("Damage rating, last 3 min", bank.tier(effs) if effs else "none",
                      help="Lags by up to 4 minutes: traces arrive a minute late and the window is "
                           "3 minutes long, so a fault that just ended still counts here.")
            for e in effs:
                st.write(f"`{e['kind']}` {e['what']}")
            if not effs:
                st.write("No service is erroring, slower or starved of traffic compared with usual.")
            st.caption("Same rules as the fault bank (bank.py), last 3 minutes against 5 to 15 "
                       "minutes ago. A fault running over 5 minutes becomes part of 'usual'.")
    with left:
        rows = []
        for svc in sorted(set(usual["services"]) | set(now["services"])):
            u, n = usual["services"].get(svc, {}), now["services"].get(svc, {})
            rows.append({"Service": svc, "Req/s": pair(n.get("rps", 0.0), u.get("rps")),
                         "Errors %": pair(pct(n), pct(u)), "p95 ms": pair(n.get("p95_ms"), u.get("p95_ms"))})
        rows.sort(key=lambda r: (r["Service"] not in flagged, r["Service"]))
        st.dataframe(rows, hide_index=True, width="stretch", height=35 * (len(rows) + 1) + 3)
        st.caption("Each cell is now / usual. Services with something wrong are listed first.")


live()
services()

with st.expander("Fault bank: every fault we have run, rated by measured damage"):
    st.markdown(bank.show() if bank.BANK.exists() else "No fault has been rated yet: uv run python bank.py run all")
