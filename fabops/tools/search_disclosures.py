"""search_company_disclosures — full-scan cosine over pre-built EDGAR index.

Spec Section 5.4. Acceptable at N<20K chunks. Ingest is Day-0 pre-work
(scripts/ingest_edgar.py). Until ingest runs, fabops_edgar_index is empty
and this tool returns {"hits": []}.
"""
import os
import time
from typing import List, Optional

import boto3

from fabops.config import TABLE_EDGAR, AWS_REGION
from fabops.tools.base import Citation, ToolResult

EMBED_MODEL = "models/gemini-embedding-001"

# Module-level cache to survive across warm Lambda invocations
_CHUNK_CACHE: Optional[List[dict]] = None


def _embed_query(query: str) -> "np.ndarray":
    import numpy as np
    import google.generativeai as genai
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    result = genai.embed_content(
        model=EMBED_MODEL,
        content=query,
        task_type="retrieval_query",
    )
    return np.array(result["embedding"], dtype=np.float32)


def _load_all_chunks() -> List[dict]:
    """Full-scan fabops_edgar_index. N<20K is acceptable (spec Section 3.2)."""
    table = boto3.resource("dynamodb", region_name=AWS_REGION).Table(TABLE_EDGAR)
    items: List[dict] = []
    resp = table.scan()
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))
    return items


def _cosine(a: "np.ndarray", b: "np.ndarray") -> float:
    import numpy as np
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


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

    import numpy as np
    qvec = _embed_query(query)
    hits = []
    for chunk in _CHUNK_CACHE:
        if date_from and chunk.get("filing_date", "") < date_from:
            continue
        cvec = np.array([float(x) for x in chunk["embedding"]], dtype=np.float32)
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
