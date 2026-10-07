"""Pieces shared by the discrete buttons (enumerate, sequence, counterexample): the user's own Python,
cheap time checks inside hot loops, and the bad-input Evidence."""
from __future__ import annotations

import ast
import inspect
import itertools
import keyword
import time
from typing import Any, Callable

from ..evidence import Evidence, jsonable
from ..parsing import compile_code


class BadInput(Exception):
    """The caller's input cannot be used. Becomes Evidence flagged ``bad_input`` with ``complete=False``."""


def bad_input(button: str, method: str, msg: str, *, result: Any = None,
              scope: str = "input rejected before running") -> Evidence:
    ev = Evidence(button=button, result=result, method=method, scope=scope, complete=False)
    ev.flag("bad_input", msg)
    return ev


def is_name(s: Any) -> bool:
    return isinstance(s, str) and s.isidentifier() and not keyword.iskeyword(s)


def is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def short(x: Any, n: int = 80) -> str:
    s = repr(x)
    return s if len(s) <= n else s[: n - 3] + "..."


def size_json(n: int | None) -> Any:
    """A size that survives JSON clients: exact while it is a safe integer, then digits, then a magnitude."""
    if n is None or n <= 2**53:
        return n
    s = str(n)
    if len(s) <= 40:
        return s
    return f"about {s[0]}.{s[1:4]}e+{len(s) - 1}"


def key_str(k: Any) -> str:
    import json
    j = jsonable(k)
    return j if isinstance(j, str) else json.dumps(j)


# ---------------------------------------------------------------------------------------------- user code

def _top_level_functions(tree: ast.Module) -> list[str]:
    return [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def compile_def(src: str, role: str) -> Callable:
    """Source that defines a function: the one called ``role``, or the only function it defines."""
    try:
        tree = ast.parse(src.strip())
    except SyntaxError as e:
        raise BadInput(f"{role}: {e.msg} (line {e.lineno})") from None
    names = _top_level_functions(tree)
    name = role if role in names else (names[0] if len(names) == 1 else None)
    if name is None:
        raise BadInput(f"{role}: the code must define a function named {role}"
                       + (f" (it defines {', '.join(names)})" if names else ""))
    try:
        return compile_code(src.strip() + "\n", kind="func", name=name)
    except BadInput:
        raise
    except Exception as e:  # noqa: BLE001
        raise BadInput(f"{role}: {type(e).__name__}: {e}") from None


class UserFn:
    """The caller's expression, lambda or def, called positionally with values for ``names``.

    An expression sees each name as a variable. A def or lambda may take any of the names as parameters
    (in any order), or a single parameter that receives the whole object: the value itself when
    ``whole_object`` (``names`` is then just ``["x"]``), else a dict of the variables. ``set`` puts extra
    names (a sweep variable) in its globals.
    """

    def __init__(self, src: Any, role: str, names: list[str], whole_object: bool = False):
        if not isinstance(src, str) or not src.strip():
            raise BadInput(f"{role} must be a non-empty string of Python")
        text = src.strip()
        try:
            tree = ast.parse(text, mode="eval")
            as_expr = True
        except SyntaxError:
            as_expr = False
        if as_expr and isinstance(tree.body, ast.Lambda):
            fn = self._compile(f"{role} = {text}\n", role)
        elif as_expr:
            for n in names:
                if not is_name(n):
                    raise BadInput(f"{role}: {n!r} cannot be used as a variable name")
            fn = self._compile(f"def {role}({', '.join(names)}):\n    return (\n{text}\n    )\n", role)
            self.call = fn
            self._globals = fn.__globals__
            return
        else:
            fn = compile_def(text, role)
        self._globals = fn.__globals__
        try:
            params = [p for p in inspect.signature(fn).parameters.values()]
        except (TypeError, ValueError):
            raise BadInput(f"{role}: cannot read the function's parameters") from None
        if any(p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD, p.KEYWORD_ONLY) for p in params):
            raise BadInput(f"{role}: use plain parameters, without *args, **kwargs or keyword-only ones")
        pn = [p.name for p in params]
        if whole_object:
            if len(pn) != 1:
                raise BadInput(f"{role}: the function takes one parameter, the object (got {len(pn)})")
            self.call = fn
        elif pn and all(p in names for p in pn) and len(set(pn)) == len(pn):
            idx = [names.index(p) for p in pn]
            if idx == list(range(len(names))):
                self.call = fn
            else:
                self.call = lambda *v: fn(*[v[i] for i in idx])
        elif len(pn) == 1:
            self.call = lambda *v: fn(dict(zip(names, v)))
        else:
            raise BadInput(f"{role}: its parameters {pn} must be some of {names}, or one parameter that "
                           "receives the whole object")

    @staticmethod
    def _compile(src: str, role: str) -> Callable:
        try:
            return compile_code(src, kind="func", name=role)
        except SyntaxError as e:
            raise BadInput(f"{role}: {e.msg}") from None
        except Exception as e:  # noqa: BLE001
            raise BadInput(f"{role}: {type(e).__name__}: {e}") from None

    def set(self, **names: Any) -> None:
        self._globals.update(names)


# ---------------------------------------------------------------------------------------------- products

POOL_MAX = 200_000  # itertools.product copies each pool, so a longer pool is walked lazily


def pool_len(p) -> int:
    return max(0, p.stop - p.start) if isinstance(p, range) else len(p)


def lazy_product(pools: list):
    """itertools.product of ranges and lists, in the same order, without copying a very long pool."""
    if len(pools) == 1:
        for v in pools[0]:
            yield (v,)
        return
    big = [i for i, p in enumerate(pools) if pool_len(p) > POOL_MAX]
    if not big:
        yield from itertools.product(*pools)
        return
    i = big[0]
    tail = pools[i + 1:]
    for h in itertools.product(*pools[:i]):
        for v in pools[i]:
            if tail:
                for t in lazy_product(tail):
                    yield h + (v,) + t
            else:
                yield h + (v,)


# ---------------------------------------------------------------------------------------------- pacing

class Pacer:
    """Cheap time checks in a hot loop. ``check(n)`` is called once ``n >= pacer.next``; it returns True when
    the budget is spent, and about every 0.2 s it streams ``partial()`` so a killed run still reports."""

    def __init__(self, ctx, partial: Callable[[], dict], *, reserve: float = 0.05, every: float = 0.2):
        self.ctx, self.partial, self.reserve, self.every = ctx, partial, reserve, every
        self.next = 1      # the first time check comes after one object, so a slow callback cannot overshoot
        self._n = 0
        self._t = self._report = time.monotonic()

    def reset(self) -> None:
        """A new count starts (n restarts from 0)."""
        self.next, self._n, self._t = 1, 0, time.monotonic()

    def check(self, n: int) -> bool:
        now = time.monotonic()
        dn, dt = n - self._n, now - self._t
        self._n, self._t = n, now
        step = int(0.01 * dn / dt) if dt > 0 and dn > 0 else max(dn * 2, 1)
        self.next = n + min(max(step, 1), 1 << 20)
        if self.ctx.time_left() <= self.reserve:
            return True
        if now - self._report >= self.every:
            self._report = now
            self.ctx.progress(self.partial())
        return False
