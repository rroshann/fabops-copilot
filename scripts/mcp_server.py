"""Stdio MCP server exposing the FabOps Copilot tool set.

This is the second face of the tool functions (spec Section 8.2). Runs
locally via `python scripts/mcp_server.py`, can be wired into Claude Desktop
via claude_desktop_config.json:

{
  "mcpServers": {
    "fabops": {
      "command": "python",
      "args": ["/absolute/path/to/scripts/mcp_server.py"],
      "env": {
        "AWS_REGION": "us-east-1",
        "GEMINI_API_KEY": "..."
      }
    }
  }
}
"""
import asyncio
import json
from typing import Any, Dict

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from fabops.tools.compute_reorder_policy import run as compute_policy
from fabops.tools.forecast_demand import run as forecast_demand
from fabops.tools.get_inventory import run as get_inventory
from fabops.tools.get_macro_signal import run as get_macro
from fabops.tools.get_supplier_leadtime import run as get_supplier
from fabops.tools.search_disclosures import run as search_disclosures
from fabops.tools.simulate_disruption import run as simulate_disruption


server = Server("fabops-copilot")


TOOLS = {
    "forecast_demand": (forecast_demand, {
        "type": "object",
        "properties": {
            "part_id": {"type": "string"},
            "horizon_months": {"type": "integer", "default": 12},
            "on_hand": {"type": "integer"},
        },
        "required": ["part_id"],
    }),
    "get_inventory": (get_inventory, {
        "type": "object",
        "properties": {"part_id": {"type": "string"}, "fab_id": {"type": "string"}},
        "required": ["part_id", "fab_id"],
    }),
    "get_supplier_leadtime": (get_supplier, {
        "type": "object",
        "properties": {"supplier_id": {"type": "string"}, "part_id": {"type": "string"}},
    }),
    "search_company_disclosures": (search_disclosures, {
        "type": "object",
        "properties": {"query": {"type": "string"}, "top_k": {"type": "integer", "default": 5}},
        "required": ["query"],
    }),
    "get_industry_macro_signal": (get_macro, {
        "type": "object",
        "properties": {
            "month": {"type": "string"},
            "series": {"type": "string", "enum": ["production", "ppi"]},
        },
        "required": ["month", "series"],
    }),
    "compute_reorder_policy": (compute_policy, {
        "type": "object",
        "properties": {
            "part_id": {"type": "string"},
            "service_level": {"type": "number", "default": 0.95},
        },
        "required": ["part_id"],
    }),
    "simulate_supplier_disruption": (simulate_disruption, {
        "type": "object",
        "properties": {
            "supplier_id": {"type": "string"},
            "delay_days": {"type": "integer"},
            "part_id": {"type": "string"},
        },
        "required": ["supplier_id", "delay_days", "part_id"],
    }),
}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name=name, description=f"FabOps {name}", inputSchema=schema)
        for name, (_, schema) in TOOLS.items()
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> list[TextContent]:
    if name not in TOOLS:
        return [TextContent(type="text", text=json.dumps({"error": f"unknown tool {name}"}))]
    fn, _ = TOOLS[name]
    result = fn(**arguments)
    return [TextContent(type="text", text=result.model_dump_json())]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
