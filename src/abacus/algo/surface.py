"""Buttons that expose algorithm files to the MCP surface and the registry (not spec buttons)."""
from __future__ import annotations

from .. import registry
from .lint import DEFAULT_K, lint
from .roles import RUN_ROLES, run_role


@registry.button(
    "algo_lint",
    description="Lint an algorithm file: header, roles, requires, determinism, agreement, range, spread, cost. "
                "Reports findings, never a verdict.",
    input_schema={"type": "object",
                  "properties": {"path": {"type": "string"}, "k": {"type": "integer", "minimum": 1, "maximum": 200}},
                  "required": ["path"]},
    default_time_s=60,
)
def algo_lint(inp: dict, ctx):
    return lint(inp["path"], k=inp.get("k", DEFAULT_K))


@registry.button(
    "algo_run",
    description="Run one role (compute, check, generate, demo, hand_space) of an algorithm file.",
    input_schema={"type": "object",
                  "properties": {"path": {"type": "string"}, "role": {"enum": list(RUN_ROLES)},
                                 "knobs": {"type": "object"}, "args": {"type": "object"}},
                  "required": ["path", "role"]},
    default_time_s=30,
)
def algo_run(inp: dict, ctx):
    return run_role(inp["path"], inp["role"], seed=ctx.seed, knobs=inp.get("knobs"),
                    in_process=True, **(inp.get("args") or {}))
