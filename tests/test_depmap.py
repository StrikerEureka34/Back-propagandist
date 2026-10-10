import json
from pathlib import Path

import depmap

FIXTURES = Path(__file__).parent / "fixtures"


def graph():
    deps = json.loads((FIXTURES / "jaeger_deps.json").read_text())["data"]
    deployments = json.loads((FIXTURES / "deployments.json").read_text())
    return depmap.build(deps, deployments)


def edge(g, src, dst):
    return next((e for e in g["edges"] if (e["from"], e["to"]) == (src, dst)), None)


def test_jaeger_call_edges_kept_without_self_edges():
    g = graph()
    assert edge(g, "frontend", "product-catalog") == {
        "from": "frontend", "to": "product-catalog", "calls": 174, "source": "jaeger"}
    assert not any(e["from"] == e["to"] for e in g["edges"])


def test_data_store_edges_come_from_env_vars():
    g = graph()
    for src, dst in [("cart", "valkey-cart"), ("checkout", "kafka"), ("accounting", "kafka"),
                     ("fraud-detection", "kafka"), ("product-catalog", "astronomy-db"),
                     ("accounting", "astronomy-db")]:
        assert edge(g, src, dst)["source"] == "env", (src, dst)
    # a jaeger edge is not duplicated by the matching env var
    assert edge(g, "frontend", "cart")["source"] == "jaeger"
    assert g["nodes"]["valkey-cart"]["callers"] == ["cart"]


def test_service_names_match_whole_words_only():
    def deploy(name, env=()):
        return {"metadata": {"name": name}, "spec": {"replicas": 1, "template": {"spec": {
            "containers": [{"env": [{"name": "ADDR", "value": v} for v in env]}]}}}}
    g = depmap.build([], {"items": [deploy("cart"), deploy("valkey-cart"),
                                    deploy("x", ["valkey-cart:6379"])]})
    assert [(e["from"], e["to"]) for e in g["edges"]] == [("x", "valkey-cart")]


def test_risk_flags():
    nodes = graph()["nodes"]
    assert nodes["valkey-cart"]["store"] == "valkey/redis"
    assert "no-persistence" in nodes["valkey-cart"]["flags"]
    assert "no-persistence" in nodes["astronomy-db"]["flags"]  # configMap is not storage
    assert nodes["kafka"]["callers"] == ["accounting", "checkout", "fraud-detection"]
    assert "hub" in nodes["kafka"]["flags"]
    assert "no-persistence" not in nodes["checkout"]["flags"]  # stateless
    assert "single-replica" in nodes["payment"]["flags"]


def test_monitoring_stack_is_not_on_the_map():
    # killing our own telemetry would blind the kill switch, so it must never be a target
    deps = json.loads((FIXTURES / "jaeger_deps.json").read_text())["data"]
    deps.append({"parent": "frontend-proxy", "child": "jaeger", "callCount": 2})
    g = depmap.build(deps, json.loads((FIXTURES / "deployments.json").read_text()))
    assert "jaeger" not in g["nodes"] and "opamp-server" not in g["nodes"]
    assert not any({e["from"], e["to"]} & depmap.MONITORING for e in g["edges"])


def test_coverage_against_official_diagram():
    documented = json.loads((Path(__file__).parent.parent / "docs" / "official_edges.json")
                            .read_text())["edges"]
    c = depmap.coverage(graph(), documented)
    assert ["checkout", "kafka"] in c["found"]          # env edge counts
    assert ["frontend", "product-catalog"] in c["found"]
    assert ["frontend-proxy", "flagd-ui"] in c["missing"]  # never called in the window
    assert ["checkout", "flagd"] in c["extra"]          # real, but not in the diagram
    assert len(c["found"]) + len(c["missing"]) == len(documented)


def test_dot_marks_stores_and_env_edges():
    dot = depmap.to_dot(graph())
    assert dot.startswith("digraph")
    assert "single-replica" not in dot  # true of every service, so it is only noise
    assert '"valkey-cart" [shape=cylinder' in dot
    assert '"cart" -> "valkey-cart" [style=dashed]' in dot
    assert '"frontend" -> "product-catalog" [label="174"]' in dot
