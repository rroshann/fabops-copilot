"""compute_reorder_policy — classical OR safety-stock calculation.

Spec Section 5.6. Reads pre-baked demand stats from fabops_policies
(resolves the policy/demand circular dep). Runtime-safe: no scipy.
"""
import math
import time
from datetime import datetime

from fabops.config import TABLE_POLICIES
from fabops.data.dynamo import get_item, get_table, _to_dynamo
from fabops.tools.base import Citation, ToolResult

# Hand-rolled z-table — avoids scipy dependency (runtime zip constraint)
_Z_SCORES = {
    0.50: 0.0000,
    0.80: 0.8416,
    0.85: 1.0364,
    0.90: 1.2816,
    0.95: 1.6449,
    0.975: 1.9600,
    0.99: 2.3263,
    0.995: 2.5758,
    0.999: 3.0902,
}


def _z(service_level: float) -> float:
    """Look up or interpolate the z-score for a service level."""
    if service_level in _Z_SCORES:
        return _Z_SCORES[service_level]
    # Linear interpolation between nearest two known service levels
    levels = sorted(_Z_SCORES.keys())
    for i in range(len(levels) - 1):
        if levels[i] <= service_level <= levels[i + 1]:
            lo, hi = levels[i], levels[i + 1]
            frac = (service_level - lo) / (hi - lo)
            return _Z_SCORES[lo] + frac * (_Z_SCORES[hi] - _Z_SCORES[lo])
    # Out of range — clamp
    if service_level < levels[0]:
        return _Z_SCORES[levels[0]]
    return _Z_SCORES[levels[-1]]


def run(part_id: str, service_level: float = 0.95, lead_time_days: float = None) -> ToolResult:
    t0 = time.time()
    cached = get_item(TABLE_POLICIES, {"part_id": part_id})

    if cached and "leadtime_demand_mean" in cached:
        dlt_mean = cached["leadtime_demand_mean"]
        dlt_std = cached["leadtime_demand_std"]
        last_updated = cached.get("last_updated", datetime.utcnow().isoformat())
    else:
        # Fallback: compute crudely from carparts history
        from fabops.data.carparts import load_carparts
        df = load_carparts()
        part_demand = df[df["part_id"] == part_id]["demand"].to_numpy()
        if len(part_demand) == 0:
            return ToolResult(
                ok=False,
                error=f"no demand history for {part_id}",
                latency_ms=(time.time() - t0) * 1000,
            )
        L = lead_time_days or 30.0
        monthly_mean = float(part_demand.mean())
        monthly_std = float(part_demand.std())
        dlt_mean = monthly_mean * (L / 30.0)
        dlt_std = monthly_std * math.sqrt(L / 30.0)
        last_updated = datetime.utcnow().isoformat()

    z = _z(service_level)
    safety_stock = z * dlt_std
    reorder_point = dlt_mean + safety_stock
    order_up_to = reorder_point + dlt_mean  # simple (s,S) with Q = dlt_mean

    staleness_days = (datetime.utcnow() - datetime.fromisoformat(last_updated)).days

    # Persist the computed policy
    get_table(TABLE_POLICIES).put_item(Item=_to_dynamo({
        "part_id": part_id,
        "reorder_point": reorder_point,
        "safety_stock": safety_stock,
        "order_up_to": order_up_to,
        "service_level": service_level,
        "z_score": z,
        "leadtime_demand_mean": dlt_mean,
        "leadtime_demand_std": dlt_std,
        "last_updated": last_updated,
        "staleness_days": staleness_days,
    }))

    return ToolResult(
        ok=True,
        data={
            "reorder_point": reorder_point,
            "safety_stock": safety_stock,
            "order_up_to": order_up_to,
            "service_level": service_level,
            "z_score": z,
            "leadtime_demand_mean": dlt_mean,
            "leadtime_demand_std": dlt_std,
            "last_updated": last_updated,
            "staleness_days": staleness_days,
        },
        citations=[
            Citation(
                source="classical OR safety-stock formula",
                excerpt=f"z({service_level})={z:.3f}; SS={safety_stock:.1f}; ROP={reorder_point:.1f}",
            )
        ],
        latency_ms=(time.time() - t0) * 1000,
        cached=cached is not None and "leadtime_demand_mean" in cached,
    )
