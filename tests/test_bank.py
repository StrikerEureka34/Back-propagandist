import pytest

import bank
import chaos

QUIET = {"aborted": False, "abort_reason": None, "recovery_s": 0.0,
         "impact": {"probes": 100, "failed": 0, "p95_ms": 10, "max_ms": 20}}


def svc(calls, errors=0, p95=10):
    return {"calls": calls, "errors": errors, "p95_ms": p95}


def win(services=None, cpu=None, mem=None):
    return {"services": services or {}, "cpu": cpu or {}, "mem": mem or {}}


def effs(before, during, summary=QUIET, pods_before=None, pods_after=None):
    return bank.effects(before, during, pods_before or {}, pods_after or {}, summary)


def test_checkout_erroring_is_high_and_internal_erroring_is_medium():
    before = win({"checkout": svc(6), "payment": svc(6)})
    assert bank.tier(effs(before, win({"checkout": svc(6, 6), "payment": svc(6)}))) == "high"
    assert bank.tier(effs(before, win({"checkout": svc(6), "payment": svc(6, 6)}))) == "medium"


def test_one_error_in_a_few_calls_is_noise_not_an_effect():
    assert effs(win({"payment": svc(3)}), win({"payment": svc(3, 1)})) == []


def test_an_already_noisy_service_must_get_twice_as_bad():
    assert effs(win({"ad": svc(100, 10)}), win({"ad": svc(100, 12)})) == []


def test_slow_customer_page_is_medium_but_slow_internal_service_is_low():
    before = win({"frontend": svc(100, p95=20), "shipping": svc(10, p95=20)})
    assert bank.tier(effs(before, win({"frontend": svc(100, p95=500), "shipping": svc(10, p95=20)}))) == "medium"
    assert bank.tier(effs(before, win({"frontend": svc(100, p95=20), "shipping": svc(10, p95=500)}))) == "low"


def test_cpu_strain_alone_is_low_and_says_so():
    found = effs(win(cpu={"ad": 0.05}), win(cpu={"ad": 0.9}))
    assert [e["kind"] for e in found] == ["cpu"] and bank.tier(found) == "low"


def test_nothing_moved_is_low_with_no_effects():
    quiet = win({"frontend": svc(100)}, {"ad": 0.05}, {"ad": 2**28})
    assert effs(quiet, quiet) == [] and bank.tier([]) == "low"


def test_kill_switch_lost_cart_and_restart_are_classified():
    tripped = {**QUIET, "aborted": True, "abort_reason": "p95_ms: ..."}
    assert bank.tier(effs(win(), win(), tripped)) == "high"
    lost = {**QUIET, "impact": {**QUIET["impact"], "cart_items": {"before": 1, "after": 0}}}
    assert [e["kind"] for e in effs(win(), win(), lost)] == ["data-loss"]
    restarted = effs(win(), win(), pods_before={"email-1": {"restarts": 0}}, pods_after={"email-1": {"restarts": 1}})
    assert [e["kind"] for e in restarted] == ["restart"] and bank.tier(restarted) == "medium"


DOC = {"flags": {
    "paymentFailure": {"defaultVariant": "off", "variants": {"off": 0, "100%": 1}},
    "productCatalogFailure": {"defaultVariant": "off", "variants": {"off": False, "on": True},
                              "targeting": {"if": [{"==": [{"var": "product_id"}, "OLJCESPC7Z"]}, "off", "off"]}},
}}


def test_with_flag_sets_default_or_the_targeting_match_branch():
    import copy
    doc = chaos.with_flag(copy.deepcopy(DOC), "paymentFailure", "100%")
    assert doc["flags"]["paymentFailure"]["defaultVariant"] == "100%"
    doc = chaos.with_flag(copy.deepcopy(DOC), "productCatalogFailure", "on")
    # only the one product fails; everything else keeps the "off" branch
    assert doc["flags"]["productCatalogFailure"]["targeting"]["if"][1:] == ["on", "off"]
    with pytest.raises(ValueError):
        chaos.with_flag(copy.deepcopy(DOC), "paymentFailure", "50%")


def test_every_flag_fault_names_a_flag_variant_and_duration():
    for e in chaos.load_experiments():
        if e["scenario"] == "flagd":
            assert {"flag", "variant", "duration"} <= set(e["params"])
            assert e["abort_if"]["max_s"] > e["params"]["duration"]


def test_the_targeted_pod_being_replaced_is_the_fault_not_collateral_damage():
    before = {"catalog-1": {"labels": {"app": "catalog"}, "restarts": 0},
              "frontend-1": {"labels": {"app": "frontend"}, "restarts": 0}}
    after = {"frontend-1": {"labels": {"app": "frontend"}, "restarts": 1}}
    found = bank.effects(win(), win(), before, after, QUIET, target="app=catalog")
    assert [e["what"] for e in found] == ["pod frontend-1 restarted 1x"]


def test_file_path_params_are_absolute_for_krknctl():
    exp = {"scenario": "service-hijacking", "params": {"scenario-file-path": "scenarios/x.yaml"}}
    cmd = chaos.krkn_command(exp)
    assert cmd[cmd.index("--scenario-file-path") + 1] == str(chaos.ROOT / "scenarios/x.yaml")
