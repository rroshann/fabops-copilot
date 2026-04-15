"""Transform the gold set into a static frontend catalog for the Browse Parts modal.

The frontend needs a list of parts a new visitor can click to explore the
agent without knowing a part ID in advance. The gold set already has 18
real parts with labeled drivers (6 policy, 9 supply, 3 demand), seeded
with deterministic drift by scripts/inject_gold_drift.py. This script
turns that gold set into a frontend-friendly catalog.json.

Zero runtime dependency. The catalog is a static JSON file shipped with
the Amplify deploy. No Lambda, no DynamoDB, no API call.

Run:
    PYTHONPATH=$(pwd) .venv/bin/python scripts/bake_catalog.py

Output:
    frontend/catalog.json

Re-run this any time the gold set is regenerated (scripts/regenerate_gold_set.py).
"""
import json
from pathlib import Path

GOLD_PATH = Path("evals/gold_set.json")
OUTPUT = Path("frontend/catalog.json")

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

DRIVER_GROUPS = [
    {
        "key": "policy",
        "label": "POLICY DRIFT",
        "description": "Policy was computed against old demand. The number is stale, not wrong.",
        "signal_template": "policy age > 365 days (threshold 90)",
    },
    {
        "key": "supply",
        "label": "SUPPLY RISK",
        "description": "A supplier is degrading. Lead-time slipping, on-time delivery dropping.",
        "signal_template": "supplier trend_30d = degrading",
    },
    {
        "key": "demand",
        "label": "DEMAND SHIFT",
        "description": "Real demand stepped up and depleted the on-hand buffer.",
        "signal_template": "on_hand = 0, buffer depleted",
    },
]


def fab_label(fab_id: str) -> str:
    return FAB_DISPLAY.get(fab_id, fab_id)


def main() -> int:
    cases = json.loads(GOLD_PATH.read_text())
    by_driver: dict[str, list[dict]] = {"policy": [], "supply": [], "demand": [], "none": []}
    for c in cases:
        driver = c.get("ground_truth_driver", "none")
        by_driver.setdefault(driver, []).append({
            "part_id": c["part_id"],
            "fab_id": c["fab_id"],
            "fab_label": fab_label(c["fab_id"]),
            "question": c["question"],
        })

    groups = []
    for g in DRIVER_GROUPS:
        parts = by_driver.get(g["key"], [])
        if not parts:
            continue
        groups.append({
            "driver": g["key"],
            "label": g["label"],
            "description": g["description"],
            "signal": g["signal_template"],
            "count": len(parts),
            "parts": parts,
        })

    payload = {
        "generated_from": str(GOLD_PATH),
        "total_parts": sum(g["count"] for g in groups),
        "groups": groups,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2))

    print(f"Wrote {OUTPUT}")
    print(f"  total parts: {payload['total_parts']}")
    for g in groups:
        print(f"  {g['label']:14s} {g['count']:2d} parts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
