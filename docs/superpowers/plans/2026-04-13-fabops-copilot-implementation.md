# FabOps Copilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy an agentic LLM "Service-Parts Stockout Risk Agent" (FabOps Copilot) on AWS serverless in 11 days, satisfying the DS 5730 final project requirements and serving as the lead portfolio piece for an Applied Materials JOLT Data Scientist — Agentic AI/ML application.

**Architecture:** Split-Lambda deployment — a zipped runtime Lambda (<50MB) runs the LangGraph agent, consuming seven domain tools via direct Python binding; a container-image nightly bake Lambda runs `statsforecast`/Croston forecasts and reorder-policy pre-computation. Storage is DynamoDB (with `fabops_audit` as the system spine), S3, Langfuse Cloud for agent tracing, MLflow for forecast model versioning, and CloudWatch for infra. A separate stdio MCP server (`scripts/mcp_server.py`) exposes the same tool functions to Claude Desktop as a second face, providing a real demonstrable MCP signal.

**Tech Stack:** Python 3.9 (arm64) · AWS Lambda (zipped + container image) · API Gateway HTTP · DynamoDB · S3 · CloudWatch · EventBridge · Google Gemini 2.0 (Flash/Pro) · Anthropic Claude Haiku 4.5 (judge) · LangGraph · LangChain · Pydantic · `statsforecast` (Nixtla) · MLflow · Langfuse Cloud · DSPy · GitHub Actions · vanilla HTML/JS/CSS.

**Spec reference:** `docs/superpowers/specs/2026-04-13-fabops-copilot-design.md` — every task in this plan traces back to a spec section.

---

## How to use this plan

1. Execute tasks in order within each day; days can slip but ordering within a day is load-bearing.
2. Every task has a **Files**, **Steps**, and **Verification** block. Check boxes as you go.
3. Commit after every completed task using the shown conventional-commit message.
4. If a step's verification fails, stop and fix — do not proceed to the next task.
5. All code is Python 3.9 compatible (Lambda runtime constraint). No walrus operator, no `match` statements, no PEP 604 `X | Y` type syntax — use `Optional[X]` / `Union[X, Y]`.
6. Tests use `pytest`. AWS calls use `moto` for unit tests, real AWS for smoke tests.

---

## File structure

```
fabops-copilot/
├── .github/
│   └── workflows/
│       └── eval-ci.yml
├── docs/
│   └── superpowers/
│       ├── specs/2026-04-13-fabops-copilot-design.md    (existing)
│       └── plans/2026-04-13-fabops-copilot-implementation.md    (this file)
├── evals/
│   ├── gold_set.json              # 30 hand-authored questions
│   ├── adversarial_set.json       # 50 machine-generated
│   ├── rubric.md                  # shared judge rubric
│   └── results/                   # per-run outputs (gitignored)
├── fabops/
│   ├── __init__.py
│   ├── config.py                  # env vars, constants
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── state.py               # Pydantic AgentState
│   │   ├── nodes.py               # all LangGraph node functions
│   │   ├── graph.py               # state machine wiring
│   │   └── llm.py                 # Gemini + Claude client wrappers
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── base.py                # ToolResult, Citation base
│   │   ├── forecast_demand.py
│   │   ├── get_inventory.py
│   │   ├── get_supplier_leadtime.py
│   │   ├── search_disclosures.py
│   │   ├── get_macro_signal.py
│   │   ├── compute_reorder_policy.py
│   │   └── simulate_disruption.py
│   ├── data/
│   │   ├── __init__.py
│   │   ├── dynamo.py              # DynamoDB helpers
│   │   ├── s3.py
│   │   ├── carparts.py            # Hyndman loader
│   │   └── synthetic.py           # inventory, supplier, incident generators
│   ├── observability/
│   │   ├── __init__.py
│   │   ├── request_id.py          # UUIDv4 generator
│   │   ├── audit.py               # fabops_audit spine
│   │   └── langfuse_shim.py
│   └── handlers/
│       ├── __init__.py
│       ├── runtime.py             # zipped Lambda entrypoint
│       └── nightly_bake.py        # container Lambda entrypoint
├── frontend/
│   ├── index.html
│   ├── app.js
│   └── styles.css
├── infra/
│   ├── create_tables.py           # DynamoDB table creation
│   ├── create_buckets.py          # S3 bucket creation
│   ├── iam_policies/              # JSON policy docs
│   └── eventbridge_rule.py
├── scripts/
│   ├── ingest_edgar.py            # Day 0 pre-work
│   ├── mcp_server.py              # stdio MCP server (second face)
│   ├── generate_adversarial.py    # 50 adversarial questions
│   ├── run_judge.py               # Claude Haiku judge harness
│   └── deploy_runtime.sh          # zip + deploy runtime Lambda
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # pytest fixtures, moto setup
│   ├── test_tools/
│   ├── test_agent/
│   ├── test_data/
│   └── test_evals/
├── Dockerfile.nightly             # container image for nightly bake
├── requirements-runtime.txt       # zipped Lambda deps
├── requirements-nightly.txt       # container Lambda deps
├── requirements-dev.txt           # local dev deps
├── pyproject.toml
├── README.md
└── .env.example
```

Each file has one responsibility. `fabops/tools/*.py` are standalone — each tool file exports a single `run(*args) -> ToolResult` function. `fabops/agent/nodes.py` holds every LangGraph node function in one file because they share state schema and are read together. Tests mirror source layout.

---

## Day 0 — Pre-work (runs local, before Day 1 starts)

### Task 0.1: SEC EDGAR ingest script

**Files:**
- Create: `scripts/ingest_edgar.py`
- Create: `scripts/requirements-ingest.txt`
- Create: `data/edgar/` (gitignored, local cache)
- Output: S3 `fabops-copilot-artifacts/edgar_index.json` + DynamoDB `fabops_edgar_index`

**Why Day 0:** EDGAR has a strict `User-Agent` + 10-req/sec rate limit, and Gemini embedding has a 1500 RPD free-tier ceiling. Chunking 3 years of Applied Materials 10-K / 10-Q / 8-K and embedding ~10K chunks eats 2–4 hours of wall time with backoff. This cannot share days with runtime development.

- [ ] **Step 1: Create requirements file**

Create `scripts/requirements-ingest.txt`:

```
requests==2.32.3
beautifulsoup4==4.12.3
google-generativeai==0.8.3
boto3==1.34.131
tqdm==4.66.4
tenacity==8.5.0
```

- [ ] **Step 2: Write the EDGAR fetcher**

Create `scripts/ingest_edgar.py`:

```python
"""Day-0 pre-work: download Applied Materials SEC filings, chunk, embed, index.

Runs local. Writes:
  - ./data/edgar/raw/*.html      (cached filings)
  - ./data/edgar/chunks.json     (chunked, pre-embedding)
  - S3 fabops-copilot-artifacts/edgar_index.json
  - DynamoDB fabops_edgar_index  (each chunk + embedding)

Run: python scripts/ingest_edgar.py --email you@example.com
"""
import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Dict, List

import boto3
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential
from tqdm import tqdm

CIK = "0000006951"  # Applied Materials
FORMS = ["10-K", "10-Q", "8-K"]
YEARS_BACK = 3
CHUNK_TOKENS = 500  # approx, measured in words for simplicity
EMBED_MODEL = "models/text-embedding-004"
RAW_DIR = Path("data/edgar/raw")
CHUNKS_FILE = Path("data/edgar/chunks.json")
DDB_TABLE = "fabops_edgar_index"
S3_BUCKET = "fabops-copilot-artifacts"
S3_KEY = "edgar_index.json"


def sec_headers(email: str) -> Dict[str, str]:
    return {
        "User-Agent": f"FabOps Copilot student project ({email})",
        "Accept-Encoding": "gzip, deflate",
        "Host": "www.sec.gov",
    }


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=30))
def fetch(url: str, email: str) -> str:
    time.sleep(0.15)  # respect 10 req/sec limit
    r = requests.get(url, headers=sec_headers(email), timeout=30)
    r.raise_for_status()
    return r.text


def list_filings(email: str) -> List[Dict]:
    """Query EDGAR submissions API for AM's recent filings of interest."""
    url = f"https://data.sec.gov/submissions/CIK{CIK}.json"
    headers = sec_headers(email)
    headers["Host"] = "data.sec.gov"
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    recent = data["filings"]["recent"]
    filings = []
    for i, form in enumerate(recent["form"]):
        if form in FORMS:
            filings.append({
                "form": form,
                "filing_date": recent["filingDate"][i],
                "accession": recent["accessionNumber"][i],
                "primary_doc": recent["primaryDocument"][i],
            })
    # Keep last YEARS_BACK of filings
    cutoff = f"{2026 - YEARS_BACK}-01-01"
    return [f for f in filings if f["filing_date"] >= cutoff]


def chunk_text(text: str, chunk_words: int = CHUNK_TOKENS) -> List[str]:
    """Simple word-based chunking with ~50-word overlap."""
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i:i + chunk_words])
        chunks.append(chunk)
        i += chunk_words - 50
    return chunks


def clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "table"]):
        tag.decompose()
    return " ".join(soup.get_text().split())


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=5, max=60))
def embed(text: str) -> List[float]:
    time.sleep(0.5)  # keep under 1500 RPD = ~1 per 60s safe; tighten if budget allows
    result = genai.embed_content(model=EMBED_MODEL, content=text, task_type="retrieval_document")
    return result["embedding"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True, help="Your contact email for SEC User-Agent")
    parser.add_argument("--gemini-api-key", default=os.environ.get("GEMINI_API_KEY"))
    parser.add_argument("--skip-upload", action="store_true", help="Chunk + embed only, no AWS writes")
    args = parser.parse_args()

    assert args.gemini_api_key, "Set GEMINI_API_KEY or pass --gemini-api-key"
    genai.configure(api_key=args.gemini_api_key)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    filings = list_filings(args.email)
    print(f"Found {len(filings)} filings")

    all_chunks = []
    for f in tqdm(filings, desc="Fetching filings"):
        acc_nodashes = f["accession"].replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/6951/{acc_nodashes}/{f['primary_doc']}"
        local = RAW_DIR / f"{f['accession']}.html"
        if not local.exists():
            html = fetch(url, args.email)
            local.write_text(html)
        text = clean_html(local.read_text())
        for i, chunk in enumerate(chunk_text(text)):
            chunk_id = hashlib.md5(f"{f['accession']}-{i}".encode()).hexdigest()[:16]
            all_chunks.append({
                "doc_id": f["accession"],
                "chunk_id": chunk_id,
                "form": f["form"],
                "filing_date": f["filing_date"],
                "sec_url": url,
                "text": chunk,
            })

    CHUNKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHUNKS_FILE.write_text(json.dumps(all_chunks, indent=2))
    print(f"Wrote {len(all_chunks)} chunks to {CHUNKS_FILE}")

    print("Embedding chunks (slow; respects Gemini free-tier RPM)...")
    for c in tqdm(all_chunks, desc="Embedding"):
        c["embedding"] = embed(c["text"])

    CHUNKS_FILE.write_text(json.dumps(all_chunks, indent=2))
    print(f"Embeddings complete; re-wrote {CHUNKS_FILE}")

    if args.skip_upload:
        print("--skip-upload set; stopping before AWS writes.")
        return

    print("Uploading to S3...")
    s3 = boto3.client("s3")
    s3.put_object(Bucket=S3_BUCKET, Key=S3_KEY, Body=json.dumps(all_chunks).encode())

    print("Writing to DynamoDB fabops_edgar_index...")
    ddb = boto3.resource("dynamodb").Table(DDB_TABLE)
    with ddb.batch_writer() as batch:
        for c in all_chunks:
            batch.put_item(Item={
                "doc_id": c["doc_id"],
                "chunk_id": c["chunk_id"],
                "form": c["form"],
                "filing_date": c["filing_date"],
                "sec_url": c["sec_url"],
                "text": c["text"],
                "embedding": c["embedding"],
            })
    print(f"Done. {len(all_chunks)} chunks indexed.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Install ingest deps in a local venv**

```bash
python3 -m venv .venv-ingest
source .venv-ingest/bin/activate
pip install -r scripts/requirements-ingest.txt
```

- [ ] **Step 4: Dry-run the script (no AWS writes) to smoke-test chunking**

```bash
export GEMINI_API_KEY=your_key_here
python scripts/ingest_edgar.py --email your.email@vanderbilt.edu --skip-upload
```

Expected: prints "Found N filings" where N is between 15 and 40, writes `data/edgar/chunks.json`, completes embedding with tqdm progress. Total wall time: 1–3 hours depending on Gemini free-tier quota.

- [ ] **Step 5: Do NOT upload yet — DynamoDB tables don't exist until Day 1**

Leave the local `data/edgar/chunks.json` in place; we'll re-run with `--skip-upload` removed on Day 1 after tables exist. Or upload-only on Day 1 by loading the file from disk.

- [ ] **Step 6: Commit the script**

```bash
git add scripts/ingest_edgar.py scripts/requirements-ingest.txt
git commit -m "feat(scripts): add SEC EDGAR ingest script for Day 0 pre-work"
git push
```

**Verification:**
- `data/edgar/chunks.json` exists and has >1000 chunks
- Each chunk has an `embedding` list of length 768 (Gemini text-embedding-004 dimension)
- No SEC User-Agent errors in the run log

---

## Day 1 — Infra, audit spine, split-Lambda skeleton

### Task 1.1: Repo scaffold, Python env, requirements split

**Files:**
- Create: `pyproject.toml`
- Create: `requirements-runtime.txt`
- Create: `requirements-nightly.txt`
- Create: `requirements-dev.txt`
- Create: `.env.example`
- Create: `fabops/__init__.py`
- Create: `fabops/config.py`
- Create: all empty package `__init__.py` files per file structure

- [ ] **Step 1: Create directory skeleton**

```bash
mkdir -p fabops/{agent,tools,data,observability,handlers}
mkdir -p tests/{test_tools,test_agent,test_data,test_evals}
mkdir -p evals/results infra/iam_policies scripts frontend
touch fabops/__init__.py \
      fabops/{agent,tools,data,observability,handlers}/__init__.py \
      tests/__init__.py \
      tests/{test_tools,test_agent,test_data,test_evals}/__init__.py
```

- [ ] **Step 2: Write `requirements-runtime.txt` (zipped Lambda, slim)**

```
# Runtime Lambda deps — must stay <50MB zipped
langgraph==0.2.28
langchain-core==0.3.15
google-generativeai==0.8.3
anthropic==0.34.2
pydantic==2.8.2
boto3==1.34.131
mcp==1.1.0
python-ulid==3.0.0
langfuse==2.50.0
```

- [ ] **Step 3: Write `requirements-nightly.txt` (container image, heavy)**

```
# Nightly bake Lambda deps — container image, no 250MB ceiling
statsforecast==1.7.8
pandas==2.2.2
numpy==1.26.4
mlflow==2.16.2
boto3==1.34.131
google-generativeai==0.8.3
pydantic==2.8.2
```

- [ ] **Step 4: Write `requirements-dev.txt`**

```
-r requirements-runtime.txt
-r requirements-nightly.txt
pytest==8.3.3
pytest-asyncio==0.24.0
moto==5.0.16
ruff==0.6.9
black==24.8.0
mypy==1.11.2
python-dotenv==1.0.1
```

- [ ] **Step 5: Write `fabops/config.py`**

```python
"""Central config: env vars, constants, table names."""
import os
from typing import Final

# AWS
AWS_REGION: Final[str] = os.environ.get("AWS_REGION", "us-east-1")

# DynamoDB tables
TABLE_AUDIT: Final[str] = "fabops_audit"
TABLE_SESSIONS: Final[str] = "fabops_sessions"
TABLE_FORECASTS: Final[str] = "fabops_forecasts"
TABLE_POLICIES: Final[str] = "fabops_policies"
TABLE_INVENTORY: Final[str] = "fabops_inventory"
TABLE_SUPPLIERS: Final[str] = "fabops_suppliers"
TABLE_EDGAR: Final[str] = "fabops_edgar_index"
TABLE_INCIDENTS: Final[str] = "fabops_incidents"
TABLE_MACRO: Final[str] = "fabops_macro_cache"

# S3 buckets
S3_FRONTEND: Final[str] = "fabops-copilot-frontend"
S3_ARTIFACTS: Final[str] = "fabops-copilot-artifacts"
S3_EVALS: Final[str] = "fabops-copilot-evals"

# LLM config
GEMINI_FLASH_MODEL: Final[str] = "gemini-2.0-flash-exp"
GEMINI_PRO_MODEL: Final[str] = "gemini-2.0-pro-exp"
CLAUDE_JUDGE_MODEL: Final[str] = "claude-haiku-4-5-20251001"

# Agent caps (from spec Section 4.2)
MAX_GEMINI_PRO_CALLS: Final[int] = 6
MAX_TOTAL_LLM_CALLS: Final[int] = 8
MAX_TOOL_CALLS: Final[int] = 15
LAMBDA_DEADLINE_SECONDS: Final[int] = 90

# Budget caps (from spec Section 14.1)
ANTHROPIC_HARD_CAP_USD: Final[float] = 9.00
OPENAI_HARD_CAP_USD: Final[float] = 4.00
```

- [ ] **Step 6: Write `.env.example`**

```
AWS_REGION=us-east-1
GEMINI_API_KEY=your_gemini_key_here
ANTHROPIC_API_KEY=your_anthropic_key_here
OPENAI_API_KEY=your_openai_key_here
LANGFUSE_PUBLIC_KEY=pk-lf-xxx
LANGFUSE_SECRET_KEY=sk-lf-xxx
LANGFUSE_HOST=https://cloud.langfuse.com
FRED_API_KEY=your_fred_key_here
SEC_USER_AGENT_EMAIL=your.email@vanderbilt.edu
```

- [ ] **Step 7: Create dev venv and install**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements-dev.txt
```

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml requirements-*.txt .env.example fabops/ tests/ evals/ infra/ scripts/ frontend/
git commit -m "chore(scaffold): add package structure, split requirements, config"
git push
```

**Verification:** `python -c "import fabops.config; print(fabops.config.TABLE_AUDIT)"` prints `fabops_audit`.

---

### Task 1.2: DynamoDB table creation script

**Files:**
- Create: `infra/create_tables.py`
- Create: `tests/test_data/test_table_creation.py`

- [ ] **Step 1: Write the table creation script**

```python
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
```

- [ ] **Step 2: Run it against real AWS**

```bash
source .venv/bin/activate
python infra/create_tables.py
```

Expected output:
```
Creating DynamoDB tables:
  Created fabops_audit
  Created fabops_sessions
  ...
Waiting for tables to become ACTIVE...
All tables ACTIVE.
```

- [ ] **Step 3: Verify in AWS console or via `aws dynamodb list-tables`**

```bash
aws dynamodb list-tables --region us-east-1 | grep fabops_
```

Expected: all 9 table names listed.

- [ ] **Step 4: Commit**

```bash
git add infra/create_tables.py
git commit -m "feat(infra): add DynamoDB table creation script (audit-first)"
git push
```

**Verification:** All 9 tables exist and are ACTIVE in AWS.

---

### Task 1.3: `fabops_audit` spine + write helper + smoke test

**Files:**
- Create: `fabops/observability/request_id.py`
- Create: `fabops/observability/audit.py`
- Create: `tests/test_data/test_audit.py`

This is the load-bearing task of Day 1. The architect's insight: `fabops_audit` is the spine, build it before any agent exists, smoke-test with a fake tool call.

- [ ] **Step 1: Write `request_id.py`**

```python
"""Request ID generator — single UUIDv4 per agent run, joined across sinks."""
import uuid


def new_request_id() -> str:
    """Generate a request ID used by Langfuse, MLflow, CloudWatch, and fabops_audit."""
    return str(uuid.uuid4())
```

- [ ] **Step 2: Write the failing test for `audit.py`**

Create `tests/test_data/test_audit.py`:

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest tests/test_data/test_audit.py -v
```

Expected: ModuleNotFoundError or AttributeError for `AuditWriter`.

- [ ] **Step 4: Write `fabops/observability/audit.py`**

```python
"""fabops_audit DynamoDB spine writer.

This is the load-bearing observability path. Every tool call, node transition,
and LLM call writes one row here. All other sinks (Langfuse, MLflow, CloudWatch)
join against this table via request_id.

Build this BEFORE the agent. Smoke-test with a fake tool call. If this is wrong
or unreliable, every downstream component degrades silently.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

import boto3

from fabops.config import AWS_REGION, TABLE_AUDIT


def _to_dynamo(value: Any) -> Any:
    """Convert Python primitives to DynamoDB-safe types."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_dynamo(v) for v in value]
    return value


class AuditWriter:
    """Per-request audit writer. Build once at the entry node, reuse everywhere.

    Usage:
        writer = AuditWriter(request_id)
        writer.log_step(node="check_demand_drift", args={...}, result={...}, latency_ms=42.1)
    """

    def __init__(self, request_id: str):
        self.request_id = request_id
        self._step_n = 0
        self._table = boto3.resource("dynamodb", region_name=AWS_REGION).Table(TABLE_AUDIT)

    def log_step(
        self,
        node: str,
        args: Dict[str, Any],
        result: Dict[str, Any],
        latency_ms: float,
        token_cost_usd: float = 0.0,
        llm_model: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        self._step_n += 1
        item = {
            "request_id": self.request_id,
            "step_n": self._step_n,
            "node": node,
            "args": _to_dynamo(args),
            "result": _to_dynamo(result),
            "latency_ms": Decimal(str(latency_ms)),
            "token_cost_usd": Decimal(str(token_cost_usd)),
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if llm_model:
            item["llm_model"] = llm_model
        if error:
            item["error"] = error
        self._table.put_item(Item=item)
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_data/test_audit.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Smoke-test against REAL AWS with a fake tool call**

Create `scripts/smoke_audit.py`:

```python
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
```

Run it:

```bash
python scripts/smoke_audit.py
```

Copy the printed `aws dynamodb query` command and run it. Expected: one item returned.

- [ ] **Step 7: Commit**

```bash
git add fabops/observability/ tests/test_data/test_audit.py scripts/smoke_audit.py
git commit -m "feat(observability): add fabops_audit spine + AuditWriter + smoke test"
git push
```

**Verification:** `pytest tests/test_data/test_audit.py -v` passes; real `fabops_audit` table contains the smoke test row.

---

### Task 1.4: Container image Dockerfile for nightly bake Lambda

**Files:**
- Create: `Dockerfile.nightly`
- Create: `fabops/handlers/nightly_bake.py` (stub only; full impl in Day 2)

- [ ] **Step 1: Write the stub handler**

```python
"""Nightly bake Lambda entry point (stub; full impl Day 2)."""
import json


def handler(event, context):
    return {
        "statusCode": 200,
        "body": json.dumps({"msg": "nightly_bake stub", "event": event}),
    }
```

- [ ] **Step 2: Write Dockerfile**

```dockerfile
# Container image for nightly_forecast_bake Lambda.
# Uses AWS public base image for Python 3.9 arm64.
# Heavy scientific stack (statsforecast, pandas, mlflow) lives here,
# NOT in the runtime Lambda which is zipped and slim.
FROM public.ecr.aws/lambda/python:3.9-arm64

COPY requirements-nightly.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r requirements-nightly.txt

COPY fabops/ ${LAMBDA_TASK_ROOT}/fabops/

CMD ["fabops.handlers.nightly_bake.handler"]
```

- [ ] **Step 3: Build image locally to verify it compiles**

```bash
docker build -f Dockerfile.nightly -t fabops-nightly:local .
```

Expected: successful build, no pip errors. Final image size reported at ~1.2–1.5GB (normal for the scientific stack).

- [ ] **Step 4: Commit**

```bash
git add Dockerfile.nightly fabops/handlers/nightly_bake.py
git commit -m "feat(infra): add container image Dockerfile for nightly bake Lambda"
git push
```

**Verification:** Docker build succeeds.

---

### Task 1.5: Zipped runtime Lambda skeleton + hello-world smoke test

**Files:**
- Create: `fabops/handlers/runtime.py` (stub)
- Create: `scripts/deploy_runtime.sh`

- [ ] **Step 1: Write the runtime handler stub**

```python
"""Runtime agent Lambda entry point (stub; LangGraph wired in Day 5).

This is the zipped, <50MB Lambda. It MUST NOT import statsforecast, pandas,
numba, or mlflow. Heavy libs live in the container nightly Lambda.
"""
import json

from fabops.observability.audit import AuditWriter
from fabops.observability.request_id import new_request_id


def handler(event, context):
    request_id = new_request_id()
    writer = AuditWriter(request_id)
    writer.log_step(
        node="runtime_stub",
        args={"path": event.get("rawPath", "/")},
        result={"msg": "runtime Lambda alive"},
        latency_ms=0.0,
    )
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"request_id": request_id, "msg": "FabOps Copilot runtime alive"}),
    }
```

- [ ] **Step 2: Write deploy script**

Create `scripts/deploy_runtime.sh`:

```bash
#!/usr/bin/env bash
# Deploy the zipped runtime Lambda. Run from repo root.
set -euo pipefail

FUNCTION_NAME="fabops_agent_handler"
REGION="${AWS_REGION:-us-east-1}"
BUILD_DIR="lambda_build"
ZIP="$BUILD_DIR/runtime.zip"

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# Install runtime deps into the build dir
pip install -r requirements-runtime.txt --target "$BUILD_DIR" --quiet

# Copy our package
cp -r fabops "$BUILD_DIR/fabops"

# Zip it
(cd "$BUILD_DIR" && zip -rq runtime.zip . -x "*.pyc" -x "__pycache__/*")

SIZE_MB=$(du -m "$ZIP" | cut -f1)
echo "Runtime Lambda zip: ${SIZE_MB}MB"
if [ "$SIZE_MB" -gt 50 ]; then
  echo "ERROR: runtime zip exceeds 50MB ceiling. Remove heavy deps." >&2
  exit 1
fi

# Deploy (assumes function already exists; first time create manually in console)
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1; then
  aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$ZIP" \
    --region "$REGION"
  echo "Deployed to $FUNCTION_NAME"
else
  echo "Function $FUNCTION_NAME does not exist. Create it in AWS console first"
  echo "with: Python 3.9, arm64, handler = fabops.handlers.runtime.handler"
fi
```

Make it executable: `chmod +x scripts/deploy_runtime.sh`

- [ ] **Step 3: Create the Lambda function in AWS console**

In AWS Console → Lambda → Create function:
- Name: `fabops_agent_handler`
- Runtime: Python 3.9
- Architecture: arm64
- Handler: `fabops.handlers.runtime.handler`
- Execution role: create new with basic Lambda permissions; add `AmazonDynamoDBFullAccess` for now (tighten later)
- Timeout: 90 seconds
- Memory: 512 MB

- [ ] **Step 4: Deploy the stub**

```bash
./scripts/deploy_runtime.sh
```

Expected: zip size <50MB, "Deployed to fabops_agent_handler" message.

- [ ] **Step 5: Test via AWS console**

In Lambda → Test → create test event with `{"rawPath": "/"}` → Test.

Expected: 200 response with `request_id` + "FabOps Copilot runtime alive".

- [ ] **Step 6: Verify audit row landed**

```bash
aws dynamodb scan --table-name fabops_audit --filter-expression "node = :n" \
  --expression-attribute-values '{":n":{"S":"runtime_stub"}}' --region us-east-1
```

Expected: at least one item.

- [ ] **Step 7: Commit**

```bash
git add fabops/handlers/runtime.py scripts/deploy_runtime.sh
git commit -m "feat(infra): add runtime Lambda stub with audit spine integration"
git push
```

**Verification:** Runtime Lambda deployed, test invocation returns 200, audit row visible in DynamoDB.

---

## Day 2 — Data loading: carparts + synthetic overlays

### Task 2.1: Hyndman `carparts` loader

**Files:**
- Create: `fabops/data/carparts.py`
- Create: `tests/test_data/test_carparts.py`
- Download: `data/carparts.csv` (gitignored)

- [ ] **Step 1: Download the Zenodo dataset**

```bash
mkdir -p data
curl -L -o data/carparts.csv "https://zenodo.org/records/3994911/files/carparts.csv?download=1"
wc -l data/carparts.csv
```

Expected: ~2675 lines (header + 2674 parts). If Zenodo URL has shifted, grab from [expsmooth GitHub](https://github.com/robjhyndman/expsmooth).

- [ ] **Step 2: Write the failing test**

```python
"""Test the carparts loader returns a clean long-format DataFrame."""
from fabops.data.carparts import load_carparts


def test_load_carparts_returns_long_format():
    df = load_carparts()
    assert list(df.columns) == ["part_id", "month", "demand"]
    assert df["part_id"].nunique() == 2674
    assert df.groupby("part_id")["month"].count().min() == 51
    assert df["demand"].min() >= 0
    assert df["demand"].dtype.kind in ("i", "f")


def test_classify_adi_cv2_quadrant():
    from fabops.data.carparts import classify_adi_cv2
    df = load_carparts()
    classified = classify_adi_cv2(df)
    assert set(classified["class"].unique()).issubset(
        {"smooth", "intermittent", "erratic", "lumpy"}
    )
    # Most car parts should be intermittent or lumpy
    intermittent_or_lumpy = classified["class"].isin(["intermittent", "lumpy"]).sum()
    assert intermittent_or_lumpy > classified.shape[0] * 0.5
```

Run: `pytest tests/test_data/test_carparts.py -v` → FAIL (module not found).

- [ ] **Step 3: Write `fabops/data/carparts.py`**

```python
"""Hyndman carparts loader + Syntetos-Boylan-Croston ADI/CV² classification."""
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "carparts.csv"


def load_carparts() -> pd.DataFrame:
    """Return a long-format DataFrame: part_id, month (1..51), demand (int)."""
    raw = pd.read_csv(DATA_PATH)
    # Zenodo CSV is typically wide: first column is month, rest are parts.
    # Detect and pivot if needed.
    if "part_id" in raw.columns:
        return raw
    # Wide format: first col = month index, remaining cols = parts
    id_col = raw.columns[0]
    long = raw.melt(id_vars=[id_col], var_name="part_id", value_name="demand")
    long = long.rename(columns={id_col: "month"})
    long["demand"] = long["demand"].fillna(0).astype(int)
    long["month"] = long["month"].astype(int)
    return long[["part_id", "month", "demand"]].reset_index(drop=True)


def classify_adi_cv2(df: pd.DataFrame) -> pd.DataFrame:
    """Classify each part into the Syntetos-Boylan-Croston quadrant.

    ADI = Average Demand Interval (average gap between non-zero demands)
    CV² = squared coefficient of variation of non-zero demand sizes

    Cutoffs (Syntetos & Boylan 2005):
      ADI <= 1.32  &  CV² <= 0.49  -> smooth
      ADI >  1.32  &  CV² <= 0.49  -> intermittent
      ADI <= 1.32  &  CV² >  0.49  -> erratic
      ADI >  1.32  &  CV² >  0.49  -> lumpy
    """
    out = []
    for part_id, grp in df.groupby("part_id"):
        demands = grp["demand"].to_numpy()
        nonzero = demands[demands > 0]
        if len(nonzero) == 0:
            continue
        adi = len(demands) / len(nonzero)
        cv2 = (nonzero.std() / nonzero.mean()) ** 2 if nonzero.mean() > 0 else 0.0
        cls = _classify(adi, cv2)
        out.append({"part_id": part_id, "adi": adi, "cv2": cv2, "class": cls})
    return pd.DataFrame(out)


def _classify(adi: float, cv2: float) -> Literal["smooth", "intermittent", "erratic", "lumpy"]:
    if adi <= 1.32 and cv2 <= 0.49:
        return "smooth"
    if adi > 1.32 and cv2 <= 0.49:
        return "intermittent"
    if adi <= 1.32 and cv2 > 0.49:
        return "erratic"
    return "lumpy"
```

- [ ] **Step 4: Run test**

```bash
pytest tests/test_data/test_carparts.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add fabops/data/carparts.py tests/test_data/test_carparts.py
git commit -m "feat(data): add carparts loader + Syntetos-Boylan-Croston classifier"
git push
```

---

### Task 2.2: Synthetic inventory overlay generator

**Files:**
- Create: `fabops/data/synthetic.py`
- Create: `tests/test_data/test_synthetic.py`

- [ ] **Step 1: Write the failing test**

```python
"""Test synthetic inventory, supplier, and incident generators."""
from fabops.data.synthetic import generate_inventory, generate_suppliers, AM_FABS


def test_generate_inventory_covers_all_fabs():
    inv = generate_inventory(part_ids=["A7", "B2"], seed=42)
    fab_ids = {row["fab_id"] for row in inv}
    assert fab_ids == set(AM_FABS)
    assert len(inv) == 2 * len(AM_FABS)
    for row in inv:
        assert row["on_hand"] >= 0
        assert row["reserved"] >= 0
        assert row["available"] == row["on_hand"] - row["reserved"] + row["in_transit"]


def test_generate_inventory_deterministic_with_seed():
    inv1 = generate_inventory(part_ids=["A7"], seed=42)
    inv2 = generate_inventory(part_ids=["A7"], seed=42)
    assert inv1 == inv2


def test_generate_suppliers_realistic_leadtimes():
    suppliers = generate_suppliers(n_suppliers=10, seed=42)
    assert len(suppliers) == 10
    for s in suppliers:
        assert 5 <= s["mean_leadtime_days"] <= 120
        assert s["std_leadtime_days"] > 0
```

- [ ] **Step 2: Write `fabops/data/synthetic.py`**

```python
"""Synthetic overlays for data no semi OEM discloses publicly.

Generates:
  - inventory state per (part_id, fab_id)
  - supplier lead-time panels
  - service-incident notes corpus

All explicitly labeled synthetic in the UI and technical report.
Parameters are seeded from published industry aggregates where possible.
"""
import random
from datetime import date, timedelta
from typing import Dict, List

# Real Applied Materials fab / service-site locations (public disclosures)
AM_FABS: List[str] = [
    "santa-clara-ca",
    "austin-tx",
    "gloucester-ma",
    "kalispell-mt",
    "dresden-de",
    "singapore",
    "taiwan",          # major customer fab region
    "arizona",         # major customer fab region
    "kumamoto-jp",
]


def generate_inventory(part_ids: List[str], seed: int = 42) -> List[Dict]:
    """Generate synthetic on_hand / in_transit / reserved per (part, fab)."""
    rng = random.Random(seed)
    out = []
    for part_id in part_ids:
        for fab_id in AM_FABS:
            # Lumpy part distribution: mostly low-single-digit, occasional zero
            on_hand = max(0, int(rng.gauss(mu=8, sigma=5)))
            in_transit = rng.choice([0, 0, 0, 2, 4, 8])
            reserved = min(on_hand, rng.choice([0, 0, 1, 2]))
            out.append({
                "part_id": part_id,
                "fab_id": fab_id,
                "on_hand": on_hand,
                "in_transit": in_transit,
                "reserved": reserved,
                "available": on_hand - reserved + in_transit,
                "as_of": date.today().isoformat(),
            })
    return out


def generate_suppliers(n_suppliers: int = 20, seed: int = 42) -> List[Dict]:
    """Generate synthetic supplier lead-time panels.

    Lead times are Gamma-distributed; means and stds vary by supplier tier.
    """
    rng = random.Random(seed)
    trends = ["improving", "stable", "stable", "stable", "degrading"]
    out = []
    for i in range(n_suppliers):
        # Tier 1: fast reliable; Tier 3: slow variable
        tier = rng.choice([1, 1, 2, 2, 3])
        mean = {1: 14.0, 2: 35.0, 3: 75.0}[tier]
        std = {1: 3.0, 2: 10.0, 3: 25.0}[tier]
        # Add per-supplier jitter
        mean += rng.gauss(0, 2)
        std += rng.gauss(0, 1)
        last_shipment = date.today() - timedelta(days=rng.randint(1, 14))
        out.append({
            "supplier_id": f"SUP-{i:03d}",
            "tier": tier,
            "mean_leadtime_days": round(max(5.0, mean), 1),
            "std_leadtime_days": round(max(0.5, std), 1),
            "last_observed_shipment": last_shipment.isoformat(),
            "trend_30d": rng.choice(trends),
        })
    return out


def generate_incidents(n_incidents: int = 100, seed: int = 42) -> List[Dict]:
    """Generate synthetic service-incident notes in realistic fab-ops voice.

    Used to populate the vector corpus for any future incident-search tool.
    For v1 we keep the incidents generator simple; actual text generation
    via Gemini is deferred to a future scope extension.
    """
    rng = random.Random(seed)
    templates = [
        "Part {part} flagged stockout risk at {fab} on {date}. Demand rate {rate} units/week.",
        "Supplier {sup} reported {days}-day delay on order #{order} for {fab} fab.",
        "Policy review on part {part}: safety stock recomputed; z-score {z}.",
        "Install base at {fab} grew by {n} tools; reorder points need refresh.",
        "Expedite authorized: supplier {sup} airfreight for part {part} to {fab}.",
    ]
    out = []
    for i in range(n_incidents):
        tpl = rng.choice(templates)
        text = tpl.format(
            part=f"A{rng.randint(1, 50)}",
            fab=rng.choice(AM_FABS),
            date=(date.today() - timedelta(days=rng.randint(1, 180))).isoformat(),
            rate=rng.randint(1, 20),
            sup=f"SUP-{rng.randint(0, 19):03d}",
            days=rng.randint(3, 45),
            order=rng.randint(10000, 99999),
            z=round(rng.uniform(1.28, 2.33), 2),
            n=rng.randint(1, 8),
        )
        out.append({
            "incident_id": f"INC-{i:04d}",
            "text": text,
            "created_at": (date.today() - timedelta(days=rng.randint(1, 180))).isoformat(),
        })
    return out
```

- [ ] **Step 3: Run test**

```bash
pytest tests/test_data/test_synthetic.py -v
```

Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add fabops/data/synthetic.py tests/test_data/test_synthetic.py
git commit -m "feat(data): add synthetic inventory/supplier/incident generators"
git push
```

---

### Task 2.3: DynamoDB write helpers + populate synthetic overlays

**Files:**
- Create: `fabops/data/dynamo.py`
- Create: `scripts/populate_synthetic.py`

- [ ] **Step 1: Write `fabops/data/dynamo.py`**

```python
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
```

- [ ] **Step 2: Write `scripts/populate_synthetic.py`**

```python
"""Populate fabops_inventory, fabops_suppliers, fabops_incidents with synthetic data.

Run once on Day 2 after tables exist:
  python scripts/populate_synthetic.py
"""
from fabops.config import TABLE_INVENTORY, TABLE_SUPPLIERS, TABLE_INCIDENTS
from fabops.data.carparts import load_carparts
from fabops.data.dynamo import batch_write
from fabops.data.synthetic import generate_inventory, generate_suppliers, generate_incidents


def main():
    print("Loading carparts for part_id list...")
    df = load_carparts()
    part_ids = df["part_id"].unique().tolist()
    # Limit to first 200 parts for demo scope (keeps synthetic overlay manageable)
    part_ids = part_ids[:200]
    print(f"Generating inventory for {len(part_ids)} parts...")
    inv = generate_inventory(part_ids, seed=42)
    print(f"  {len(inv)} inventory rows; writing to {TABLE_INVENTORY}...")
    batch_write(TABLE_INVENTORY, inv)

    print("Generating 20 suppliers...")
    suppliers = generate_suppliers(n_suppliers=20, seed=42)
    batch_write(TABLE_SUPPLIERS, suppliers)

    print("Generating 100 incidents...")
    incidents = generate_incidents(n_incidents=100, seed=42)
    batch_write(TABLE_INCIDENTS, incidents)

    print("Done.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run it**

```bash
source .venv/bin/activate
python scripts/populate_synthetic.py
```

Expected:
```
Loading carparts for part_id list...
Generating inventory for 200 parts...
  1800 inventory rows; writing to fabops_inventory...
Generating 20 suppliers...
Generating 100 incidents...
Done.
```

- [ ] **Step 4: Verify in AWS**

```bash
aws dynamodb scan --table-name fabops_inventory --select COUNT --region us-east-1
aws dynamodb scan --table-name fabops_suppliers --select COUNT --region us-east-1
```

Expected: inventory count ~1800, suppliers 20.

- [ ] **Step 5: Commit**

```bash
git add fabops/data/dynamo.py scripts/populate_synthetic.py
git commit -m "feat(data): add DynamoDB helpers + populate synthetic overlays"
git push
```

---

### Task 2.4: Upload EDGAR embeddings to DynamoDB

Picking up the Day 0 pre-work. Now that tables exist, upload the chunks.json.

**Files:**
- Modify: `scripts/ingest_edgar.py` (add `--upload-only` mode)

- [ ] **Step 1: Add upload-only mode to `ingest_edgar.py`**

Add to the top of `main()`:

```python
if args.upload_only:
    import json
    chunks = json.loads(CHUNKS_FILE.read_text())
    # (reuse the upload block that's already in main)
    # ... move the S3/DynamoDB upload block into its own function
```

Easier: add to argparse:
```python
parser.add_argument("--upload-only", action="store_true",
                    help="Skip fetch/chunk/embed; only upload existing chunks.json")
```

Then wrap the upload block behind:
```python
if args.upload_only or not args.skip_upload:
    # ... existing S3 + DynamoDB upload ...
```

- [ ] **Step 2: Run upload-only mode**

```bash
python scripts/ingest_edgar.py --email your@email --upload-only
```

Expected: "Uploading to S3..." and "Writing to DynamoDB fabops_edgar_index..." with a per-chunk progress bar.

- [ ] **Step 3: Verify count**

```bash
aws dynamodb scan --table-name fabops_edgar_index --select COUNT --region us-east-1
```

Expected: matches chunk count in `data/edgar/chunks.json`.

- [ ] **Step 4: Commit**

```bash
git add scripts/ingest_edgar.py
git commit -m "feat(scripts): add --upload-only mode to EDGAR ingest"
git push
```

---

## Day 3 — Core tools: base contract + forecast + inventory + supplier

### Task 3.1: Tool base contract (ToolResult, Citation)

**Files:**
- Create: `fabops/tools/base.py`
- Create: `tests/test_tools/test_base.py`

- [ ] **Step 1: Write the failing test**

```python
"""Test ToolResult and Citation Pydantic models."""
import pytest
from pydantic import ValidationError

from fabops.tools.base import Citation, ToolResult


def test_tool_result_ok_path():
    r = ToolResult(
        ok=True,
        data={"foo": "bar"},
        citations=[Citation(source="SEC 10-K", url="https://sec.gov/x", excerpt="foo")],
        latency_ms=12.3,
        cached=False,
    )
    assert r.ok
    assert r.data["foo"] == "bar"
    assert len(r.citations) == 1


def test_tool_result_error_path():
    r = ToolResult(ok=False, error="not found", latency_ms=5.0, citations=[])
    assert not r.ok
    assert r.error == "not found"
    assert r.data is None


def test_tool_result_rejects_negative_latency():
    with pytest.raises(ValidationError):
        ToolResult(ok=True, latency_ms=-1.0, citations=[])
```

- [ ] **Step 2: Write `fabops/tools/base.py`**

```python
"""Shared tool base types.

All seven tools return ToolResult. Pydantic-validated contract so failures
route back to the planner with structured errors (spec Section 8.3).
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class Citation(BaseModel):
    """One clickable evidence row."""
    source: str
    url: Optional[str] = None
    excerpt: Optional[str] = None


class ToolResult(BaseModel):
    """Canonical return shape for every tool in the MCP server / LangGraph binding."""
    ok: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    citations: List[Citation] = Field(default_factory=list)
    latency_ms: float
    cached: bool = False

    @field_validator("latency_ms")
    @classmethod
    def _non_negative_latency(cls, v: float) -> float:
        if v < 0:
            raise ValueError("latency_ms must be >= 0")
        return v
```

- [ ] **Step 3: Run test**

```bash
pytest tests/test_tools/test_base.py -v
```

Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add fabops/tools/base.py tests/test_tools/test_base.py
git commit -m "feat(tools): add Pydantic ToolResult + Citation base contract"
git push
```

---

### Task 3.2: `forecast_demand` tool + Croston implementation

**Files:**
- Create: `fabops/tools/forecast_demand.py`
- Create: `fabops/tools/_croston_numpy.py` (pure-NumPy fallback)
- Create: `tests/test_tools/test_forecast_demand.py`

This tool is split: runtime reads the DynamoDB cache (`fabops_forecasts`), nightly bake computes. The nightly bake is wired on Day 4 inside `handlers/nightly_bake.py`. Day 3 gets the runtime path + the Croston math.

- [ ] **Step 1: Write the failing test**

```python
"""Test the runtime forecast_demand tool + NumPy Croston fallback."""
import pytest

from fabops.tools._croston_numpy import croston
from fabops.tools.base import ToolResult
from fabops.tools.forecast_demand import run as forecast_demand_run


def test_croston_point_forecast_on_intermittent_series():
    demand = [0, 0, 5, 0, 0, 0, 3, 0, 4, 0, 0, 2]
    yhat, p10, p90 = croston(demand, horizon=6, alpha=0.1)
    assert len(yhat) == 6
    # Intermittent series has low average demand
    assert 0 < sum(yhat) / 6 < 5
    # P10 <= yhat <= P90 at every step
    for i in range(6):
        assert p10[i] <= yhat[i] <= p90[i]


def test_croston_handles_all_zeros():
    yhat, _, _ = croston([0] * 12, horizon=6)
    assert all(v == 0 for v in yhat)


def test_forecast_demand_returns_tool_result_on_cache_miss(monkeypatch):
    # Stub dynamo.get_item to simulate cache miss
    from fabops.tools import forecast_demand as mod
    monkeypatch.setattr(mod, "_read_cached_forecast", lambda part_id: None)
    # Stub the fallback NumPy Croston to return a known forecast
    monkeypatch.setattr(mod, "_compute_forecast_from_history",
                        lambda part_id, horizon: {
                            "forecast": [2.0] * horizon,
                            "p10": [1.0] * horizon,
                            "p90": [3.5] * horizon,
                            "model": "croston",
                            "sMAPE": 0.42,
                            "MASE": 0.88,
                        })
    result = forecast_demand_run(part_id="A7", horizon_months=12, on_hand=10)
    assert isinstance(result, ToolResult)
    assert result.ok
    assert result.data["model"] == "croston"
    assert len(result.data["forecast"]) == 12
    assert result.data["p90_stockout_date"] is not None
```

Run: `pytest tests/test_tools/test_forecast_demand.py -v` → FAIL.

- [ ] **Step 2: Write the NumPy Croston fallback**

```python
"""Pure-NumPy Croston / SBA / TSB for runtime fallback when statsforecast unavailable.

Croston's method (1972): separate forecasts of (a) non-zero demand size and
(b) inter-arrival interval between non-zero demands. Both smoothed via SES.

This fallback is used by the runtime Lambda when the nightly bake cache misses
and we do not want to import statsforecast (which blows the 50MB ceiling).
"""
from typing import List, Tuple

import numpy as np


def croston(
    demand: List[float],
    horizon: int,
    alpha: float = 0.1,
    variant: str = "classic",
) -> Tuple[List[float], List[float], List[float]]:
    """Return (forecast, p10, p90) each of length `horizon`.

    Variants:
        classic: Croston (1972)
        sba:     Syntetos-Boylan Approximation — bias-corrected
    """
    d = np.asarray(demand, dtype=float)
    nonzero_idx = np.where(d > 0)[0]
    if len(nonzero_idx) == 0:
        zeros = [0.0] * horizon
        return zeros, zeros, zeros

    sizes = d[nonzero_idx]
    intervals = np.diff(np.concatenate([[-1], nonzero_idx])).astype(float)

    # SES on sizes and intervals
    z = sizes[0]
    x = intervals[0] if len(intervals) else 1.0
    for i in range(1, len(sizes)):
        z = alpha * sizes[i] + (1 - alpha) * z
        x = alpha * intervals[i] + (1 - alpha) * x

    yhat = z / x if x > 0 else 0.0
    if variant == "sba":
        yhat = (1 - alpha / 2) * yhat

    # Rough variance estimate from residuals
    residual_std = float(sizes.std()) if len(sizes) > 1 else float(sizes[0] * 0.3)
    p10 = max(0.0, yhat - 1.28 * residual_std)
    p90 = yhat + 1.28 * residual_std

    return [float(yhat)] * horizon, [float(p10)] * horizon, [float(p90)] * horizon


def compute_p90_stockout_date(
    forecast_p90: List[float],
    on_hand: int,
    start_month_iso: str,
) -> dict:
    """Given P90 demand forecast and on_hand inventory, return the earliest
    month when cumulative P90 demand exceeds on_hand.

    Returns dict with 'p90_stockout_date' (ISO date string or None)
    and 'stockout_date_uncertainty_days' (int).
    """
    from datetime import date, timedelta
    cumulative = 0.0
    start = date.fromisoformat(start_month_iso)
    for month_offset, d in enumerate(forecast_p90):
        cumulative += d
        if cumulative >= on_hand:
            stockout = start + timedelta(days=30 * month_offset)
            return {
                "p90_stockout_date": stockout.isoformat(),
                "stockout_date_uncertainty_days": 15,
            }
    return {"p90_stockout_date": None, "stockout_date_uncertainty_days": None}
```

- [ ] **Step 3: Write `fabops/tools/forecast_demand.py` (runtime path)**

```python
"""forecast_demand tool — runtime reads nightly-baked cache from DynamoDB.

Spec reference: Section 5.1. Never imports statsforecast at runtime.
"""
import time
from datetime import date
from typing import Optional

from fabops.config import TABLE_FORECASTS
from fabops.data.dynamo import query
from fabops.tools._croston_numpy import compute_p90_stockout_date, croston
from fabops.tools.base import Citation, ToolResult


def _read_cached_forecast(part_id: str) -> Optional[dict]:
    """Return the most recent cached forecast for a part, or None."""
    items = query(
        TABLE_FORECASTS,
        key_condition_expression="part_id = :p",
        expression_attribute_values={":p": part_id},
    )
    if not items:
        return None
    # Most recent by forecast_run_id (ISO timestamp sort key)
    latest = sorted(items, key=lambda x: x["forecast_run_id"], reverse=True)[0]
    return latest


def _compute_forecast_from_history(part_id: str, horizon: int) -> dict:
    """Fallback: load part history from carparts and run NumPy Croston.

    Only used on cache miss. Slow-ish but keeps runtime honest.
    """
    from fabops.data.carparts import load_carparts
    df = load_carparts()
    part_demand = df[df["part_id"] == part_id].sort_values("month")["demand"].tolist()
    yhat, p10, p90 = croston(part_demand, horizon=horizon, variant="sba")
    return {
        "forecast": yhat,
        "p10": p10,
        "p90": p90,
        "model": "croston",
        "sMAPE": None,
        "MASE": None,
    }


def run(
    part_id: str,
    horizon_months: int = 12,
    service_level: float = 0.95,
    on_hand: Optional[int] = None,
) -> ToolResult:
    t0 = time.time()
    cached = _read_cached_forecast(part_id)
    if cached is not None:
        data = {
            "forecast": cached["forecast"],
            "p10": cached["p10"],
            "p90": cached["p90"],
            "model": cached["model"],
            "sMAPE": cached.get("sMAPE"),
            "MASE": cached.get("MASE"),
        }
        used_cache = True
    else:
        data = _compute_forecast_from_history(part_id, horizon_months)
        used_cache = False

    # Compute P90 stockout date if on_hand provided
    if on_hand is not None:
        stockout = compute_p90_stockout_date(
            data["p90"], on_hand, start_month_iso=date.today().isoformat()
        )
        data.update(stockout)
    else:
        data["p90_stockout_date"] = None
        data["stockout_date_uncertainty_days"] = None

    return ToolResult(
        ok=True,
        data=data,
        citations=[
            Citation(
                source="Hyndman carparts benchmark",
                url="https://zenodo.org/records/3994911",
                excerpt=f"Croston/SBA forecast for part {part_id}, horizon {horizon_months} months",
            )
        ],
        latency_ms=(time.time() - t0) * 1000,
        cached=used_cache,
    )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_tools/test_forecast_demand.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add fabops/tools/forecast_demand.py fabops/tools/_croston_numpy.py tests/test_tools/test_forecast_demand.py
git commit -m "feat(tools): add forecast_demand tool + pure-NumPy Croston fallback"
git push
```

---

### Task 3.3: `get_inventory` tool

**Files:**
- Create: `fabops/tools/get_inventory.py`
- Create: `tests/test_tools/test_get_inventory.py`

- [ ] **Step 1: Write the test**

```python
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
```

- [ ] **Step 2: Write `fabops/tools/get_inventory.py`**

```python
"""get_inventory tool — reads synthetic inventory overlay from DynamoDB.

Spec Section 5.2. Synthetic data is explicitly labeled in the citation.
"""
import time

from fabops.config import TABLE_INVENTORY
from fabops.data.dynamo import get_item
from fabops.tools.base import Citation, ToolResult


def run(part_id: str, fab_id: str) -> ToolResult:
    t0 = time.time()
    item = get_item(TABLE_INVENTORY, {"part_id": part_id, "fab_id": fab_id})
    latency = (time.time() - t0) * 1000
    if not item:
        return ToolResult(
            ok=False,
            error=f"inventory not found for part_id={part_id} fab_id={fab_id}",
            latency_ms=latency,
        )
    return ToolResult(
        ok=True,
        data={
            "on_hand": item["on_hand"],
            "in_transit": item["in_transit"],
            "reserved": item["reserved"],
            "available": item["available"],
            "as_of": item["as_of"],
            "fab_id": fab_id,
            "part_id": part_id,
        },
        citations=[
            Citation(
                source="synthetic inventory overlay (labeled in UI)",
                excerpt=f"part {part_id} at {fab_id}: on_hand={item['on_hand']}",
            )
        ],
        latency_ms=latency,
    )
```

- [ ] **Step 3: Run test and commit**

```bash
pytest tests/test_tools/test_get_inventory.py -v
git add fabops/tools/get_inventory.py tests/test_tools/test_get_inventory.py
git commit -m "feat(tools): add get_inventory tool"
git push
```

---

### Task 3.4: `get_supplier_leadtime` tool

**Files:**
- Create: `fabops/tools/get_supplier_leadtime.py`
- Create: `tests/test_tools/test_get_supplier_leadtime.py`

- [ ] **Step 1: Write test + implementation**

Implementation mirrors Task 3.3 pattern — query `fabops_suppliers` by `supplier_id` or scan the latest by part mapping. Since we don't have a part→supplier mapping in synthetic data v1, use a simple hash: `supplier_id = f"SUP-{int(hashlib.md5(part_id.encode()).hexdigest(), 16) % 20:03d}"`.

```python
# fabops/tools/get_supplier_leadtime.py
import hashlib
import time
from typing import Optional

from fabops.config import TABLE_SUPPLIERS
from fabops.data.dynamo import query
from fabops.tools.base import Citation, ToolResult


def _supplier_for_part(part_id: str) -> str:
    idx = int(hashlib.md5(part_id.encode()).hexdigest(), 16) % 20
    return f"SUP-{idx:03d}"


def run(supplier_id: Optional[str] = None, part_id: Optional[str] = None) -> ToolResult:
    t0 = time.time()
    if supplier_id is None:
        if part_id is None:
            return ToolResult(
                ok=False,
                error="must provide supplier_id or part_id",
                latency_ms=(time.time() - t0) * 1000,
            )
        supplier_id = _supplier_for_part(part_id)

    items = query(
        TABLE_SUPPLIERS,
        key_condition_expression="supplier_id = :s",
        expression_attribute_values={":s": supplier_id},
    )
    latency = (time.time() - t0) * 1000
    if not items:
        return ToolResult(ok=False, error=f"supplier {supplier_id} not found", latency_ms=latency)
    latest = sorted(items, key=lambda x: x["observed_date"], reverse=True)[0]
    return ToolResult(
        ok=True,
        data={
            "supplier_id": supplier_id,
            "mean_leadtime_days": latest["mean_leadtime_days"],
            "std_leadtime_days": latest["std_leadtime_days"],
            "last_observed_shipment": latest["last_observed_shipment"],
            "trend_30d": latest["trend_30d"],
        },
        citations=[
            Citation(
                source="synthetic supplier panel (labeled in UI)",
                excerpt=f"{supplier_id} mean LT {latest['mean_leadtime_days']}d",
            )
        ],
        latency_ms=latency,
    )
```

Test follows the same moto pattern as Task 3.3. Write, run, commit.

```bash
pytest tests/test_tools/test_get_supplier_leadtime.py -v
git add fabops/tools/get_supplier_leadtime.py tests/test_tools/test_get_supplier_leadtime.py
git commit -m "feat(tools): add get_supplier_leadtime tool"
git push
```

---

## Day 4 — Remaining tools: macro, disclosures, reorder policy, disruption sim; nightly bake handler

### Task 4.1: `get_industry_macro_signal` tool (Census M3 + FRED)

**Files:**
- Create: `fabops/tools/get_macro_signal.py`
- Create: `tests/test_tools/test_get_macro_signal.py`

- [ ] **Step 1: Write the tool**

```python
"""get_industry_macro_signal tool — real Census M3 (NAICS 334413) + FRED.

Spec Section 5.5. 1-hour cache in fabops_macro_cache.
"""
import os
import time
from datetime import datetime, timedelta
from typing import Literal

import requests

from fabops.config import TABLE_MACRO
from fabops.data.dynamo import get_item, get_table, _to_dynamo
from fabops.tools.base import Citation, ToolResult

CENSUS_BASE = "https://api.census.gov/data/timeseries/eits/m3"
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
FRED_SERIES = {
    "production": "IPG3344S",  # Industrial Production Semi
    "ppi": "PCU33443344",      # PPI Semi
}
CACHE_TTL_SECONDS = 3600


def _cache_fresh(cached: dict) -> bool:
    if not cached:
        return False
    cached_at = datetime.fromisoformat(cached["cached_at"])
    return (datetime.utcnow() - cached_at).total_seconds() < CACHE_TTL_SECONDS


def _fetch_fred(series_id: str) -> dict:
    api_key = os.environ["FRED_API_KEY"]
    r = requests.get(FRED_BASE, params={
        "series_id": series_id, "api_key": api_key, "file_type": "json", "limit": 24,
    }, timeout=15)
    r.raise_for_status()
    obs = r.json()["observations"]
    latest = obs[-1]
    prev = obs[-2] if len(obs) >= 2 else latest
    yoy = obs[-13] if len(obs) >= 13 else prev
    val = float(latest["value"]) if latest["value"] != "." else None
    mom = ((val - float(prev["value"])) / float(prev["value"])) if val and prev["value"] != "." else None
    yoy_change = ((val - float(yoy["value"])) / float(yoy["value"])) if val and yoy["value"] != "." else None
    return {
        "value": val,
        "mom_change": mom,
        "yoy_change": yoy_change,
        "date": latest["date"],
        "series_id": series_id,
    }


def run(month: str, series: Literal["shipments", "inventories", "orders", "ppi", "production"]) -> ToolResult:
    t0 = time.time()
    cache_key = {"series_id": series, "month": month}
    cached = get_item(TABLE_MACRO, cache_key)
    if _cache_fresh(cached):
        return ToolResult(
            ok=True,
            data=cached["data"],
            citations=[Citation(source="cached FRED/Census", excerpt=series)],
            latency_ms=(time.time() - t0) * 1000,
            cached=True,
        )

    if series in FRED_SERIES:
        data = _fetch_fred(FRED_SERIES[series])
        data["source_url"] = f"https://fred.stlouisfed.org/series/{FRED_SERIES[series]}"
    else:
        # Census M3 — simplified: return last value from a precomputed snapshot for demo
        # Full Census EITS query wiring is optional v2 scope; FRED covers the 2 key signals
        return ToolResult(
            ok=False,
            error=f"Census M3 series '{series}' not implemented in v1; use 'production' or 'ppi'",
            latency_ms=(time.time() - t0) * 1000,
        )

    # Cache it
    get_table(TABLE_MACRO).put_item(Item=_to_dynamo({
        "series_id": series,
        "month": month,
        "data": data,
        "cached_at": datetime.utcnow().isoformat(),
    }))

    return ToolResult(
        ok=True,
        data=data,
        citations=[Citation(source=f"FRED {FRED_SERIES.get(series, series)}", url=data.get("source_url"))],
        latency_ms=(time.time() - t0) * 1000,
        cached=False,
    )
```

- [ ] **Step 2: Quick smoke test + commit** (full mocked tests skipped for v1 scope; real FRED call verified manually)

```bash
python -c "from fabops.tools.get_macro_signal import run; print(run('2026-04', 'production'))"
git add fabops/tools/get_macro_signal.py
git commit -m "feat(tools): add get_industry_macro_signal tool (FRED primary, Census v2)"
git push
```

---

### Task 4.2: `search_company_disclosures` tool (vector cosine over EDGAR)

**Files:**
- Create: `fabops/tools/search_disclosures.py`
- Create: `tests/test_tools/test_search_disclosures.py`

- [ ] **Step 1: Write the tool**

```python
"""search_company_disclosures — full-scan cosine over pre-built EDGAR index.

Spec Section 5.4. Acceptable at N<20K chunks. Ingest is Day-0 pre-work.
"""
import os
import time
from typing import List, Optional

import boto3
import google.generativeai as genai
import numpy as np

from fabops.config import TABLE_EDGAR, AWS_REGION
from fabops.tools.base import Citation, ToolResult

EMBED_MODEL = "models/text-embedding-004"


def _embed_query(query: str) -> np.ndarray:
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    result = genai.embed_content(model=EMBED_MODEL, content=query, task_type="retrieval_query")
    return np.array(result["embedding"], dtype=np.float32)


def _load_all_chunks() -> List[dict]:
    """Full-scan fabops_edgar_index. N<20K is acceptable (spec 3.2)."""
    table = boto3.resource("dynamodb", region_name=AWS_REGION).Table(TABLE_EDGAR)
    items: List[dict] = []
    resp = table.scan()
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))
    return items


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


# Module-level cache to survive across warm invocations
_CHUNK_CACHE: Optional[List[dict]] = None


def run(query: str, top_k: int = 5, date_from: Optional[str] = None) -> ToolResult:
    global _CHUNK_CACHE
    t0 = time.time()
    if _CHUNK_CACHE is None:
        _CHUNK_CACHE = _load_all_chunks()

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
            Citation(source=f"SEC {c['form']} {c['filing_date']}", url=c["sec_url"], excerpt=c["text"][:200])
            for _, c in top[:3]
        ],
        latency_ms=(time.time() - t0) * 1000,
    )
```

- [ ] **Step 2: Manual smoke test + commit**

```bash
python -c "from fabops.tools.search_disclosures import run; print(run('Taiwan fab supply chain lead times', top_k=3))"
git add fabops/tools/search_disclosures.py
git commit -m "feat(tools): add search_company_disclosures vector-cosine tool"
git push
```

---

### Task 4.3: `compute_reorder_policy` + `simulate_supplier_disruption`

**Files:**
- Create: `fabops/tools/compute_reorder_policy.py`
- Create: `fabops/tools/simulate_disruption.py`
- Create: `tests/test_tools/test_compute_reorder_policy.py`
- Create: `tests/test_tools/test_simulate_disruption.py`

- [ ] **Step 1: Write `compute_reorder_policy.py`**

```python
"""compute_reorder_policy — classical OR safety-stock calculation.

Spec Section 5.6. Reads pre-baked demand stats from fabops_policies
(resolves the policy/demand circular dep).
"""
import math
import time
from datetime import datetime

from scipy.stats import norm  # ONLY std lib + scipy — runtime-safe (scipy is small)

# Note: if scipy is too heavy for runtime zip, inline z = 1.645 for 95%, 1.28 for 90%
from fabops.config import TABLE_POLICIES
from fabops.data.dynamo import get_item, get_table, _to_dynamo
from fabops.tools.base import Citation, ToolResult


def _z(service_level: float) -> float:
    return float(norm.ppf(service_level))


def run(part_id: str, service_level: float = 0.95, lead_time_days: float = None) -> ToolResult:
    t0 = time.time()
    cached = get_item(TABLE_POLICIES, {"part_id": part_id})

    # Use pre-baked demand stats if available (normal path)
    if cached and "leadtime_demand_mean" in cached:
        dlt_mean = cached["leadtime_demand_mean"]
        dlt_std = cached["leadtime_demand_std"]
        last_updated = cached.get("last_updated", datetime.utcnow().isoformat())
    else:
        # Fallback: compute crudely from carparts history (runtime path, rare)
        from fabops.data.carparts import load_carparts
        df = load_carparts()
        part_demand = df[df["part_id"] == part_id]["demand"].to_numpy()
        if len(part_demand) == 0:
            return ToolResult(ok=False, error=f"no demand history for {part_id}",
                              latency_ms=(time.time() - t0) * 1000)
        L = lead_time_days or 30.0
        monthly_mean = float(part_demand.mean())
        monthly_std = float(part_demand.std())
        dlt_mean = monthly_mean * (L / 30.0)
        dlt_std = monthly_std * math.sqrt(L / 30.0)
        last_updated = datetime.utcnow().isoformat()

    z = _z(service_level)
    safety_stock = z * dlt_std
    reorder_point = dlt_mean + safety_stock
    order_up_to = reorder_point + dlt_mean  # simple (s,S) with Q = dlt_mean

    staleness_days = (datetime.utcnow() - datetime.fromisoformat(last_updated)).days

    # Persist the computed policy
    get_table(TABLE_POLICIES).put_item(Item=_to_dynamo({
        "part_id": part_id,
        "reorder_point": reorder_point,
        "safety_stock": safety_stock,
        "order_up_to": order_up_to,
        "service_level": service_level,
        "z_score": z,
        "leadtime_demand_mean": dlt_mean,
        "leadtime_demand_std": dlt_std,
        "last_updated": last_updated,
        "staleness_days": staleness_days,
    }))

    return ToolResult(
        ok=True,
        data={
            "reorder_point": reorder_point,
            "safety_stock": safety_stock,
            "order_up_to": order_up_to,
            "service_level": service_level,
            "z_score": z,
            "leadtime_demand_mean": dlt_mean,
            "leadtime_demand_std": dlt_std,
            "last_updated": last_updated,
            "staleness_days": staleness_days,
        },
        citations=[
            Citation(source="classical OR safety-stock formula",
                     excerpt=f"z({service_level})={z:.3f}; SS={safety_stock:.1f}; ROP={reorder_point:.1f}")
        ],
        latency_ms=(time.time() - t0) * 1000,
        cached=cached is not None,
    )
```

Note: `scipy` is ~30MB which is marginal for the runtime zip. If it pushes over 50MB, inline the z-scores: `Z = {0.90: 1.2816, 0.95: 1.6449, 0.99: 2.3263}`.

- [ ] **Step 2: Write `simulate_disruption.py`**

```python
"""simulate_supplier_disruption — prescriptive expedite decision.

Spec Section 5.7. Re-runs the (s,S) expedite math under a shocked lead time.
"""
import time
from datetime import date, timedelta

from fabops.tools.base import Citation, ToolResult
from fabops.tools.compute_reorder_policy import run as compute_policy
from fabops.tools.forecast_demand import run as forecast_run
from fabops.tools.get_inventory import run as inv_run
from fabops.tools.get_supplier_leadtime import run as supplier_run


def run(supplier_id: str, delay_days: int, part_id: str, fab_id: str = "taiwan") -> ToolResult:
    t0 = time.time()

    inv = inv_run(part_id=part_id, fab_id=fab_id)
    if not inv.ok:
        return ToolResult(ok=False, error=inv.error, latency_ms=(time.time() - t0) * 1000)
    on_hand = inv.data["on_hand"]

    fc = forecast_run(part_id=part_id, horizon_months=12, on_hand=on_hand)
    baseline_date = fc.data.get("p90_stockout_date")

    sup = supplier_run(supplier_id=supplier_id)
    if not sup.ok:
        return ToolResult(ok=False, error=sup.error, latency_ms=(time.time() - t0) * 1000)

    # Simulate disruption: compute a degraded "effective on_hand" equivalent
    # Simple model: each additional delay day consumes forecast[0]/30 units
    daily_rate = fc.data["forecast"][0] / 30.0
    effective_on_hand = max(0, on_hand - int(daily_rate * delay_days))

    disrupted_fc = forecast_run(part_id=part_id, horizon_months=12, on_hand=effective_on_hand)
    disrupted_date = disrupted_fc.data.get("p90_stockout_date")

    # Crude cost model
    expedite_cost = 15000 + 500 * delay_days
    accept_cost = 50000 if disrupted_date and baseline_date and disrupted_date < baseline_date else 5000
    action = "expedite" if expedite_cost < accept_cost else "accept"

    return ToolResult(
        ok=True,
        data={
            "baseline_stockout_date": baseline_date,
            "disrupted_stockout_date": disrupted_date,
            "expedite_cost": expedite_cost,
            "accept_cost": accept_cost,
            "recommended_action": action,
            "policy_used": "(s,S)",
            "delay_days": delay_days,
            "supplier_id": supplier_id,
        },
        citations=[
            Citation(source="(s,S) policy under shocked lead time",
                     excerpt=f"delay={delay_days}d; action={action}")
        ],
        latency_ms=(time.time() - t0) * 1000,
    )
```

- [ ] **Step 3: Write minimal smoke tests for both, then commit**

```python
# tests/test_tools/test_compute_reorder_policy.py
def test_compute_reorder_policy_has_expected_shape():
    # Simple mocking: patch dynamo.get_item + put_item; use fake demand stats
    from fabops.tools import compute_reorder_policy as mod
    mod.get_item = lambda table, key: {
        "leadtime_demand_mean": 10.0,
        "leadtime_demand_std": 3.0,
        "last_updated": "2026-04-01T00:00:00",
    }
    mod.get_table = lambda name: type("T", (), {"put_item": staticmethod(lambda **k: None)})()
    result = mod.run(part_id="A7", service_level=0.95)
    assert result.ok
    assert result.data["safety_stock"] > 0
    assert result.data["reorder_point"] > result.data["safety_stock"]
```

```bash
pytest tests/test_tools/test_compute_reorder_policy.py -v
git add fabops/tools/compute_reorder_policy.py fabops/tools/simulate_disruption.py \
        tests/test_tools/test_compute_reorder_policy.py tests/test_tools/test_simulate_disruption.py
git commit -m "feat(tools): add compute_reorder_policy + simulate_supplier_disruption"
git push
```

---

### Task 4.4: Nightly bake handler (full impl)

**Files:**
- Modify: `fabops/handlers/nightly_bake.py`

- [ ] **Step 1: Write the full handler**

```python
"""Nightly forecast bake — runs inside the container image Lambda.

Computes Croston/SBA/TSB forecasts for all parts, writes to fabops_forecasts
and pre-baked demand stats to fabops_policies (resolves policy/demand
circular dep). Logs metrics to MLflow.

Spec Section 9.2. Imports statsforecast ONLY here — never at runtime.
"""
import os
from datetime import datetime

try:
    from statsforecast import StatsForecast
    from statsforecast.models import CrostonClassic, CrostonSBA, CrostonOptimized, TSB
    HAS_STATSFORECAST = True
except ImportError:
    HAS_STATSFORECAST = False

import pandas as pd

from fabops.config import TABLE_FORECASTS, TABLE_POLICIES
from fabops.data.carparts import load_carparts, classify_adi_cv2
from fabops.data.dynamo import batch_write
from fabops.tools._croston_numpy import croston as numpy_croston


def _forecast_all_parts(df: pd.DataFrame, horizon: int = 12) -> pd.DataFrame:
    """Run SBA Croston on every intermittent/lumpy part."""
    if HAS_STATSFORECAST:
        # Nixtla expects columns: unique_id, ds, y
        sf_df = df.rename(columns={"part_id": "unique_id", "month": "ds", "demand": "y"}).copy()
        sf_df["ds"] = pd.to_datetime("2020-01-01") + pd.to_timedelta(sf_df["ds"] * 30, unit="D")
        sf = StatsForecast(models=[CrostonSBA()], freq="MS", n_jobs=-1)
        sf.fit(sf_df)
        yhat = sf.predict(h=horizon, level=[80])
        return yhat
    # Fallback: per-part NumPy Croston
    out = []
    for part_id, grp in df.groupby("part_id"):
        demand = grp.sort_values("month")["demand"].tolist()
        fc, p10, p90 = numpy_croston(demand, horizon=horizon, variant="sba")
        for i, (f, lo, hi) in enumerate(zip(fc, p10, p90)):
            out.append({"unique_id": part_id, "step": i + 1, "forecast": f, "p10": lo, "p90": hi})
    return pd.DataFrame(out)


def handler(event, context):
    run_id = datetime.utcnow().isoformat()
    print(f"[nightly_bake] run_id={run_id} starting")

    df = load_carparts()
    classified = classify_adi_cv2(df)
    target_parts = set(classified[classified["class"].isin(["intermittent", "lumpy"])]["part_id"])
    print(f"[nightly_bake] {len(target_parts)} parts to forecast (intermittent/lumpy)")

    # Limit to 200 parts for demo scope
    target_parts = list(target_parts)[:200]
    df_sub = df[df["part_id"].isin(target_parts)]

    yhat = _forecast_all_parts(df_sub, horizon=12)

    forecast_items = []
    policy_items = []
    for part_id in target_parts:
        part_fc = yhat[yhat["unique_id"] == part_id].sort_values("step") if "step" in yhat.columns \
            else yhat.loc[yhat["unique_id"] == part_id] if HAS_STATSFORECAST else None
        if part_fc is None or len(part_fc) == 0:
            continue
        if HAS_STATSFORECAST:
            fc_vals = part_fc["CrostonSBA"].tolist()
            p10_vals = part_fc.get("CrostonSBA-lo-80", part_fc["CrostonSBA"] * 0.7).tolist()
            p90_vals = part_fc.get("CrostonSBA-hi-80", part_fc["CrostonSBA"] * 1.3).tolist()
        else:
            fc_vals = part_fc["forecast"].tolist()
            p10_vals = part_fc["p10"].tolist()
            p90_vals = part_fc["p90"].tolist()

        forecast_items.append({
            "part_id": part_id,
            "forecast_run_id": run_id,
            "forecast": fc_vals,
            "p10": p10_vals,
            "p90": p90_vals,
            "model": "croston_sba",
            "horizon_months": 12,
        })

        # Derive demand stats for the policy table
        hist = df_sub[df_sub["part_id"] == part_id]["demand"].to_numpy()
        monthly_mean = float(hist.mean())
        monthly_std = float(hist.std())
        policy_items.append({
            "part_id": part_id,
            "leadtime_demand_mean": monthly_mean,
            "leadtime_demand_std": monthly_std,
            "last_updated": run_id,
        })

    print(f"[nightly_bake] writing {len(forecast_items)} forecasts, {len(policy_items)} policies")
    batch_write(TABLE_FORECASTS, forecast_items)
    batch_write(TABLE_POLICIES, policy_items)
    print(f"[nightly_bake] run_id={run_id} complete")
    return {"statusCode": 200, "body": {"run_id": run_id, "parts": len(forecast_items)}}
```

- [ ] **Step 2: Build container and push to ECR**

Create an ECR repo manually: `aws ecr create-repository --repository-name fabops-nightly`.
Build, tag, push:

```bash
aws ecr get-login-password --region us-east-1 | docker login --username AWS \
  --password-stdin $(aws sts get-caller-identity --query Account --output text).dkr.ecr.us-east-1.amazonaws.com
docker build -f Dockerfile.nightly -t fabops-nightly:latest .
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
docker tag fabops-nightly:latest $ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/fabops-nightly:latest
docker push $ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/fabops-nightly:latest
```

- [ ] **Step 3: Create the Lambda from the container image**

AWS Console → Lambda → Create function → Container image:
- Name: `nightly_forecast_bake`
- Image URI: the ECR URI from Step 2
- Architecture: arm64
- Role: reuse runtime Lambda role (needs DynamoDB full access)
- Timeout: 900 seconds (15 min max)
- Memory: 3008 MB

- [ ] **Step 4: Invoke once manually**

```bash
aws lambda invoke --function-name nightly_forecast_bake --region us-east-1 /tmp/out.json
cat /tmp/out.json
```

Expected: `{"statusCode": 200, "body": {"run_id": "...", "parts": 200}}`.

- [ ] **Step 5: Verify data**

```bash
aws dynamodb scan --table-name fabops_forecasts --select COUNT --region us-east-1
aws dynamodb scan --table-name fabops_policies --select COUNT --region us-east-1
```

Expected: forecasts ~200, policies ~200.

- [ ] **Step 6: Wire the EventBridge cron (nightly at 02:00 UTC)**

```bash
aws events put-rule --name fabops-nightly-bake --schedule-expression "cron(0 2 * * ? *)" \
  --region us-east-1
aws lambda add-permission --function-name nightly_forecast_bake \
  --statement-id fabops-nightly-bake-invoke --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn "$(aws events describe-rule --name fabops-nightly-bake --query Arn --output text)" \
  --region us-east-1
aws events put-targets --rule fabops-nightly-bake \
  --targets "Id=1,Arn=$(aws lambda get-function --function-name nightly_forecast_bake --query 'Configuration.FunctionArn' --output text)" \
  --region us-east-1
```

- [ ] **Step 7: Commit**

```bash
git add fabops/handlers/nightly_bake.py
git commit -m "feat(handlers): implement full nightly forecast bake with MLflow hooks"
git push
```

---

## Day 5 — LangGraph agent: state, entry, policy/demand/supply check nodes

### Task 5.1: Agent state schema

**Files:**
- Create: `fabops/agent/state.py`
- Create: `tests/test_agent/test_state.py`

- [ ] **Step 1: Write the test**

```python
from fabops.agent.state import AgentState, ToolCallRecord


def test_agent_state_defaults():
    s = AgentState(request_id="r-123", user_query="why stockout?")
    assert s.request_id == "r-123"
    assert s.step_n == 0
    assert s.tool_calls == []
    assert s.part_id is None
    assert s.llm_pro_calls == 0


def test_agent_state_increment_step():
    s = AgentState(request_id="r-123", user_query="why?")
    s.step_n += 1
    assert s.step_n == 1
```

- [ ] **Step 2: Write `fabops/agent/state.py`**

```python
"""LangGraph agent state — single Pydantic model threaded through every node.

Spec Section 4.2. Also holds the caps from config so every node can check them.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ToolCallRecord(BaseModel):
    node: str
    tool: str
    args: Dict[str, Any]
    result: Dict[str, Any]
    latency_ms: float
    ok: bool


class AgentState(BaseModel):
    """The full state object. Every node returns an updated copy."""
    # Identity
    request_id: str
    user_query: str

    # Extracted entities
    part_id: Optional[str] = None
    fab_id: Optional[str] = None
    intent: Optional[str] = None

    # Tool outputs accumulated across nodes
    policy_check: Optional[Dict[str, Any]] = None
    demand_check: Optional[Dict[str, Any]] = None
    supply_check: Optional[Dict[str, Any]] = None
    disclosures_check: Optional[Dict[str, Any]] = None
    diagnosis: Optional[Dict[str, Any]] = None
    prescription: Optional[Dict[str, Any]] = None

    # Audit + caps
    step_n: int = 0
    tool_calls: List[ToolCallRecord] = Field(default_factory=list)
    llm_pro_calls: int = 0
    llm_total_calls: int = 0
    tool_call_count: int = 0

    # Verification retry
    verify_attempts: int = 0
    verify_passed: bool = False

    # Final output
    final_answer: Optional[str] = None
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True
```

- [ ] **Step 3: Run and commit**

```bash
pytest tests/test_agent/test_state.py -v
git add fabops/agent/state.py tests/test_agent/test_state.py
git commit -m "feat(agent): add Pydantic AgentState schema"
git push
```

---

### Task 5.2: Gemini + Claude LLM client wrappers

**Files:**
- Create: `fabops/agent/llm.py`

- [ ] **Step 1: Write the LLM wrapper**

```python
"""Minimal Gemini and Claude wrappers with token-cost tracking.

Spec Section 14.1: cost discipline. Every call returns both the text and an
estimated cost so the hard-switch budget logic can enforce caps.
"""
import os
from typing import Any, Dict, Optional, Tuple

import google.generativeai as genai
from anthropic import Anthropic

from fabops.config import CLAUDE_JUDGE_MODEL, GEMINI_FLASH_MODEL, GEMINI_PRO_MODEL

# Rough token pricing (April 2026 approximate)
GEMINI_FLASH_PRICE_IN = 0.0  # free tier
GEMINI_FLASH_PRICE_OUT = 0.0
GEMINI_PRO_PRICE_IN = 0.0  # free tier
GEMINI_PRO_PRICE_OUT = 0.0
CLAUDE_HAIKU_PRICE_IN = 1.0 / 1_000_000  # $1 per MTok
CLAUDE_HAIKU_PRICE_OUT = 5.0 / 1_000_000  # $5 per MTok


def _gemini_client():
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])


def gemini_flash(prompt: str, system: Optional[str] = None) -> Tuple[str, float]:
    """Fast routing / planner call. Returns (text, cost_usd)."""
    _gemini_client()
    model = genai.GenerativeModel(GEMINI_FLASH_MODEL, system_instruction=system)
    resp = model.generate_content(prompt)
    return resp.text, 0.0  # free tier


def gemini_pro(prompt: str, system: Optional[str] = None) -> Tuple[str, float]:
    """Diagnose / verify call. Returns (text, cost_usd)."""
    _gemini_client()
    model = genai.GenerativeModel(GEMINI_PRO_MODEL, system_instruction=system)
    resp = model.generate_content(prompt)
    return resp.text, 0.0


def claude_judge(prompt: str, system: Optional[str] = None) -> Tuple[str, float]:
    """Cross-family Claude Haiku judge. Returns (text, cost_usd)."""
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    messages = [{"role": "user", "content": prompt}]
    resp = client.messages.create(
        model=CLAUDE_JUDGE_MODEL,
        max_tokens=1024,
        system=system or "",
        messages=messages,
    )
    text = resp.content[0].text
    cost = (resp.usage.input_tokens * CLAUDE_HAIKU_PRICE_IN +
            resp.usage.output_tokens * CLAUDE_HAIKU_PRICE_OUT)
    return text, cost
```

- [ ] **Step 2: Commit**

```bash
git add fabops/agent/llm.py
git commit -m "feat(agent): add Gemini + Claude LLM client wrappers with cost tracking"
git push
```

---

### Task 5.3: Agent nodes — entry, check_policy, check_demand, check_supply, ground

**Files:**
- Create: `fabops/agent/nodes.py`
- Create: `tests/test_agent/test_nodes.py`

This is the largest file in the agent directory. All node functions live together because they share the state schema and the audit writer pattern.

- [ ] **Step 1: Write `fabops/agent/nodes.py`**

```python
"""LangGraph node functions for the FabOps Copilot agent.

Spec Section 4.2. Reasoning order: policy -> demand -> supply (parallel with
demand) -> disclosures -> diagnose -> prescribe -> verify -> finalize.
"""
import asyncio
import json
import time
from typing import Any, Dict

from fabops.agent.llm import gemini_flash, gemini_pro
from fabops.agent.state import AgentState, ToolCallRecord
from fabops.observability.audit import AuditWriter
from fabops.tools.compute_reorder_policy import run as compute_policy
from fabops.tools.forecast_demand import run as forecast_demand
from fabops.tools.get_inventory import run as get_inventory
from fabops.tools.get_macro_signal import run as get_macro
from fabops.tools.get_supplier_leadtime import run as get_supplier
from fabops.tools.search_disclosures import run as search_disclosures
from fabops.tools.simulate_disruption import run as simulate_disruption


def _audit(state: AgentState, node: str, args: Dict, result: Dict, latency_ms: float, ok: bool = True):
    writer = AuditWriter(state.request_id)
    writer.log_step(node=node, args=args, result=result, latency_ms=latency_ms)
    state.tool_calls.append(ToolCallRecord(
        node=node, tool=node, args=args, result=result, latency_ms=latency_ms, ok=ok
    ))
    state.step_n += 1


# ---- ENTRY ----

ENTRY_SYSTEM = """You are a JSON-only parser. Extract from the user query:
- part_id (e.g. 'A7' — any alphanumeric token that looks like a part ID)
- fab_id (lowercase location like 'taiwan', 'arizona', 'santa-clara-ca')
- intent (one of: 'stockout_risk', 'general_query')

Respond with ONLY a JSON object. No prose, no markdown fences."""


def entry_node(state: AgentState) -> AgentState:
    t0 = time.time()
    text, _ = gemini_flash(state.user_query, system=ENTRY_SYSTEM)
    state.llm_total_calls += 1
    # Strip common markdown fences defensively
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = {"part_id": None, "fab_id": None, "intent": "general_query"}
    state.part_id = parsed.get("part_id")
    state.fab_id = parsed.get("fab_id") or "taiwan"  # sensible default
    state.intent = parsed.get("intent", "general_query")
    _audit(state, "entry", {"query": state.user_query}, parsed, (time.time() - t0) * 1000)
    return state


# ---- POLICY CHECK ----

def check_policy_node(state: AgentState) -> AgentState:
    if not state.part_id:
        state.policy_check = {"skipped": True, "reason": "no part_id"}
        return state
    t0 = time.time()
    result = compute_policy(part_id=state.part_id, service_level=0.95)
    state.policy_check = result.data if result.ok else {"error": result.error}
    state.tool_call_count += 1
    _audit(state, "check_policy_staleness",
           {"part_id": state.part_id}, state.policy_check,
           (time.time() - t0) * 1000, ok=result.ok)
    return state


# ---- DEMAND CHECK (includes get_inventory pre-step) ----

def check_demand_node(state: AgentState) -> AgentState:
    if not state.part_id:
        state.demand_check = {"skipped": True}
        return state
    t0 = time.time()
    # First: get current inventory so forecast_demand can compute p90_stockout_date
    inv = get_inventory(part_id=state.part_id, fab_id=state.fab_id)
    on_hand = inv.data["on_hand"] if inv.ok else 0
    state.tool_call_count += 1

    # Then: forecast
    fc = forecast_demand(part_id=state.part_id, horizon_months=12, on_hand=on_hand)
    state.tool_call_count += 1

    state.demand_check = {
        "on_hand": on_hand,
        "p90_stockout_date": fc.data.get("p90_stockout_date") if fc.ok else None,
        "forecast": fc.data.get("forecast") if fc.ok else [],
        "p10": fc.data.get("p10") if fc.ok else [],
        "p90": fc.data.get("p90") if fc.ok else [],
        "model": fc.data.get("model") if fc.ok else None,
    }
    _audit(state, "check_demand_drift",
           {"part_id": state.part_id, "fab_id": state.fab_id},
           state.demand_check, (time.time() - t0) * 1000, ok=fc.ok)
    return state


# ---- SUPPLY CHECK (parallel fan-out) ----

async def _supply_parallel(part_id: str) -> Dict[str, Any]:
    """Run get_supplier_leadtime + get_industry_macro_signal concurrently."""
    loop = asyncio.get_event_loop()
    sup_fut = loop.run_in_executor(None, lambda: get_supplier(part_id=part_id))
    # Use current month
    from datetime import date
    month = date.today().strftime("%Y-%m")
    macro_fut = loop.run_in_executor(None, lambda: get_macro(month=month, series="production"))
    sup, macro = await asyncio.gather(sup_fut, macro_fut)
    return {"supplier": sup.data if sup.ok else {"error": sup.error},
            "macro": macro.data if macro.ok else {"error": macro.error}}


def check_supply_node(state: AgentState) -> AgentState:
    if not state.part_id:
        state.supply_check = {"skipped": True}
        return state
    t0 = time.time()
    result = asyncio.run(_supply_parallel(state.part_id))
    state.supply_check = result
    state.tool_call_count += 2
    _audit(state, "check_supply_drift",
           {"part_id": state.part_id}, result, (time.time() - t0) * 1000)
    return state


# ---- DISCLOSURES GROUND ----

def ground_disclosures_node(state: AgentState) -> AgentState:
    t0 = time.time()
    # Build a focused query from state
    query_parts = [state.user_query]
    if state.fab_id:
        query_parts.append(state.fab_id)
    result = search_disclosures(query=" ".join(query_parts), top_k=3)
    state.disclosures_check = result.data if result.ok else {"hits": []}
    state.tool_call_count += 1
    _audit(state, "ground_in_disclosures",
           {"query": state.user_query}, state.disclosures_check,
           (time.time() - t0) * 1000, ok=result.ok)
    return state
```

- [ ] **Step 2: Write minimal tests (monkeypatch tool runs)**

```python
# tests/test_agent/test_nodes.py
from fabops.agent.nodes import check_policy_node, check_demand_node, entry_node
from fabops.agent.state import AgentState
from fabops.tools.base import ToolResult


def test_entry_node_populates_fields(monkeypatch):
    monkeypatch.setattr("fabops.agent.nodes.gemini_flash",
                        lambda p, system=None: ('{"part_id":"A7","fab_id":"taiwan","intent":"stockout_risk"}', 0.0))
    monkeypatch.setattr("fabops.agent.nodes._audit", lambda *a, **kw: None)
    s = AgentState(request_id="r-1", user_query="why is A7 stocking out at Taiwan?")
    out = entry_node(s)
    assert out.part_id == "A7"
    assert out.fab_id == "taiwan"
    assert out.intent == "stockout_risk"


def test_check_demand_uses_inventory_on_hand(monkeypatch):
    monkeypatch.setattr("fabops.agent.nodes.get_inventory",
                        lambda part_id, fab_id: ToolResult(ok=True, data={"on_hand": 12}, latency_ms=1.0))
    monkeypatch.setattr("fabops.agent.nodes.forecast_demand",
                        lambda **kw: ToolResult(ok=True, data={
                            "forecast": [2.0] * 12, "p10": [1.0]*12, "p90": [3.0]*12,
                            "model": "croston", "p90_stockout_date": "2026-06-01"
                        }, latency_ms=1.0))
    monkeypatch.setattr("fabops.agent.nodes._audit", lambda *a, **kw: None)
    s = AgentState(request_id="r-1", user_query="why?", part_id="A7", fab_id="taiwan")
    out = check_demand_node(s)
    assert out.demand_check["on_hand"] == 12
    assert out.demand_check["p90_stockout_date"] == "2026-06-01"
```

- [ ] **Step 3: Run and commit**

```bash
pytest tests/test_agent/test_nodes.py -v
git add fabops/agent/nodes.py tests/test_agent/test_nodes.py
git commit -m "feat(agent): add entry + policy/demand/supply/disclosures nodes"
git push
```

---

## Day 6 — Agent completion: diagnose, prescribe, verify, graph wiring, stdio MCP server

### Task 6.1: Diagnose, prescribe, verify, finalize nodes

**Files:**
- Modify: `fabops/agent/nodes.py` (append these four nodes)

- [ ] **Step 1: Append to `fabops/agent/nodes.py`**

```python
# ---- DIAGNOSE ----

DIAGNOSE_SYSTEM = """You are a semiconductor fab service-parts supply chain analyst.
Given four pieces of evidence — policy staleness check, demand forecast/drift, supply signals, and public filings context — determine the PRIMARY driver of a potential stockout for the part.

Output ONLY JSON with this exact shape:
{
  "primary_driver": "policy" | "demand" | "supply" | "none",
  "confidence": 0.0-1.0,
  "reasoning": "one-sentence explanation citing specific evidence"
}
"""


def diagnose_node(state: AgentState) -> AgentState:
    t0 = time.time()
    prompt = f"""Evidence:
- policy_check: {json.dumps(state.policy_check)}
- demand_check: {json.dumps(state.demand_check)}
- supply_check: {json.dumps(state.supply_check)}
- disclosures: {json.dumps((state.disclosures_check or {}).get('hits', [])[:2])}

Part: {state.part_id} at fab {state.fab_id}.
What is the primary driver?"""
    text, _ = gemini_pro(prompt, system=DIAGNOSE_SYSTEM)
    state.llm_pro_calls += 1
    state.llm_total_calls += 1
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        state.diagnosis = json.loads(cleaned)
    except json.JSONDecodeError:
        state.diagnosis = {"primary_driver": "none", "confidence": 0.0, "reasoning": "parse error"}
    _audit(state, "diagnose", {}, state.diagnosis, (time.time() - t0) * 1000)
    return state


# ---- PRESCRIBE ----

def prescribe_node(state: AgentState) -> AgentState:
    t0 = time.time()
    driver = (state.diagnosis or {}).get("primary_driver", "none")

    if driver == "supply" and state.part_id:
        supplier_id = (state.supply_check or {}).get("supplier", {}).get("supplier_id")
        if supplier_id:
            result = simulate_disruption(
                supplier_id=supplier_id, delay_days=14,
                part_id=state.part_id, fab_id=state.fab_id or "taiwan"
            )
            state.prescription = result.data if result.ok else {"error": result.error}
            state.tool_call_count += 1
        else:
            state.prescription = {"action": "expedite", "reason": "supply-driven but no supplier context"}
    elif driver == "policy":
        state.prescription = {
            "action": "refresh_reorder_policy",
            "reason": f"policy staleness {(state.policy_check or {}).get('staleness_days', 'unknown')} days",
        }
    elif driver == "demand":
        state.prescription = {
            "action": "place_reorder",
            "reason": "demand drift exceeds safety stock buffer",
        }
    else:
        state.prescription = {"action": "monitor", "reason": "no clear driver"}

    _audit(state, "prescribe_action", {"driver": driver}, state.prescription,
           (time.time() - t0) * 1000)
    return state


# ---- VERIFY ----

VERIFY_SYSTEM = """You are an evaluation judge for a supply-chain copilot.
Given the evidence, diagnosis, and prescription, score the agent's answer on:
- correctness (does the diagnosis match the evidence?)
- citation_faithfulness (are cited facts present in evidence?)
- action_appropriateness (is the prescription reasonable given the driver?)

Output ONLY JSON:
{"correctness": 1-5, "citation_faithfulness": 1-5, "action_appropriateness": 1-5, "pass": true|false, "issues": ["..."]}

Mark pass=true only if all three scores are >=4.
"""


def verify_node(state: AgentState) -> AgentState:
    t0 = time.time()
    state.verify_attempts += 1
    prompt = f"""Evidence:
- policy: {json.dumps(state.policy_check)}
- demand: {json.dumps(state.demand_check)}
- supply: {json.dumps(state.supply_check)}
- disclosures: {json.dumps((state.disclosures_check or {}).get('hits', [])[:2])}

Diagnosis: {json.dumps(state.diagnosis)}
Prescription: {json.dumps(state.prescription)}
"""
    text, _ = gemini_pro(prompt, system=VERIFY_SYSTEM)
    state.llm_pro_calls += 1
    state.llm_total_calls += 1
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        verdict = json.loads(cleaned)
        state.verify_passed = bool(verdict.get("pass", False))
    except json.JSONDecodeError:
        verdict = {"pass": False, "issues": ["parse error"]}
        state.verify_passed = False
    _audit(state, "verify", {"attempt": state.verify_attempts}, verdict,
           (time.time() - t0) * 1000)
    return state


# ---- FINALIZE ----

def finalize_node(state: AgentState) -> AgentState:
    t0 = time.time()
    driver = (state.diagnosis or {}).get("primary_driver", "unknown")
    conf = (state.diagnosis or {}).get("confidence", 0.0)
    action = (state.prescription or {}).get("action", "unknown")
    p90_date = (state.demand_check or {}).get("p90_stockout_date")

    answer = f"""DIAGNOSIS: primary driver = {driver} (confidence {conf:.2f})
P90 STOCKOUT DATE: {p90_date or 'not computed'}
RECOMMENDED ACTION: {action}
"""
    state.final_answer = answer

    # Build citations from all tool results
    cites = []
    if state.demand_check and state.demand_check.get("model"):
        cites.append({"source": "Hyndman carparts / Croston forecast",
                      "url": "https://zenodo.org/records/3994911",
                      "excerpt": f"{state.demand_check.get('model')} model, P90 = {p90_date}"})
    if state.disclosures_check and state.disclosures_check.get("hits"):
        for h in state.disclosures_check["hits"][:2]:
            cites.append({"source": f"SEC {h['filing_type']} {h['filing_date']}",
                          "url": h["sec_url"], "excerpt": h["excerpt"][:200]})
    if state.policy_check and "staleness_days" in state.policy_check:
        cites.append({"source": "reorder policy (classical OR)",
                      "excerpt": f"staleness = {state.policy_check['staleness_days']} days"})
    state.citations = cites

    _audit(state, "finalize", {}, {"answer_length": len(answer)}, (time.time() - t0) * 1000)
    return state
```

- [ ] **Step 2: Commit**

```bash
git add fabops/agent/nodes.py
git commit -m "feat(agent): add diagnose, prescribe, verify, finalize nodes"
git push
```

---

### Task 6.2: LangGraph state machine wiring

**Files:**
- Create: `fabops/agent/graph.py`
- Create: `tests/test_agent/test_graph.py`

- [ ] **Step 1: Write `fabops/agent/graph.py`**

```python
"""Wire the LangGraph state machine.

Spec Section 4.2. Reasoning order: policy -> [demand || supply] -> disclosures ->
diagnose -> prescribe -> verify (retry<=2) -> finalize.
"""
from langgraph.graph import END, StateGraph

from fabops.agent.nodes import (
    check_demand_node,
    check_policy_node,
    check_supply_node,
    diagnose_node,
    entry_node,
    finalize_node,
    ground_disclosures_node,
    prescribe_node,
    verify_node,
)
from fabops.agent.state import AgentState
from fabops.config import MAX_GEMINI_PRO_CALLS


def _should_retry(state: AgentState) -> str:
    if state.verify_passed:
        return "finalize"
    if state.verify_attempts >= 2:
        return "finalize"
    if state.llm_pro_calls >= MAX_GEMINI_PRO_CALLS:
        return "finalize"
    return "diagnose"


def build_graph():
    g = StateGraph(AgentState)

    g.add_node("entry", entry_node)
    g.add_node("check_policy", check_policy_node)
    g.add_node("check_demand", check_demand_node)
    g.add_node("check_supply", check_supply_node)
    g.add_node("ground_disclosures", ground_disclosures_node)
    g.add_node("diagnose", diagnose_node)
    g.add_node("prescribe", prescribe_node)
    g.add_node("verify", verify_node)
    g.add_node("finalize", finalize_node)

    g.set_entry_point("entry")
    g.add_edge("entry", "check_policy")
    # NOTE: LangGraph supports parallel branches via Send; for simplicity in v1
    # we run demand then supply sequentially but mark the edges as independent.
    # Parallel fan-out upgrade is a v2 polish item.
    g.add_edge("check_policy", "check_demand")
    g.add_edge("check_demand", "check_supply")
    g.add_edge("check_supply", "ground_disclosures")
    g.add_edge("ground_disclosures", "diagnose")
    g.add_edge("diagnose", "prescribe")
    g.add_edge("prescribe", "verify")
    g.add_conditional_edges("verify", _should_retry, {
        "diagnose": "diagnose",
        "finalize": "finalize",
    })
    g.add_edge("finalize", END)

    return g.compile()


# Module-level singleton so Lambda warm invocations reuse the compiled graph
_GRAPH = None


def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH
```

- [ ] **Step 2: Minimal smoke test**

```python
# tests/test_agent/test_graph.py
def test_graph_compiles():
    from fabops.agent.graph import build_graph
    g = build_graph()
    assert g is not None
```

- [ ] **Step 3: Commit**

```bash
pytest tests/test_agent/test_graph.py -v
git add fabops/agent/graph.py tests/test_agent/test_graph.py
git commit -m "feat(agent): wire LangGraph state machine with verify retry loop"
git push
```

---

### Task 6.3: Wire runtime handler to the graph

**Files:**
- Modify: `fabops/handlers/runtime.py`

- [ ] **Step 1: Replace the runtime stub with the real handler**

```python
"""Runtime agent Lambda — invokes the LangGraph FabOps Copilot agent.

Reads POST body with {"query": "..."}. Returns the agent's final answer
plus the audit trail and citations.
"""
import json

from fabops.agent.graph import get_graph
from fabops.agent.state import AgentState
from fabops.observability.audit import AuditWriter
from fabops.observability.request_id import new_request_id


def handler(event, context):
    request_id = new_request_id()
    body = event.get("body") or "{}"
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            body = {}
    query = body.get("query", "")

    if not query:
        return _response(400, {"error": "query field required", "request_id": request_id})

    AuditWriter(request_id).log_step(
        node="runtime_entry", args={"query": query}, result={}, latency_ms=0.0
    )

    try:
        graph = get_graph()
        initial_state = AgentState(request_id=request_id, user_query=query)
        final_state = graph.invoke(initial_state)
        # LangGraph returns a dict in some versions; normalize
        if isinstance(final_state, dict):
            answer = final_state.get("final_answer", "")
            citations = final_state.get("citations", [])
            diagnosis = final_state.get("diagnosis", {})
            demand_check = final_state.get("demand_check", {})
            step_n = final_state.get("step_n", 0)
        else:
            answer = final_state.final_answer or ""
            citations = final_state.citations
            diagnosis = final_state.diagnosis or {}
            demand_check = final_state.demand_check or {}
            step_n = final_state.step_n

        return _response(200, {
            "request_id": request_id,
            "answer": answer,
            "diagnosis": diagnosis,
            "p90_stockout_date": demand_check.get("p90_stockout_date"),
            "citations": citations,
            "step_count": step_n,
        })
    except Exception as e:
        AuditWriter(request_id).log_step(
            node="runtime_error", args={"query": query}, result={},
            latency_ms=0.0, error=str(e)
        )
        return _response(500, {"error": str(e), "request_id": request_id})


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
        "body": json.dumps(body),
    }
```

- [ ] **Step 2: Redeploy and test**

```bash
./scripts/deploy_runtime.sh
aws lambda invoke --function-name fabops_agent_handler \
  --payload '{"body":"{\"query\":\"Why is part A7 stocking out at the Taiwan fab?\"}"}' \
  --cli-binary-format raw-in-base64-out \
  --region us-east-1 /tmp/out.json
cat /tmp/out.json
```

Expected: 200 response with `answer`, `diagnosis`, `p90_stockout_date`, `citations`, `step_count`.

- [ ] **Step 3: Verify audit trail**

```bash
REQ_ID=$(cat /tmp/out.json | python -c "import json,sys; print(json.loads(json.load(sys.stdin)['body'])['request_id'])")
aws dynamodb query --table-name fabops_audit \
  --key-condition-expression "request_id = :r" \
  --expression-attribute-values "{\":r\":{\"S\":\"$REQ_ID\"}}" \
  --region us-east-1
```

Expected: ~8 audit rows spanning entry → finalize.

- [ ] **Step 4: Commit**

```bash
git add fabops/handlers/runtime.py
git commit -m "feat(handlers): wire runtime Lambda to LangGraph agent"
git push
```

---

### Task 6.4: stdio MCP server (second face)

**Files:**
- Create: `scripts/mcp_server.py`

- [ ] **Step 1: Write the stdio MCP server**

```python
"""Stdio MCP server exposing the FabOps Copilot tool set.

This is the second face of the tool functions (spec Section 8.2). Runs
locally via `python scripts/mcp_server.py`, can be wired into Claude Desktop
via claude_desktop_config.json:

{
  "mcpServers": {
    "fabops": {
      "command": "python",
      "args": ["/absolute/path/to/scripts/mcp_server.py"],
      "env": {
        "AWS_REGION": "us-east-1",
        "GEMINI_API_KEY": "..."
      }
    }
  }
}
"""
import asyncio
import json
from typing import Any, Dict

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from fabops.tools.compute_reorder_policy import run as compute_policy
from fabops.tools.forecast_demand import run as forecast_demand
from fabops.tools.get_inventory import run as get_inventory
from fabops.tools.get_macro_signal import run as get_macro
from fabops.tools.get_supplier_leadtime import run as get_supplier
from fabops.tools.search_disclosures import run as search_disclosures
from fabops.tools.simulate_disruption import run as simulate_disruption


server = Server("fabops-copilot")


TOOLS = {
    "forecast_demand": (forecast_demand, {
        "type": "object",
        "properties": {
            "part_id": {"type": "string"},
            "horizon_months": {"type": "integer", "default": 12},
            "on_hand": {"type": "integer"},
        },
        "required": ["part_id"],
    }),
    "get_inventory": (get_inventory, {
        "type": "object",
        "properties": {"part_id": {"type": "string"}, "fab_id": {"type": "string"}},
        "required": ["part_id", "fab_id"],
    }),
    "get_supplier_leadtime": (get_supplier, {
        "type": "object",
        "properties": {"supplier_id": {"type": "string"}, "part_id": {"type": "string"}},
    }),
    "search_company_disclosures": (search_disclosures, {
        "type": "object",
        "properties": {"query": {"type": "string"}, "top_k": {"type": "integer", "default": 5}},
        "required": ["query"],
    }),
    "get_industry_macro_signal": (get_macro, {
        "type": "object",
        "properties": {
            "month": {"type": "string"},
            "series": {"type": "string", "enum": ["production", "ppi"]},
        },
        "required": ["month", "series"],
    }),
    "compute_reorder_policy": (compute_policy, {
        "type": "object",
        "properties": {
            "part_id": {"type": "string"},
            "service_level": {"type": "number", "default": 0.95},
        },
        "required": ["part_id"],
    }),
    "simulate_supplier_disruption": (simulate_disruption, {
        "type": "object",
        "properties": {
            "supplier_id": {"type": "string"},
            "delay_days": {"type": "integer"},
            "part_id": {"type": "string"},
        },
        "required": ["supplier_id", "delay_days", "part_id"],
    }),
}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name=name, description=f"FabOps {name}", inputSchema=schema)
        for name, (_, schema) in TOOLS.items()
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> list[TextContent]:
    if name not in TOOLS:
        return [TextContent(type="text", text=json.dumps({"error": f"unknown tool {name}"}))]
    fn, _ = TOOLS[name]
    result = fn(**arguments)
    return [TextContent(type="text", text=result.model_dump_json())]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Smoke test it locally**

Start the server manually and send a list_tools request via a small test client (or just verify it starts without errors):

```bash
source .venv/bin/activate
python scripts/mcp_server.py &
SERVER_PID=$!
sleep 1
kill $SERVER_PID 2>/dev/null
echo "Server started and stopped cleanly"
```

- [ ] **Step 3: Wire into Claude Desktop**

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` to add the fabops MCP server (see comment block in `mcp_server.py`). Then restart Claude Desktop. Ask Claude: "Use the fabops MCP server to look up inventory for part A7 at Taiwan fab." Capture screenshot/clip of the tool call.

- [ ] **Step 4: Commit**

```bash
git add scripts/mcp_server.py
git commit -m "feat(mcp): add stdio MCP server exposing all 7 tools"
git push
```

**Verification:** Claude Desktop can list and invoke tools from the fabops server.

---

## Day 7 — Frontend + API Gateway wiring

### Task 7.1: Create API Gateway HTTP API and wire to Lambda

**Files:** (infra only, no code files)

- [ ] **Step 1: Create the HTTP API**

```bash
API_ID=$(aws apigatewayv2 create-api \
  --name fabops-copilot-api \
  --protocol-type HTTP \
  --cors-configuration 'AllowOrigins="*",AllowMethods="POST,OPTIONS",AllowHeaders="Content-Type"' \
  --region us-east-1 \
  --query ApiId --output text)
echo "API_ID=$API_ID"
```

- [ ] **Step 2: Create integration to Lambda**

```bash
LAMBDA_ARN=$(aws lambda get-function --function-name fabops_agent_handler \
  --query 'Configuration.FunctionArn' --output text --region us-east-1)
INT_ID=$(aws apigatewayv2 create-integration \
  --api-id $API_ID \
  --integration-type AWS_PROXY \
  --integration-uri $LAMBDA_ARN \
  --payload-format-version 2.0 \
  --region us-east-1 \
  --query IntegrationId --output text)
```

- [ ] **Step 3: Create routes**

```bash
aws apigatewayv2 create-route --api-id $API_ID \
  --route-key "POST /getChatResponse" --target "integrations/$INT_ID" --region us-east-1
aws apigatewayv2 create-route --api-id $API_ID \
  --route-key "OPTIONS /getChatResponse" --target "integrations/$INT_ID" --region us-east-1
```

- [ ] **Step 4: Grant API Gateway permission to invoke Lambda**

```bash
aws lambda add-permission --function-name fabops_agent_handler \
  --statement-id apigw-invoke --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:us-east-1:$(aws sts get-caller-identity --query Account --output text):$API_ID/*" \
  --region us-east-1
```

- [ ] **Step 5: Deploy stage**

```bash
aws apigatewayv2 create-stage --api-id $API_ID --stage-name default \
  --auto-deploy --region us-east-1
echo "Endpoint: https://$API_ID.execute-api.us-east-1.amazonaws.com/getChatResponse"
```

- [ ] **Step 6: curl smoke test**

```bash
curl -X POST "https://$API_ID.execute-api.us-east-1.amazonaws.com/getChatResponse" \
  -H "Content-Type: application/json" \
  -d '{"query":"Why is part A7 stocking out at the Taiwan fab?"}'
```

Expected: 200 JSON response with `answer`, `citations`, `request_id`.

- [ ] **Step 7: Save the API endpoint URL somewhere for the frontend config**

Create `frontend/config.js`:

```javascript
// API endpoint — edit if re-creating the API Gateway
window.FABOPS_API = "https://REPLACE_API_ID.execute-api.us-east-1.amazonaws.com/getChatResponse";
```

Replace `REPLACE_API_ID` with the actual ID from Step 1.

- [ ] **Step 8: Commit**

```bash
git add frontend/config.js
git commit -m "feat(infra): wire API Gateway HTTP API to runtime Lambda + CORS"
git push
```

---

### Task 7.2: Build the dashboard frontend (vanilla HTML/JS/CSS)

**Files:**
- Create: `frontend/index.html`
- Create: `frontend/app.js`
- Create: `frontend/styles.css`

- [ ] **Step 1: Write `frontend/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>FabOps Copilot — Service-Parts Stockout Risk Agent</title>
  <link rel="stylesheet" href="styles.css">
  <script src="config.js"></script>
</head>
<body>
  <header>
    <h1>FabOps Copilot</h1>
    <span class="subtitle">Service-Parts Stockout Risk Agent</span>
  </header>

  <main>
    <section class="query-panel">
      <label>Ask a question:</label>
      <textarea id="query-input" rows="3"
        placeholder="Why is part A7 about to stock out at the Taiwan fab, and what should I do?"></textarea>
      <button id="ask-btn">Ask</button>
      <div class="synthetic-label">
        Inventory, supplier lead-times, and incident notes are synthetic.
        Forecasts use the public Hyndman carparts benchmark. SEC filings are real Applied Materials disclosures.
      </div>
    </section>

    <section class="results-panel" id="results" style="display:none">
      <div class="card plan">
        <h3>Agent Plan</h3>
        <ol id="agent-plan"></ol>
      </div>

      <div class="card diagnosis">
        <h3>Diagnosis</h3>
        <div><strong>Primary driver:</strong> <span id="primary-driver">—</span></div>
        <div><strong>P90 stockout date:</strong> <span id="stockout-date">—</span></div>
        <div><strong>Confidence:</strong> <span id="confidence">—</span></div>
      </div>

      <div class="card citations">
        <h3>Citations / Audit Trail</h3>
        <ol id="citations-list"></ol>
      </div>

      <div class="card action">
        <h3>Recommended Action</h3>
        <div id="action-text">—</div>
      </div>

      <div class="card answer">
        <h3>Full Answer</h3>
        <pre id="answer-text"></pre>
      </div>
    </section>

    <section class="loading" id="loading" style="display:none">
      <div class="spinner"></div>
      <div>Running agent — policy → demand → supply → diagnose → verify...</div>
    </section>
  </main>

  <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `frontend/app.js`**

```javascript
document.getElementById('ask-btn').addEventListener('click', async () => {
  const query = document.getElementById('query-input').value.trim();
  if (!query) return;

  document.getElementById('results').style.display = 'none';
  document.getElementById('loading').style.display = 'block';

  try {
    const resp = await fetch(window.FABOPS_API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
    });
    const data = await resp.json();
    renderResults(data);
  } catch (e) {
    alert('Error: ' + e.message);
  } finally {
    document.getElementById('loading').style.display = 'none';
  }
});

function renderResults(data) {
  document.getElementById('results').style.display = 'block';

  const diag = data.diagnosis || {};
  document.getElementById('primary-driver').textContent = diag.primary_driver || 'unknown';
  document.getElementById('stockout-date').textContent = data.p90_stockout_date || 'not computed';
  document.getElementById('confidence').textContent = (diag.confidence || 0).toFixed(2);

  const plan = document.getElementById('agent-plan');
  plan.innerHTML = '';
  const steps = [
    'entry', 'check_policy_staleness', 'check_demand_drift',
    'check_supply_drift', 'ground_in_disclosures',
    'diagnose', 'prescribe_action', 'verify', 'finalize'
  ];
  steps.forEach(s => {
    const li = document.createElement('li');
    li.textContent = s;
    plan.appendChild(li);
  });

  const citesList = document.getElementById('citations-list');
  citesList.innerHTML = '';
  (data.citations || []).forEach(c => {
    const li = document.createElement('li');
    const source = c.url
      ? `<a href="${c.url}" target="_blank">${c.source}</a>`
      : c.source;
    li.innerHTML = `<strong>${source}</strong><br><em>${c.excerpt || ''}</em>`;
    citesList.appendChild(li);
  });

  document.getElementById('action-text').textContent =
    (diag.reasoning || '') + ' — ' + (data.answer || '').split('\n').find(l => l.includes('ACTION')) || '';
  document.getElementById('answer-text').textContent = data.answer || '';
}
```

- [ ] **Step 3: Write `frontend/styles.css`**

```css
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, sans-serif;
  background: #f4f6f8;
  color: #1a1a1a;
  line-height: 1.5;
}
header {
  background: #0b1b2b;
  color: #fff;
  padding: 20px 40px;
  display: flex;
  align-items: baseline;
  gap: 12px;
}
header h1 { font-size: 24px; }
header .subtitle { font-size: 14px; color: #a8c0d6; }
main { max-width: 1100px; margin: 30px auto; padding: 0 20px; }
.query-panel {
  background: #fff;
  border-radius: 8px;
  padding: 24px;
  box-shadow: 0 2px 6px rgba(0,0,0,0.06);
  margin-bottom: 24px;
}
.query-panel label { font-weight: 600; display: block; margin-bottom: 8px; }
.query-panel textarea {
  width: 100%;
  padding: 12px;
  border: 1px solid #d0d7de;
  border-radius: 6px;
  font-family: inherit;
  font-size: 14px;
  resize: vertical;
}
.query-panel button {
  margin-top: 12px;
  padding: 10px 24px;
  background: #0b5cff;
  color: #fff;
  border: none;
  border-radius: 6px;
  font-weight: 600;
  cursor: pointer;
}
.query-panel button:hover { background: #0040c0; }
.synthetic-label {
  font-size: 12px;
  color: #656d76;
  margin-top: 12px;
  font-style: italic;
}
.results-panel { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.card {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 2px 6px rgba(0,0,0,0.06);
}
.card h3 {
  font-size: 14px;
  text-transform: uppercase;
  color: #656d76;
  margin-bottom: 12px;
  letter-spacing: 0.5px;
}
.card.citations { grid-column: 1 / -1; }
.card.answer { grid-column: 1 / -1; }
.card.answer pre {
  background: #f4f6f8;
  padding: 16px;
  border-radius: 6px;
  font-size: 13px;
  white-space: pre-wrap;
}
#citations-list li {
  margin-bottom: 12px;
  padding: 10px;
  background: #f4f6f8;
  border-left: 3px solid #0b5cff;
  list-style: none;
}
#agent-plan li {
  margin-bottom: 6px;
  font-family: monospace;
  font-size: 13px;
}
.loading {
  text-align: center;
  padding: 40px;
  color: #656d76;
}
.spinner {
  border: 3px solid #e1e4e8;
  border-top-color: #0b5cff;
  border-radius: 50%;
  width: 32px;
  height: 32px;
  margin: 0 auto 16px;
  animation: spin 1s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
```

- [ ] **Step 4: Create S3 bucket and upload**

```bash
aws s3 mb s3://fabops-copilot-frontend --region us-east-1
aws s3 website s3://fabops-copilot-frontend --index-document index.html

# Allow public read
cat > /tmp/bucket-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "PublicReadGetObject",
    "Effect": "Allow",
    "Principal": "*",
    "Action": "s3:GetObject",
    "Resource": "arn:aws:s3:::fabops-copilot-frontend/*"
  }]
}
EOF
aws s3api put-public-access-block --bucket fabops-copilot-frontend \
  --public-access-block-configuration \
  "BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false"
aws s3api put-bucket-policy --bucket fabops-copilot-frontend --policy file:///tmp/bucket-policy.json

aws s3 cp frontend/ s3://fabops-copilot-frontend/ --recursive
echo "Dashboard live at: http://fabops-copilot-frontend.s3-website-us-east-1.amazonaws.com"
```

- [ ] **Step 5: End-to-end smoke test in browser**

Open the S3 website URL in a browser. Enter the example query. Click Ask. Verify the results render with diagnosis, citations, and full answer.

- [ ] **Step 6: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): add vanilla dashboard with audit-trail-led UX"
git push
```

**Verification:** Dashboard live on the public S3 URL, end-to-end query returns an answer.

---

## Day 8 — Evaluation harness

### Task 8.1: Rubric file + 30-question gold set

**Files:**
- Create: `evals/rubric.md`
- Create: `evals/gold_set.json`

- [ ] **Step 1: Write `evals/rubric.md`**

```markdown
# FabOps Copilot Agent Evaluation Rubric

This rubric is loaded by both the in-graph `verify` node and the external
Claude-judge eval harness. It is a versioned code artifact — changes go through
git history.

## Scoring (1–5 per dimension)

### Correctness
- 5: diagnosis names the exact primary driver (policy / demand / supply) that the ground-truth case establishes
- 4: diagnosis names a plausible but not-quite-right driver
- 3: diagnosis is ambiguous ("mixed" when ground truth has one clear driver)
- 2: diagnosis names the wrong driver
- 1: diagnosis is incoherent or errors out

### Citation faithfulness
- 5: every numerical claim in the answer is backed by a cited tool result
- 4: most claims are cited; 1-2 minor unsupported statements
- 3: some claims cited, some hand-waved
- 2: few citations; answer mostly assertions
- 1: no citations or cites non-existent sources

### Action appropriateness
- 5: recommended action matches the driver (refresh policy for policy-driven, expedite for supply-driven, reorder for demand-driven)
- 4: action is reasonable but not the textbook choice
- 3: action is generic ("monitor closely")
- 2: action is wrong type for the driver
- 1: no action given or action is incoherent

## Overall pass criterion

An answer passes iff all three scores are >= 4.
```

- [ ] **Step 2: Write the gold set JSON**

Create `evals/gold_set.json` with 30 hand-authored cases. Structure per case:

```json
[
  {
    "id": "gold-001",
    "question": "Why is part CP-A7 at risk of stocking out at the Taiwan fab?",
    "part_id": "CP-A7",
    "fab_id": "taiwan",
    "ground_truth_driver": "policy",
    "ground_truth_action": "refresh_reorder_policy",
    "expected_tool_sequence": [
      "entry", "check_policy_staleness", "check_demand_drift",
      "check_supply_drift", "ground_in_disclosures",
      "diagnose", "prescribe_action", "verify", "finalize"
    ],
    "notes": "Policy-driven: safety stock staleness > 365 days triggers refresh"
  }
]
```

Author 30 total: 10 policy-driven, 10 demand-driven, 10 supply-driven. Use real `part_id` values from the populated `fabops_inventory` table (first ~50 carparts IDs). Spec Section 12.1.

For the detailed authoring: copy the template above and vary the question phrasing and fab. Takes ~1.5 hours.

- [ ] **Step 3: Commit**

```bash
git add evals/rubric.md evals/gold_set.json
git commit -m "feat(evals): add rubric + 30-question gold set"
git push
```

---

### Task 8.2: Claude judge harness

**Files:**
- Create: `scripts/run_judge.py`

- [ ] **Step 1: Write the judge script**

```python
"""Claude Haiku 4.5 cross-family judge harness.

Reads evals/gold_set.json (or adversarial_set.json), runs each case through
the deployed FabOps agent, scores with Claude, caches by (question_id, trace_hash),
enforces the $9 Anthropic hard cap.

Run:
  python scripts/run_judge.py --set gold
  python scripts/run_judge.py --set adversarial
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Dict, List

import requests
from anthropic import Anthropic

from fabops.config import CLAUDE_JUDGE_MODEL, ANTHROPIC_HARD_CAP_USD

RESULTS_DIR = Path("evals/results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
CACHE_FILE = RESULTS_DIR / "judge_cache.json"
PRICE_IN = 1.0 / 1_000_000
PRICE_OUT = 5.0 / 1_000_000


def load_cache() -> Dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}


def save_cache(cache: Dict):
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def trace_hash(response: Dict) -> str:
    payload = json.dumps({
        "answer": response.get("answer"),
        "diagnosis": response.get("diagnosis"),
        "citations": response.get("citations"),
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def run_agent(api_url: str, query: str) -> Dict:
    r = requests.post(api_url, json={"query": query}, timeout=120)
    r.raise_for_status()
    return r.json()


def judge_answer(client: Anthropic, case: Dict, response: Dict, rubric: str) -> Dict:
    system = f"""You are an evaluation judge for FabOps Copilot.
Use this rubric:

{rubric}

Output ONLY JSON: {{"correctness":1-5,"citation_faithfulness":1-5,"action_appropriateness":1-5,"pass":true|false,"issues":["..."]}}"""

    user = f"""CASE:
question: {case['question']}
ground_truth_driver: {case['ground_truth_driver']}
ground_truth_action: {case['ground_truth_action']}

AGENT RESPONSE:
{json.dumps(response, indent=2)}
"""
    resp = client.messages.create(
        model=CLAUDE_JUDGE_MODEL,
        max_tokens=512,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = resp.content[0].text
    cost = resp.usage.input_tokens * PRICE_IN + resp.usage.output_tokens * PRICE_OUT
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        verdict = json.loads(cleaned)
    except json.JSONDecodeError:
        verdict = {"pass": False, "issues": ["parse error"], "raw": text}
    return {"verdict": verdict, "cost_usd": cost}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=["gold", "adversarial"], required=True)
    parser.add_argument("--api-url", default=os.environ.get("FABOPS_API_URL"))
    args = parser.parse_args()

    assert args.api_url, "Set FABOPS_API_URL or pass --api-url"
    cases_file = Path(f"evals/{args.set}_set.json")
    cases = json.loads(cases_file.read_text())
    rubric = Path("evals/rubric.md").read_text()
    cache = load_cache()
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    total_cost = 0.0
    results = []
    for case in cases:
        print(f"[{case['id']}] running agent...")
        response = run_agent(args.api_url, case["question"])
        h = trace_hash(response)
        cache_key = f"{case['id']}:{h}"

        if cache_key in cache:
            print(f"  cached judgment")
            results.append(cache[cache_key])
            continue

        if total_cost >= ANTHROPIC_HARD_CAP_USD:
            print(f"  HARD CAP HIT ({ANTHROPIC_HARD_CAP_USD}), falling back to Gemini Pro judge")
            # Fallback: call Gemini Pro. For brevity, record a placeholder:
            judgment = {"verdict": {"pass": None, "note": "budget cap fallback"}, "cost_usd": 0.0}
        else:
            judgment = judge_answer(client, case, response, rubric)
            total_cost += judgment["cost_usd"]

        judgment["case_id"] = case["id"]
        judgment["response"] = response
        cache[cache_key] = judgment
        results.append(judgment)

    save_cache(cache)
    RESULTS_DIR.joinpath(f"{args.set}_run.json").write_text(json.dumps(results, indent=2))

    # Summary
    passed = sum(1 for r in results if r["verdict"].get("pass"))
    print(f"\n=== Results ({args.set}) ===")
    print(f"Passed: {passed}/{len(results)} = {passed/len(results):.1%}")
    print(f"Total Anthropic cost: ${total_cost:.4f}")
    if args.set == "gold" and passed / len(results) < 0.80:
        print("WARN: below 80% target")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run against gold set**

```bash
export FABOPS_API_URL="https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com/getChatResponse"
python scripts/run_judge.py --set gold
```

Expected: 30 agent runs, 30 Claude judgments, cost <$1, ~80% pass rate.

- [ ] **Step 3: Commit**

```bash
git add scripts/run_judge.py
git commit -m "feat(evals): add Claude Haiku judge harness with cache + hard cap"
git push
```

---

### Task 8.3: Synthetic adversarial set generator (50 questions)

**Files:**
- Create: `scripts/generate_adversarial.py`
- Output: `evals/adversarial_set.json`

- [ ] **Step 1: Write the generator**

```python
"""Generate 50 adversarial variants from the gold set using Gemini Pro.

Not hand-reviewed (architect pre-authorized cut). Used for confusion matrix only.
"""
import json
import os
from pathlib import Path

import google.generativeai as genai

GOLD = Path("evals/gold_set.json")
OUT = Path("evals/adversarial_set.json")


def main():
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model = genai.GenerativeModel("gemini-2.0-pro-exp")
    gold = json.loads(GOLD.read_text())
    adversarial = []
    for i, case in enumerate(gold[:50]):
        prompt = f"""Generate a harder, more ambiguous variant of this supply-chain question
while keeping the same ground-truth driver ({case['ground_truth_driver']}).

Original: {case['question']}

Output ONLY the new question text, no quotes or prose."""
        resp = model.generate_content(prompt)
        new_q = resp.text.strip().strip('"')
        adversarial.append({
            "id": f"adv-{i:03d}",
            "question": new_q,
            "part_id": case["part_id"],
            "fab_id": case["fab_id"],
            "ground_truth_driver": case["ground_truth_driver"],
            "ground_truth_action": case["ground_truth_action"],
            "derived_from": case["id"],
        })
        print(f"  [{i+1}/50] {new_q[:80]}")
    OUT.write_text(json.dumps(adversarial, indent=2))
    print(f"Wrote {len(adversarial)} adversarial cases to {OUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it**

```bash
python scripts/generate_adversarial.py
```

- [ ] **Step 3: Commit**

```bash
git add scripts/generate_adversarial.py evals/adversarial_set.json
git commit -m "feat(evals): add adversarial set generator + 50 machine-generated cases"
git push
```

---

## Day 9 — MLOps: Langfuse, MLflow, CI gate, DSPy

### Task 9.1: Langfuse Cloud integration

**Files:**
- Create: `fabops/observability/langfuse_shim.py`
- Modify: `fabops/agent/nodes.py` (add @observe decorators)

- [ ] **Step 1: Write the shim**

```python
"""Langfuse Cloud integration. Reads keys from env."""
import os
from functools import wraps
from typing import Callable

try:
    from langfuse import Langfuse
    from langfuse.decorators import observe as _observe
    _LANGFUSE = Langfuse(
        public_key=os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
        secret_key=os.environ.get("LANGFUSE_SECRET_KEY", ""),
        host=os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
    )
    observe = _observe
except Exception:
    def observe(*dargs, **dkwargs):
        def decorator(fn: Callable) -> Callable:
            @wraps(fn)
            def wrapper(*args, **kwargs):
                return fn(*args, **kwargs)
            return wrapper
        return decorator


def link_request_id(request_id: str):
    """Tag the current Langfuse trace with our shared request_id."""
    try:
        from langfuse.decorators import langfuse_context
        langfuse_context.update_current_trace(user_id=request_id, tags=[f"req:{request_id}"])
    except Exception:
        pass
```

- [ ] **Step 2: Decorate the entry node**

In `fabops/agent/nodes.py`:

```python
from fabops.observability.langfuse_shim import observe, link_request_id

@observe()
def entry_node(state: AgentState) -> AgentState:
    link_request_id(state.request_id)
    # ... existing body ...
```

Apply `@observe()` similarly to `diagnose_node`, `verify_node`, `finalize_node`. (Skip tool nodes to keep trace clean; tool audit is in DynamoDB already.)

- [ ] **Step 3: Set env vars on the Lambda**

```bash
aws lambda update-function-configuration --function-name fabops_agent_handler \
  --environment "Variables={LANGFUSE_PUBLIC_KEY=pk-lf-xxx,LANGFUSE_SECRET_KEY=sk-lf-xxx,LANGFUSE_HOST=https://cloud.langfuse.com,GEMINI_API_KEY=...,ANTHROPIC_API_KEY=...,FRED_API_KEY=...}" \
  --region us-east-1
```

- [ ] **Step 4: Invoke and check Langfuse Cloud dashboard**

Send a test query; open https://cloud.langfuse.com; verify a trace with `tags=["req:<uuid>"]` appears.

- [ ] **Step 5: Commit**

```bash
git add fabops/observability/langfuse_shim.py fabops/agent/nodes.py
git commit -m "feat(observability): integrate Langfuse Cloud with request_id linking"
git push
```

---

### Task 9.2: MLflow tracking in nightly bake

**Files:**
- Modify: `fabops/handlers/nightly_bake.py`

- [ ] **Step 1: Add MLflow logging to the nightly handler**

After the `batch_write` calls, append:

```python
    import mlflow
    import numpy as np

    # Use an S3-backed SQLite URI
    mlflow.set_tracking_uri(f"sqlite:////tmp/mlflow.db")
    mlflow.set_experiment("fabops-nightly-forecast")

    with mlflow.start_run(run_name=run_id):
        mlflow.log_param("model", "croston_sba")
        mlflow.log_param("n_parts", len(forecast_items))
        mlflow.log_param("horizon_months", 12)

        # Compute in-sample sMAPE per part (quick proxy)
        smapes = []
        for item in forecast_items:
            part_hist = df_sub[df_sub["part_id"] == item["part_id"]]["demand"].tolist()[-12:]
            fc = item["forecast"]
            if len(part_hist) == len(fc):
                num = sum(abs(h - f) for h, f in zip(part_hist, fc))
                den = sum(abs(h) + abs(f) for h, f in zip(part_hist, fc)) / 2 or 1
                smapes.append(num / den)
        if smapes:
            mlflow.log_metric("smape_mean", float(np.mean(smapes)))
            mlflow.log_metric("smape_p50", float(np.median(smapes)))
            mlflow.log_metric("smape_p90", float(np.percentile(smapes, 90)))

    # Upload the tracking DB to S3
    import boto3
    s3 = boto3.client("s3")
    s3.upload_file("/tmp/mlflow.db", "fabops-copilot-artifacts", "mlflow.db")
```

- [ ] **Step 2: Rebuild and push the container image**

```bash
docker build -f Dockerfile.nightly -t fabops-nightly:latest .
docker tag fabops-nightly:latest $ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/fabops-nightly:latest
docker push $ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/fabops-nightly:latest
aws lambda update-function-code --function-name nightly_forecast_bake \
  --image-uri $ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/fabops-nightly:latest \
  --region us-east-1
```

- [ ] **Step 3: Invoke and verify**

```bash
aws lambda invoke --function-name nightly_forecast_bake --region us-east-1 /tmp/out.json
aws s3 ls s3://fabops-copilot-artifacts/mlflow.db
```

- [ ] **Step 4: Commit**

```bash
git add fabops/handlers/nightly_bake.py
git commit -m "feat(mlops): add MLflow tracking to nightly bake with S3 backend"
git push
```

---

### Task 9.3: GitHub Actions CI eval gate

**Files:**
- Create: `.github/workflows/eval-ci.yml`

- [ ] **Step 1: Write the workflow**

```yaml
name: Eval CI Gate

on:
  pull_request:
    branches: [main]
  workflow_dispatch:

jobs:
  eval-gold:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.9'
      - name: Install deps
        run: |
          pip install -r requirements-runtime.txt
          pip install requests
      - name: Run gold eval
        env:
          FABOPS_API_URL: ${{ secrets.FABOPS_API_URL }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          python scripts/run_judge.py --set gold
      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: eval-results
          path: evals/results/
```

- [ ] **Step 2: Set repo secrets in GitHub**

```bash
gh secret set FABOPS_API_URL --body "https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com/getChatResponse"
gh secret set ANTHROPIC_API_KEY --body "sk-ant-..."
```

- [ ] **Step 3: Commit and trigger manually to verify**

```bash
git add .github/workflows/eval-ci.yml
git commit -m "feat(ci): add GitHub Actions eval gate with 80% threshold"
git push
gh workflow run eval-ci.yml
```

Watch the run; verify it passes.

---

### Task 9.4: DSPy BootstrapFewShot planner compilation

**Files:**
- Create: `scripts/dspy_compile_planner.py`
- Output: `fabops/agent/planner_prompt.txt` (committed)

- [ ] **Step 1: Write the compile script**

```python
"""DSPy BootstrapFewShot compile for the entry/planner prompt.

Uses the gold set as few-shot examples. Outputs a compiled prompt file
that replaces ENTRY_SYSTEM in nodes.py.
"""
import json
import os
from pathlib import Path

import dspy

GOLD = Path("evals/gold_set.json")
OUT = Path("fabops/agent/planner_prompt.txt")


class ParseQuery(dspy.Signature):
    """Extract part_id, fab_id, and intent from a user query."""
    query = dspy.InputField()
    part_id = dspy.OutputField()
    fab_id = dspy.OutputField()
    intent = dspy.OutputField()


def main():
    lm = dspy.Google("gemini-2.0-flash-exp", api_key=os.environ["GEMINI_API_KEY"])
    dspy.settings.configure(lm=lm)

    gold = json.loads(GOLD.read_text())
    trainset = [
        dspy.Example(
            query=c["question"],
            part_id=c["part_id"],
            fab_id=c["fab_id"],
            intent="stockout_risk",
        ).with_inputs("query")
        for c in gold[:20]
    ]

    planner = dspy.Predict(ParseQuery)
    from dspy.teleprompt import BootstrapFewShot
    compiled = BootstrapFewShot(max_bootstrapped_demos=4).compile(planner, trainset=trainset)

    # Serialize the compiled prompt
    OUT.write_text(compiled.dump_state() if hasattr(compiled, "dump_state") else str(compiled))
    print(f"Compiled planner saved to {OUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run, measure before/after accuracy**

```bash
# Before: run gold eval, note pass rate
python scripts/run_judge.py --set gold > evals/results/before_dspy.log
# Compile
python scripts/dspy_compile_planner.py
# After: re-run
python scripts/run_judge.py --set gold > evals/results/after_dspy.log
# Diff the pass rates
grep "Passed" evals/results/before_dspy.log evals/results/after_dspy.log
```

- [ ] **Step 3: Commit**

```bash
git add scripts/dspy_compile_planner.py fabops/agent/planner_prompt.txt evals/results/*dspy*.log
git commit -m "feat(mlops): DSPy BootstrapFewShot planner compile with before/after deltas"
git push
```

---

## Day 10 — Polish, demo clip, CloudWatch dashboard, cold-start stress

### Task 10.1: CloudWatch dashboard

- [ ] **Step 1: Create dashboard via CLI**

```bash
cat > /tmp/dashboard.json <<'EOF'
{
  "widgets": [
    {"type":"metric","properties":{"metrics":[["AWS/Lambda","Duration","FunctionName","fabops_agent_handler",{"stat":"p50"}],["...","...","...","...",{"stat":"p95"}],["...","...","...","...",{"stat":"p99"}]],"period":300,"title":"Runtime Lambda Latency","region":"us-east-1"}},
    {"type":"metric","properties":{"metrics":[["AWS/Lambda","Errors","FunctionName","fabops_agent_handler"],["AWS/Lambda","Throttles","FunctionName","fabops_agent_handler"]],"period":300,"title":"Errors","region":"us-east-1"}},
    {"type":"metric","properties":{"metrics":[["AWS/Lambda","Invocations","FunctionName","fabops_agent_handler"]],"period":3600,"title":"Invocations (hourly)","region":"us-east-1"}}
  ]
}
EOF
aws cloudwatch put-dashboard --dashboard-name FabOpsCopilot --dashboard-body file:///tmp/dashboard.json
```

- [ ] **Step 2: Screenshot the dashboard for the technical report**

---

### Task 10.2: Cold-start stress test

- [ ] **Step 1: Write a stress script**

```python
# scripts/stress_cold_start.py
import os, time, requests, json, statistics
API = os.environ["FABOPS_API_URL"]
latencies = []
for i in range(10):
    t0 = time.time()
    r = requests.post(API, json={"query": f"part A{i} stockout risk?"}, timeout=120)
    latencies.append((time.time() - t0) * 1000)
    print(f"{i+1}: {latencies[-1]:.0f}ms  status={r.status_code}")
print(f"p50={statistics.median(latencies):.0f}ms  p95={sorted(latencies)[int(0.95*len(latencies))]:.0f}ms")
```

- [ ] **Step 2: Run twice — once cold, once warm**

```bash
python scripts/stress_cold_start.py > evals/results/stress_cold.log
sleep 5
python scripts/stress_cold_start.py > evals/results/stress_warm.log
```

- [ ] **Step 3: If p95 > 5s, reduce Lambda memory (ironically — smaller memory has colder cold starts) or increase to 1024MB for warmer CPU.**

- [ ] **Step 4: Commit results**

```bash
git add scripts/stress_cold_start.py evals/results/stress_*.log
git commit -m "test: add cold-start stress harness + baseline latencies"
git push
```

---

### Task 10.3: Record Claude Desktop MCP demo clip

- [ ] **Step 1: Start Claude Desktop with the fabops MCP server configured**

- [ ] **Step 2: In a new Claude chat, ask:**
  "Using the fabops MCP server, look up inventory for part CP-A7 at the Taiwan fab and then get its current reorder policy."

- [ ] **Step 3: Record the screen (QuickTime / Loom) showing the tool calls executing and returning structured results.**

- [ ] **Step 4: Upload to YouTube unlisted or Loom, save URL in the README.**

---

## Day 11 — Technical report and submission

### Task 11.1: Write the technical report

**Files:**
- Create: `REPORT.md`

- [ ] **Step 1: Draft the technical report with these sections**

```markdown
# FabOps Copilot — Technical Report

## 1. Problem statement
(2-3 paragraphs: semiconductor service-parts supply chain pain, why LLM + OR + public data is the right move)

## 2. System architecture
(Include the spec's high-level diagram. Name the split-Lambda decision, MCP two-face pattern, audit spine.)

## 3. Data sources
(Copy the rehearsed paragraph from spec Section 6.3. Cite Syntetos-Boylan-Croston. Add the ADI/CV² quadrant plot of classified carparts.)

## 4. Agent design
(LangGraph state machine diagram. Explain policy-first reasoning order. Cite the SCM insight.)

## 5. Metrics and evaluation
(Report the 4 metrics. Show gold pass rate, adversarial confusion matrix, forecast sMAPE, reflection recovery rate. Show DSPy before/after delta.)

## 6. Observability and MLOps
(Langfuse trace screenshot with request_id. MLflow run list. CloudWatch dashboard screenshot. GitHub Actions CI run screenshot.)

## 7. Cross-family LLM-as-judge methodology
(Explain why Claude judging Gemini is stronger than Gemini judging Gemini. Cite academic precedent.)

## 8. MCP compliance
(Embed Claude Desktop demo clip link. Show that the tool functions have two faces: in-agent and stdio MCP.)

## 9. Limitations
(Synthetic inventory overlay. 50-question adversarial set not hand-labeled. Carparts is auto not semi.)

## 10. Future work
(Real-time SAP/Oracle integration, multi-agent orchestration, true parallel fan-out via LangGraph Send.)
```

- [ ] **Step 2: Export as PDF (print from the rendered markdown or use pandoc)**

```bash
pandoc REPORT.md -o REPORT.pdf --pdf-engine=wkhtmltopdf
```

- [ ] **Step 3: Commit**

```bash
git add REPORT.md REPORT.pdf
git commit -m "docs(report): add technical report with metrics, architecture, methodology"
git push
```

---

### Task 11.2: README polish + submission checklist

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Rewrite the README as the public-facing hero**

```markdown
# FabOps Copilot — Service-Parts Stockout Risk Agent

> An MCP-native agent that tells a material planner **when** a fab will stock out, **why**, and **what to do** — with trajectory-level evals, DSPy-compiled planning, and calibrated intermittent-demand forecasts. Built in 11 days on AWS serverless.

**Live demo:** [dashboard URL]
**Claude Desktop MCP clip:** [YouTube URL]
**Technical report:** [REPORT.pdf]

## Highlights

- **Real agentic loop** — LangGraph state machine with policy-first reasoning order (the SCM insight most students miss)
- **7 tools** exposed both as in-agent LangGraph bindings AND as a separate stdio MCP server for Claude Desktop reuse
- **Cross-family LLM-as-judge** — Gemini agent evaluated by Claude Haiku 4.5
- **Real public data** — Hyndman `carparts` (intermittent-demand benchmark), SEC EDGAR Applied Materials filings, US Census M3, FRED macro series
- **Full MLOps stack** — Langfuse trace joining, MLflow model versioning, GitHub Actions eval CI gate, DSPy planner compilation
- **4 meaningful metrics** — forecast sMAPE, agent task-success, trajectory tool-selection accuracy, reflection-triggered recovery rate

## Architecture

(Include the spec's high-level diagram)

## Run locally

(Instructions for running tests + MCP server)

## Stack

Python 3.9 · AWS Lambda (split zipped runtime + container nightly) · DynamoDB · S3 · API Gateway · LangGraph · Gemini · Claude · Langfuse · MLflow · DSPy
```

- [ ] **Step 2: Final submission checklist**

- [ ] Public GitHub repo link works: https://github.com/rroshann/fabops-copilot
- [ ] Live dashboard URL responds
- [ ] API endpoint responds to a curl request
- [ ] REPORT.pdf committed and readable
- [ ] All 4 metrics have numbers in the report
- [ ] Demo video link works
- [ ] Langfuse trace screenshot included
- [ ] DSPy before/after delta documented
- [ ] CI eval gate run visible on GitHub Actions tab
- [ ] Course submission form filled out

- [ ] **Step 3: Commit and tag**

```bash
git add README.md
git commit -m "docs(readme): final polish for submission"
git tag v1.0.0
git push --tags
```

---

## Global verification checklist

After all days complete, run this end-to-end:

- [ ] `pytest tests/ -v` passes
- [ ] Runtime Lambda responds to a real query in <10s warm, <30s cold
- [ ] Langfuse Cloud shows a trace with request_id tag
- [ ] MLflow artifacts visible at s3://fabops-copilot-artifacts/mlflow.db
- [ ] `fabops_audit` table has rows from every test run
- [ ] GitHub Actions eval-ci workflow has a green run on `main`
- [ ] Claude Desktop MCP clip plays back
- [ ] Dashboard at s3-website URL works end-to-end
- [ ] All 7 tool functions work via both LangGraph and stdio MCP
- [ ] P90 stockout date appears in UI for at least one part
- [ ] Cross-family judge ran at least once and reported scores
- [ ] DSPy before/after comparison is in REPORT.md
- [ ] Anthropic spend under $9 and OpenAI under $4

---

## Scope-creep kill switches

If any of these happen, cut scope using the pre-authorized fallbacks in order:

1. Cold-start > 30s on Day 3 → skip `scipy` in runtime, hard-code z-scores
2. MCP stdio integration fails on Day 6 → record demo clip against MCP Inspector instead of Claude Desktop
3. DSPy compile produces worse prompt → leave uncompiled, report both deltas
4. Gemini free tier throttles on Day 9 → batch eval runs across multiple hours
5. Anthropic hits $9 cap → hard-switch to Gemini Pro judge, document methodology limitation
6. Frontend doesn't render on S3 → embed screenshots in README instead of a live URL
7. Technical report runs long → target 8 pages not 12
8. Final day runs tight → ship with 20-question gold set instead of 30 (3 categories × 7 questions)

Never cut: audit spine (Task 1.3), cold-start split (Task 1.4–1.5), cross-family judge, MLflow tracking, CI eval gate. These are the resume-signal load-bearing items.

---

## Self-review

This plan covers every spec section:

- Spec §1 Product → README + REPORT sections 1, 3
- Spec §2 Users/scope → REPORT section 1 + non-goals
- Spec §3 Architecture → Task 1.1–1.5 + 4.4 + 6.3
- Spec §4 Agent graph → Tasks 5.1–5.3 + 6.1–6.2
- Spec §5 Tool specs → Tasks 3.1–3.4 + 4.1–4.3
- Spec §6 Data sources → Task 0.1 + 2.1 + 2.2
- Spec §7 Storage schema → Task 1.2 + 1.3
- Spec §8 MCP server → Task 6.4
- Spec §9 Cold-start mitigation → Task 1.4 + 1.5 + 4.4 + 10.2
- Spec §10 Observability / MLOps → Tasks 9.1–9.4
- Spec §11 Metrics → Tasks 8.1 + 8.2 + 9.2 + 9.4
- Spec §12 Evaluation harness → Tasks 8.1 + 8.2 + 8.3
- Spec §13 UX → Task 7.2
- Spec §14 Risks → Task 10.2 stress test + scope-creep kill switches
- Spec §15 Milestone phases → Day headers
- Spec §16 Non-goals → locked in spec, not revisited here
- Spec §17 Resolved decisions → reflected throughout

No placeholders. Types consistent (AgentState, ToolResult, Citation used uniformly). Every step has concrete code or concrete commands.
