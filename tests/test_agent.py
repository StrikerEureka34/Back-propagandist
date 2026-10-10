import json
from pathlib import Path

import pytest

import agent

BANK = json.loads((Path(__file__).parent / "fixtures" / "bank.json").read_text())
POOL = ["blast-loss", "cart-wipe", "payment-kill", "catalog-kill"]


def fake_ask(answers: dict):
    """An LLM stand-in that answers by task: plan, analyst (worker), fixer, final."""
    def ask(role, system, prompt, need=None):
        kind = "plan" if role == "orchestrator" and "Plan" in system else role
        kind = "final" if role == "orchestrator" and "summary" in system else kind
        kind = "fixer" if "fix catalog" in system else kind
        answer = answers.get(kind)
        return {**answer, "_by": "test/fake-model"} if answer is not None else None  # like agent.ask
    return ask


PLAN = {"queue": [
    {"ids": ["nope"], "hypothesis": "invented", "predicted": "high", "reason": "x", "confidence": 0.9},
    {"ids": ["blast-loss"], "hypothesis": "checkout has no retries", "predicted": "high", "reason": "loss", "confidence": 0.7},
    {"ids": ["cart-wipe", "payment-kill"], "hypothesis": "invented pair", "predicted": "high", "reason": "y", "confidence": 0.5},
    {"ids": ["cart-wipe"], "hypothesis": "carts live in memory", "predicted": "high", "reason": "no volume", "confidence": 0.8},
    {"ids": ["payment-kill"], "hypothesis": "payment restarts fast", "predicted": "medium", "reason": "z", "confidence": 0.4},
    {"ids": ["catalog-kill"], "hypothesis": "catalog is a hub", "predicted": "high", "reason": "w", "confidence": 0.6},
], "suggestions": [{"ids": ["quote-garbage"], "why": "same checkout path", "confidence": 0.5},
                   {"ids": ["made-up"], "why": "nope", "confidence": 0.9}]}
ANALYST = {"what_happened": "checkout failed", "why": "no retries", "hypothesis_held": True, "tier": "low",
           "evidence": ["bank.json:blast-loss", "runs/does-not-exist.json", "service-facts"], "confidence": 0.7,
           "follow_up": {"ids": ["blast-latency"], "why": "same path, slower instead of lossy"}}
FIXER = {"fix": "timeouts and retries", "change": "per-call deadlines in checkout", "verify_with": "blast-loss",
         "catalog_match": True, "confidence": 0.6}
FINAL = {"summary": "Checkout is the weak spot.", "next_tests": [{"ids": ["quote-garbage"], "why": "wrong answers"}],
         "ideas": ["cut flagd"]}


def run_session(ask, tmp_path, budget=3, pool=POOL):
    deps = agent.Deps(ask=ask, run=agent.replay(BANK), approve=lambda item: True,
                      exps=[{"id": i, "scenario": e["scenario"], "params": e["params"],
                             "target": "node:chaos-worker" if e["scenario"].startswith("node") else f"opentelemetry.io/name={i}"}
                            for i, e in BANK.items()],
                      graph={"nodes": {}, "edges": []}, prior={})
    return agent.session(pool, budget, deps, tmp_path)


def test_replay_session_ranks_by_leverage_and_validates_the_llm(tmp_path):
    ask = fake_ask({"plan": PLAN, "worker": ANALYST, "fixer": FIXER, "final": FINAL})
    state = run_session( ask, tmp_path, budget=3)
    report = (tmp_path / "report.md").read_text()
    ran = [r["id"] for r in state["results"]]
    assert ran == ["blast-loss", "cart-wipe", "payment-kill"]  # plan order, budget 3, unknowns skipped
    assert "nope" in state["dropped"] and "cart-wipe+payment-kill" in state["dropped"]
    assert report.index("blast-loss") < report.index("cart-wipe")  # leverage 3.0 before 1.5
    analysis = state["results"][0]["analysis"]
    assert "tier" not in analysis and analysis["flag"]  # the measured tier stands
    assert analysis["evidence"] == ["bank.json:blast-loss", "service-facts"]  # unknown file dropped
    assert "catalog-kill" in [s["ids"][0] for s in state["next"]]  # over budget: next session
    assert "made-up" not in json.dumps(state["next"])  # suggestions only name known faults
    assert "Resilience score" in report and "no AI" not in report


def test_all_models_down_still_gives_a_ranked_report(tmp_path):
    state = run_session(fake_ask({}), tmp_path, budget=2)
    report = (tmp_path / "report.md").read_text()
    assert "no AI" in report
    assert len(state["results"]) == 2 and "Resilience score" in report


def test_ask_falls_back_to_the_other_provider_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "CACHE", tmp_path)
    calls = []

    def fake_llm(prompt, system=None, model=None, max_tokens=None, provider=None, **_):
        calls.append(provider)
        if provider == "groq":
            raise RuntimeError("groq HTTP 429")
        return 'Sure:\n```json\n{"ok": 1}\n```'
    monkeypatch.setattr(agent.llm, "llm", fake_llm)
    nemotron = agent.llm.OPENAI_STYLE["openrouter"][2]
    assert agent.ask("orchestrator", "sys", "hello", "ok") == {"ok": 1, "_by": nemotron}  # says who answered
    assert calls == ["groq", "openrouter"]
    assert agent.ask("orchestrator", "sys", "hello", "ok") == {"ok": 1, "_by": nemotron}  # cached: no new call
    assert calls == ["groq", "openrouter"]


def test_a_short_rate_limit_is_waited_out_not_handed_to_the_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "CACHE", tmp_path)
    calls, waits = [], []

    def fake_llm(prompt, system=None, model=None, max_tokens=None, provider=None, **_):
        calls.append(provider)
        if len(calls) == 1:
            raise RuntimeError('groq HTTP 429: {"error":{"message":"Rate limit reached for model on tokens '
                               'per minute (TPM): Limit 8000, Used 7215, Requested 4831. Please try again in 7.5s."}}')
        return '{"queue": [{"ids": ["blast-loss"]}]}'
    monkeypatch.setattr(agent.llm, "llm", fake_llm)
    monkeypatch.setattr(agent.time, "sleep", waits.append)
    answer = agent.ask("orchestrator", "sys", "plan", "queue")
    assert calls == ["groq", "groq"] and waits == [8.5]  # waited as asked, then Groq again
    assert answer["_by"] == agent.llm.OPENAI_STYLE["groq"][2]


def test_a_planner_that_ranks_one_fault_still_runs_the_budget(tmp_path):
    one = {"queue": [{"ids": ["cart-wipe"], "hypothesis": "carts live in memory", "predicted": "high", "confidence": 0.8}]}
    state = run_session(fake_ask({"plan": one, "worker": ANALYST, "fixer": FIXER, "final": FINAL}), tmp_path, budget=3)
    ran = [r["id"] for r in state["results"]]
    assert ran[0] == "cart-wipe" and len(ran) == 3  # the planner's pick first, then rules fill the budget
    assert all(r["item"].get("ranked_by") == "rules" for r in state["results"][1:])
    assert "added by rules" in state["results"][1]["item"]["hypothesis"]


def test_json_takes_the_answer_not_the_echoed_example():
    # the prompt's example echoed first, then the real answer
    text = ('Format: {"ids": ["<id>"], "why": "..."}\nAnswer:\n'
            '{"what_happened": "checkout failed", "follow_up": {"ids": ["blast-latency"], "why": "slower"}}')
    assert agent._json(text, "what_happened")["what_happened"] == "checkout failed"
    # a copied "... or null" makes the outer object invalid; the inner example alone isn't an answer
    assert agent._json('{"what_happened": "x", "follow_up": {"ids": ["<id>"]} or null}', "what_happened") is None


def test_file_approver_reads_the_console_buttons(tmp_path):
    import threading

    def click(choice):
        def press():
            while not (tmp_path / "pending.json").exists():
                pass
            (tmp_path / "decision.json").write_text(json.dumps({"decision": choice}))
        threading.Thread(target=press, daemon=True).start()

    approve = agent.file_approver(tmp_path)
    for choice, expected in (("approve", True), ("skip", False), ("stop", None)):
        click(choice)
        assert approve({"ids": ["blast-loss"]}) is expected
        assert not (tmp_path / "pending.json").exists()


def test_a_stop_ends_the_session_and_progress_says_done(tmp_path):
    deps = agent.Deps(ask=fake_ask({}), run=agent.replay(BANK), approve=lambda item: None,
                      exps=[{"id": "blast-loss", "scenario": "node-network-chaos", "params": {}, "target": "node:chaos-worker"}],
                      graph={"nodes": {}, "edges": []})
    state = agent.session(["blast-loss"], 3, deps, tmp_path)
    assert state["stopped"] == "a person stopped the session" and state["results"] == []
    progress = json.loads((tmp_path / "progress.json").read_text())
    assert progress["stage"] == "done" and progress["stopped"]


def test_auto_approve_only_in_replay():
    assert agent.approver(auto=True, replay=True)({"ids": ["x"]}) is True
    with pytest.raises(SystemExit):
        agent.approver(auto=True, replay=False)
