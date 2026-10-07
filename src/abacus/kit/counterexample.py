"""counterexample: search for a point that breaks a claim (kit/04 s6).

Finding one is conclusive. Not finding one is not: the scope always says how many points were looked at and how.
"""
from __future__ import annotations

import bisect
import math
import secrets
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from .. import registry
from ..algo.rng import AbacusRNG
from ..evidence import Evidence
from . import _discrete as D
from ._discrete import BadInput

NAME = "counterexample"
DEFAULT_SAMPLES = 10_000
DEFAULT_K = 5
CLOSEST = 5
MAX_CORNERS = 64
ARITH = (ArithmeticError, ValueError)   # a point where the claim cannot be evaluated is not a counterexample

DESCRIPTION = (
    "Search for a case that breaks a claim. claim is a Python predicate over the named variables: an expression "
    "(a * b != 6), a lambda or a def; math, itertools, Fraction, sp (sympy) and np (numpy) are available. "
    "domain gives each variable one of: [a, b] (the integers a..b, inclusive), {real: [a, b]} (a real interval), "
    "{values: [..]} (a finite list), {sampler: 'lambda rng: rng.randint(1, 10**6)'} (code that draws a value from rng, "
    "which has randint, uniform, choice, random, shuffle, sample, plus py and np generators). "
    "mode is exhaustive (every point of finite domains, in order, first variable slowest), random (samples points, "
    "default 10000, after trying the corners of the domain) or both (exhaustive for a finite domain, spending up to "
    "half the time, then random sampling if that did not cover it). Stops after k counterexamples (default 5). "
    "margin is a Python expression for lhs - rhs of an inequality: the claim is then margin >= 0 if no claim is given, "
    "and the closest calls (smallest margins, with their points) are reported. Seeded for random mode. "
    "Result: counterexamples (the first k), checked, errored (points where the claim could not be evaluated), and "
    "closest. A search that finds nothing says how much it covered and does not show the claim holds."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "claim": {"type": "string"},
        "domain": {"type": "object"},
        "mode": {"enum": ["exhaustive", "random", "both"]},
        "margin": {"type": "string"},
        "samples": {"type": "integer"},
        "k": {"type": "integer"},
    },
    "required": ["domain"],
}


# ------------------------------------------------------------------------------------------------ domains

@dataclass
class Var:
    name: str
    kind: str                     # int | real | values | sampler
    lo: Any = None
    hi: Any = None
    values: list | None = None
    fn: D.UserFn | None = None

    @property
    def finite(self) -> bool:
        return self.kind in ("int", "values")

    def pool(self):
        return range(self.lo, self.hi + 1) if self.kind == "int" else self.values

    def size(self) -> int:
        return D.pool_len(self.pool())

    def sample(self, rng: AbacusRNG):
        if self.kind == "int":
            return rng.randint(self.lo, self.hi)
        if self.kind == "real":
            return rng.uniform(self.lo, self.hi)
        if self.kind == "values":
            return rng.choice(self.values)
        return self.fn.call(rng)

    def desc(self) -> str:
        if self.kind == "int":
            return f"{self.name} in [{self.lo}, {self.hi}]"
        if self.kind == "real":
            return f"{self.name} in real [{self.lo}, {self.hi}]"
        if self.kind == "values":
            shown = ", ".join(D.short(v, 20) for v in self.values[:6]) + (", ..." if len(self.values) > 6 else "")
            return f"{self.name} in {{{shown}}}"
        return f"{self.name} from a sampler"


def _real(v: Any, name: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise BadInput(f"domain {name}: real bounds must be finite numbers, got {D.short(v)}")
    return float(v)


def parse_domain(domain: Any) -> list[Var]:
    if not isinstance(domain, dict) or not domain:
        raise BadInput("domain must name at least one variable, e.g. {\"n\": [1, 100]}")
    out = []
    for name, d in domain.items():
        if not D.is_name(name):
            raise BadInput(f"domain: {name!r} cannot be used as a variable name")
        if isinstance(d, list):
            if len(d) != 2 or not all(D.is_int(v) for v in d):
                raise BadInput(f"domain {name}: an integer range is [a, b] with integers; "
                               "use {\"real\": [a, b]} for a real interval")
            if d[1] < d[0]:
                raise BadInput(f"domain {name}: [{d[0]}, {d[1]}] is empty")
            out.append(Var(name, "int", d[0], d[1]))
        elif isinstance(d, dict) and len(d) == 1:
            (kind, spec), = d.items()
            if kind == "real":
                if not (isinstance(spec, list) and len(spec) == 2):
                    raise BadInput(f"domain {name}: real needs [a, b]")
                lo, hi = _real(spec[0], name), _real(spec[1], name)
                if hi < lo:
                    raise BadInput(f"domain {name}: real [{spec[0]}, {spec[1]}] is empty")
                out.append(Var(name, "real", lo, hi))
            elif kind == "values":
                if not isinstance(spec, list) or not spec:
                    raise BadInput(f"domain {name}: values needs a non-empty list")
                out.append(Var(name, "values", values=spec))
            elif kind == "sampler":
                out.append(Var(name, "sampler", fn=D.UserFn(spec, "sampler", ["rng"], whole_object=True)))
            else:
                raise BadInput(f"domain {name}: unknown kind {kind!r}; use [a, b], real, values or sampler")
        else:
            raise BadInput(f"domain {name}: expected [a, b], {{\"real\": [a, b]}}, {{\"values\": [..]}} "
                           "or {\"sampler\": code}")
    return out


def _corners(vars: list[Var]) -> list[tuple]:
    """Every combination of the low and high ends of the ranges and intervals, when there are few enough."""
    if not all(v.kind in ("int", "real") for v in vars) or 2 ** len(vars) > MAX_CORNERS:
        return []
    ends = [list(dict.fromkeys((v.lo, v.hi))) for v in vars]
    out: list[tuple] = [()]
    for e in ends:
        out = [p + (x,) for p in out for x in e]
    return out


# ------------------------------------------------------------------------------------------------ the search

class _UserError(Exception):
    def __init__(self, role: str, point: tuple | None, exc: BaseException):
        super().__init__(role)
        self.role, self.point, self.exc = role, point, exc


class Search:
    def __init__(self, vars: list[Var], claim: D.UserFn | None, margin: D.UserFn | None, k: int):
        self.vars, self.names = vars, [v.name for v in vars]
        self.claim = claim.call if claim else None
        self.margin = margin.call if margin else None
        self.k = k
        self.checked = 0
        self.errored = 0
        self.first_error: tuple[BaseException, tuple] | None = None
        self.found: list[tuple] = []
        self.closest: list[tuple] = []     # sorted (margin, order, point)

    def point(self, p: tuple) -> dict:
        return dict(zip(self.names, p))

    def result(self) -> dict:
        res: dict = {"counterexamples": [self.point(p) for p in self.found], "checked": self.checked,
                     "errored": self.errored}
        if self.margin is not None:
            res["closest"] = [{"point": self.point(p), "margin": m} for m, _, p in self.closest]
        return res

    def scan(self, points, pacer: D.Pacer) -> str:
        """Check points in order. Returns "done", "found" (k counterexamples), or "stopped" (the pacer's time ran out)."""
        claim, margin, found, closest, k = self.claim, self.margin, self.found, self.closest, self.k
        n, base = 0, self.checked
        try:
            for p in points:
                if n >= pacer.next:  # at the top, so points that all fail to evaluate still hit the time check
                    self.checked = base + n
                    if pacer.check(n):
                        return "stopped"
                n += 1
                m = None
                if margin is not None:
                    try:
                        m = margin(*p)
                        if not isinstance(m, (int, float, Fraction)):
                            m = float(m)
                        if m != m:
                            raise ValueError("the margin is nan")
                    except ARITH as e:
                        self._error(e, p)
                        continue
                    except Exception as e:  # noqa: BLE001
                        self.checked = base + n
                        raise _UserError("margin", p, e) from None
                try:
                    ok = bool(claim(*p)) if claim is not None else m >= 0
                except ARITH as e:
                    self._error(e, p)
                    continue
                except Exception as e:  # noqa: BLE001
                    self.checked = base + n
                    raise _UserError("claim", p, e) from None
                if m is not None and (len(closest) < CLOSEST or m < closest[-1][0]):
                    bisect.insort(closest, (m, base + n, p))
                    if len(closest) > CLOSEST:
                        closest.pop()
                if not ok:
                    found.append(p)
                    if len(found) >= k:
                        return "found"
        finally:
            self.checked = base + n
        return "done"

    def _error(self, e: BaseException, p: tuple) -> None:
        self.errored += 1
        if self.first_error is None:
            self.first_error = (e, p)


def _random_points(vars: list[Var], rng: AbacusRNG, count: int, corners: list[tuple], ctr: list):
    """Corners first, then ``count`` random points. ctr[0] ends up as the number of random points drawn."""
    yield from corners
    for _ in range(count):
        try:
            p = tuple(v.sample(rng) for v in vars)
        except Exception as e:  # noqa: BLE001
            raise _UserError("sampler", None, e) from None
        ctr[0] += 1
        yield p


def _run(inp: dict, ctx) -> Evidence:
    vars_ = parse_domain(inp.get("domain"))
    names = [v.name for v in vars_]
    claim_src, margin_src = inp.get("claim"), inp.get("margin")
    if claim_src is None and margin_src is None:
        raise BadInput("give a claim, or a margin (the claim is then margin >= 0)")
    claim = D.UserFn(claim_src, "claim", names) if claim_src is not None else None
    margin = D.UserFn(margin_src, "margin", names) if margin_src is not None else None
    mode = inp.get("mode", "both")
    samples = inp.get("samples", DEFAULT_SAMPLES)
    k = inp.get("k", DEFAULT_K)
    if not D.is_int(samples) or samples < 1:
        raise BadInput("samples must be an integer >= 1")
    if not D.is_int(k) or k < 1:
        raise BadInput("k must be an integer >= 1")
    finite = all(v.finite for v in vars_)
    if mode == "exhaustive" and not finite:
        bad = ", ".join(v.name for v in vars_ if not v.finite)
        raise BadInput(f"exhaustive needs integer ranges or value lists; {bad} is a real interval or a sampler")
    seed = ctx.seed if ctx.seed is not None else secrets.randbelow(2 ** 32)
    rng = AbacusRNG(seed)
    dom_size = math.prod(v.size() for v in vars_) if finite else None
    dom_text = ", ".join(v.desc() for v in vars_)

    s = Search(vars_, claim, margin, k)
    notes: list[str] = []
    method_guess = "exhaustive" if mode == "exhaustive" else "sampled"

    def partial() -> dict:
        return {"result": s.result(), "method": method_guess,
                "scope": f"{dom_text}: stopped at the time budget after {s.checked} points; "
                         "the points beyond those were not checked"}

    parts: list[str] = []           # what was covered, in order
    status, err = "done", None
    covered_all = False             # the exhaustive pass consumed the whole domain
    ex_checked = 0
    sampled = False
    try:
        ctx.progress(partial())
        if finite and mode in ("exhaustive", "both"):
            # In "both" the exhaustive pass gets up to half of the time; the sampling pass gets the rest.
            reserve = 0.05 if mode == "exhaustive" else max(0.05, ctx.time_left() * 0.5)
            status = s.scan(D.lazy_product([v.pool() for v in vars_]), D.Pacer(ctx, partial, reserve=reserve))
            ex_checked = s.checked
            total = D.size_json(dom_size)
            handoff = status == "stopped" and mode == "both" and ctx.time_left() > 0.1
            if handoff:
                status = "done"
                parts.append(f"the first {ex_checked} of {total} points checked in order before the exhaustive "
                             "pass gave way to sampling")
            elif status == "done":
                covered_all = True
                parts.append(f"all {total} points checked in order")
            else:
                parts.append(f"{ex_checked} of {total} points checked in order")
        elif mode == "both":
            bad = ", ".join(v.name for v in vars_ if not v.finite)
            notes.append(f"exhaustive pass skipped: {bad} is a real interval or a sampler, so the domain is not finite")
        if status == "done" and not covered_all and mode in ("random", "both"):
            sampled = True
            corners = _corners(vars_)
            drawn = [0]
            before = s.checked
            status = s.scan(_random_points(vars_, rng, samples, corners, drawn), D.Pacer(ctx, partial))
            got = s.checked - before
            tail = f" plus {len(corners)} corner points of the domain" if corners else ""
            if status == "done":
                parts.append(f"{drawn[0]} random points sampled (seed {seed}){tail}")
            else:
                parts.append(f"{got} of {samples + len(corners)} random points sampled (seed {seed}){tail}")
    except _UserError as e:
        status, err = "error", e

    n_found = len(s.found)
    if status == "stopped":
        end = "stopped at the time budget; the rest were not checked"
    elif status == "error":
        end = f"stopped at an error in {err.role} after {s.checked} points"
    elif status == "found":
        end = (f"{n_found} broke the claim, the last at point {s.checked}; the search stopped there (k = {k}), "
               "so later points were not checked")
    elif n_found:
        end = f"{n_found} broke the claim"
    else:
        end = "none broke the claim"
    scope = f"{dom_text}: " + "; ".join(parts + [end])
    if n_found == 0 and status == "done" and not covered_all:
        scope += (". Sampling does not show that the claim holds where it did not look" if sampled
                  else ". Points that were not checked are not covered")
    ev = Evidence(button=NAME, result=s.result(), method="sampled" if sampled else "exhaustive", scope=scope,
                  complete=status in ("done", "found"), seed=seed, examples=[s.point(p) for p in s.found])
    if status == "error":
        ev.flag("bad_input", _error_message(err, names))
    if s.errored:
        e, p = s.first_error
        ev.flag("claim_error", f"the claim could not be evaluated at {s.errored} point(s), which are not counted as "
                f"counterexamples; the first was {D.short(s.point(p), 60)}: {type(e).__name__}: {e}")
    ev.notes.extend(notes)
    return ev


def _error_message(err: _UserError, names: list[str]) -> str:
    at = ""
    if err.point is not None:
        at = " at " + ", ".join(f"{n}={D.short(v, 40)}" for n, v in zip(names, err.point))
    return f"{err.role} raised {type(err.exc).__name__}: {err.exc}{at}"


@registry.button(NAME, description=DESCRIPTION, input_schema=SCHEMA, uses_seed=True)
def counterexample_button(inp: dict, ctx) -> Evidence:
    try:
        return _run(inp, ctx)
    except BadInput as e:
        return D.bad_input(NAME, "exhaustive" if inp.get("mode") == "exhaustive" else "sampled", str(e))

