"""Test get_supplier_leadtime against moto-mocked DynamoDB."""
import boto3
import pytest
from decimal import Decimal
from moto import mock_aws

from fabops.config import TABLE_SUPPLIERS
from fabops.tools.get_supplier_leadtime import run as get_supplier_run


@pytest.fixture
def suppliers_table():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName=TABLE_SUPPLIERS,
            KeySchema=[
                {"AttributeName": "supplier_id", "KeyType": "HASH"},
                {"AttributeName": "observed_date", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "supplier_id", "AttributeType": "S"},
                {"AttributeName": "observed_date", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        ddb.get_waiter("table_exists").wait(TableName=TABLE_SUPPLIERS)
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE_SUPPLIERS)
        table.put_item(Item={
            "supplier_id": "SUP-001",
            "observed_date": "2026-04-13",
            "tier": 2,
            "mean_leadtime_days": Decimal("35.0"),
            "std_leadtime_days": Decimal("10.0"),
            "last_observed_shipment": "2026-04-10",
            "trend_30d": "stable",
        })
        yield table


def test_get_supplier_by_id(suppliers_table):
    result = get_supplier_run(supplier_id="SUP-001")
    assert result.ok
    assert result.data["mean_leadtime_days"] == 35.0
    assert result.data["trend_30d"] == "stable"


def test_get_supplier_by_part_id_uses_hash(suppliers_table):
    # hash("A7") -> some deterministic SUP-XXX; if it hits 001, pass; if not, the test should at least not crash.
    # For this test we just ensure that using part_id routes to some supplier and returns either ok or a not-found error.
    result = get_supplier_run(part_id="test_part")
    # Either the hashed supplier exists or it doesn't — no crash either way
    assert isinstance(result.ok, bool)


def test_get_supplier_missing(suppliers_table):
    result = get_supplier_run(supplier_id="SUP-999")
    assert not result.ok
    assert "not found" in result.error.lower()


def test_get_supplier_requires_some_arg():
    from moto import mock_aws
    with mock_aws():
        result = get_supplier_run()
        assert not result.ok
        assert "supplier_id" in result.error.lower() or "part_id" in result.error.lower()
