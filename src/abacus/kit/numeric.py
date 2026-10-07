"""`numeric`: high-precision numerics with mpmath (kit/04 s11).

Integrals, sums, products, limits, roots and initial-value problems, each to a stated number of digits
with an error estimate. The estimate is a self-check (the quadrature's own error, or the difference
between two independent computations), never a proof.
"""
from __future__ import annotations

import re

import mpmath as mp
import sympy as sp

from .. import registry
from ..evidence import Evidence
from . import _algebra as alg
from . import _continuous as C

NAME = "numeric"
GUARD = 10            # extra working digits beyond what was asked
NoConv = mp.mp.NoConvergence
SHIFT = 8             # terms summed directly when checking an infinite sum by shifting its start

_SCHEMA = {
    "type": "object", "required": ["op"], "additionalProperties": False,
    "properties": {
        "op": {"enum": ["integral", "sum", "product", "limit", "root", "ode"],
               "description": "integral, sum, product (each over var from lo to hi; use oo or -oo for infinity), "
                              "limit (of expr as var -> at), root (solve expr == 0), ode (an initial-value "
                              "problem evaluated at a point)."},
        "expr": {"anyOf": [{"type": "string", "minLength": 1},
                           {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1}],
                 "description": "The expression, e.g. 'exp(-x**2)'. For root, an equation 'lhs == rhs' is also "
                                "read; a list of expressions is a system (root) or the right-hand sides "
                                "y1' = ..., y2' = ... (ode)."},
        "var": {"anyOf": [{"type": "string", "minLength": 1},
                          {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1}],
                "description": "The variable (a list of them for a root system). For ode, the independent "
                               "variable (default t)."},
        "lo": {"type": ["string", "number"], "description": "Lower limit (integral, sum, product); -oo allowed."},
        "hi": {"type": ["string", "number"], "description": "Upper limit; oo allowed."},
        "at": {"type": ["string", "number"],
               "description": "limit: the point var tends to (oo allowed). ode: the point to evaluate at."},
        "dir": {"enum": ["+", "-"], "default": "+",
                "description": "limit: approach from above (+, default) or below (-). The other side is checked "
                               "and noted if it differs."},
        "x0": {"anyOf": [{"type": ["string", "number"]},
                         {"type": "array", "items": {"type": ["string", "number"]}, "minItems": 1}],
               "description": "root: a starting value, or for one equation a bracket [a, b] with a sign change, "
                              "or for a system a list of starting values."},
        "y": {"anyOf": [{"type": "string", "minLength": 1},
                        {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1}],
              "description": "ode: the name(s) of the unknown(s), default y."},
        "y0": {"anyOf": [{"type": ["string", "number"]},
                         {"type": "array", "items": {"type": ["string", "number"]}, "minItems": 1}],
               "description": "ode: the initial value(s) at t0."},
        "t0": {"type": ["string", "number"], "description": "ode: the initial point (default 0)."},
        "digits": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 30,
                   "description": "Significant digits wanted (default 30)."},
        "proposed": {"description": "A value to compare with the computed one (a number or an expression). Sets "
                                    "`compare`: equal within the result's own precision."},
    },
}


class _Bad(ValueError):
    pass


def _list(v):
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _name(s, what="variable name") -> str:
    if not isinstance(s, str) or not re.match(alg.IDENT, s):
        raise _Bad(f"{what} {s!r} must be a plain name such as x or n")
    C.parse(s)   # rejects names the parser refuses (e.g. containing import or lambda)
    return s


def _need(inp, *keys):
    miss = [k for k in keys if inp.get(k) is None]
    if miss:
        raise _Bad(f"op {inp['op']} needs {', '.join(miss)}")


def _real(v, what, allow_inf=False):
    """A real number (mpf), or +-inf, from a JSON number or an expression string."""
    if isinstance(v, bool):
        raise _Bad(f"{what} must be a number or an expression")
    if isinstance(v, (int, float)):
        return mp.mpf(repr(v)) if isinstance(v, float) else mp.mpf(v)
    try:
        e = C.parse(v)
        C.check_function(e, [], what)
    except ValueError as exc:
        raise _Bad(str(exc)) from None
    if e in (sp.oo, -sp.oo):
        if not allow_inf:
            raise _Bad(f"{what} must be a finite number")
        return mp.inf if e == sp.oo else -mp.inf
    if not e.is_number or e.is_real is False:
        raise _Bad(f"{what} {v!r} must be a real number")
    val = sp.N(e, mp.mp.dps + 5)
    if val.has(sp.nan, sp.zoo) or not val.is_real:
        raise _Bad(f"{what} {v!r} is not a finite real number")
    return mp.mpf(str(val))


def _integer(v, what):
    x = _real(v, what, allow_inf=True)
    if x in (mp.inf, -mp.inf):
        return x
    if x != mp.nint(x):
        raise _Bad(f"{what} must be an integer (got {v!r})")
    return int(mp.nint(x))


class _Fn:
    """A parsed expression as an mpmath function that watches the clock."""

    def __init__(self, expr, names, ctx):
        self.f = sp.lambdify(list(names), expr, modules="mpmath")
        self.ctx = ctx
        self.calls = 0

    def __call__(self, *a):
        self.calls += 1
        if self.ctx.time_left() <= 0:
            raise C.Stopped
        if self.calls % 2000 == 0:
            self.ctx.progress({"result": None, "method": "numeric",
                               "scope": f"stopped before a value; {self.calls} evaluations so far"})
        return self.f(*a)


def _expr(src, names, what="the expression"):
    try:
        e = C.parse(src, names)
        C.check_function(e, names, what)
    except ValueError as exc:
        raise _Bad(str(exc)) from None
    return e


def _agree(a, b, digits) -> bool:
    scale = max(abs(a), abs(b), mp.mpf(10) ** -digits)
    return abs(a - b) <= scale * mp.mpf(10) ** -(digits + 1)


# --------------------------------------------------------------------------------------- operations


class _Out:
    def __init__(self, vals, errs, scalar=True, scope="", notes=None, flags=None, extra=None):
        self.vals, self.errs, self.scalar = vals, errs, scalar
        self.scope, self.notes, self.flags, self.extra = scope, notes or [], flags or [], extra or {}


def _op_integral(inp, ctx, digits):
    _need(inp, "expr", "var", "lo", "hi")
    v = _name(inp["var"])
    if not isinstance(inp["expr"], str):
        raise _Bad("integral takes one expression")
    f = _Fn(_expr(inp["expr"], [v]), [v], ctx)
    a, b = _real(inp["lo"], "lo", True), _real(inp["hi"], "hi", True)
    infinite = a in (mp.inf, -mp.inf) or b in (mp.inf, -mp.inf)
    deg = 6 + digits // 40
    val, err = mp.quad(f, [a, b], error=True, maxdegree=deg)
    notes = []
    if err > abs(val) * mp.mpf(10) ** -digits and err > mp.mpf(10) ** -digits:
        # Not obviously converged: rerun with a finer rule; the two answers must agree, and their difference
        # counts toward the error (a divergent integral changes a lot between the runs).
        val2, err2 = mp.quad(f, [a, b], error=True, maxdegree=deg + 3)
        err = max(err2, abs(val2 - val))
        val = val2
    if infinite:
        notes.append("an infinite range is mapped to a finite one by mpmath's tanh-sinh scheme; the error is an "
                     "estimate, not a bound")
    scope = (f"mpmath tanh-sinh quadrature of {inp['expr']} over [{inp['lo']}, {inp['hi']}] at {digits + GUARD} "
             f"working digits ({f.calls} evaluations)")
    return _Out([val], [err], scope=scope, notes=notes)


def _inf_sum(f, lo, hi, digits, ctx, product=False):
    """(value, error estimate, notes, flags) of an infinite sum or product, checked a second way."""
    run = mp.nprod if product else mp.nsum
    comb = (lambda a, b: a * b) if product else (lambda a, b: a + b)
    direct = mp.fprod if product else mp.fsum
    notes, flags = [], []
    if hi == mp.inf and lo != -mp.inf:
        g, start = f, lo
    elif lo == -mp.inf and hi != mp.inf:
        g, start = (lambda k: f(-k)), -hi
    else:   # both infinite: split at 0
        left = _inf_sum(lambda k: f(-k), 1, mp.inf, digits, ctx, product)
        right = _inf_sum(f, 0, mp.inf, digits, ctx, product)
        return comb(left[0], right[0]), left[1] + right[1], left[2] + right[2], left[3] + right[3]
    start = int(start)
    plain = run(g, [start, mp.inf])
    head = direct(g(mp.mpf(k)) for k in range(start, start + SHIFT))
    shifted = comb(head, run(g, [start + SHIFT, mp.inf]))
    if _agree(plain, shifted, digits):
        return plain, abs(plain - shifted), notes, flags
    if product:
        flags.append(("slow_convergence", "the product and its shifted copy disagree"))
        notes.append("the infinite product did not converge cleanly: starting it later gave a different value, "
                     "so the error estimate (that difference) is large")
        return plain, abs(plain - shifted), notes, flags
    # The default extrapolation (Richardson / Shanks) is unreliable on a slowly convergent series. Euler-Maclaurin
    # is tried as a second opinion; it is trusted only where it agrees with one of the first two runs.
    try:
        em = mp.nsum(g, [start, mp.inf], method="euler-maclaurin")
    except (NoConv, ValueError, ZeroDivisionError):
        em = None
    d_plain = f"two runs of the default extrapolation (Richardson/Shanks) differed by {mp.nstr(abs(plain - shifted), 3)}"
    if em is not None:
        for other in (plain, shifted):
            if _agree(em, other, digits):
                flags.append(("slow_convergence", "the default extrapolation was unsteady"))
                notes.append(f"the series converges slowly: {d_plain}; Euler-Maclaurin agrees with one of them, "
                             f"so that value is used")
                return em, abs(em - other), notes, flags
    flags.append(("slow_convergence", "the series converges too slowly for the extrapolations to agree"))
    notes.append(f"the series converges slowly (or not at all): {d_plain}"
                 + (f", and Euler-Maclaurin gave {mp.nstr(em, 8)}, which agrees with neither" if em is not None else "")
                 + ". The extrapolations do not converge, so the value is unreliable; check that the series "
                   "converges, or sum more terms directly")
    err = abs(plain - shifted)
    if em is not None:
        err = max(err, abs(em - plain), abs(em - shifted))
    return (em if em is not None else plain), err, notes, flags


def _op_series(inp, ctx, digits, product):
    _need(inp, "expr", "var", "lo", "hi")
    v = _name(inp["var"])
    if not isinstance(inp["expr"], str):
        raise _Bad(f"{inp['op']} takes one expression")
    f = _Fn(_expr(inp["expr"], [v]), [v], ctx)
    lo, hi = _integer(inp["lo"], "lo"), _integer(inp["hi"], "hi")
    name = "product" if product else "sum"
    if lo not in (mp.inf, -mp.inf) and hi not in (mp.inf, -mp.inf):
        if hi < lo:
            raise _Bad(f"hi ({hi}) is below lo ({lo}); the {name} would be empty")
        terms = (f(mp.mpf(k)) for k in range(lo, hi + 1))
        val = mp.fprod(terms) if product else mp.fsum(terms)
        scope = f"{name} of {inp['expr']} for {v} = {lo}..{hi}, every term evaluated at {digits + GUARD} digits"
        return _Out([val], [mp.mpf(0)], scope=scope,
                    notes=[f"a finite {name}: every term was added directly, so the only error is rounding at "
                           f"{digits + GUARD} working digits"])
    if lo == mp.inf or hi == -mp.inf:
        raise _Bad("lo must be below hi")
    val, err, notes, flags = _inf_sum(f, lo, hi, digits, ctx, product)
    notes.append(f"an infinite {name} is approximated by extrapolation, so the error is an estimate (the "
                 f"disagreement between two runs), not a bound")
    scope = (f"mpmath {'nprod' if product else 'nsum'} of {inp['expr']} for {v} = {inp['lo']}..{inp['hi']}, "
             f"checked against a run that starts {SHIFT} terms later, at {digits + GUARD} working digits")
    return _Out([val], [err], scope=scope, notes=notes, flags=flags)


def _op_limit(inp, ctx, digits):
    _need(inp, "expr", "var", "at")
    v = _name(inp["var"])
    if not isinstance(inp["expr"], str):
        raise _Bad("limit takes one expression")
    f = _Fn(_expr(inp["expr"], [v]), [v], ctx)
    at = _real(inp["at"], "at", True)
    direction = -1 if inp.get("dir") == "-" else 1
    dps = digits + GUARD
    v1 = mp.limit(f, at, direction=direction)
    with mp.workdps(dps + 15):
        v2 = mp.limit(f, at, direction=direction)
    err = abs(v1 - v2)
    notes, flags = [], []
    if at not in (mp.inf, -mp.inf):
        with mp.workdps(dps):
            other = mp.limit(f, at, direction=-direction)
        if not _agree(v1, other, min(digits, 10)):
            flags.append(("one_sided", "the limits from the two sides differ"))
            notes.append(f"the limit from the other side is {mp.nstr(other, 12)}, which differs: the two-sided "
                         f"limit does not exist; the value is the {'right' if direction == 1 else 'left'}-hand limit")
        else:
            notes.append("the limit from the other side agrees")
    probe = [(mp.mpf(10) ** 8) * (1 + k / mp.mpf(3)) for k in range(3)]
    if at in (mp.inf, -mp.inf):
        pts = [(1 if at == mp.inf else -1) * p for p in probe]
    else:
        pts = [at + direction / p for p in probe]
    try:
        dev = max(abs(f(p) - v1) for p in pts)
    except (ZeroDivisionError, ValueError, ArithmeticError):
        dev = mp.mpf(0)
    if dev > mp.mpf(10) ** -3 * (1 + abs(v1)):
        err = max(err, dev)
        flags.append(("limit_doubtful", "values of the function very near the point are far from the limit found"))
        notes.append(f"values of the function very close to the point differ from the limit found by up to "
                     f"{mp.nstr(dev, 3)}: it may oscillate, have no limit, or approach it very slowly. Treat the "
                     f"value as doubtful")
    notes.append("the limit is found by extrapolating values near the point; the error is the difference between "
                 "two runs at different working precision, an estimate that cannot detect a limit that does not "
                 "exist (oscillation) or a slow approach")
    scope = (f"mpmath limit of {inp['expr']} as {v} -> {inp['at']} ({'from above' if direction == 1 else 'from below'}) "
             f"at {dps} working digits, repeated at {dps + 15}")
    return _Out([v1], [err], scope=scope, notes=notes, flags=flags)


def _equation(src: str) -> str:
    m = re.match(r"^(.*?)(?<![<>!=])={1,2}(?!=)(.*)$", src, re.S)
    if m and m.group(1).strip() and m.group(2).strip():
        return f"({m.group(1)}) - ({m.group(2)})"
    return src


def _op_root(inp, ctx, digits):
    _need(inp, "expr", "var", "x0")
    exprs = _list(inp["expr"])
    names = [_name(n) for n in _list(inp["var"])]
    if len(set(names)) != len(names):
        raise _Bad("the variable names must differ")
    if len(exprs) != len(names):
        raise _Bad(f"{len(exprs)} equation(s) need {len(exprs)} variable(s), but var lists {len(names)}")
    fs = [_Fn(_expr(_equation(s) if isinstance(s, str) else s, names), names, ctx) for s in exprs]
    x0 = _list(inp["x0"])
    dps = digits + GUARD
    if len(fs) == 1:
        if len(x0) not in (1, 2):
            raise _Bad("x0 is a start value, or a bracket [a, b] for one equation")
        start = [_real(s, "x0") for s in x0]
        kw = {"solver": "anderson"} if len(start) == 2 else {}
        arg = tuple(start) if len(start) == 2 else start[0]
        solve = lambda: mp.findroot(fs[0], arg, **kw)  # noqa: E731
        resid = lambda r: [abs(fs[0](r))]  # noqa: E731
        as_list = lambda r: [r]  # noqa: E731
    else:
        if len(x0) != len(fs):
            raise _Bad(f"a system of {len(fs)} equations needs {len(fs)} starting values in x0")
        start = [_real(s, "x0") for s in x0]
        F = lambda *a: [f(*a) for f in fs]  # noqa: E731
        solve = lambda: mp.findroot(F, start)  # noqa: E731
        resid = lambda r: [abs(t) for t in F(*r)]  # noqa: E731
        as_list = lambda r: list(r)  # noqa: E731
    try:
        r1 = as_list(solve())
        residual = max(resid(r1[0] if len(fs) == 1 else r1))
        with mp.workdps(dps + 15):
            r2 = as_list(solve())
    except ValueError as exc:
        if "Could not find root" in str(exc) or "tolerance" in str(exc) or "bracket" in str(exc).lower():
            raise NoConv(str(exc)) from None
        raise
    errs = [abs(a - b) for a, b in zip(r1, r2)]
    notes = ["root finding reports one root near the start; others may exist. The error is the difference between "
             "two runs at different working precision, and `residual` is |f(root)|"]
    scope = (f"mpmath findroot ({'secant' if len(fs) == 1 and len(start) == 1 else 'anderson bracketing' if len(fs) == 1 else 'multidimensional Newton'}) "
             f"for {', '.join(str(s) for s in exprs)} from {inp['x0']} at {dps} working digits, repeated at {dps + 15}")
    return _Out(r1, errs, scalar=len(fs) == 1, scope=scope, notes=notes, extra={"residual": mp.nstr(residual, 3)})


def _op_ode(inp, ctx, digits):
    _need(inp, "expr", "y0", "at")
    t = _name(inp.get("var", "t"))
    ys = [_name(n, "unknown name") for n in _list(inp.get("y", "y"))]
    rhs = _list(inp["expr"])
    if len(rhs) != len(ys):
        raise _Bad(f"{len(rhs)} right-hand side(s) for {len(ys)} unknown(s) in y")
    if len({t, *ys}) != len(ys) + 1:
        raise _Bad("the independent variable and the unknowns need different names")
    names = [t] + ys
    fs = [_Fn(_expr(s, names), names, ctx) for s in rhs]
    scalar = len(ys) == 1 and not isinstance(inp["expr"], list)
    y0 = [_real(s, "y0") for s in _list(inp["y0"])]
    if len(y0) != len(ys):
        raise _Bad(f"y0 has {len(y0)} value(s) for {len(ys)} unknown(s)")
    t0 = _real(inp.get("t0", 0), "t0")
    at = _real(inp["at"], "at")
    dps = digits + GUARD
    sign = -1 if at < t0 else 1

    def solve():
        if scalar:
            F = (lambda s, y: sign * fs[0](sign * s, y))
            sol = mp.odefun(F, sign * t0, y0[0])
            return [sol(sign * at)]
        F = (lambda s, y: [sign * f(sign * s, *y) for f in fs])
        sol = mp.odefun(F, sign * t0, y0)
        return list(sol(sign * at))

    if at == t0:
        r1 = list(y0)
        r2 = list(y0)
    else:
        r1 = solve()
        with mp.workdps(dps + 15):
            r2 = solve()
    errs = [abs(a - b) for a, b in zip(r1, r2)]
    notes = ["the ODE is solved by mpmath's Taylor-series method; the error is the difference between two runs at "
             "different working precision, an estimate. A stiff problem or a solution that blows up before the "
             "point will be slow or fail"]
    scope = (f"mpmath odefun (Taylor series) for {', '.join(y + chr(39) for y in ys)} = {', '.join(rhs)} from "
             f"{t} = {inp.get('t0', 0)} to {inp['at']}, at {dps} working digits, repeated at {dps + 15}")
    return _Out(r1, errs, scalar=scalar, scope=scope, notes=notes)


# --------------------------------------------------------------------------------------- the button


def _reliable(v, err, digits) -> int:
    if err == 0 or (err <= mp.mpf(10) ** -digits and abs(v) <= mp.mpf(10) ** -digits):
        return digits   # a value of zero, to an absolute 10^-digits
    mag = abs(v)
    if mag == 0:
        return max(0, min(digits, int(mp.floor(-mp.log10(err)))))
    if err >= mag:
        return 0
    return max(0, min(digits, int(mp.floor(-mp.log10(err / mag)))))


def _fmt(v, n: int) -> str:
    return mp.nstr(v, n, min_fixed=-8, max_fixed=max(30, n + 5))


@registry.button(
    NAME,
    description="High-precision numerics (mpmath) to a stated number of digits (default 30): integral, sum, "
                "product (over var from lo to hi; oo and -oo are infinity), limit (expr as var -> at), root "
                "(solve expr == 0 from x0 or a bracket, or a system), ode (an initial-value problem y' = expr, "
                "y(t0) = y0, evaluated at `at`). Returns the value with its digits and an error estimate, and "
                "notes when convergence is slow or the estimate is large (then fewer digits are shown). "
                "The estimate is a self-check, not a proof.",
    input_schema=_SCHEMA,
)
def numeric(inp: dict, ctx) -> Evidence:
    digits = int(inp.get("digits", 30))
    op = inp["op"]
    saved = mp.mp.dps
    try:
        mp.mp.dps = digits + GUARD
        try:
            if op == "integral":
                out = _op_integral(inp, ctx, digits)
            elif op == "sum":
                out = _op_series(inp, ctx, digits, product=False)
            elif op == "product":
                out = _op_series(inp, ctx, digits, product=True)
            elif op == "limit":
                out = _op_limit(inp, ctx, digits)
            elif op == "root":
                out = _op_root(inp, ctx, digits)
            else:
                out = _op_ode(inp, ctx, digits)
        except C.Stopped:
            ev = Evidence(button=NAME, result=None, method="numeric",
                          scope=f"{op} stopped at the time budget before reaching a value; nothing is reported",
                          complete=False)
            return C.budget_stop(ev, "no value was reached")
        except _Bad as e:
            return alg.bad_input(NAME, str(e))
        except NoConv as e:
            ev = Evidence(button=NAME, result=None, method="numeric",
                          scope=f"{op} did not converge; nothing is reported", complete=False)
            ev.flag("no_convergence", f"mpmath did not converge: {e}")
            return ev
        except (ZeroDivisionError, ValueError, TypeError, OverflowError, ArithmeticError) as e:
            return alg.bad_input(NAME, f"the expression could not be evaluated: {type(e).__name__}: {e}")
        return _finish(inp, out, digits)
    finally:
        mp.mp.dps = saved


def _finish(inp, out: _Out, digits: int) -> Evidence:
    rel = [_reliable(v, e, digits) for v, e in zip(out.vals, out.errs)]
    reliable = min(rel)
    shown = max(1, reliable)
    err = max(out.errs)
    tiny = mp.mpf(10) ** -digits
    zero = [bool(e > 0 and abs(v) <= tiny and e <= tiny) for v, e in zip(out.vals, out.errs)]
    vals = ["0" if z else _fmt(v, shown) for v, z in zip(out.vals, zero)]
    result = {"op": inp["op"], "value": vals[0] if out.scalar else vals, "digits": shown,
              "reliable_digits": reliable, "error_estimate": mp.nstr(err, 3)}
    if shown != digits:
        result["requested_digits"] = digits
    result.update(out.extra)
    notes, flags = list(out.notes), list(out.flags)
    if any(zero):
        notes.append(f"a value indistinguishable from zero (smaller than its error estimate {mp.nstr(err, 3)}) is "
                     f"shown as 0: the result is zero to within an absolute {mp.nstr(err, 3)}")
    complete = True
    if reliable < min(digits, 5):
        complete = False
        flags.append(("no_convergence", f"the error estimate {mp.nstr(err, 3)} is too large: fewer than "
                                        f"{min(digits, 5)} digits can be trusted"))
        notes.append(f"error estimate {mp.nstr(err, 3)} is too large for the value (fewer than {min(digits, 5)} digits "
                     f"are reliable): the integral or series may diverge, oscillate, have a non-integrable "
                     f"singularity, or converge too slowly. The value shown is a rough magnitude only")
    elif reliable < digits:
        flags.append(("low_accuracy", f"only about {reliable} of {digits} requested digits are reliable"))
        notes.append(f"error estimate {mp.nstr(err, 3)} is larger than the {digits}-digit target: only about "
                     f"{reliable} digits are reliable, so only those are shown")
    if any(c == "slow_convergence" for c, _ in flags) and not any("converge" in n for n in notes):
        notes.append("convergence is slow")
    ev = Evidence(button=NAME, result=result, method="numeric", scope=out.scope, complete=complete,
                  precision={"digits": reliable, "error_estimate": mp.nstr(err, 3)}, notes=notes)
    for code, msg in flags:
        ev.flag(code, msg)
    if "proposed" in inp:
        if out.scalar:
            tol = max(err, abs(out.vals[0]) * mp.mpf(10) ** -shown)
            C.tolerance_compare(ev, inp["proposed"], out.vals[0], tol, lambda s: C.parse(s))
        else:
            ev.notes.append("proposed is compared only with a single value; this result is a list, so compare was not set")
    return ev
