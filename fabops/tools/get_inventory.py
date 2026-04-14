"""get_inventory tool — reads synthetic inventory overlay from DynamoDB.

Spec Section 5.2. Synthetic data is explicitly labeled in the citation.
"""
import time

from fabops.config import TABLE_INVENTORY
from fabops.data.dynamo import get_item
from fabops.tools.base import Citation, ToolResult


def run(part_id: str, fab_id: str) -> ToolResult:
    t0 = time.time()
    item = get_item(TABLE_INVENTORY, {"part_id": part_id, "fab_id": fab_id})
    latency = (time.time() - t0) * 1000
    if not item:
        return ToolResult(
            ok=False,
            error=f"inventory not found for part_id={part_id} fab_id={fab_id}",
            latency_ms=latency,
        )
    return ToolResult(
        ok=True,
        data={
            "on_hand": item["on_hand"],
            "in_transit": item["in_transit"],
            "reserved": item["reserved"],
            "available": item["available"],
            "as_of": item["as_of"],
            "fab_id": fab_id,
            "part_id": part_id,
        },
        citations=[
            Citation(
                source="synthetic inventory overlay (labeled in UI)",
                excerpt=f"part {part_id} at {fab_id}: on_hand={item['on_hand']}",
            )
        ],
        latency_ms=latency,
    )
