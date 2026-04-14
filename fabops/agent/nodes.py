"""LangGraph node functions for the FabOps Copilot agent.

Spec Section 4.2. Reasoning order: policy -> demand -> supply (parallel with
demand) -> disclosures -> diagnose -> prescribe -> verify -> finalize.

This file holds the first five nodes (entry, check_policy, check_demand,
check_supply, ground_disclosures). Day 6 Task 6.1 appends diagnose/prescribe/
verify/finalize to the same file so they share the state schema and the
``_audit`` helper.
"""
import asyncio
import json
import time
from datetime import date
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


# ---- AUDIT HELPER ---------------------------------------------------------
#
# fabops_audit uses a (request_id, step_n) composite key. AuditWriter keeps
# its own `_step_n` counter that starts at 0 on every construction. If we
# build a fresh AuditWriter inside this helper on each call (which we do, to
# keep nodes stateless and picklable by LangGraph) then every row would be
# written with step_n=1 and silently overwrite the previous row.
#
# Fix: we are the single source of truth for the step counter via
# ``state.step_n``. Before calling ``log_step`` we sync the writer's internal
# counter to ``state.step_n`` so its ``+= 1`` yields ``state.step_n + 1``,
# then we bump ``state.step_n`` to match. This keeps the state counter and
# the DynamoDB sort key aligned without touching the AuditWriter public API.
def _audit(
    state: AgentState,
    node: str,
    args: Dict[str, Any],
    result: Dict[str, Any],
    latency_ms: float,
    ok: bool = True,
) -> None:
    writer = AuditWriter(state.request_id)
    # Seed the writer's counter from the authoritative state counter so that
    # log_step's internal increment yields state.step_n + 1.
    writer._step_n = state.step_n
    writer.log_step(node=node, args=args, result=result, latency_ms=latency_ms)
    state.step_n += 1
    state.tool_calls.append(
        ToolCallRecord(
            node=node,
            tool=node,
            args=args,
            result=result,
            latency_ms=latency_ms,
            ok=ok,
        )
    )


# ---- ENTRY ----------------------------------------------------------------

ENTRY_SYSTEM = """You are a JSON-only parser. Extract from the user query:
- part_id (e.g. 'A7' — any alphanumeric token that looks like a part ID)
- fab_id (lowercase location like 'taiwan', 'arizona', 'santa-clara-ca')
- intent (one of: 'stockout_risk', 'general_query')

Respond with ONLY a JSON object. No prose, no markdown fences."""


def entry_node(state: AgentState) -> AgentState:
    t0 = time.time()
    text, _ = gemini_flash(state.user_query, system=ENTRY_SYSTEM)
    state.llm_total_calls += 1
    cleaned = (
        text.strip()
        .removeprefix("```json")
        .removeprefix("```")
        .removesuffix("```")
        .strip()
    )
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = {"part_id": None, "fab_id": None, "intent": "general_query"}
    state.part_id = parsed.get("part_id")
    state.fab_id = parsed.get("fab_id") or "taiwan"
    state.intent = parsed.get("intent", "general_query")
    _audit(
        state,
        "entry",
        {"query": state.user_query},
        parsed,
        (time.time() - t0) * 1000,
    )
    return state


# ---- POLICY CHECK ---------------------------------------------------------


def check_policy_node(state: AgentState) -> AgentState:
    if not state.part_id:
        state.policy_check = {"skipped": True, "reason": "no part_id"}
        return state
    t0 = time.time()
    result = compute_policy(part_id=state.part_id, service_level=0.95)
    state.policy_check = result.data if result.ok else {"error": result.error}
    state.tool_call_count += 1
    _audit(
        state,
        "check_policy_staleness",
        {"part_id": state.part_id},
        state.policy_check,
        (time.time() - t0) * 1000,
        ok=result.ok,
    )
    return state


# ---- DEMAND CHECK (pre-steps with get_inventory) --------------------------


def check_demand_node(state: AgentState) -> AgentState:
    if not state.part_id:
        state.demand_check = {"skipped": True}
        return state
    t0 = time.time()
    inv = get_inventory(part_id=state.part_id, fab_id=state.fab_id)
    on_hand = inv.data["on_hand"] if inv.ok else 0
    state.tool_call_count += 1

    fc = forecast_demand(
        part_id=state.part_id, horizon_months=12, on_hand=on_hand
    )
    state.tool_call_count += 1

    state.demand_check = {
        "on_hand": on_hand,
        "p90_stockout_date": fc.data.get("p90_stockout_date") if fc.ok else None,
        "forecast": fc.data.get("forecast") if fc.ok else [],
        "p10": fc.data.get("p10") if fc.ok else [],
        "p90": fc.data.get("p90") if fc.ok else [],
        "model": fc.data.get("model") if fc.ok else None,
    }
    _audit(
        state,
        "check_demand_drift",
        {"part_id": state.part_id, "fab_id": state.fab_id},
        state.demand_check,
        (time.time() - t0) * 1000,
        ok=fc.ok,
    )
    return state


# ---- SUPPLY CHECK (parallel fan-out) --------------------------------------


async def _supply_parallel(part_id: str) -> Dict[str, Any]:
    """Run get_supplier_leadtime + get_industry_macro_signal concurrently."""
    loop = asyncio.get_event_loop()
    sup_fut = loop.run_in_executor(None, lambda: get_supplier(part_id=part_id))
    month = date.today().strftime("%Y-%m")
    macro_fut = loop.run_in_executor(
        None, lambda: get_macro(month=month, series="production")
    )
    sup, macro = await asyncio.gather(sup_fut, macro_fut)
    return {
        "supplier": sup.data if sup.ok else {"error": sup.error},
        "macro": macro.data if macro.ok else {"error": macro.error},
    }


def check_supply_node(state: AgentState) -> AgentState:
    if not state.part_id:
        state.supply_check = {"skipped": True}
        return state
    t0 = time.time()
    result = asyncio.run(_supply_parallel(state.part_id))
    state.supply_check = result
    state.tool_call_count += 2
    _audit(
        state,
        "check_supply_drift",
        {"part_id": state.part_id},
        result,
        (time.time() - t0) * 1000,
    )
    return state


# ---- DISCLOSURES GROUND ---------------------------------------------------


def ground_disclosures_node(state: AgentState) -> AgentState:
    t0 = time.time()
    query_parts = [state.user_query]
    if state.fab_id:
        query_parts.append(state.fab_id)
    result = search_disclosures(query=" ".join(query_parts), top_k=3)
    state.disclosures_check = result.data if result.ok else {"hits": []}
    state.tool_call_count += 1
    _audit(
        state,
        "ground_in_disclosures",
        {"query": state.user_query},
        state.disclosures_check,
        (time.time() - t0) * 1000,
        ok=result.ok,
    )
    return state


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
            # simulate_disruption.data holds sim metrics; wrap with an explicit
            # action so finalize_node's .get("action") doesn't fall through.
            sim = result.data if result.ok else {"error": result.error}
            state.prescription = {
                "action": "expedite",
                "reason": f"supply-driven; disruption sim shows {sim.get('expected_delay_days', 'n/a')}d impact",
                "simulation": sim,
            }
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
