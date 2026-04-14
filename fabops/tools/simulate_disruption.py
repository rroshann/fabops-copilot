"""simulate_supplier_disruption — prescriptive expedite decision.

Spec Section 5.7. Re-runs the (s,S) expedite math under a shocked lead time.
"""
import time

from fabops.tools.base import Citation, ToolResult
from fabops.tools.forecast_demand import run as forecast_run
from fabops.tools.get_inventory import run as inv_run
from fabops.tools.get_supplier_leadtime import run as supplier_run


def run(supplier_id: str, delay_days: int, part_id: str, fab_id: str = "taiwan") -> ToolResult:
    t0 = time.time()

    inv = inv_run(part_id=part_id, fab_id=fab_id)
    if not inv.ok:
        return ToolResult(
            ok=False,
            error=inv.error,
            latency_ms=(time.time() - t0) * 1000,
        )
    on_hand = inv.data["on_hand"]

    fc = forecast_run(part_id=part_id, horizon_months=12, on_hand=on_hand)
    if not fc.ok:
        return ToolResult(
            ok=False,
            error=fc.error or "forecast_demand failed",
            latency_ms=(time.time() - t0) * 1000,
        )
    baseline_date = fc.data.get("p90_stockout_date")

    sup = supplier_run(supplier_id=supplier_id)
    if not sup.ok:
        return ToolResult(
            ok=False,
            error=sup.error,
            latency_ms=(time.time() - t0) * 1000,
        )

    # Simulate disruption: reduce effective on_hand by (daily_rate * delay_days)
    daily_rate = fc.data["forecast"][0] / 30.0 if fc.data["forecast"] else 0.0
    effective_on_hand = max(0, on_hand - int(daily_rate * delay_days))

    disrupted_fc = forecast_run(
        part_id=part_id,
        horizon_months=12,
        on_hand=effective_on_hand,
    )
    disrupted_date = disrupted_fc.data.get("p90_stockout_date") if disrupted_fc.ok else None

    # Crude cost model (placeholder — the report can highlight these are illustrative)
    expedite_cost = 15000 + 500 * delay_days
    accept_cost = 50000 if disrupted_date and baseline_date and disrupted_date < baseline_date else 5000
    action = "expedite" if expedite_cost < accept_cost else "accept"

    return ToolResult(
        ok=True,
        data={
            "baseline_stockout_date": baseline_date,
            "disrupted_stockout_date": disrupted_date,
            "expedite_cost": expedite_cost,
            "accept_cost": accept_cost,
            "recommended_action": action,
            "policy_used": "(s,S)",
            "delay_days": delay_days,
            "supplier_id": supplier_id,
        },
        citations=[
            Citation(
                source="(s,S) policy under shocked lead time",
                excerpt=f"delay={delay_days}d; action={action}",
            )
        ],
        latency_ms=(time.time() - t0) * 1000,
    )
