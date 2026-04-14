"""Nightly bake Lambda entry point (stub; full impl Day 2)."""
import json


def handler(event, context):
    return {
        "statusCode": 200,
        "body": json.dumps({"msg": "nightly_bake stub", "event": event}),
    }
