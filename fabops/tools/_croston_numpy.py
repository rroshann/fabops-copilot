"""Pure-NumPy Croston / SBA / TSB for runtime fallback when statsforecast unavailable.

Croston's method (1972): separate forecasts of (a) non-zero demand size and
(b) inter-arrival interval between non-zero demands. Both smoothed via SES.

This fallback is used by the runtime Lambda when the nightly bake cache misses
and we do not want to import statsforecast (which blows the 50MB ceiling).
"""
from typing import List, Tuple

import numpy as np


def croston(
    demand: List[float],
    horizon: int,
    alpha: float = 0.1,
    variant: str = "classic",
) -> Tuple[List[float], List[float], List[float]]:
    """Return (forecast, p10, p90) each of length `horizon`.

    Variants:
        classic: Croston (1972)
        sba:     Syntetos-Boylan Approximation — bias-corrected
    """
    d = np.asarray(demand, dtype=float)
    nonzero_idx = np.where(d > 0)[0]
    if len(nonzero_idx) == 0:
        zeros = [0.0] * horizon
        return zeros, zeros, zeros

    sizes = d[nonzero_idx]
    intervals = np.diff(np.concatenate([[-1], nonzero_idx])).astype(float)

    # SES on sizes and intervals
    z = sizes[0]
    x = intervals[0] if len(intervals) else 1.0
    for i in range(1, len(sizes)):
        z = alpha * sizes[i] + (1 - alpha) * z
        x = alpha * intervals[i] + (1 - alpha) * x

    yhat = z / x if x > 0 else 0.0
    if variant == "sba":
        yhat = (1 - alpha / 2) * yhat

    # Rough variance estimate from residuals
    residual_std = float(sizes.std()) if len(sizes) > 1 else float(sizes[0] * 0.3)
    p10 = max(0.0, yhat - 1.28 * residual_std)
    p90 = yhat + 1.28 * residual_std

    return [float(yhat)] * horizon, [float(p10)] * horizon, [float(p90)] * horizon


def compute_p90_stockout_date(
    forecast_p90: List[float],
    on_hand: int,
    start_month_iso: str,
) -> dict:
    """Given P90 demand forecast and on_hand inventory, return the earliest
    month when cumulative P90 demand exceeds on_hand.

    Returns dict with 'p90_stockout_date' (ISO date string or None)
    and 'stockout_date_uncertainty_days' (int).
    """
    from datetime import date, timedelta
    cumulative = 0.0
    start = date.fromisoformat(start_month_iso)
    for month_offset, d in enumerate(forecast_p90):
        cumulative += d
        if cumulative >= on_hand:
            stockout = start + timedelta(days=30 * month_offset)
            return {
                "p90_stockout_date": stockout.isoformat(),
                "stockout_date_uncertainty_days": 15,
            }
    return {"p90_stockout_date": None, "stockout_date_uncertainty_days": None}
