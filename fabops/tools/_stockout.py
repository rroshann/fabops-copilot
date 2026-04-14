"""Pure-Python P90 stockout-date helper.

Extracted from `_croston_numpy` so the runtime Lambda (which does not bundle
numpy) can import it without triggering `import numpy`. The numpy-based
Croston/SBA fallback stays in `_croston_numpy` and is only used by the
nightly bake container (which does bundle numpy).
"""
from datetime import date, timedelta
from typing import List


def compute_p90_stockout_date(
    forecast_p90: List[float],
    on_hand: int,
    start_month_iso: str,
) -> dict:
    """Earliest month when cumulative P90 demand exceeds on_hand inventory.

    Returns dict with 'p90_stockout_date' (ISO date or None) and
    'stockout_date_uncertainty_days'.
    """
    cumulative = 0.0
    start = date.fromisoformat(start_month_iso)
    for month_offset, d in enumerate(forecast_p90):
        cumulative += float(d)
        if cumulative >= on_hand:
            stockout = start + timedelta(days=30 * month_offset)
            return {
                "p90_stockout_date": stockout.isoformat(),
                "stockout_date_uncertainty_days": 15,
            }
    return {"p90_stockout_date": None, "stockout_date_uncertainty_days": None}
