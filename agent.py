"""The agent: an orchestrator plans which faults to run, a person approves every run, sub-agents
explain each result and propose fixes, and the orchestrator writes the ranked report.

    uv run python agent.py --replay bank.json --auto-approve      # no cluster: replays rated faults
    uv run python agent.py --pool blast-loss,cart-wipe --budget 8  # live, on the Arch box

The code decides the order and enforces safety. The LLM ranks, writes hypotheses and explains.
Every number in the report comes from judge.py rules, never from a model. One fresh sub-agent
per task, one after another: the cluster runs one fault at a time anyway.
"""

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph

import bank
import chaos
import depmap
import judge
import llm

ROOT = Path(__file__).parent
CACHE = ROOT / "runs" / "llm-cache"
DOCS = {"service-facts": ROOT / "docs" / "service-facts.md", "fix-catalog": ROOT / "docs" / "fix-catalog.md"}
# Each role's provider first, then the other one as the fallback. Models: provider defaults in llm.py
# (groq: gpt-oss-120b, openrouter: nemotron), or ORCHESTRATOR_MODEL / WORKER_MODEL in .env.
ROLES = {"orchestrator": ("groq", "openrouter"), "worker": ("openrouter", "groq")}
# Reasoning tokens count against max_tokens, so too little cuts the JSON off. Groq's free tier
# caps tokens per minute at 8k including the prompt; OpenRouter's nemotron thinks out loud first.
MAX_TOKENS = {"groq": 4500, "openrouter": 6000}
BRIEF = " Keep every text field under 25 words."
TIERS = ("high", "medium", "low")

PLAN_SYSTEM = (
    "Plan a chaos-engineering session on an online shop. Rank every candidate fault by expected "
    "leverage: the biggest customer impact from the weakest fault. The code runs them in your order "
    "until the run budget is used, so list them all. Only use ids and pairs from the "
    "candidates given; never invent one. For each, give a testable hypothesis, the tier you predict "
    "(high, medium or low), a one-line reason that cites the map or the service facts, and a "
    "confidence from 0 to 1. Reply with one JSON object only.")
ANALYST_SYSTEM = (
    "Explain one chaos experiment's result to an SRE in plain words. Use only the evidence given; "
    "the measured tier is final. Reply with one JSON object only.")
FIXER_SYSTEM = (
    "Propose one fix for a group of chaos findings that share a root cause. Take it from the fix "
    "catalog when a row matches, and name the fault that proves the fix. Reply with one JSON object only.")
FINAL_SYSTEM = (
    "Write the summary of a chaos session for engineers: what is weakest, what to fix first, what "
    "held up. The ranking and every number are given; don't change them. Reply with one JSON object only.")


# ---------------------------------------------------------------- LLM: roles, fallback, cache, JSON

def _json(text: str, need: str) -> dict | None:
    """The model's answer: the last JSON object in its reply that has the `need` key. Models wrap
    answers in prose or fences and sometimes echo the prompt's example first; an echo still
    holding a placeholder ("<id>", "...") isn't an answer."""
    decoder, found = json.JSONDecoder(), None
    for i, ch in enumerate(text or ""):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
        except ValueError:
            continue
        if isinstance(obj, dict) and need in obj and not re.search(r'"(<id>|\.\.\.)"', json.dumps(obj)):
            found = obj
    return found


def _call(provider: str, prompt: str, system: str, model: str | None) -> str:
    """One provider call. On a short rate limit (Groq: "Please try again in 22.1s"), wait as long
    as asked, up to 30 s, and retry once: back-to-back sessions hit Groq's tokens-per-minute cap,
    and falling back to the slower model for a 20-second wait is the worse deal."""
    for _ in range(2):
        try:
            return llm.llm(prompt, system=system, model=model, max_tokens=MAX_TOKENS[provider], provider=provider)
        except RuntimeError as e:
            wait = re.search(r"try again in ([\d.]+)s", str(e))
            if not wait or float(wait.group(1)) > 30:
                raise
            print(f"  {provider}: rate limited, waiting {float(wait.group(1)):.0f} s", file=sys.stderr, flush=True)
            time.sleep(float(wait.group(1)) + 1)
    raise RuntimeError(f"{provider}: still rate limited after waiting")


def ask(role: str, system: str, prompt: str, need: str) -> dict | None:
    """One sub-agent call: the role's provider, then the other, one JSON retry each, cached.
    Returns None when every provider fails, and the caller falls back to rules ("no AI").
    Every answer says which model gave it ("_by"), and the raw reply is kept next to the cache
    entry, to check what a model actually said."""
    key = hashlib.sha256(json.dumps([role, system, prompt]).encode()).hexdigest()[:24]
    hit = CACHE / f"{key}.json"
    if hit.exists():
        cached = json.loads(hit.read_text(encoding="utf-8"))
        return {**cached["answer"], "_by": cached.get("by", cached["provider"])}
    CACHE.mkdir(parents=True, exist_ok=True)
    for i, provider in enumerate(ROLES[role]):
        model = (os.environ.get(f"{role.upper()}_MODEL") if i == 0 else None) or llm.OPENAI_STYLE[provider][2]
        retry = "\n\nReply with exactly one JSON object, no prose, no placeholders."
        # nemotron thinks out loud and can run out of tokens before the JSON: its retry skips thinking
        for attempt, sys_extra in ((prompt, ""), (prompt + retry, "\n/no_think" if provider == "openrouter" else "")):
            try:
                text = _call(provider, attempt, system + BRIEF + sys_extra, model)
            except RuntimeError as e:
                print(f"  {role}: {provider} failed ({str(e)[:120]}), trying the next one", file=sys.stderr, flush=True)
                break
            (CACHE / f"{key}.{provider}.raw.txt").write_text(text or "", encoding="utf-8")
            if (answer := _json(text, need)) is not None:
                hit.write_text(json.dumps({"provider": provider, "by": model, "answer": answer}), encoding="utf-8")
                return {**answer, "_by": model}
    return None


def short(model: str | None) -> str:
    """'openai/gpt-oss-120b' -> 'gpt-oss-120b'; 'nvidia/nemotron-3.5-lightning:free' -> 'nemotron-3.5-lightning'."""
    return (model or "rules").split("/")[-1].removesuffix(":free")


# ---------------------------------------------------------------- runners and the person

def replay(recorded: dict) -> Callable[[str], dict]:
    """Returns recorded bank entries instead of injecting: the whole loop, no cluster."""
    def run(exp_id: str) -> dict:
        e = recorded.get(exp_id)
        return copy.deepcopy(e) if e else {"skipped": f"{exp_id} isn't in the recorded bank"}
    return run


def live() -> Callable[[str], dict]:
    """bank.measure() with a fresh baseline before every fault, so faults don't pollute each other."""
    state = {"first": True}

    def run(exp_id: str) -> dict:
        exp = next(e for e in chaos.load_experiments() if e["id"] == exp_id.split("+")[0])
        if not bank.wait_healthy(exp["probe_url"]):
            return {"stopped": "shop still unhealthy 5 min after the last fault"}
        first, state["first"] = state["first"], False
        if not first:
            time.sleep(bank.MIN_WINDOW_S)  # a clean baseline window after the last fault
        t0 = time.time()
        baseline = bank.window(t0 - (bank.BASELINE_S if first else bank.MIN_WINDOW_S), t0)
        try:
            entry = bank.measure(exp_id, baseline)
        except SystemExit as e:  # a person stopped it (STOP file / Ctrl+C) or the shop was unhealthy
            return {"stopped": str(e)}
        return entry or {"skipped": "krkn failed, nothing was injected"}
    return run


def approver(auto: bool, replay: bool, ui_dir: Path | None = None) -> Callable[[dict], bool | None]:
    """A person approves every real fault: in the terminal, or in the console (ui_dir). Answers:
    True = run it, False = skip it, None = stop the session. Auto-approve only replays."""
    if auto and not replay:
        sys.exit("--auto-approve only works with --replay: a person approves every real fault")
    if auto:
        return lambda item: True
    if ui_dir:
        return file_approver(ui_dir)

    def approve(item: dict) -> bool | None:
        print(f"\n--- next: {'+'.join(item['ids'])} ---")
        print(f"hypothesis: {item.get('hypothesis')}  (predicted {item.get('predicted')}, "
              f"confidence {item.get('confidence')})")
        print(f"why: {item.get('reason')}")
        print("kill switch: blast radius, runs/STOP and Ctrl+C always; error/latency limits from experiments.toml")
        answer = input("Run it? [y]es / [n]o, skip / [q]uit: ").strip().lower()
        return True if answer == "y" else None if answer == "q" else False
    return approve


def file_approver(ui_dir: Path) -> Callable[[dict], bool | None]:
    """The console's Approve / Skip / Stop buttons: the agent writes pending.json and waits for the
    page to write decision.json, the same pattern as chaos.py's STOP file."""
    pending, decision = ui_dir / "pending.json", ui_dir / "decision.json"

    def approve(item: dict) -> bool | None:
        decision.unlink(missing_ok=True)
        _write(pending, item)
        while not decision.exists():
            time.sleep(0.5)
        choice = json.loads(decision.read_text(encoding="utf-8")).get("decision")
        decision.unlink(missing_ok=True)
        pending.unlink(missing_ok=True)
        return True if choice == "approve" else None if choice == "stop" else False
    return approve


def _write(path: Path, data) -> None:
    """Write JSON in one step (temp file, then rename), so the console never reads half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


@dataclass
class Deps:
    ask: Callable[[str, str, str, str], dict | None]
    run: Callable[[str], dict]
    approve: Callable[[dict], bool | None]
    exps: list[dict]
    graph: dict
    prior: dict = field(default_factory=dict)  # tiers from earlier sessions; {} = plan blind
    pairs: bool = False  # run pairs (needs the combo runner, #20); otherwise they become suggestions


class Session(TypedDict, total=False):
    pool: list[str]
    budget: int
    queue: list[dict]
    results: list[dict]
    dropped: list[str]
    skipped: list[str]
    next: list[dict]
    stopped: str
    plan_ai: bool
    plan_by: str
    rejected_pairs: list[dict]
    ranked: list[dict]
    groups: dict
    fixes: dict
    summary: dict


# ---------------------------------------------------------------- context packs (deterministic)

def _target(exp: dict) -> str:
    return exp["target"].partition("=")[2] or exp["target"]


def _map_facts(graph: dict, svc: str) -> str:
    node = graph.get("nodes", {}).get(svc)
    if svc.startswith("node:"):
        return "a node fault: every backend on the blast node"
    if not node:
        return "not in the map"
    flags = [f for f in node.get("flags", []) if f != "single-replica"]
    return f"called by {', '.join(node.get('callers', [])) or 'nobody'}" + (f"; {', '.join(flags)}" if flags else "")


def _doc(name: str) -> str:
    return DOCS[name].read_text(encoding="utf-8") if DOCS[name].exists() else ""


def _cell(text) -> str:
    return " ".join(str(text if text is not None else "-").split()).replace("|", "/")


# ---------------------------------------------------------------- graph nodes

def build(deps: Deps, out: Path):
    by_id = {e["id"]: e for e in deps.exps}

    def known(ids: list[str]) -> bool:
        if len(ids) == 1:
            return ids[0] in by_id
        return len(ids) == 2 and bool(judge.candidate_pairs(ids, deps.exps, deps.graph)[0])

    def add_next(state: dict, ids, why, confidence=None, source=""):
        ids = [i for i in (ids or []) if isinstance(i, str)]
        key = "+".join(ids)
        done = {r["id"] for r in state.get("results", [])} | {"+".join(n["ids"]) for n in state.get("next", [])}
        if ids and known(ids) and key not in done:
            state.setdefault("next", []).append({"ids": ids, "why": why, "confidence": confidence, "source": source})

    def plan(state: dict) -> dict:
        pool = [i for i in state["pool"] if i in by_id]
        pairs, rejected = judge.candidate_pairs(pool, deps.exps, deps.graph)
        rows = "\n".join(
            f"- {i}: {by_id[i].get('note') or by_id[i]['scenario']} | scenario {by_id[i]['scenario']} | "
            f"strength {judge.strength(by_id[i])} | target {_target(by_id[i])} ({_map_facts(deps.graph, _target(by_id[i]))})"
            + (f" | measured before: {deps.prior[i]}" if i in deps.prior else "") for i in pool)
        prompt = (f"Run budget: {state['budget']} faults. Rank all {len(pool)} candidates; the first ones that "
                  f"fit the budget run.\nCandidate faults:\n{rows}\n\nCandidate pairs (code-checked):\n"
                  + ("\n".join(f"- {'+'.join(p['ids'])}: {p['reason']}" for p in pairs) or "- none")
                  + f"\n\nService facts:\n{_doc('service-facts')}\n\n"
                  "Answer with one JSON object shaped like this example (one id per single fault, two "
                  "ids for a pair; predicted is high, medium or low; suggestions may be empty):\n"
                  '{"queue": [{"ids": ["<id>"], "hypothesis": "...", "predicted": "high", "reason": "...", '
                  '"confidence": 0.6}], "suggestions": [{"ids": ["<id>"], "why": "...", "confidence": 0.4}]}')
        answer = deps.ask("orchestrator", PLAN_SYSTEM, prompt, "queue")
        queue, dropped, seen = [], [], set()
        state = {**state, "next": [], "dropped": [], "plan_ai": answer is not None,
                 "plan_by": (answer or {}).get("_by")}
        for item in (answer or {}).get("queue", []):
            ids = [i for i in item.get("ids", []) if isinstance(i, str)]
            key = "+".join(ids)
            if key in seen:
                continue
            seen.add(key)
            single = len(ids) == 1 and ids[0] in pool
            pair = len(ids) == 2 and set(ids) <= set(pool) and any(sorted(ids) == sorted(p["ids"]) for p in pairs)
            if pair and not deps.pairs:
                add_next(state, ids, "pair: needs the combo runner (#20)", item.get("confidence"), "planner")
            elif single or pair:
                queue.append({**item, "ids": ids,
                              "predicted": item.get("predicted") if item.get("predicted") in TIERS else None})
            else:
                dropped.append(key or "?")
        for i in sorted(pool, key=lambda i: judge.STRENGTH[judge.strength(by_id[i])]):  # whatever it left out
            if i not in seen:
                queue.append({"ids": [i], "predicted": None, "confidence": None, "ranked_by": "rules",
                              "hypothesis": "not ranked by the planner: added by rules, mildest fault first"
                              if answer else "(no AI) mildest fault first",
                              "reason": "fault strength " + judge.strength(by_id[i])})
        for s in (answer or {}).get("suggestions", []):
            add_next(state, s.get("ids"), s.get("why"), s.get("confidence"), "planner")
        return {**state, "queue": queue, "dropped": dropped, "results": [], "skipped": [],
                "rejected_pairs": rejected}

    def run_next(state: dict) -> dict:
        item, rest = state["queue"][0], state["queue"][1:]
        key = "+".join(item["ids"])
        decision = deps.approve(item)
        if decision is None:
            return {"queue": rest, "stopped": "a person stopped the session"}
        if not decision:
            return {"queue": rest, "skipped": state["skipped"] + [f"{key} (not approved)"]}
        entry = deps.run(key)
        if "stopped" in entry:
            return {"queue": rest, "stopped": entry["stopped"]}
        if "skipped" in entry:
            return {"queue": rest, "skipped": state["skipped"] + [f"{key} ({entry['skipped']})"]}
        exp = by_id.get(item["ids"][0], {"target": "?"})
        passed, total, failed = judge.score(entry)
        prompt = (f"Fault: {key}: {entry.get('fault')} (strength {judge.strength(entry) if '+' not in key else 'pair'})\n"
                  f"Target: {_target(exp)} ({_map_facts(deps.graph, _target(exp))})\n"
                  f"Hypothesis before the run: {item.get('hypothesis')}\n"
                  f"Measured tier (rules, final): {entry['tier']}; root-cause tag: {judge.cause(entry)}\n"
                  f"SLO points {passed}/{total}; broken: {', '.join(failed) or 'none'}\n"
                  f"Recovery: {entry.get('recovery_s')} s; shop probe: {entry.get('shop')}\n"
                  "Effects:\n" + ("\n".join(f"- {e['what']}" for e in entry["effects"]) or "- no detectable effect")
                  + f"\n\nService facts:\n{_doc('service-facts')}\n\n"
                  f"Evidence you may cite: bank.json:{key}, service-facts.\n"
                  "Answer with one JSON object shaped like this example. follow_up is null, or one "
                  'fault id (or two for a pair) from the bank worth testing next, as {"ids": [...], "why": "..."}:\n'
                  '{"what_happened": "...", "why": "...", "hypothesis_held": true, '
                  f'"evidence": ["bank.json:{key}", "service-facts"], "follow_up": null, "confidence": 0.6}}')
        answer = deps.ask("worker", ANALYST_SYSTEM, prompt, "what_happened")
        analysis = dict(answer) if answer else {
            "what_happened": "; ".join(e["what"] for e in entry["effects"][:3]) or "no detectable effect",
            "why": "(no AI) see the effects", "confidence": None, "evidence": [f"bank.json:{key}"]}
        if analysis.pop("tier", entry["tier"]) != entry["tier"]:
            analysis["flag"] = "the analyst named another tier; the measured one stands"
        analysis["evidence"] = [c for c in analysis.get("evidence", []) if isinstance(c, str) and (
            c == f"bank.json:{key}" or c in DOCS or (ROOT / c).exists())]
        state = {**state, "queue": rest}
        follow = analysis.get("follow_up")
        follow = follow if isinstance(follow, dict) else {}
        add_next(state, follow.get("ids"), follow.get("why"), analysis.get("confidence"), f"analyst ({key})")
        return {"queue": rest, "next": state.get("next", []),
                "results": state["results"] + [{"id": key, "item": item, "entry": entry, "analysis": analysis}]}

    def more(state: dict) -> str:
        return "run_next" if state["queue"] and not state.get("stopped") and len(state["results"]) < state["budget"] else "fix"

    def fix(state: dict) -> dict:
        for item in state["queue"]:  # over the budget, or the session was stopped
            add_next(state, item["ids"], item.get("hypothesis"), item.get("confidence"),
                     "stopped" if state.get("stopped") else "over the run budget")
        entries = {r["id"]: r["entry"] for r in state["results"]}
        predicted = {r["id"]: r["item"]["predicted"] for r in state["results"] if r["item"].get("predicted")}
        ranked = judge.rank(entries, predicted)
        groups = judge.groups(ranked)
        why = {r["id"]: r["analysis"].get("why") for r in state["results"]}
        fixes = {}
        for cause, ids in groups.items():
            rows = [r for r in ranked if r["id"] in ids]
            prompt = (f"Root cause tag: {cause}\nFindings:\n" + "\n".join(
                f"- {r['id']}: {r['tier']} from a {r['strength']} fault; {'; '.join(r['effects'][:4])}; analyst: {why.get(r['id'])}"
                for r in rows) + f"\n\nFix catalog:\n{_doc('fix-catalog')}\n\nService facts:\n{_doc('service-facts')}\n\n"
                "Answer with one JSON object shaped like this example (verify_with is a fault id from "
                "the findings or the catalog):\n"
                '{"fix": "...", "change": "...", "verify_with": "<id>", "catalog_match": true, "confidence": 0.6}')
            role = "orchestrator" if any(r["tier"] == "high" for r in rows) else "worker"  # strong model for high
            answer = deps.ask(role, FIXER_SYSTEM, prompt, "fix")
            fixes[cause] = dict(answer) if answer else _catalog_fix(cause)
            if fixes[cause].get("verify_with") not in by_id:
                fixes[cause]["verify_with"] = ids[0]
        return {"queue": [], "next": state.get("next", []), "ranked": ranked, "groups": groups, "fixes": fixes}

    def report(state: dict) -> dict:
        ranked = state["ranked"]
        entries = [r["entry"] for r in state["results"]]
        hits, judged = judge.hit_rate({r["id"]: r["item"]["predicted"] for r in state["results"] if r["item"].get("predicted")},
                                      {r["id"]: r["entry"] for r in state["results"]})
        prompt = ("Findings ranked by leverage (impact / fault strength):\n" + "\n".join(
            f"{n}. {r['id']}: {r['tier']}, {r['strength']}, leverage {r['leverage']}, cause {r['cause']}"
            for n, r in enumerate(ranked, 1)) + "\nFixes:\n" + "\n".join(
            f"- {c}: {f.get('fix')}" for c, f in state["fixes"].items())
            + f"\nResilience score: {judge.resilience(entries)}/100. Planner hit rate: {hits}/{judged}.\n"
            "Answer with one JSON object shaped like this example (summary is 3 to 5 sentences; "
            "next_tests name fault ids from the bank; ideas are new faults in words):\n"
            '{"summary": "...", "next_tests": [{"ids": ["<id>"], "why": "..."}], "ideas": ["..."]}')
        answer = deps.ask("orchestrator", FINAL_SYSTEM, prompt, "summary") or {}
        state = {**state}
        for t in answer.get("next_tests", []) if isinstance(answer.get("next_tests"), list) else []:
            if isinstance(t, dict):
                add_next(state, t.get("ids"), t.get("why"), None, "orchestrator")
        summary = {"text": answer.get("summary") or (
            f"(no AI) {len(judge.findings(ranked))} findings, {len(judge.root_causes(ranked))} root causes "
            f"from mild or targeted faults, resilience score {judge.resilience(entries)}/100."),
            "ideas": [i for i in answer.get("ideas", []) if isinstance(i, str)], "by": answer.get("_by")}
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.md").write_text(render({**state, "summary": summary}, hits, judged), encoding="utf-8")
        _write(out / "session.json", {**state, "summary": summary})
        return {"summary": summary, "next": state.get("next", [])}

    def step(name: str, fn):
        """Every node saves the session to progress.json when it finishes: the console's live view."""
        def node(state: dict) -> dict:
            update = fn(state)
            now = {**state, **update}
            _write(out / "progress.json", {
                "stage": "done" if name == "report" else name, "pool": now.get("pool"), "budget": now.get("budget"),
                "queue": now.get("queue", []), "dropped": now.get("dropped", []), "skipped": now.get("skipped", []),
                "stopped": now.get("stopped"), "next": now.get("next", []), "plan_ai": now.get("plan_ai"),
                "plan_by": now.get("plan_by"), "pid": os.getpid(),
                "results": [{"id": r["id"], "item": r["item"], "tier": r["entry"]["tier"], "analysis": r["analysis"],
                             "effects": [e["what"] for e in r["entry"]["effects"]]} for r in now.get("results", [])],
            })
            done = len(now.get("results", []))
            print(f"[{name}] runs {done}/{now.get('budget')}, queued {len(now.get('queue', []))}"
                  + (f", stopped: {now['stopped']}" if now.get("stopped") else ""), file=sys.stderr, flush=True)
            return update
        return node

    g = StateGraph(Session)
    for name, fn in (("plan", plan), ("run_next", run_next), ("fix", fix), ("report", report)):
        g.add_node(name, step(name, fn))
    g.add_edge(START, "plan")
    g.add_conditional_edges("plan", more, ["run_next", "fix"])
    g.add_conditional_edges("run_next", more, ["run_next", "fix"])
    g.add_edge("fix", "report")
    g.add_edge("report", END)
    return g.compile()


def _catalog_fix(cause: str) -> dict:
    """No model answered: the first fix-catalog row for this cause ("strains:<service>" matches any)."""
    for line in _doc("fix-catalog").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 4:
            continue
        row = cells[0].split(",")[0].strip()
        if row == cause or (row.endswith(":<service>") and cause.startswith(row.split(":")[0] + ":")):
            verify = re.split(r"[:,]", cells[3])[0].strip()
            return {"fix": cells[2], "change": cells[2], "verify_with": verify, "catalog_match": True,
                    "confidence": None, "note": "(no AI) taken from the fix catalog"}
    return {"fix": "(no AI) no catalog row for this cause", "change": "-", "verify_with": None,
            "catalog_match": False, "confidence": None}


def session(pool: list[str], budget: int, deps: Deps, out: Path) -> dict:
    return build(deps, Path(out)).invoke({"pool": pool, "budget": budget}, {"recursion_limit": 200})


# ---------------------------------------------------------------- the report

def render(state: dict, hits: int, judged: int) -> str:
    ranked, results = state["ranked"], state["results"]
    by = {r["id"]: r for r in results}
    entries = [r["entry"] for r in results]
    causes = sorted(judge.root_causes(ranked))

    def models(answers) -> str:
        names = sorted({short(a.get("_by")) for a in answers if a.get("_by")})
        return ", ".join(names) or "rules (no AI)"
    lines = [
        "# Chaos session report", "",
        f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · {len(state['pool'])} faults picked · budget "
        f"{state['budget']} · {len(results)} run" + (f" · stopped: {state['stopped']}" if state.get("stopped") else ""),
        "",
        "Every number comes from `judge.py` rules over the measured effects. The text comes from the "
        f"models that answered: planner {short(state.get('plan_by')) if state.get('plan_by') else 'rules (no AI)'}, "
        f"analysts {models(r['analysis'] for r in results)}, fixes {models(state['fixes'].values())}, "
        f"summary {short(state['summary'].get('by')) if state['summary'].get('by') else 'rules (no AI)'}. "
        "Each shows its own confidence. A person approved each run.", "",
        "## Summary", "", state["summary"]["text"], "",
        "## Scores", "",
        f"- **Resilience score** (krkn's formula, this pool): **{judge.resilience(entries)}/100**",
        f"- **Root causes found by mild or targeted faults:** {len(causes)} ({', '.join(causes) or 'none'})",
        f"- **Planner hit rate** (predicted tier = measured): {hits}/{judged}", "",
        "## Findings, ranked by leverage (impact ÷ fault strength)", "",
        "| # | Fault | Tier | Strength | Leverage | Root cause | What broke | Why (analyst) | Conf. | Evidence |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for n, r in enumerate(judge.findings(ranked), 1):
        a = by[r["id"]]["analysis"]
        lines.append(f"| {n} | `{r['id']}` | {r['tier']} | {r['strength']} | {r['leverage']} | {r['cause']}"
                     f"{' (repeat)' if r['repeat'] else ''} | {_cell('; '.join(r['effects'][:2]))} | "
                     f"{_cell(a.get('why'))}{' ⚠ ' + _cell(a['flag']) if a.get('flag') else ''} | "
                     f"{_cell(a.get('confidence'))} | {_cell(', '.join(a.get('evidence', [])))} |")
    lines += ["", "## Fixes, one per root cause", ""]
    for cause, ids in state["groups"].items():
        f = state["fixes"][cause]
        lines += [f"**{cause}**: {', '.join(f'`{i}`' for i in ids)}",
                  f"- Fix: {_cell(f.get('fix'))}", f"- Change: {_cell(f.get('change'))}",
                  f"- Verify with: `{f.get('verify_with')}` · confidence {_cell(f.get('confidence'))} · "
                  f"{'from the fix catalog' if f.get('catalog_match') else 'not in the fix catalog'}"
                  + (f" · {f['note']}" if f.get("note") else ""), ""]
    held = [r for r in ranked if r["tier"] == "low"]
    lines += ["## Held up (rated low)", ""] + [f"- `{r['id']}`: {_cell('; '.join(r['effects'][:2]) or 'no detectable effect')}"
                                               for r in held] + ([""] if held else ["- none", ""])
    lines += ["## Runs, in the planner's order", "",
              "| # | Fault | Hypothesis (planner) | Predicted | Measured | Held? (analyst) | Conf. |",
              "|---|---|---|---|---|---|---|"]
    for n, r in enumerate(results, 1):
        it, a = r["item"], r["analysis"]
        lines.append(f"| {n} | `{r['id']}` | {_cell(it.get('hypothesis'))} | {it.get('predicted') or '-'} | "
                     f"{r['entry']['tier']} | {_cell(a.get('hypothesis_held'))} | {_cell(it.get('confidence'))} |")
    lines += ["", "## Suggested next", ""] + [
        f"- `{'+'.join(s['ids'])}`: {_cell(s.get('why'))} ({s['source']}"
        + (f", confidence {s['confidence']}" if s.get("confidence") is not None else "") + ")"
        for s in state.get("next", [])] + ["" if state.get("next") else "- none", ""]
    if state["summary"]["ideas"]:
        lines += ["## Ideas (not runnable until someone adds them to `experiments.toml`)", ""] + [
            f"- {_cell(i)}" for i in state["summary"]["ideas"]] + [""]
    if state.get("dropped") or state.get("skipped"):
        lines += ["## Not run", ""] + [f"- `{d}`: dropped by validation (not in the pool or the code-checked pairs)"
                                       for d in state.get("dropped", [])] + [f"- {s}" for s in state.get("skipped", [])] + [""]
    return "\n".join(lines)


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pool", help="comma-separated fault ids (default with --replay: every rated fault)")
    p.add_argument("--budget", type=int, default=8, help="max fault runs this session (default 8)")
    p.add_argument("--replay", metavar="BANK_JSON", help="replay recorded ratings instead of injecting")
    p.add_argument("--auto-approve", action="store_true", help="only with --replay")
    p.add_argument("--pairs", action="store_true", help="run code-checked pairs (needs the combo runner, #20)")
    p.add_argument("--out", help="output dir (default runs/session-<time>)")
    p.add_argument("--ui", action="store_true", help="approvals come from the console (files in --out)")
    args = p.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # model text has characters a Windows console can't print
        stream.reconfigure(errors="replace")  # type: ignore[attr-defined]
    exps = chaos.load_experiments()
    recorded = json.loads(Path(args.replay).read_text(encoding="utf-8")) if args.replay else bank.load()
    pool = args.pool.split(",") if args.pool else [i for i, e in recorded.items() if "control" not in e]
    if not args.replay and not args.pool:
        sys.exit("--pool is required for a live session")
    try:
        graph = depmap.build(*depmap.fetch()) if not args.replay else None
    except Exception:
        graph = None
    graph = graph or depmap.prune(json.loads((ROOT / "refs" / "dependency-map.json").read_text()))
    out = Path(args.out or ROOT / "runs" / f"session-{datetime.now():%Y%m%d-%H%M%S}")
    deps = Deps(ask=ask, run=replay(recorded) if args.replay else live(),
                approve=approver(args.auto_approve, bool(args.replay), out if args.ui else None), exps=exps,
                graph=graph, prior={} if args.replay else {i: e["tier"] for i, e in recorded.items()},
                pairs=args.pairs)
    state = session(pool, args.budget, deps, out)
    print(f"\nreport: {out / 'report.md'}")
    for n, r in enumerate(state["ranked"], 1):
        print(f"{n:2}. {r['id']:24} {r['tier']:6} {r['strength']:8} leverage {r['leverage']}")


if __name__ == "__main__":
    main()
