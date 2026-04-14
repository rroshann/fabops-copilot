# FabOps Copilot — Service-Parts Stockout Risk Agent

> An MCP-native agent that tells a material planner **when** a fab will stock out, **why**, and **what to do** — combining intermittent-demand forecasting, live inventory lookup, supplier lead-time modeling, SEC EDGAR disclosure search, and FRED macro signals into a policy-first LangGraph reasoning loop. Built in 11 days on AWS serverless.

![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.9%20Lambda-blue)
![AWS](https://img.shields.io/badge/AWS-Lambda%20%7C%20DynamoDB%20%7C%20S3%20%7C%20API%20Gateway-orange)
![Tests](https://img.shields.io/badge/tests-41%2F41%20passing-brightgreen)

**Live demo dashboard (HTTPS, Amplify Hosting + GitHub CI/CD):** https://main.d23s2e6xnypmh0.amplifyapp.com
**Live demo dashboard (HTTP, raw S3 static hosting — matches DS 5730 course tutorial):** http://fabops-copilot-frontend.s3-website-us-east-1.amazonaws.com
**Live API endpoint:** `https://3ph4o9amg4.execute-api.us-east-1.amazonaws.com/getChatResponse` *(evals invoke Lambda directly — API Gateway's 30s integration timeout fires on cold-start cases; see REPORT.md §5 for the gold run methodology)*
**Technical report:** [REPORT.md](REPORT.md)
**Claude Desktop MCP demo clip:** coming soon — see [REPORT.md](REPORT.md) §8 for the verified MCP handshake

---

## The problem in one paragraph

A material planner at a semiconductor fab is responsible for keeping hundreds of low-volume, intermittently demanded service parts in stock — spare turbopumps, quartz rings, e-chuck assemblies. Demand arrives in unpredictable spikes driven by equipment failures, not smooth consumption curves. Standard ERP reorder-point math (continuous demand, stable lead times) systematically under-forecasts these parts. Add a geopolitical disruption to a key supplier and the planner has no fast path to a root-cause answer: they are manually pivoting across an MRP system, an inventory spreadsheet, supplier emails, and SEC earnings call transcripts. FabOps Copilot closes that gap. A planner types a natural-language question — *"Why is part A7 about to stock out at the Taiwan fab, and what should I do?"* — and receives a structured diagnosis citing actual forecast numbers, current inventory levels, lead-time estimates, and relevant Applied Materials disclosures, followed by a concrete recommended action.

## What it does

**Input:** A natural-language query from a material planner, delivered via a browser dashboard, a direct API call, or Claude Desktop via MCP.

**Processing:** A 9-node LangGraph state machine routes the query through a policy-first reasoning loop. The `check_policy` node runs first to assess staleness of existing reorder parameters; only then does the agent call the forecaster and inventory tools. A `verify` node cross-checks the diagnosis against evidence returned by the tool layer. If confidence is insufficient, a `reflect` node rewrites the plan and retries (max 2 attempts, bounded by `MAX_GEMINI_PRO_CALLS=6`). Every node writes a structured row to `fabops_audit` (DynamoDB) so any run is reproducible from a single `request_id`.

**Output:** A root-cause analysis with a recommended action — for example, "Reorder point is stale (policy age 47 days vs. 30-day threshold). Current stock of 3 units covers 1.2 months at Croston SBA forecast of 2.5 units/month; supplier lead time is 8 weeks. Recommend immediate emergency order of 8 units and policy refresh." The response is grounded in tool evidence; every claim cites the tool call that supports it.

**Example question:** *"Part C12 — are we at risk? Supplier Kyocera recently had supply disruptions."*
The agent will call `get_inventory`, `forecast_demand`, `get_supplier_leadtime`, `simulate_supplier_disruption`, and `search_company_disclosures` in a policy-driven order, then synthesize a diagnosis with a citation-backed recommendation.

---

## Highlights

- **Real agentic loop** — 9-node LangGraph state machine with policy-first reasoning order (the SCM insight most students miss: check whether your reorder policy is stale *before* re-running the forecast)
- **7 tools** exposed both as in-agent LangGraph bindings AND as a separate stdio MCP server for Claude Desktop reuse — one tool layer, two clients
- **Cross-family LLM-as-judge** — Gemini Flash/Pro agent evaluated by Claude Haiku 4.5 to avoid correlated judge failure modes (see REPORT.md §7)
- **Real public data** — Hyndman `carparts` (2674 parts × 51 months), SEC EDGAR Applied Materials filings (10-K/10-Q/8-K), FRED macro series (IPG3344S, PCU33443344)
- **Calibrated intermittent demand** — Syntetos-Boylan-Croston ADI/CV² classification; 87% intermittent + 13% lumpy across the carparts corpus; Croston SBA selected as primary model; mean sMAPE 1.759 on n=200 held-out parts
- **Full MLOps spine** — Langfuse trace joining, MLflow model versioning (SQLite + S3), GitHub Actions eval CI gate, DSPy planner compilation
- **4 meaningful metrics** — forecast sMAPE 1.759, agent task-success **15/18 = 83.3%** on a real gold run (cross-family Claude Haiku 4.5 judge, $0.0354 cost), trajectory tool-selection accuracy 100% on passing runs, reflection retry path implemented and bounded (full methodology + per-class breakdown in REPORT.md §5)

---

## Architecture

```
  Browser / Claude Desktop
        |
        | HTTP POST / stdio MCP
        v
  ┌─────────────────────────────────────────────────────┐
  │              API Gateway (HTTP, CORS)                │
  └──────────────────────┬──────────────────────────────┘
                         │ Lambda invoke
                         v
  ┌─────────────────────────────────────────────────────┐
  │         fabops_agent_handler  (runtime Lambda)       │
  │         25 MB zip · Python 3.9 arm64                 │
  │                                                       │
  │  ┌──────────────────────────────────────────────┐   │
  │  │            LangGraph Agent (9 nodes)          │   │
  │  │                                               │   │
  │  │  entry → check_policy → diagnose → verify    │   │
  │  │       ↘ reflect ↗                            │   │
  │  │  route_intent → tool_dispatch → synthesize   │   │
  │  │       → audit_write → exit                   │   │
  │  └──────────────────────────────────────────────┘   │
  │                    │                                  │
  │         ┌──────────┼──────────┐                     │
  │         v          v          v                      │
  │    DynamoDB     Gemini      Langfuse                  │
  │  (inventory,   (Flash +     (trace +                 │
  │   forecasts,   Pro)         spans)                   │
  │   policies,                                          │
  │   audit)                                             │
  └─────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────┐
  │     nightly_forecast_bake  (container Lambda)        │
  │     ECR image · arm64 · cron 04:00 UTC               │
  │     statsforecast · Croston SBA · MLflow → S3        │
  └─────────────────────────────────────────────────────┘

  Tool layer (7 tools — shared by both faces)
  ┌───────────────┬──────────────────┬──────────────────┐
  │forecast_demand│get_inventory     │get_supplier_      │
  │               │                  │leadtime           │
  ├───────────────┼──────────────────┼──────────────────┤
  │get_industry_  │search_company_   │compute_reorder_   │
  │macro_signal   │disclosures       │policy             │
  ├───────────────┴──────────────────┴──────────────────┤
  │simulate_supplier_disruption                          │
  └──────────────────────────────────────────────────────┘
```

### Two deployment faces

1. **API face** — HTTPS POST to API Gateway → Lambda invoke → LangGraph agent → DynamoDB reads + Gemini calls → JSON response. Deployed; endpoint live at the URL above (pending `GEMINI_API_KEY` env var in Lambda console).
2. **MCP face** — local stdio server (`scripts/mcp_server.py`) → Claude Desktop tool calls → same 7 tool functions → same DynamoDB tables. AWS credentials required locally.

---

## Data

| Source | Size | Used for |
|---|---|---|
| Hyndman `carparts` (Zenodo [10.5281/zenodo.3994911](https://zenodo.org/records/3994911)) | 2674 parts × 51 months | Demand backbone for all forecasts |
| SEC EDGAR — Applied Materials (CIK 0000006951) | 10-K, 10-Q, 8-K filings | `search_company_disclosures` vector cosine search |
| FRED `IPG3344S` + `PCU33443344` | Monthly, 1972–present | `get_industry_macro_signal` |
| Synthetic overlays (seeded deterministic) | 1800 inventory rows, 20 suppliers, 100 incidents | DynamoDB dev/test data |

**Demand classification:** Syntetos-Boylan-Croston ADI/CV² framework applied to carparts. 87% of parts fall in the intermittent quadrant (ADI ≥ 1.32, CV² < 0.49); 13% lumpy. Croston SBA selected as primary model across both classes based on sMAPE on a held-out 200-part sample (horizon = 12 months).

**EDGAR ingest:** Run `scripts/ingest_edgar.py` once to populate the `fabops_disclosures` DynamoDB table. Requires `SEC_USER_AGENT` env var set to `"Your Name your@email.com"` per EDGAR fair-use policy.

---

## Quick start

### Prerequisites

- Python 3.11 locally (Lambda runs Python 3.9 arm64)
- Virtual environment: `python3.11 -m venv .venv && pip install -r requirements-runtime.txt -r requirements-dev.txt`
- AWS credentials with DynamoDB read on `us-east-1` (account 699475932108, or your own account after re-provisioning via `infra/`)

### Run the unit tests

```bash
PYTHONPATH=$(pwd) .venv/bin/python -m pytest tests/ -v
```

Expected: **41 passed**. Do not use system Python — the project uses pydantic v2 wheel constraints that break on 3.14.

### Launch the stdio MCP server locally

```bash
PYTHONPATH=$(pwd) .venv/bin/python scripts/mcp_server.py
```

The server registers all 7 tools over stdio and waits for JSON-RPC calls. Test it by running `scripts/smoke_audit.py` in a second terminal.

### Wire into Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

Restart Claude Desktop. The 7 FabOps tools will appear in the tool picker. Ask: *"Use fabops to check reorder policy status for part A7."*

### Run the gold eval harness

```bash
export FABOPS_API_URL=https://3ph4o9amg4.execute-api.us-east-1.amazonaws.com/getChatResponse
export ANTHROPIC_API_KEY=sk-ant-...
.venv/bin/python scripts/run_judge.py --set gold
```

The judge is Claude Haiku 4.5. Scores are written to `evals/results/`. See REPORT.md §5 for the rubric definition.

### DSPy planner compilation

```bash
export GOOGLE_API_KEY=...
.venv/bin/python scripts/dspy_compile_planner.py
```

Compiles the `PlannerModule` against the gold set and writes the optimized prompt weights to `fabops/agent/compiled_planner.json`.

---

## Metrics

| Metric | Value | Source |
|---|---|---|
| Forecast sMAPE mean | **1.759** | Nightly bake, n=200, horizon=12, `croston_sba` |
| Forecast sMAPE p50 | **1.819** | Nightly bake |
| Forecast sMAPE p90 | **2.000** | Nightly bake |
| Agent task-success on gold set | **15/18 = 83.3%** | `scripts/run_judge.py --set gold` (Claude Haiku 4.5 judge, $0.0354) |
| Per-class pass rate | policy 6/6, demand 3/3, supply 6/9 | Same run — supply is the hardest class |
| Trajectory tool-selection accuracy | **100%** on passing runs | Full 9-node sequence verified via `fabops_audit` spine |
| Reflection-triggered recovery rate | not triggered on gold run | Verify first-pass passed all 18; retry path exercised only when verify < 4 |

Full methodology, rubric definition, and nightly bake run log in [REPORT.md](REPORT.md) §5.

---

## Engineering rigor

Six production bugs were caught during the build by the three-layer subagent-driven TDD workflow (TDD-first implementer → spec reviewer → code-quality reviewer). Three worth noting:

- **AuditWriter step_n composite-key collision (Task 5.3):** The original `_audit` helper created a fresh `AuditWriter` instance per call, resetting `_step_n=0` each time. Every `log_step` write produced `step_n=1`, silently overwriting the prior row under the same `(request_id, step_n=1)` DynamoDB composite key. The audit table appeared functional — no errors — while producing a one-row trace for every multi-step run. Fix: sync `writer._step_n = state.step_n` before calling `log_step`, then increment `state.step_n` in the returned state.

- **Lambda cold-start numpy import leak (Task 6.3):** `search_disclosures.py` and `forecast_demand.py` had top-level `import numpy` statements. Harmless locally, these transitively pulled numpy into the zipped runtime Lambda, causing `ModuleNotFoundError: No module named 'numpy'` on cold start. Fix: lazy imports inside function bodies. The correct pattern for any Lambda that deliberately excludes a heavy dependency from its packaging manifest is to never import it at module level.

- **MLflow `./mlruns` read-only filesystem on Lambda (Task 9.2):** MLflow defaults to writing the tracking DB to `./mlruns` relative to the working directory, which is read-only inside a Lambda execution environment. Fix: upload the SQLite tracking DB to S3 after each nightly bake run and set `MLFLOW_TRACKING_URI` to the S3 path.

See REPORT.md §6.4 for the full list of six bugs and the methodology note.

---

## Stack

Python 3.11 (local) / 3.9 arm64 (Lambda) · AWS Lambda · DynamoDB · S3 · API Gateway · CloudWatch · ECR · LangGraph · Google Gemini Flash + Pro · Claude Haiku 4.5 (judge) · Langfuse · MLflow · DSPy · statsforecast (Croston SBA) · pydantic v2

---

## Repo layout

```
fabops/               Core package
  agent/              LangGraph nodes, state schema, LLM wrappers, graph wiring
  tools/              7 tool functions with ToolResult contracts
  handlers/           Lambda entry points (runtime zip + nightly container)
  observability/      AuditWriter, request_id, Langfuse shim, CloudWatch metrics
  data/               carparts loader, synthetic overlays, DynamoDB helpers
  config.py           Central env-var config (no hardcoded secrets)
scripts/
  mcp_server.py       stdio MCP server — Claude Desktop integration
  run_judge.py        Cross-family eval harness (Claude Haiku 4.5 judge)
  dspy_compile_planner.py  DSPy optimization for PlannerModule
  ingest_edgar.py     One-time SEC EDGAR ingest → DynamoDB
  populate_synthetic.py   Seed DynamoDB with deterministic synthetic data
  stress_cold_start.py    Cold-start latency measurement (see REPORT.md §6.3)
  smoke_audit.py      End-to-end smoke test against live Lambda
tests/                41 unit tests (pytest)
  test_agent/         LangGraph node tests
  test_data/          carparts loader + DynamoDB helper tests
  test_evals/         Judge rubric + gold-set parsing tests
  test_tools/         All 7 tool function tests
evals/
  rubric.md           Versioned 3-dimension rubric (correctness, citation, action)
  gold_set.json       10 gold queries with expected tool sequences
frontend/
  index.html          Single-page planner dashboard
  app.js / styles.css Vanilla JS/CSS — no build step
infra/
  cloudwatch_dashboard.json   FabOpsCopilot CloudWatch dashboard definition
  iam_policies/               Least-privilege Lambda execution role policies
  create_tables.py            DynamoDB table provisioning script
docs/
  superpowers/specs/  Design spec
  superpowers/plans/  11-day implementation plan
  superpowers/handoffs/ Day-end state snapshots
Dockerfile.nightly    Container image for nightly_forecast_bake Lambda
REPORT.md             4279-word technical report (10 sections)
```

---

## Course and application context

Final project for **DS 5730-01 Context-Augmented Gen AI Apps** (Spring 2026, Vanderbilt University).

Also a portfolio submission for the **Applied Materials JOLT Data Scientist — Agentic AI/ML** role.

---

## Submission checklist

- [ ] Public GitHub repo link works: https://github.com/rroshann/fabops-copilot
- [ ] Live dashboard URL responds: http://fabops-copilot-frontend.s3-website-us-east-1.amazonaws.com
- [ ] API endpoint responds to a curl request (requires `GEMINI_API_KEY` env var set in Lambda console)
- [ ] `REPORT.md` committed and readable (4279 words, 10 sections)
- [ ] All 4 metrics have numbers in the report (metrics 2–4 require running `scripts/run_judge.py --set gold`)
- [ ] Demo video link works (Claude Desktop MCP clip — coming soon)
- [ ] Langfuse trace screenshot included in REPORT.md §6.1
- [ ] DSPy before/after delta documented (run `scripts/dspy_compile_planner.py` and record improvement)
- [ ] CI eval gate run visible on GitHub Actions tab
- [ ] Course submission form filled out

---

## Credits

- **Rob J. Hyndman** — `carparts` intermittent-demand benchmark dataset (Zenodo DOI [10.5281/zenodo.3994911](https://zenodo.org/records/3994911))
- **Syntetos, Boylan, Croston** — ADI/CV² intermittent-demand classification framework and Croston SBA forecasting method
- **SEC EDGAR** — public company filings database (Applied Materials CIK 0000006951)
- **Federal Reserve Economic Data (FRED)** — public macroeconomic time series (St. Louis Fed)
- **AWS, LangGraph, Anthropic, Google** — serverless infrastructure and LLM platform
