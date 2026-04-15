"""One-time pre-bake of the EDGAR chunk index into a gzipped JSON asset.

Root cause fix for the 43-second cold start. Instead of scanning
fabops_edgar_index from DynamoDB on every Lambda cold start, we scan
it once here on the local machine and ship the result inside the
Lambda zip. The runtime tool loads it from disk at module-scope
import, which runs during Lambda's boosted-CPU init phase and does
not count against the API Gateway 30-second invocation clock.

Run:
    PYTHONPATH=$(pwd) .venv/bin/python scripts/prebake_edgar_chunks.py

Output:
    fabops/tools/_edgar_chunks.json.gz

This file is checked into git because it is the canonical source
of truth for the Lambda runtime. Re-run this script any time the
fabops_edgar_index table changes (which should be rare, only after
scripts/ingest_edgar.py).
"""
import gzip
import json
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import boto3

from fabops.config import AWS_REGION, TABLE_EDGAR

OUTPUT = Path("fabops/tools/_edgar_chunks.json.gz")
SCHEMA_VERSION = 1


def _to_jsonable(value: Any) -> Any:
    """Convert Decimal to float so the result is JSON-serializable.

    DynamoDB returns numerics as Decimal. The runtime cosine math
    uses float anyway, so converting here is both safe and saves a
    conversion step at runtime.
    """
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    return value


def scan_all_chunks() -> list[dict]:
    table = boto3.resource("dynamodb", region_name=AWS_REGION).Table(TABLE_EDGAR)
    items: list[dict] = []
    resp = table.scan()
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))
    return items


def main() -> int:
    print(f"Scanning {TABLE_EDGAR} in {AWS_REGION}...")
    t0 = time.time()
    raw_items = scan_all_chunks()
    scan_elapsed = time.time() - t0
    print(f"  scanned {len(raw_items)} items in {scan_elapsed:.1f}s")

    if not raw_items:
        print("ERROR: table is empty. Run scripts/ingest_edgar.py first.", file=sys.stderr)
        return 1

    # Convert Decimal -> float and strip fields we do not need at runtime.
    # Keeping only the fields search_disclosures.run() actually reads.
    print("Normalizing items...")
    baked = []
    for item in raw_items:
        baked.append({
            "form": str(item.get("form", "")),
            "filing_date": str(item.get("filing_date", "")),
            "text": str(item.get("text", "")),
            "sec_url": str(item.get("sec_url", "")),
            "embedding": _to_jsonable(item.get("embedding", [])),
        })

    payload = {
        "schema_version": SCHEMA_VERSION,
        "table": TABLE_EDGAR,
        "count": len(baked),
        "chunks": baked,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    print(f"Serializing to {OUTPUT}...")
    # Compact JSON (no whitespace), then gzip at maximum compression.
    # Floats dominate the payload, so gzip ratio is modest (~2x) but
    # meaningful.
    raw_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    gz_bytes = gzip.compress(raw_bytes, compresslevel=9)
    OUTPUT.write_bytes(gz_bytes)

    raw_mb = len(raw_bytes) / (1024 * 1024)
    gz_mb = len(gz_bytes) / (1024 * 1024)
    print(f"  raw JSON: {raw_mb:.2f} MB")
    print(f"  gzipped:  {gz_mb:.2f} MB")
    print(f"  ratio:    {raw_mb / gz_mb:.1f}x")

    if gz_mb > 20:
        print(
            "WARNING: gzipped payload exceeds 20 MB. The Lambda zip ceiling "
            "is 50 MB and the current deps are ~26 MB, so this may push us "
            "over. Consider reducing embedding precision or moving to S3.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
