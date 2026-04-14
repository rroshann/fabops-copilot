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
from datetime import date
from pathlib import Path
from typing import Dict, List

import boto3
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
from tenacity import RetryError, retry, stop_after_attempt, wait_exponential
from tqdm import tqdm

CIK = "0000006951"  # Applied Materials
FORMS = ["10-K", "10-Q", "8-K"]
YEARS_BACK = 3
CHUNK_TOKENS = 500  # approx, measured in words for simplicity
EMBED_MODEL = "models/gemini-embedding-001"
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


# FIX 5: Added retry decorator and rate-limit sleep to list_filings
@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=30))
def list_filings(email: str) -> List[Dict]:
    """Query EDGAR submissions API for AM's recent filings of interest."""
    time.sleep(0.15)  # respect 10 req/sec limit
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
    # FIX 4: Use date.today().year instead of hardcoded 2026
    cutoff = f"{date.today().year - YEARS_BACK}-01-01"
    return [filing for filing in filings if filing["filing_date"] >= cutoff]


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


# FIX 1: Linearize tables instead of dropping them
def clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    # script/style are pure noise — drop entirely
    for tag in soup(["script", "style"]):
        tag.decompose()
    # tables carry financial + supply-chain data — linearize, do not drop
    for table in soup.find_all("table"):
        linearized = " | ".join(
            cell.get_text(strip=True) for cell in table.find_all(["td", "th"]) if cell.get_text(strip=True)
        )
        table.replace_with(f" {linearized} ")
    return " ".join(soup.get_text().split())


# FIX 2a: Corrected sleep to 2.5s (~24/min, under 30/min RPM free-tier ceiling)
#          and bumped retry to 8 attempts with max 120s wait for wider RPM recovery window
@retry(stop=stop_after_attempt(8), wait=wait_exponential(multiplier=2, min=10, max=120))
def embed(text: str) -> List[float]:
    time.sleep(2.5)  # ~24 req/min — safely under Gemini free-tier 30 RPM; spreads RPD across the day
    result = genai.embed_content(model=EMBED_MODEL, content=text, task_type="retrieval_document")
    return result["embedding"]


# FIX 3a: Extracted helper so incremental saves share one code path
def _save_chunks(chunks: List[Dict]) -> None:
    CHUNKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHUNKS_FILE.write_text(json.dumps(chunks, indent=2))


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
        # FIX (minor): Renamed loop variable from f to filing to avoid shadowing the built-in
        for filing in tqdm(filings, desc="Fetching filings"):
            acc_nodashes = filing["accession"].replace("-", "")
            url = f"https://www.sec.gov/Archives/edgar/data/6951/{acc_nodashes}/{filing['primary_doc']}"
            local = RAW_DIR / f"{filing['accession']}.html"
            if not local.exists():
                html = fetch(url, args.email)
                local.write_text(html)
            text = clean_html(local.read_text())
            for i, chunk in enumerate(chunk_text(text)):
                chunk_id = hashlib.md5(f"{filing['accession']}-{i}".encode()).hexdigest()[:16]
                all_chunks.append({
                    "doc_id": filing["accession"],
                    "chunk_id": chunk_id,
                    "form": filing["form"],
                    "filing_date": filing["filing_date"],
                    "sec_url": url,
                    "text": chunk,
                })

        # FIX 3a: Save immediately after building chunk list (before embedding starts)
        _save_chunks(all_chunks)
        print(f"Wrote {len(all_chunks)} chunks to {CHUNKS_FILE}")

        # FIX 3b: Resume logic — load already-embedded chunks and skip them
        if CHUNKS_FILE.exists():
            existing = {c["chunk_id"]: c for c in json.loads(CHUNKS_FILE.read_text()) if "embedding" in c}
            if existing:
                print(f"[resume] Found {len(existing)} already-embedded chunks; skipping them")
                for c in all_chunks:
                    if c["chunk_id"] in existing:
                        c["embedding"] = existing[c["chunk_id"]]["embedding"]

        print("Embedding chunks (slow; respects Gemini free-tier RPM)...")
        for idx, c in enumerate(tqdm(all_chunks, desc="Embedding")):
            # FIX 3b: Skip chunks that already have an embedding (from resume)
            if "embedding" in c:
                continue
            # FIX 2b: Catch RetryError after quota exhaustion — save progress and exit cleanly
            try:
                c["embedding"] = embed(c["text"])
            except (RetryError, Exception) as e:
                print(f"\n[embed] FAILED for chunk {c['chunk_id']} after retries: {e}")
                embedded_count = len([x for x in all_chunks if "embedding" in x])
                print(f"[embed] Progress saved at {embedded_count}/{len(all_chunks)} chunks.")
                print(f"[embed] Resume tomorrow by re-running the same command (idempotent via --upload-only once complete)")
                # FIX 3a: Save current progress before exiting
                _save_chunks(all_chunks)
                raise SystemExit(1)
            # FIX 3a: Incremental save every 100 embeddings
            if (idx + 1) % 100 == 0:
                _save_chunks(all_chunks)

        # FIX 3a: Final save after embedding loop completes
        _save_chunks(all_chunks)
        print(f"Embeddings complete; re-wrote {CHUNKS_FILE}")

        if args.skip_upload:
            print("--skip-upload set; stopping before AWS writes.")
            return
    else:
        # --upload-only mode: load the existing chunks file
        all_chunks = json.loads(CHUNKS_FILE.read_text())
        print(f"Loaded {len(all_chunks)} chunks from {CHUNKS_FILE}")
        # FIX 3c: Skip chunks without embeddings rather than crashing DynamoDB write
        missing = [c for c in all_chunks if "embedding" not in c]
        if missing:
            print(f"[upload-only] WARNING: {len(missing)} chunks have no embedding and will be skipped.")
            all_chunks = [c for c in all_chunks if "embedding" in c]
            print(f"[upload-only] Uploading {len(all_chunks)} embedded chunks.")

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
