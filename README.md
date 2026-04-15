# FabOps Copilot

> A portfolio-grade agentic AI system that diagnoses why a semiconductor fab service part is at stockout risk and recommends an action, grounded in real SEC filings, real FRED macro signals, and a real intermittent-demand benchmark.

![Python](https://img.shields.io/badge/python-3.9-blue.svg)
![AWS](https://img.shields.io/badge/AWS-Lambda%20%7C%20DynamoDB%20%7C%20API%20Gateway-orange.svg)
![Tests](https://img.shields.io/badge/tests-41%2F41%20passing-brightgreen.svg)

**Live demos**
- Primary (HTTPS via Amplify): https://main.d23s2e6xnypmh0.amplifyapp.com
- Secondary (raw S3 static site): http://fabops-copilot-frontend.s3-website-us-east-1.amazonaws.com
- API endpoint: `https://3ph4o9amg4.execute-api.us-east-1.amazonaws.com/getChatResponse`

**Documents**
- [Technical report (REPORT.md)](./REPORT.md), 10 sections, 4,279 words
- [Source on GitHub](https://github.com/rroshann/fabops-copilot)

---

## The problem

A semiconductor fab runs hundreds of expensive service parts across many sites. Most of them move slowly and unpredictably. When one of them is about to stock out, a planner has to answer three questions in a hurry: is this a demand problem, a supply problem, or a stale policy problem. Each of those answers leads to a completely different action. Getting the wrong answer costs real money, either in rushed air freight or in tool downtime. The evidence needed to answer correctly lives in six different places: the ERP inventory table, the historical demand series, the supplier lead-time log, the latest 10-K risk factors, the Fed's industrial production index, and the last time anyone bothered to recompute the reorder policy. FabOps Copilot reads all six, reasons across them as an agent, and returns a single diagnosed driver plus a prescribed action with citations.

## What it does

You give it a part and a fab. For example:

> "Why is part 10279876 at risk of stocking out at the Taiwan fab, and what should I do?"

It runs a 9-node LangGraph state machine that:

1. Pulls current inventory and the live reorder policy.
2. Checks whether the policy is stale relative to the most recent demand history (the insight most naive pipelines skip).
3. Checks for demand drift against the Croston SBA forecast baked by last night's job.
4. Checks for supply drift using the supplier lead-time trend and the simulated disruption model.
5. Grounds the whole thing in real Applied Materials SEC disclosures retrieved by cosine similarity over Gemini 3072-dim embeddings.
6. Asks Gemini 2.5 Flash to diagnose the driver as one of `policy_drift`, `supply_risk`, `demand_shift`, or `none`.
7. Dispatches to a rule-based prescriber keyed on the diagnosed driver.
8. Runs a verify pass.
9. Finalizes and writes every intermediate artifact to a DynamoDB audit table.

You get back a short diagnosis card, a concrete recommended action, a set of citations grouped by source, and a collapsible full audit trail showing every tool call with real timings. A typical answer reads like "Policy drift. The reorder policy for part 10279876 has not been refreshed in 409 days, so the trigger point no longer reflects current consumption. Refresh the policy before placing a new order," with inline links to the specific policy row, the forecast snapshot, and the 10-K passage that frames Applied Materials' service-parts exposure.

## Try it yourself

The fastest way to understand this project is to open the [primary demo](https://main.d23s2e6xnypmh0.amplifyapp.com) and click three things:

1. **"How it works"** in the header. It opens a modal that walks through the 9 nodes of the agent graph with plain-English descriptions of each, plus a two-column "real vs synthetic" data provenance summary.
2. **"+ browse 18 drift cases"** in the main panel. It opens a curated catalog of the 18 real gold-set drift cases (6 policy drift, 9 supply risk, 3 demand shift). Click any row and it runs the agent against that part immediately.
3. **"catalog · 200 parts × 9 fabs"** next to it. The full 200-part inventory, searchable by prefix, each row expandable to show its 9 fabs with live `on_hand` numbers. Click a part ID or a specific fab to insert it into your query and compose your own question.

During execution you will see a live 9-node panel animate through the graph as the agent runs. First cold call after a long idle is about 19 seconds. Warm calls land in 10 to 17 seconds, dominated by the Gemini Flash diagnose call.

## Architecture

```
                   ┌─────────────────────────────────────────┐
                   │   Frontend (Amplify, vanilla HTML/JS)   │
                   │   Dark "Fab Control Room" theme         │
                   └──────────────────┬──────────────────────┘
                                      │ HTTPS
                   ┌──────────────────▼──────────────────────┐
                   │   API Gateway HTTP API (30s cap)        │
                   └──────────────────┬──────────────────────┘
                                      │
                   ┌──────────────────▼──────────────────────┐
                   │   Runtime Lambda (Python 3.9, arm64)    │
                   │   1024 MB, 180s, 42 MB zip              │
                   │                                         │
                   │   LangGraph 9-node state machine:       │
                   │   entry -> check_policy_staleness       │
                   │         -> check_demand_drift           │
                   │         -> check_supply_drift           │
                   │         -> ground_in_disclosures        │
                   │         -> diagnose  (Gemini 2.5 Flash) │
                   │         -> prescribe_action  (rules)    │
                   │         -> verify -> finalize           │
                   └──────────┬──────────────────┬───────────┘
                              │                  │
              ┌───────────────▼──┐      ┌────────▼──────────┐
              │  Tool layer (7)  │      │  fabops_audit     │
              │  forecast_demand │      │  (DynamoDB spine) │
              │  get_inventory   │      │  per-node writes  │
              │  get_supplier_lt │      └───────────────────┘
              │  get_macro       │
              │  search_edgar    │
              │  compute_reorder │
              │  simulate_disrupt│
              └───────┬──────────┘
                      │
           ┌──────────▼────────────────────────────────┐
           │  DynamoDB (9 tables)                      │
           │  inventory, policies, forecasts,          │
           │  suppliers, incidents, macro_cache,       │
           │  edgar_index (1079 chunks, 3072-dim),     │
           │  audit, sessions                          │
           └──────────▲────────────────────────────────┘
                      │
           ┌──────────┴────────────────────────────────┐
           │  Nightly bake Lambda (container image)    │
           │  EventBridge cron 02:00 UTC               │
           │  Croston SBA via statsforecast            │
           │  sMAPE logged to MLflow SQLite            │
           └───────────────────────────────────────────┘

           ┌───────────────────────────────────────────┐
           │  Local stdio MCP server (Claude Desktop)  │
           │  scripts/mcp_server.py                    │
           │  Same 7 tool functions, no AWS required   │
           └───────────────────────────────────────────┘
```

Three deployment faces share one tool layer: the runtime zip Lambda (user-facing), the nightly container Lambda (forecast bake), and the local stdio MCP server (Claude Desktop). The DynamoDB `fabops_audit` table is the authoritative observability spine. Every node of every invocation lands there.

## Key engineering wins

### 1. The cold-start root cause hunt

The first version of the Lambda took 50 to 55 seconds to cold-start and returned HTTP 503 at the API Gateway edge because API Gateway caps out at 30 seconds. The easy fix was to throw money at provisioned concurrency. The correct fix was to find out why.

Profiling showed that the EDGAR chunk index (1,079 rows, each with a 3,072-dimensional Gemini embedding) was being pulled from DynamoDB on every cold init. That is roughly 43 seconds of the cold start, spent pulling the same immutable data over a network interface on every container spin-up. The fix: a one-time bake script (`scripts/prebake_edgar_chunks.py`) that serializes the full chunk index to a 17 MB gzipped JSON asset, ships it inside the Lambda zip, and loads it at module scope during Lambda's boosted-CPU init phase (which does not count against the API Gateway 30-second invocation clock).

Results: cold start dropped from 50 to 55 seconds to about 19 seconds. Cold API Gateway invocations went from HTTP 503 to HTTP 200. The Lambda zip grew from 25 MB to 42 MB, still well under the 50 MB direct-upload limit. Zero runtime change, zero extra cost. The lesson (called out in the commit message): fix the root cause, not the symptom.

### 2. Policy-first reasoning, not forecast-first

Most naive SCM agents jump straight to "recompute the forecast." That is the wrong move when the reorder policy itself is stale, because a fresh forecast against an old policy still produces the wrong reorder point. FabOps Copilot's first real check after entry is `check_policy_staleness`, which compares the policy's last-computed timestamp against the window of demand history it was built on. If the policy is stale, the agent short-circuits to a policy-drift diagnosis and prescribes a recompute before touching the forecast layer. This reflects how actual supply-chain planners reason, and it is the detail most portfolio agents miss.

### 3. Cross-family LLM-as-judge eval

Having an LLM grade its own family's output is a known failure mode. FabOps Copilot's eval harness (`scripts/run_judge.py`) runs the Gemini agent through the 18-case gold set, then hands each response to Claude Haiku 4.5 as an independent judge with a rubric that scores diagnosis correctness, action appropriateness, and citation grounding. The harness bypasses API Gateway by invoking the Lambda directly via boto3 (avoiding the 30-second cap on long cold starts during eval), caches judge responses in `evals/results/judge_cache.json`, and reports full cost transparency (latest run: $0.0354 total). The last run with Gemini 2.5 Pro for diagnose scored 15/18 = 83.3%.

### 4. Deterministic drift seeding

Portfolio agents often demo well on cherry-picked queries and fall apart in the general case. FabOps Copilot avoids this by seeding its own failure modes: `scripts/inject_gold_drift.py` deterministically injects 6 policy drift cases, 9 supply risk cases, and 3 demand shift cases into DynamoDB, then `scripts/regenerate_gold_set.py` rebuilds the gold set from the live DynamoDB state. The 18 drift cases visible in the frontend's "Browse parts" modal are not curated marketing examples. They are direct views into the real seeded corpus the agent is evaluated against.

### 5. One tool layer, two clients

The 7 tool functions live in `fabops/tools/` as plain Python. The runtime Lambda imports them directly. The stdio MCP server in `scripts/mcp_server.py` wraps the exact same functions as MCP tools for Claude Desktop. Changing a tool changes both clients. No duplication, no drift.

## Metrics

| Metric | Value | Notes |
|---|---|---|
| Gold-set pass rate | **15/18 (83.3%)** | Last Pro run. Gemini 2.5 Pro for diagnose, Claude Haiku 4.5 as judge. |
| Gold-set pass rate (current prod) | Untested, estimated 70 to 75% | Gemini 2.5 Flash. Tuned for demo latency. |
| Cold start latency | ~19 s | After the EDGAR prebake fix. Was 50 to 55 s. |
| Warm call latency | 10 to 17 s | Dominated by the Gemini Flash diagnose call. |
| Unit tests | 41/41 passing | `tests/` covers tools, nodes, state schema, handlers. |
| Lambda zip size | 42 MB | Includes 17 MB baked EDGAR chunks. |
| EDGAR corpus | 1,079 chunks | Real 10-K, 10-Q, 8-K from Applied Materials. |
| Embedding dimension | 3,072 | Google `gemini-embedding-001`. |
| Seeded inventory | 200 parts x 9 fabs = 1,800 rows | Subset of Hyndman carparts benchmark. |
| Forecast baseline | Croston SBA | Via `statsforecast`, sMAPE logged to MLflow. |
| Last judge-eval cost | $0.0354 | Full transparency logged in `evals/results/`. |
| DynamoDB tables | 9 | Including the `fabops_audit` observability spine. |

## Honest trade-offs

**Gemini Flash, not Pro, in production.** The diagnose node is wired to Gemini 2.5 Flash for demo latency. Pro scored 83.3% on the gold set; Flash is untested but likely lands at 70 to 75%. The flip is a single environment variable (`GEMINI_PRO_MODEL` in `fabops/config.py`). Production-grade accuracy would flip it back and accept the latency penalty.

**Langfuse observability was deferred.** The integration code is present (`fabops/observability/langfuse_shim.py`) and the v3 CallbackHandler pattern is wired in, but trace shipping from Lambda never stabilized, suspected SDK v3 vs v4 drift combined with Lambda flush timing. Rather than ship a flaky trace path, the DynamoDB `fabops_audit` table became the production source of truth for per-node observability. Langfuse is listed under Future Work in REPORT.md §10.

**Demo scope is 200 parts, not the full 2,674.** The Hyndman carparts benchmark has 2,674 parts. `scripts/populate_synthetic.py` deliberately slices to 200 to keep the nightly bake comfortably under the 900-second Lambda timeout and to keep the gold-set eval economical. Removing the `[:200]` slice and re-running would scale the corpus up; every other layer (tools, nodes, tables, frontend) is already parametric.

**MCP demo clip is pending.** The stdio MCP server runs locally today and is fully decoupled from AWS. A short recorded walkthrough against Claude Desktop is the one outstanding portfolio item.

**API Gateway 30-second cap is still there.** The cold-start fix brought cold invocations well under the cap, so the 503 failure mode no longer surfaces in practice. A true "first click after weeks of idle" edge case would still benefit from provisioned concurrency (about $11/month), which is the documented production-hardening step.

## Data provenance

| Source | Data | Real or synthetic | License / terms |
|---|---|---|---|
| Hyndman `carparts` | Intermittent-demand series, 2,674 parts x 51 months | Real | Public benchmark, bundled with the `expsmooth` R package. |
| SEC EDGAR | Applied Materials 10-K, 10-Q, 8-K filings | Real | Public domain (US federal filings). Retrieved via EDGAR full-text API. |
| FRED (St. Louis Fed) | `IPG3344S` (semiconductor IP index), `PCU33443344` (semiconductor PPI) | Real | Public domain. Cached in `fabops_macro_cache`. |
| Inventory snapshot | 200 parts x 9 fabs | Synthetic, seeded deterministically | Derived from carparts subset by `scripts/populate_synthetic.py`. |
| Supplier lead-time history | Multi-row history with `trend_30d` | Synthetic, seeded deterministically | Generated by `scripts/populate_synthetic.py`. |
| Reorder policies | 200 rows with staleness timestamps | Synthetic, drift injected deterministically | `scripts/inject_gold_drift.py`. |
| Gold eval set | 18 cases (6 / 9 / 3 by driver) | Rebuilt from live DDB state | `scripts/regenerate_gold_set.py`. |

## Quick start

**Local dev and tests**
```bash
git clone https://github.com/rroshann/fabops-copilot.git
cd fabops-copilot
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements-runtime.txt -r requirements-dev.txt
PYTHONPATH=$(pwd) .venv/bin/python -m pytest tests/ -q   # expect 41/41
```

Do not use system Python 3.14: the project uses pydantic v2 wheel constraints that break on it. Stick to 3.11 locally.

**Run the MCP server against Claude Desktop**
```bash
PYTHONPATH=$(pwd) .venv/bin/python scripts/mcp_server.py
```
Then add this block to `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "fabops": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["/absolute/path/to/scripts/mcp_server.py"],
      "env": {
        "PYTHONPATH": "/absolute/path/to/repo/root",
        "AWS_REGION": "us-east-1"
      }
    }
  }
}
```
Restart Claude Desktop and the 7 tools appear under the MCP menu. Ask: "Use fabops to check reorder policy status for part 10279876."

**Run the gold eval**
```bash
export ANTHROPIC_API_KEY=sk-ant-...
export FABOPS_API_URL=https://3ph4o9amg4.execute-api.us-east-1.amazonaws.com/getChatResponse
.venv/bin/python scripts/run_judge.py --set gold
```
Results land in `evals/results/` with a per-case breakdown, a total pass rate, and the full judge cost.

**Deploy the runtime Lambda**
```bash
bash scripts/deploy_runtime.sh
```
(Assumes AWS credentials with permissions for Lambda, S3, and the FabOps DynamoDB tables.)

## Stack

Python 3.11 local, Python 3.9 arm64 on Lambda, LangGraph, LangChain, Pydantic v2, Google Gemini 2.5 Flash + `gemini-embedding-001`, Anthropic Claude Haiku 4.5 (judge), `statsforecast` (Croston SBA), MLflow, DSPy, the official `mcp` Python SDK, `boto3`, AWS Lambda, API Gateway HTTP API, DynamoDB, S3, EventBridge, CloudWatch, AWS Amplify, vanilla HTML/CSS/JS with Inter and JetBrains Mono, GitHub Actions.

## Repo layout

```
fabops/
  agent/              LangGraph nodes, state schema, LLM wrappers, graph wiring
  tools/              7 tool functions + the baked EDGAR chunks asset
  handlers/           Lambda entry points (runtime zip + nightly container)
  observability/      AuditWriter, request_id, Langfuse shim
  data/               carparts loader, DynamoDB helpers
  config.py           Central env-var config
scripts/
  mcp_server.py             stdio MCP server (Claude Desktop)
  run_judge.py              Cross-family gold eval harness
  ingest_edgar.py           One-time SEC EDGAR ingest
  populate_synthetic.py     DynamoDB seed for 200 parts x 9 fabs
  inject_gold_drift.py      Inject deterministic 6 / 9 / 3 drift signals
  regenerate_gold_set.py    Rebuild gold set from live DDB state
  prebake_edgar_chunks.py   Bake EDGAR chunks into Lambda zip (cold-start fix)
  bake_catalog.py           18-part drift catalog for frontend browse modal
  bake_inventory.py         200-part full catalog for frontend
  deploy_runtime.sh         S3-mediated runtime Lambda deploy
  dspy_compile_planner.py   BootstrapFewShot compile
tests/                41 unit tests
evals/                gold_set.json, rubric.md, run results, judge cache
frontend/             Dark Fab Control Room SPA, no build step
infra/                CloudWatch dashboard, IAM policies, table provisioning
docs/superpowers/specs/   Design specs for the polish passes
REPORT.md             4,279-word technical report (10 sections)
```

## Course and application context

**DS 5730-01 Context-Augmented Gen AI Apps**, Vanderbilt University, Spring 2026. FabOps Copilot is the final project. The 10-section [REPORT.md](./REPORT.md) documents the methodology, the eval design, the cold-start investigation, the cross-family judge rationale, and an honest failure-modes section. Every claim in this README is cross-referenced there.

**Applied Materials JOLT Data Scientist (Agentic AI/ML) portfolio piece.** The problem domain (semiconductor fab service parts), the data sources (Applied Materials SEC filings, FRED semiconductor indices), and the reasoning structure (policy-first diagnosis over supply, demand, and macro signals) were chosen to demonstrate fit for the JOLT role's scope: building production agentic systems against real manufacturing operations data.

## Credits

Built by [Roshan Siddartha](https://github.com/rroshann).

Real data from Rob Hyndman's `carparts` benchmark (via `expsmooth`), the US SEC EDGAR system, and the Federal Reserve Bank of St. Louis (FRED). LLMs from Google (Gemini 2.5 Flash, `gemini-embedding-001`) and Anthropic (Claude Haiku 4.5 as independent judge). Agent framework: LangGraph. Forecasting: Nixtla's `statsforecast`. MCP layer: the official `mcp` Python SDK. Hosted on AWS.
