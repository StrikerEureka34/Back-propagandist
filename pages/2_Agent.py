"""Agent session: pick faults from the bank, the planner orders them, a person approves every run,
sub-agents explain each result and propose one fix per root cause. Every number comes from
judge.py rules, never from a model.

The agent runs as its own process (agent.py --ui), so this page stays responsive: it reads
runs/session-*/progress.json every 2 s and answers approvals by writing decision.json.
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_sortables import sort_items

import agent_flow
import bank
import chaos
import judge
from agent import how_scores_work, short

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
STAGES = {"starting": "Starting the agent", "plan": "Planned", "run_next": "Running",
          "fix": "Writing fixes", "done": "Done"}

st.set_page_config(page_title="Agent session", layout="wide")
st.title("Agent session")


def read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


OWN = " · model's own estimate "


def conf(value, prefix: str = " · confidence ") -> str:
    """The model's own confidence, or nothing when no model answered."""
    return f"{prefix}{value:.0%}" if isinstance(value, (int, float)) else ""


@st.cache_data(ttl=10, show_spinner=False)
def cluster_up() -> bool:
    return chaos.probe_once(f"{chaos.SHOP}/api/products")[0]


def pid_alive(pid) -> bool:
    """Is the agent still running? After a page reload the Popen handle is gone, so check its pid.
    POSIX only: on Windows os.kill(pid, 0) would terminate the process, so assume it's alive."""
    if not isinstance(pid, int) or os.name == "nt":
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def sessions() -> list[Path]:
    return sorted((p.parent for p in RUNS.glob("session-*/progress.json")), reverse=True)


def launch(pool: list[str], budget: int, replay: bool, auto: bool, pairs: bool):
    out = RUNS / f"session-{datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-u", str(ROOT / "agent.py"), "--pool", ",".join(pool), "--budget", str(budget),
           "--ui", "--out", str(out)]
    if replay:
        cmd += ["--replay", str(bank.BANK)] + (["--auto-approve"] if auto else [])
    if pairs:
        cmd += ["--pairs"]
    log = open(out / "agent.log", "w", encoding="utf-8")
    st.session_state["proc"] = subprocess.Popen(
        cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env={**os.environ, "PYTHONUTF8": "1"},
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        start_new_session=os.name != "nt")
    st.session_state["session_dir"] = str(out)
    st.session_state["mode"] = "replay" if replay else "live"
    st.rerun()


def decide(out: Path, choice: str):
    tmp = out / "decision.tmp"
    tmp.write_text(json.dumps({"decision": choice}), encoding="utf-8")
    os.replace(tmp, out / "decision.json")


# ---------------------------------------------------------------- 1 pick

def pick():
    rated = bank.load()
    ranked = {r["id"]: r for r in judge.rank(rated)}
    exps = [e for e in chaos.load_experiments() if "expect" not in e and e["scenario"] != "flagd"]
    st.caption("The planner (Groq gpt-oss-120b) orders the faults you pick by expected leverage. You approve "
               "every run. An analyst (Groq gpt-oss-20b) explains each result, and a fixer proposes one fix "
               "per root cause; OpenRouter nemotron steps in if Groq fails. Every number on this page comes "
               "from rules (judge.py), never from a model.")
    st.header("1. Pick the faults")
    left, right = st.columns([7, 5])
    with right:
        with st.container(border=True):
            mode = st.radio("Mode", ["Replay the recorded bank", "Live on the cluster"],
                            help="Replay reuses past results, no cluster needed. Live injects real faults.")
            replay = mode.startswith("Replay")
            live_ok = cluster_up()
            if not replay and not live_ok:
                st.error(f"The shop at {chaos.SHOP} isn't answering. Live runs need the cluster (the Arch box).")
            budget = st.number_input("Run budget", min_value=1, max_value=len(exps), value=min(8, len(exps)),
                                     help="Max faults to run, one at a time. Live: about 6 min each.")
            auto = st.checkbox("Approve every run automatically", disabled=not replay,
                               help="Replay only. Live runs always wait for you.")
            pairs = st.checkbox("Also test fault pairs", help="Two faults at once, from safe pairs only. You still approve each.")
            controls = [f"{e['control']['expected']} expected, {'pass' if e['control']['pass'] else 'FAIL'}"
                        for e in rated.values() if "control" in e]
            st.caption(f"Calibration: {len(controls)} known-answer controls in the bank, "
                       f"{sum('pass' in c for c in controls)} pass. If one fails, the measurement is broken.")
    with left:
        rows = [{"Run": e["id"] in ranked, "Fault": e["id"], "What it does": e.get("note") or e["scenario"],
                 "Strength": judge.strength(e), "Measured": ranked[e["id"]]["tier"] if e["id"] in ranked else "not rated",
                 "Leverage": ranked[e["id"]]["leverage"] if e["id"] in ranked else None,
                 "Root cause": ranked[e["id"]]["cause"] if e["id"] in ranked else ""} for e in exps]
        table = st.data_editor(
            pd.DataFrame(rows), hide_index=True, width="stretch", height="content", key="pool_editor",
            column_order=("Run", "Fault", "Measured", "Leverage", "What it does"), placeholder="-",
            disabled=["Fault", "What it does", "Strength", "Measured", "Leverage", "Root cause"],
            column_config={"Run": st.column_config.CheckboxColumn("Run", width="small"),
                           "Leverage": st.column_config.NumberColumn(format="%.2f",
                                                                     help="Damage ÷ how hard we pushed.")})
        pool = table.loc[table["Run"], "Fault"].tolist()
        unrated = [i for i in pool if i not in ranked]
        if replay and unrated:
            pool = [i for i in pool if i in ranked]
            st.caption(f"Replay leaves out {', '.join(unrated)}: not rated in the bank yet.")
        st.caption("Measured and leverage come from earlier runs in the bank (bank.json). The planner doesn't see "
                   "them in replay, so its predictions are a real test. Controls aren't listed: they check the scale.")
    with right:
        if st.button("Start session", type="primary", disabled=not pool or (not replay and not live_ok),
                     width="stretch"):
            launch(pool, min(int(budget), len(pool)), replay, auto, pairs)
    st.header("How the agent works")
    agent_flow.show(model={"planner": "gpt-oss-120b", "analyst": "gpt-oss-20b"})
    earlier = sessions()
    if earlier:
        with st.expander("Open an earlier session"):
            choice = st.selectbox("Session", earlier, format_func=lambda p: p.name)
            if st.button("Open"):
                st.session_state["session_dir"] = str(choice)
                st.session_state.pop("proc", None)
                st.rerun()


# ---------------------------------------------------------------- 2 run (live view)

def predicted(item: dict) -> str:
    """'medium (80%)': the planner's tier and its own confidence, in one cell."""
    c = item.get("confidence")
    return (item.get("predicted") or "-") + (f" ({c:.0%})" if isinstance(c, (int, float)) else "")


def source(item: dict) -> str:
    """Who put a run in the queue: the planner, the rules (planner left it out), or an analyst's lead."""
    if item.get("source"):
        return item["source"] + (" (not in pool)" if "not in the pool" in (item.get("reason") or "") else "")
    return "rules" if item.get("ranked_by") == "rules" else "planner"


def runs_table(results: list[dict], queue: list[dict], left: int = 0) -> pd.DataFrame:
    """Finished runs, then the queue: the first `left` items run this session, the rest don't."""
    rows = [{"Fault": r["id"], "Source": source(r["item"]), "Measured": r["tier"] if "tier" in r else r["entry"]["tier"],
             "Predicted": predicted(r["item"]),
             "Hypothesis held?": {True: "yes", False: "no"}.get(r["analysis"].get("hypothesis_held"), "-"),
             "Hypothesis": r["item"].get("hypothesis")} for r in results]
    rows += [{"Fault": "+".join(q["ids"]), "Source": source(q), "Measured": "up next" if n < left else "next session",
              "Predicted": predicted(q), "Hypothesis held?": "", "Hypothesis": q.get("hypothesis")}
             for n, q in enumerate(queue)]
    return pd.DataFrame(rows)


def analyst_notes(results: list[dict], newest_first: bool = False):
    for r in (reversed(results) if newest_first else results):
        a = r["analysis"]
        tier = r["tier"] if "tier" in r else r["entry"]["tier"]
        with st.expander(f"{r['id']}: measured {tier}"):
            st.write(a.get("what_happened") or "-")
            st.write(f"Why: {a.get('why') or '-'}")
            if a.get("flag"):
                st.warning(a["flag"])
            check = a.get("check")
            if check:
                disproved = [why for ok, why in check["checks"] if not ok and "bank measured" in why]
                if disproved:
                    st.warning("Contradicts the measurement: " + "; ".join(disproved))
                st.caption(f"Evidence check {check['pct']}%", help="  \n".join(  # markdown line breaks
                    f"{'✓' if ok else '✗'} {why}" for ok, why in check["checks"]))
            by = short(a["_by"]) if a.get("_by") else "rules" if str(a.get("why", "")).startswith("(no AI)") else ""
            st.caption((f"By {by}. " if by else "") + f"Evidence: {', '.join(a.get('evidence', [])) or 'none cited'}"
                       + conf(a.get("confidence"), ". Model's own estimate (unchecked) ") + ".")


@st.fragment(run_every=2)
def watch(out: Path):
    progress = read(out / "progress.json") or {"stage": "starting", "results": [], "queue": [], "budget": "?"}
    pending = read(out / "pending.json")
    proc = st.session_state.get("proc")
    if (out / "session.json").exists():
        st.rerun()  # finished: switch to the results view
    gone = proc.poll() is not None if proc is not None else not pid_alive(progress.get("pid"))
    if gone:
        log = (out / "agent.log").read_text(encoding="utf-8", errors="replace")[-1500:]
        code = f" (exit {proc.returncode})" if proc is not None else ""
        st.error(f"The agent stopped before finishing{code}. Last lines of its log:")
        st.code(log)
        return
    results, queue = progress.get("results", []), progress.get("queue", [])
    head, kill = st.columns([4, 1], vertical_alignment="center")
    head.header("2. Run")
    if chaos.stop_requested():
        st.warning("Emergency stop pressed. The running fault is stopped and cleaned up within about a second, "
                   "nothing new starts, and the agent writes the report from the runs so far.")
    elif kill.button(":red[Emergency stop]", key=f"kill-{out.name}", width="stretch",
                     help="Immediately stops the fault that is running, removes anything it left in the shop, "
                          "cancels any run waiting for your approval, and ends the session. The report is "
                          "written from the runs finished so far."):
        chaos.RUNS.mkdir(exist_ok=True)
        (chaos.RUNS / "STOP").write_text("")  # what every runner and wait checks
        st.rerun(scope="fragment")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Runs", f"{len(results)} / {progress.get('budget')}")
    b = progress.get("budget")
    budget = b if isinstance(b, int) else len(queue)
    left = max(0, min(budget - len(results), len(queue)))
    c2.metric("Still to run", left, help=f"Budget: {budget} runs.")
    c3.metric("Planner", "-" if progress.get("plan_ai") is None else short(progress.get("plan_by"))
              if progress["plan_ai"] else "rules (no AI)", help="The model that made the plan.")
    c4.metric("Status", "Waiting for you" if pending else STAGES.get(progress["stage"], progress["stage"]))
    if pending:
        with st.container(border=True):
            n = len(results) + 1
            st.subheader(f"Run {n}: {'+'.join(pending['ids'])}")
            src = pending.get("source") or ""
            if src.startswith("analyst"):
                st.badge("Analyst follow-up", color="gray")
                st.write(f"Suggested by the analyst after **{src.removeprefix('analyst after ')}**."
                         + (" It is not in the pool you picked, so it only runs if you approve it."
                            if "not in the pool" in (pending.get("reason") or "") else ""))
            st.write(pending.get("hypothesis") or "-")
            st.caption((f"Predicted {pending['predicted']}{conf(pending.get('confidence'))} · "
                        if pending.get("predicted") else "") + f"why: {pending.get('reason') or '-'}")
            st.caption("Kill switch: blast radius, STOP and Ctrl+C always; error and latency limits from "
                       "experiments.toml (traffic-spike: blast radius and STOP only).")
            b1, b2, b3 = st.columns(3)
            key = f"{out.name}-{n}"
            if b1.button("Approve and run", type="primary", key=f"approve-{key}", width="stretch"):
                decide(out, "approve")
            if b2.button("Skip this one", key=f"skip-{key}", width="stretch"):
                decide(out, "skip")
            if b3.button("Stop the session", key=f"stop-{key}", width="stretch"):
                decide(out, "stop")
    elif progress["stage"] == "starting":
        st.info("The planner is ordering the faults. This takes up to a minute.")
    elif progress["stage"] == "plan":
        st.info("Planned. The first approval card appears here in a moment.")
    elif progress["stage"] == "run_next" and not pending:
        st.info("A fault is running, or the analyst is explaining the last one. Live runs take 6 to 7 "
                "minutes each, including a cool-down so faults don't blur each other's baseline.")
    if st.toggle("Show the flow", key=f"flow-toggle-{out.name}",
                 help="The agent's steps as a diagram. The step running now is outlined."):
        agent_flow.show(progress, pending,
                        model={"planner": short(progress["plan_by"])} if progress.get("plan_by") else {})
    if st.session_state.get("mode") == "live":
        st.page_link("pages/1_Live_run.py", label="Watch the shop live: probe chart and per-service health")
    if results or queue:
        st.dataframe(runs_table(results, queue, left), hide_index=True, width="stretch", height="content")
        if len(queue) > left:
            st.caption(f"Only the first {budget} faults run, one at a time, in this order. The other "
                       f"{len(queue) - left} don't run this session. Pairs run only when 'Also test fault "
                       "pairs' was ticked at the start.")
        if len(queue) > 1 and not chaos.stop_requested():
            reorder(out, queue, left)
    analyst_notes(results, newest_first=True)


def drag_style(left: int) -> str:
    """The drag list in the theme's colours and font, read from .streamlit/config.toml (no hex values
    here). Items are numbered, and the ones past the budget are dashed and marked."""
    o = st.get_option
    font, _, url = str(o("theme.font")).partition(":")  # "'IBM Plex Sans':https://fonts..." (the iframe has no page fonts)
    return (f"@import url('{url}');" if url else "") + (
        f".sortable-component {{background: {o('theme.backgroundColor')}; border: none; padding: 0;}}"
        f".sortable-container-body {{background: {o('theme.backgroundColor')}; padding: 0; counter-reset: n;}}"
        f".sortable-item, .sortable-item:hover {{background: {o('theme.secondaryBackgroundColor')}; "
        f"color: {o('theme.textColor')}; border: 1px solid {o('theme.borderColor')}; "
        f"border-radius: {o('theme.baseRadius')}; font-family: {font or 'sans-serif'}, sans-serif; font-size: 14px; "
        "text-align: left; margin: 0 0 4px; padding: 8px 12px;}"
        f".sortable-item:hover {{border-color: {o('theme.textColor')};}}"
        f".sortable-item:focus-visible {{outline: 2px solid {o('theme.primaryColor')}; outline-offset: 2px;}}"
        ".sortable-item::before {counter-increment: n; content: counter(n) \".\\00a0\\00a0\";}"
        f".sortable-item:nth-child(n+{left + 1}) {{border-style: dashed; opacity: .55;}}"
        f".sortable-item:nth-child(n+{left + 1})::after {{content: \"\\00a0\\00a0·\\00a0not this session\";}}")


def reorder(out: Path, queue: list[dict], left: int):
    """A person drags the planner's queue into another order. The agent reads order.json before each
    run, and a card waiting for approval makes way for the new first fault."""
    keys = ["+".join(q["ids"]) for q in queue]
    # a toggle, not an expander: the component measures its height when it mounts, and inside a
    # collapsed expander that is 0 px (design review, 2026-10-11)
    if not st.toggle("Change the run order", key=f"reorder-{out.name}"):
        return
    st.caption(f"Drag a fault up or down. The top {left} run this session. If a run is waiting for your "
               "approval, it is replaced by the new first fault.")
    # a new queue (the agent applied an order, or a run finished) starts a fresh list
    dragged = sort_items(keys, direction="vertical", custom_style=drag_style(left),
                         key=f"order-{out.name}-{'|'.join(keys)}")
    saved = read(out / "order.json")
    if dragged != keys and dragged != saved:  # write once per drag: every write re-asks a waiting card
        tmp = out / "order.tmp"
        tmp.write_text(json.dumps(dragged), encoding="utf-8")
        os.replace(tmp, out / "order.json")  # one step: the agent never reads half a file
        st.toast(f"New order saved. Next up: {dragged[0]}.")


# ---------------------------------------------------------------- 3 results

def results_view(out: Path):
    s = read(out / "session.json")
    if s is None:
        st.error(f"Can't read {out / 'session.json'}.")
        return
    results = s["results"]
    entries = [r["entry"] for r in results]
    preds = {r["id"]: r["item"]["predicted"] for r in results if r["item"].get("predicted")}
    hits, judged = judge.hit_rate(preds, {r["id"]: r["entry"] for r in results})
    # recomputed from the stored measurements, so sessions saved before a rule change show today's reasoning
    ranked = judge.rank({r["id"]: r["entry"] for r in results}, preds)
    targets = {e["id"]: e["target"] for e in chaos.load_experiments()}
    for r in results:
        if "check" not in r["analysis"]:
            pct, checks = judge.check_note(r["analysis"], r["entry"], targets.get(r["id"].split("+")[0], ""))
            r["analysis"]["check"] = {"pct": pct, "checks": [[ok, why] for ok, why in checks]}
    st.header("3. Results")
    st.caption(f"Session {out.name}" + (f" · stopped: {s['stopped']}" if s.get("stopped") else ""))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Resilience score", f"{judge.resilience(entries)} / 100",
              help="How much of what customers need held up. 100 = nothing broke.")
    c2.metric("Root causes found", len(judge.root_causes(ranked)),
              help="Separate weaknesses found by small faults.")
    blind = s.get("plan_blind")
    c3.metric("Planner hit rate", f"{hits} / {judged}" if judged else "not scored",
              help="Guesses the planner got right. " + (
                  "It guessed blind." if blind else "It saw past results, so it's partly memory." if blind is False
                  else ""))
    c4.metric("Runs", f"{len(results)} / {s['budget']}")
    with st.container(border=True):
        st.write(s["summary"]["text"])
        no_ai = s["summary"]["text"].startswith("(no AI)")
        st.caption("Written by rules: no model answered." if no_ai else
                   f"Summary by {short(s['summary']['by']) if s['summary'].get('by') else 'the planner model'}. "
                   "Every number on this page comes from judge.py.")
    with st.container(horizontal=True):
        report = (out / "report.md").read_text(encoding="utf-8")
        st.download_button("Download report.md", report, file_name=f"{out.name}-report.md",
                           mime="text/markdown", type="primary")
        if st.button("New session"):
            for k in ("session_dir", "proc", "mode"):
                st.session_state.pop(k, None)
            st.rerun()

    with st.expander("How the scores work"):
        st.markdown("\n".join(how_scores_work()))
        grid = {r["id"]: {row["slo"]: ("✓" if row["held"] else "✗") for row in judge.slo_rows(r["entry"])}
                for r in results}
        st.dataframe(pd.DataFrame([{"SLO": slo, "Points": pts, **{i: grid[i][slo] for i in grid}}
                                   for slo, pts, _, _ in judge.SLOS]), hide_index=True, width="stretch",
                     height="content")
        st.caption("Each run's SLOs: ✓ held, ✗ broken. The broken ones, with the effect behind them, are in the "
                   "findings table.")

    st.subheader("Findings, ranked by leverage")
    found = judge.findings(ranked)
    number = {r["id"]: n for n, r in enumerate(found, 1)}
    notes = {r["id"]: r["analysis"] for r in results}
    st.dataframe(pd.DataFrame([{
        "#": n, "Fault": r["id"], "Tier": r["tier"], "Strength": r["strength"],
        "Leverage": judge.leverage_text(r), "SLO points": f"{r['score'][0]} / {r['score'][1]}",
        "Broken SLOs": ", ".join(r["broken"]) or "none",
        "Root cause": r["cause"] + (f" (same cause as #{number[r['repeat_of']]})" if r.get("repeat_of") in number else ""),
        "Decided by": r["decided_by"],
        "Evidence check": f"{notes[r['id']]['check']['pct']}%" if notes[r["id"]].get("check") else "-",
    } for n, r in enumerate(found, 1)]), hide_index=True, width="stretch", height="content", column_config={
        "Tier": st.column_config.TextColumn(help="How bad it was for customers, as measured."),
        "Strength": st.column_config.TextColumn(help="How hard we pushed: mild, targeted or broad."),
        "Leverage": st.column_config.TextColumn(help="Damage ÷ push. Big damage from a small push ranks first."),
        "SLO points": st.column_config.TextColumn(help="Checks that held, out of the total."),
        "Root cause": st.column_config.TextColumn(help="Same tag, likely the same fix."),
        "Decided by": st.column_config.TextColumn(help="The measurement behind the root cause."),
        "Evidence check": st.column_config.TextColumn(help="How well the AI's note matches the data."),
    })
    st.caption("Why each one broke is in the analyst notes below.")

    st.subheader("Fixes, one per root cause")
    groups = list(s["groups"].items())
    for i in range(0, len(groups), 2):
        for col, (cause, ids) in zip(st.columns(2), groups[i:i + 2]):
            f = s["fixes"][cause]
            with col.container(border=True):
                st.write(f"**{cause}**: {', '.join(ids)}")
                st.write(f.get("fix") or "-")
                if f.get("change") and f.get("change") not in ("-", f.get("fix")):
                    st.caption(f"Change: {f['change']}")
                st.caption(f"Verify with {f.get('verify_with')}{conf(f.get('confidence'), OWN)} · "
                           f"{'from the fix catalog' if f.get('catalog_match') else 'not in the fix catalog'}")

    left, right = st.columns([7, 5])
    with left:
        st.subheader("Runs, in the planner's order")
        st.dataframe(runs_table(results, []), hide_index=True, width="stretch", height="content")
    with right:
        st.subheader("Analyst notes")
        analyst_notes(results)
    left, right = st.columns([7, 5])
    with left:
        st.subheader("Suggested next")
        for n in s.get("next", []):
            st.write(f"`{'+'.join(n['ids'])}`: {n.get('why') or '-'}")
            st.caption(f"Suggested by the {n.get('source')}{conf(n.get('confidence'), OWN)}")
        if not s.get("next"):
            st.write("Nothing suggested.")
        if s.get("not_run"):
            st.caption(f"Not run this session (over the budget, not ranked by the planner): {', '.join(s['not_run'])}.")
    with right:
        if s["summary"].get("ideas"):
            st.subheader("Ideas")
            st.caption("Not runnable until someone adds them to experiments.toml.")
            for idea in s["summary"]["ideas"]:
                st.write(f"- {idea}")
        not_run = [f"{d}: dropped by validation" for d in s.get("dropped", [])] + s.get("skipped", [])
        if not_run:
            st.subheader("Not run")
            for line in not_run:
                st.write(f"- {line}")


current = st.session_state.get("session_dir")
if not current:
    pick()
elif (Path(current) / "session.json").exists():
    results_view(Path(current))
else:
    watch(Path(current))
