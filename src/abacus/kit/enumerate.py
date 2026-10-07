"""enumerate: count the objects of a space that meet a condition (kit/04 s4).

Exhaustive: every object is generated and tested, so a count is exact when ``complete`` is true and a lower
bound on the matches among the objects reached when a budget stopped the run.
"""
from __future__ import annotations

import collections
import itertools
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

import sympy as sp

from .. import registry
from ..config import get_config
from ..evidence import Evidence, make_compare
from ..parsing import compile_code
from . import _discrete as D
from ._discrete import BadInput

NAME = "enumerate"
METHOD = "exhaustive"
MAX_ITEMS = 100_000      # an object with more items than this is out of reach
MAX_SWEEP = 1000
MAX_KEYS = 1000          # distinct group_by keys reported
EXACT_LOG10 = 300        # a space bigger than 10^300 is not sized exactly
LATTICE_STATES = 400_000
LN10 = math.log(10)

DESCRIPTION = (
    "Count the objects of a space that meet a condition, by exhaustive enumeration. "
    "space is one of: {product: {a: [1, 20], b: [1, 20]}} (inclusive integer ranges); {permutations: n or [items]}; "
    "{combinations: {of: n or [items], k}}; {subsets: n or [items]}; {compositions: {n, parts}} (positive parts); "
    "{partitions: n}; {words: {alphabet: 'HT', length: 10}}; {lattice_paths: {to: [m, n], steps: [[1, 0], [0, 1]]}} "
    "(steps default to right and up; every step must point forward along some direction so paths end); "
    "{graphs: {n}} (labelled graphs on vertices 0..n-1); {code: 'def space(): yield ...'}. "
    "An integer n stands for the items 0..n-1. "
    "where is a Python expression, lambda or def over the object: a product exposes its variables by name (a, b); "
    "every other space exposes the object as x (permutations, combinations, subsets, compositions and partitions "
    "are tuples, words are strings, a lattice path is the tuple of points visited from (0, 0) to the target, "
    "a graph is a frozenset of (i, j) edges with i < j and also exposes n). "
    "math, itertools, collections, Fraction, sp (sympy) and np (numpy) are available. "
    "sweep {n: [1, 12]} repeats for each n (n may be used in where and in the space as an integer expression such as "
    "'n' or '2*n+1'); counts then come back as a sequence. "
    "group_by is a key expression or def: the result is then a distribution instead of a count. "
    "Result: count (or counts per sweep value, or distribution) and space_size; examples are the first matching "
    "objects. Flags space_too_large when the space looks too big for the budget; the button still runs and returns "
    "a partial count with complete false."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "space": {"type": "object"},
        "where": {"type": "string"},
        "sweep": {"type": "object"},
        "group_by": {"type": "string"},
        "proposed": {},
    },
    "required": ["space"],
}


# ------------------------------------------------------------------------------------------------ spaces

@dataclass
class Space:
    desc: str
    make: Callable[[], Iterator]
    size: int | None                       # None: not known
    huge: bool = False                     # not sized because it is beyond 10^EXACT_LOG10, or too big to count
    fields: list[str] | None = None        # a product: the named variables; otherwise the object is `x`
    names: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    huge_why: str = ""                     # why a huge space was not sized, when that is not plain largeness


def intval(v: Any, what: str, env: dict) -> int:
    if D.is_int(v):
        return v
    if isinstance(v, str):
        try:
            r = compile_code(v, kind="expr", args=tuple(env))(*env.values())
        except Exception as e:  # noqa: BLE001
            raise BadInput(f"{what}: could not evaluate {v!r}: {type(e).__name__}: {e}") from None
        if D.is_int(r):
            return r
        raise BadInput(f"{what}: {v!r} evaluated to {r!r}, not an integer")
    raise BadInput(f"{what}: expected an integer, got {D.short(v)}")


def _items(spec: Any, what: str, env: dict):
    if isinstance(spec, list):
        if len(spec) > MAX_ITEMS:
            raise BadInput(f"{what}: more than {MAX_ITEMS} items")
        return spec
    n = intval(spec, what, env)
    if n < 0:
        raise BadInput(f"{what}: {n} is negative")
    if n > MAX_ITEMS:
        raise BadInput(f"{what}: {n} items is more than the {MAX_ITEMS} an object can hold here")
    return range(n)


def _repeat_notes(spec: Any, items) -> list[str]:
    """Items that repeat are told apart by position, so equal items count as different objects."""
    if isinstance(spec, list) and len({repr(v) for v in items}) < len(items):
        return ["the items repeat, and objects are counted by position: equal items are treated as different, "
                "so arrangements that look the same are counted separately"]
    return []


def _items_desc(spec: Any, items) -> str:
    if isinstance(spec, list):
        return f"the {len(items)} given items"
    if isinstance(spec, str):
        return f"0..({spec})-1"
    return f"0..{len(items) - 1}" if len(items) else "no items"


def _sized(lg10: float | None, exact: Callable[[], int]) -> tuple[int | None, bool]:
    """(size, huge): the exact size unless it is astronomically large, which is only flagged."""
    if lg10 is not None and lg10 > EXACT_LOG10:
        return None, True
    return exact(), False


def _lg_comb(n: int, k: int) -> float | None:
    if not 0 <= k <= n:
        return None
    return (math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)) / LN10


def _exactly(spec: Any, keys: set[str], what: str, form: str) -> dict:
    if not isinstance(spec, dict) or set(spec) != keys:
        raise BadInput(f"{what}: expected {form}")
    return spec


def _product(spec: Any, env: dict) -> Space:
    if not isinstance(spec, dict) or not spec:
        raise BadInput("product: expected {variable: [low, high], ...}")
    names, bounds, parts, lg10, empty = [], [], [], 0.0, False
    for name, b in spec.items():
        if not D.is_name(name):
            raise BadInput(f"product: {name!r} cannot be used as a variable name")
        if name in env:
            raise BadInput(f"product: {name!r} is also the sweep variable")
        if not isinstance(b, list) or len(b) != 2:
            raise BadInput(f"product: {name} needs [low, high]")
        lo, hi = intval(b[0], f"product {name} low", env), intval(b[1], f"product {name} high", env)
        names.append(name)
        bounds.append((lo, hi))
        parts.append(f"{name} in [{b[0]}, {b[1]}]")
        if hi < lo:
            empty = True
        else:
            lg10 += math.log10(hi - lo + 1)
    if empty:
        size, huge = 0, False
    else:
        size, huge = _sized(lg10, lambda: math.prod(hi - lo + 1 for lo, hi in bounds))
    return Space(", ".join(parts), lambda: D.lazy_product([range(lo, hi + 1) for lo, hi in bounds]), size, huge, fields=names)


def _permutations(spec: Any, env: dict) -> Space:
    items = _items(spec, "permutations", env)
    n = len(items)
    size, huge = _sized(math.lgamma(n + 1) / LN10, lambda: math.factorial(n))
    return Space(f"permutations of {_items_desc(spec, items)}", lambda: itertools.permutations(items), size, huge,
                 notes=_repeat_notes(spec, items))


def _combinations(spec: Any, env: dict) -> Space:
    spec = _exactly(spec, {"of", "k"}, "combinations", '{"of": n or [items], "k": k}')
    items = _items(spec["of"], "combinations of", env)
    k = intval(spec["k"], "combinations k", env)
    if k < 0:
        raise BadInput(f"combinations: k = {k} is negative")
    n = len(items)
    size, huge = _sized(_lg_comb(n, k), lambda: math.comb(n, k) if k <= n else 0)
    return Space(f"{k}-element combinations of {_items_desc(spec['of'], items)}",
                 lambda: itertools.combinations(items, k), size, huge, notes=_repeat_notes(spec["of"], items))


def _subsets(spec: Any, env: dict) -> Space:
    items = _items(spec, "subsets", env)
    n = len(items)
    size, huge = _sized(n * math.log10(2), lambda: 2 ** n)
    return Space(f"subsets of {_items_desc(spec, items)}",
                 lambda: itertools.chain.from_iterable(itertools.combinations(items, r) for r in range(n + 1)),
                 size, huge, notes=_repeat_notes(spec, items))


def _compositions_iter(n: int, k: int):
    if k == 0:
        if n == 0:
            yield ()
        return
    if n < k:
        return
    for cuts in itertools.combinations(range(1, n), k - 1):
        pts = (0,) + cuts + (n,)
        yield tuple(b - a for a, b in zip(pts, pts[1:]))


def _compositions(spec: Any, env: dict) -> Space:
    spec = _exactly(spec, {"n", "parts"}, "compositions", '{"n": n, "parts": k}')
    n, k = intval(spec["n"], "compositions n", env), intval(spec["parts"], "compositions parts", env)
    if n < 0 or k < 0:
        raise BadInput("compositions: n and parts must be at least 0")
    if n > MAX_ITEMS or k > MAX_ITEMS:
        raise BadInput(f"compositions: n and parts are limited to {MAX_ITEMS}")
    if k == 0 or n < k:
        size, huge = (1 if k == 0 and n == 0 else 0), False
    else:
        size, huge = _sized(_lg_comb(n - 1, k - 1), lambda: math.comb(n - 1, k - 1))
    return Space(f"compositions of {spec['n']} into {spec['parts']} positive parts",
                 lambda: _compositions_iter(n, k), size, huge)


def _partitions_iter(n: int):
    """Integer partitions as non-increasing tuples (Kelleher's accelerated ascending generator, reversed)."""
    if n == 0:
        yield ()
        return
    a = [0] * (n + 1)
    k, y = 1, n - 1
    while k != 0:
        x = a[k - 1] + 1
        k -= 1
        while 2 * x <= y:
            a[k] = x
            y -= x
            k += 1
        l = k + 1
        while x <= y:
            a[k], a[l] = x, y
            yield tuple(reversed(a[:k + 2]))
            x += 1
            y -= 1
        a[k] = x + y
        y = x + y - 1
        yield tuple(reversed(a[:k + 1]))


def _partitions(spec: Any, env: dict) -> Space:
    n = intval(spec, "partitions", env)
    if n < 0:
        raise BadInput(f"partitions: {n} is negative")
    if n > MAX_ITEMS:
        raise BadInput(f"partitions: n is limited to {MAX_ITEMS}")
    if n > 5000:
        size, huge = None, True
    else:
        size, huge = int(sp.functions.combinatorial.numbers.partition(n)), False
    return Space(f"partitions of {spec}", lambda: _partitions_iter(n), size, huge)


def _words(spec: Any, env: dict) -> Space:
    spec = _exactly(spec, {"alphabet", "length"}, "words", '{"alphabet": "HT", "length": 10}')
    alpha = spec["alphabet"]
    if not isinstance(alpha, (str, list)) or len(alpha) == 0:
        raise BadInput("words: alphabet must be a non-empty string or list")
    if len({repr(c) for c in alpha}) != len(alpha):
        raise BadInput("words: the alphabet repeats a symbol, which would count words twice")
    length = intval(spec["length"], "words length", env)
    if length < 0 or length > MAX_ITEMS:
        raise BadInput(f"words: length must be between 0 and {MAX_ITEMS}")
    a = len(alpha)
    size, huge = _sized(length * math.log10(a), lambda: a ** length)
    if isinstance(alpha, str):
        make = lambda: map("".join, itertools.product(alpha, repeat=length))  # noqa: E731
    else:
        make = lambda: itertools.product(alpha, repeat=length)  # noqa: E731
    return Space(f"words of length {spec['length']} over {alpha if isinstance(alpha, str) else a}"
                 + ("" if isinstance(alpha, str) else " symbols"), make, size, huge)


def _lattice(spec: Any, env: dict, ctx, deadline: float) -> Space:
    if not isinstance(spec, dict) or "to" not in spec or not set(spec) <= {"to", "steps"}:
        raise BadInput('lattice_paths: expected {"to": [m, n], "steps": [[1, 0], [0, 1]]}')
    to = spec["to"]
    if not isinstance(to, list) or len(to) != 2:
        raise BadInput("lattice_paths: to must be [m, n]")
    target = (intval(to[0], "lattice_paths to", env), intval(to[1], "lattice_paths to", env))
    raw = spec.get("steps", [[1, 0], [0, 1]])
    if (not isinstance(raw, list) or not raw
            or not all(isinstance(s, list) and len(s) == 2 and all(D.is_int(c) for c in s) for s in raw)):
        raise BadInput("lattice_paths: steps must be a non-empty list of [dx, dy] integer pairs")
    steps = [(s[0], s[1]) for s in raw]
    if len(set(steps)) != len(steps):
        raise BadInput("lattice_paths: steps repeats a step, which would count paths twice")
    w = next(((a, b) for a, b in sorted(itertools.product(range(-4, 5), repeat=2), key=lambda t: (abs(t[0]) + abs(t[1]), t))
              if (a, b) != (0, 0) and all(a * s[0] + b * s[1] > 0 for s in steps)), None)
    if w is None:
        raise BadInput("lattice_paths: the steps must all point forward along one direction, or a path could "
                       f"go on forever (steps {steps})")
    ways, why = _lattice_ways(steps, w, target, deadline)
    size = None if ways is None else ways.get((0, 0), 0)
    pot = lambda p: w[0] * p[0] + w[1] * p[1]  # noqa: E731
    tpot = pot(target)

    def make():
        origin = (0, 0)
        if ways is not None and ways.get(origin, 0) == 0:
            return
        path, stack = [origin], [0]
        if origin == target:
            yield (origin,)
            return
        work = 0
        while stack:
            work += 1
            if work & 8191 == 0 and ctx.time_left() <= 0.05:  # a long stretch with no path to yield
                raise _OutOfTime
            i = stack[-1]
            if i == len(steps):
                stack.pop()
                path.pop()
                continue
            stack[-1] = i + 1
            p, s = path[-1], steps[i]
            q = (p[0] + s[0], p[1] + s[1])
            if ways is not None:
                if ways.get(q, 0) == 0:
                    continue
            elif pot(q) > tpot:
                continue
            if q == target:
                yield tuple(path) + (q,)
            else:
                path.append(q)
                stack.append(0)

    return Space(f"lattice paths from (0, 0) to ({to[0]}, {to[1]}) with steps {[list(s) for s in steps]}",
                 make, size, ways is None, huge_why=why)


def _lattice_ways(steps, w, target, deadline: float = math.inf):
    """Paths from each position to the target, over every position a path can pass through; None when
    there are too many positions to hold, or counting them runs past ``deadline``; the second item says which."""
    pot = lambda p: w[0] * p[0] + w[1] * p[1]  # noqa: E731
    tpot = pot(target)
    forward_only = all(s[0] >= 0 and s[1] >= 0 for s in steps)

    def inside(p):
        if pot(p) > tpot:
            return False
        return not (forward_only and (p[0] > target[0] or p[1] > target[1]))

    seen, stack = {(0, 0)}, [(0, 0)]
    if not inside((0, 0)):
        return {}, ""
    pops = 0
    while stack:
        pops += 1
        p = stack.pop()
        for s in steps:
            q = (p[0] + s[0], p[1] + s[1])
            if q not in seen and inside(q):
                seen.add(q)
                stack.append(q)
        if len(seen) > LATTICE_STATES:
            return None, "states"
        if pops & 1023 == 0 and time.monotonic() > deadline:
            return None, "timeout"
    ways: dict = {}
    for p in sorted(seen, key=pot, reverse=True):
        ways[p] = 1 if p == target else sum(ways.get((p[0] + s[0], p[1] + s[1]), 0) for s in steps)
    return ways, ""


def _graphs(spec: Any, env: dict) -> Space:
    spec = _exactly(spec, {"n"}, "graphs", '{"n": n}')
    n = intval(spec["n"], "graphs n", env)
    if n < 0 or n > 60:
        raise BadInput("graphs: n must be between 0 and 60")
    edges = [(i, j) for i in range(n) for j in range(i + 1, n)]
    e = len(edges)
    size, huge = _sized(e * math.log10(2), lambda: 2 ** e)

    def make():
        for mask in range(1 << e):
            yield frozenset(ed for j, ed in enumerate(edges) if mask >> j & 1)

    return Space(f"labelled graphs on {spec['n']} vertices", make, size, huge, names={"n": n})


def _code(spec: Any, env: dict) -> Space:
    if not isinstance(spec, str) or not spec.strip():
        raise BadInput('code: expected the source of "def space(): yield ..."')
    fn = D.compile_def(spec, "space")
    fn.__globals__.update(env)

    def make():
        try:
            return iter(fn())
        except Exception as e:  # noqa: BLE001
            raise _UserError("space", None, e) from None

    return Space("objects yielded by the given space() code", make, None)


BUILDERS = {"product": _product, "permutations": _permutations, "combinations": _combinations,
            "subsets": _subsets, "compositions": _compositions, "partitions": _partitions, "words": _words,
            "lattice_paths": _lattice, "graphs": _graphs, "code": _code}


def build(space: Any, env: dict, ctx, deadline: float) -> Space:
    if not isinstance(space, dict) or len(space) != 1:
        raise BadInput(f"space must be an object with exactly one key, one of: {', '.join(BUILDERS)}")
    (kind, spec), = space.items()
    if kind not in BUILDERS:
        raise BadInput(f"unknown space {kind!r}; the spaces are: {', '.join(BUILDERS)}")
    if kind == "lattice_paths":
        return _lattice(spec, env, ctx, deadline)
    return BUILDERS[kind](spec, env)


# ------------------------------------------------------------------------------------------------ the run

class _OutOfTime(Exception):
    """Raised by a space's own generator when the budget ends between two objects."""


class _UserError(Exception):
    def __init__(self, role: str, obj: Any, exc: BaseException):
        super().__init__(role)
        self.role, self.obj, self.exc = role, obj, exc


class State:
    """Everything the result and the scope are built from, so a partial one can be sent at any moment."""

    def __init__(self, sw_name, sw_vals, grouped, has_where, per):
        self.sw_name, self.sw_vals, self.grouped, self.has_where = sw_name, sw_vals, grouped, has_where
        self.per = per
        self.counts: list[int] = []
        self.dists: list[dict] = []
        self.sizes: list[Any] = []
        self.examples: list = []
        self.checked_done = 0
        self.idx = 0
        self.finished = False
        self.truncated = False
        self.new_value(None)
        self.total_known: int | None = None

    def new_value(self, size) -> None:
        self.checked, self.count, self.size = 0, 0, size
        self.dist: collections.Counter = collections.Counter()
        self.ex: list = []
        self.first: dict = {}

    def fmt_dist(self, dist) -> dict:
        items = list(dist.items())
        try:
            items.sort(key=lambda kv: kv[0])
        except TypeError:
            items.sort(key=lambda kv: repr(kv[0]))
        if len(items) > MAX_KEYS:
            self.truncated = True
            keep = {id(kv) for kv in sorted(items, key=lambda kv: -kv[1])[:MAX_KEYS]}
            items = [kv for kv in items if id(kv) in keep]
        out = {D.key_str(k): c for k, c in items}
        if len(out) < len(items):  # a str key and a non-str key print the same: tell them apart
            out = {repr(k): c for k, c in items}
        return out

    def result(self) -> dict:
        if self.sw_name:
            done = len(self.counts)
            res: dict = {"sweep": {self.sw_name: self.sw_vals[:done]}, "counts": list(self.counts),
                         "space_size": [D.size_json(s) for s in self.sizes]}
            if self.grouped:
                res["distributions"] = [self.fmt_dist(d) for d in self.dists]
            if not self.finished:
                prog = {self.sw_name: self.sw_vals[self.idx], "count_so_far": self.count,
                        "objects_checked": self.checked, "space_size": D.size_json(self.size)}
                if self.grouped:
                    prog["distribution_so_far"] = self._partial_dist()
                res["in_progress"] = prog
            return res
        res = {"count": self.count, "space_size": D.size_json(self.size)}
        if self.grouped:
            res["distribution"] = self.fmt_dist(self.dist)
            res["distinct_keys"] = len(self.dist)
        if not self.finished:
            res["objects_checked"] = self.checked
        return res

    def _partial_dist(self):
        return self.fmt_dist(self.dist) if len(self.dist) <= 5000 else {"distinct_keys": len(self.dist)}

    def checked_total(self) -> int:
        return self.checked_done + (0 if self.finished and self.sw_name else self.checked)


def _fmt_obj(space: Space, obj: Any, sw: tuple[str | None, Any]) -> Any:
    out = dict(zip(space.fields, obj)) if space.fields is not None else obj
    name, value = sw
    if name is None:
        return out
    return {name: value, **out} if space.fields is not None else {name: value, "x": out}


def _scan(space: Space, wcall, gcall, st: State, pacer: D.Pacer, sw) -> str:
    """Walk one space. Returns "done" or "stopped"; raises _UserError when the caller's code fails."""
    star = space.fields is not None
    n = cnt = 0
    pacer.reset()
    dist, ex, first = st.dist, st.ex, st.first
    per = st.per
    try:
        for obj in space.make():
            n += 1
            if wcall is not None:
                try:
                    ok = bool(wcall(*obj) if star else wcall(obj))
                except Exception as e:  # noqa: BLE001
                    st.checked, st.count = n, cnt
                    raise _UserError("where", obj, e) from None
            else:
                ok = True
            if ok:
                cnt += 1
                if gcall is not None:
                    try:
                        key = gcall(*obj) if star else gcall(obj)
                        dist[key] += 1
                    except Exception as e:  # noqa: BLE001
                        st.checked, st.count = n, cnt - 1
                        raise _UserError("group_by", obj, e) from None
                    if len(first) < per and key not in first:
                        first[key] = None
                        ex.append({"key": key, "example": _fmt_obj(space, obj, sw)})
                elif len(ex) < per:
                    ex.append(_fmt_obj(space, obj, sw))
            if n >= pacer.next:
                st.checked, st.count = n, cnt
                if pacer.check(n):
                    return "stopped"
    except _UserError:
        raise
    except _OutOfTime:
        st.checked, st.count = n, cnt
        return "stopped"
    except Exception as e:  # noqa: BLE001  (the space's own code failed part-way)
        st.checked, st.count = n, cnt
        raise _UserError("space", None, e) from None
    st.checked, st.count = n, cnt
    return "done"


def _rate(space: Space, where: D.UserFn | None, gb: D.UserFn | None, extras: dict) -> float | None:
    """Seconds per object, from the first few hundred objects."""
    star = space.fields is not None
    try:
        if where:
            where.set(**extras)
        if gb:
            gb.set(**extras)
        wc, gc = (where.call if where else None), (gb.call if gb else None)
        t0, k = time.perf_counter(), 0
        for obj in itertools.islice(space.make(), 300):
            k += 1
            ok = (wc(*obj) if star else wc(obj)) if wc else True
            if ok and gc:
                gc(*obj) if star else gc(obj)
            if time.perf_counter() - t0 > 0.02:
                break
        return (time.perf_counter() - t0) / k if k else None
    except Exception:  # noqa: BLE001  (the real run reports it)
        return None


def _parse_sweep(sweep: Any) -> tuple[str | None, list]:
    if sweep is None:
        return None, [None]
    if not isinstance(sweep, dict) or len(sweep) != 1:
        raise BadInput('sweep must name exactly one variable, e.g. {"n": [1, 12]}')
    (name, b), = sweep.items()
    if not D.is_name(name):
        raise BadInput(f"sweep: {name!r} cannot be used as a variable name")
    if not (isinstance(b, list) and len(b) == 2 and all(D.is_int(v) for v in b)):
        raise BadInput("sweep: expected [low, high] with integers")
    if b[1] < b[0] or b[1] - b[0] + 1 > MAX_SWEEP:
        raise BadInput(f"sweep: needs low <= high and at most {MAX_SWEEP} values")
    return name, list(range(b[0], b[1] + 1))


def _scope(st: State, base: str, size_text: str, status: str, err: _UserError | None) -> str:
    cond = "against where" if st.has_where else "counted"
    total = st.checked_total()
    if status == "done":
        if st.total_known is not None:
            return f"{base}: all {size_text} objects checked {cond}" if st.has_where else f"{base}: all {size_text} objects counted"
        return f"{base}: every object the generator yielded ({total}) checked {cond}" if st.has_where \
            else f"{base}: every object the generator yielded ({total}) counted"
    where = f"after checking {total} of {size_text} objects" if st.total_known is not None \
        else f"after checking {total} objects"
    if status == "error":
        head = f"{base}: stopped at an error in {err.role} {where}"
    else:
        head = f"{base}: stopped at the time budget {where}"
    tail = "; the count covers only those objects" if not st.sw_name else "; the counts cover only those objects"
    if st.sw_name:
        done = len(st.counts)
        sw = st.sw_vals
        part = (f"{st.sw_name} = {sw[0]}..{sw[done - 1]} finished" if done > 1 else
                f"{st.sw_name} = {sw[0]} finished" if done == 1 else "no sweep value finished")
        tail = f"; {part}, {st.sw_name} = {sw[st.idx]} was partly checked and is not in counts"
    return head + tail


def _run(inp: dict, ctx) -> Evidence:
    cfg = get_config()
    sw_name, sw_vals = _parse_sweep(inp.get("sweep"))
    envs = [{sw_name: v} if sw_name else {} for v in sw_vals]
    deadline = time.monotonic() + 0.4 * ctx.time_left()   # sizing the spaces must leave time to enumerate them
    spaces = [build(inp.get("space"), env, ctx, deadline) for env in envs]
    fields = spaces[0].fields
    if sw_name is not None and fields is None:
        if sw_name == "x":
            raise BadInput("sweep: x is the name of the object in this space, so it cannot also be the sweep "
                           "variable; use another name such as n")
        for env, sp_ in zip(envs, spaces):
            if sw_name in sp_.names and sp_.names[sw_name] != env[sw_name]:
                raise BadInput(f"sweep: {sw_name} is also a name this space gives to where (it is the graph's "
                               "own n), and the two differ; use another sweep name")
    names = list(fields) if fields is not None else ["x"]
    whole = fields is None
    where = D.UserFn(inp["where"], "where", names, whole) if inp.get("where") is not None else None
    gb = D.UserFn(inp["group_by"], "group_by", names, whole) if inp.get("group_by") is not None else None

    sizes = [s.size for s in spaces]
    huge = any(s.huge for s in spaces)
    total = None if huge or any(z is None for z in sizes) else sum(sizes)
    st = State(sw_name, sw_vals, gb is not None, where is not None,
               per=max(1, cfg.max_examples // len(sw_vals)))
    st.total_known = total
    st.size = spaces[0].size
    base = spaces[0].desc + (f", for {sw_name} = {sw_vals[0]}..{sw_vals[-1]}" if sw_name else "")
    size_text = str(D.size_json(total)) if total is not None else "an unknown number of"

    ev = Evidence(button=NAME, result=None, method=METHOD, scope="x")
    # Is the space bigger than the budget can finish? Time a few hundred objects of the biggest case.
    if huge:
        whys = {s.huge_why for s in spaces if s.huge and s.huge_why}
        if whys == {"timeout"}:
            ev.flag("space_too_large", "the size estimate timed out before the lattice paths could be counted, so "
                    "the size is unknown (it may be very large); the run goes ahead and returns what it reaches")
        elif whys == {"states"}:
            ev.flag("space_too_large", f"the lattice has more than {LATTICE_STATES} positions, too many to size; "
                    "the run goes ahead and returns what it reaches")
        else:
            ev.flag("space_too_large", f"the space has more than 10^{EXACT_LOG10} objects (or too many to count, "
                    "or the size estimate timed out), far beyond any budget; the run goes ahead and returns what "
                    "it reaches")
    elif total is not None and total > 0:
        k = max(range(len(spaces)), key=lambda i: sizes[i])
        rate = _rate(spaces[k], where, gb, {**envs[k], **spaces[k].names})
        if rate and total * rate > ctx.time_left():
            ev.flag("space_too_large",
                    f"the space has {D.size_json(total)} objects; at about {1 / rate:.3g} objects per second that "
                    f"needs about {total * rate:.3g} s and {ctx.time_left():.3g} s of budget are left; the run goes "
                    "ahead and returns what it reaches")

    def partial() -> dict:
        return {"result": st.result(), "scope": _scope(st, base, size_text, "stopped", None), "method": METHOD}

    pacer = D.Pacer(ctx, partial)
    ctx.progress(partial())
    status, err = "done", None
    for i, (env, space) in enumerate(zip(envs, spaces)):
        st.idx = i
        st.new_value(space.size)
        extras = {**env, **space.names}
        if where:
            where.set(**extras)
        if gb:
            gb.set(**extras)
        try:
            status = _scan(space, where.call if where else None, gb.call if gb else None, st, pacer,
                           (sw_name, sw_vals[i]))
        except _UserError as e:
            status, err = "error", e
        if status != "done":
            break
        st.examples.extend(st.ex)
        if sw_name:
            st.counts.append(st.count)
            st.sizes.append(space.size)
            st.checked_done += st.checked
            if gb is not None:
                st.dists.append(st.dist)
    st.finished = status == "done"
    if status != "done":
        st.examples.extend(st.ex)

    ev.result = st.result()
    ev.complete = st.finished
    ev.scope = _scope(st, base, size_text, status, err)
    ev.examples = st.examples
    if status == "error":
        ev.flag("bad_input", _error_message(err, spaces[st.idx], sw_name, sw_vals[st.idx]))
    if status == "stopped" and not huge and any(z is None for z in sizes) and "space_too_large" not in             [f["code"] for f in ev.flags]:
        ev.flag("space_too_large", "the size of the space was unknown (a generator has no size estimate), so this "
                "could not be checked before the run; the budget stopped it, so the space is bigger than the "
                "budget could cover")
    for note in dict.fromkeys(n for s in spaces for n in s.notes):
        ev.notes.append(note)
    if st.truncated:
        ev.notes.append(f"distribution truncated to the {MAX_KEYS} most common of its keys")
    if inp.get("proposed") is not None:
        ev.compare = _compare(inp["proposed"], st)
        if not ev.complete:
            ev.notes.append("compare uses the partial count; the run did not finish")
    return ev


def _error_message(err: _UserError, space: Space, sw_name, sw_value) -> str:
    where = ""
    if err.obj is not None:
        where = " on " + (", ".join(f"{k}={D.short(v, 40)}" for k, v in zip(space.fields, err.obj))
                          if space.fields is not None else f"x={D.short(err.obj)}")
    sw = f" (with {sw_name}={sw_value})" if sw_name else ""
    return f"{err.role} raised {type(err.exc).__name__}: {err.exc}{where}{sw}"


def _compare(proposed: Any, st: State):
    if st.sw_name:
        return make_compare(proposed, list(st.counts))
    if st.grouped:
        computed = st.fmt_dist(st.dist)
        if isinstance(proposed, dict):
            proposed = {D.key_str(k) if not isinstance(k, str) else k: v for k, v in proposed.items()}
        return make_compare(proposed, computed)
    return make_compare(proposed, st.count)


@registry.button(NAME, description=DESCRIPTION, input_schema=SCHEMA)
def enumerate_button(inp: dict, ctx) -> Evidence:
    try:
        return _run(inp, ctx)
    except BadInput as e:
        return D.bad_input(NAME, METHOD, str(e))

