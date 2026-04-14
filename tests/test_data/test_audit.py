"""Test the fabops_audit write helper against moto."""
import boto3
import pytest
from moto import mock_aws

from fabops.config import TABLE_AUDIT
from fabops.observability.audit import AuditWriter
from fabops.observability.request_id import new_request_id


@pytest.fixture
def ddb_table():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName=TABLE_AUDIT,
            KeySchema=[
                {"AttributeName": "request_id", "KeyType": "HASH"},
                {"AttributeName": "step_n", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "request_id", "AttributeType": "S"},
                {"AttributeName": "step_n", "AttributeType": "N"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        ddb.get_waiter("table_exists").wait(TableName=TABLE_AUDIT)
        yield boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE_AUDIT)


def test_audit_writer_records_step(ddb_table):
    req_id = new_request_id()
    writer = AuditWriter(req_id)
    writer.log_step(
        node="fake_tool",
        args={"part_id": "A7"},
        result={"ok": True},
        latency_ms=12.3,
        token_cost_usd=0.0,
    )
    items = ddb_table.query(
        KeyConditionExpression="request_id = :r",
        ExpressionAttributeValues={":r": req_id},
    )["Items"]
    assert len(items) == 1
    item = items[0]
    assert item["node"] == "fake_tool"
    assert item["step_n"] == 1
    assert "ts" in item


def test_audit_writer_increments_step(ddb_table):
    req_id = new_request_id()
    writer = AuditWriter(req_id)
    writer.log_step(node="step_a", args={}, result={}, latency_ms=1.0)
    writer.log_step(node="step_b", args={}, result={}, latency_ms=1.0)
    items = sorted(
        ddb_table.query(
            KeyConditionExpression="request_id = :r",
            ExpressionAttributeValues={":r": req_id},
        )["Items"],
        key=lambda x: x["step_n"],
    )
    assert len(items) == 2
    assert items[0]["step_n"] == 1
    assert items[1]["step_n"] == 2
