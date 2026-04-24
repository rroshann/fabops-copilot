"""Monitoring endpoint backing /monitor in the frontend.

Scans the `fabops_audit` DynamoDB spine, groups rows by request_id, and
returns per-request summaries plus aggregate stats suitable for a
read-only monitoring dashboard.

The heavy lifting lives in DDB; this handler is pure fan-in + shape.
Scan is acceptable because the audit table has at most a few thousand
rows per week at demo traffic. If usage grows, swap for a GSI on `ts`.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

import boto3

from fabops.config import AWS_REGION, TABLE_AUDIT


MAX_REQUESTS_RETURNED = 50


def _to_primitive(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_to_primitive(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_primitive(v) for k, v in value.items()}
    return value


def _summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Fold all rows for one request_id into a single summary dict."""
    rows_sorted = sorted(rows, key=lambda r: int(r.get("step_n", 0)))
    total_latency_ms = sum(float(r.get("latency_ms", 0)) for r in rows_sorted)
    first_ts = rows_sorted[0].get("ts") if rows_sorted else None

    user_query = ""
    primary_driver = None
    error = None
    for r in rows_sorted:
        args = r.get("args") or {}
        if not user_query and isinstance(args, dict) and "query" in args:
            user_query = args["query"]
        if r.get("node") == "diagnose":
            result = r.get("result") or {}
            if isinstance(result, dict):
                primary_driver = result.get("primary_driver")
        if r.get("node") == "runtime_error":
            error = r.get("error")

    return {
        "request_id": rows_sorted[0]["request_id"] if rows_sorted else "",
        "ts": first_ts,
        "user_query": user_query,
        "primary_driver": primary_driver,
        "step_count": len(rows_sorted),
        "total_latency_ms": round(total_latency_ms, 1),
        "ok": error is None,
        "error": error,
        "trace": [
            {
                "step_n": int(r.get("step_n", 0)),
                "node": r.get("node", ""),
                "latency_ms": round(float(r.get("latency_ms", 0)), 1),
                "ok": r.get("error") is None,
                "error": r.get("error"),
            }
            for r in rows_sorted
        ],
    }


def _scan_audit_table() -> List[Dict[str, Any]]:
    table = boto3.resource("dynamodb", region_name=AWS_REGION).Table(TABLE_AUDIT)
    items: List[Dict[str, Any]] = []
    resp = table.scan()
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))
    return items


def _aggregates(requests: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not requests:
        return {
            "total_requests": 0,
            "requests_24h": 0,
            "error_rate_pct": 0.0,
            "p50_latency_ms": 0,
            "p95_latency_ms": 0,
        }

    now = datetime.now(timezone.utc)
    recent = []
    for r in requests:
        ts = r.get("ts")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts)
            if (now - dt).total_seconds() < 86400:
                recent.append(r)
        except ValueError:
            continue

    latencies = sorted(float(r.get("total_latency_ms", 0)) for r in requests if r.get("ok"))
    def pct(p: float) -> int:
        if not latencies:
            return 0
        idx = min(len(latencies) - 1, int(len(latencies) * p))
        return int(latencies[idx])

    errors = sum(1 for r in requests if not r.get("ok"))
    return {
        "total_requests": len(requests),
        "requests_24h": len(recent),
        "error_rate_pct": round(errors / len(requests) * 100, 1),
        "p50_latency_ms": pct(0.5),
        "p95_latency_ms": pct(0.95),
    }


def handler(event, context):
    try:
        raw = _scan_audit_table()
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in raw:
            rid = row.get("request_id")
            if rid:
                groups[rid].append(row)

        summaries = [_summarize(rows) for rows in groups.values()]
        summaries = [_to_primitive(s) for s in summaries]
        summaries.sort(key=lambda s: s.get("ts") or "", reverse=True)
        capped = summaries[:MAX_REQUESTS_RETURNED]

        body = {
            "aggregates": _aggregates(summaries),
            "requests": capped,
            "returned": len(capped),
            "total_tracked": len(summaries),
        }
        return _response(200, body)
    except Exception as e:
        return _response(500, {"error": str(e), "type": type(e).__name__})


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
        "body": json.dumps(body),
    }
