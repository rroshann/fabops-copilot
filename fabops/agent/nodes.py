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

from fabops.agent.llm import gemini_flash
from fabops.agent.state import AgentState, ToolCallRecord
from fabops.observability.audit import AuditWriter
from fabops.tools.compute_reorder_policy import run as compute_policy
from fabops.tools.forecast_demand import run as forecast_demand
from fabops.tools.get_inventory import run as get_inventory
from fabops.tools.get_macro_signal import run as get_macro
from fabops.tools.get_supplier_leadtime import run as get_supplier
from fabops.tools.search_disclosures import run as search_disclosures


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
