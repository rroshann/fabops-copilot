"""Regenerate evals/gold_set.json from the ACTUAL DynamoDB state.

The original gold set was hand-authored with labels that did not match the
real state of fabops_inventory / fabops_policies / fabops_forecasts — e.g.
cases labeled "policy-driven" had staleness_days=0 on the pre-baked policies.
This probe reads the real data for each of the 18 intersection part_ids,
applies a deterministic hierarchy, and emits a new gold set whose labels
are provably correct given the system state.

Hierarchy (mirrors diagnose_node's intent):
  1. staleness_days > 365 OR leadtime_demand_mean missing -> policy / refresh_reorder_policy
  2. any active supplier incident for this part              -> supply / expedite
  3. on_hand < reorder_point (incl on_hand=0)                -> demand / place_reorder
  4. otherwise (healthy buffer, fresh policy, no incident)   -> none / monitor

Run:
  PYTHONPATH=$(pwd) .venv/bin/python scripts/regenerate_gold_set.py
"""
import hashlib
import json
from pathlib import Path
from typing import Any, Dict

import boto3

REGION = "us-east-1"
GOLD_PATH = Path("evals/gold_set.json")

# 18 question templates spanning interrogative variety. Will be paired with
# whichever driver the probe finds for each part_id.
QUESTION_TEMPLATES = [
    "Why is part {pid} at risk of stocking out at the {fab_pretty} fab?",
    "What's driving the inventory situation for part {pid} at the {fab_pretty} fab?",
    "Is part {pid} going to stock out at the {fab_pretty} fab?",
    "Explain the stockout risk for part {pid} at the {fab_pretty} fab.",
    "Should we take action on part {pid} at the {fab_pretty} fab?",
    "What's the status of part {pid} at the {fab_pretty} fab?",
    "Forecast the stockout risk for part {pid} at the {fab_pretty} fab.",
    "Is part {pid} correctly managed at the {fab_pretty} fab?",
    "What's the risk profile for part {pid} at the {fab_pretty} fab?",
    "Should I expect a shortage of part {pid} at the {fab_pretty} fab?",
    "What's happening with part {pid} at the {fab_pretty} fab?",
    "Why might part {pid} stock out at the {fab_pretty} fab?",
    "Diagnose the stockout risk for part {pid} at the {fab_pretty} fab.",
    "Assess the supply risk for part {pid} at the {fab_pretty} fab.",
    "What does the data say about part {pid} at the {fab_pretty} fab?",
    "Should we reorder part {pid} at the {fab_pretty} fab?",
    "Review the risk for part {pid} at the {fab_pretty} fab.",
    "What should we do about part {pid} at the {fab_pretty} fab?",
]

FAB_ORDER = [
    "taiwan", "arizona", "singapore", "austin-tx",
    "dresden-de", "gloucester-ma", "kumamoto-jp",
    "santa-clara-ca", "kalispell-mt",
]


def fab_pretty(fab_id: str) -> str:
    return {
        "taiwan": "Taiwan",
        "arizona": "Arizona",
        "singapore": "Singapore",
        "austin-tx": "Austin",
        "dresden-de": "Dresden",
        "gloucester-ma": "Gloucester",
        "kumamoto-jp": "Kumamoto",
        "santa-clara-ca": "Santa Clara",
        "kalispell-mt": "Kalispell",
    }.get(fab_id, fab_id)


def _num(x: Any, default: float = 0.0) -> float:
    if x is None:
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def derive_driver(inv: Dict, policy: Dict, supplier: Dict) -> Dict[str, str]:
    """Apply the deterministic hierarchy to a (inv, policy, supplier) tuple."""
    staleness = _num(policy.get("staleness_days"), 999)
    on_hand = _num(inv.get("on_hand") if inv else None, 0)
    reorder_point = _num(policy.get("reorder_point"), 0)
    has_ltd = "leadtime_demand_mean" in (policy or {})
    supplier_trend = (supplier or {}).get("trend_30d", "stable")

    # 1. Policy stale -> policy-driven
    if staleness > 365 or not has_ltd:
        return {
            "driver": "policy",
            "action": "refresh_reorder_policy",
            "notes": f"policy staleness={staleness:.0f}d (threshold 365d); needs refresh",
        }

    # 2. Supplier degrading -> supply-driven
    if supplier_trend == "degrading":
        return {
            "driver": "supply",
            "action": "expedite",
            "notes": f"supplier {supplier.get('supplier_id', '?')} trend_30d=degrading; expedite required",
        }

    # 3. Inventory below reorder point -> demand-driven
    if on_hand < reorder_point or on_hand == 0:
        return {
            "driver": "demand",
            "action": "place_reorder",
            "notes": f"on_hand={on_hand:.1f} < reorder_point={reorder_point:.2f}; demand has depleted buffer",
        }

    # 4. Healthy -> none
    return {
        "driver": "none",
        "action": "monitor",
        "notes": f"on_hand={on_hand:.1f} >= reorder_point={reorder_point:.2f}; fresh policy, stable supplier; healthy",
    }


def _supplier_for_part(part_id: str) -> str:
    idx = int(hashlib.md5(part_id.encode()).hexdigest(), 16) % 20
    return f"SUP-{idx:03d}"


def _latest_supplier_row(r, supplier_id: str) -> Dict:
    """Read the newest observed_date row for a supplier."""
    resp = r.Table("fabops_suppliers").query(
        KeyConditionExpression="supplier_id = :s",
        ExpressionAttributeValues={":s": supplier_id},
        ScanIndexForward=False,  # newest first
        Limit=1,
    )
    items = resp.get("Items", [])
    return items[0] if items else {"supplier_id": supplier_id}


def probe_part(r, part_id: str, fab_id: str) -> Dict[str, Any]:
    """Read inventory + policy + mapped supplier for (part_id, fab_id) and
    return the derived driver label + supporting evidence.
    """
    inv = r.Table("fabops_inventory").get_item(
        Key={"part_id": part_id, "fab_id": fab_id}
    ).get("Item", {})
    policy = r.Table("fabops_policies").get_item(Key={"part_id": part_id}).get("Item", {})
    supplier = _latest_supplier_row(r, _supplier_for_part(part_id))
    return derive_driver(inv, policy, supplier)


def main():
    existing = json.loads(GOLD_PATH.read_text())
    r = boto3.resource("dynamodb", region_name=REGION)

    new_cases = []
    for i, c in enumerate(existing):
        part_id = c["part_id"]
        fab_id = c["fab_id"]
        derived = probe_part(r, part_id, fab_id)
        question = QUESTION_TEMPLATES[i % len(QUESTION_TEMPLATES)].format(
            pid=part_id, fab_pretty=fab_pretty(fab_id)
        )
        new_case = {
            "id": c["id"],
            "question": question,
            "part_id": part_id,
            "fab_id": fab_id,
            "ground_truth_driver": derived["driver"],
            "ground_truth_action": derived["action"],
            "expected_tool_sequence": c["expected_tool_sequence"],
            "notes": derived["notes"],
        }
        new_cases.append(new_case)
        print(f"  {c['id']:9s} {part_id:10s} @ {fab_id:16s} -> {derived['driver']:7s} / {derived['action']}")

    GOLD_PATH.write_text(json.dumps(new_cases, indent=2))

    # Summary
    from collections import Counter
    counts = Counter(c["ground_truth_driver"] for c in new_cases)
    print(f"\nTotal: {len(new_cases)} cases")
    print(f"Drivers: {dict(counts)}")


if __name__ == "__main__":
    main()
