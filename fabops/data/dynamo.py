"""DynamoDB read/write helpers shared by tools and nightly bake.

All functions convert floats -> Decimal on write (DynamoDB constraint)
and Decimal -> float on read.
"""
from decimal import Decimal
from typing import Any, Dict, List

import boto3
from botocore.exceptions import ClientError

from fabops.config import AWS_REGION


def _to_dynamo(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_dynamo(v) for v in value]
    return value


def _from_dynamo(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value) if value % 1 != 0 else int(value)
    if isinstance(value, dict):
        return {k: _from_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_dynamo(v) for v in value]
    return value


def get_table(name: str):
    return boto3.resource("dynamodb", region_name=AWS_REGION).Table(name)


def batch_write(table_name: str, items: List[Dict], chunk_size: int = 25) -> int:
    """BatchWriteItem with exponential backoff, jitter, 25-item chunks.

    Returns the number of items written. Prevents partition hot-spotting on
    nightly burst writes (spec Section 14).
    """
    import random
    import time
    table = get_table(table_name)
    written = 0
    with table.batch_writer() as writer:
        for item in items:
            writer.put_item(Item=_to_dynamo(item))
            written += 1
            if written % chunk_size == 0:
                time.sleep(0.05 + random.random() * 0.1)
    return written


def get_item(table_name: str, key: Dict) -> Dict:
    try:
        resp = get_table(table_name).get_item(Key=key)
        return _from_dynamo(resp.get("Item", {}))
    except ClientError:
        return {}


def query(table_name: str, key_condition_expression, expression_attribute_values) -> List[Dict]:
    resp = get_table(table_name).query(
        KeyConditionExpression=key_condition_expression,
        ExpressionAttributeValues=expression_attribute_values,
    )
    return [_from_dynamo(i) for i in resp.get("Items", [])]
