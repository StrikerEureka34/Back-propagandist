import agent_flow


def test_the_diagram_outlines_the_step_a_live_session_is_on():
    assert agent_flow.active_step(None, False) is None  # pick screen: nothing running
    assert agent_flow.active_step({"stage": "starting"}, False) == "planner"
    assert agent_flow.active_step({"stage": "run_next"}, True) == "approve"  # a card waits for a person
    assert agent_flow.active_step({"stage": "run_next"}, False) == "fault"
    assert agent_flow.active_step({"stage": "done"}, False) == "report"


def test_every_edge_joins_two_steps_from_a_real_side():
    ids, sides = set(agent_flow.STEPS), {"left", "right", "top", "bottom"}
    assert all(a in ids and b in ids and o in sides and i in sides for a, b, o, i, _ in agent_flow.EDGES)
    assert {a for a, *_ in agent_flow.EDGES} | {b for _, b, *_ in agent_flow.EDGES} == ids  # nothing floats free
