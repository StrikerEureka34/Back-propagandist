import json
from pathlib import Path

import heat

BANK = json.loads((Path(__file__).parent / "fixtures" / "bank.json").read_text())


def test_damage_levels_and_labels():
    assert heat.damage({"kind": "errors", "what": "checkout errors 0% -> 56% (5/9 calls)"}) == (3, "56% err")
    assert heat.damage({"kind": "latency", "what": "checkout p95 48 -> 3650 ms"}) == (3, "76x slower")
    assert heat.damage({"kind": "latency", "what": "checkout p95 48 -> 330 ms"}) == (2, "7x slower")
    assert heat.damage({"kind": "data-loss", "what": "cart items 1 -> 0"}) == (3, "data lost")
    assert heat.damage({"kind": "cpu", "what": "ad CPU 0.00 -> 2.52 cores"})[0] == 1


def test_blast_rows_show_who_each_fault_hurt():
    df = heat.blast_rows(BANK)
    cell = lambda f, s: df[(df.Fault == f) & (df.Service == s)].iloc[0]
    assert cell("blast-loss", "checkout")["Damage"] == 3  # errors and a 199x slowdown: the worse wins
    assert cell("cart-wipe", heat.SHOP)["Label"] == "data lost"  # damage that isn't one service's
    assert not df.Fault.str.startswith("control-").any()  # controls check the scale; not on the map


def test_service_rows_against_usual():
    usual = {"services": {"checkout": {"calls": 100, "errors": 0, "rps": 1.0, "p95_ms": 48}}}
    now = {"services": {"checkout": {"calls": 100, "errors": 30, "rps": 0.4, "p95_ms": 960}}}
    df = heat.service_rows(usual, now).set_index("Check")
    assert df.loc["Errors", "Damage"] == 3 and df.loc["Errors", "Label"] == "30.0%"
    assert df.loc["Slower", "Damage"] == 3 and df.loc["Slower", "Label"] == "20x"
    assert df.loc["Traffic", "Damage"] == 3  # 0.4 of usual: starved
    calm = heat.service_rows(usual, usual)
    assert (calm.Damage == 0).all() and (calm.Label == "").all()
