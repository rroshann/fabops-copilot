"""Test get_inventory tool against moto-mocked DynamoDB."""
import boto3
import pytest
from moto import mock_aws

from fabops.config import TABLE_INVENTORY
from fabops.tools.get_inventory import run as get_inventory_run


@pytest.fixture
def inventory_table():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName=TABLE_INVENTORY,
            KeySchema=[
                {"AttributeName": "part_id", "KeyType": "HASH"},
                {"AttributeName": "fab_id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "part_id", "AttributeType": "S"},
                {"AttributeName": "fab_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        ddb.get_waiter("table_exists").wait(TableName=TABLE_INVENTORY)
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE_INVENTORY)
        table.put_item(Item={
            "part_id": "A7",
            "fab_id": "taiwan",
            "on_hand": 5,
            "in_transit": 2,
            "reserved": 1,
            "available": 6,
            "as_of": "2026-04-13",
        })
        yield table


def test_get_inventory_returns_exact_row(inventory_table):
    result = get_inventory_run(part_id="A7", fab_id="taiwan")
    assert result.ok
    assert result.data["on_hand"] == 5
    assert result.data["available"] == 6
    assert len(result.citations) == 1


def test_get_inventory_missing_row(inventory_table):
    result = get_inventory_run(part_id="ZZZ", fab_id="nowhere")
    assert not result.ok
    assert "not found" in result.error.lower()
