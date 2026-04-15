"""search_company_disclosures. Full-scan cosine over pre-built EDGAR index.

Spec Section 5.4. Acceptable at N<20K chunks. Ingest is Day-0 pre-work
(scripts/ingest_edgar.py). Until ingest runs, fabops_edgar_index is empty
and this tool returns {"hits": []}.

Runtime constraint: the deployed Lambda zip does NOT bundle numpy (would
blow the 50 MB ceiling). All vector math here is pure Python so the tool
works identically in dev (venv with numpy) and on Lambda (no numpy).

Cold-start fix: the chunks are pre-baked into
`fabops/tools/_edgar_chunks.json.gz` by `scripts/prebake_edgar_chunks.py`
and shipped inside the Lambda zip. Module-scope import loads them at
init time (Lambda boosted CPU, does not count against the API Gateway
30-second invocation clock), which drops cold-start from ~50s (DynamoDB
full scan of 1079 items) to ~8s (gzip decompress + json parse of a
17 MB asset). DynamoDB remains the fallback for local dev when the
asset has not been generated yet.
"""
import gzip
import json
import math
import os
import time
from pathlib import Path
from typing import List, Optional

from fabops.config import TABLE_EDGAR, AWS_REGION
from fabops.tools.base import Citation, ToolResult

EMBED_MODEL = "models/gemini-embedding-001"

# Module-level cache to survive across warm Lambda invocations
_CHUNK_CACHE: Optional[List[dict]] = None

# Path to the pre-baked gzipped JSON asset. Sits next to this module,
# so both the local venv and the Lambda runtime resolve it the same way.
_BAKED_ASSET = Path(__file__).parent / "_edgar_chunks.json.gz"


def _embed_query(query: str) -> List[float]:
    import google.generativeai as genai
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    result = genai.embed_content(
        model=EMBED_MODEL,
        content=query,
        task_type="retrieval_query",
    )
    return [float(x) for x in result["embedding"]]


def _load_from_baked_asset() -> Optional[List[dict]]:
    """Load chunks from the gzipped JSON shipped with the package.

    Returns None if the asset is missing (e.g. local dev before the
    prebake script has been run). Raises if the asset exists but
    cannot be parsed, since a corrupt asset is a deploy-time bug
    that should fail loudly.
    """
    if not _BAKED_ASSET.exists():
        return None
    raw = gzip.decompress(_BAKED_ASSET.read_bytes())
    payload = json.loads(raw)
    return payload.get("chunks", [])


def _load_from_dynamodb() -> List[dict]:
    """Fallback: full-scan fabops_edgar_index from DynamoDB.

    Only used in local dev when the pre-baked asset has not been
    generated yet. The Lambda runtime should never hit this path.
    """
    import boto3

    table = boto3.resource("dynamodb", region_name=AWS_REGION).Table(TABLE_EDGAR)
    items: List[dict] = []
    resp = table.scan()
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))
    return items


def _load_all_chunks() -> List[dict]:
    """Load the full EDGAR chunk index.

    Preference order: pre-baked asset first, DynamoDB fallback second.
    The baked asset dominates in production because it avoids the
    43-second DynamoDB full scan during Lambda cold start.
    """
    baked = _load_from_baked_asset()
    if baked is not None:
        return baked
    return _load_from_dynamodb()


# Eagerly populate the cache at module import so the cost lands in
# Lambda's init phase (boosted CPU, free clock) instead of the first
# invocation. Wrapped in try/except so a broken asset does not prevent
# the module from importing at all; we fall back to lazy loading on
# the first call in that case.
try:
    _CHUNK_CACHE = _load_all_chunks()
except Exception as _init_err:  # pragma: no cover, intentional broad catch
    print(f"[search_disclosures] eager load failed, will retry lazily: {_init_err}")
    _CHUNK_CACHE = None


def _cosine(a: List[float], b: List[float]) -> float:
    """Pure-Python cosine similarity. O(n) over the shared length."""
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def reset_cache() -> None:
    """Clear the module-level chunk cache. Used by tests."""
    global _CHUNK_CACHE
    _CHUNK_CACHE = None


def run(query: str, top_k: int = 5, date_from: Optional[str] = None) -> ToolResult:
    global _CHUNK_CACHE
    t0 = time.time()

    if _CHUNK_CACHE is None:
        _CHUNK_CACHE = _load_all_chunks()

    if not _CHUNK_CACHE:
        return ToolResult(
            ok=True,
            data={"hits": [], "note": "EDGAR index is empty; run scripts/ingest_edgar.py first"},
            latency_ms=(time.time() - t0) * 1000,
        )

    qvec = _embed_query(query)
    hits = []
    for chunk in _CHUNK_CACHE:
        if date_from and chunk.get("filing_date", "") < date_from:
            continue
        cvec = [float(x) for x in chunk["embedding"]]
        score = _cosine(qvec, cvec)
        hits.append((score, chunk))

    hits.sort(key=lambda x: x[0], reverse=True)
    top = hits[:top_k]

    return ToolResult(
        ok=True,
        data={
            "hits": [
                {
                    "filing_type": c["form"],
                    "filing_date": c["filing_date"],
                    "excerpt": c["text"][:400],
                    "relevance": round(score, 4),
                    "sec_url": c["sec_url"],
                }
                for score, c in top
            ]
        },
        citations=[
            Citation(
                source=f"SEC {c['form']} {c['filing_date']}",
                url=c["sec_url"],
                excerpt=c["text"][:200],
            )
            for _, c in top[:3]
        ],
        latency_ms=(time.time() - t0) * 1000,
    )
