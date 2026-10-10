"""Chaos console. Run from the repo root: uv run streamlit run app.py"""

import json
import subprocess
from pathlib import Path

import streamlit as st

import depmap

RECORDED = Path("refs/dependency-map.json")  # live map captured on the Arch box

st.set_page_config(page_title="Chaos console", layout="wide")


@st.cache_data(ttl=60, show_spinner="Reading traces and cluster config")
def load_map() -> tuple[dict, str]:
    try:
        return depmap.build(*depmap.fetch()), "Live: Jaeger traces (last 15 min) + kubectl"
    except (OSError, ValueError, subprocess.CalledProcessError):
        # ponytail: no cluster on this machine, so show the map recorded on the Arch box
        return depmap.prune(json.loads(RECORDED.read_text())), f"Recorded on the Arch box ({RECORDED})"


graph, source = load_map()
nodes, edges = graph["nodes"], graph["edges"]
with open("docs/official_edges.json") as f:
    documented = json.load(f)["edges"]
cov = depmap.coverage(graph, documented)

st.title("Dependency map")
st.caption(f"{source}. Cylinders are data stores, dashed links come from config only "
           "(databases and queues leave no traces), bold marks a risk.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Services", len(nodes))
c2.metric("Traced calls", f"{sum(e['calls'] or 0 for e in edges):,}")
c3.metric("Links found only in config", sum(e["source"] == "env" for e in edges))
c4.metric("Official diagram edges found", f"{len(cov['found'])} / {len(documented)}")

left, right = st.columns([7, 5])
with right:
    focus = st.selectbox("Focus on a service", ["Whole shop", *nodes])
    show_flags = st.toggle("Show feature-flag links (flagd)", value=focus == "flagd")

    risky = sorted((n for n in nodes.items() if {"no-persistence", "hub"} & set(n[1]["flags"])),
                   key=lambda kv: -len(kv[1]["callers"]))
    st.subheader("Riskiest targets")
    st.dataframe([{"Service": name, "Callers": len(n["callers"]), "Data store": n["store"] or "",
                   "Risk": ", ".join(f for f in n["flags"] if f != "single-replica")}
                  for name, n in risky], hide_index=True, width="stretch")
    st.caption("Every service runs a single replica, so that flag is left out.")

    if focus != "Whole shop":
        with st.container(border=True):
            st.subheader(focus)
            inbound = [e for e in edges if e["to"] == focus]
            outbound = [e for e in edges if e["from"] == focus]
            calls = lambda e: f"{e['calls']:,} calls" if e["calls"] else "config"
            st.write("**Called by:** " + (", ".join(f"{e['from']} ({calls(e)})" for e in inbound) or "nobody"))
            st.write("**Calls:** " + (", ".join(f"{e['to']} ({calls(e)})" for e in outbound) or "nothing"))

with left:
    shown = [e for e in edges
             if (show_flags or "flagd" not in (e["from"], e["to"]))
             and (focus == "Whole shop" or focus in (e["from"], e["to"]))]
    keep = {n for e in shown for n in (e["from"], e["to"])} | ({focus} - {"Whole shop"})
    if focus == "Whole shop":
        keep |= set(nodes)  # isolated services stay visible
    st.graphviz_chart(depmap.to_dot({"nodes": {k: v for k, v in nodes.items() if k in keep},
                                     "edges": shown}), width="stretch")

with st.expander(f"Compared with the official architecture diagram: "
                 f"{len(cov['missing'])} missing, {len(cov['extra'])} extra"):
    st.write("**Missing:** " + (", ".join(f"{a} → {b}" for a, b in cov["missing"]) or "none"))
    st.write("**Extra (real, but not in the diagram):** "
             + ", ".join(f"{a} → {b}" for a, b in cov["extra"]))
