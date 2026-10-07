"""The `run` button: exec a piece of Python once, capture stdout, return the last expression's value.

Registered as an internal button so budget.call can run it in a child process with a time limit.
"""
from __future__ import annotations

import ast
import contextlib
import io
import threading
import time

from . import registry
from .evidence import Evidence, jsonable

RUN_SCHEMA = {"type": "object", "required": ["code"], "additionalProperties": False,
              "properties": {"code": {"type": "string", "description": "Python source to execute once."}}}


_LAZY = {"np": "numpy", "sp": "sympy", "nx": "networkx", "mpmath": "mpmath", "scipy": "scipy"}


class _Namespace(dict):
    """Exec globals whose heavy aliases (np, sp, ...) import on first use, so they cost no budget unless used."""

    def __missing__(self, key):
        mod = _LAZY.get(key)
        if mod is None:
            raise KeyError(key)
        try:
            val = __import__(mod)
        except ImportError:
            raise KeyError(key) from None
        self[key] = val
        return val


def namespace() -> dict:
    import cmath
    import fractions
    import functools
    import itertools
    import math
    import random

    ns = _Namespace({"__name__": "__abacus_run__", "math": math, "cmath": cmath, "fractions": fractions,
                     "Fraction": fractions.Fraction, "itertools": itertools, "functools": functools,
                     "random": random})
    try:
        import abacus.kit as ak
        ns["ak"] = ak
    except ModuleNotFoundError as e:
        if e.name != "abacus.kit":
            raise
    return ns


class _Tee(io.StringIO):
    """Collects stdout and streams the text so far, so a timeout still returns partial output.

    Progress goes out at most every 50 ms, but a trailing timer flushes whatever was written in between,
    so everything written before a kill is in the last partial.
    """

    _EVERY = 0.05

    def __init__(self, progress):
        super().__init__()
        self._progress, self._last = progress, 0.0
        self._lock = threading.Lock()
        self._timer = None

    def _send(self):
        with self._lock:
            self._timer = None
            self._last = time.monotonic()
            self._progress({"result": {"stdout": self.getvalue(), "value": None},
                            "method": "timed", "scope": "ran the given code; stopped before it finished"})

    def write(self, s):
        n = super().write(s)
        if time.monotonic() - self._last > self._EVERY:
            self._send()
        elif self._timer is None:
            t = threading.Timer(self._EVERY, self._send)
            t.daemon = True
            self._timer = t
            t.start()
        return n

    def close_stream(self):
        t = self._timer
        if t is not None:
            t.cancel()


def run_code(code: str, progress=lambda p: None) -> tuple[str, object]:
    out, value, exc = _execute(code, progress)
    if exc is not None:
        raise exc
    return out, value


def _execute(code, progress):
    tree = ast.parse(code, "<run>", "exec")
    last = None
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        last = ast.Expression(tree.body.pop().value)
    out = _Tee(progress)
    ns = namespace()
    value, exc = None, None
    try:
        with contextlib.redirect_stdout(out):
            exec(compile(tree, "<run>", "exec"), ns)
            if last is not None:
                value = eval(compile(last, "<run>", "eval"), ns)
    except Exception as e:  # noqa: BLE001
        exc = e
    finally:
        out.close_stream()
    return out.getvalue(), value, exc


def _run(inp, ctx):
    try:
        stdout, value, exc = _execute(inp["code"], ctx.progress)
    except SyntaxError as e:
        ev = Evidence(button="run", result=None, method="timed", scope="the code did not parse", complete=False)
        ev.flag("error", f"{type(e).__name__}: {e}")
        return ev
    if exc is not None:
        ev = Evidence(button="run", result={"stdout": stdout, "value": None}, method="timed",
                      scope="the code raised an error", complete=False)
        ev.flag("error", f"{type(exc).__name__}: {exc}")
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
