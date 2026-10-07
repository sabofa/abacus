"""`numeric`: high-precision numerics with mpmath (kit/04 s11).

Integrals, sums, products, limits, roots and initial-value problems, each to a stated number of digits
with an error estimate. The estimate is a self-check (the quadrature's own error, or the difference
between two independent computations), never a proof.
"""
from __future__ import annotations

import math
import re

import mpmath as mp
import sympy as sp

from .. import registry
from ..evidence import Evidence
from . import _algebra as alg
from . import _continuous as C

NAME = "numeric"
PEAK_RANGE = 10 ** 4     # |f| is tracked where the quadrature samples within this distance of the origin
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


class _Fail(Exception):
    """The computation cannot honestly give a value (a divergent sum, an integral with no limit): the button reports
    no value, an incomplete result and this flag."""

    def __init__(self, code: str, message: str, scope: str = "", notes=None):
        super().__init__(message)
        self.code, self.message, self.scope, self.notes = code, message, scope, list(notes or [])


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
        self.peak = mp.mpf(0)   # the largest |f| seen at a one-variable argument within PEAK_RANGE of the origin

    def __call__(self, *a):
        self.calls += 1
        if self.ctx.time_left() <= 0:
            raise C.Stopped
        if self.calls % 2000 == 0:
            self.ctx.progress({"result": None, "method": "numeric",
                               "scope": f"stopped before a value; {self.calls} evaluations so far"})
        r = self.f(*a)
        if len(a) == 1:
            try:
                if abs(a[0]) <= PEAK_RANGE:
                    self.peak = max(self.peak, abs(r))
            except (TypeError, ValueError):
                pass
        return r


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


def _geo_points(a, b, base, kmax):
    """Split points for an infinite range, at geometrically growing distances from the finite end (or from 0 on the
    whole line): tanh-sinh resolves a peak far from the end, or a narrow one, only when it is cut into pieces of
    comparable scale. Different bases give different, independent runs of the quadrature."""
    reach = [mp.mpf(base) ** k for k in range(kmax)]
    if a == -mp.inf and b == mp.inf:
        return [a] + [-t for t in reversed(reach)] + [mp.mpf(0)] + reach + [b]
    if b == mp.inf:
        mid = [a + t for t in reach]
        return sorted(set([a] + mid + ([mp.mpf(0)] if a < 0 else []))) + [b]
    if a == -mp.inf:
        mid = [b - t for t in reach]
        return [a] + sorted(set(mid + ([mp.mpf(0)] if b > 0 else []))) + [b]
    return [a, b]


def _finite_scale(f, a, b) -> mp.mpf:
    """How large the integrand gets on the part of the range the quadrature can really see: the largest |f| it
    evaluated within PEAK_RANGE of the origin, and on log-spaced points (0.001 to 1000) out from the finite end."""
    ends = [x for x in (a, b) if x not in (mp.inf, -mp.inf)]
    offsets = [mp.mpf(10) ** (mp.mpf(k) / 4) for k in range(-12, 13)]
    if not ends:
        pts = [s * t for t in offsets for s in (1, -1)] + [mp.mpf(0)]
    else:
        pts = [e + (1 if e == a else -1) * t for e in ends for t in offsets] + ends
    best = f.peak
    for x in pts:
        try:
            best = max(best, abs(f.f(x)))
        except (ZeroDivisionError, ValueError, ArithmeticError, TypeError):
            continue
    return best


def _op_integral(inp, ctx, digits):
    _need(inp, "expr", "var", "lo", "hi")
    v = _name(inp["var"])
    if not isinstance(inp["expr"], str):
        raise _Bad("integral takes one expression")
    f = _Fn(_expr(inp["expr"], [v]), [v], ctx)
    a, b = _real(inp["lo"], "lo", True), _real(inp["hi"], "hi", True)
    infinite = a in (mp.inf, -mp.inf) or b in (mp.inf, -mp.inf)
    deg = 6 + digits // 40
    notes = []
    # Tanh-sinh evaluates the midpoint of a symmetric range; an integrand undefined there (sin(x)/x at 0, a removable
    # singularity) would be rejected, so a range that contains 0 is split at 0 and its pieces never touch it.
    pts = [a, 0, b] if a < 0 < b else [a, b]
    if infinite:
        pts = _geo_points(a, b, 2, 12)
    try:
        val, err = mp.quad(f, pts, error=True, maxdegree=deg)
    except ZeroDivisionError:
        if infinite or len(pts) > 2:
            raise
        mid = (a + b) / 2
        pts = [a, mid, b]
        val, err = mp.quad(f, pts, error=True, maxdegree=deg)
        notes.append(f"the integrand is undefined at the midpoint {mp.nstr(mid, 8)} of the range (a removable "
                     f"singularity?), so the range was split there; if it is a true pole the integral diverges and "
                     f"the error estimate will be large")
    if a < 0 < b and len(pts) == 3 and pts[1] == 0:
        notes.append("the range contains 0 and was split there, so an integrand that is undefined only at 0 "
                     "(a removable singularity such as sin(x)/x) is integrated through it")
    if err > abs(val) * mp.mpf(10) ** -digits and err > mp.mpf(10) ** -digits:
        # Not obviously converged: rerun with a finer rule; the two answers must agree, and their difference
        # counts toward the error (a divergent integral changes a lot between the runs).
        val2, err2 = mp.quad(f, pts, error=True, maxdegree=deg + 3)
        err = max(err2, abs(val2 - val))
        val = val2
    if infinite:
        # mpmath's own error estimate is absolute and can be tiny next to a huge, meaningless value (1 against 1e44),
        # so an infinite range is always computed a second time on a different split and degree, and the two must
        # agree. A value enormous next to the integrand on the finite part is a divergent integral, not an answer.
        val2, err2 = mp.quad(f, _geo_points(a, b, 3, 8), error=True, maxdegree=deg + 1)
        err = max(err, err2, abs(val - val2))
        if err2 < err and abs(val - val2) <= err2:
            val = val2
        scale = _finite_scale(f, a, b) or mp.mpf(1)
        if abs(val) > mp.mpf(10) ** 8 * scale or abs(val2) > mp.mpf(10) ** 8 * scale:
            raise _Fail("no_convergence",
                        f"the integral over [{inp['lo']}, {inp['hi']}] has no value this method can reach: the result "
                        f"({mp.nstr(val, 3)}) is enormous next to the integrand on the finite part (up to "
                        f"{mp.nstr(scale, 3)}), the sign of a divergent integral or one with no limit "
                        f"(oscillating without decay, such as sin x on [0, oo))",
                        f"mpmath tanh-sinh quadrature of {inp['expr']} over [{inp['lo']}, {inp['hi']}] ran twice on "
                        f"different splits and gave no usable value; nothing is reported",
                        ["two runs of the quadrature (different splits) were compared; mpmath's own estimate "
                         "(absolute, about 1) was not trusted next to a value this large",
                         "an oscillating integrand that does not decay has no limit; one that decays only through "
                         "oscillation (cos(x**2), sin(x)/x) converges but is out of reach of this quadrature"])
        notes.append("an infinite range is mapped to a finite one by mpmath's tanh-sinh scheme and computed twice on "
                     "different splits; the error is the larger of mpmath's estimate and the disagreement of the two "
                     "runs, an estimate and not a bound")
    scope = (f"mpmath tanh-sinh quadrature of {inp['expr']} over [{inp['lo']}, {inp['hi']}] at {digits + GUARD} "
             f"working digits ({f.calls} evaluations)")
    return _Out([val], [err], scope=scope, notes=notes)


SCALES = (10 ** 3, 10 ** 6, 10 ** 9)
P_DIVERGENT = 1.02      # terms ~ n^-p with p at or below this: the series diverges (or is at best conditionally convergent)
P_CONVERGENT = 1.08     # ... and above this it converges absolutely; in between, it cannot be told


def _term_sizes(g, start, product):
    """For each scale S, (S, max |term| over four consecutive indices near start+S, whether their signs alternate).
    A product's 'term' is the factor minus 1. A scale where g cannot be evaluated is skipped."""
    rows = []
    for S in SCALES:
        vals = []
        try:
            for j in range(4):
                t = g(mp.mpf(start + S + j))
                vals.append(t - 1 if product else t)
        except (ZeroDivisionError, ValueError, OverflowError, ArithmeticError, TypeError):
            continue
        mags = [abs(t) for t in vals]
        alt = all(not isinstance(t, mp.mpc) and t != 0 for t in vals) and all(
            vals[i] * vals[i + 1] < 0 for i in range(3))
        rows.append((S, max(mags), alt))
    return rows


def _check_terms(g, start, product, name, text):
    """Raise _Fail unless the terms of an infinite sum (factors of a product) clearly head to zero (one) fast enough
    for the series to converge. Returns (decay rate p in n^-p, whether the signs alternate)."""
    what = "factors" if product else "terms"
    rows = _term_sizes(g, start, product)
    got = {S: (a, alt) for S, a, alt in rows}
    if 10 ** 6 not in got or 10 ** 9 not in got:
        raise _Fail("no_convergence",
                    f"the {what} of the {name} could not be evaluated far enough out (n = 10^6 and 10^9) to check "
                    f"that it converges, so no value is reported",
                    f"infinite {name} of {text}: convergence could not be checked; nothing is reported")
    a3 = got.get(10 ** 3, (None, False))[0]
    a6, alt6 = got[10 ** 6]
    a9, alt9 = got[10 ** 9]
    sizes = ", ".join(f"{mp.nstr(a, 3)} at n=10^{int(round(math.log10(S)))}" for S, a, _ in rows)
    scope0 = f"infinite {name} of {text}: the {what} were checked first and did not allow a value; nothing is reported"
    if a9 == 0 and a6 == 0:
        return mp.inf, False
    if a9 >= a6 * mp.mpf("0.999") or a9 > mp.mpf("0.01"):
        raise _Fail("divergent",
                    f"the {what} of the {name} do not tend to {'1' if product else 'zero'} (size {sizes}), so it "
                    f"diverges or has no limit (it oscillates or grows); no value is reported",
                    scope0, [f"size of the {what}{' minus 1' if product else ''}: {sizes}"])
    alt = alt6 and alt9
    p = mp.log(a6 / a9) / mp.log(1000) if a9 != 0 else mp.inf
    if alt:
        if a9 < mp.mpf("1e-4") and a9 < a6 and (a3 is None or a6 < a3):
            return p, True
        raise _Fail("no_convergence",
                    f"the {what} alternate in sign but shrink too slowly (size {sizes}) for the alternating-series "
                    f"test; convergence cannot be confirmed, so no value is reported",
                    scope0, [f"size of the {what}: {sizes}"])
    if p <= P_DIVERGENT:
        raise _Fail("divergent",
                    f"the {what} of the {name} shrink no faster than 1/n (size {sizes}, decay rate about n^-"
                    f"{mp.nstr(p, 3)}), the borderline of divergence: the series diverges, or at best converges "
                    f"only conditionally, which this method cannot confirm; no value is reported",
                    scope0, [f"size of the {what}: {sizes}; a series needs {what} shrinking faster than 1/n"])
    if p < P_CONVERGENT:
        raise _Fail("no_convergence",
                    f"the {what} of the {name} shrink almost as slowly as 1/n (size {sizes}, decay rate about n^-"
                    f"{mp.nstr(p, 3)}), so convergence cannot be told from divergence by a numeric test; no value "
                    f"is reported",
                    scope0, [f"size of the {what}: {sizes}"])
    return p, False


def _tail_em(g, start, N, p):
    """(value, error) of sum_{k>=start} g(k): the first N-start terms directly, the rest by Euler-Maclaurin with the tail
    integral computed after the substitution x = N t^-m. A slowly decaying integrand (x^-1.1) loses real mass beyond
    the point where mpmath's own tanh-sinh scheme stops (about 1e40), which this substitution removes."""
    head = mp.fsum(g(mp.mpf(k)) for k in range(start, N))
    m = min(mp.mpf(30), max(mp.mpf(1), 1 / (p - 1)))
    integral = mp.quad(lambda t: g(N * t ** (-m)) * N * m * t ** (-m - 1), [0, 1])
    tail, err = mp.sumem(g, [N, mp.inf], integral=integral, error=True)
    return head + tail, err


def _slow_sum(g, start, p, digits):
    """A slowly convergent, non-alternating series (terms ~ n^-p, p small): two Euler-Maclaurin sums that start the
    tail at different points must agree. The default extrapolation is not used: it is unreliable here."""
    try:
        v1, e1 = _tail_em(g, start, start + 20, p)
        v2, e2 = _tail_em(g, start, start + 40, p)
    except (NoConv, ValueError, ZeroDivisionError, ArithmeticError):
        v1 = v2 = None
    if v1 is None or isinstance(v1, mp.mpc) or isinstance(v2, mp.mpc) or not _agree(v1, v2, 6):
        gap = f"; the two sums were {mp.nstr(v1, 10)} and {mp.nstr(v2, 10)}" if v1 is not None else ""
        raise _Fail("no_convergence",
                    f"the series converges slowly (terms ~ n^-{mp.nstr(p, 3)}) and two Euler-Maclaurin sums did not "
                    f"agree{gap}; no value is reported",
                    "infinite sum: a slowly convergent series whose Euler-Maclaurin sums disagree; nothing is reported",
                    ["the default extrapolation (Richardson/Shanks) is unreliable on a series this slow and was not used"])
    err = max(abs(v1 - v2), e1, e2)
    return v2, err, [f"the series converges slowly (terms ~ n^-{mp.nstr(p, 3)}): the value is an Euler-Maclaurin sum "
                     f"whose tail starts at two different terms (differing by {mp.nstr(abs(v1 - v2), 3)}); the "
                     f"default extrapolation is unreliable here and was not used"],         [("slow_convergence", "the series converges slowly; its sum is an Euler-Maclaurin estimate")]


def _inf_sum(f, lo, hi, digits, ctx, product=False, text=""):
    """(value, error estimate, notes, flags) of an infinite sum or product, checked several ways. Raises _Fail when
    the series does not clearly converge or the checks do not agree."""
    run = mp.nprod if product else mp.nsum
    comb = (lambda a, b: a * b) if product else (lambda a, b: a + b)
    direct = mp.fprod if product else mp.fsum
    name = "product" if product else "sum"
    notes, flags = [], []
    if hi == mp.inf and lo != -mp.inf:
        g, start = f, lo
    elif lo == -mp.inf and hi != mp.inf:
        g, start = (lambda k: f(-k)), -hi
    else:   # both infinite: split at 0
        left = _inf_sum(lambda k: f(-k), 1, mp.inf, digits, ctx, product, text)
        right = _inf_sum(f, 0, mp.inf, digits, ctx, product, text)
        return comb(left[0], right[0]), left[1] + right[1], left[2] + right[2], left[3] + right[3]
    start = int(start)
    # 1. The terms must head to zero, and fast enough. Extrapolation applied to a divergent series returns a
    #    confident number (sum 1/n gives 6.7, sum 1 gives 450, sum 2^n gives -1), so this comes first.
    p, alt = _check_terms(g, start, product, name, text)
    if not product and not alt and p < 1 + (digits + 5) / 40:
        return _slow_sum(g, start, p, digits)
    plain = run(g, [start, mp.inf])
    head = direct(g(mp.mpf(k)) for k in range(start, start + SHIFT))
    shifted = comb(head, run(g, [start + SHIFT, mp.inf]))
    plain_ok = _agree(plain, shifted, digits)
    if product:
        if not plain_ok:
            flags.append(("slow_convergence", "the product and its shifted copy disagree"))
            notes.append("the infinite product did not converge cleanly: starting it later gave a different value, "
                         "so the error estimate (that difference) is large")
        return plain, abs(plain - shifted), notes, flags
    d_plain = f"two runs of the default extrapolation (Richardson/Shanks) differed by {mp.nstr(abs(plain - shifted), 3)}"
    if alt:
        if not plain_ok:
            raise _Fail("no_convergence",
                        f"the alternating series did not extrapolate steadily ({d_plain}); no value is reported",
                        f"infinite sum of {text}: extrapolation did not settle; nothing is reported", [d_plain])
        notes.append("the terms alternate in sign and shrink to zero, so the series converges (alternating-series "
                     "test); the value is extrapolated and agrees with a run that starts later")
        return plain, abs(plain - shifted), notes, flags
    # 2. A second method. Euler-Maclaurin sums the head and integrates the tail; started at `start` and at
    #    `start+SHIFT` the two must agree with each other. The default extrapolation (Richardson / Shanks) is
    #    unreliable on a slowly convergent series, so it is cross-checked whenever the decay is slower than n^-4.
    em = em_shift = None
    if not plain_ok or p < 4:
        try:
            em = mp.nsum(g, [start, mp.inf], method="euler-maclaurin")
            em_shift = comb(head, mp.nsum(g, [start + SHIFT, mp.inf], method="euler-maclaurin"))
        except (NoConv, ValueError, ZeroDivisionError, ArithmeticError):
            em = em_shift = None
    em_gap = abs(em - em_shift) if em is not None else None
    em_ok = em is not None and not isinstance(em, mp.mpc) and _agree(em, em_shift, 6)
    if plain_ok and (em is None or (em_ok and _agree(plain, em, min(digits, 6)))):
        err = abs(plain - shifted)
        if em_ok:
            err = max(err, abs(plain - em), em_gap)
        if em is None and p < 4:
            flags.append(("slow_convergence", "the series converges slowly and the cross-check could not run"))
            notes.append(f"the series converges slowly (terms ~ n^-{mp.nstr(p, 3)}) and Euler-Maclaurin, the "
                         f"cross-check, did not run; only the default extrapolation and its shifted copy agree")
        return plain, err, notes, flags
    if em_ok and not plain_ok:
        flags.append(("slow_convergence", "the default extrapolation was unsteady"))
        notes.append(f"the series converges slowly (terms ~ n^-{mp.nstr(p, 3)}): {d_plain}; Euler-Maclaurin started "
                     f"at two points agrees with itself to within {mp.nstr(em_gap, 3)}, so it is used")
        return em, em_gap, notes, flags
    detail = (f"{d_plain}; Euler-Maclaurin at two start points gave {mp.nstr(em, 8)} and {mp.nstr(em_shift, 8)}"
              if em is not None else f"{d_plain}; Euler-Maclaurin did not converge")
    raise _Fail("no_convergence",
                f"the series' terms shrink (about n^-{mp.nstr(p, 3)}) but the value could not be pinned down: "
                f"{detail}; the checks do not agree, so no value is reported",
                f"infinite sum of {text}: the independent checks disagree; nothing is reported", [detail])


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
    val, err, notes, flags = _inf_sum(f, lo, hi, digits, ctx, product, inp['expr'])
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
    sym = [_expr(_equation(s) if isinstance(s, str) else s, names) for s in exprs]
    fs = [_Fn(e, names, ctx) for e in sym]
    x0 = _list(inp["x0"])
    dps = digits + GUARD
    notes, flags = [], []
    if len(fs) == 1:
        if len(x0) not in (1, 2):
            raise _Bad("x0 is a start value, or a bracket [a, b] for one equation")
        start = [_real(s, "x0") for s in x0]
        if len(start) == 2:
            fa, fb = fs[0](start[0]), fs[0](start[1])
            if fa == fb and fa != 0:
                # the bracketing solver divides by f(b) - f(a); equal end values leave it nothing to work with
                raise _Fail("no_sign_change",
                            f"f has the same value ({mp.nstr(fa, 8)}) at both ends of the bracket "
                            f"[{mp.nstr(start[0], 8)}, {mp.nstr(start[1], 8)}], so there is no sign change and the "
                            f"bracketing solver has no slope to follow: no root is guaranteed in it, and none is "
                            f"reported",
                            f"mpmath findroot (anderson bracketing) for {exprs[0]} on {inp['x0']}: the bracket has "
                            f"no sign change; nothing is reported",
                            ["give a bracket whose ends have opposite signs, or a single start value"])
            if fa * fb > 0:
                flags.append(("no_sign_change", f"f has the same sign at both ends of the bracket "
                                                f"[{mp.nstr(start[0], 8)}, {mp.nstr(start[1], 8)}]: a root there is "
                                                f"not guaranteed, and the search may leave the bracket"))
                notes.append("the bracket does not contain a sign change, so it does not bracket a root; any root "
                             "found is a root of f but may lie outside it")
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
    scope_method = ('secant' if len(fs) == 1 and len(start) == 1 else 'anderson bracketing' if len(fs) == 1
                    else 'multidimensional Newton')
    multiple = 0
    try:
        r1 = as_list(solve())
        residual = max(resid(r1[0] if len(fs) == 1 else r1))
        with mp.workdps(dps + 15):
            r2 = as_list(solve())
    except ValueError as exc:
        if not ("Could not find root" in str(exc) or "tolerance" in str(exc) or "bracket" in str(exc).lower()):
            raise
        if len(fs) != 1:
            raise NoConv(str(exc)) from None
        # A multiple root (x-1)**2 makes f flat where it vanishes, so the residual test fails. Look for it as a
        # simple root of a derivative of f, then confirm that f itself vanishes there.
        got = _multiple_root(sym[0], names[0], fs[0], start, digits, dps, ctx)
        if got is None:
            raise NoConv(str(exc)) from None
        r1, r2, residual, multiple = got
        scope_method = f"secant on the derivative of order {multiple}"
    errs = [abs(a - b) for a, b in zip(r1, r2)]
    if len(fs) == 1 and len(start) == 2:
        lo_b, hi_b = min(start), max(start)
        if not lo_b <= r1[0] <= hi_b:
            flags.append(("root_outside_bracket", f"the root found ({mp.nstr(r1[0], 12)}) lies outside the bracket "
                                                  f"[{mp.nstr(lo_b, 8)}, {mp.nstr(hi_b, 8)}]"))
    notes.append("root finding reports one root near the start; others may exist. The error is the difference between "
                 "two runs at different working precision, and `residual` is |f(root)|")
    if multiple:
        flags.append(("multiple_root", f"f and its derivative of order {multiple} both vanish here: a multiple root "
                                       f"(multiplicity at least {multiple + 1}); the root was found as a simple root "
                                       f"of that derivative, and a root of even multiplicity is a touch, not a "
                                       f"crossing, so a bracket test cannot see it"))
        notes.append("f is flat at a multiple root, so the direct search cannot converge on it; the error estimate "
                     "is for the derivative's root, which is the same point")
    scope = (f"mpmath findroot ({scope_method}) "
             f"for {', '.join(str(s) for s in exprs)} from {inp['x0']} at {dps} working digits, repeated at {dps + 15}")
    return _Out(r1, errs, scalar=len(fs) == 1, scope=scope, notes=notes, flags=flags,
                extra={"residual": mp.nstr(residual, 3)})


def _multiple_root(expr, var, f, start, digits, dps, ctx):
    """([root], [root at higher precision], |f(root)|, order of the derivative) for a multiple root of one equation, or
    None. Tries the first few derivatives; accepts a root of f^(m) at which f itself vanishes to the target digits."""
    sym = sp.Symbol(var)
    tiny = mp.mpf(10) ** -digits
    for m in range(1, 5):
        d = _Fn(sp.diff(expr, sym, m), [var], ctx)
        arg = tuple(start) if len(start) == 2 else start[0]
        kw = {"solver": "anderson"} if len(start) == 2 else {}
        try:
            r1 = mp.findroot(d, arg, **kw)
            res = abs(f(r1))
            if res > tiny:
                continue
            with mp.workdps(dps + 15):
                r2 = mp.findroot(d, arg, **kw)
            return [r1], [r2], res, m
        except (ValueError, ZeroDivisionError, ArithmeticError):
            continue
    return None


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
        except _Fail as e:
            ev = Evidence(button=NAME, result=None, method="numeric",
                          scope=e.scope or f"{op} has no value this method can reach; nothing is reported",
                          complete=False, notes=e.notes + ["a series or integral that does not clearly converge is "
                                                           "reported without a value rather than with a doubtful one"])
            ev.flag(e.code, e.message)
            return ev
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
    # An integral whose error estimate is too large for any digits is flagged and carries no value: mpmath's estimate
    # is a self-check that a slowly converging (1/x**1.1) or divergent (1/x) integral beats, so a "rough value" with
    # digits and an error attached would claim more than the evidence supports.
    withheld = inp["op"] == "integral" and reliable < min(digits, 5)
    if withheld:
        result = {"op": inp["op"], "value": None, "digits": 0, "reliable_digits": 0, "requested_digits": digits}
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
                     f"singularity, or converge too slowly. " +
                     ("No value is reported: the quadrature's own number is not trustworthy to even one digit"
                      if withheld else "The value shown is a rough magnitude only"))
    elif reliable < digits:
        flags.append(("low_accuracy", f"only about {reliable} of {digits} requested digits are reliable"))
        notes.append(f"error estimate {mp.nstr(err, 3)} is larger than the {digits}-digit target: only about "
                     f"{reliable} digits are reliable, so only those are shown")
    if any(c == "slow_convergence" for c, _ in flags) and not any("converge" in n for n in notes):
        notes.append("convergence is slow")
    ev = Evidence(button=NAME, result=result, method="numeric", scope=out.scope, complete=complete,
                  precision={"digits": 0} if withheld else {"digits": reliable, "error_estimate": mp.nstr(err, 3)},
                  notes=notes)
    for code, msg in flags:
        ev.flag(code, msg)
    if "proposed" in inp and withheld:
        ev.notes.append("proposed was not compared: the integral has no reliable value")
    elif "proposed" in inp:
        if out.scalar:
            tol = max(err, abs(out.vals[0]) * mp.mpf(10) ** -shown)
            C.tolerance_compare(ev, inp["proposed"], out.vals[0], tol, lambda s: C.parse(s))
        else:
            ev.notes.append("proposed is compared only with a single value; this result is a list, so compare was not set")
    return ev
