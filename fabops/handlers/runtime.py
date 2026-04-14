"""Runtime agent Lambda entry point (stub; LangGraph wired in Day 5).

This is the zipped, <50MB Lambda. It MUST NOT import statsforecast, pandas,
numba, or mlflow. Heavy libs live in the container nightly Lambda.
"""
import json

from fabops.observability.audit import AuditWriter
from fabops.observability.request_id import new_request_id


def handler(event, context):
    request_id = new_request_id()
    writer = AuditWriter(request_id)
    writer.log_step(
        node="runtime_stub",
        args={"path": event.get("rawPath", "/")},
        result={"msg": "runtime Lambda alive"},
        latency_ms=0.0,
    )
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"request_id": request_id, "msg": "FabOps Copilot runtime alive"}),
    }
