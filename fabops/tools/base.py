"""Shared tool base types.

All seven tools return ToolResult. Pydantic-validated contract so failures
route back to the planner with structured errors (spec Section 8.3).
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class Citation(BaseModel):
    """One clickable evidence row."""
    source: str
    url: Optional[str] = None
    excerpt: Optional[str] = None


class ToolResult(BaseModel):
    """Canonical return shape for every tool in the MCP server / LangGraph binding."""
    ok: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    citations: List[Citation] = Field(default_factory=list)
    latency_ms: float
    cached: bool = False

    @field_validator("latency_ms")
    @classmethod
    def _non_negative_latency(cls, v: float) -> float:
        if v < 0:
            raise ValueError("latency_ms must be >= 0")
        return v
