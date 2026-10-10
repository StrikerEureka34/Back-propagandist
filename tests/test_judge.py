import json
from pathlib import Path

import judge

BANK = json.loads((Path(__file__).parent / "fixtures" / "bank.json").read_text())

# targets as in experiments.toml; candidate_pairs needs them, bank entries don't store them
EXPS = [
    {"id": "traffic-spike", "scenario": "http-load", "target": "opentelemetry.io/name=frontend-proxy", "params": {}},
    {"id": "cpu-starve", "scenario": "node-cpu-hog", "target": "node:chaos-worker", "params": {"cpu-percentage": 100}},
    {"id": "blast-latency", "scenario": "node-network-chaos", "target": "node:chaos-worker", "params": {"latency": "200ms"}},
    {"id": "blast-loss", "scenario": "node-network-chaos", "target": "node:chaos-worker", "params": {"loss": "10%"}},
    {"id": "catalog-kill", "scenario": "pod-scenarios", "target": "opentelemetry.io/name=product-catalog", "params": {}},
    {"id": "catalog-db-cutoff", "scenario": "pod-network-filter", "target": "opentelemetry.io/name=product-catalog", "params": {}},
    {"id": "quote-garbage", "scenario": "service-hijacking", "target": "opentelemetry.io/name=quote", "params": {}},
    {"id": "cart-wipe", "scenario": "pod-scenarios", "target": "opentelemetry.io/name=valkey-cart", "params": {}},
    {"id": "ad-kill", "scenario": "pod-scenarios", "target": "opentelemetry.io/name=ad", "params": {}},
    {"id": "email-kill", "scenario": "pod-scenarios", "target": "opentelemetry.io/name=email", "params": {}},
    {"id": "control-ad-cpu", "scenario": "flagd", "target": "opentelemetry.io/name=ad", "params": {}, "expect": "low"},
]

# who calls whom: frontend -> checkout -> shipping -> quote, frontend/checkout -> cart -> valkey-cart
GRAPH = {"nodes": {}, "edges": [
    {"from": a, "to": b} for a, b in [
        ("frontend", "checkout"), ("checkout", "shipping"), ("shipping", "quote"), ("frontend", "cart"),
        ("checkout", "cart"), ("cart", "valkey-cart"), ("frontend", "product-catalog"),
        ("frontend", "ad"), ("checkout", "email"), ("load-generator", "frontend"),
    ]]}


def test_strength_reads_scenario_and_params():
    s = lambda scenario, **params: judge.strength({"scenario": scenario, "params": params})
    assert s("http-load") == "broad"
    assert s("node-cpu-hog", **{"cpu-percentage": 100}) == "broad"
    assert s("node-cpu-hog", **{"cpu-percentage": 30}) == "mild"
    assert s("node-network-chaos", loss="10%") == "mild"
    assert s("node-network-chaos", loss="100%") == "broad"  # a cut-off node, not a lossy one
    assert s("node-memory-hog", **{"memory-consumption": "1g"}) == "mild"
    assert s("node-memory-hog", **{"memory-consumption": "90%"}) == "broad"
    for scenario in ("pod-scenarios", "pod-network-filter", "service-hijacking", "container-scenarios"):
        assert s(scenario) == "targeted"


def test_leverage_puts_a_small_fault_with_a_big_effect_first():
    ranked = judge.rank(BANK)
    ids = [r["id"] for r in ranked]
    assert ids[0] == "blast-loss"  # high from a mild 10 % loss: leverage 3.0
    assert ranked[0]["leverage"] == 3.0
    assert ids.index("catalog-kill") < ids.index("cpu-starve")  # targeted-high beats broad-medium
    # equal leverage 1.0: the medium effect from a targeted fault before the low one from a mild fault
    assert ids.index("recommendation-cutoff") < ids.index("blast-memory")
    assert not any(i.startswith("control-") for i in ids)  # controls check the scale, they aren't findings


def test_score_uses_krkn_points():
    clean = {"effects": []}
    assert judge.score(clean) == (15, 15, [])
    customer_errors = {"effects": [{"kind": "errors", "service": "checkout"}]}
    passed, total, failed = judge.score(customer_errors)
    assert (passed, total) == (12, 15) and failed == ["customers get answers"]
    internal_errors = {"effects": [{"kind": "errors", "service": "shipping"}]}
    assert judge.score(internal_errors)[0] == 14  # a warning SLO: 1 point
    assert judge.resilience([clean, customer_errors]) == round(100 * 27 / 30)


def test_root_causes_and_grouping():
    ranked = judge.rank(BANK)
    by_id = {r["id"]: r for r in ranked}
    assert by_id["blast-loss"]["cause"] == by_id["quote-garbage"]["cause"] == "breaks:checkout"
    assert by_id["cart-wipe"]["cause"] == "loses-state"
    assert by_id["catalog-kill"]["cause"] == "slow-recovery"
    groups = judge.groups(ranked)
    assert {"blast-loss", "quote-garbage"} <= set(groups["breaks:checkout"])
    # criterion 1: distinct causes rated >= medium, each found by a mild or targeted fault
    assert len(judge.root_causes(ranked)) >= 3


def test_repeat_cause_ranks_after_a_new_one_at_equal_leverage():
    ranked = judge.rank(BANK)
    ties = [r for r in ranked if r["leverage"] == 1.5]
    repeats = [r["repeat"] for r in ties]
    assert repeats == sorted(repeats)  # new causes first, repeats after


def test_candidate_pairs_refuses_unsafe_and_independent_pairs():
    pool = [e["id"] for e in EXPS]
    pairs, rejected = judge.candidate_pairs(pool, EXPS, GRAPH)
    reason = {tuple(sorted(r["ids"])): r["reason"] for r in rejected}
    assert "two broad" in reason[("cpu-starve", "traffic-spike")]
    assert "same node" in reason[("blast-latency", "blast-loss")]
    assert "same target" in reason[("catalog-db-cutoff", "catalog-kill")]
    assert "control" in reason[("ad-kill", "control-ad-cpu")]
    kept = {tuple(sorted(p["ids"])) for p in pairs}
    assert ("cart-wipe", "quote-garbage") in kept  # both sit under checkout and frontend
    assert ("quote-garbage", "traffic-spike") in kept  # a spike while a dependency is down
    assert ("ad-kill", "email-kill") in reason and "independent" in reason[("ad-kill", "email-kill")]


def test_compound_and_hit_rate():
    assert judge.compound("high", ["medium", "low"]) == "compound"
    assert judge.compound("high", ["high", "low"]) == "independent"
    assert judge.hit_rate({"blast-loss": "high", "payment-kill": "high"}, BANK) == (1, 2)
