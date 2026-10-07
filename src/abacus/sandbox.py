"""The `run` button: exec a piece of Python once, capture stdout, return the last expression's value.

Registered as an internal button so budget.call can run it in a child process with a time limit.
"""
from __future__ import annotations

import ast
import contextlib
import io
import time

from . import registry
from .evidence import Evidence, jsonable

RUN_SCHEMA = {"type": "object", "required": ["code"], "additionalProperties": False,
              "properties": {"code": {"type": "string", "description": "Python source to execute once."}}}


def namespace() -> dict:
    import cmath
    import fractions
    import functools
    import itertools
    import math
    import random

    ns: dict = {"__name__": "__abacus_run__", "math": math, "cmath": cmath, "fractions": fractions,
                "Fraction": fractions.Fraction, "itertools": itertools, "functools": functools,
                "random": random}
    for alias, mod in (("np", "numpy"), ("sp", "sympy"), ("nx", "networkx"), ("mpmath", "mpmath"),
                       ("scipy", "scipy")):
        try:
            ns[alias] = __import__(mod)
        except ImportError:
            pass
    try:
        import abacus.kit as ak
        ns["ak"] = ak
    except ModuleNotFoundError as e:
        if e.name != "abacus.kit":
            raise
    return ns


class _Tee(io.StringIO):
    """Collects stdout and streams the text so far, so a timeout still returns partial output."""

    def __init__(self, progress):
        super().__init__()
        self._progress, self._last = progress, 0.0

    def write(self, s):
        n = super().write(s)
        now = time.monotonic()
        if now - self._last > 0.05:
            self._last = now
            self._progress({"result": {"stdout": self.getvalue(), "value": None},
                            "method": "timed", "scope": "ran the given code; stopped before it finished"})
        return n


def run_code(code: str, progress=lambda p: None) -> tuple[str, object]:
    tree = ast.parse(code, "<run>", "exec")
    last = None
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        last = ast.Expression(tree.body.pop().value)
    out = _Tee(progress)
    ns = namespace()
    value = None
    with contextlib.redirect_stdout(out):
        exec(compile(tree, "<run>", "exec"), ns)
        if last is not None:
            value = eval(compile(last, "<run>", "eval"), ns)
    return out.getvalue(), value


def _run(inp, ctx):
    try:
        stdout, value = run_code(inp["code"], ctx.progress)
    except Exception as e:  # noqa: BLE001
        ev = Evidence(button="run", result=None, method="timed", scope="the code raised an error", complete=False)
        ev.flag("error", f"{type(e).__name__}: {e}")
        return ev
    return Evidence(button="run", result={"stdout": stdout, "value": jsonable(value)}, method="timed",
                    scope="ran the given code once")


try:
    registry.get("run")
except KeyError:
    registry.button("run", description=(
        "Run a piece of Python once in the abacus sandbox (ak, math, numpy as np, sympy as sp, networkx as nx "
        "are available). Returns the captured stdout and the value of the last expression. A runaway guard "
        "stops it at the time budget; this is not a security boundary."),
        input_schema=RUN_SCHEMA)(_run)
