"""forecast_demand tool — runtime reads nightly-baked cache from DynamoDB.

Spec reference: Section 5.1. Never imports statsforecast at runtime.
"""
import time
from datetime import date
from typing import Optional

from fabops.config import TABLE_FORECASTS
from fabops.data.dynamo import query
from fabops.tools.base import Citation, ToolResult


def _read_cached_forecast(part_id: str) -> Optional[dict]:
    """Return the most recent cached forecast for a part, or None."""
    items = query(
        TABLE_FORECASTS,
        key_condition_expression="part_id = :p",
        expression_attribute_values={":p": part_id},
    )
    if not items:
        return None
    latest = sorted(items, key=lambda x: x["forecast_run_id"], reverse=True)[0]
    return latest


def _compute_forecast_from_history(part_id: str, horizon: int) -> dict:
    """Fallback: load part history from carparts and run NumPy Croston.

    Only used on cache miss. Slow-ish but keeps runtime honest.
    numpy and _croston_numpy are imported lazily here so the Lambda cold-start
    import path does not fail when numpy is absent from the zip.
    """
    from fabops.data.carparts import load_carparts
    from fabops.tools._croston_numpy import croston as _croston
    df = load_carparts()
    part_demand = df[df["part_id"] == part_id].sort_values("month")["demand"].tolist()
    yhat, p10, p90 = _croston(part_demand, horizon=horizon, variant="sba")
    return {
        "forecast": yhat,
        "p10": p10,
        "p90": p90,
        "model": "croston",
        "sMAPE": None,
        "MASE": None,
    }


def run(
    part_id: str,
    horizon_months: int = 12,
    service_level: float = 0.95,
    on_hand: Optional[int] = None,
) -> ToolResult:
    t0 = time.time()
    cached = _read_cached_forecast(part_id)
    if cached is not None:
        data = {
            "forecast": cached["forecast"],
            "p10": cached["p10"],
            "p90": cached["p90"],
            "model": cached["model"],
            "sMAPE": cached.get("sMAPE"),
            "MASE": cached.get("MASE"),
        }
        used_cache = True
    else:
        data = _compute_forecast_from_history(part_id, horizon_months)
        used_cache = False

    if on_hand is not None:
        from fabops.tools._croston_numpy import compute_p90_stockout_date as _compute_stockout
        stockout = _compute_stockout(
            data["p90"], on_hand, start_month_iso=date.today().isoformat()
        )
        data.update(stockout)
    else:
        data["p90_stockout_date"] = None
        data["stockout_date_uncertainty_days"] = None

    return ToolResult(
        ok=True,
        data=data,
        citations=[
            Citation(
                source="Hyndman carparts benchmark",
                url="https://zenodo.org/records/3994911",
                excerpt=f"Croston/SBA forecast for part {part_id}, horizon {horizon_months} months",
            )
        ],
        latency_ms=(time.time() - t0) * 1000,
        cached=used_cache,
    )
