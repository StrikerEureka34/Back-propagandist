"""The agent's flow as an animated, clickable diagram: who does each step (a person, code, a model, or
the cluster), what guards it, and, in a live session, which step is running. The page is agent_flow.html,
rendered as a Streamlit component; this module fills it with the steps, the live session and the theme's
colours and fonts (no colour values here)."""

import json
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

TEMPLATE = Path(__file__).with_name("agent_flow.html")
ROLE_COLOR = {"person": 0, "code": 1, "cluster": 2, "model": 3}  # chartCategoricalColors; 4 is too close to 0

# id: (title, role, subtitle, (column, row), what it does, what guards it)
STEPS = {
    "pick": ("You pick the pool", "person", "faults, run budget, pairs on or off", (0, 0),
             "Choose which faults from the bank the agent may use, how many runs it gets, and whether it may "
             "test two faults at once.",
             "Controls never enter the pool. The budget caps the session."),
    "planner": ("Planner", "model", "orders the faults by leverage", (1, 0),
                "Ranks every fault (and every allowed pair) by expected leverage: the most customer impact from "
                "the weakest fault. Writes a testable hypothesis, a predicted tier, a reason and a confidence.",
                "It can only name faults and pairs the code offers; anything else is dropped. Faults it leaves "
                "out are added by rules, mildest first."),
    "queue": ("Queue and guards", "code", "the run order, checked by code", (2, 0),
              "Holds the run order: the planner's, then your drag-and-drop changes, then analyst follow-ups. "
              "judge.py builds the pairs that are allowed.",
              "Never two broad faults together, never the same target twice, never a control. One fault at a "
              "time across the whole machine (run lock)."),
    "approve": ("You approve each run", "person", "approve, skip or stop", (3, 0),
                "Every fault waits on a card until a person approves, skips or stops it. Emergency stop ends "
                "the whole session at any point.",
                "Nothing reaches the cluster without a person's click."),
    "fault": ("Fault and kill switch", "cluster", "krkn breaks one thing", (3, 1),
              "chaos.py starts the fault with krkn (a pod killed, a network cut, a dependency answering "
              "garbage, a slow node) and checks the shop every second.",
              "It stops itself when errors or slowness pass the limits, when a pod outside the target goes "
              "down, at the time limit, or on STOP, then cleans up what krkn left."),
    "measure": ("Measure and rate", "code", "Prometheus, before vs during", (2, 1),
                "bank.measure() compares every service's errors, slowness, traffic, CPU and memory with a quiet "
                "window before the fault, waits for the damage to clear, and rates it high, medium or low.",
                "Every number comes from rules, never from a model. Two known-answer controls check the scale."),
    "analyst": ("Analyst", "model", "explains what broke", (1, 1),
                "Explains what broke and why in plain words, says whether the hypothesis held, cites its "
                "evidence, and may suggest one follow-up fault.",
                "The measured tier is final, and judge.py checks each note against the evidence. A follow-up "
                "must be a known, non-broad fault that hasn't run; at most 2 per session."),
    "judge": ("Root causes and scores", "code", "judge.py, after the last run", (1, 2),
              "Groups the findings by root cause, ranks them by leverage (impact divided by fault strength) and "
              "computes krkn's resilience score for the pool.",
              "Two scores, never mixed: leverage ranks findings, the resilience score rates the system, so "
              "breaking everything can't win."),
    "fixer": ("Fixer", "model", "one fix per root cause", (2, 2),
              "Proposes one fix per root cause, from the fix catalog when a row matches, and names the fault "
              "that would prove the fix.",
              "The fault it names must exist in the bank, so the fix can be re-run and checked."),
    "report": ("Report", "model", "summary over the ranked findings", (3, 2),
               "The planner model writes the summary; report.md and session.json are saved with every number "
               "and the run files they come from.",
               "The ranking and the numbers are given to the model; it can't change them."),
}
# (from, to, side it leaves, side it enters, label). Row 0 runs right, row 1 runs back left, row 2 right.
EDGES = [("pick", "planner", "right", "left", ""), ("planner", "queue", "right", "left", ""),
         ("queue", "approve", "right", "left", ""), ("approve", "fault", "bottom", "top", "approved"),
         ("fault", "measure", "left", "right", ""), ("measure", "analyst", "left", "right", ""),
         ("analyst", "queue", "top", "bottom", "next run, or its follow-up"),
         ("analyst", "judge", "bottom", "top", "budget used or stopped"),
         ("judge", "fixer", "right", "left", ""), ("fixer", "report", "right", "left", "")]


def active_step(progress: dict | None, waiting: bool) -> str | None:
    """Which step a live session is on, from its progress file. None outside a session."""
    stage = (progress or {}).get("stage")
    if stage in ("starting", "plan"):
        return "planner" if stage == "starting" else "queue"
    if stage == "run_next":
        return "approve" if waiting else "fault"
    return {"fix": "fixer", "done": "report"}.get(stage)


def _theme() -> dict:
    o = st.get_option
    colors = o("theme.chartCategoricalColors")
    font, _, font_url = str(o("theme.font")).partition(":")
    heading, _, heading_url = str(o("theme.headingFont")).partition(":")
    return {"bg": o("theme.backgroundColor"), "surface": o("theme.secondaryBackgroundColor"),
            "ink": o("theme.textColor"), "line": o("theme.borderColor"), "signal": o("theme.primaryColor"),
            "radius": o("theme.baseRadius"), "font": font, "heading": heading,
            "imports": [u for u in (font_url, heading_url) if u],
            "roles": {role: colors[i] for role, i in ROLE_COLOR.items()}}


def show(progress: dict | None = None, pending: dict | None = None, model: dict | None = None, height: int = 700):
    """The diagram and its details panel. `model` names the model per step, e.g. {"planner": "gpt-oss-120b"};
    in a live session the running step ripples and the panel opens on it."""
    active = active_step(progress, bool(pending))
    data = {"active": active,
            "steps": {sid: {"title": t, "role": r, "sub": sub, "at": at, "what": what, "guards": guards,
                            "model": (model or {}).get(sid)}
                      for sid, (t, r, sub, at, what, guards) in STEPS.items()},
            "edges": [{"from": a, "to": b, "out": o, "in": i, "label": label} for a, b, o, i, label in EDGES],
            "live": {sid: live(sid, progress or {}, pending) for sid in STEPS}}
    safe = lambda d: json.dumps(d).replace("</", "<\\/")  # nothing in the data can close the script tag
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/null", safe(data)).replace("/*THEME*/null", safe(_theme()))
    components.html(html, height=height, scrolling=False)


def live(sid: str, progress: dict, pending: dict | None) -> list[str]:
    """What this step produced in the current session, from the progress file."""
    results, queue = progress.get("results", []), progress.get("queue", [])
    last = results[-1] if results else None
    if sid == "planner" and queue:
        return [f"- {'+'.join(q['ids'])}: {q.get('hypothesis') or '-'}" for q in queue[:3]]
    if sid == "queue" and queue:
        return ["Up next: " + ", ".join("+".join(q["ids"]) for q in queue[:6])]
    if sid == "approve" and pending:
        return [f"Waiting for you: {'+'.join(pending['ids'])}"]
    if sid in ("fault", "measure") and last:
        return [f"Last run: {last['id']} rated {last['tier']}"] + [f"- {e}" for e in last.get("effects", [])[:3]]
    if sid == "analyst" and last:
        a = last.get("analysis", {})
        return [f"On {last['id']}: {a.get('what_happened') or '-'}"] + (
            [f"Follow-up: {a['follow_up_status']}"] if a.get("follow_up_status") else [])
    return []
