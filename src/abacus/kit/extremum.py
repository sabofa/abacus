"""`extremum`: maximise or minimise a function, e.g. to test an inequality (kit/04 s10).

Numeric search (grid, multistart local search, differential evolution) or, for small cases, a symbolic
Lagrange / KKT enumeration. A numeric search finds candidates, not proofs: the best point is the best one
the search saw, and a better one may exist where no start landed.
"""
from __future__ import annotations

import itertools
import math
import re
import warnings

import mpmath as _mp
import numpy as np
import sympy as sp
from scipy import optimize

from .. import parsing, registry
from ..evidence import Evidence
from . import _algebra as alg
from . import _continuous as C

NAME = "extremum"
BIG = 1e100
FEAS = 1e-6              # constraint violation allowed in a reported point
ACTIVE = 1e-6            # distance to a bound / constraint that counts as "on it"
NEAR_KEEP = 10
NEAR_GAP = 1e3          # a local result more than this many times (1 + |best|) worse than the best is not "near"
CROSS_RUNS = 3          # differential-evolution runs that cross-check a multistart which found several local optima
MAX_GRID = 40_000
_OPS = re.compile(r"<=|>=|==|=|<|>")

_BOUND = {"type": ["string", "number", "null"]}
_SCHEMA = {
    "type": "object", "required": ["f", "vars"], "additionalProperties": False,
    "properties": {
        "f": {"anyOf": [{"type": "string", "minLength": 1},
                        {"type": "object", "required": ["code"], "additionalProperties": False,
                         "properties": {"code": {"type": "string", "minLength": 1}}}],
              "description": "The function to optimise. A string is an expression in the variable names "
                             "('x + 1/x', 'x*y*(1-x-y)'; ^ is a power). {\"code\": ...} is Python run as code "
                             "(a lambda or def taking the variables in order, or an expression over the names); "
                             "math, np, sp and Fraction are available."},
        "vars": {"type": "object", "minProperties": 1,
                 "additionalProperties": {"anyOf": [
                     {"type": "array", "minItems": 2, "maxItems": 2, "items": _BOUND},
                     {"type": "object", "additionalProperties": False,
                      "properties": {"min": _BOUND, "max": _BOUND}}]},
                 "description": "Each variable with its bounds: {\"x\": [0, \"oo\"], \"y\": [-1, 1]} or "
                                "{\"x\": {\"min\": 0}}. Use \"oo\", \"-oo\" or null for no bound; bounds may be "
                                "expressions like \"pi\". Bounds are closed."},
        "constraints": {"type": "array", "items": {"type": "string", "minLength": 1},
                        "description": "Relations in the variables, e.g. 'x + y == 2', 'x*y >= 1', 'x**2 + y**2 <= 4'. "
                                       "A strict < or > is treated as <= or >=."},
        "goal": {"enum": ["min", "max"], "default": "min"},
        "method": {"enum": ["auto", "grid", "multistart", "evolution", "lagrange"], "default": "auto",
                   "description": "auto: multistart local search (evolution when there are many variables); grid: "
                                  "a grid, then local polish (equalities must be solvable for a variable); "
                                  "multistart: random starts; evolution: differential evolution; lagrange: exact "
                                  "critical points by sympy, small cases only (at most 3 variables)."},
        "starts": {"type": "integer", "minimum": 1, "maximum": 100000,
                   "description": "Local searches (multistart) or independent runs (evolution)."},
        "grid_points": {"type": "integer", "minimum": 9, "maximum": 2000000,
                        "description": f"Grid method: about this many points in all (default {MAX_GRID})."},
        "proposed": {"description": "A value to compare with the best value found (number or expression). Sets "
                                    "`compare`: equal within the search tolerance (numeric) or exactly (lagrange)."},
    },
}


class _Bad(ValueError):
    pass


# ----------------------------------------------------------------------------- reading the input


def _bound(v, what: str):
    """(float, sympy value or None) of a bound; None / oo / inf strings are +-inf (sign decided by the caller)."""
    if v is None:
        return None, None
    if isinstance(v, bool):
        raise _Bad(f"{what}: a bound must be a number, an expression, or null")
    if isinstance(v, (int, float)):
        if not math.isfinite(v):
            return None, None
        return float(v), sp.nsimplify(v, rational=True) if isinstance(v, float) else sp.Integer(v)
    s = str(v).strip().lower().lstrip("+")
    if s in ("oo", "inf", "infinity", "-oo", "-inf", "-infinity"):
        return (math.inf if not s.startswith("-") else -math.inf), None
    try:
        e = C.parse(v)
        C.check_function(e, [], what)
    except ValueError as exc:
        raise _Bad(f"{what}: {exc}") from None
    if not e.is_number or e.is_real is False:
        raise _Bad(f"{what}: {v!r} is not a real number")
    x = float(sp.N(e, 30))
    return x, e


def _read_vars(spec: dict):
    names, lo, hi, lo_e, hi_e = [], [], [], [], []
    for name, b in spec.items():
        if not re.match(alg.IDENT, name):
            raise _Bad(f"variable name {name!r} must be a plain name such as x")
        try:
            C.parse(name)
        except ValueError as exc:
            raise _Bad(f"variable name {name!r}: {exc}") from None
        a, z = (b[0], b[1]) if isinstance(b, list) else (b.get("min", b.get("lo")), b.get("max", b.get("hi")))
        (l, le), (h, he) = _bound(a, f"the lower bound of {name}"), _bound(z, f"the upper bound of {name}")
        l = -math.inf if l is None else l
        h = math.inf if h is None else h
        if l == math.inf or h == -math.inf or l > h:
            raise _Bad(f"the bounds of {name} are empty: [{a}, {z}]")
        names.append(name)
        lo.append(l)
        hi.append(h)
        lo_e.append(le)
        hi_e.append(he)
    return names, np.array(lo), np.array(hi), lo_e, hi_e


def _read_constraint(src: str, names):
    """(sympy g, kind, text): g >= 0 for 'ge', g == 0 for 'eq'."""
    ops = list(_OPS.finditer(src))
    if len(ops) != 1:
        raise _Bad(f"constraint {src!r} must be one relation such as 'x + y == 2' or 'x*y >= 1' (one of "
                   f"==, =, <=, >=, <, >)")
    op = ops[0].group()
    try:
        lhs, rhs = C.parse(src[:ops[0].start()], names), C.parse(src[ops[0].end():], names)
        C.check_function(lhs - rhs, names, f"constraint {src!r}")
    except ValueError as exc:
        raise _Bad(str(exc)) from None
    strict = op in ("<", ">")
    if op in ("=", "=="):
        return lhs - rhs, "eq", src.strip(), strict
    return (lhs - rhs if op in (">", ">=") else rhs - lhs), "ge", src.strip(), strict


def _code_function(src: str, names):
    m = re.match(r"\s*def\s+(\w+)", src)
    try:
        if m:
            return parsing.compile_code(src, kind="func", name=m.group(1))
        if src.strip().startswith("lambda"):
            return parsing.compile_code(src.strip(), kind="expr", args=())()
        return parsing.compile_code(src.strip(), kind="expr", args=tuple(names))
    except (SyntaxError, ValueError, NameError, TypeError) as exc:
        raise _Bad(f"could not compile f: {type(exc).__name__}: {exc}") from None


def _to_float(r) -> float:
    """A real float, or nan if r is complex with a real imaginary part or not a number at all."""
    if isinstance(r, np.ndarray) and r.size == 1:
        r = r.item()
    if isinstance(r, (complex, np.complexfloating)):
        c = complex(r)
        return c.real if abs(c.imag) <= 1e-12 * (1 + abs(c.real)) else math.nan
    try:
        return float(r)
    except TypeError:
        c = complex(r)
        return c.real if abs(c.imag) <= 1e-12 * (1 + abs(c.real)) else math.nan


ARITH = (ArithmeticError, ValueError)   # a point where f is undefined is infeasible, not an error


class Problem:
    """f, the bounds and the constraints, with every evaluation guarded. Minimises sign * f."""

    def __init__(self, names, lo, hi, f, cons, sign, is_code=False, exprs=None):
        self.names, self.lo, self.hi, self.d = list(names), lo, hi, len(names)
        self.f, self.cons, self.sign, self.is_code = f, cons, sign, is_code
        self.exprs = exprs        # (f_expr, [(g_expr, kind, text)]) when everything is a sympy expression
        self.evals = 0
        self.undefined = 0

    def _call(self, fn, x):
        self.evals += 1
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                a = [float(v) for v in x] if self.is_code else list(np.asarray(x, dtype=float))
                v = _to_float(fn(*a))
            except ARITH:
                v = math.nan
        if not math.isfinite(v):
            self.undefined += 1
            return math.nan
        return v

    def value(self, x) -> float:
        return self._call(self.f, x)

    def g(self, x) -> float:
        v = self.value(x)
        return BIG if math.isnan(v) else self.sign * v

    def con_values(self, x):
        return [self._call(fn, x) for fn, _k, _t in self.cons]

    def violation(self, x) -> float:
        worst = 0.0
        for v, (_fn, kind, _t) in zip(self.con_values(x), self.cons):
            if math.isnan(v):
                return math.inf
            worst = max(worst, -v if kind == "ge" else abs(v))
        return worst

    def feasible(self, x) -> bool:
        return self.violation(x) <= FEAS and bool(np.all(x >= self.lo - 1e-12) and np.all(x <= self.hi + 1e-12))

    def draw(self, rng):
        u, w = rng.random(self.d), rng.random(self.d)
        x = np.empty(self.d)
        for i in range(self.d):
            lo, hi = self.lo[i], self.hi[i]
            if math.isfinite(lo) and math.isfinite(hi):
                x[i] = lo + (hi - lo) * u[i]
            elif math.isfinite(lo):
                x[i] = lo + 10 ** (-2 + 5 * u[i])
            elif math.isfinite(hi):
                x[i] = hi - 10 ** (-2 + 5 * u[i])
            else:
                x[i] = (1 if w[i] < 0.5 else -1) * 10 ** (-2 + 5 * u[i])
        return x

    def axis(self, i: int, n: int):
        lo, hi = self.lo[i], self.hi[i]
        if math.isfinite(lo) and math.isfinite(hi):
            return list(np.linspace(lo, hi, n))
        k = max(1, (n - 1) // 2)
        off = list(np.geomspace(1e-2, 1e3, k))
        if math.isfinite(lo):
            return [lo] + [lo + o for o in off]
        if math.isfinite(hi):
            return [hi] + [hi - o for o in off]
        return [0.0] + [o for o in off] + [-o for o in off]


def _build(names, lo, hi, f, cons_exprs, sign, *, f_expr=None, code_fn=None):
    syms = [sp.Symbol(n) for n in names]
    cons = []
    for g, kind, text, _strict in cons_exprs:
        cons.append((sp.lambdify(syms, g, modules=["scipy", "numpy"]), kind, text))
    if code_fn is not None:
        return Problem(names, lo, hi, code_fn, cons, sign, is_code=True)
    fn = sp.lambdify(syms, f_expr, modules=["scipy", "numpy"])
    return Problem(names, lo, hi, fn, cons, sign, exprs=(f_expr, cons_exprs))


# ----------------------------------------------------------------------------- local search


def _local(P: Problem, x0):
    bounds = [(None if not math.isfinite(l) else l, None if not math.isfinite(h) else h)
              for l, h in zip(P.lo, P.hi)]
    x0 = np.clip(x0, P.lo, P.hi)
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            if not P.cons:
                res = optimize.minimize(P.g, x0, method="L-BFGS-B", bounds=bounds,
                                        options={"maxiter": 500, "ftol": 1e-15, "gtol": 1e-10})
            else:
                cs = []
                for fn, kind, _t in P.cons:
                    def make(fn=fn, kind=kind):
                        def c(x):
                            v = P._call(fn, x)
                            return (-BIG if kind == "ge" else BIG) if math.isnan(v) else v
                        return c
                    cs.append({"type": "ineq" if kind == "ge" else "eq", "fun": make()})
                res = optimize.minimize(P.g, x0, method="SLSQP", bounds=bounds, constraints=cs,
                                        options={"maxiter": 300, "ftol": 1e-13})
        except (ValueError, ArithmeticError, np.linalg.LinAlgError):
            return None
    x = np.clip(np.asarray(res.x, dtype=float), P.lo, P.hi)
    if not np.all(np.isfinite(x)):
        return None
    return x


class Found:
    """What the search has seen: local optima (feasible), with how many starts reached each."""

    def __init__(self, P: Problem):
        self.P = P
        self.pts: list[tuple[float, np.ndarray]] = []    # (g, x) feasible local results
        self.starts = 0
        self.infeasible = 0
        self.at_infinity: list[str] = []   # unbounded variables along which the best point can be pushed for free
        self.dropped = 0                   # local results too far from the best to be called near-optimal

    def check_infinity(self) -> bool:
        """True once the best point so far can be pushed toward infinity at no loss: the optimum is then an infimum
        (or supremum) that is approached and not attained, and more searching cannot improve on it."""
        if not self.pts:
            return False
        g, x = min(self.pts, key=lambda t: t[0])
        self.at_infinity = _infinity_probe(self.P, x, g)
        return bool(self.at_infinity)

    def add(self, x) -> None:
        if x is None:
            self.infeasible += 1
            return
        g = self.P.g(x)
        if g >= BIG or not self.P.feasible(x):
            self.infeasible += 1
            return
        self.pts.append((g, np.array(x)))

    def clusters(self):
        out = []   # [g, x, hits]
        for g, x in sorted(self.pts, key=lambda t: (t[0], tuple(t[1]))):
            for c in out:
                if np.all(np.abs(c[1] - x) <= 1e-3 * (1 + np.abs(x))):
                    c[2] += 1
                    break
            else:
                out.append([g, x, 1])
        return out


def _distinct_optima(found: Found) -> int:
    """How many local optima with distinct values the search has found (equal values are ties, not alternatives)."""
    cl = found.clusters()
    if not cl:
        return 0
    vals = []
    for g, _x, _h in cl:
        if abs(g - cl[0][0]) > NEAR_GAP * (1 + abs(cl[0][0])):
            continue   # an unconverged run, not a local optimum
        if all(abs(g - v) > 1e-4 * (1 + abs(v)) for v in vals):
            vals.append(g)
    return len(vals)


def _spread(found: Found) -> float:
    """The largest difference between the values of the (reasonably close) local optima found."""
    cl = found.clusters()
    if len(cl) < 2:
        return 0.0
    best = cl[0][0]
    close = [abs(g - best) for g, _x, _h in cl if abs(g - best) <= NEAR_GAP * (1 + abs(best))]
    return max(close) if close else 0.0


def _pool_order(P: Problem, rng, n: int):
    pts = [P.draw(rng) for _ in range(n)]
    scored = []
    for i, x in enumerate(pts):
        g = P.g(x)
        v = P.violation(x) if P.cons else 0.0
        scored.append((BIG * 10 if (g >= BIG or not math.isfinite(v)) else g + 1e6 * v, i))
    order = [i for _s, i in sorted(scored)]
    return pts, order


def _multistart(P, rng, ctx, starts, found: Found, report):
    pool_n = max(50, 8 * starts)
    pts, order = _pool_order(P, rng, pool_n)
    n_best = (starts + 1) // 2
    picks = order[:n_best]
    rest = [i for i in order[n_best:]]
    rest_pick = rng.permutation(len(rest))[:starts - n_best]
    picks += [rest[j] for j in rest_pick]
    for i in picks:
        if ctx.time_left() <= 0:
            return True
        found.starts += 1
        found.add(_local(P, pts[i]))
        report()
        if found.check_infinity():
            return False
    return False


def _evolution(P, rng, ctx, runs, found: Found, report):
    win_lo, win_hi = P.lo.copy(), P.hi.copy()
    for i in range(P.d):
        if not math.isfinite(win_lo[i]) and not math.isfinite(win_hi[i]):
            win_lo[i], win_hi[i] = -1e3, 1e3
        elif not math.isfinite(win_lo[i]):
            win_lo[i] = win_hi[i] - 1e3
        elif not math.isfinite(win_hi[i]):
            win_hi[i] = win_lo[i] + 1e3

    def obj(x):
        g = P.g(x)
        if g >= BIG:
            return BIG
        return g + 1e6 * P.violation(x) if P.cons else g

    for _ in range(runs):
        if ctx.time_left() <= 0:
            return True
        found.starts += 1
        seed = int(rng.integers(0, 2 ** 31 - 1))
        stop = []

        def cb(xk, convergence=None):
            if ctx.time_left() <= 0:
                stop.append(1)
                return True
            return False

        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = optimize.differential_evolution(obj, list(zip(win_lo, win_hi)), seed=seed, maxiter=200,
                                                  popsize=15, tol=1e-10, polish=False, updating="immediate",
                                                  callback=cb)
        x = np.asarray(res.x, dtype=float)
        polished = _local(P, x)
        found.add(polished if polished is not None else x)
        report()
        if stop:
            return True
        if found.check_infinity():
            return False
    return False


def _grid(P: Problem, ctx, total, found: Found, report):
    d = P.d
    per = max(3, min(2001, int(total ** (1.0 / d)))) if d > 1 else min(2001, max(total, 9))
    axes = [P.axis(i, per) for i in range(d)]
    keep: list[tuple[float, tuple]] = []
    n = 0
    for pt in itertools.product(*axes):
        n += 1
        if n % 512 == 0 and ctx.time_left() <= 0:
            found.grid_points = n
            return True
        x = np.array(pt)
        g = P.g(x)
        if g >= BIG or (P.cons and P.violation(x) > 1e-9):
            continue
        keep.append((g, pt))
        if len(keep) > 400:
            keep.sort()
            keep = keep[:40]
    found.grid_points = n
    keep.sort()
    seeds = []
    for g, pt in keep:
        x = np.array(pt)
        if all(np.any(np.abs(x - y) > 1e-3 * (1 + np.abs(x))) for y in seeds):
            seeds.append(x)
        if len(seeds) >= 8:
            break
    for x in seeds:
        found.starts += 1
        loc = _local(P, x)
        found.add(loc if loc is not None else x)   # the polished point only: the raw grid seed is not a result
        report()
        if ctx.time_left() <= 0:
            return True
    return False


# ----------------------------------------------------------------------------- reporting


def _describe_active(P: Problem, x):
    out = []
    for i, nm in enumerate(P.names):
        if math.isfinite(P.lo[i]) and x[i] <= P.lo[i] + ACTIVE * (1 + abs(P.lo[i])):
            out.append(f"{nm} = {P.lo[i]:g} (lower bound)")
        elif math.isfinite(P.hi[i]) and x[i] >= P.hi[i] - ACTIVE * (1 + abs(P.hi[i])):
            out.append(f"{nm} = {P.hi[i]:g} (upper bound)")
    for v, (_fn, kind, text) in zip(P.con_values(x), P.cons):
        if kind == "ge" and not math.isnan(v) and v <= ACTIVE:
            out.append(f"{text} (inequality constraint holds with equality)")
    return out


def _entry(P: Problem, x, g, best_g, hits=None):
    e = {"value": P.sign * g, "point": {n: float(v) for n, v in zip(P.names, x)}}
    if best_g is not None:
        e["gap"] = abs(g - best_g)
    if hits is not None:
        e["found_by"] = hits
    return e


def _infinity_probe(P: Problem, x, g0):
    """Names of unbounded variables along which moving far away is as good as the best point."""
    hits = []
    for i, nm in enumerate(P.names):
        for direction, bound in ((1, P.hi[i]), (-1, P.lo[i])):
            if math.isfinite(bound):
                continue
            for k in (3, 6):
                y = x.copy()
                y[i] += direction * 10.0 ** k
                gy = P.g(y)
                if gy < BIG and P.feasible(y) and gy <= g0 + 1e-9 * (1 + abs(g0)):
                    hits.append(nm)
                    break
            else:
                continue
            break
    return hits


def _result_from(P: Problem, found: Found):
    cl = found.clusters()
    if not cl:
        return None, [], []
    best_g, best_x, best_hits = cl[0]
    best = _entry(P, best_x, best_g, None, best_hits)
    close = [c for c in cl[1:] if abs(c[0] - best_g) <= NEAR_GAP * (1 + abs(best_g))]
    found.dropped = len(cl) - 1 - len(close)
    near = [_entry(P, x, g, best_g, hits) for g, x, hits in close[:NEAR_KEEP]]
    return best, near, cl


def _finish_numeric(inp, P: Problem, found: Found, ctx, methods, stopped, extra_scope, seed, notes0, multimodal=0.0):
    best, near, cl = _result_from(P, found)
    notes = list(notes0)
    flags = []
    result = {"goal": inp.get("goal", "min"), "best": best, "near_optimal": near,
              "starts": found.starts, "feasible_runs": len(found.pts), "evaluations": P.evals,
              "methods_run": methods}
    if best is not None:
        bx = cl[0][1]
        active = _describe_active(P, bx)
        result["on_boundary"] = bool(active)
        result["active"] = active
        if active:
            flags.append(("boundary_optimum", "the best point lies on the boundary of the feasible region: "
                                              + "; ".join(active)))
        far = _infinity_probe(P, bx, cl[0][0])
        if far:
            flags.append(("optimum_at_infinity", f"moving {', '.join(far)} far toward infinity is as good as the "
                                                 f"best point, so the optimum may be an infimum approached but not "
                                                 f"attained"))
            notes.append("an unbounded variable can be pushed far away at no loss: the value reported may be an "
                         "infimum (or supremum) that is only approached, not attained")
        if found.infeasible and found.infeasible >= found.starts and found.starts:
            notes.append("no search converged to a feasible point except those reported")
    else:
        result["on_boundary"] = None
        result["active"] = []
        if not stopped:
            flags.append(("no_feasible_point", "no feasible point was found; the constraints may be unsatisfiable, or "
                                               "the search did not reach the feasible region"))
    if P.undefined:
        notes.append(f"f or a constraint was undefined (division by zero, a square root of a negative ...) at "
                     f"{P.undefined} of {P.evals} evaluations; those points were skipped, so a bound at which "
                     f"f is singular is never reported as the optimum")
    if found.dropped:
        notes.append(f"{found.dropped} local result(s) more than {NEAR_GAP:g} times (1 + |best|) worse than the best "
                     f"were left out of near_optimal: they are unconverged runs, not near-optimal points")
    if multimodal:
        flags.append(("multimodal", f"several distinct local optima were found (values differ by up to "
                                    f"{_mp.nstr(multimodal, 3)}): the global optimum may be another one. Numeric search "
                                    f"finds candidates, not proofs"))
        notes.append("the function has several local optima; a differential-evolution run cross-checked the "
                     "multistart, but neither proves that the best value found is the global optimum")
    notes.append("numeric search finds candidates, not proofs: the best point is the best one seen, and a better "
                 "one may lie where no start landed. near_optimal lists the other distinct local optima found (ties "
                 "show equality cases and symmetry)")
    if any(math.isinf(v) for v in P.lo) or any(math.isinf(v) for v in P.hi):
        notes.append("an unbounded variable is sampled on a logarithmic window from its finite bound (offsets 0.01 to "
                     "1000, or +-1000 about 0); an optimum far outside it is not seen")
    scope = (f"{'+'.join(methods)} for the {inp.get('goal', 'min')}imum of f over {P.d} variable(s): {found.starts} "
             f"search(es) run{extra_scope}, {len(found.pts)} converged to a feasible point; numeric search, "
             f"candidates not proofs")
    ev = Evidence(button=NAME, result=result, method="search", scope=scope, complete=not stopped,
                  precision={"value_tolerance": 1e-9, "point_tolerance": 1e-5,
                             "note": "float64 local optimiser; the value is f at the point reported, the point is "
                                     "accurate to about the square root of machine precision for smooth f"},
                  notes=notes, seed=seed)
    for code, msg in flags:
        ev.flag(code, msg)
    if stopped:
        C.budget_stop(ev, "the search was cut short, so the result is the best found so far" if best is not None
                      else "no search finished")
    if "proposed" in inp and best is not None:
        C.tolerance_compare(ev, inp["proposed"], best["value"], 1e-7 * (1 + abs(best["value"])), lambda s: C.parse(s))
    return ev


# ----------------------------------------------------------------------------- grid with equalities


def _eliminate(f_expr, cons, names, lo, hi, lo_e, hi_e):
    """Solve each equality for one variable and substitute it away. Returns (f, cons, kept names, kept index,
    expressions of the eliminated variables in the kept ones)."""
    syms = {n: sp.Symbol(n) for n in names}
    remaining = list(names)
    subs: dict = {}
    f = f_expr
    cons = list(cons)
    while True:
        eqs = [c for c in cons if c[1] == "eq"]
        if not eqs:
            break
        g, _kind, text, strict = eqs[0]
        cons.remove(eqs[0])
        g = sp.simplify(g)
        if not (g.free_symbols & {syms[n] for n in remaining}):
            if g != 0:
                raise _Bad(f"the equality {text!r} cannot hold after the earlier ones were used")
            continue
        for v in remaining:
            if syms[v] not in g.free_symbols:
                continue
            try:
                sols = sp.solve(g, syms[v])
            except (NotImplementedError, ValueError, TypeError):
                continue
            if len(sols) == 1 and syms[v] not in sols[0].free_symbols and sols[0].is_real is not False:
                s = sols[0]
                break
        else:
            raise _Bad(f"method grid could not solve the equality {text!r} for a single value of one variable "
                       f"(it has none or several solutions); use method multistart or evolution, which handle "
                       f"equalities directly")
        i = names.index(v)
        f = f.subs(syms[v], s)
        cons = [(c.subs(syms[v], s), k, t, st) for c, k, t, st in cons]
        subs = {k: e.subs(syms[v], s) for k, e in subs.items()}
        subs[v] = s
        if math.isfinite(lo[i]):
            cons.append((s - lo_e[i], "ge", f"{v} >= {lo_e[i]} (bound of an eliminated variable)", False))
        if math.isfinite(hi[i]):
            cons.append((hi_e[i] - s, "ge", f"{v} <= {hi_e[i]} (bound of an eliminated variable)", False))
        remaining.remove(v)
    return f, cons, remaining, subs


# ----------------------------------------------------------------------------- lagrange


def _lagrange(inp, ctx, names, lo, hi, lo_e, hi_e, f_expr, cons, sign):
    d = len(names)
    ineq = [c for c in cons if c[1] == "ge"]
    eqs = [c for c in cons if c[1] == "eq"]
    if d > 3 or len(ineq) > 3:
        raise _Bad(f"method lagrange is for small cases (at most 3 variables and 3 inequalities; got {d} "
                   f"and {len(ineq)}); use multistart")
    syms = [sp.Symbol(n) for n in names]
    options = []
    for i in range(d):
        o = ["free"]
        if math.isfinite(lo[i]):
            o.append("lo")
        if math.isfinite(hi[i]):
            o.append("hi")
        options.append(o)
    candidates: dict = {}
    complete = True
    notes: list[str] = []
    family = False
    total = 0
    for state in itertools.product(*options):
        for act in itertools.product((False, True), repeat=len(ineq)):
            if ctx.time_left() <= 0:
                return None, False, notes + ["stopped at the time budget before every case was solved"]
            total += 1
            fixed = {syms[i]: (lo_e[i] if s == "lo" else hi_e[i]) for i, s in enumerate(state) if s != "free"}
            free = [syms[i] for i, s in enumerate(state) if s == "free"]
            active = [c[0] for c in eqs] + [c[0] for c, a in zip(ineq, act) if a]
            where = [f"{names[i]} at its {'lower' if s == 'lo' else 'upper'} bound" for i, s in enumerate(state)
                     if s != "free"] + [f"{c[2]} with equality" for c, a in zip(ineq, act) if a]
            fs = f_expr.subs(fixed)
            acts = [a.subs(fixed) for a in active]
            if not free:
                sols = [{}]
            else:
                lams = list(sp.symbols(f"_l0:{len(acts)}")) if acts else []
                lag = fs - sum((l * a for l, a in zip(lams, acts)), sp.Integer(0))
                system = [sp.diff(lag, u) for u in free] + acts
                try:
                    sols = sp.solve(system, free + lams, dict=True)
                except (NotImplementedError, ValueError, TypeError, ZeroDivisionError, RecursionError):
                    complete = False
                    notes.append(f"sympy could not solve the critical-point equations for the case "
                                 f"{', '.join(where) or 'interior'}")
                    continue
            for sol in sols:
                pt = dict(fixed)
                ok = True
                for u in free:
                    val = sol.get(u)
                    if val is None or val.free_symbols & set(free):
                        ok = False
                        break
                    if val.free_symbols:   # a free multiplier left over is fine; a free coordinate is not
                        ok = False
                        break
                    pt[u] = val
                if not ok:
                    family = True
                    continue
                try:
                    vec = [pt[s] for s in syms]
                    num = [complex(sp.N(v, 30)) for v in vec]
                except (TypeError, ValueError):
                    continue
                if any(abs(c.imag) > 1e-12 for c in num):
                    continue
                xs = np.array([c.real for c in num])
                if not (np.all(xs >= lo - 1e-9 * (1 + np.abs(lo))) and np.all(xs <= hi + 1e-9 * (1 + np.abs(hi)))):
                    continue
                cv = [complex(sp.N(c[0].subs(dict(zip(syms, vec))), 30)) for c in cons]
                if any(abs(c.imag) > 1e-9 for c in cv):
                    continue
                if any((-c.real > 1e-9) if cc[1] == "ge" else (abs(c.real) > 1e-9) for c, cc in zip(cv, cons)):
                    continue
                try:
                    exact = sp.simplify(f_expr.subs(dict(zip(syms, vec))))
                    val = complex(sp.N(exact, 30))
                except (TypeError, ValueError, ZeroDivisionError):
                    continue
                if exact.has(sp.nan, sp.zoo, sp.oo, -sp.oo) or abs(val.imag) > 1e-12:
                    continue
                key = tuple(round(float(v), 9) for v in xs)
                kind = "; ".join(where) if where else "interior critical point"
                if key not in candidates:
                    candidates[key] = {"exact": exact, "value": val.real, "x": xs,
                                       "exact_point": [sp.nsimplify(v) if v.is_number else v for v in vec],
                                       "kind": kind}
    if family:
        complete = False
        notes.append("some cases have a continuous family of critical points (f is constant along a curve); only "
                     "isolated critical points are listed, so the result is incomplete")
    return candidates, complete, notes + [f"{total} cases examined (each variable free or at a bound, each "
                                          f"inequality inactive or active)"]


def _lagrange_infinity(names, lo, hi, f_expr, cons, sign, best):
    """Unbounded variables along which the best critical point can be bettered or matched far out (a numeric probe)."""
    if not (np.any(np.isinf(lo)) or np.any(np.isinf(hi))):
        return []
    P = _build(names, lo, hi, None, cons, sign, f_expr=f_expr)
    x = np.array(best["x"], dtype=float)
    g0 = P.g(x)
    if g0 >= BIG:
        return []
    return _infinity_probe(P, x, g0)


def _run_lagrange(inp, ctx, names, lo, hi, lo_e, hi_e, f_expr, cons, sign):
    cands, complete, notes = _lagrange(inp, ctx, names, lo, hi, lo_e, hi_e, f_expr, cons, sign)
    goal = inp.get("goal", "min")
    stopped = cands is None
    if stopped:
        ev = Evidence(button=NAME, result={"goal": goal, "best": None, "near_optimal": []}, method="symbolic",
                      scope="lagrange stopped at the time budget before every case was solved; nothing is reported",
                      complete=False, notes=notes)
        return C.budget_stop(ev, "no result")
    ordered = sorted(cands.values(), key=lambda c: sign * c["value"])

    def entry(c, ref=None):
        e = {"value": c["value"], "exact": str(c["exact"]), "latex": sp.latex(c["exact"]),
             "point": {n: float(x) for n, x in zip(names, c["x"])},
             "point_exact": {n: str(v) for n, v in zip(names, c["exact_point"])}, "kind": c["kind"]}
        if ref is not None:
            e["gap"] = abs(c["value"] - ref)
        return e

    flags = []
    unbounded = False
    if ordered:
        best = ordered[0]
        result = {"goal": goal, "best": entry(best), "near_optimal": [entry(c, best["value"]) for c in ordered[1:1 + NEAR_KEEP]],
                  "candidates_examined": len(ordered)}
        far = _lagrange_infinity(names, lo, hi, f_expr, cons, sign, best)
        if far:
            unbounded = True
            flags.append(("optimum_at_infinity", f"moving {', '.join(far)} far toward infinity is as good as the best "
                                                 f"critical point, so f is unbounded in that direction (or has a "
                                                 f"better infimum there): the critical points listed are local, not "
                                                 f"the optimum"))
            notes.append("an unbounded variable can be pushed far away at no loss from the best critical point: the "
                         "value reported is not the global optimum (there may be none)")
        on_b = best["kind"] != "interior critical point"
        result["on_boundary"] = on_b
        result["active"] = [] if not on_b else [best["kind"]]
        if on_b:
            flags.append(("boundary_optimum", f"the best candidate lies on the boundary of the feasible region: "
                                              f"{best['kind']}"))
    else:
        result = {"goal": goal, "best": None, "near_optimal": [], "on_boundary": None, "active": [],
                  "candidates_examined": 0}
        flags.append(("no_candidate", "no feasible critical point or boundary point was found"))
    if any(math.isinf(v) for v in list(lo) + list(hi)):
        notes.append("a variable is unbounded: behaviour toward infinity was not examined, so an infimum or "
                     "supremum approached there is not reported")
    funcs = f_expr.has(sp.sin, sp.cos, sp.tan, sp.exp, sp.log, sp.Abs, sp.Piecewise, sp.Max, sp.Min)
    if funcs:
        notes.append("f has transcendental or non-smooth parts: sympy may return only some solutions of such "
                     "equations, and points where f is not differentiable are not examined, so the list can be "
                     "incomplete")
    else:
        notes.append("points where f is not differentiable are not examined (f here is smooth wherever defined)")
    notes.append("lagrange lists the exact critical points and boundary cases that sympy could solve for; it is "
                 "exact where it finds them but does not prove that nothing else exists")
    scope = (f"symbolic Lagrange / KKT enumeration by sympy for the {goal}imum of f over {len(names)} variable(s): "
             f"critical points of f on each face of the bounds and each active-inequality case; exact for the "
             f"cases sympy solved")
    ev = Evidence(button=NAME, result=result, method="symbolic", scope=scope, complete=complete and not unbounded,
                  precision={"exact": True, "note": "exact values and points (sympy); floats are 30-digit evaluations"},
                  notes=notes)
    for code, msg in flags:
        ev.flag(code, msg)
    if not complete:
        ev.flag("incomplete_cases", "some cases could not be solved; see the notes")
    if "proposed" in inp and ordered:
        alg.compare(ev, inp["proposed"], ordered[0]["exact"], lambda s: C.parse(s))
    return ev


# ----------------------------------------------------------------------------- the button


@registry.button(
    NAME,
    description="Maximise or minimise a function f of variables with bounds and constraints (e.g. to test an "
                "inequality or find an equality case). Methods: auto, grid, multistart (random starts + local "
                "search), evolution (differential evolution), lagrange (exact critical points by sympy, small "
                "cases). Returns the best value and where it occurs, whether it is on the boundary, the other "
                "distinct near-optimal points (ties show equality cases and symmetry) and how many starts ran. "
                "Seeded. A numeric search finds candidates, not proofs.",
    input_schema=_SCHEMA,
    uses_seed=True,
)
def extremum(inp: dict, ctx) -> Evidence:
    try:
        return _run(inp, ctx)
    except _Bad as e:
        return alg.bad_input(NAME, str(e))
    except (SyntaxError, NameError, TypeError, AttributeError, KeyError, IndexError, ZeroDivisionError) as e:
        return alg.bad_input(NAME, f"f (or a constraint) raised {type(e).__name__}: {e}")


def _run(inp: dict, ctx) -> Evidence:
    names, lo, hi, lo_e, hi_e = _read_vars(inp["vars"])
    goal = inp.get("goal", "min")
    sign = 1.0 if goal == "min" else -1.0
    method = inp.get("method", "auto")
    cons = [_read_constraint(c, names) for c in inp.get("constraints", [])]
    notes0 = []
    if any(c[3] for c in cons):
        notes0.append("a strict inequality (< or >) was treated as non-strict (<= or >=): an optimum on that "
                      "boundary may be only approached, not attained")
    f = inp["f"]
    if isinstance(f, dict):
        if method == "lagrange":
            raise _Bad("method lagrange needs f as an expression, not code")
        fn = _code_function(f["code"], names)
        P = _build(names, lo, hi, None, cons, sign, code_fn=fn)
        notes0.append("f was run as Python code with the variables passed in order as floats")
        f_expr = None
    else:
        try:
            f_expr = C.parse(f, names)
            C.check_function(f_expr, names, "f")
        except ValueError as e:
            raise _Bad(str(e)) from None
        P = _build(names, lo, hi, None, cons, sign, f_expr=f_expr)
    rng = np.random.default_rng(ctx.seed if ctx.seed is not None else 0)
    seed = ctx.seed

    if method == "lagrange":
        return _run_lagrange(inp, ctx, names, lo, hi, lo_e, hi_e, f_expr, cons, sign)

    found = Found(P)
    methods: list[str] = []
    stopped = False
    extra = ""

    def report():
        best, _near, _cl = _result_from(P, found)
        ctx.progress({"result": {"best": best, "starts": found.starts}, "method": "search",
                      "scope": f"{found.starts} search(es) run so far; numeric search, candidates not proofs"})

    starts = inp.get("starts")
    auto = method == "auto"
    multimodal = 0.0
    if method == "auto":
        method = "evolution" if P.d > 6 else "multistart"
    if method == "grid":
        total = int(inp.get("grid_points", MAX_GRID))
        gp = P
        recon = None
        if any(c[1] == "eq" for c in cons):
            if f_expr is None:
                raise _Bad("method grid cannot enforce an equality constraint when f is code; use multistart "
                           "or evolution")
            f2, cons2, kept, subs = _eliminate(f_expr, cons, names, lo, hi, lo_e, hi_e)
            idx = [names.index(n) for n in kept]
            gp = _build(kept, lo[idx], hi[idx], None, cons2, sign, f_expr=f2)
            recon = (kept, subs, idx)
            notes0.append(f"the equality constraint(s) were solved for {', '.join(sorted(subs))} and substituted, so "
                          f"the grid runs over {', '.join(kept) or 'no free variable'}")
        found_g = Found(gp)
        methods.append("grid")
        if gp.names:
            stopped = _grid(gp, ctx, total, found_g, lambda: None)
        else:   # every variable was eliminated: the equalities fix the point
            found_g.starts = 1
            found_g.add(np.array([]))
        extra = f" over {getattr(found_g, 'grid_points', 0)} grid points then local polish"
        if recon is None:
            found, P = found_g, gp
        else:
            kept, subs, _idx = recon
            for g, xr in found_g.pts:
                found.pts.append((g, _expand(xr, names, kept, subs)))
            found.starts, found.infeasible = found_g.starts, found_g.infeasible
            P.evals += gp.evals
            P.undefined += gp.undefined
    elif method == "multistart":
        n = int(starts or min(200, 20 * P.d + 10))
        methods.append("multistart")
        stopped = _multistart(P, rng, ctx, n, found, report)
        if not found.pts and not stopped and P.d >= 1 and inp.get("method", "auto") == "auto":
            methods.append("evolution")
            stopped = _evolution(P, rng, ctx, 3, found, report)
        elif auto and not stopped and not found.at_infinity and _distinct_optima(found) > 1:
            # Several local optima: the multistart may have missed the global one, so differential evolution
            # (global by design) is run as a cross-check, and its points join the pool.
            methods.append("evolution")
            stopped = _evolution(P, rng, ctx, CROSS_RUNS, found, report)
            multimodal = _spread(found)
    else:
        n = int(starts or 4)
        methods.append("evolution")
        stopped = _evolution(P, rng, ctx, n, found, report)
        if P.d > 6 and inp.get("method", "auto") == "auto":
            notes0.append("more than 6 variables: differential evolution was used instead of multistart")
    return _finish_numeric(inp, P, found, ctx, methods, stopped, extra, seed, notes0, multimodal)


def _expand(xr, names, kept, subs):
    """The full point from the values of the kept variables (the eliminated ones are computed)."""
    vals = {sp.Symbol(k): v for k, v in zip(kept, xr)}
    out = []
    for n in names:
        if n in kept:
            out.append(float(vals[sp.Symbol(n)]))
        else:
            out.append(float(sp.N(subs[n].subs(vals))))
    return np.array(out)
