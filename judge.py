"""Rules that turn the fault bank into ranked findings without rewarding "break everything".

Two scores, never mixed:
    leverage = impact / strength    ranks findings: a big effect from a small fault is a weakness
    resilience score                rates the system: krkn's points, over a fixed pool

impact is the bank tier (high 3, medium 2, low 1). strength is how hard we pushed (mild 1,
targeted 2, broad 3), read from the scenario and its params, so experiments.toml needs no new
field. Why not rank by damage: krkn-ai's AI policy warns that "miscalculated fitness can drive
the genetic algorithm toward excessively destructive or ineffective scenarios".
"""

import itertools
import re

import bank

IMPACT = {"high": 3, "medium": 2, "low": 1}
STRENGTH = {"mild": 1, "targeted": 2, "broad": 3}
ENTRY = {"frontend", "frontend-proxy", "frontend-web", "load-generator"}  # upstream of every request
NODE_SCENARIOS = {"node-cpu-hog", "node-memory-hog", "node-network-chaos", "node-io-hog"}

# krkn's resiliency score: critical SLOs 3 points, warnings 1 (krkn docs, "Resilience Score")
SLOS = [  # what must hold, points, effect kinds that break it, which services count
    ("customers get answers", 3, {"errors", "throughput"}, "customer"),
    ("no data lost", 3, {"data-loss"}, "any"),
    ("the shop recovers", 3, {"no-recovery"}, "any"),
    ("the shop stays up", 3, {"shop-down", "kill-switch"}, "any"),
    ("other services answer", 1, {"errors", "throughput"}, "internal"),
    ("customers aren't 2x slower", 1, {"latency"}, "customer"),
    ("nothing else restarts", 1, {"restart", "pod-replaced"}, "any"),
]


def _number(value) -> float:
    match = re.search(r"[\d.]+", str(value))
    return float(match.group()) if match else 0.0


def strength(exp: dict) -> str:
    """How hard a fault pushes: mild (partial degradation), targeted (one service), broad (all)."""
    scenario, p = exp["scenario"], exp.get("params", {})
    if scenario == "http-load":
        return "broad"  # the front door flooded
    if scenario == "node-cpu-hog":
        return "broad" if _number(p.get("cpu-percentage", 100)) >= 80 else "mild"
    if scenario == "node-network-chaos":
        return "broad" if _number(p.get("loss", 0)) >= 50 or _number(p.get("latency", 0)) >= 1000 else "mild"
    if scenario == "node-memory-hog":
        mem = str(p.get("memory-consumption", "90%"))
        return "broad" if mem.endswith("%") and _number(mem) >= 50 else "mild"
    return "targeted"  # one service killed, cut off or hijacked


def _points(exp_id: str, entries: dict) -> int:
    """A pair "a+b" pushes as hard as both of its faults together."""
    return sum(STRENGTH[strength(entries[x])] for x in exp_id.split("+") if x in entries) or STRENGTH["targeted"]


def cause(entry: dict) -> str:
    """A root-cause tag from what broke. Findings that share one are likely one fix."""
    effs = entry["effects"]
    kinds = {e["kind"] for e in effs}
    if "data-loss" in kinds:
        return "loses-state"
    if "no-recovery" in kinds:
        return "slow-recovery"
    for svc in ("checkout", "frontend", "frontend-proxy"):  # money first
        if any(e.get("service") == svc and e["kind"] in {"errors", "throughput", "latency"} for e in effs):
            return f"breaks:{svc}"
    hit = next((e["service"] for e in effs if e.get("service")), None)
    return f"strains:{hit}" if hit else "none"


def score(entry: dict) -> tuple[int, int, list[str]]:
    """(points passed, points possible, SLOs broken) for one rated fault."""
    failed = []
    for name, _, kinds, where in SLOS:
        for e in entry["effects"]:
            customer = e.get("service") in bank.CUSTOMER_FACING
            if e["kind"] in kinds and (where == "any" or (where == "customer") == customer):
                failed.append(name)
                break
    total = sum(points for _, points, _, _ in SLOS)
    return total - sum(points for name, points, _, _ in SLOS if name in failed), total, failed


def resilience(entries: list[dict]) -> int:
    """krkn's resiliency score over a pool: points passed / points possible x 100."""
    scores = [score(e) for e in entries]
    return round(100 * sum(s[0] for s in scores) / sum(s[1] for s in scores)) if scores else 100


def rank(entries: dict, predicted: dict | None = None) -> list[dict]:
    """Every rated fault, controls left out, most leverage first. Ties: the bigger effect, then a
    surprise (the planner predicted another tier), then a cause not seen yet before a repeat."""
    predicted = predicted or {}
    rows = []
    for exp_id, e in entries.items():
        if "control" in e or e.get("scenario") == "flagd":
            continue  # controls check the measuring scale, they aren't findings
        points = _points(exp_id, entries) if "+" in exp_id else STRENGTH[strength(e)]
        rows.append({
            "id": exp_id, "tier": e["tier"], "strength": "pair" if "+" in exp_id else strength(e),
            "leverage": round(IMPACT[e["tier"]] / points, 2), "cause": cause(e),
            "surprise": exp_id in predicted and predicted[exp_id] != e["tier"],
            "score": score(e)[:2], "fault": e.get("fault", ""),
            "effects": [x["what"] for x in e["effects"]],
        })
    def key(r, *extra):
        return (-r["leverage"], -IMPACT[r["tier"]], not r["surprise"], *extra, r["id"])

    rows.sort(key=key)
    seen = set()
    for r in rows:
        r["repeat"] = r["cause"] in seen and r["cause"] != "none"
        seen.add(r["cause"])
    rows.sort(key=lambda r: key(r, r["repeat"]))
    return rows


def findings(ranked: list[dict]) -> list[dict]:
    return [r for r in ranked if r["tier"] in ("high", "medium")]


def groups(ranked: list[dict]) -> dict[str, list[str]]:
    """Findings by root cause, in rank order: one fixer per group."""
    out: dict[str, list[str]] = {}
    for r in findings(ranked):
        out.setdefault(r["cause"], []).append(r["id"])
    return out


def root_causes(ranked: list[dict]) -> set[str]:
    """Distinct causes rated >= medium and found without brute force (success criterion 1)."""
    return {r["cause"] for r in findings(ranked) if r["strength"] in ("mild", "targeted")}


def compound(pair_tier: str, single_tiers: list[str]) -> str:
    """A pair only teaches something if it is worse than either fault alone."""
    return "compound" if IMPACT[pair_tier] > max(IMPACT[t] for t in single_tiers) else "independent"


def hit_rate(predicted: dict, entries: dict) -> tuple[int, int]:
    """How often the planner's predicted tier matched the measured one: (hits, predictions)."""
    judged = [i for i in predicted if i in entries]
    return sum(entries[i]["tier"] == predicted[i] for i in judged), len(judged)


def _upstream(graph: dict, svc: str, hops: int = 2) -> set[str]:
    """svc and whoever calls it within `hops`, minus the entry layer that calls everything."""
    callers: dict[str, set[str]] = {}
    for e in graph["edges"]:
        callers.setdefault(e["to"], set()).add(e["from"])
    seen = frontier = {svc}
    for _ in range(hops):
        frontier = {c for s in frontier for c in callers.get(s, ())} - seen
        seen = seen | frontier
    return seen - ENTRY


def _pair(a: dict, b: dict, graph: dict) -> tuple[bool, str]:
    """(kept, why) for one pair of faults."""
    if any("expect" in e or e["scenario"] == "flagd" for e in (a, b)):
        return False, "a control checks the scale; it isn't paired"
    if strength(a) == strength(b) == "broad":
        return False, "two broad faults: breaks everything, teaches nothing"
    if a["target"] == b["target"]:
        if a["target"].startswith("node:") and a["scenario"] != b["scenario"]:
            return True, "two different faults on the same node"
        why = "same node scenario on the same node: their rules clash" if a["target"].startswith("node:") else "same target"
        return False, why
    if "http-load" in (a["scenario"], b["scenario"]):
        return True, "a load spike touches every request"
    if any(e["scenario"] in NODE_SCENARIOS for e in (a, b)):
        return True, "a node fault touches every backend on that node"
    sa, sb = (e["target"].partition("=")[2] for e in (a, b))
    if ENTRY & {sa, sb}:
        return True, "the entry point is on every request"
    shared = _upstream(graph, sa) & _upstream(graph, sb)
    if shared:
        return True, "shared caller: " + ", ".join(sorted(shared))
    return False, "independent: no shared caller below the entry point"


def candidate_pairs(pool: list[str], exps: list[dict], graph: dict) -> tuple[list[dict], list[dict]]:
    """Code builds the pairs the orchestrator may rank; it can't invent others."""
    by_id = {e["id"]: e for e in exps}
    pairs, rejected = [], []
    for a, b in itertools.combinations(sorted(set(pool) & set(by_id)), 2):
        kept, why = _pair(by_id[a], by_id[b], graph)
        (pairs if kept else rejected).append({"ids": [a, b], "reason": why})
    return pairs, rejected
