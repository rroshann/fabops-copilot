"""Inject deterministic drift into DynamoDB so the gold set has real 6/6/6 signals.

The populate script (Day 2.3) produces a "healthy" synthetic state — fresh
policies, stable suppliers, varied on_hand. That's great for normal operation
but makes an eval gold set degenerate: every case collapses to "monitor."

This script picks 6 parts per driver from the 18-part gold set intersection
and injects ONE signal per part so the probe script re-labels them correctly:
  - policy-target: set fabops_policies.last_updated back ~400 days
  - supply-target: set the part's mapped supplier.trend_30d = "degrading" on
    a fresh observed_date row
  - demand-target: set fabops_inventory.on_hand = 0 at the target fab

All other fields are left alone, so each part has exactly one problem signal.
The nightly bake will overwrite policies at 02:00 UTC, so re-run this script
if the staleness gets reset.

Run:
  PYTHONPATH=$(pwd) .venv/bin/python scripts/inject_gold_drift.py
"""
import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import boto3

REGION = "us-east-1"
GOLD_PATH = Path("evals/gold_set.json")

POLICY_TARGETS_IDX = [0, 1, 2, 3, 4, 5]      # gold-001..006 (positions in gold_set.json)
SUPPLY_TARGETS_IDX = [6, 7, 8, 9, 10, 11]    # gold-007..012
DEMAND_TARGETS_IDX = [12, 13, 14, 15, 16, 17]  # gold-013..018

STALE_DATE = "2025-03-01T00:00:00"  # ~400 days before today (2026-04-14)
DRIFT_OBS_DATE = date.today().isoformat()


def _supplier_for_part(part_id: str) -> str:
    idx = int(hashlib.md5(part_id.encode()).hexdigest(), 16) % 20
    return f"SUP-{idx:03d}"


def age_policy(r, part_id: str) -> None:
    """Set fabops_policies.{last_updated, staleness_days} so the part looks stale."""
    today = date.today()
    stale_iso = STALE_DATE
    staleness = (today - date(2025, 3, 1)).days
    r.Table("fabops_policies").update_item(
        Key={"part_id": part_id},
        UpdateExpression="SET last_updated = :lu, staleness_days = :sd",
        ExpressionAttributeValues={
            ":lu": stale_iso,
            ":sd": Decimal(str(staleness)),
        },
    )
    print(f"  policy[{part_id}] aged to staleness={staleness}d (last_updated={stale_iso})")


def mark_supplier_degrading(r, part_id: str) -> None:
    """Write a fresh observed_date row for the part's mapped supplier with
    trend_30d='degrading'. The composite key is (supplier_id, observed_date)
    so this inserts a new row rather than overwriting the existing history.
    """
    supplier_id = _supplier_for_part(part_id)
    r.Table("fabops_suppliers").put_item(
        Item={
            "supplier_id": supplier_id,
            "observed_date": DRIFT_OBS_DATE,
            "tier": Decimal("1"),
            "mean_leadtime_days": Decimal("22.5"),  # elevated from ~12d baseline
            "std_leadtime_days": Decimal("4.0"),
            "last_observed_shipment": date.today().isoformat(),
            "trend_30d": "degrading",
        }
    )
    print(f"  supplier[{supplier_id}] (for part {part_id}) -> degrading on {DRIFT_OBS_DATE}")


def zero_inventory(r, part_id: str, fab_id: str) -> None:
    """Force on_hand=0 for this (part, fab) pair."""
    r.Table("fabops_inventory").update_item(
        Key={"part_id": part_id, "fab_id": fab_id},
        UpdateExpression="SET on_hand = :z",
        ExpressionAttributeValues={":z": Decimal("0")},
    )
    print(f"  inventory[{part_id}@{fab_id}] -> on_hand=0")


def main():
    cases = json.loads(GOLD_PATH.read_text())
    assert len(cases) == 18, f"expected 18 cases, got {len(cases)}"
    r = boto3.resource("dynamodb", region_name=REGION)

    print("=== Policy drift (6 parts) ===")
    for i in POLICY_TARGETS_IDX:
        age_policy(r, cases[i]["part_id"])

    print("\n=== Supply drift (6 parts) ===")
    for i in SUPPLY_TARGETS_IDX:
        mark_supplier_degrading(r, cases[i]["part_id"])

    print("\n=== Demand drift (6 parts) ===")
    for i in DEMAND_TARGETS_IDX:
        zero_inventory(r, cases[i]["part_id"], cases[i]["fab_id"])

    print("\nDone. Re-run scripts/regenerate_gold_set.py to rebuild the gold set "
          "with the new labels.")


if __name__ == "__main__":
    main()
