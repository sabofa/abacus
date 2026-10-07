"""MCP server over stdio, built from the registry. Uses the SDK's low-level `Server` (mcp 2.3.0)."""
from __future__ import annotations

import asyncio
import json

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from . import __version__, budget, registry, sandbox  # noqa: F401  (sandbox registers `run`)
from .algo import roles, surface  # noqa: F401  (register algo_lint, algo_run)
from .library import surface as library_surface  # noqa: F401  (register algo_search, algo_show, link_*)


def list_tools() -> list[types.Tool]:
    registry.load_all()
    return [types.Tool(name=b.name, description=b.description, input_schema=b.input_schema)
            for b in registry.all_buttons()]


def call_tool(name: str, args: dict | None) -> tuple[str, bool]:
    """Returns (json text, is_error). An unknown tool is an error; everything else is Evidence."""
    registry.load_all()
    try:
        registry.get(name)
    except KeyError as e:
        return json.dumps({"error": e.args[0]}), True
    return json.dumps(budget.call(name, dict(args or {})).to_dict()), False


async def _on_list_tools(ctx, params) -> types.ListToolsResult:
    return types.ListToolsResult(tools=list_tools())


async def _on_call_tool(ctx, params) -> types.CallToolResult:
    text, is_error = await asyncio.to_thread(call_tool, params.name, params.arguments)
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=is_error)


def make_server() -> Server:
    return Server("abacus", version=__version__, on_list_tools=_on_list_tools, on_call_tool=_on_call_tool)


async def _serve() -> None:
    server = make_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def serve() -> None:
    asyncio.run(_serve())
