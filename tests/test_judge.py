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


def test_a_big_customer_slowdown_counts_as_no_answer():
    # checkout p95 48 -> 3650 ms is 76x: customers effectively get no answer, not just a slow one
    assert judge.score(BANK["blast-latency"]) == (11, 15, ["customers get answers", "customers aren't 2x slower"])
    # 48 -> 330 ms is 7x and under 2 s: still only the 1-point warning
    assert judge.score(BANK["cpu-starve"])[:2] == (14, 15)


# Real notes nemotron wrote on the Arch box (2026-10-11)
CART_NOTE = {"what_happened": "Pod kill erased in-memory cart items (1→0), shop recovered instantly (0.0s), "
                              "no data loss, SLO preserved",
             "why": "valkey-cart has no volume (memory only); pod loss immediately loses cart state with no "
                    "persistent impact, per service-facts", "evidence": ["bank.json:cart-wipe", "service-facts"]}
LOSS_NOTE = {"what_happened": "Backend packet loss spiked checkout p95 from 48ms to 8125ms, errors to 8%, though "
                              "shop stayed online per probe data.",
             "why": "Checkout sequences charge card then ship; packet loss blocks shipping/quote calls, causing "
                    "errors and p95 spikes, per service-facts.", "evidence": ["bank.json:blast-loss", "service-facts"]}


def test_check_note_catches_claims_the_measurement_disproves():
    pct, checks = judge.check_note(CART_NOTE, BANK["cart-wipe"], "opentelemetry.io/name=valkey-cart")
    failed = [why for ok, why in checks if not ok]
    assert pct == 20  # two claims disproved: "no data loss" and "SLO preserved"
    assert any("no data loss" in w and "cart items 1 -> 0" in w for w in failed)
    assert any("slo preserved" in w for w in failed)


def test_check_note_marks_a_small_sample():
    pct, checks = judge.check_note(LOSS_NOTE, BANK["blast-loss"], "node:chaos-worker")
    assert pct == 80  # grounded, no contradiction, cites evidence; but checkout's error ratio is 5 of 9 calls
    assert (False, "only 9 checkout calls in the window: a small sample") in checks
    assert any(ok and "checkout" in why for ok, why in checks)


def test_rank_rows_carry_the_reasoning():
    rows = {r["id"]: r for r in judge.rank(BANK)}
    assert judge.leverage_text(rows["blast-loss"]) == "3 ÷ 1 = 3"
    assert judge.leverage_text(rows["cart-wipe"]) == "3 ÷ 2 = 1.5"
    assert rows["cart-wipe"]["decided_by"] == "cart items 1 -> 0"
    assert rows["blast-loss"]["decided_by"].startswith("checkout errors")
    assert rows["quote-garbage"]["repeat_of"] == "blast-loss"  # same cause as #1
    assert "no data lost" in rows["cart-wipe"]["broken"]


def test_a_pair_pushes_as_hard_as_both_faults():
    # a session holds only the pair's own entry, and traffic-spike was never rated alone: the pair's
    # strength must come from its own scenario and params, not from looking its halves up
    pair = {"tier": "high", "scenario": "pod-scenarios+http-load", "effects": [],
            "params": {"cart-wipe": {"pod-label": "opentelemetry.io/name=valkey-cart"},
                       "traffic-spike": {"rate": "1000/1s"}}}
    row = judge.rank({"cart-wipe+traffic-spike": pair})[0]
    assert judge.leverage_text(row) == "3 ÷ 5 = 0.6"  # targeted 2 + broad 3: a broad half costs leverage
