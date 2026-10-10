import pytest

import bank
import chaos

QUIET = {"aborted": False, "abort_reason": None, "recovery_s": 0.0,
         "impact": {"probes": 100, "failed": 0, "p95_ms": 10, "max_ms": 20}}


def svc(calls, errors=0, p95=10, rps=None):
    return {"calls": calls, "rps": calls / 100 if rps is None else rps, "errors": errors, "p95_ms": p95}


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


def test_a_customer_facing_service_starved_of_traffic_is_high():
    # catalog-kill on 2026-10-10: the frontend served ~75 % fewer requests, with no errors yet
    before = win({"frontend": svc(1000, rps=17.0), "product-catalog": svc(700, rps=6.0)})
    during = win({"frontend": svc(300, rps=4.2), "product-catalog": svc(50, rps=0.4)})
    found = effs(before, during)
    assert [e["kind"] for e in found] == ["throughput", "throughput"] and bank.tier(found) == "high"


def test_the_targets_own_lost_traffic_is_the_fault_and_a_quiet_service_is_not_starved():
    before = win({"recommendation": svc(300, rps=1.0), "quote": svc(10, rps=0.2)})
    during = win({"quote": svc(2, rps=0.02)})
    assert bank.effects(before, during, {}, {}, QUIET, target="opentelemetry.io/name=recommendation") == []


def test_a_service_missing_from_the_fault_window_is_no_data_not_zero_traffic():
    # catalog-kill on 2026-10-10: a 90 s window held one sample for the frontend, so it came back empty
    before = win({"frontend": svc(1000, rps=17.0)})
    assert effs(before, win({})) == []
    assert [e["kind"] for e in effs(before, win({"frontend": svc(0, rps=0.0)}))] == ["throughput"]


def test_windows_are_never_shorter_than_two_samples():
    assert bank.MIN_WINDOW_S >= 2 * bank.SCRAPE_S


def test_only_quote_garbage_skips_the_workload_signature_check():
    exps = chaos.load_experiments()
    assert [e["id"] for e in exps if "disable-image-signature" in e.get("params", {})] == ["quote-garbage"]
    cmd = chaos.krkn_command(next(e for e in exps if e["id"] == "quote-garbage"))
    assert cmd[cmd.index("--disable-image-signature") + 1] == "true"
    assert all("--run-unsigned-images" not in chaos.krkn_command(e) for e in exps if e["scenario"] != "flagd")


def test_recovery_is_the_first_minute_the_faults_own_damage_is_gone():
    entry = {"effects": [{"kind": "errors", "service": "checkout", "what": ""}],
             "windows": {"baseline": [0, 300]}}
    sick, well = win({"checkout": svc(20, 10)}), win({"checkout": svc(20)})
    healthy_from = 1000 + bank.MIN_WINDOW_S + 2 * bank.SCRAPE_S  # still erroring for two more minutes
    fake = lambda start, end: win({"checkout": svc(20)}) if end == 300 else (well if end >= healthy_from else sick)
    assert bank.recovery(entry, "", 1000, 5000, fake) == healthy_from - 1000
    assert bank.recovery(entry, "", 1000, healthy_from - 1, fake) is None  # next fault came first


def test_a_fault_with_no_metric_damage_has_nothing_to_recover_and_noise_elsewhere_is_ignored():
    assert bank.recovery({"effects": [{"kind": "data-loss", "what": ""}]}, "", 0, 9999) == 0.0
    entry = {"effects": [{"kind": "errors", "service": "checkout", "what": ""}], "windows": {"baseline": [0, 300]}}
    other_noise = win({"checkout": svc(20), "ad": svc(20, 10)})
    fake = lambda start, end: win({"checkout": svc(20), "ad": svc(20)}) if end == 300 else other_noise
    assert bank.recovery(entry, "", 1000, 5000, fake) == bank.MIN_WINDOW_S
