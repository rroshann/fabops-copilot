"""Day 1 smoke test: write a fake tool call to real fabops_audit."""
from fabops.observability.audit import AuditWriter
from fabops.observability.request_id import new_request_id

req_id = new_request_id()
writer = AuditWriter(req_id)
writer.log_step(
    node="SMOKE_TEST_fake_tool",
    args={"part_id": "A7", "fab_id": "taiwan"},
    result={"ok": True, "data": {"p90_stockout_date": "2026-05-03"}},
    latency_ms=42.1,
)
print(f"Wrote smoke test row with request_id={req_id}")
print(f"Verify: aws dynamodb query --table-name fabops_audit "
      f"--key-condition-expression 'request_id = :r' "
      f"--expression-attribute-values '{{\":r\":{{\"S\":\"{req_id}\"}}}}'")
