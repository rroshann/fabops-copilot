"""LangGraph agent state — single Pydantic model threaded through every node.

Spec Section 4.2. Also holds the caps from config so every node can check them.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ToolCallRecord(BaseModel):
    node: str
    tool: str
    args: Dict[str, Any]
    result: Dict[str, Any]
    latency_ms: float
    ok: bool


class AgentState(BaseModel):
    """The full state object. Every node returns an updated copy."""
    # Identity
    request_id: str
    user_query: str

    # Extracted entities
    part_id: Optional[str] = None
    fab_id: Optional[str] = None
    intent: Optional[str] = None

    # Tool outputs accumulated across nodes
    policy_check: Optional[Dict[str, Any]] = None
    demand_check: Optional[Dict[str, Any]] = None
    supply_check: Optional[Dict[str, Any]] = None
    disclosures_check: Optional[Dict[str, Any]] = None
    diagnosis: Optional[Dict[str, Any]] = None
    prescription: Optional[Dict[str, Any]] = None

    # Audit + caps
    step_n: int = 0
    tool_calls: List[ToolCallRecord] = Field(default_factory=list)
    llm_pro_calls: int = 0
    llm_total_calls: int = 0
    tool_call_count: int = 0

    # Verification retry
    verify_attempts: int = 0
    verify_passed: bool = False

    # Final output
    final_answer: Optional[str] = None
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)
