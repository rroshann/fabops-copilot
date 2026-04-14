"""Test the runtime forecast_demand tool + NumPy Croston fallback."""
import pytest

from fabops.tools._croston_numpy import croston
from fabops.tools.base import ToolResult
from fabops.tools.forecast_demand import run as forecast_demand_run


def test_croston_point_forecast_on_intermittent_series():
    demand = [0, 0, 5, 0, 0, 0, 3, 0, 4, 0, 0, 2]
    yhat, p10, p90 = croston(demand, horizon=6, alpha=0.1)
    assert len(yhat) == 6
    assert 0 < sum(yhat) / 6 < 5
    for i in range(6):
        assert p10[i] <= yhat[i] <= p90[i]


def test_croston_handles_all_zeros():
    yhat, _, _ = croston([0] * 12, horizon=6)
    assert all(v == 0 for v in yhat)


def test_forecast_demand_returns_tool_result_on_cache_miss(monkeypatch):
    from fabops.tools import forecast_demand as mod
    monkeypatch.setattr(mod, "_read_cached_forecast", lambda part_id: None)
    monkeypatch.setattr(mod, "_compute_forecast_from_history",
                        lambda part_id, horizon: {
                            "forecast": [2.0] * horizon,
                            "p10": [1.0] * horizon,
                            "p90": [3.5] * horizon,
                            "model": "croston",
                            "sMAPE": 0.42,
                            "MASE": 0.88,
                        })
    result = forecast_demand_run(part_id="A7", horizon_months=12, on_hand=10)
    assert isinstance(result, ToolResult)
    assert result.ok
    assert result.data["model"] == "croston"
    assert len(result.data["forecast"]) == 12
    assert result.data["p90_stockout_date"] is not None
