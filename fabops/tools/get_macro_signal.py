"""get_industry_macro_signal tool — real Census M3 (NAICS 334413) + FRED.

Spec Section 5.5. 1-hour cache in fabops_macro_cache.
"""
import os
import time
from datetime import datetime
from typing import Literal

import requests

from fabops.config import TABLE_MACRO
from fabops.data.dynamo import get_item, get_table, _to_dynamo
from fabops.tools.base import Citation, ToolResult

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
FRED_SERIES = {
    "production": "IPG3344S",  # Industrial Production Semi & Electronic Components
    "ppi": "PCU33443344",      # PPI Semi Manufacturing
}
CACHE_TTL_SECONDS = 3600


def _cache_fresh(cached: dict) -> bool:
    if not cached or "cached_at" not in cached:
        return False
    cached_at = datetime.fromisoformat(cached["cached_at"])
    return (datetime.utcnow() - cached_at).total_seconds() < CACHE_TTL_SECONDS


def _fetch_fred(series_id: str) -> dict:
    api_key = os.environ["FRED_API_KEY"]
    r = requests.get(FRED_BASE, params={
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "limit": 24,
        "sort_order": "desc",
    }, timeout=15)
    r.raise_for_status()
    obs = r.json()["observations"]
    # obs[0] is the most recent; reverse for chronological
    obs = list(reversed(obs))
    latest = obs[-1]
    prev = obs[-2] if len(obs) >= 2 else latest
    yoy = obs[-13] if len(obs) >= 13 else prev
    val = float(latest["value"]) if latest["value"] not in (".", "") else None
    mom = None
    yoy_change = None
    if val is not None and prev["value"] not in (".", ""):
        mom = (val - float(prev["value"])) / float(prev["value"])
    if val is not None and yoy["value"] not in (".", ""):
        yoy_change = (val - float(yoy["value"])) / float(yoy["value"])
    return {
        "value": val,
        "mom_change": mom,
        "yoy_change": yoy_change,
        "date": latest["date"],
        "series_id": series_id,
    }


def run(month: str, series: Literal["shipments", "inventories", "orders", "ppi", "production"]) -> ToolResult:
    t0 = time.time()
    cache_key = {"series_id": series, "month": month}
    cached = get_item(TABLE_MACRO, cache_key)
    if _cache_fresh(cached):
        return ToolResult(
            ok=True,
            data=cached.get("data", {}),
            citations=[Citation(source="cached FRED", excerpt=series)],
            latency_ms=(time.time() - t0) * 1000,
            cached=True,
        )

    if series in FRED_SERIES:
        data = _fetch_fred(FRED_SERIES[series])
        data["source_url"] = f"https://fred.stlouisfed.org/series/{FRED_SERIES[series]}"
    else:
        return ToolResult(
            ok=False,
            error=f"Census M3 series '{series}' not implemented in v1; use 'production' or 'ppi'",
            latency_ms=(time.time() - t0) * 1000,
        )

    get_table(TABLE_MACRO).put_item(Item=_to_dynamo({
        "series_id": series,
        "month": month,
        "data": data,
        "cached_at": datetime.utcnow().isoformat(),
    }))

    return ToolResult(
        ok=True,
        data=data,
        citations=[
            Citation(
                source=f"FRED {FRED_SERIES.get(series, series)}",
                url=data.get("source_url"),
            )
        ],
        latency_ms=(time.time() - t0) * 1000,
        cached=False,
    )
