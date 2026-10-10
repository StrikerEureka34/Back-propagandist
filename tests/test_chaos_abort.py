import subprocess
import time

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
