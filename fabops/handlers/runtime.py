"""Runtime agent Lambda — invokes the LangGraph FabOps Copilot agent.

Reads POST body with {"query": "..."}. Returns the agent's final answer
plus the audit trail and citations.
"""
import json
import traceback

from fabops.agent.graph import get_graph
from fabops.agent.state import AgentState
from fabops.observability.audit import AuditWriter
from fabops.observability.langfuse_shim import (
    flush as langfuse_flush,
    get_callback_handler,
)
from fabops.observability.request_id import new_request_id


def handler(event, context):
    request_id = new_request_id()
    body = event.get("body") or "{}"
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            body = {}
    query = body.get("query", "")

    if not query:
        return _response(400, {"error": "query field required", "request_id": request_id})

    # Single writer for this request so step_n increments monotonically,
    # preventing the error row from overwriting the entry row in DynamoDB.
    audit = AuditWriter(request_id)
    audit.log_step(
        node="runtime_entry", args={"query": query}, result={}, latency_ms=0.0
    )

    try:
        graph = get_graph()
        initial_state = AgentState(request_id=request_id, user_query=query)
        # Attach the Langfuse CallbackHandler when configured (v3 pattern).
        # Without it, graph.invoke runs with no callbacks and Langfuse sees
        # nothing. The handler auto-captures every LLM/tool span inside the
        # LangGraph execution.
        callbacks = []
        langfuse_cb = get_callback_handler()
        if langfuse_cb is not None:
            callbacks.append(langfuse_cb)
        langchain_config = {
            "callbacks": callbacks,
            "metadata": {"fabops_request_id": request_id},
            "tags": [f"req:{request_id}"],
        }
        final_state = graph.invoke(initial_state, config=langchain_config)
        # LangGraph returns a dict in some versions; normalize
        if isinstance(final_state, dict):
            answer = final_state.get("final_answer", "")
            citations = final_state.get("citations", [])
            diagnosis = dict(final_state.get("diagnosis") or {})
            prescription = final_state.get("prescription") or {}
            demand_check = final_state.get("demand_check", {})
            step_n = final_state.get("step_n", 0)
            tool_calls_raw = final_state.get("tool_calls", []) or []
        else:
            answer = final_state.final_answer or ""
            citations = final_state.citations
            diagnosis = dict(final_state.diagnosis or {})
            prescription = final_state.prescription or {}
            demand_check = final_state.demand_check or {}
            step_n = final_state.step_n
            tool_calls_raw = final_state.tool_calls or []

        # Merge prescription.action into diagnosis so the frontend has a
        # single object to render. The agent stores diagnosis (driver +
        # confidence + reasoning) and prescription (action) separately
        # in state; the frontend wants them together.
        if prescription:
            if "action" in prescription and "action" not in diagnosis:
                diagnosis["action"] = prescription["action"]
            # Surface driver-specific metrics if present
            for k in ("policy_age_days", "staleness_days",
                      "leadtime_slip_days", "run_rate_delta_pct"):
                if k in prescription and k not in diagnosis:
                    diagnosis[k] = prescription[k]

        # Normalize tool_calls into a frontend-friendly audit array.
        # Each entry exposes node + duration_ms + ok + tool name.
        # Pydantic models are dumped via model_dump; dict items pass through.
        audit_trail = []
        for tc in tool_calls_raw:
            if hasattr(tc, "model_dump"):
                d = tc.model_dump()
            elif isinstance(tc, dict):
                d = tc
            else:
                continue
            audit_trail.append({
                "node": d.get("node", ""),
                "tool": d.get("tool", ""),
                "duration_ms": int(round(float(d.get("latency_ms", 0)))),
                "ok": bool(d.get("ok", True)),
            })

        return _response(200, {
            "request_id": request_id,
            "answer": answer,
            "diagnosis": diagnosis,
            "p90_stockout_date": demand_check.get("p90_stockout_date"),
            "citations": citations,
            "step_count": step_n,
            "audit": audit_trail,
        })
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[runtime_error] {type(e).__name__}: {e}\n{tb}")
        audit.log_step(
            node="runtime_error", args={"query": query}, result={},
            latency_ms=0.0, error=f"{type(e).__name__}: {e}"
        )
        return _response(500, {"error": str(e), "request_id": request_id})
    finally:
        # Force Langfuse to ship buffered trace events before Lambda terminates.
        # On Lambda, the process ends before the SDK's background batch flush
        # fires, so buffered events are lost unless we flush explicitly here.
        langfuse_flush()


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
        "body": json.dumps(body),
    }
