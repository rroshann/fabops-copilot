# FabOps Copilot — Design Spec

**Date:** 2026-04-13
**Status:** Design locked, pending implementation plan
**Course:** DS 5730-01 Context-Augmented Gen AI Apps, Vanderbilt University, Spring 2026
**Author:** Roshan Siddartha Sivakumar

---

## 1. Product

**Name:** FabOps Copilot
**Subtitle:** Service-Parts Stockout Risk Agent
**Tagline:** *An MCP-native agent that tells a material planner **when** a fab will stock out, **why**, and **what to do** — with trajectory-level evals, DSPy-compiled planning, and calibrated intermittent-demand forecasts. Built in 11 days on AWS serverless.*

### 1.1 Product vision

A Material Planner working a semiconductor fab opens a dashboard and asks a natural-language question like *"Why is wafer-chuck part A7 about to stock out at the Taiwan fab, and what should I do?"* An agent decomposes the question into a structured investigation, runs that investigation across seven tools in the correct supply-chain reasoning order (policy → demand → supply → action), returns a **P90 stockout date** with a clickable audit trail citing every piece of evidence, and recommends a prescriptive action (expedite, re-route, reorder, accept).

### 1.2 Dual strategic goal

1. **Full grade on DS 5730 final project.** Meets every requirement: real agentic component, deployed public web app, observability, ≥2 metrics, public GitHub, technical report.
2. **Lead portfolio piece for Applied Materials' JOLT Data Scientist — Agentic AI/ML role.** Every design choice maximizes recognition by a semiconductor-OEM supply-chain hiring manager in April 2026.

---

## 2. Users and scope

### 2.1 Primary persona: the Material Planner

A supply-chain professional on a team like Applied Materials' JOLT (Joint Operations Leadership). Their daily pain is not forecasting accuracy; it is **reconciling conflicting signals across planning systems, field tickets, and spreadsheets so they can defend a decision in a Monday review meeting**. Their moat requirement is **auditability and explainability**, not model sophistication. Every recommendation must cite its sources.

### 2.2 In scope

- Natural-language query entry
- Automatic reasoning-order triage: policy staleness → demand drift → supply drift → action
- Seven domain tools exposed as an MCP server
- P90 stockout-date forecasting with prediction intervals (not point forecasts)
- Clickable audit trail of every tool call and every citation
- A scenario / what-if supplier-disruption tool
- Observability dashboard with four quantitative metrics

### 2.3 Out of scope

- Real-time SAP/Oracle integration (out of scope for a student project)
- Multi-agent orchestration (single-agent, single-graph)
- Fine-tuning Gemini (using it off the shelf via function calling + LangGraph)
- Authentication / user management (public demo, session is UUID only)
- Mobile-responsive design (desktop dashboard only)
- Anything beyond semiconductor service parts

---

## 3. System architecture

### 3.1 High-level diagram

```
                    Browser (static dashboard, S3-hosted)
                                │
                                │  HTTPS (POST /getChatResponse)
                                ▼
                         API Gateway (HTTP, CORS)
                                │
                                ▼
                  Lambda: fabops_agent_handler (Python 3.9, arm64)
                                │
                ┌───────────────┼───────────────────────────┐
                │               │                           │
                ▼               ▼                           ▼
          LangGraph         MCP client             Langfuse SDK
        agent runtime   (in-process tools)      (traces, evals)
                │               │
                ▼               ▼
         Gemini API       Tool implementations
                                │
            ┌───────────────────┼───────────────┬────────────────┐
            ▼                   ▼               ▼                ▼
       DynamoDB           S3 (assets,       SEC EDGAR      Census M3 / FRED
    (cached forecasts,   artifacts,         (public API)    (public APIs)
    sessions, audit,     MLflow store)
    vector index)
                                                            │
                                                            ▼
                                                      CloudWatch
                                               (metrics, logs, dashboard)

        ┌────────────────── Nightly (EventBridge cron) ──────────────────┐
        │                                                                │
        ▼                                                                ▼
  Lambda: nightly_forecast_bake                              Lambda: nightly_eval_run
  (runs statsforecast on all parts,                          (runs 30-gold eval harness,
  writes P90 tables to DynamoDB)                             emits Langfuse dataset run)
```

### 3.2 Key architecture decisions

| Decision | Choice | Rationale |
|---|---|---|
| Frontend hosting | S3 static site | Matches course tutorial pattern; zero backend overhead |
| API layer | API Gateway HTTP (not REST) | Cheaper, simpler CORS, matches tutorial |
| Compute | Lambda Python 3.9 arm64 | Course layer provides `langchain-core` + `google-generativeai`; arm64 is tutorial default |
| LLM | Google Gemini (Flash for routing, Pro for final synthesis) | Course default; free tier; already layer-provisioned |
| Agent framework | **LangGraph** on top of `langchain-core` | Explicit state-graph renders well in technical report; 2026-current; builds on course layer |
| Tool protocol | **Direct LangGraph tool binding + separate tested stdio MCP server as a second face of the same tool functions** | Low-risk runtime (no protocol overhead in the hot path); real, demoable MCP via a genuinely tested stdio server used live inside Claude Desktop in the demo video. Real 2026 signal without cold-start tax. |
| Runtime Lambda packaging | **Zipped** (<50MB), slim: `langgraph` + `langchain-core` + `google-generativeai` + `anthropic` + Pydantic + MCP client only | Keeps cold-start minimal; no `statsforecast` / `pandas` / `numba` / MLflow at runtime |
| Nightly Lambda packaging | **Container image** (up to 10 GB), holds the heavy scientific stack: `statsforecast` + `numba` + `pandas` + MLflow | Solves the 250 MB unzipped ceiling cleanly; cold-start doesn't matter (offline cron) |
| State store | DynamoDB | Tutorial-native; single-digit-ms access; session + cached forecasts + **audit spine** |
| Vector store | Pre-computed Gemini embeddings in DynamoDB; **full-scan + in-memory cosine at runtime, explicitly acceptable at N < 20,000 chunks** | Honest about the constraint; migrates to S3 Vectors / FAISS if corpus grows |
| Observability | Langfuse Cloud (free) + CloudWatch + shared `request_id` UUIDv4 joining every sink | Langfuse for agent traces; MLflow for model metrics; CloudWatch for infra; **one request_id joins all four** |
| Model tracking | MLflow (SQLite backend on S3) | Versioned Croston/SBA/TSB runs, per-SKU sMAPE/MASE |
| CI | GitHub Actions eval harness | Fails PR if agent task-success drops >5pp vs `main` |

---

## 4. The agent graph

### 4.1 Reasoning-order insight (load-bearing)

Per the Supply Chain Strategist red-team: **real fab service-parts stockouts are almost never forecast failures. They are lead-time variance failures compounding against stale safety-stock parameters nobody recomputed.** If the agent defaults to "the forecast was wrong," a real planner knows immediately that the builder has never sat next to one. The graph must check **policy → demand → supply → action** in that order.

### 4.2 LangGraph state machine

Nodes:

| Node | Type | Calls | Purpose |
|---|---|---|---|
| `entry` | router | — | Parse query, extract `part_id` / `fab_id` / intent; **generate `request_id` UUIDv4 used by every downstream sink** (Langfuse, MLflow, CloudWatch, `fabops_audit`); init state |
| `check_policy_staleness` | tool | `compute_reorder_policy` | Is the reorder policy current? When was it last recomputed vs. install-base changes? Reads pre-baked `leadtime_demand_mean/std` from `fabops_policies`; **does not** recompute live. |
| `check_demand_drift` | tool (compound) | `get_inventory` → `forecast_demand` | First reads current `on_hand` via `get_inventory(part_id, fab_id)`, then calls `forecast_demand` with that `on_hand` to compute the P90 stockout date. Returns residuals vs. prior forecast. |
| `check_supply_drift` | tool (parallel fan-out) | `get_supplier_leadtime`, `get_industry_macro_signal` | Lead-time variance + industry-level signals |
| `ground_in_disclosures` | tool | `search_company_disclosures` | Any public AM filing context relevant to this part / fab / timeframe |
| `diagnose` | LLM reflection | Gemini Pro | Synthesize: is the primary driver policy, demand, or supply? Assign a confidence. |
| `prescribe_action` | tool (conditional) | `simulate_supplier_disruption` | If supply-driven: run what-if; if policy-driven: recommend policy refresh; if demand-driven: recommend reorder |
| `verify` | LLM judge | Gemini Pro | Score draft answer (1–5) against tool evidence via Pydantic-validated rubric; bounded retry (max 2) |
| `finalize` | formatter | — | Assemble user-facing response with audit trail and citations |

Edges (simplified):

```
entry
  ↓
check_policy_staleness
  ↓
[check_demand_drift  ‖  check_supply_drift]   (parallel, asyncio.gather)
  ↓
ground_in_disclosures
  ↓
diagnose ────┐
  ↓          │
prescribe_action
  ↓
verify ──(fail, retry ≤2)──▶ diagnose
  ↓ (pass)
finalize
```

**Hard caps per request** to bound Lambda cost and latency:
- **≤6 Gemini Pro calls** (diagnose + verify + up to 2 retries of each)
- **≤8 total LLM calls** including cheap Gemini Flash routing
- **≤15 tool calls** total across the graph
- **Global timeout: 90 seconds**, enforced by Lambda context deadline

### 4.3 Agenticness properties

The graph clears the April-2026 bar because it has:

1. **Domain-grounded dynamic routing** (policy-first reasoning order)
2. **Parallel tool fan-out** on supply + demand checks
3. **Structured output validation with bounded retry** (Pydantic + max 2 retries at every tool-call node)
4. **Self-critique loop** (`verify` node as Gemini-as-judge) with a stopping criterion
5. **Citation-grounded final answer** tied to tool evidence

---

## 5. Tool specifications

All seven tools are exposed as a single **MCP server** running in-process inside the Lambda. The LangGraph agent consumes them as MCP clients. This lets the same tool server be mounted by Claude Desktop, Cursor, or any future internal agent without modification — a platform-thinking signal a JOLT hiring manager will recognize.

### 5.1 `forecast_demand`

- **Inputs:** `part_id: str`, `horizon_months: int = 12`, `service_level: float = 0.95`, `on_hand: Optional[int]`
- **Output schema (Pydantic):** `{forecast: List[float], p10: List[float], p90: List[float], p90_stockout_date: Optional[date], stockout_date_uncertainty_days: Optional[int], model: Literal["croston", "sba", "tsb"], sMAPE: float, MASE: float}`
- **Definition of `p90_stockout_date`:** the earliest date at which cumulative demand at the **90th percentile** of the forecast distribution exceeds `on_hand` inventory. This is a conservative early-warning estimate — the date a planner should target for replenishment to maintain a 90% no-stockout service level. `stockout_date_uncertainty_days` is the width of the 10th-to-90th percentile window around that date.
- **Data:** Hyndman `carparts` benchmark (2,674 × 51 months)
- **Implementation:** `statsforecast` Croston / SBA / TSB with prediction intervals, running **inside the container-image `nightly_forecast_bake` Lambda**; writes to `fabops_forecasts` and `fabops_policies`. Runtime (zipped) Lambda never imports `statsforecast`; it only reads cached results from DynamoDB. Fallback hand-rolled Croston in NumPy if wheel fails on arm64.
- **Note:** the **P90 prediction interval** is load-bearing — this is the "shibboleth" that separates us from students using ARIMA on lumpy series

### 5.2 `get_inventory`

- **Inputs:** `part_id: str`, `fab_id: str`
- **Output schema:** `{on_hand: int, in_transit: int, reserved: int, available: int, as_of: datetime, fab_id: str, part_id: str}`
- **Data:** synthetic overlay (no public source exists for SKU-level semi inventory; explicitly labeled synthetic in the UI)
- **Site list (`fab_id` dimension):** Real locations pulled from Applied Materials' public disclosures. Includes both AM's own manufacturing / service sites (e.g., Santa Clara, Austin, Gloucester, Dresden, Singapore) and named major customer fab regions (e.g., "Taiwan", "Arizona") where AM-serviced equipment is deployed. `fab_id` is a slight simplification — in the real world, parts flow from an AM site to a customer fab — but for the demo a single-dimension site identifier is sufficient.

### 5.3 `get_supplier_leadtime`

- **Inputs:** `supplier_id: str` or `part_id: str`
- **Output schema:** `{supplier_id: str, mean_leadtime_days: float, std_leadtime_days: float, last_observed_shipment: date, trend_30d: Literal["improving", "stable", "degrading"]}`
- **Data:** synthetic, distributional parameters seeded from industry aggregates

### 5.4 `search_company_disclosures`

- **Inputs:** `query: str`, `top_k: int = 5`, `date_from: Optional[date]`
- **Output schema:** `{hits: List[{filing_type, filing_date, excerpt, relevance, sec_url}]}`
- **Data:** real — SEC EDGAR, Applied Materials CIK `0000006951`, 10-K / 10-Q / 8-K from last 3 years, chunked + embedded with Gemini embeddings, stored in DynamoDB
- **Ingest is Day-0 pre-work, not runtime or nightly.** A one-shot `scripts/ingest_edgar.py` script runs locally before day 1, batch-downloads filings (with the SEC `User-Agent` header), chunks at ~500 tokens, embeds via Gemini with exponential backoff, writes chunks to `fabops_edgar_index` DynamoDB + a mirror JSON snapshot to S3. Runtime tool only queries the pre-built index — no live EDGAR calls.
- **Runtime retrieval:** full-scan + in-memory cosine at Lambda (see Section 3.2). Expected corpus ~5K–20K chunks. If it ever exceeds 20K, migrate to S3 Vectors.
- **SEC User-Agent:** every HTTP call to EDGAR sets `User-Agent: FabOps Copilot (student project, contact: <email>)` per SEC fair-access policy.

### 5.5 `get_industry_macro_signal`

- **Inputs:** `month: date`, `series: Literal["shipments", "inventories", "orders", "ppi", "production"]`
- **Output schema:** `{series: str, value: float, mom_change: float, yoy_change: float, source_url: str}`
- **Data:** real — US Census M3 API (NAICS 334413) + FRED series `IPG3344S`, `PCU33443344`
- **Implementation:** direct HTTP calls with 1-hour cache in DynamoDB

### 5.6 `compute_reorder_policy` *(added per SCM strategist)*

- **Inputs:** `part_id: str`, `service_level: float = 0.95`, `lead_time_days: Optional[float]`
- **Output schema:** `{reorder_point: float, safety_stock: float, order_up_to: float, service_level: float, z_score: float, leadtime_demand_mean: float, leadtime_demand_std: float, last_updated: datetime, staleness_days: int}`
- **Implementation:** classical OR. Safety stock = z(α) × σ_DLT where σ_DLT derived from Croston-adjusted demand variance and lead-time variance. `staleness_days` is the critical flag the policy-first reasoning node uses.
- **Circular-dependency resolution:** The policy node runs *before* the demand node, but the policy calculation needs `leadtime_demand_mean/std` which are derived from Croston output. **Resolution: the nightly bake writes both — forecasts to `fabops_forecasts` AND the derived demand stats into `fabops_policies.leadtime_demand_mean/std`. Runtime `compute_reorder_policy` reads the pre-baked stats; no live Croston call during agent execution.** On cache miss (rare), falls back to the NumPy Croston path.
- **Signal value:** this tool is pure operations-research proof. A JOLT reviewer sees it and knows the builder has actually studied inventory theory.

### 5.7 `simulate_supplier_disruption` *(added per SCM strategist)*

- **Inputs:** `supplier_id: str`, `delay_days: int`, `part_id: str`
- **Output schema:** `{baseline_stockout_date: date, disrupted_stockout_date: date, expedite_cost: float, accept_cost: float, recommended_action: Literal["expedite", "accept", "reroute"], policy_used: Literal["(s,S)", "newsvendor"]}`
- **Implementation:** re-runs the (s,S) or newsvendor expedite decision under a shocked lead time. Prescriptive, not diagnostic.

---

## 6. Data sources (final)

### 6.1 Real public sources

| Source | Powers | Licensing | Access |
|---|---|---|---|
| Hyndman `carparts` (Zenodo DOI [10.5281/zenodo.3994911](https://zenodo.org/records/3994911)) | `forecast_demand` | Open per Zenodo record metadata (verify on download) | Direct CSV download |
| SEC EDGAR — Applied Materials (CIK 0000006951) | `search_company_disclosures` | Public domain | `data.sec.gov/submissions/CIK0000006951.json` + full-text search; `User-Agent` header required |
| US Census M3 (NAICS 334413) | `get_industry_macro_signal` | Public domain | `api.census.gov/data/timeseries/eits/m3` |
| FRED (`IPG3344S`, `PCU33443344`) | `get_industry_macro_signal` | Public domain | `api.stlouisfed.org/fred/series/observations` (free API key) |
| Applied Materials public fab list | `fab_id` dimension | Public | Scraped once from AM corporate site, committed as static JSON |

### 6.2 Synthetic overlay (only where no public data exists)

| Synthetic layer | Why synthetic | Generation method |
|---|---|---|
| Per-part inventory levels per fab | No semi OEM discloses SKU inventory | Sampled from (s,S) policy around each part's long-run demand rate |
| Per-supplier lead-time panels | Same | Gamma-distributed around industry-typical means, seeded from published benchmarks |
| Service-incident notes corpus (~100 tickets) | Privately held | LLM-generated from realistic fab-ops templates |

### 6.3 Framing in the technical report (rehearsed paragraph)

> *"Demand data is the Hyndman `carparts` benchmark (Zenodo DOI 10.5281/zenodo.3994911, 2,674 parts × 51 months), the canonical public intermittent-demand dataset used in academic forecasting literature (Syntetos, Boylan, Croston). We use it as a **methodological proxy**, not a representative dataset — real semi fab service parts have heavier tails, stronger install-base coupling, and tool-generation obsolescence cliffs that `carparts` does not capture. Parts are classified on the Syntetos-Boylan-Croston ADI/CV² quadrant; we forecast only those falling in the intermittent or lumpy quadrants, the domain where Croston/SBA/TSB are the literature-recommended methods. Industry macro context is pulled live from US Census M3 (NAICS 334413) and FRED (`IPG3344S`, `PCU33443344`). Qualitative supply-chain signals are pulled from Applied Materials' SEC EDGAR filings (CIK 0000006951). Inventory positions, supplier lead-times, and service-incident notes — which no semiconductor OEM discloses at the SKU level — are generated as a thin synthetic overlay with distributional parameters fit to published industry aggregates, clearly labeled as synthetic in the UI. Evaluation uses a cross-family LLM-as-judge (Claude Haiku 4.5 judging a Gemini-based agent) to avoid the correlated bias that same-family judging introduces."*

---

## 7. Storage schema

### 7.1 DynamoDB tables

**The load-bearing table is `fabops_audit`. Build it on day 1, before the agent exists, with a working write helper and a fake-tool-call smoke test. Every other component (Langfuse traces, MLflow model runs, CloudWatch, CI eval harness, the audit-trail-led UI, the technical report, the demo video) joins against it via the shared `request_id` UUIDv4. Treat this table as the system's spine, not a side effect.**

| Table | Partition key | Sort key | Contents |
|---|---|---|---|
| **`fabops_audit`** ⭐ (spine) | `request_id` | `step_n` | Full agent audit trail: every tool call, arguments, result, latency, token cost, `request_id` joining Langfuse / MLflow / CloudWatch |
| `fabops_sessions` | `session_id` | `message_ts` | Conversation turns, user queries, final responses |
| `fabops_forecasts` | `part_id` | `forecast_run_id` | Nightly-baked P90 tables per part, per model, with run metadata. Written via `BatchWriteItem` with exponential backoff and jitter to avoid partition hot-spotting. |
| `fabops_policies` | `part_id` | — | Latest `compute_reorder_policy` output **including pre-baked `leadtime_demand_mean` / `leadtime_demand_std`** (resolves the policy/demand circular dep) and `last_updated` for staleness logic |
| `fabops_inventory` | `part_id` | `fab_id` | Synthetic inventory state |
| `fabops_suppliers` | `supplier_id` | `observed_date` | Synthetic supplier lead-time panels |
| `fabops_edgar_index` | `doc_id` | `chunk_id` | SEC filing chunks + pre-computed Gemini embeddings (**Day-0 pre-work, not runtime**) |
| `fabops_incidents` | `incident_id` | — | Synthetic service-incident notes + embeddings |
| `fabops_macro_cache` | `series_id` | `month` | Census M3 + FRED responses, 1-hour TTL |

### 7.2 S3 buckets

- `fabops-copilot-frontend` — static dashboard HTML/JS/CSS
- `fabops-copilot-artifacts` — MLflow tracking store (SQLite + artifact dir), Zenodo raw data, synthetic overlay seeds
- `fabops-copilot-evals` — 30-question gold set, 200-question synthetic adversarial set, per-run eval results

---

## 8. MCP server layer

### 8.1 Why MCP

Per the expert panel, exposing the seven tools via a real Model Context Protocol server is the **single strongest April-2026 signal** that separates this agent from a 2024-style ReAct loop. It also lets the same tool set be reused by Claude Desktop, Cursor, or any future internal agent — a platform-thinking cue a JOLT hiring manager will recognize immediately.

### 8.2 Implementation — two faces of the same tool functions

After the Software Architect red-team, the spec deliberately separates runtime execution from MCP protocol compliance to avoid "a LangChain tool registry wearing an MCP costume":

- **Face 1 — Runtime hot path (LangGraph inside Lambda):** LangGraph calls the seven tool Python functions **directly** via its native tool-binding interface. No MCP protocol, no stdio subprocess, no cold-start tax. This is the path every user request traverses.
- **Face 2 — Real stdio MCP server (`scripts/mcp_server.py`):** A genuine stdio-based MCP server that imports the exact same tool functions and exposes them via the MCP standard interface. **This server is tested end-to-end by running it inside Claude Desktop** as part of the final deliverable. A 30-second clip of Claude Desktop invoking `forecast_demand` through this MCP server is recorded in the demo video. That clip is the proof that the MCP story is real, not cosmetic.
- **One canonical tool implementation, two call paths.** Both faces import from `fabops/tools/*.py`. The test suite exercises each tool function directly, through the LangGraph binding, and through the stdio MCP server, so all three paths are validated.
- **Why not `langchain-mcp-adapters`?** Running LangGraph as an MCP client across a process boundary would add cold-start surface and debug complexity for zero functional gain — LangGraph is already inside the Lambda. The two-face pattern delivers the MCP signal honestly without the runtime tax.

### 8.3 Tool contract (shared base)

Every tool follows this contract:

```python
class ToolResult(BaseModel):
    ok: bool
    data: Optional[dict]
    error: Optional[str]
    citations: List[Citation]  # clickable trail
    latency_ms: float
    cached: bool
```

On validation failure, the LangGraph node routes back to the planner with the error; bounded retry cap of 2.

---

## 9. Cold-start mitigation (load-bearing decision, day 1)

### 9.1 The risk

Per the AI Engineer red-team: `statsforecast` + `numba` cold-starts on arm64 Lambda add 20–40 seconds to first-invocation latency. The p95 latency metric — the headline observability number on the resume dashboard — would be dominated by cold starts, not agent reasoning.

### 9.2 Mitigation stack

1. **Split deployment: two Lambdas, two packaging strategies.**
   - **Runtime agent Lambda** (`fabops_agent_handler`): **zipped**, <50MB target. Contains only `langgraph` + `langchain-core` + `google-generativeai` + `anthropic` + Pydantic + MCP client + tool Python code. **Never imports `statsforecast`, `numba`, `pandas`, or MLflow.**
   - **Nightly bake Lambda** (`nightly_forecast_bake`): **container image**, up to 10 GB. Holds the full scientific stack: `statsforecast` + `numba` + `pandas` + MLflow + `boto3`. EventBridge cron, one run per day. Cold-start irrelevant because nobody is waiting. Solves the 250 MB unzipped ceiling cleanly.
2. **Nightly pre-compute writes both forecasts and derived demand stats** into `fabops_forecasts` and `fabops_policies` respectively, so the runtime policy node never has to call `statsforecast` live.
3. **Provisioned concurrency: NOT used** (architect's pre-authorized cut). Saves ~$3 and ~30 min of setup. The split-packaging strategy alone keeps runtime cold-start acceptable.
4. **Fallback:** if `statsforecast` arm64 wheels break during container build, hand-rolled Croston in pure NumPy (~30 lines). No `numba`, no cold-start cost even in the nightly Lambda.
5. **Runtime Lambda deadline:** 90-second global timeout enforced by Lambda context deadline; agent aborts gracefully and emits an audit record on exceed.

### 9.3 Day-1 decision

Build the nightly pre-compute pipeline first, before writing the runtime agent. This is a deliberate decision to avoid the day-9 panic pattern where cold starts emerge as a problem right before the demo.

---

## 10. Observability and MLOps

### 10.1 The MLOps story (what the JD asks for verbatim)

> *"MLOps, including model deployment, versioning and performance monitoring in production environments"*

We satisfy this with four concrete artifacts, joined by a shared `request_id`:

**Shared `request_id` (load-bearing):** Every user request generates a single UUIDv4 `request_id` at the `entry` node. That same value is emitted to **all four observability sinks** — Langfuse traces, MLflow runs, CloudWatch logs, and the `fabops_audit` DynamoDB spine. End-to-end reproducibility of any failed run is a single join on `request_id`, not manual log archaeology. Without this discipline, the four sinks degrade into disconnected silos.

### 10.2 Langfuse (agent tracing) — non-negotiable

- **Langfuse Cloud free tier** (decided; no infra overhead; traces sit on langfuse.com and are linked to eval runs)
- One decorator per LangGraph node automatically captures: trace, span, tool call, token count, cost, latency
- Every agent run is linked to its eval result — the closed loop the red-team flagged as the 2026 signal
- Free tier monthly event cap (~50K events) is expected to be sufficient; if a batch eval run would blow the cap we throttle evals rather than pay for Langfuse

### 10.3 MLflow (forecast model versioning)

- SQLite tracking backend stored in S3 (`fabops-copilot-artifacts/mlflow.db`)
- Every nightly forecast run logs: model type (Croston / SBA / TSB), per-SKU sMAPE and MASE, P90 coverage, run timestamp, seed
- This is the exact artifact the JD's "versioning and performance monitoring" line asks for

### 10.4 GitHub Actions eval harness (CI gate)

- On every PR to `main`: run the 30-question gold eval set
- Compare agent task-success rate to `main` baseline
- **Fail the PR if task-success drops >5 percentage points**
- This single CI file is what makes the resume bullet honest — it's not a claim, it's a gate

### 10.5 DSPy planner optimization

- Compile the planner prompt against the 30-question gold set using **DSPy `BootstrapFewShot`** (architect's pre-authorized cut — MIPROv2 is too Gemini-quota-hungry for a solo 11-day build)
- Report before/after accuracy delta in the technical report (expected: +5 to +15pp)
- Signal: "I treat prompts as artifacts, not vibes"

### 10.6 CloudWatch dashboard

Secondary, but present. Panels:

- p50 / p95 / p99 latency per agent run
- Tool call distribution (which tools get used most)
- Error rate
- Cold-start rate
- Daily Gemini token cost
- Daily forecast sMAPE (from nightly bake)

---

## 11. Metrics (4 total)

| # | Metric | Definition | Target |
|---|---|---|---|
| 1 | **Demand forecast accuracy** | sMAPE and MASE vs. seasonal-naive baseline on held-out part-months; P90 interval coverage | MASE <1.0 on intermittent/lumpy quadrant; P90 coverage within ±5pp of nominal |
| 2 | **Agent task-success rate** | Cross-family Claude Haiku 4.5 judge score on 30-question gold set (hand-authored, hand-labeled) + 50-question synthetic adversarial set (machine-generated, used for confusion matrix) | ≥80% on gold; adversarial set reports raw accuracy + confusion matrix (no preset target) |
| 3 | **Trajectory tool-selection accuracy** | Per-step: did the agent pick the correct tool given the state? Scored against labeled trajectories. Confusion matrix over tool choices. | ≥85% correct-tool-at-step |
| 4 | **Reflection-triggered recovery rate** | Fraction of runs where the `verify` node caught a wrong draft answer and the retry produced a correct one | Report actual rate (no preset target; this demonstrates the self-correction loop works) |

---

## 12. Evaluation harness

### 12.1 Gold set (30 questions, hand-authored)

- 10 "policy-driven" stockout cases (stale safety-stock is the real cause)
- 10 "demand-driven" stockout cases (forecast drift is the real cause)
- 10 "supply-driven" stockout cases (supplier lead-time expansion is the real cause)
- Each has: question, ground-truth diagnosis, ground-truth recommended action, expected tool call sequence, acceptable answer rubric

### 12.2 Synthetic adversarial set (50 questions, generated)

- Generated by Gemini Pro prompted with the gold set as seed + "generate a harder / ambiguous / adversarial variant"
- **Not hand-reviewed** (architect's pre-authorized cut from 200 → 50 to fit Phase 4 budget; hand-labeling 200 questions = 4–6 hours that the 11-day timeline cannot absorb)
- Used for trajectory-level scoring and the tool-selection confusion matrix only
- If any adversarial case surfaces a real agent bug during dev, it graduates into the gold set (~3–5 additions expected)

### 12.3 Judge — cross-family LLM-as-judge (load-bearing methodology)

- **Primary judge: Claude Haiku 4.5** via the Anthropic API, funded from student credits. Rubric-based (1–5 scale on: correctness, citation faithfulness, action appropriateness).
- **Fallback judge: Gemini Pro**, activated if the Anthropic budget is exhausted (see Section 14 cost controls).
- **Why cross-family:** same-family LLM-as-judge (Gemini judging Gemini) produces correlated bias and is methodologically weak. A cross-family judge (Claude judging Gemini) is the current academic best practice for agent evaluation in 2026 and reads materially stronger in the technical report.
- **Rubric is a versioned repo artifact:** committed at `evals/rubric.md`. Loaded by both the in-graph `verify` node and the external Claude-judge eval harness from that single path. Treated as code — every change shows in git history.
- **Cost discipline:** judge responses are cached by `(question_id, agent_trace_hash)` so identical traces are not re-judged across dev iterations. The 50-question synthetic adversarial set is run only 2–3 times (final-week regressions), not every dev iteration.

### 12.4 Trajectory scoring

- For each run, compare actual tool call sequence vs. expected
- Compute per-step precision / recall on tool selection
- Generate confusion matrix (which tools get confused with which)
- Feed findings back into DSPy planner compilation

---

## 13. UX

### 13.1 Moat principle (per Trend Researcher)

**The audit trail leads. The forecast chart is secondary.** A JOLT planner's job is to defend a decision in a Monday review — they need a clickable citation trail, not a prettier chart.

### 13.2 Dashboard layout (v1)

```
┌─────────────────────────────────────────────────────────────────┐
│  FabOps Copilot                             Session: abc-1234   │
├─────────────────────┬───────────────────────────────────────────┤
│                     │                                           │
│   Filters:          │   Query: [Why is part A7 at Taiwan fab…]  │
│   ┌───────────┐     │   [Ask]                                   │
│   │ Fab: TW   │     │                                           │
│   │ Part: A7  │     │   ┌─ Agent Plan ────────────────────┐     │
│   └───────────┘     │   │ 1. check_policy_staleness ✓     │     │
│                     │   │ 2. check_demand_drift  ✓  │─┐    │     │
│                     │   │ 3. check_supply_drift  ✓  │ │par │     │
│                     │   │ 4. ground_in_disclosures ✓      │     │
│                     │   │ 5. diagnose            ✓        │     │
│                     │   │ 6. prescribe_action    ✓        │     │
│                     │   │ 7. verify              ✓        │     │
│                     │   └─────────────────────────────────┘     │
│                     │                                           │
│                     │   ┌─ Diagnosis ─────────────────────┐     │
│                     │   │ PRIMARY DRIVER: supply           │     │
│                     │   │ P90 stockout: 2026-05-03 ± 6d    │     │
│                     │   └─────────────────────────────────┘     │
│                     │                                           │
│                     │   ┌─ Citations / Audit trail ──────┐     │
│                     │   │ (1) Croston P90 = May 3 [link]  │     │
│                     │   │ (2) FRED IPG3344S -2.1% [link]  │     │
│                     │   │ (3) AM 10-Q: Taiwan lead-time…  │     │
│                     │   │     [link to SEC filing]        │     │
│                     │   │ (4) Policy last updated 14 mo   │     │
│                     │   │     ago [link to compute run]   │     │
│                     │   └─────────────────────────────────┘     │
│                     │                                           │
│                     │   ┌─ Recommended Action ───────────┐     │
│                     │   │ EXPEDITE from supplier B       │     │
│                     │   │ Cost delta: $42k vs. accept    │     │
│                     │   │ Confidence: 0.82               │     │
│                     │   └─────────────────────────────────┘     │
│                     │                                           │
│                     │   ┌─ Forecast ──────────────────────┐     │
│                     │   │ [chart: demand + P10/P90 band]  │     │
│                     │   └─────────────────────────────────┘     │
└─────────────────────┴───────────────────────────────────────────┘
```

### 13.3 Design system

Kept minimal — single-page HTML + vanilla JS + a small CSS framework. No React in v1 to keep the Lambda-to-S3 deploy loop simple. Upgrade to a framework only if time allows.

---

## 14. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `statsforecast` arm64 cold-start blows p95 | HIGH | HIGH | Container-image nightly Lambda (heavy stack isolated); zipped runtime Lambda never imports `statsforecast`; reads P90 tables from DynamoDB cache; NumPy Croston fallback if wheels break |
| **Runtime Lambda zipped package exceeds 250 MB ceiling** | MEDIUM | HIGH | Runtime package strictly excludes `statsforecast`, `numba`, `pandas`, MLflow. Container image nightly Lambda absorbs the heavy stack. Smoke-test package size in CI on every PR. |
| **EDGAR ingest Gemini embedding rate limit stalls pre-work** | MEDIUM | MEDIUM | Day-0 offline ingest with exponential backoff + per-second budget; cached into S3 so re-runs are idempotent; if Gemini blocks, use OpenAI `text-embedding-3-small` via the $5 credit as overflow |
| **EventBridge → Lambda IAM wiring for nightly cron has hidden complexity** | MEDIUM | LOW | Budget 0.5 day explicitly in Phase 0 day 1 for EventBridge rule + target + permission + first successful trigger |
| **DynamoDB `fabops_forecasts` partition hot-spotting during nightly burst write (2,674 items)** | LOW | MEDIUM | Use `BatchWriteItem` (25 items/batch) with exponential backoff + jitter; spread writes over ~60 seconds |
| **CORS + credentials footgun** (API Gateway HTTP + `Access-Control-Allow-Origin: *` with credentials silently fails) | MEDIUM | LOW | No credentials mode in v1; wildcard origin in dev, pinned origin in final demo; explicit `OPTIONS` preflight handler |
| MCP stdio server fails to integrate with Claude Desktop for the demo clip | LOW | LOW | Build the stdio face on day 5–6, test against Claude Desktop same day; fallback is recording the clip against a local MCP inspector (still real MCP, just not Claude Desktop) |
| Langfuse cloud free tier event cap hit during batch evals | LOW | LOW | Throttle batch eval runs; cache judge responses; if cap hit late, disable tracing on synthetic-set re-runs only |
| Gemini free tier rate limits during eval runs | MEDIUM | MEDIUM | Batch eval runs, cache judge responses, spread over multiple days; OpenAI GPT-4o-mini overflow via $5 credit |
| DSPy compilation on 30 examples produces worse prompt | LOW | LOW | Report both versions in the tech report; it's a signal either way |
| Scope creep from the expanded plan | MEDIUM | HIGH | Lock this spec; every additional feature request triggers explicit scope negotiation |
| Demo-day Lambda quota / billing surprise | LOW | MEDIUM | Monitor CloudWatch cost daily; hard-cap Gemini usage in runtime |
| Anthropic judge spend exceeds $10 credit | MEDIUM | MEDIUM | See Section 14.1 Budget and Cost Controls below |

### 14.1 Budget and cost controls

**Available credits (hard limits):**

- **Google Gemini:** free tier (no credit pool; rate limits are the constraint)
- **Anthropic:** $10 credit
- **OpenAI:** $5 credit

**Spending plan:**

- **Gemini (agent runtime, embeddings, DSPy compile, fallback judge):** target **$0** — all on free tier
- **Anthropic (cross-family Claude Haiku 4.5 judge + synthetic adversarial eval generation):** target **~$8**, hard cap **$9**
- **OpenAI (GPT-4o-mini overflow insurance if Gemini free tier rate-limits block a DSPy compile or batch eval):** target **~$2**, hard cap **$4**
- **Total projected burn:** ~$10–$12 of the $15 combined credit pool. ~$3–$5 safety margin.

**Hard-switch automation:**

1. Every judge call logs estimated Anthropic spend into `fabops_audit`.
2. A running total is computed at the start of each eval batch.
3. **At $9.00 cumulative Anthropic spend, the judge auto-switches to Gemini Pro** for the remainder of the project. A Slack-style console warning is emitted. This switch is one line of code behind a feature flag.
4. Same pattern for OpenAI overflow: hard-switch at $4.00.

**Cost-saving defenses:**

- **Judge response caching** by `(question_id, agent_trace_hash)` — if an agent's trace didn't change, we don't re-judge. Expected savings: ~60% of judge spend across dev iterations.
- **Tiered eval cadence:** 30-question gold set runs on every PR (cheap); 200-question synthetic adversarial set runs only on final-week regressions (expensive), 2–3 times total.
- **Batched judge calls** (one Anthropic API request per batch of 10 questions, not one per question) to amortize HTTP overhead.

**Non-goal:** we will not pay out-of-pocket. If all three budgets deplete, the project falls back to the Gemini-only path, still functional, with the cross-family methodology explicitly noted as a limitation in the report.

---

## 15. Rough milestone plan (11 days + Day 0 pre-work)

High-level only — the full day-by-day implementation plan comes in the next step via the `writing-plans` skill. These are load-bearing phases, not a schedule.

0. **Phase -1 — Day 0 pre-work (before day 1 starts, runs local):** SEC EDGAR ingest script (`scripts/ingest_edgar.py`) — download AM 10-K/10-Q/8-K from last 3 years, chunk, embed with Gemini, write to S3 snapshot + DynamoDB `fabops_edgar_index`. This is deliberately offloaded to Day 0 because Gemini embedding rate limits make it non-trivial and it cannot share days with runtime work.
1. **Phase 0 — Infra + audit spine (day 1):** DynamoDB tables (audit first), S3 buckets, IAM roles, EventBridge → nightly Lambda permission, container-image nightly Lambda skeleton, zipped runtime Lambda skeleton, **`fabops_audit` write helper smoke-tested with a fake tool call before any agent exists**, `statsforecast` wheel test or NumPy Croston fallback decision
2. **Phase 1 — Data & tools (days 2–4):** load `carparts` into the nightly bake, build `forecast_demand` + `compute_reorder_policy` that together write to `fabops_forecasts` and `fabops_policies` (including pre-baked demand stats), wire Census M3 + FRED, synthesize inventory/supplier/incident overlays, implement `simulate_supplier_disruption`, `get_inventory`, `get_supplier_leadtime`
3. **Phase 2 — LangGraph agent + stdio MCP second face (days 4–6):** build the LangGraph state machine with policy-first reasoning order, direct tool binding (not through MCP) on the hot path, Pydantic validation, parallel fan-out, `verify` node, bounded retry; in parallel build `scripts/mcp_server.py` stdio MCP server importing the same tool functions, test against Claude Desktop, record demo clip
4. **Phase 3 — Frontend & API (days 6–7):** S3-hosted dashboard with audit-trail-first layout, API Gateway routes, CORS plan (wildcard dev, pinned prod, explicit `OPTIONS` preflight), wire to Lambda, end-to-end smoke test
5. **Phase 4 — Evals & MLOps (days 7–9):** 30-question gold set hand-authored, 50-question synthetic adversarial set machine-generated, Langfuse Cloud integration with shared `request_id`, MLflow tracking in nightly bake, GitHub Actions CI eval gate, DSPy `BootstrapFewShot` planner compilation, confusion matrix reporting
6. **Phase 5 — Technical report & polish (days 9–11):** write the report with the rehearsed paragraph, record the demo video (including the 30s Claude Desktop MCP clip), final deployment, README polish, cold-start stress test, submit

---

## 16. Non-goals (explicit)

To stop future scope creep:

- NOT building authentication
- NOT building multi-agent orchestration
- NOT fine-tuning Gemini
- NOT integrating with any real SAP / Oracle / enterprise system
- NOT building a mobile UI
- NOT supporting non-English queries
- NOT claiming the synthetic inventory data is real
- NOT building a user management system
- NOT adding OpenAI / Claude as alternative LLMs
- NOT implementing a custom vector database beyond DynamoDB + cosine

---

## 17. Resolved decisions (locked 2026-04-13, revised after architect review)

All prior open questions have been resolved with the user and are locked into this spec:

1. **MCP fidelity:** Two-face architecture. LangGraph calls the seven tool Python functions **directly** on the runtime hot path (no protocol overhead, no cold-start tax). A genuinely separate stdio MCP server at `scripts/mcp_server.py` imports the same tool functions and is tested live inside Claude Desktop for the demo video. That Claude Desktop clip is the MCP signal's proof.
2. **Lambda packaging:** **Split — container image for the nightly bake Lambda** (holds `statsforecast` + `numba` + `pandas` + MLflow, offline cron, cold-start irrelevant), **zipped for the runtime agent Lambda** (<50 MB, slim, never imports heavy scientific stack). Solves the 250 MB unzipped ceiling without sacrificing runtime cold-start.
3. **Langfuse deployment:** Langfuse Cloud free tier. Zero infra overhead, traces sit on langfuse.com linked to eval runs.
4. **DSPy planner compilation:** in scope, using `BootstrapFewShot` only (MIPROv2 pre-authorized cut — Gemini quota hungry). Compiles against the 30-question gold set in minutes.
5. **Frontend framework:** vanilla HTML / JS / CSS. Matches the course tutorial AWS pattern, simplest S3 deploy loop, no build-step complexity.
6. **LLM-as-judge model:** cross-family — Claude Haiku 4.5 (Anthropic API, funded from student credits) judges the Gemini-based agent. Gemini Pro is the budget-exhaustion fallback. Full cost discipline in Section 14.1.
7. **Primary agent LLM:** Google Gemini 2.0 Flash for routing and planner, Gemini 2.0 Pro for diagnose and verify. All on free tier, zero runtime cost.
8. **Adversarial eval set:** 50 questions, machine-generated, not hand-labeled, used for confusion matrix only (pre-authorized cut from 200 → 50 to fit Phase 4 budget).
9. **Provisioned concurrency:** not used (pre-authorized cut — saves $3 and ~30 min setup). Split packaging alone keeps runtime cold-start acceptable.
10. **Shared `request_id` UUIDv4:** mandated. Generated at `entry` node, logged to Langfuse + MLflow + CloudWatch + `fabops_audit`. Single join key for end-to-end reproducibility.
11. **`fabops_audit` is the system spine:** built day 1 before any agent exists, smoke-tested with a fake tool call before any real tool runs.
12. **EDGAR ingest is Day 0 pre-work:** runs local via `scripts/ingest_edgar.py`, not part of runtime or nightly.
13. **DynamoDB vector search:** explicit full-scan + in-memory cosine, acceptable at N < 20K chunks. Not an "index."
14. **Rubric file:** versioned at `evals/rubric.md`, loaded by both `verify` node and the Claude judge.

Spec is now considered design-locked. Any further change requires explicit user-driven scope negotiation.
