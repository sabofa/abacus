"""Pieces shared by the computer-science buttons (diff_test, growth): the user's own function from source."""
from __future__ import annotations

import ast
import inspect
from typing import Any, Callable

from ..parsing import compile_code
from ._discrete import BadInput, is_name


def compile_callable(src: Any, role: str, names: list[str] | None = None) -> Callable:
    """The caller's function from source: a lambda, a source with one or more ``def``s (the one called ``role``
    if there is one, else the last), or a bare expression in ``names`` (the input names)."""
    if not isinstance(src, str) or not src.strip():
        raise BadInput(f"{role} must be a non-empty string of Python")
    text = src.strip()
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        tree = None
    try:
        if tree is not None and isinstance(tree.body, ast.Lambda):
            return compile_code(f"{role} = {text}\n", kind="func", name=role)
        if tree is not None:
            if not names:
                raise BadInput(f"{role}: a bare expression needs input names; write a lambda or a def")
            for n in names:
                if not is_name(n):
                    raise BadInput(f"{role}: {n!r} cannot be used as an input name")
            return compile_code(f"def {role}({', '.join(names)}):\n    return (\n{text}\n    )\n",
                                kind="func", name=role)
        mod = ast.parse(text + "\n")
        defs = [n.name for n in mod.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if not defs:
            raise BadInput(f"{role}: the code must define a function (def), or be a lambda or an expression")
        name = role if role in defs else defs[-1]
        return compile_code(text + "\n", kind="func", name=name)
    except BadInput:
        raise
    except SyntaxError as e:
        raise BadInput(f"{role}: {e.msg} (line {e.lineno})") from None
    except Exception as e:  # noqa: BLE001  (the code ran at definition time and raised)
        raise BadInput(f"{role}: {type(e).__name__}: {e}") from None


def binding(fn: Callable, role: str, n_pos: int, names: list[str] | None = None) -> str:
    """How to call ``fn`` with ``n_pos`` positional values, or by keyword with ``names``: ``"kw"`` or ``"pos"``.
    Raises BadInput if neither fits the function's parameters."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return "kw" if names else "pos"
    if names:
        try:
            sig.bind(**{n: None for n in names})
            return "kw"
        except TypeError:
            pass
    try:
        sig.bind(*[None] * n_pos)
        return "pos"
    except TypeError:
        want = f"the names {names}" if names else f"{n_pos} positional argument(s)"
        raise BadInput(f"{role}: its parameters {sig} do not fit the input, which supplies {want}") from None
