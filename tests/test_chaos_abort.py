import subprocess
import time

import pytest

import chaos

LIMITS = {"error_rate": 0.5, "p95_ms": 1000, "max_s": 100}


def ok(t, ms=20):
    return (t, True, ms)


def bad(t, ms=2000):
    return (t, False, ms)


def test_breach_quiet_when_healthy():
    assert chaos.breach([ok(t) for t in range(5)], LIMITS) is None


def test_breach_on_error_rate():
    reason = chaos.breach([ok(0), bad(1), bad(2), bad(3)], LIMITS)
    assert reason and "error_rate" in reason


def test_breach_on_p95():
    reason = chaos.breach([ok(t, 1500) for t in range(5)], LIMITS)
    assert reason and "p95_ms" in reason


def test_breach_on_max_duration():
    reason = chaos.breach([ok(101)], LIMITS)
    assert reason and "max_s" in reason


def test_breach_ignores_old_samples():
    # a bad burst that left the window must not keep the switch tripped
    samples = [bad(t) for t in range(3)] + [ok(t) for t in range(60, 66)]
    assert chaos.breach(samples, LIMITS) is None


def test_breach_ignores_a_single_blip():
    # one timeout among healthy probes must not trip the switch (p95 of 5 samples is just the max)
    assert chaos.breach([ok(0), ok(1), ok(2), ok(3), bad(4)], LIMITS) is None
    assert chaos.breach([ok(0), ok(1), ok(2), ok(3), ok(4, 5000)], LIMITS) is None


def test_breach_trips_on_two_blips_in_the_window():
    assert chaos.breach([ok(0), ok(1), ok(2), bad(3), bad(4)], LIMITS)
    assert chaos.breach([ok(0), ok(1), ok(2), ok(3, 5000), ok(4, 5000)], LIMITS)


def test_breach_waits_for_enough_samples():
    assert chaos.breach([bad(0)], LIMITS) is None


def test_breach_kills_long_running_scenario_and_cleans_up():
    proc = subprocess.Popen(["sleep", "60"], start_new_session=True)
    cleaned = []
    t0 = time.monotonic()
    reason = chaos.supervise(
        proc, LIMITS,
        probe=lambda: (False, 2000),
        blast=lambda: None,
        cleanup=lambda: cleaned.append(True),
        interval=0.05,
    )
    took = time.monotonic() - t0
    assert reason and "error_rate" in reason
    assert cleaned == [True]
    assert proc.poll() is not None, "scenario process still running"
    assert took < 2


def test_blast_radius_aborts():
    proc = subprocess.Popen(["sleep", "60"], start_new_session=True)
    cleaned = []
    reason = chaos.supervise(
        proc, LIMITS,
        probe=lambda: (True, 10),
        blast=lambda: "pod cart-1 NotReady",
        cleanup=lambda: cleaned.append(True),
        interval=0.05,
    )
    assert reason == "blast radius: pod cart-1 NotReady"
    assert cleaned == [True] and proc.poll() is not None


def test_stop_file_aborts(tmp_path):
    stop = tmp_path / "STOP"
    stop.write_text("")
    proc = subprocess.Popen(["sleep", "60"], start_new_session=True)
    reason = chaos.supervise(
        proc, LIMITS, probe=lambda: (True, 10), blast=lambda: None,
        cleanup=lambda: None, interval=0.05, stop_file=stop)
    assert reason == "STOP file" and proc.poll() is not None


def test_healthy_scenario_finishes_without_abort():
    proc = subprocess.Popen(["true"])
    cleaned = []
    reason = chaos.supervise(
        proc, LIMITS, probe=lambda: (True, 10), blast=lambda: None,
        cleanup=lambda: cleaned.append(True), interval=0.05)
    assert reason is None and cleaned == []


def test_experiments_menu_has_the_contract_keys():
    exps = {e["id"]: e for e in chaos.load_experiments()}
    assert {"cart-wipe", "traffic-spike", "cpu-starve", "kafka-outage"} <= set(exps)
    for e in exps.values():
        assert {"scenario", "params", "target", "probe_url", "abort_if"} <= set(e)
        assert {"error_rate", "p95_ms", "max_s"} <= set(e["abort_if"])


def test_krkn_command_always_waits_1s_and_points_at_prometheus():
    exp = {e["id"]: e for e in chaos.load_experiments()}["traffic-spike"]
    cmd = chaos.krkn_command(exp)
    assert cmd[:3] == ["krknctl", "run", "http-load"]
    assert cmd[cmd.index("--wait-duration") + 1] == "1"
    assert cmd[cmd.index("--prometheus-url") + 1] == "http://localhost:9090"


def test_network_target_is_replaced_only_when_the_run_was_aborted(monkeypatch):
    calls = []
    monkeypatch.setattr(chaos, "sh", lambda *cmd: calls.append(cmd) or "")
    monkeypatch.setattr(chaos, "pods", lambda: {"rec-1": {"labels": {"app": "rec"}, "ready": True, "done": False}})
    exp = {"scenario": "pod-network-filter", "target": "app=rec"}
    cleanup = chaos.cleanup_fn(exp, {"rec-1": {}}, set())
    cleanup(aborted=False)
    assert not any(c[:3] == ("kubectl", "delete", "pod") for c in calls)
    cleanup()
    assert ("kubectl", "delete", "pod", "rec-1", "-n", chaos.NS, "--wait=false") in calls


def test_krkn_failed_catches_a_broken_tc_command_that_krkn_still_calls_pass():
    log = ("[WARNING] tc command returned output (may be a warning): tc qdisc add dev eth0 parent 100:1 "
           "handle 101: netem delay 200ms loss % — Unknown\n    Exit Status           : PASS (0)\n")
    assert chaos.krkn_failed(log, aborted=False, returncode=0)
    assert not chaos.krkn_failed("    Exit Status           : PASS (0)\n", aborted=False, returncode=0)
    harmless = ("[WARNING] tc command returned output (may be a warning): tc class add dev eth0 parent 100: "
                "classid 100:1 htb rate 10gbit — Warning: sch_htb: quantum of class 1000001 is big.\n")
    assert not chaos.krkn_failed(harmless, aborted=False, returncode=0)
    assert chaos.krkn_failed("    Exit Status           : FAIL (1)\n", aborted=False, returncode=1)
    assert not chaos.krkn_failed("", aborted=True, returncode=-9)  # killed by our own kill switch


@pytest.mark.skipif(chaos.fcntl is None, reason="no flock on Windows; live runs are Linux-only")
def test_a_second_fault_is_refused_while_one_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(chaos, "RUNS", tmp_path)
    other = open(tmp_path / "LOCK", "a+")  # another process mid-fault (flock is per open file)
    other.write("payment-kill, pid 1")
    other.flush()
    chaos.fcntl.flock(other, chaos.fcntl.LOCK_EX | chaos.fcntl.LOCK_NB)
    with pytest.raises(SystemExit, match="payment-kill"):
        with chaos.exclusive("control-ad-cpu"):
            pass
    other.close()  # the holder finished (or died): the lock is free, and re-entrant inside
    with chaos.exclusive("control-ad-cpu"):
        with chaos.exclusive("control-ad-cpu"):
            assert "control-ad-cpu" in (tmp_path / "LOCK").read_text()


def test_a_pair_runs_until_both_finish_and_an_abort_kills_both():
    short = subprocess.Popen(["sleep", "0.2"], start_new_session=True)
    long = subprocess.Popen(["sleep", "60"], start_new_session=True)
    probes = iter([(True, 10)] * 10 + [(False, 2000)] * 100)  # healthy after the short one ends, then broken
    reason = chaos.supervise([short, long], LIMITS, probe=lambda: next(probes), blast=lambda: None,
                             cleanup=lambda: None, interval=0.05)
    assert reason, "stopped watching when the first fault finished"
    assert short.poll() is not None and long.poll() is not None


EXPS = [
    {"id": "blast-loss", "scenario": "node-network-chaos", "target": "node:chaos-worker", "probe_url": "u",
     "params": {"loss": "10"}, "abort_if": {"error_rate": 0.5, "p95_ms": 3000, "max_s": 240}},
    {"id": "blast-latency", "scenario": "node-network-chaos", "target": "node:chaos-worker", "probe_url": "u",
     "params": {"latency": "200ms"}, "abort_if": {"error_rate": 0.5, "p95_ms": 3000, "max_s": 240}},
    {"id": "blast-memory", "scenario": "node-memory-hog", "target": "node:chaos-worker", "probe_url": "u",
     "params": {}, "abort_if": {"error_rate": 0.5, "p95_ms": 3000, "max_s": 240}},
    {"id": "cart-wipe", "scenario": "pod-scenarios", "target": "app.kubernetes.io/component=valkey-cart",
     "probe_url": "u", "impact": "cart", "params": {}, "abort_if": {"error_rate": 0.3, "p95_ms": 5000, "max_s": 180}},
    {"id": "control-ad-cpu", "scenario": "flagd", "target": "opentelemetry.io/name=ad", "probe_url": "u",
     "expect": "low", "params": {}, "abort_if": {"error_rate": 0.5, "p95_ms": 3000, "max_s": 240}},
]


@pytest.mark.parametrize("pair,why", [("blast-loss+blast-latency", "same node scenario"),
                                      ("cart-wipe+control-ad-cpu", "control"),
                                      ("cart-wipe+cart-wipe", "same target"),
                                      ("cart-wipe+blast-loss+blast-memory", "two faults")])
def test_forbidden_pairs_are_refused(monkeypatch, pair, why):
    monkeypatch.setattr(chaos, "load_experiments", lambda: EXPS)
    with pytest.raises(SystemExit, match=why):
        chaos.find(pair)


def test_a_pair_has_both_targets_and_the_stricter_kill_switch(monkeypatch):
    monkeypatch.setattr(chaos, "load_experiments", lambda: EXPS)
    pair = chaos.combined(chaos.find("blast-memory+cart-wipe"))
    assert pair["abort_if"] == {"error_rate": 0.3, "p95_ms": 3000, "max_s": 240}
    assert pair["impact"] == "cart" and set(pair["params"]) == {"blast-memory", "cart-wipe"}
    cart_pod = {"labels": {"app.kubernetes.io/component": "valkey-cart"}}
    assert chaos.is_target(pair["target"], cart_pod)  # its replacement is the fault, not collateral
    assert not chaos.is_target(pair["target"], {"labels": {"opentelemetry.io/name": "ad"}})


def test_an_aborted_node_network_fault_takes_its_delay_and_helper_pod_with_it(monkeypatch):
    calls = []
    show = ("qdisc htb 100: dev eth0 root refcnt 17 r2q 10 default 0x1 direct_packets_stat 28\n"
            "qdisc netem 101: dev eth0 parent 100:1 limit 1000 delay 200ms\nqdisc noqueue 0: dev lo root refcnt 2\n")

    def sh(*cmd):
        calls.append(cmd)
        if cmd[:4] == ("kubectl", "get", "pods", "-n") and cmd[4] == "default":
            return "pod/node-network-chaos-ovbce\npod/unrelated\n"
        return show if cmd[-2:] == ("qdisc", "show") else ""
    monkeypatch.setattr(chaos, "sh", sh)
    monkeypatch.setattr(chaos, "pods", lambda: {})
    exp = {"scenario": "node-network-chaos", "target": "node:chaos-worker", "params": {"node-name": "chaos-worker"}}
    chaos.cleanup_fn(exp, {}, set())(aborted=True)
    assert ("kubectl", "delete", "pod/node-network-chaos-ovbce", "-n", "default", "--wait=false",
            "--grace-period=0", "--force") in calls
    assert ("docker", "exec", "chaos-worker", "tc", "qdisc", "del", "dev", "eth0", "root") in calls
    assert not any("unrelated" in " ".join(c) for c in calls if "delete" in c)
    calls.clear()
    chaos.cleanup_fn(exp, {}, set())(aborted=False)  # krkn finished and cleaned up itself: hands off
    assert not any("del" in c for c in calls)
