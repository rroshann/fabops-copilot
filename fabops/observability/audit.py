"""fabops_audit DynamoDB spine writer.

This is the load-bearing observability path. Every tool call, node transition,
and LLM call writes one row here. All other sinks (Langfuse, MLflow, CloudWatch)
join against this table via request_id.

Build this BEFORE the agent. Smoke-test with a fake tool call. If this is wrong
or unreliable, every downstream component degrades silently.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

import boto3

from fabops.config import AWS_REGION, TABLE_AUDIT


def _to_dynamo(value: Any) -> Any:
    """Convert Python primitives to DynamoDB-safe types."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_dynamo(v) for v in value]
    return value


class AuditWriter:
    """Per-request audit writer. Build once at the entry node, reuse everywhere.

    Usage:
        writer = AuditWriter(request_id)
        writer.log_step(node="check_demand_drift", args={...}, result={...}, latency_ms=42.1)
    """

    def __init__(self, request_id: str):
        self.request_id = request_id
        self._step_n = 0
        self._table = boto3.resource("dynamodb", region_name=AWS_REGION).Table(TABLE_AUDIT)

    def log_step(
        self,
        node: str,
        args: Dict[str, Any],
        result: Dict[str, Any],
        latency_ms: float,
        token_cost_usd: float = 0.0,
        llm_model: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        self._step_n += 1
        item = {
            "request_id": self.request_id,
            "step_n": self._step_n,
            "node": node,
            "args": _to_dynamo(args),
            "result": _to_dynamo(result),
            "latency_ms": Decimal(str(latency_ms)),
            "token_cost_usd": Decimal(str(token_cost_usd)),
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if llm_model:
            item["llm_model"] = llm_model
        if error:
            item["error"] = error
        self._table.put_item(Item=item)
