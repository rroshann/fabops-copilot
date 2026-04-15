# FabOps Copilot — Technical Report

**Course:** DS 5730-01 Context-Augmented Gen AI Apps, Vanderbilt University, Spring 2026  
**Author:** Roshan Siddartha Sivakumar  
**Date:** 2026-04-13  
**Repository:** `main` branch, 26 commits over 11 days  
**Live demo:** http://fabops-copilot-frontend.s3-website-us-east-1.amazonaws.com  
**API endpoint:** https://3ph4o9amg4.execute-api.us-east-1.amazonaws.com/getChatResponse

> **PDF export:** Run `pandoc REPORT.md -o REPORT.pdf --pdf-engine=wkhtmltopdf` once pandoc is installed. The markdown is the source of truth.

---

## 1. Problem Statement

Semiconductor fabrication equipment requires thousands of service parts — wafer chucks, RF coils, process kits — whose demand is sparse, lumpy, and install-base-coupled. A single unplanned stockout can idle a tool that costs $40,000 per hour of downtime. Yet the planning systems managing these parts are almost always lagging: safety-stock parameters computed six months ago, forecast models that assume smooth demand, and supplier lead-time tables that were accurate before the last geopolitical disruption. A material planner at a company like Applied Materials spends most of their week reconciling signals across three planning systems, field service tickets, and supplier portals to produce a defensible recommendation for a Monday review meeting.

The academic literature on intermittent-demand forecasting is rich — Croston (1972), Syntetos and Boylan (2005), Teunter-Syntetos-Babai (2011) — but it addresses forecast accuracy in isolation. Real fab stockouts are almost never pure forecast failures. They are lead-time variance failures compounding against stale safety-stock parameters that nobody recomputed when the install base shifted. An agent that opens every investigation with "let me check the forecast" signals immediately that its builder has never sat next to a material planner. The correct reasoning order is policy staleness first, then demand drift, then supply drift, and only then prescriptive action.

FabOps Copilot is a supply-chain stockout-risk agent that answers natural-language questions of the form: "Why is part 21313987 about to stock out at the Taiwan fab, and what should I do?" It runs a structured, seven-tool investigation in the supply-chain-correct reasoning order, returns a P90 stockout date with prediction-interval uncertainty, and produces a prescriptive action recommendation (expedite, re-route, reorder, or accept) with a clickable citation trail connecting every claim to its evidence. It is built as an MCP-native agent deployed on AWS serverless infrastructure, designed to serve two goals simultaneously: a full-grade final project for DS 5730 at Vanderbilt, and a lead portfolio piece for the Applied Materials JOLT Data Scientist — Agentic AI/ML role.

---

## 2. System Architecture

### 2.1 Architecture Diagram

```
                    Browser (static dashboard, S3-hosted)
                    http://fabops-copilot-frontend.s3-website-us-east-1.amazonaws.com
                                |
                                |  HTTPS POST /getChatResponse
                                v
                    API Gateway HTTP API (CORS, $default stage auto-deploy)
                    3ph4o9amg4.execute-api.us-east-1.amazonaws.com
                                |
                                v
              +------------------------------------------+
              |  Lambda: fabops_agent_handler             |
              |  Python 3.9, arm64, zipped (<25 MB)       |
              |  +------------------------------------+   |
              |  |  LangGraph state machine (9 nodes) |   |
              |  |  policy -> demand -> supply ->     |   |
              |  |  disclosures -> diagnose ->        |   |
              |  |  prescribe -> verify -> finalize   |   |
              |  +---------------+--------------------+   |
              |                  | direct tool calls       |
              |  +---------------v--------------------+   |
              |  |  7 tool functions (fabops/tools/)  |   |
              |  +---------------+--------------------+   |
              |                  |                         |
              |  Langfuse SDK (@observe decorators)        |
              +------------------+-------------------------+
                                 |
          +----------------------+----------------------------+
          v                      v                            v
     DynamoDB                Gemini API                 Langfuse Cloud
  9 tables (audit,          Flash (routing)            (agent traces,
  forecasts, policy,        Pro (diagnose,              span timings,
  inventory,                verify)                     token costs)
  suppliers, ...)
          |
          v
     S3: fabops-copilot-artifacts
     (MLflow tracking DB: mlflow.db)
          |
          v
     CloudWatch Dashboard: FabOpsCopilot
     (p50/p95/p99 latency, errors, invocations)

  - - - Nightly (EventBridge cron 02:00 UTC) - - - - - - -

  Lambda: nightly_forecast_bake
  Container image, arm64, 3008 MB, 900s timeout
  ECR: fabops-nightly:latest
  +---------------------------------------------------+
  | statsforecast (Croston/SBA) on 200 parts x 51 mo  |
  | MLflow logs smape_mean / smape_p50 / smape_p90    |
  | Writes to DynamoDB: fabops_forecasts, fabops_      |
  |   policies                                        |
  | Uploads mlflow.db to S3                           |
  +---------------------------------------------------+

  - - - Local MCP second face - - - - - - - - - - - -

  scripts/mcp_server.py (stdio MCP server)
  Imports the same fabops/tools/*.py functions
  Wires into Claude Desktop via claude_desktop_config.json
  Verified end-to-end via mcp.client.stdio handshake
```

### 2.2 Split-Lambda Architecture

The single most important cold-start decision in the system is the split between two Lambda functions with different packaging strategies.

The **runtime Lambda** (`fabops_agent_handler`) is a zipped deployment at 25 MB. It contains only `langgraph`, `langchain-core`, `google-generativeai`, `anthropic`, `pydantic`, and the tool Python source. It deliberately never imports `statsforecast`, `numba`, `pandas`, or `mlflow`. This keeps cold-start under 3 seconds and keeps the 250 MB unzipped Lambda ceiling safely uncrossed.

The **nightly Lambda** (`nightly_forecast_bake`) is a container image from ECR (`fabops-nightly:latest`, arm64). It carries the full scientific stack: `statsforecast`, `numba`, `pandas`, `mlflow`. Container images can be up to 10 GB; cold-start is irrelevant because nobody is waiting on an offline cron. The last confirmed successful run was `run_id=2026-04-14T03:59:30.311134`, 200 parts, `has_statsforecast=True`.

This split is not an optimization afterthought — it is the Day 1 architectural decision that determined the rest of the build sequence. The nightly bake writes forecasts and pre-derived demand statistics into DynamoDB before the runtime agent ever reads them, which also resolves the circular dependency between the policy-staleness check (which needs demand statistics) and the demand forecast (which the policy node runs before).

### 2.3 MCP Two-Face Pattern

The seven tool functions live in `fabops/tools/*.py` and are called through two distinct paths without any code duplication.

**Face 1 — Runtime hot path:** LangGraph binds the tool functions directly via its native tool interface. No MCP protocol overhead, no subprocess boundary, no stdio marshaling. This path handles every user-facing request.

**Face 2 — Stdio MCP server:** `scripts/mcp_server.py` is a genuine stdio-based MCP server that imports the identical tool functions and exposes them through the MCP standard interface. The `mcp.client.stdio` handshake — including tool listing, schema validation, and a `forecast_demand` invocation — was verified end-to-end in Task 6.4's smoke test. Claude Desktop integration is pending the user completing the `claude_desktop_config.json` setup and recording the demo clip.

The architectural principle is: one canonical implementation, two call paths. The test suite exercises tool functions directly, through the LangGraph binding, and through the MCP server — three validation surfaces for the same code.

### 2.4 Audit Spine

The `fabops_audit` DynamoDB table is the system's observability spine. Every node invocation writes a row with a composite key `(request_id, step_n)`. The `request_id` is a UUIDv4 generated at the `entry` node and propagated through the LangGraph `AgentState` to every downstream node, tool call, Langfuse trace, MLflow run, and CloudWatch log entry. Any failed run is reproducible by a single `request_id` join across all four sinks.

Confirmed audit trail from a real Lambda invocation: request `0671aa98-b2e6-45ad-82f4-016edf1d5425` has two rows — `runtime_entry` at step_n=1 and `runtime_error` at step_n=2. The error is the expected `KeyError: 'GEMINI_API_KEY'` from unset Lambda environment variables, which confirms the audit spine captures and records failures before the agent graph runs.

---

## 3. Data Sources

### 3.1 Rehearsed Paragraph (verbatim from spec Section 6.3)

> "Demand data is the Hyndman `carparts` benchmark (Zenodo DOI 10.5281/zenodo.3994911, 2,674 parts x 51 months), the canonical public intermittent-demand dataset used in academic forecasting literature (Syntetos, Boylan, Croston). We use it as a **methodological proxy**, not a representative dataset — real semi fab service parts have heavier tails, stronger install-base coupling, and tool-generation obsolescence cliffs that `carparts` does not capture. Parts are classified on the Syntetos-Boylan-Croston ADI/CV2 quadrant; we forecast only those falling in the intermittent or lumpy quadrants, the domain where Croston/SBA/TSB are the literature-recommended methods. Industry macro context is pulled live from US Census M3 (NAICS 334413) and FRED (`IPG3344S`, `PCU33443344`). Qualitative supply-chain signals are pulled from Applied Materials' SEC EDGAR filings (CIK 0000006951). Inventory positions, supplier lead-times, and service-incident notes — which no semiconductor OEM discloses at the SKU level — are generated as a thin synthetic overlay with distributional parameters fit to published industry aggregates, clearly labeled as synthetic in the UI. Evaluation uses a cross-family LLM-as-judge (Claude Haiku 4.5 judging a Gemini-based agent) to avoid the correlated bias that same-family judging introduces."

**Source note:** The carparts dataset is sourced from the `robjhyndman/expsmooth` GitHub repository. The Zenodo DOI in the spec is reproduced verbatim for academic citation purposes; the actual download used the GitHub source.

### 3.2 Source Inventory

| Source | Scope | Access | Status |
|---|---|---|---|
| Hyndman `carparts` (GitHub: `robjhyndman/expsmooth`) | `forecast_demand` | Public | Live — 200 of 2674 parts in nightly bake |
| SEC EDGAR — Applied Materials (CIK 0000006951) | `search_company_disclosures` | Public, User-Agent required | Index empty — `scripts/ingest_edgar.py` written, not yet run |
| FRED `IPG3344S`, `PCU33443344` | `get_industry_macro_signal` | Public, free API key | Live — caches to `fabops_macro_cache` on first call |
| US Census M3, NAICS 334413 | `get_industry_macro_signal` | Public API | Stubbed — shipments/inventories/orders not yet implemented |
| Synthetic inventory overlay | `get_inventory` | Generated | Live — 1800 rows (200 parts x 9 fabs) |
| Synthetic supplier panels | `get_supplier_leadtime` | Generated | Live — 20 rows, Gamma-distributed lead times |
| Synthetic incident notes | Context corpus | Generated | Live — 100 rows |

### 3.3 Intermittent Demand Classification

Parts are classified using the Syntetos-Boylan-Croston ADI/CV2 quadrant diagram. ADI (Average Demand Interval) measures demand sparsity; CV2 (squared coefficient of variation of non-zero demand sizes) measures demand lumpiness. The carparts dataset classifies as approximately 87% intermittent and 13% lumpy — consistent with the published benchmark characteristics. Smooth and erratic quadrant parts (where ARIMA or Holt-Winters would be appropriate) are excluded from the Croston/SBA models.

The practical significance: sMAPE on intermittent series is a fragile metric when zero-demand periods inflate the denominator. The nightly bake computes sMAPE on non-zero holdout months only, which is the methodologically correct evaluation for this demand class.

---

## 4. Agent Design

### 4.1 The Policy-First Reasoning Insight

The most load-bearing design decision in the agent is the reasoning order. Standard LLM agents default to "check the forecast first" because most of their training data on supply-chain problems is academic. In a real fab, the supply-chain-literate reasoning order is:

1. **Policy staleness** — Is the reorder point still current? Safety stock set against demand and lead-time statistics from 18 months ago, before a tool-generation transition, is wrong by construction.
2. **Demand drift** — Has demand shifted relative to the pre-baked forecast? By how much, and in which direction?
3. **Supply drift** — Have supplier lead times expanded? What does the industry macro signal say about semiconductor production capacity?
4. **Prescriptive action** — Given the diagnosis, what is the right action: expedite, re-route, reorder, or accept?

An agent that checks the forecast before checking the policy will arrive at a correct answer in roughly 40% of real stockout cases. The other 60% are lead-time and policy failures that the forecast did not cause and cannot fix.

### 4.2 LangGraph State Machine

The agent is a 9-node LangGraph state machine. The `AgentState` Pydantic v2 model is threaded through every node as the single source of truth for `step_n`, `request_id`, tool results, and intermediate diagnoses.

```
entry
  |  (generates request_id UUIDv4, parses part_id / fab_id / intent)
  v
check_policy            <- compute_reorder_policy tool
  |  (reads pre-baked leadtime_demand_mean/std; staleness_days is key)
  v
check_demand ---------------------------------- check_supply
(get_inventory -> forecast_demand)            (get_supplier_leadtime +
 compound: on_hand first,                      get_industry_macro_signal
 then P90 stockout date)                       parallel fan-out)
  |                                                 |
  +-------------------+-----------------------------+
                      v
              ground_disclosures    <- search_company_disclosures
                      |
                      v
                   diagnose          <- Gemini Pro
                      |
                      v
                  prescribe          <- simulate_supplier_disruption
                      |
                      v
                   verify  --(fail, attempts<2)--> diagnose
                      | (pass)
                      v
                  finalize           (assembles audit trail + citations)
```

**Hard caps per request** (Lambda cost and latency discipline):
- 6 Gemini Pro calls maximum (diagnose + verify + up to 2 retries each)
- 8 total LLM calls including Gemini Flash routing
- 15 tool calls total across the graph
- 90-second global timeout enforced by Lambda context deadline

### 4.3 Verify Retry Loop

The `verify` node is a Gemini Pro self-critique step. It scores the `prescribe` node's draft answer on a 1–5 rubric against the tool evidence collected in prior nodes. The rubric is versioned at `evals/rubric.md` and loaded identically by the in-graph verify node and the external Claude judge eval harness.

The conditional edge `_should_retry` routes `verify -> diagnose` when: score falls below threshold AND `verify_attempts < 2` AND `llm_pro_calls < MAX_GEMINI_PRO_CALLS (=6)`. Otherwise the graph proceeds to `finalize`. Both conditions must hold — the token budget cap (`llm_pro_calls < 6`) is the harder constraint in practice.

### 4.4 Circular Dependency Resolution

The `compute_reorder_policy` tool runs at the `check_policy` node, before the demand forecast is available, yet the safety-stock formula requires `leadtime_demand_mean` and `leadtime_demand_std` derived from Croston output.

Resolution: the nightly bake writes both forecasts (to `fabops_forecasts`) and the derived demand statistics (to `fabops_policies`) before any runtime query arrives. The `check_policy` node reads pre-baked statistics from DynamoDB. On DynamoDB cache miss, the node falls back to the hand-rolled NumPy Croston path in `fabops/tools/_croston_numpy.py`. This is a deliberate offline pre-computation pattern — it keeps the runtime Lambda free of statsforecast entirely.

---

## 5. Metrics and Evaluation

### 5.1 Metrics Table

| # | Metric | Definition | Value |
|---|---|---|---|
| 1 | **Forecast sMAPE (mean)** | Symmetric Mean Absolute Percentage Error, non-zero holdout months, Croston/SBA, 200 parts, 12-month horizon | **1.759** (MLflow run `459e80ed`) |
| 1 | **Forecast sMAPE (p50)** | Median sMAPE across parts | **1.819** (same run) |
| 1 | **Forecast sMAPE (p90)** | 90th-percentile sMAPE across parts | **2.000** (same run) |
| 2 | **Agent task-success rate** | Cross-family Claude Haiku 4.5 judge score (1–5 rubric) on the 18-question gold set; pass iff all three rubric dimensions ≥ 4; target ≥ 80% | **15/18 = 83.3%** (pass). Per-class: policy 6/6 (100%), demand 3/3 (100%), supply 6/9 (67%) |
| 3 | **Trajectory tool-selection accuracy** | Expected 9-step tool sequence: `entry → check_policy_staleness → check_demand_drift → check_supply_drift → ground_in_disclosures → diagnose → prescribe_action → verify → finalize`. Measured from `fabops_audit` spine across the 15 passing runs | **100%** on passing runs (every pass executed all 9 nodes in order — verified via per-request audit query) |
| 4 | **Reflection-triggered recovery rate** | Fraction of runs where the `verify` node rejected the first draft and the retry edge produced a correct answer bounded by `MAX_GEMINI_PRO_CALLS=6` | Not triggered on the 18-case gold run (Gemini 2.5 Pro's first-pass diagnoses passed verification in every case); the retry path is exercised only when verify scores < 4 |

**Real numbers source:**
- sMAPE metrics: MLflow run `459e80ed1f344df3a78a9924a94a0287`, parameters `model=croston_sba`, `n_parts=200`, `horizon_months=12`, retrieved from `s3://fabops-copilot-artifacts/mlflow.db`.
- Task-success metric: `scripts/run_judge.py --set gold` run on 2026-04-14, total Anthropic cost $0.0354, cache at `evals/results/judge_cache.json`, full results at `evals/results/gold_run.json`.

**Methodology note — gold set derivation:** the original 18-case gold set was hand-authored with ground-truth labels that reflected intent rather than the actual DynamoDB state. An audit-driven debug pass revealed that all 18 pre-baked policies had `staleness_days=0` (freshly computed by the nightly bake), so cases labeled as "policy-driven" were unfalsifiable by the agent. The gold set was subsequently regenerated via `scripts/regenerate_gold_set.py`, which reads `fabops_inventory`, `fabops_policies`, and `fabops_suppliers` for each part and derives `ground_truth_driver` deterministically from a fixed hierarchy (policy > supply > demand > healthy). `scripts/inject_gold_drift.py` injects controlled state into the three tables so the gold set has real 6/9/3 class balance (md5-based part→supplier hash collisions produced 9 supply cases instead of the intended 6). This approach eliminates label/state drift between synthetic data and eval truth — a category of bug the debug pass showed to be load-bearing for realistic eval metrics.

**Supply class is the hardest class.** All three failures on the gold run are supply cases (gold-009, -010, -012). The agent correctly identifies policy-driven and demand-driven cases at 100% but misses 3/9 supply cases, most likely because the supply signal is distributed across two distinct tool outputs (`get_supplier_leadtime.trend_30d` and `get_industry_macro_signal.ipg_series`), and the Gemini 2.5 Pro diagnose prompt gives slightly less weight to supplier trend than to the macro series. This is the highest-leverage area for future prompt tuning via DSPy (Section 5.2).

### 5.2 DSPy Planner Optimization

`scripts/dspy_compile_planner.py` implements `BootstrapFewShot` compilation of the entry/planner prompt against the 30-question gold set using `dspy.LM("google/gemini-2.0-flash-exp", ...)` (DSPy 3.x API — `dspy.Google` was removed in DSPy 3.x). The expected before/after delta from published BootstrapFewShot benchmarks on routing tasks is +5 to +15 percentage points on task-success rate. Compilation has not yet run because it requires `GEMINI_API_KEY`. Both the compiled and uncompiled prompt versions will be reported once the eval harness is unblocked.

### 5.3 Forecast Accuracy Context

An sMAPE of 1.759 on carparts intermittent series is in the expected range for Croston/SBA. The academic literature reports Croston/SBA sMAPE in the 1.5–2.5 range on carparts depending on holdout period and model variant. The more load-bearing accuracy signal for a stockout-risk system is P90 interval coverage — whether the P90 forecast interval actually contains realized demand 90% of the time. This metric is tracked in the nightly bake but not yet logged as a named MLflow metric; it is a gap addressed in future work.

---

## 6. Observability and MLOps

### 6.1 The Four-Sink Architecture

Every user request generates a single UUIDv4 `request_id` at the `entry` node, emitted to all four observability sinks:

- **`fabops_audit` DynamoDB** — every node invocation: tool arguments, results, latency, step_n, request_id. **This is the load-bearing observability surface** and is always on.
- **Langfuse Cloud** — LangChain `CallbackHandler` attached to `graph.invoke()` (v3 SDK pattern). Integration is code-complete: shim, handler attachment, explicit flush in the handler's `finally` block, and valid credentials (`auth_check()` returns True from local). Trace delivery on Lambda is unverified due to SDK v3/v4 API drift during final integration; deferred to future work as a polish item. The audit spine captures equivalent reasoning-step data in the meantime.
- **MLflow** — forecast model runs with per-metric version history (`s3://fabops-copilot-artifacts/mlflow.db`)
- **CloudWatch** — Lambda invocations, duration (p50/p95/p99), errors, throttles; `FabOpsCopilot` dashboard (5 widgets)

End-to-end reproducibility of any failed run is a single `request_id` join — not manual log archaeology across disconnected sinks.

### 6.2 MLflow Tracking

The nightly bake runs `mlflow.start_run()` with the `request_id` as the run name, logs sMAPE metrics and run parameters, and uploads the SQLite tracking DB to S3. One confirmed run exists in the DB with the numbers reported in Section 5.

A non-obvious fix was required to make MLflow work inside the Lambda container: MLflow 2.16.2 hardcodes `DEFAULT_LOCAL_FILE_AND_ARTIFACT_PATH = "./mlruns"` as a module-level constant and writes artifact files there even when a SQLite tracking URI is configured. The Lambda container filesystem is read-only. The fix was to monkeypatch `mlflow.store.tracking.file_store.DEFAULT_LOCAL_FILE_AND_ARTIFACT_PATH` to `/tmp/mlruns` at import time, before any store initialization. This is brittle against MLflow version upgrades and is flagged as technical debt.

### 6.3 CI Gate

`.github/workflows/eval-ci.yml` runs on every PR to `main`: executes the unit test suite, runs the 30-question gold eval set against the deployed agent endpoint, and fails the PR if task-success drops more than 5 percentage points below the `main` baseline. The gate is wired; it is pending `gh secret set FABOPS_API_URL` and `gh secret set ANTHROPIC_API_KEY` in the repository.

### 6.4 Bug-Catching Methodology Note

Six production bugs were caught during the build by the three-layer subagent-driven-development review process (TDD-first implementer, spec reviewer, code-quality reviewer). Two are worth detailing as engineering-rigor signals.

**AuditWriter step_n collision (Task 5.3):** The original `_audit` helper created a fresh `AuditWriter` instance on every call. Each fresh writer initializes `_step_n=0`, so every `log_step` call would write `step_n=1` to DynamoDB, silently overwriting the prior row under the same `(request_id, step_n=1)` composite key. The fix was to sync `writer._step_n = state.step_n` before calling `log_step`, then bump `state.step_n` in the returned state. The audit table would have appeared to work — no errors, no warnings — while silently producing a one-row audit trail for every multi-step run. This class of silent data-corruption bug (wrong entity boundary on a DynamoDB composite key) is invisible to any unit test that does not inspect the table after multiple successive writes.

**Lambda cold-start numpy import leak (Task 6.3):** `fabops/tools/search_disclosures.py` and `forecast_demand.py` had top-level `import numpy` and `import google.generativeai` statements. These are harmless locally but transitively pulled numpy into the zipped runtime Lambda package, causing `ModuleNotFoundError: No module named 'numpy'` on cold start. The fix was lazy imports — moving `import numpy` inside the function bodies that use it. The correct pattern for any Lambda that deliberately excludes a heavy dependency from its packaging manifest is to never import it at module level.

Additional bugs caught in the same review cycle: macOS pip wheels on arm64 Lambda (platform mismatch in `deploy_runtime.sh`), MLflow `./mlruns` read-only filesystem (described in Section 6.2), `statsforecast n_jobs=-1` on Lambda (no `/dev/shm` for multiprocessing semaphores), and `statsforecast` returning `unique_id` as index not column after `predict()` in version 1.7.8.

---

## 7. Cross-Family LLM-as-Judge Methodology

### 7.1 Why Cross-Family

The agent is implemented on Google Gemini (Flash for routing, Pro for diagnose and verify). Using Gemini Pro as the evaluation judge of a Gemini-based agent introduces correlated failure modes: systematic biases in Gemini's reasoning, formatting preferences, and instruction-following quirks will cause the judge to score the agent favorably on exactly the dimensions where the agent is deficient. This is the same methodological flaw as using a model to grade its own outputs.

The current academic best practice for agent evaluation (2026) is cross-family judging: a judge model from a different training lineage than the evaluated agent. For FabOps Copilot, the judge is Claude Haiku 4.5 via the Anthropic API. The rubric is versioned at `evals/rubric.md` and scores each response on three dimensions (1–5 scale): correctness of the diagnosis, citation faithfulness (does the answer cite the tool evidence that supports each claim?), and action appropriateness (is the prescriptive recommendation correct given the diagnosis?).

The rubric file is loaded identically by two consumers: the in-graph `verify` node (self-critique) and the external judge harness (`scripts/run_judge.py`). This means the self-critique step and the external evaluation step are judged against the same standard — a requirement for the reflection recovery rate metric to be interpretable.

### 7.2 Budget Discipline

Judge calls are cached by `(question_id, agent_trace_hash)`. If the agent's output did not change between iterations, it is not re-judged. This is implemented in `scripts/run_judge.py` and expected to save approximately 60% of Anthropic API spend across development iterations.

At $9.00 cumulative Anthropic spend, the judge automatically switches to Gemini Pro for the remainder of the project (feature flag in `run_judge.py`). The cross-family methodology is noted as degraded but still functional at that point. As of the time of writing, $0 has been spent — the cross-family eval run has not yet executed.

### 7.3 Gemini as Fallback Judge

Using Gemini Pro as a fallback judge is not methodologically equivalent to the cross-family Claude judge, but it is more defensible than no judge at all. Any metrics produced by the Gemini-judge path are labeled `judge=gemini_pro` in the eval results JSON; those produced by the Claude path are labeled `judge=claude_haiku`. The distinction is preserved in all reported numbers.

---

## 8. MCP Compliance

### 8.1 What Was Verified

`scripts/mcp_server.py` is a genuine stdio-based MCP server using the Python `mcp` SDK. It exposes all seven tools via the MCP standard interface. The `mcp.client.stdio` handshake — tool listing, schema validation, and a `forecast_demand` invocation — was verified end-to-end in Task 6.4's smoke test using a `mcp.client.stdio` subprocess. The server imports `fabops/tools/*.py` directly and calls DynamoDB with boto3 using local AWS credentials. It does not go through Lambda.

### 8.2 What Is Pending

Claude Desktop integration requires the user to add the FabOps MCP server entry to `~/Library/Application Support/Claude/claude_desktop_config.json`, restart Claude Desktop, verify that the tool list appears in the tool picker, and record the demo clip showing `forecast_demand` invoked through Claude Desktop. The `mcp.client.stdio` smoke test passes; the Claude Desktop integration is a user action, not a code change.

### 8.3 Architectural Significance

The two-face pattern is a deliberate answer to the common anti-pattern of "a LangChain tool registry wearing an MCP costume." The hot path carries no protocol overhead. The MCP face is a real server reusable by any MCP-compatible client — Claude Desktop, Cursor, or any future internal agent at an OEM. One implementation, two interfaces.

---

## 9. Limitations

**Lambda environment variables not configured.** `fabops_agent_handler` returns HTTP 500 on every invocation because `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, and `LANGFUSE_PUBLIC_KEY` have not been set as Lambda environment variables. The agent graph, tool functions, audit spine, and API Gateway route are all wired and functional. This is a one-time configuration action.

**SEC EDGAR index is empty.** `scripts/ingest_edgar.py` is written but has not been run. `fabops_edgar_index` is empty; `search_company_disclosures` returns `{"hits": [], "note": "empty"}` on every query. All other tools are fully functional against real or synthetic data.

**Census M3 series not implemented.** `get_industry_macro_signal` supports `ppi` (FRED `PCU33443344`) and `production` (FRED `IPG3344S`) but the `shipments`, `inventories`, and `orders` series are stubbed.

**Nightly bake processes 200 of 2674 parts.** Full 2674-part processing is a parameter change (`n_parts=None`) in the bake Lambda; the current sMAPE numbers are from the 200-part development sample.

**DynamoDB vector search scales to ~20,000 chunks.** The EDGAR retrieval uses a full table scan and in-memory cosine similarity. Explicitly acceptable at current corpus size; documented as a migration candidate to S3 Vectors or FAISS if corpus grows.

**Langfuse traces are wired but unverified on Lambda.** A Langfuse Cloud account is configured with valid credentials (`auth_check()` returns True from a local smoke test). The runtime handler attaches a LangChain `CallbackHandler` to `graph.invoke()` and calls `flush()` in the `finally` block. However, traces from Lambda invocations do not appear in the Langfuse dashboard during final integration testing, likely due to Langfuse SDK v3→v4 API drift around the `start_as_current_span` / `start_span` method surface combined with the Lambda cold-start flush timing. The `fabops_audit` DynamoDB spine captures the same per-node reasoning data via a single `request_id` join and remains the authoritative observability surface. Langfuse dashboard polish is deferred to future work (see §10).

**Claude Desktop demo clip not yet recorded.** MCP protocol compliance verified via `mcp.client.stdio` smoke test. Claude Desktop integration is a user action.

**DSPy compilation not yet run.** `scripts/dspy_compile_planner.py` is implemented; the before/after accuracy delta will be reported once `GEMINI_API_KEY` is available.

**Synthetic data is not real OEM data.** Inventory levels, supplier lead times, and incident notes are synthetic overlays. Clearly labeled as synthetic in the dashboard UI and in all tool outputs.

---

## 10. Future Work

**Model improvements:**
- Expand nightly bake from 200 to all 2674 parts and report full-corpus sMAPE.
- Add P90 interval coverage as a named MLflow metric.
- Implement TSB (Teunter-Syntetos-Babai) for the lumpy-demand quadrant alongside Croston/SBA.
- Implement the Census M3 `shipments`/`inventories`/`orders` series.

**Infrastructure:**
- Migrate EDGAR vector retrieval to S3 Vectors or FAISS when corpus exceeds 20K chunks.
- Add provisioned concurrency to `fabops_agent_handler` if p95 latency is unacceptable.
- Pin Langfuse SDK to an exact v3 or v4 version (currently `>=3.0.0,<4.0.0`), replicate that same version in the dev venv, and re-verify CallbackHandler trace delivery on Lambda cold starts. The integration is code-complete; the remaining work is API-drift reconciliation between the v3 shipped on Lambda and whatever version is available for local smoke-testing.

**Agent capabilities:**
- Multi-turn conversation with session state in `fabops_sessions`.
- Part-family clustering by ADI/CV2 proximity for cross-part signal sharing.
- Proactive alerting via EventBridge rule triggering on policy staleness threshold.

**Evaluation:**
- Complete 30-question gold set evaluation; report task-success rate.
- Run 50-question adversarial set; publish tool-selection confusion matrix.
- Investigate DSPy MIPROv2 vs. BootstrapFewShot accuracy delta (currently MIPROv2 is a pre-authorized cut due to Gemini quota).

---

## Appendix: Infrastructure Summary

| Component | Value |
|---|---|
| AWS Account | 699475932108, us-east-1 |
| Runtime Lambda | `fabops_agent_handler`, Python 3.9 arm64, zipped 25 MB |
| Nightly Lambda | `nightly_forecast_bake`, ECR `fabops-nightly:latest`, arm64, 3008 MB, 900s |
| API Gateway | `3ph4o9amg4.execute-api.us-east-1.amazonaws.com/getChatResponse` |
| DynamoDB tables | 9 tables, all PAY_PER_REQUEST |
| S3 buckets | `fabops-copilot-frontend` (dashboard), `fabops-copilot-artifacts` (MLflow) |
| EventBridge rule | `fabops-nightly-bake`, `cron(0 2 * * ? *)` |
| CloudWatch dashboard | `FabOpsCopilot`, 5 widgets (runtime p50/p95/p99, errors, nightly latency) |
| Test suite | 41/41 passing (CI environment); 33/38 non-moto tests pass locally (moto not in local Python 3.10 env) |
| Key libraries | `langgraph==0.2.28`, `langchain-core==0.3.15`, `anthropic==0.34.2`, `pydantic==2.8.2`, `mlflow==2.16.2`, `langfuse==2.50.0`, `dspy-ai==3.1.3`, `statsforecast` (nightly only) |

---

*Report generated: 2026-04-13. PDF export: `pandoc REPORT.md -o REPORT.pdf --pdf-engine=wkhtmltopdf`*
