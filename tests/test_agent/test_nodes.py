"""Unit tests for fabops/agent/nodes.py — entry/policy/demand/supply/ground.

All tool + LLM + audit dependencies are monkeypatched so these tests never
touch DynamoDB, Gemini, or the real tool implementations.
"""
from fabops.agent.nodes import (
    _audit,
    check_demand_node,
    check_policy_node,
    check_supply_node,
    entry_node,
    ground_disclosures_node,
)
from fabops.agent.state import AgentState
from fabops.tools.base import ToolResult


def test_entry_node_populates_fields(monkeypatch):
    monkeypatch.setattr(
        "fabops.agent.nodes.gemini_flash",
        lambda p, system=None: (
            '{"part_id":"A7","fab_id":"taiwan","intent":"stockout_risk"}',
            0.0,
        ),
    )
    monkeypatch.setattr("fabops.agent.nodes._audit", lambda *a, **kw: None)
    s = AgentState(request_id="r-1", user_query="why is A7 stocking out at Taiwan?")
    out = entry_node(s)
    assert out.part_id == "A7"
    assert out.fab_id == "taiwan"
    assert out.intent == "stockout_risk"
    assert out.llm_total_calls == 1


def test_entry_node_handles_fenced_json(monkeypatch):
    monkeypatch.setattr(
        "fabops.agent.nodes.gemini_flash",
        lambda p, system=None: (
            '```json\n{"part_id":"B2","fab_id":"arizona","intent":"general_query"}\n```',
            0.0,
        ),
    )
    monkeypatch.setattr("fabops.agent.nodes._audit", lambda *a, **kw: None)
    s = AgentState(request_id="r-1", user_query="...")
    out = entry_node(s)
    assert out.part_id == "B2"
    assert out.fab_id == "arizona"


def test_entry_node_handles_bad_json(monkeypatch):
    monkeypatch.setattr(
        "fabops.agent.nodes.gemini_flash",
        lambda p, system=None: ("not json at all", 0.0),
    )
    monkeypatch.setattr("fabops.agent.nodes._audit", lambda *a, **kw: None)
    s = AgentState(request_id="r-1", user_query="hi")
    out = entry_node(s)
    assert out.part_id is None
    assert out.fab_id == "taiwan"  # default
    assert out.intent == "general_query"


def test_check_policy_skips_without_part_id(monkeypatch):
    monkeypatch.setattr("fabops.agent.nodes._audit", lambda *a, **kw: None)
    s = AgentState(request_id="r-1", user_query="q")
    out = check_policy_node(s)
    assert out.policy_check == {"skipped": True, "reason": "no part_id"}


def test_check_policy_calls_tool(monkeypatch):
    calls = {}

    def fake_compute(part_id, service_level=0.95):
        calls["part_id"] = part_id
        calls["service_level"] = service_level
        return ToolResult(
            ok=True,
            data={"reorder_point": 50, "order_qty": 100},
            latency_ms=2.0,
        )

    monkeypatch.setattr("fabops.agent.nodes.compute_policy", fake_compute)
    monkeypatch.setattr("fabops.agent.nodes._audit", lambda *a, **kw: None)
    s = AgentState(request_id="r-1", user_query="q", part_id="A7")
    out = check_policy_node(s)
    assert calls == {"part_id": "A7", "service_level": 0.95}
    assert out.policy_check["reorder_point"] == 50
    assert out.tool_call_count == 1


def test_check_demand_uses_inventory_on_hand(monkeypatch):
    monkeypatch.setattr(
        "fabops.agent.nodes.get_inventory",
        lambda part_id, fab_id: ToolResult(
            ok=True, data={"on_hand": 12}, latency_ms=1.0
        ),
    )
    monkeypatch.setattr(
        "fabops.agent.nodes.forecast_demand",
        lambda **kw: ToolResult(
            ok=True,
            data={
                "forecast": [2.0] * 12,
                "p10": [1.0] * 12,
                "p90": [3.0] * 12,
                "model": "croston",
                "p90_stockout_date": "2026-06-01",
            },
            latency_ms=1.0,
        ),
    )
    monkeypatch.setattr("fabops.agent.nodes._audit", lambda *a, **kw: None)
    s = AgentState(
        request_id="r-1", user_query="why?", part_id="A7", fab_id="taiwan"
    )
    out = check_demand_node(s)
    assert out.demand_check["on_hand"] == 12
    assert out.demand_check["p90_stockout_date"] == "2026-06-01"
    assert out.demand_check["model"] == "croston"
    assert out.tool_call_count == 2


def test_check_demand_skips_without_part_id(monkeypatch):
    monkeypatch.setattr("fabops.agent.nodes._audit", lambda *a, **kw: None)
    s = AgentState(request_id="r-1", user_query="q")
    out = check_demand_node(s)
    assert out.demand_check == {"skipped": True}


def test_check_supply_fan_out(monkeypatch):
    monkeypatch.setattr(
        "fabops.agent.nodes.get_supplier",
        lambda part_id=None, supplier_id=None: ToolResult(
            ok=True,
            data={"supplier_id": "SUP1", "lead_time_days": 45},
            latency_ms=1.0,
        ),
    )
    monkeypatch.setattr(
        "fabops.agent.nodes.get_macro",
        lambda month, series: ToolResult(
            ok=True, data={"index": 101.2, "series": series}, latency_ms=1.0
        ),
    )
    monkeypatch.setattr("fabops.agent.nodes._audit", lambda *a, **kw: None)
    s = AgentState(request_id="r-1", user_query="q", part_id="A7")
    out = check_supply_node(s)
    assert out.supply_check["supplier"]["lead_time_days"] == 45
    assert out.supply_check["macro"]["series"] == "production"
    assert out.tool_call_count == 2


def test_ground_disclosures_node(monkeypatch):
    captured = {}

    def fake_search(query, top_k=5, date_from=None):
        captured["query"] = query
        captured["top_k"] = top_k
        return ToolResult(ok=True, data={"hits": [{"doc": "10-K"}]}, latency_ms=1.0)

    monkeypatch.setattr("fabops.agent.nodes.search_disclosures", fake_search)
    monkeypatch.setattr("fabops.agent.nodes._audit", lambda *a, **kw: None)
    s = AgentState(
        request_id="r-1", user_query="tsmc outage", fab_id="taiwan"
    )
    out = ground_disclosures_node(s)
    assert captured["top_k"] == 3
    assert "taiwan" in captured["query"]
    assert out.disclosures_check["hits"] == [{"doc": "10-K"}]
    assert out.tool_call_count == 1


def test_audit_writes_distinct_step_n(monkeypatch):
    """Regression guard: _audit must not clobber earlier rows.

    Every call to _audit needs to produce a strictly increasing step_n
    (both in state.step_n and in the DynamoDB row written via log_step).
    """
    written = []

    class FakeWriter:
        def __init__(self, request_id):
            self.request_id = request_id
            self._step_n = 0

        def log_step(self, node, args, result, latency_ms, **kw):
            self._step_n += 1
            written.append((self.request_id, self._step_n, node))

    monkeypatch.setattr("fabops.agent.nodes.AuditWriter", FakeWriter)
    s = AgentState(request_id="r-1", user_query="q")
    _audit(s, "n1", {}, {}, 1.0)
    _audit(s, "n2", {}, {}, 1.0)
    _audit(s, "n3", {}, {}, 1.0)
    step_ns = [row[1] for row in written]
    assert step_ns == [1, 2, 3], f"audit rows collided: {written}"
    assert s.step_n == 3
