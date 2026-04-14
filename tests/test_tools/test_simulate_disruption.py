"""Smoke test for simulate_supplier_disruption — mocks sub-tools."""
from unittest.mock import patch

from fabops.tools.base import ToolResult


def test_simulate_disruption_happy_path():
    from fabops.tools import simulate_disruption as mod

    fake_inv = ToolResult(ok=True, data={"on_hand": 50}, latency_ms=1.0)
    fake_fc = ToolResult(
        ok=True,
        data={
            "forecast": [3.0] * 12,
            "p90_stockout_date": "2026-08-01",
            "p10": [1.0] * 12,
            "p90": [4.0] * 12,
        },
        latency_ms=1.0,
    )
    fake_sup = ToolResult(
        ok=True,
        data={"supplier_id": "SUP-001", "mean_leadtime_days": 30.0},
        latency_ms=1.0,
    )

    with patch.object(mod, "inv_run", return_value=fake_inv):
        with patch.object(mod, "forecast_run", return_value=fake_fc):
            with patch.object(mod, "supplier_run", return_value=fake_sup):
                result = mod.run(
                    supplier_id="SUP-001",
                    delay_days=14,
                    part_id="A7",
                    fab_id="taiwan",
                )

    assert result.ok
    assert result.data["supplier_id"] == "SUP-001"
    assert result.data["delay_days"] == 14
    assert result.data["recommended_action"] in ("expedite", "accept")
    assert result.data["policy_used"] == "(s,S)"
    assert "expedite_cost" in result.data
    assert "accept_cost" in result.data


def test_simulate_disruption_missing_inventory():
    from fabops.tools import simulate_disruption as mod
    fake_inv_err = ToolResult(ok=False, error="not found", latency_ms=1.0)
    with patch.object(mod, "inv_run", return_value=fake_inv_err):
        result = mod.run(supplier_id="SUP-001", delay_days=7, part_id="A7")
    assert not result.ok
    assert "not found" in result.error
