"""MCP protocol compliance smoke test.

Validates that `scripts/mcp_server.py` registers exactly the seven FabOps
tools with well-formed JSON input schemas, and that each tool callable is
the same function object consumed by the LangGraph runtime. This is the
authoritative in-repo evidence for the report's MCP-compliance claim
without paying the cost of a full stdio subprocess handshake on every
pytest run (which imports an 18 MB baked EDGAR asset at module init).

The full end-to-end stdio handshake is verifiable manually with:
    python scripts/mcp_server.py
and any MCP client (Claude Desktop, `mcp inspect`, etc.).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_PATH = REPO_ROOT / "scripts" / "mcp_server.py"

EXPECTED_TOOLS = {
    "forecast_demand",
    "get_inventory",
    "get_supplier_leadtime",
    "search_company_disclosures",
    "get_industry_macro_signal",
    "compute_reorder_policy",
    "simulate_supplier_disruption",
}


@pytest.fixture(scope="module")
def mcp_server_module():
    pytest.importorskip("mcp")
    spec = importlib.util.spec_from_file_location("_fabops_mcp_server", SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_server_file_exists():
    assert SERVER_PATH.exists(), f"mcp_server.py missing at {SERVER_PATH}"


def test_registers_exactly_seven_fabops_tools(mcp_server_module):
    advertised = set(mcp_server_module.TOOLS.keys())
    assert advertised == EXPECTED_TOOLS, (
        f"Tool set drift. Missing: {EXPECTED_TOOLS - advertised}. "
        f"Unexpected: {advertised - EXPECTED_TOOLS}."
    )


def test_every_tool_has_object_type_input_schema(mcp_server_module):
    for name, (func, schema) in mcp_server_module.TOOLS.items():
        assert callable(func), f"{name} callable must be a function"
        assert schema.get("type") == "object", (
            f"{name} schema type must be 'object', got {schema.get('type')}"
        )
        assert "properties" in schema, f"{name} schema missing 'properties'"


def test_tool_callables_are_the_same_functions_the_runtime_uses(mcp_server_module):
    from fabops.tools import (
        compute_reorder_policy,
        forecast_demand,
        get_inventory,
        get_macro_signal,
        get_supplier_leadtime,
        search_disclosures,
        simulate_disruption,
    )

    expected_identity = {
        "forecast_demand": forecast_demand.run,
        "get_inventory": get_inventory.run,
        "get_supplier_leadtime": get_supplier_leadtime.run,
        "search_company_disclosures": search_disclosures.run,
        "get_industry_macro_signal": get_macro_signal.run,
        "compute_reorder_policy": compute_reorder_policy.run,
        "simulate_supplier_disruption": simulate_disruption.run,
    }
    for name, expected_func in expected_identity.items():
        actual_func = mcp_server_module.TOOLS[name][0]
        assert actual_func is expected_func, (
            f"{name} MCP binding diverged from runtime import. "
            "The two-face pattern only works if both faces call the same object."
        )


def test_mcp_server_api_is_present(mcp_server_module):
    assert hasattr(mcp_server_module, "server"), "mcp.server.Server instance missing"
    assert mcp_server_module.server.name == "fabops-copilot"
