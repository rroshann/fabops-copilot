# FabOps Copilot — Handoff for Day 5

**Date:** 2026-04-14 (after Day 4 completion, before Day 5 start)
**Current HEAD:** `655241c`
**Purpose:** Resume the implementation in a fresh Claude Code session with zero prior conversation context.

## How to resume

In the fresh session, paste this as your first message:

> "Continue the FabOps Copilot build. Read `docs/superpowers/handoff-day5.md` for full state. Then read `docs/superpowers/plans/2026-04-13-fabops-copilot-implementation.md` Day 5 and start dispatching Task 5.1 via subagent-driven-development. Use the same model strategy we were using (Sonnet for most tasks, Opus for complex agent graph wiring)."

That's it. The fresh session will read this handoff, understand the state, and keep going.

## Project goal (one sentence)

Ship an agentic LLM "Service-Parts Stockout Risk Agent" on AWS serverless in 11 days that doubles as a DS 5730 final project and a lead portfolio piece for an Applied Materials JOLT Data Scientist — Agentic AI/ML application.

## Source documents

- **Spec:** `docs/superpowers/specs/2026-04-13-fabops-copilot-design.md` — fully locked, architect-reviewed, includes cross-family LLM-as-judge methodology, split-Lambda packaging, MCP two-face architecture, policy-first reasoning order
- **Plan:** `docs/superpowers/plans/2026-04-13-fabops-copilot-implementation.md` — 4869-line day-by-day implementation plan with TDD for most tasks
- **Repo:** https://github.com/rroshann/fabops-copilot

## Current state — what's done (Days 0–4)

### Day 0 (pre-work, ⏸ waiting on user execution)
- [x] `scripts/ingest_edgar.py` written and syntax-verified (commit `de8e3f9` + fixes `aae8a70`)
- [ ] **User action required:** run `python scripts/ingest_edgar.py --email your@email` locally to populate `fabops_edgar_index`. Takes 1–3 hours. This only affects the `search_company_disclosures` tool — until ingest runs, that tool returns empty results, which does NOT block Day 5–6 agent development.

### Day 1 — Infra + audit spine ✅
- [x] 1.1 Scaffold + split requirements (`5df38cc`)
- [x] 1.2 DynamoDB tables creation — **9 tables live in real AWS us-east-1** (`16022e3`)
- [x] 1.3 `fabops_audit` spine + `AuditWriter` — TDD red→green + real-AWS smoke test (`4177c0b`)
- [x] 1.4 `Dockerfile.nightly` container image (1.64 GB) (`4834db2`)
- [x] 1.5 Zipped runtime Lambda skeleton + deploy script (`1844760`)
- [x] **1.5 fix:** runtime zip went from 50 MB (at ceiling) → 29 MB (21 MB headroom) by moving `google-generativeai` to a Lambda layer and removing `mcp` from runtime requirements (`308c912`)

### Day 2 — Data + synthetic overlays ✅ (3/4; Task 2.4 deferred on user Day 0 run)
- [x] 2.1 Hyndman `carparts` loader + Syntetos-Boylan-Croston ADI/CV² classifier (`3527feb`). Dataset has exactly **2674 parts × 51 months**, 87% intermittent + 13% lumpy. Downloaded from `robjhyndman/expsmooth` GitHub (the Zenodo ID in the plan is wrong — `3994911` doesn't exist).
- [x] 2.2 Synthetic overlay generators (inventory, suppliers, incidents) (`b249135`)
- [x] 2.3 DynamoDB helpers + populate script. **Real AWS now has 1800 inventory + 20 suppliers + 100 incidents** (`0908a49`)
- [ ] 2.4 EDGAR upload — blocked on Day 0 user run

### Day 3 — Core tools ✅
- [x] 3.1 `ToolResult` + `Citation` Pydantic base contract (`d5a6b5b`)
- [x] 3.2 `forecast_demand` tool + pure-NumPy Croston/SBA fallback + `compute_p90_stockout_date` helper (`7ff98bf`). Runtime-safe, no statsforecast import.
- [x] 3.3 `get_inventory` tool, moto-tested (`a959195`)
- [x] 3.4 `get_supplier_leadtime` tool, moto-tested (`6e4b749`)

### Day 4 — Remaining tools + nightly bake ✅
- [x] 4.1 `get_industry_macro_signal` — FRED API + DynamoDB cache. Only `production` and `ppi` series implemented (IPG3344S, PCU33443344). Census M3 returns "not implemented" (`36f1b33`)
- [x] 4.2 `search_company_disclosures` — full-scan cosine over DynamoDB, returns empty `{"hits": [], "note": "...empty..."}` until Day 0 user run (`e6ee9b2`)
- [x] 4.3 `compute_reorder_policy` (with hand-rolled z-table to avoid scipy) + `simulate_supplier_disruption` (`e08eb2e`)
- [x] 4.4 **Full nightly bake with statsforecast — deployed as container-image Lambda, 200 forecasts + 200 policies written, EventBridge cron set up for 02:00 UTC nightly** (`655241c`)

## Two real bugs Opus caught in Task 4.4 plan template

1. `StatsForecast(n_jobs=-1)` fails on Lambda (needs `/dev/shm` for multiprocessing semaphores). **Fixed to `n_jobs=1`.**
2. `statsforecast==1.7.8` returns `unique_id` as DataFrame **index** after `predict()`, not a column. **Fixed with defensive `reset_index()`.**

**⚠️ These fixes are in the code at commit `655241c` but the plan document still has the buggy template.** If the fresh session re-reads the plan Task 4.4, it may be confused. Back-propagate to the plan doc OR just trust the code as the source of truth. (Non-critical — Task 4.4 is already done.)

## Real AWS state right now

- **Region:** us-east-1
- **Account:** 699475932108
- **DynamoDB tables (9, all PAY_PER_REQUEST):**
  - `fabops_audit` — partition `request_id`, sort `step_n` (N). Has rows from Day 1 smoke test + runtime Lambda stub + real Lambda invokes.
  - `fabops_sessions` — empty (not used yet)
  - `fabops_forecasts` — **200 rows** from nightly bake
  - `fabops_policies` — **200 rows** with pre-baked `leadtime_demand_mean/std`
  - `fabops_inventory` — 1800 rows (200 parts × 9 fabs)
  - `fabops_suppliers` — 20 rows
  - `fabops_edgar_index` — empty (Day 0 blocked)
  - `fabops_incidents` — 100 rows
  - `fabops_macro_cache` — empty (populated on first tool call)
- **Lambda functions:**
  - `fabops_agent_handler` — zipped (29 MB), Python 3.9 arm64, `fabops-gemini` layer attached, currently has a STUB handler that only writes an audit row and returns `{"msg": "FabOps Copilot runtime alive"}`. Day 5 replaces this.
  - `nightly_forecast_bake` — container image from ECR `fabops-nightly:latest`, arm64, 900s timeout, 3008 MB. Successfully computed 200 forecasts on the most recent invoke.
- **Lambda layer:** `arn:aws:lambda:us-east-1:699475932108:layer:fabops-gemini:1` (holds `google-generativeai` for the runtime Lambda)
- **IAM role:** `fabops-lambda-role` (has `AWSLambdaBasicExecutionRole` + `AmazonDynamoDBFullAccess`)
- **ECR repo:** `fabops-nightly` (holds the container image for the nightly bake)
- **EventBridge rule:** `fabops-nightly-bake` → cron(0 2 * * ? *) → `nightly_forecast_bake` Lambda
- **API Gateway:** not yet created (Day 7 task)
- **S3:** no buckets created yet (Day 7 task for the frontend, Day 9 task for MLflow artifacts)

## Test suite

**28/28 passing.** Locations:
- `tests/test_data/test_audit.py` (2 tests)
- `tests/test_data/test_carparts.py` (2)
- `tests/test_data/test_synthetic.py` (3)
- `tests/test_tools/test_base.py` (3)
- `tests/test_tools/test_forecast_demand.py` (3)
- `tests/test_tools/test_get_inventory.py` (2)
- `tests/test_tools/test_get_supplier_leadtime.py` (4)
- `tests/test_tools/test_get_macro_signal.py` (2)
- `tests/test_tools/test_search_disclosures.py` (2)
- `tests/test_tools/test_compute_reorder_policy.py` (3)
- `tests/test_tools/test_simulate_disruption.py` (2)

Run them all: `PYTHONPATH=$(pwd) .venv/bin/python -m pytest tests/ -v`

## Dev environment

- **Python:** 3.11 (venv at `.venv/`). System `python3` is 3.14 which breaks `pydantic-core` wheels — do NOT use it.
- **PYTHONPATH required:** `fabops` is not an editable install yet, so every script/pytest run needs `PYTHONPATH=$(pwd)`. Follow-up task #12 in the original task list tracks adding `pip install -e .`.
- **Dev venv has all deps installed** (runtime + nightly + dev tools).

## Model strategy for Day 5+

- **Sonnet** for most tasks (well-specified implementation from plan)
- **Opus** for:
  - Day 5 Task 5.3 — LangGraph node functions (the big complex file)
  - Day 6 Task 6.1 — diagnose/prescribe/verify/finalize nodes + `verify` retry logic
  - Day 6 Task 6.2 — LangGraph state machine wiring with conditional retry edges
  - Day 6 Task 6.4 — stdio MCP server + Claude Desktop integration

## Day 5 task list (next session starts here)

From the implementation plan, Day 5 has 3 tasks:

1. **Task 5.1** — Agent state Pydantic schema (`fabops/agent/state.py`). Create `AgentState` and `ToolCallRecord` models. TDD with 2 tests. SIMPLE — Sonnet.
2. **Task 5.2** — LLM client wrappers (`fabops/agent/llm.py`). Gemini Flash + Gemini Pro + Claude judge with cost tracking. No tests (manual smoke test). Sonnet.
3. **Task 5.3** — Agent nodes: entry, check_policy, check_demand (with get_inventory pre-step), check_supply (parallel fan-out), ground_disclosures. Big file, lots of integration. **Opus.**

Day 6 starts the next day:
4. **Task 6.1** — Remaining nodes: diagnose, prescribe, verify, finalize. **Opus.**
5. **Task 6.2** — LangGraph state machine wiring with `_should_retry` conditional. **Opus.**
6. **Task 6.3** — Wire runtime handler to the graph. Sonnet.
7. **Task 6.4** — stdio MCP server + Claude Desktop test + demo clip. **Opus.**

## Follow-up debt (non-blocking)

1. **Editable install** (`pip install -e .`) — so scripts don't need `PYTHONPATH=$(pwd)` prefix. Original task list #12.
2. **Back-propagate Task 4.4 bug fixes** to the plan doc (the `n_jobs=1` and `reset_index()` fixes).
3. **Fix Zenodo DOI reference** in spec data-source table (wrong ID, actual dataset came from expsmooth GitHub).
4. **Calibrate P10/P90 for nightly bake forecasts** — currently eyeballed at `0.6*fc` / `1.4*fc`; should use bootstrap intervals if evals flag the coverage.

## Budget status

- **Anthropic credit ($10 total):** ~$0 used so far. Cross-family judge doesn't run until Day 8.
- **OpenAI credit ($5 total):** $0 used. Reserved for overflow.
- **Gemini:** $0 (free tier). Not yet used at runtime — will start when Day 5 Task 5.2 wires the LLM clients.

## Process notes from Days 0–4

- **Subagent-driven-development loop caught 5 real bugs** across the 4 days:
  - Task 0.1: table decompose, Gemini rate-limit math, no crash recovery (3 critical bugs in template)
  - Task 4.4: `n_jobs=-1`, `unique_id` index/column (2 bugs in template)
- **The loop pattern that works best:** implementer → combined spec + quality review in one dispatch for simple tasks, implementer → separate spec review → separate code quality review for complex tasks. The full separate-review loop is worth it for any task with real logic (forecasting, agent graph, MCP server).
- **TDD red → green is non-negotiable** for Python module creation. Every tool task in this build did it and caught pathing / import errors early.
- **Container rebuilds via Docker layer cache are fast** — the 1.6 GB pip layer is reused. Budget 5–15 min only for cold builds.

## Environment variables needed for Day 5+

Day 5 Task 5.2 will first need these set:

```bash
export GEMINI_API_KEY="your_key"
export ANTHROPIC_API_KEY="your_key"  # not used until Day 8
export FRED_API_KEY="your_key"
```

These are needed both locally (for tests that hit real APIs) and on the Lambda (via `aws lambda update-function-configuration --environment`). The runtime Lambda currently has NO env vars set — Day 5 adds them.
