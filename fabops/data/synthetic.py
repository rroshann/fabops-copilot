"""Synthetic overlays for data no semi OEM discloses publicly.

Generates:
  - inventory state per (part_id, fab_id)
  - supplier lead-time panels
  - service-incident notes corpus

All explicitly labeled synthetic in the UI and technical report.
Parameters are seeded from published industry aggregates where possible.
"""
import random
from datetime import date, timedelta
from typing import Dict, List

# Real Applied Materials fab / service-site locations (public disclosures)
AM_FABS: List[str] = [
    "santa-clara-ca",
    "austin-tx",
    "gloucester-ma",
    "kalispell-mt",
    "dresden-de",
    "singapore",
    "taiwan",          # major customer fab region
    "arizona",         # major customer fab region
    "kumamoto-jp",
]


def generate_inventory(part_ids: List[str], seed: int = 42) -> List[Dict]:
    """Generate synthetic on_hand / in_transit / reserved per (part, fab)."""
    rng = random.Random(seed)
    out = []
    for part_id in part_ids:
        for fab_id in AM_FABS:
            # Lumpy part distribution: mostly low-single-digit, occasional zero
            on_hand = max(0, int(rng.gauss(mu=8, sigma=5)))
            in_transit = rng.choice([0, 0, 0, 2, 4, 8])
            reserved = min(on_hand, rng.choice([0, 0, 1, 2]))
            out.append({
                "part_id": part_id,
                "fab_id": fab_id,
                "on_hand": on_hand,
                "in_transit": in_transit,
                "reserved": reserved,
                "available": on_hand - reserved + in_transit,
                "as_of": date.today().isoformat(),
            })
    return out


def generate_suppliers(n_suppliers: int = 20, seed: int = 42) -> List[Dict]:
    """Generate synthetic supplier lead-time panels.

    Lead times are Gamma-distributed; means and stds vary by supplier tier.
    """
    rng = random.Random(seed)
    trends = ["improving", "stable", "stable", "stable", "degrading"]
    out = []
    for i in range(n_suppliers):
        tier = rng.choice([1, 1, 2, 2, 3])
        mean = {1: 14.0, 2: 35.0, 3: 75.0}[tier]
        std = {1: 3.0, 2: 10.0, 3: 25.0}[tier]
        mean += rng.gauss(0, 2)
        std += rng.gauss(0, 1)
        last_shipment = date.today() - timedelta(days=rng.randint(1, 14))
        out.append({
            "supplier_id": f"SUP-{i:03d}",
            "tier": tier,
            "mean_leadtime_days": round(max(5.0, mean), 1),
            "std_leadtime_days": round(max(0.5, std), 1),
            "last_observed_shipment": last_shipment.isoformat(),
            "trend_30d": rng.choice(trends),
        })
    return out


def generate_incidents(n_incidents: int = 100, seed: int = 42) -> List[Dict]:
    """Generate synthetic service-incident notes in realistic fab-ops voice.

    Used to populate the corpus for future incident-search tool.
    """
    rng = random.Random(seed)
    templates = [
        "Part {part} flagged stockout risk at {fab} on {date}. Demand rate {rate} units/week.",
        "Supplier {sup} reported {days}-day delay on order #{order} for {fab} fab.",
        "Policy review on part {part}: safety stock recomputed; z-score {z}.",
        "Install base at {fab} grew by {n} tools; reorder points need refresh.",
        "Expedite authorized: supplier {sup} airfreight for part {part} to {fab}.",
    ]
    out = []
    for i in range(n_incidents):
        tpl = rng.choice(templates)
        text = tpl.format(
            part=f"A{rng.randint(1, 50)}",
            fab=rng.choice(AM_FABS),
            date=(date.today() - timedelta(days=rng.randint(1, 180))).isoformat(),
            rate=rng.randint(1, 20),
            sup=f"SUP-{rng.randint(0, 19):03d}",
            days=rng.randint(3, 45),
            order=rng.randint(10000, 99999),
            z=round(rng.uniform(1.28, 2.33), 2),
            n=rng.randint(1, 8),
        )
        out.append({
            "incident_id": f"INC-{i:04d}",
            "text": text,
            "created_at": (date.today() - timedelta(days=rng.randint(1, 180))).isoformat(),
        })
    return out
