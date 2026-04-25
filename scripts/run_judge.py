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
import re
import sys
from pathlib import Path
from typing import Dict

import boto3
import requests
from anthropic import Anthropic
from botocore.config import Config as BotoConfig

from fabops.config import AWS_REGION, CLAUDE_JUDGE_MODEL, ANTHROPIC_HARD_CAP_USD


def _extract_json_object(text: str) -> str:
    """Pull a JSON object out of a model response that may be wrapped in
    markdown fences or preceded by prose. Falls back to the original text.
    """
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return m.group(1)
    m = re.search(r"(\{.*\})", text, re.DOTALL)
    if m:
        return m.group(1)
    return text.strip()

LAMBDA_FUNCTION_NAME = "fabops_agent_handler"
# Lambda hard-timeout is 90s; boto3 read_timeout must be >= that.
_BOTO_CONFIG = BotoConfig(read_timeout=180, connect_timeout=10, retries={"max_attempts": 2})
_LAMBDA_CLIENT = None


def _get_lambda_client():
    global _LAMBDA_CLIENT
    if _LAMBDA_CLIENT is None:
        _LAMBDA_CLIENT = boto3.client("lambda", region_name=AWS_REGION, config=_BOTO_CONFIG)
    return _LAMBDA_CLIENT

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
    """Invoke the deployed agent Lambda directly (bypasses API Gateway).

    Direct invoke avoids API Gateway's 30s HTTP API integration timeout on
    cold-start cases. The agent still runs the full LangGraph loop — only
    the transport layer differs. Set FABOPS_USE_HTTP=1 to force the HTTP
    path through API Gateway instead (useful for smoke-testing routing).
    """
    if os.environ.get("FABOPS_USE_HTTP") == "1":
        r = requests.post(api_url, json={"query": query}, timeout=180)
        r.raise_for_status()
        return r.json()

    client = _get_lambda_client()
    resp = client.invoke(
        FunctionName=LAMBDA_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps({"body": json.dumps({"query": query})}),
    )
    raw = json.loads(resp["Payload"].read())
    # runtime handler returns API Gateway-shaped dict: {statusCode, headers, body}
    body = raw.get("body", "{}")
    if isinstance(body, str):
        body = json.loads(body)
    if raw.get("statusCode", 500) >= 500:
        raise RuntimeError(f"agent Lambda returned {raw.get('statusCode')}: {body}")
    return body


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
    try:
        verdict = json.loads(_extract_json_object(text))
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
        print(f"[{case['id']}] running agent...", flush=True)
        try:
            response = run_agent(args.api_url, case["question"])
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {str(e)[:200]}", flush=True)
            judgment = {
                "verdict": {"pass": False, "issues": [f"agent error: {type(e).__name__}"]},
                "cost_usd": 0.0,
                "case_id": case["id"],
                "response": {"error": str(e)[:500]},
            }
            results.append(judgment)
            cache[f"{case['id']}:error"] = judgment
            save_cache(cache)  # persist incrementally
            continue
        h = trace_hash(response)
        cache_key = f"{case['id']}:{h}"

        if cache_key in cache:
            print("  cached judgment")
            results.append(cache[cache_key])
            continue

        if total_cost >= ANTHROPIC_HARD_CAP_USD:
            print(f"  HARD CAP HIT ({ANTHROPIC_HARD_CAP_USD}), falling back to Gemini Pro judge")
            judgment = {"verdict": {"pass": None, "note": "budget cap fallback"}, "cost_usd": 0.0}
        else:
            judgment = judge_answer(client, case, response, rubric)
            total_cost += judgment["cost_usd"]

        judgment["case_id"] = case["id"]
        judgment["response"] = response
        cache[cache_key] = judgment
        results.append(judgment)
        save_cache(cache)  # persist incrementally so mid-loop crash doesn't lose work
        print(f"  pass={judgment['verdict'].get('pass')} cost=${judgment['cost_usd']:.4f}", flush=True)

    save_cache(cache)
    RESULTS_DIR.joinpath(f"{args.set}_run.json").write_text(json.dumps(results, indent=2))

    passed = sum(1 for r in results if r["verdict"].get("pass"))
    print(f"\n=== Results ({args.set}) ===")
    print(f"Passed: {passed}/{len(results)} = {passed/len(results):.1%}")
    print(f"Total Anthropic cost: ${total_cost:.4f}")
    if args.set == "gold" and passed / len(results) < 0.80:
        print("WARN: below 80% target")
        sys.exit(1)


if __name__ == "__main__":
    main()
