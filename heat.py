"""Heatmaps for the console: which services each fault hurt, and which services are off right now.
Darker red = more damage. The colours come from the theme (heat-0..9 in DESIGN.md), none here."""

import re

import altair as alt
import pandas as pd

import bank

TOP = 5  # top of the colour scale: the worst cell (3) lands near heat-6, so its label stays readable
SHOP = "whole shop"  # column for damage that isn't one service's: data lost, no recovery, shop down
WHOLE = {"data-loss": "data lost", "no-recovery": "no recovery", "shop-down": "shop down", "kill-switch": "kill switch"}


def damage(e: dict) -> tuple[int, str]:
    """(0 to 3, short label) for one effect from the bank."""
    kind, what = e["kind"], e.get("what", "")
    if kind in WHOLE:
        return 3, WHOLE[kind]
    if kind == "errors":
        m = re.search(r"-> (\d+)%", what)
        pct = int(m[1]) if m else 0
        return (3 if pct >= 25 else 2), f"{pct}% err"
    if kind == "throughput":
        return 3, "starved"
    if kind == "latency":
        m = re.search(r"p95 (\d+) -> (\d+) ms", what)
        x = int(m[2]) / max(1, int(m[1])) if m else 2.0
        return (3 if x >= 10 else 2), f"{x:.0f}x slower"
    if kind in ("cpu", "memory"):
        return 1, kind
    return 0, ""


def blast_rows(entries: dict) -> pd.DataFrame:
    """Fault x service: the worst damage each fault did to each service. Controls left out."""
    cells: dict[tuple[str, str], dict] = {}
    for fault, entry in entries.items():
        if "control" in entry:
            continue
        for e in entry["effects"]:
            svc = SHOP if e["kind"] in WHOLE else e.get("service")
            level, label = damage(e)
            if not svc or not level:
                continue
            cell = cells.setdefault((fault, svc), {"Fault": fault, "Service": svc, "Damage": 0, "Label": "",
                                                    "Effect": [], "Tier": entry["tier"]})
            cell["Effect"].append(e["what"])
            if level > cell["Damage"]:
                cell["Damage"], cell["Label"] = level, label
    rows = [{**c, "Effect": "; ".join(c["Effect"])} for c in cells.values()]
    return pd.DataFrame(rows, columns=["Fault", "Service", "Damage", "Label", "Effect", "Tier"])


def service_rows(usual: dict, now: dict) -> pd.DataFrame:
    """Service x (errors, slower, traffic) right now against usual, with a damage level per cell."""
    rows = []
    for svc in sorted(set(usual["services"]) | set(now["services"])):
        u, n = usual["services"].get(svc, {}), now["services"].get(svc, {})
        pct = lambda d: 100 * d["errors"] / d["calls"] if d.get("calls") else 0.0
        err, was = pct(n), pct(u)
        e_level = 0 if err <= was or err < 0.1 else 1 if err < 5 else 2 if err < 25 else 3
        rows.append({"Service": svc, "Check": "Errors", "Damage": e_level,
                     "Label": f"{err:.1f}%" if e_level else "", "Effect": f"now {err:.1f}%, usual {was:.1f}%"})
        x = n["p95_ms"] / u["p95_ms"] if n.get("p95_ms") and u.get("p95_ms") else 1.0
        s_level = 3 if x >= 10 else 2 if x >= 2 else 1 if x >= 1.5 else 0
        rows.append({"Service": svc, "Check": "Slower", "Damage": s_level, "Label": f"{x:.0f}x" if s_level else "",
                     "Effect": f"p95 now {n.get('p95_ms', '-')} ms, usual {u.get('p95_ms', '-')} ms"})
        r = n.get("rps", 0.0) / u["rps"] if u.get("rps", 0) >= bank.MIN_RPS else 1.0
        t_level = 3 if r <= bank.STARVED else 1 if r <= 0.8 else 0
        rows.append({"Service": svc, "Check": "Traffic", "Damage": t_level, "Label": f"-{1 - r:.0%}" if t_level else "",
                     "Effect": f"now {n.get('rps', 0)} req/s, usual {u.get('rps', '-')} req/s"})
    return pd.DataFrame(rows)


def chart(df: pd.DataFrame, x: str, y: str, x_order: list, y_order: list) -> alt.LayerChart:
    """A labelled heatmap; hover a cell for the measured numbers."""
    base = alt.Chart(df).encode(
        x=alt.X(f"{x}:N", sort=x_order, title=None, axis=alt.Axis(orient="top", labelAngle=0, labelLimit=140)),
        y=alt.Y(f"{y}:N", sort=y_order, title=None, axis=alt.Axis(labelLimit=220)))
    cells = base.mark_rect().encode(
        color=alt.Color("Damage:Q", scale=alt.Scale(domain=[0, TOP]), legend=None),
        tooltip=[alt.Tooltip(f"{y}:N"), alt.Tooltip(f"{x}:N"), alt.Tooltip("Effect:N")])
    labels = base.mark_text(fontSize=11).encode(text="Label:N")
    return (cells + labels).properties(height=alt.Step(28))


def blast_chart(entries: dict) -> alt.LayerChart | None:
    df = blast_rows(entries)
    if df.empty:
        return None
    order = {"high": 0, "medium": 1, "low": 2}
    faults = sorted(df["Fault"].unique(), key=lambda f: (order[entries[f]["tier"]], -df[df.Fault == f]["Damage"].sum(), f))
    services = sorted(df["Service"].unique(), key=lambda s: (s != SHOP, -df[df.Service == s]["Damage"].sum(), s))
    return chart(df, "Service", "Fault", services, faults)


def service_chart(usual: dict, now: dict) -> alt.LayerChart:
    df = service_rows(usual, now)
    total = df.groupby("Service")["Damage"].sum()
    services = sorted(total.index, key=lambda s: (-total[s], s))
    return chart(df, "Check", "Service", ["Errors", "Slower", "Traffic"], services)


def worst(entry: dict) -> str:
    """The one effect that says most about a fault: whole-shop damage first, then the worst level."""
    effs = entry["effects"]
    if not effs:
        return "no detectable effect"
    return max(effs, key=lambda e: (e["kind"] in WHOLE, damage(e)[0]))["what"]
