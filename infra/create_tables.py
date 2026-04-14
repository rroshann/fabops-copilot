"""Create all DynamoDB tables for FabOps Copilot.

Run: python infra/create_tables.py
Idempotent — safe to re-run.
"""
import boto3
from botocore.exceptions import ClientError

from fabops.config import (
    AWS_REGION, TABLE_AUDIT, TABLE_SESSIONS, TABLE_FORECASTS, TABLE_POLICIES,
    TABLE_INVENTORY, TABLE_SUPPLIERS, TABLE_EDGAR, TABLE_INCIDENTS, TABLE_MACRO,
)

TABLES = [
    # (name, partition_key, sort_key_or_none)
    (TABLE_AUDIT, ("request_id", "S"), ("step_n", "N")),
    (TABLE_SESSIONS, ("session_id", "S"), ("message_ts", "S")),
    (TABLE_FORECASTS, ("part_id", "S"), ("forecast_run_id", "S")),
    (TABLE_POLICIES, ("part_id", "S"), None),
    (TABLE_INVENTORY, ("part_id", "S"), ("fab_id", "S")),
    (TABLE_SUPPLIERS, ("supplier_id", "S"), ("observed_date", "S")),
    (TABLE_EDGAR, ("doc_id", "S"), ("chunk_id", "S")),
    (TABLE_INCIDENTS, ("incident_id", "S"), None),
    (TABLE_MACRO, ("series_id", "S"), ("month", "S")),
]


def create_table(ddb, name, pk, sk):
    key_schema = [{"AttributeName": pk[0], "KeyType": "HASH"}]
    attr_defs = [{"AttributeName": pk[0], "AttributeType": pk[1]}]
    if sk is not None:
        key_schema.append({"AttributeName": sk[0], "KeyType": "RANGE"})
        attr_defs.append({"AttributeName": sk[0], "AttributeType": sk[1]})
    try:
        ddb.create_table(
            TableName=name,
            KeySchema=key_schema,
            AttributeDefinitions=attr_defs,
            BillingMode="PAY_PER_REQUEST",
        )
        print(f"  Created {name}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            print(f"  {name} already exists")
        else:
            raise


def main():
    ddb = boto3.client("dynamodb", region_name=AWS_REGION)
    print("Creating DynamoDB tables:")
    # Build audit table FIRST — it is the system spine
    for name, pk, sk in TABLES:
        create_table(ddb, name, pk, sk)
    print("Waiting for tables to become ACTIVE...")
    waiter = ddb.get_waiter("table_exists")
    for name, _, _ in TABLES:
        waiter.wait(TableName=name)
    print("All tables ACTIVE.")


if __name__ == "__main__":
    main()
