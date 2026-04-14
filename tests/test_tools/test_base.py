"""Test ToolResult and Citation Pydantic models."""
import pytest
from pydantic import ValidationError

from fabops.tools.base import Citation, ToolResult


def test_tool_result_ok_path():
    r = ToolResult(
        ok=True,
        data={"foo": "bar"},
        citations=[Citation(source="SEC 10-K", url="https://sec.gov/x", excerpt="foo")],
        latency_ms=12.3,
        cached=False,
    )
    assert r.ok
    assert r.data["foo"] == "bar"
    assert len(r.citations) == 1


def test_tool_result_error_path():
    r = ToolResult(ok=False, error="not found", latency_ms=5.0, citations=[])
    assert not r.ok
    assert r.error == "not found"
    assert r.data is None


def test_tool_result_rejects_negative_latency():
    with pytest.raises(ValidationError):
        ToolResult(ok=True, latency_ms=-1.0, citations=[])
