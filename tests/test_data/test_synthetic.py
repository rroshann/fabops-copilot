"""Test synthetic inventory, supplier, and incident generators."""
from fabops.data.synthetic import generate_inventory, generate_suppliers, AM_FABS


def test_generate_inventory_covers_all_fabs():
    inv = generate_inventory(part_ids=["A7", "B2"], seed=42)
    fab_ids = {row["fab_id"] for row in inv}
    assert fab_ids == set(AM_FABS)
    assert len(inv) == 2 * len(AM_FABS)
    for row in inv:
        assert row["on_hand"] >= 0
        assert row["reserved"] >= 0
        assert row["available"] == row["on_hand"] - row["reserved"] + row["in_transit"]


def test_generate_inventory_deterministic_with_seed():
    inv1 = generate_inventory(part_ids=["A7"], seed=42)
    inv2 = generate_inventory(part_ids=["A7"], seed=42)
    assert inv1 == inv2


def test_generate_suppliers_realistic_leadtimes():
    suppliers = generate_suppliers(n_suppliers=10, seed=42)
    assert len(suppliers) == 10
    for s in suppliers:
        assert 5 <= s["mean_leadtime_days"] <= 120
        assert s["std_leadtime_days"] > 0
        assert "observed_date" in s, "observed_date sort key must be present for DynamoDB write"
