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

# krkn's resiliency score: critical SLOs 3 points, warnings 1 (krkn docs, "Resilience Score"). Our
# SLOs measure what customers feel, from the bank's effects: krkn's built-in score gave 100/100 to
# a fault that made the shop 66x slower (docs/decisions-and-lessons.md).
SLOS = [  # what must hold, points, effect kinds that break it, which services count
    ("customers get answers", 3, {"errors", "throughput"}, "customer"),
    ("no data lost", 3, {"data-loss"}, "any"),
    ("the shop recovers", 3, {"no-recovery"}, "any"),
    ("the shop stays up", 3, {"shop-down", "kill-switch"}, "any"),
    ("other services answer", 1, {"errors", "throughput"}, "internal"),
    ("customers aren't 2x slower", 1, {"latency"}, "customer"),
    ("nothing else restarts", 1, {"restart", "pod-replaced"}, "any"),
]
# A customer page 10x slower than usual, or slower than 2 s, is no answer for a shopper: it breaks
# "customers get answers" too, not only the 1-point latency warning.
BIG_SLOWDOWN_X, BIG_SLOWDOWN_MS = 10, 2000
SMALL_SAMPLE = 20  # an error ratio from fewer calls than this is shaky
# Claims in an analyst's note that the measurement can prove wrong: (pattern, what disproves it)
CLAIMS = [
    (r"\bno (data )?loss\b|\bno data (was )?lost\b", {"data-loss"}),
    (r"\bno (detectable |visible )?(effect|impact)\b|\bunaffected\b", "any effect"),
    (r"\bfully recovered\b|\bno lasting (damage|impact)\b", {"no-recovery"}),
    (r"\bslos? (were |was )?(preserved|held|met|intact)\b", "broken SLOs"),
    (r"\bstayed (up|online|available)\b|\bno outage\b", {"shop-down", "kill-switch"}),
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


def _points(exp_id: str, entry: dict) -> int:
    """A pair "a+b" pushes as hard as both of its faults together. Read from the pair's own entry
    (scenario "sa+sb", params keyed by fault id, chaos.py), since its halves may never be rated alone."""
    halves = zip(exp_id.split("+"), entry["scenario"].split("+"))
    return sum(STRENGTH[strength({"scenario": s, "params": entry.get("params", {}).get(x, {})})] for x, s in halves)


def _cause(entry: dict) -> tuple[str, dict | None]:
    """The root-cause tag and the effect that decided it."""
    effs = entry["effects"]
    for kind, tag in (("data-loss", "loses-state"), ("no-recovery", "slow-recovery")):
        if hit := next((e for e in effs if e["kind"] == kind), None):
            return tag, hit
    for svc in ("checkout", "frontend", "frontend-proxy"):  # money first
        if hit := next((e for e in effs if e.get("service") == svc and e["kind"] in {"errors", "throughput", "latency"}), None):
            return f"breaks:{svc}", hit
    hit = next((e for e in effs if e.get("service")), None)
    return (f"strains:{hit['service']}", hit) if hit else ("none", None)


def cause(entry: dict) -> str:
    """A root-cause tag from what broke. Findings that share one are likely one fix."""
    return _cause(entry)[0]


def decided_by(entry: dict) -> str:
    """The measured effect behind the root-cause tag, in the bank's words."""
    hit = _cause(entry)[1]
    return hit["what"] if hit else "no detectable effect"


def big_slowdown(e: dict) -> bool:
    """A customer-facing p95 at least 10x usual or at least 2 s (bank: '<svc> p95 <b> -> <d> ms')."""
    m = re.search(r"p95 (\d+) -> (\d+) ms", e.get("what", ""))
    return (e["kind"] == "latency" and e.get("service") in bank.CUSTOMER_FACING and m is not None
            and (int(m[2]) >= BIG_SLOWDOWN_X * max(1, int(m[1])) or int(m[2]) >= BIG_SLOWDOWN_MS))


def _breaks(slo: tuple, e: dict) -> bool:
    name, _, kinds, where = slo
    customer = e.get("service") in bank.CUSTOMER_FACING
    if e["kind"] in kinds and (where == "any" or (where == "customer") == customer):
        return True
    return name == "customers get answers" and big_slowdown(e)


def slo_rows(entry: dict) -> list[dict]:
    """Every SLO for one fault: held or broken, its points, and the effect that broke it."""
    rows = []
    for slo in SLOS:
        hit = next((e for e in entry["effects"] if _breaks(slo, e)), None)
        rows.append({"slo": slo[0], "points": slo[1], "kind": "critical" if slo[1] == 3 else "warning",
                     "held": hit is None, "because": hit.get("what", hit["kind"]) if hit else ""})
    return rows


def score(entry: dict) -> tuple[int, int, list[str]]:
    """(points passed, points possible, SLOs broken) for one rated fault."""
    rows = slo_rows(entry)
    return sum(r["points"] for r in rows if r["held"]), sum(r["points"] for r in rows), \
        [r["slo"] for r in rows if not r["held"]]


def check_note(note: dict, entry: dict, target: str = "") -> tuple[int, list[tuple[bool, str]]]:
    """How far an analyst's note can be trusted, from rules: (percent, [(passed, why)]).
    Starts at 100: -40 per claim the measurement disproves, -30 if it names nothing that broke,
    -20 if the deciding error ratio rests on fewer than 20 calls, -10 if it cites no evidence."""
    text = " ".join(str(note.get(k) or "") for k in ("what_happened", "why")).lower()
    norm = lambda s: s.lower().replace("-", " ")
    effs, checks, pct = entry["effects"], [], 100
    broken = score(entry)[2]
    for pattern, disproof in CLAIMS:
        claim = re.search(pattern, text)
        if not claim:
            continue
        if disproof == "any effect":
            wrong, proof = bool(effs), effs[0]["what"] if effs else ""
        elif disproof == "broken SLOs":
            wrong, proof = bool(broken), f"broken SLOs: {', '.join(broken)}"
        else:
            hit = next((e for e in effs if e["kind"] in disproof), None)
            wrong, proof = hit is not None, hit["what"] if hit else ""
        if wrong:
            pct -= 40
            checks.append((False, f"says \"{claim.group()}\", but the bank measured {proof}"))
    if not any(not ok for ok, _ in checks):
        checks.append((True, "no claim contradicts the measurement"))
    hit = {e["service"] for e in effs if e.get("service")}
    names = sorted(s for s in hit | {target.partition("=")[2] or target} if s and norm(s) in norm(text))
    if not effs:
        checks.append((True, "nothing broke, so there is nothing to name"))
    elif names:
        checks.append((True, f"names what broke: {', '.join(names)}"))
    else:
        pct -= 30
        checks.append((False, "names no service that broke"))
    calls = [(int(m[2]), e.get("service")) for e in effs if e["kind"] == "errors"
             and (m := re.search(r"\((\d+)/(\d+) calls\)", e["what"]))]
    if calls and min(calls)[0] < SMALL_SAMPLE:
        pct -= 20
        checks.append((False, f"only {min(calls)[0]} {min(calls)[1]} calls in the window: a small sample"))
    elif calls:
        checks.append((True, f"error ratios rest on {min(calls)[0]}+ calls"))
    if note.get("evidence"):
        checks.append((True, f"cites {', '.join(note['evidence'])}"))
    else:
        pct -= 10
        checks.append((False, "cites no evidence"))
    return max(0, pct), checks


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
        points = _points(exp_id, e) if "+" in exp_id else STRENGTH[strength(e)]
        passed, total, broken = score(e)
        rows.append({
            "id": exp_id, "tier": e["tier"], "strength": "pair" if "+" in exp_id else strength(e),
            "points": points, "leverage": round(IMPACT[e["tier"]] / points, 2), "cause": cause(e),
            "decided_by": decided_by(e), "surprise": exp_id in predicted and predicted[exp_id] != e["tier"],
            "score": (passed, total), "broken": broken, "fault": e.get("fault", ""),
            "effects": [x["what"] for x in e["effects"]],
        })
    def key(r, *extra):
        return (-r["leverage"], -IMPACT[r["tier"]], not r["surprise"], *extra, r["id"])

    rows.sort(key=key)
    first: dict[str, str] = {}
    for r in rows:
        r["repeat"] = r["cause"] in first and r["cause"] != "none"
        first.setdefault(r["cause"], r["id"])
    rows.sort(key=lambda r: key(r, r["repeat"]))
    for r in rows:
        r["repeat_of"] = first[r["cause"]] if r["repeat"] else None
    return rows


def leverage_text(row: dict) -> str:
    """The arithmetic behind a leverage figure: '3 ÷ 1 = 3.0' (impact points ÷ strength points)."""
    return f"{IMPACT[row['tier']]} ÷ {row['points']} = {row['leverage']:g}"


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


def forbidden(a: dict, b: dict) -> str | None:
    """Why this pair never runs, whatever the map says (chaos.py refuses it too), or None."""
    if any("expect" in e or e["scenario"] == "flagd" for e in (a, b)):
        return "a control checks the scale; it isn't paired"
    if strength(a) == strength(b) == "broad":
        return "two broad faults: breaks everything, teaches nothing"
    if a["target"] == b["target"] and not (a["target"].startswith("node:") and a["scenario"] != b["scenario"]):
        return "same node scenario on the same node: their rules clash" if a["target"].startswith("node:") else "same target"
    return None


def _pair(a: dict, b: dict, graph: dict) -> tuple[bool, str]:
    """(kept, why) for one pair of faults."""
    if why := forbidden(a, b):
        return False, why
    if a["target"] == b["target"]:
        return True, "two different faults on the same node"
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
