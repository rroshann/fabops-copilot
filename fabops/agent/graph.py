"""Wire the LangGraph state machine.

Spec Section 4.2. Reasoning order: policy -> [demand || supply] -> disclosures ->
diagnose -> prescribe -> verify (retry<=2) -> finalize.

The verify node is gated behind FABOPS_ENABLE_VERIFY (default off) because it
runs a second Gemini Pro call (3-8s per invoke) that doubles the p50 latency
for little marginal quality gain once the primary diagnose step is stable.
Set FABOPS_ENABLE_VERIFY=1 on the Lambda to re-enable the verify retry loop.
"""
import os

from langgraph.graph import END, StateGraph

from fabops.agent.nodes import (
    check_demand_node,
    check_policy_node,
    check_supply_node,
    diagnose_node,
    entry_node,
    finalize_node,
    ground_disclosures_node,
    prescribe_node,
    verify_node,
)
from fabops.agent.state import AgentState
from fabops.config import MAX_GEMINI_PRO_CALLS


def _should_retry(state: AgentState) -> str:
    if state.verify_passed:
        return "finalize"
    if state.verify_attempts >= 2:
        return "finalize"
    if state.llm_pro_calls >= MAX_GEMINI_PRO_CALLS:
        return "finalize"
    return "diagnose"


def build_graph():
    g = StateGraph(AgentState)
    enable_verify = os.environ.get("FABOPS_ENABLE_VERIFY") == "1"

    g.add_node("entry", entry_node)
    g.add_node("check_policy", check_policy_node)
    g.add_node("check_demand", check_demand_node)
    g.add_node("check_supply", check_supply_node)
    g.add_node("ground_disclosures", ground_disclosures_node)
    g.add_node("diagnose", diagnose_node)
    g.add_node("prescribe", prescribe_node)
    if enable_verify:
        g.add_node("verify", verify_node)
    g.add_node("finalize", finalize_node)

    g.set_entry_point("entry")
    g.add_edge("entry", "check_policy")
    g.add_edge("check_policy", "check_demand")
    g.add_edge("check_demand", "check_supply")
    g.add_edge("check_supply", "ground_disclosures")
    g.add_edge("ground_disclosures", "diagnose")
    g.add_edge("diagnose", "prescribe")
    if enable_verify:
        g.add_edge("prescribe", "verify")
        g.add_conditional_edges("verify", _should_retry, {
            "diagnose": "diagnose",
            "finalize": "finalize",
        })
    else:
        # Fast path: skip verify, go straight from prescribe to finalize.
        g.add_edge("prescribe", "finalize")
    g.add_edge("finalize", END)

    return g.compile()


# Module-level singleton so Lambda warm invocations reuse the compiled graph
_GRAPH = None


def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH
