"""Buttons that expose algorithm files to the MCP surface and the registry (not spec buttons).

`algo_run` is registered in roles.py, next to the code it runs.
"""
from __future__ import annotations

from .. import registry
from .lint import DEFAULT_K, lint


@registry.button(
    "algo_lint",
    description="Lint an algorithm file: header, roles, requires, determinism, agreement, range, spread, cost. "
                "Reports findings, never a verdict. Stops itself before the time budget and reports what it had.",
    input_schema={"type": "object",
                  "properties": {"path": {"type": "string"}, "k": {"type": "integer", "minimum": 1, "maximum": 200}},
                  "required": ["path"]},
    default_time_s=60,
)
def algo_lint(inp: dict, ctx):
    # Leave a fifth of the budget for the lint to wrap up and send its partial result.
    return lint(inp["path"], k=inp.get("k", DEFAULT_K), time_s=ctx.time_left() * 0.8)
