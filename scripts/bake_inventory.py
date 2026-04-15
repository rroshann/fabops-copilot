"""Bake the full 200-part inventory catalog into a static frontend asset.

Output: frontend/inventory.json

Structure:
    {
      "generated_at": "...",
      "total_parts": 200,
      "total_fabs": 9,
      "parts": [
        {
          "part_id": "10279876",
          "status": "policy" | "supply" | "demand" | "healthy",
          "fabs": [
            {"fab_id": "taiwan", "fab_label": "Taiwan",
             "on_hand": 12, "reorder_point": 8},
            ...
          ]
        },
        ...
      ]
    }

Status is determined by cross-referencing evals/gold_set.json: the 18
parts with injected drift signals inherit their ground_truth_driver;
every other part is "healthy". This is authoritative because the gold
set labels come from scripts/inject_gold_drift.py and
scripts/regenerate_gold_set.py, which derive them from live DynamoDB
state.

Run:
    PYTHONPATH=$(pwd) .venv/bin/python scripts/bake_inventory.py

Re-run any time the nightly bake changes reorder_points or the drift
script is re-run.
"""
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

import boto3

from fabops.config import AWS_REGION, TABLE_INVENTORY, TABLE_POLICIES

GOLD_PATH = Path("evals/gold_set.json")
OUTPUT = Path("frontend/inventory.json")

FAB_DISPLAY = {
    "taiwan": "Taiwan",
    "arizona": "Arizona",
    "singapore": "Singapore",
    "dresden-de": "Dresden",
    "kumamoto-jp": "Kumamoto",
    "austin-tx": "Austin",
    "santa-clara-ca": "Santa Clara",
    "gloucester-ma": "Gloucester",
    "kalispell-mt": "Kalispell",
}


def _scan_all(table):
    items = []
    resp = table.scan()
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))
    return items


def _num(x, default=0):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return default


def main() -> int:
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)

    print(f"Scanning {TABLE_INVENTORY}...")
    inv_rows = _scan_all(dynamodb.Table(TABLE_INVENTORY))
    print(f"  {len(inv_rows)} inventory rows")

    print(f"Scanning {TABLE_POLICIES}...")
    policy_rows = _scan_all(dynamodb.Table(TABLE_POLICIES))
    print(f"  {len(policy_rows)} policy rows")

    # Index policy rows by part_id for fast reorder_point lookup.
    policy_by_part: dict[str, dict] = {}
    for p in policy_rows:
        pid = str(p.get("part_id", ""))
        if pid:
            policy_by_part[pid] = p

    # Build the gold-driver map so we know which parts have injected drift.
    gold_by_part: dict[str, str] = {}
    if GOLD_PATH.exists():
        gold_cases = json.loads(GOLD_PATH.read_text())
        for c in gold_cases:
            gold_by_part[str(c["part_id"])] = c.get("ground_truth_driver", "none")
        print(f"  gold set: {len(gold_by_part)} drift-labeled parts")
    else:
        print("  WARNING: evals/gold_set.json not found, all parts will read as 'healthy'")

    # Group inventory rows by part_id.
    inv_by_part: dict[str, list[dict]] = defaultdict(list)
    for row in inv_rows:
        pid = str(row.get("part_id", ""))
        fab = str(row.get("fab_id", ""))
        if not pid or not fab:
            continue
        inv_by_part[pid].append({
            "fab_id": fab,
            "fab_label": FAB_DISPLAY.get(fab, fab),
            "on_hand": _num(row.get("on_hand", 0)),
            "reorder_point": _num(
                policy_by_part.get(pid, {}).get("reorder_point", 0)
            ),
        })

    # Compose part entries with a status label.
    parts = []
    fab_set = set()
    for pid in sorted(inv_by_part.keys()):
        fabs = sorted(inv_by_part[pid], key=lambda f: f["fab_label"])
        for f in fabs:
            fab_set.add(f["fab_id"])

        gold_driver = gold_by_part.get(pid)
        if gold_driver in ("policy", "supply", "demand"):
            status = gold_driver
        elif gold_driver == "none":
            status = "healthy"
        else:
            status = "healthy"

        parts.append({
            "part_id": pid,
            "status": status,
            "fabs": fabs,
        })

    # Stable sort: drift-seeded first (so the "drift only" view is fast to
    # scroll), then healthy by part_id. Within drift, cluster by driver.
    driver_rank = {"policy": 0, "supply": 1, "demand": 2, "healthy": 3}
    parts.sort(key=lambda p: (driver_rank.get(p["status"], 9), p["part_id"]))

    payload = {
        "generated_at": date.today().isoformat(),
        "total_parts": len(parts),
        "total_fabs": len(fab_set),
        "parts": parts,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload))

    raw_kb = OUTPUT.stat().st_size / 1024
    print(f"Wrote {OUTPUT}")
    print(f"  total parts: {payload['total_parts']}")
    print(f"  total fabs:  {payload['total_fabs']}")
    print(f"  file size:   {raw_kb:.1f} KB")

    # Per-status breakdown
    counts: dict[str, int] = defaultdict(int)
    for p in parts:
        counts[p["status"]] += 1
    for s in ("policy", "supply", "demand", "healthy"):
        if s in counts:
            print(f"  {s:8s}  {counts[s]:3d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
