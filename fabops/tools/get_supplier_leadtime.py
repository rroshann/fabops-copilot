"""get_supplier_leadtime tool — reads synthetic supplier panels from DynamoDB.

Spec Section 5.3. Part->supplier mapping is a deterministic hash for v1
(no real part-supplier relationship in the synthetic data).
"""
import hashlib
import time
from typing import Optional

from fabops.config import TABLE_SUPPLIERS
from fabops.data.dynamo import query
from fabops.tools.base import Citation, ToolResult


def _supplier_for_part(part_id: str) -> str:
    idx = int(hashlib.md5(part_id.encode()).hexdigest(), 16) % 20
    return f"SUP-{idx:03d}"


def run(supplier_id: Optional[str] = None, part_id: Optional[str] = None) -> ToolResult:
    t0 = time.time()
    if supplier_id is None:
        if part_id is None:
            return ToolResult(
                ok=False,
                error="must provide supplier_id or part_id",
                latency_ms=(time.time() - t0) * 1000,
            )
        supplier_id = _supplier_for_part(part_id)

    items = query(
        TABLE_SUPPLIERS,
        key_condition_expression="supplier_id = :s",
        expression_attribute_values={":s": supplier_id},
    )
    latency = (time.time() - t0) * 1000
    if not items:
        return ToolResult(
            ok=False,
            error=f"supplier {supplier_id} not found",
            latency_ms=latency,
        )
    latest = sorted(items, key=lambda x: x["observed_date"], reverse=True)[0]
    return ToolResult(
        ok=True,
        data={
            "supplier_id": supplier_id,
            "mean_leadtime_days": latest["mean_leadtime_days"],
            "std_leadtime_days": latest["std_leadtime_days"],
            "last_observed_shipment": latest["last_observed_shipment"],
            "trend_30d": latest["trend_30d"],
        },
        citations=[
            Citation(
                source="synthetic supplier panel (labeled in UI)",
                excerpt=f"{supplier_id} mean LT {latest['mean_leadtime_days']}d",
            )
        ],
        latency_ms=latency,
    )
