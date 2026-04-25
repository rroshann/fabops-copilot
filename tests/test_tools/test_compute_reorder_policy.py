"""Smoke test for compute_reorder_policy — mocks dynamo helpers."""
from unittest.mock import patch, MagicMock


def test_compute_reorder_policy_with_cached_stats():
    from fabops.tools import compute_reorder_policy as mod

    def fake_get(table, key):
        return {
            "leadtime_demand_mean": 10.0,
            "leadtime_demand_std": 3.0,
            "last_updated": "2026-04-01T00:00:00",
        }
    fake_table = MagicMock()
    with patch.object(mod, "get_item", side_effect=fake_get):
        with patch.object(mod, "get_table", return_value=fake_table):
            result = mod.run(part_id="A7", service_level=0.95)
    assert result.ok
    # z(0.95) ≈ 1.645, so SS ≈ 4.93, ROP ≈ 14.93
    assert 4.5 < result.data["safety_stock"] < 5.5
    assert 14.0 < result.data["reorder_point"] < 16.0
    assert result.data["z_score"] == 1.6449


def test_compute_reorder_policy_z_interpolation():
    from fabops.tools.compute_reorder_policy import _z
    assert _z(0.95) == 1.6449
    assert _z(0.99) == 2.3263
    # Interpolate between 0.95 and 0.975 at 0.96
    z96 = _z(0.96)
    assert 1.645 < z96 < 1.96


def test_compute_reorder_policy_missing_history_returns_error():
    from fabops.tools import compute_reorder_policy as mod
    with patch.object(mod, "get_item", return_value={}):
        with patch("fabops.data.carparts.load_carparts") as mock_load:
            import pandas as pd
            mock_load.return_value = pd.DataFrame(columns=["part_id", "month", "demand"])
            result = mod.run(part_id="UNKNOWN", service_level=0.95)
    assert not result.ok
    assert "no demand history" in result.error
