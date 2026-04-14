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
    parser.add_argument("--upload-only", action="store_true", help="Skip fetch/chunk/embed; only upload existing chunks.json")
    args = parser.parse_args()

    assert args.gemini_api_key or args.upload_only, "Set GEMINI_API_KEY or pass --gemini-api-key (unless --upload-only)"

    if not args.upload_only:
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
    else:
        # --upload-only mode: load the existing chunks file
        all_chunks = json.loads(CHUNKS_FILE.read_text())
        print(f"Loaded {len(all_chunks)} chunks from {CHUNKS_FILE}")

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
