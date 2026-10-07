"""`identify`: turn a decimal into a closed form (kit/04 s9).

Integer-relation search (PSLQ) over a basis of constants, and minimal-polynomial search for algebraic
numbers. A candidate is numeric agreement to the digits given, never a proof.
"""
from __future__ import annotations

import itertools
import math
import re

import mpmath as mp
import sympy as sp

from .. import registry
from ..evidence import Evidence
from . import _algebra as alg
from . import _continuous as C

NAME = "identify"
RELIABLE_DIGITS = 15            # below this a match is weak
MAX_CANDIDATES = 12
DEFAULT_BASIS = ["pi", "E", "sqrt(2)", "sqrt(3)", "sqrt(5)", "log(2)", "log(3)", "EulerGamma", "zeta(3)",
                 "Catalan"]
EXTRA_DEFAULT = ["pi**2"]       # a derived constant also tried when the basis is the default one
FILL = 0.6                      # a relation is kept only if its coefficients take up at most this much of the digits

_DECIMAL = re.compile(r"^\s*([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?\s*$")

_SCHEMA = {
    "type": "object", "required": ["value"], "additionalProperties": False,
    "properties": {
        "value": {"type": ["string", "number"],
                  "description": "The number to identify: a decimal string with as many digits as you have "
                                 "('0.5772156649015328606'), or an expression evaluated to `digits` digits "
                                 "('sqrt(2)+1'). A JSON number is a float and counts as 15 digits."},
        "digits": {"type": "integer", "minimum": 5, "maximum": 1000, "default": 30,
                   "description": "Significant digits an expression `value` is evaluated to (default 30). "
                                  "Ignored for a decimal string, whose own digits are used."},
        "basis": {"type": "array", "items": {"type": "string", "minLength": 1}, "maxItems": 20,
                  "description": "Constants to look for, as expressions ('pi', 'log(2)', 'sqrt(7)'). 1 is always "
                                 "included. Default: pi, E, sqrt(2), sqrt(3), sqrt(5), log(2), log(3), "
                                 "EulerGamma, zeta(3), Catalan (and pi**2). Use E for Euler's number."},
        "max_terms": {"type": "integer", "minimum": 1, "maximum": 3, "default": 2,
                      "description": "How many basis constants (besides 1) one candidate may combine (default 2)."},
        "max_degree": {"type": "integer", "minimum": 2, "maximum": 8, "default": 4,
                       "description": "Highest degree of the integer polynomial searched for (default 4)."},
        "proposed": {"description": "A closed form to compare with the best candidate (an expression string). "
                                    "Sets `compare`; it is a plain comparison, not a judgement."},
    },
}


class _Bad(ValueError):
    pass


def _read_value(value, digits: int):
    """(x as mpf at working precision, significant digits, absolute error bound, source note)."""
    notes = []
    if isinstance(value, bool):
        raise _Bad("value must be a number or a string")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _Bad("value is not finite")
        notes.append("the value was given as a float, which holds about 15 reliable digits; only 15 are used "
                     "(pass a decimal string to supply more)")
        value = f"{value:.14e}"
    if isinstance(value, int):
        value = str(value)
    m = _DECIMAL.match(value) if isinstance(value, str) else None
    if m and (m.group(2) or m.group(3)):
        sign, ip, fp, ex = m.group(1), m.group(2), m.group(3) or "", int(m.group(4) or 0)
        sig = (ip + fp).lstrip("0")
        if not sig:
            raise _Bad("the value is zero; there is nothing to identify")
        n_dig = len(sig)
        decimals = len(fp) - ex
        dps = max(n_dig, 15) + 30
        with mp.workdps(dps + max(0, -decimals)):
            x = mp.mpf(f"{sign}{ip or '0'}.{fp or '0'}e{ex}")
        err = mp.mpf(10) ** (-decimals)
        return x, n_dig, err, notes
    # an expression
    try:
        e = C.parse(value)
        C.check_function(e, [], "the value")
    except ValueError as exc:
        raise _Bad(str(exc)) from None
    dps = digits + 30
    try:
        with mp.workdps(dps):
            v = sp.N(e, dps)
            if v.has(sp.nan, sp.zoo, sp.oo, -sp.oo) or not v.is_real:
                raise _Bad(f"the value {value!r} is not a finite real number")
            x = mp.mpf(str(v))
    except (TypeError, ValueError, ArithmeticError) as exc:
        raise _Bad(f"could not evaluate {value!r}: {exc}") from None
    if x == 0:
        raise _Bad("the value is zero; there is nothing to identify")
    with mp.workdps(dps):
        mag = int(mp.floor(mp.log10(abs(x))))
    decimals = digits - 1 - mag
    return x, digits, mp.mpf(10) ** (-decimals), notes


def _clen(coeffs) -> float:
    return sum(math.log10(1 + abs(int(c))) for c in coeffs)


def _fmt_err(r) -> str:
    return mp.nstr(r, 3) if r != 0 else "0"


def _linear_candidate(coeffs, consts, x, err, n_dig, dps):
    """x = -(c1*1 + c2*b1 + ...)/c0 as a sympy expression, checked against x. None if it does not hold."""
    c0 = int(coeffs[0])
    if c0 == 0:
        return None
    expr = sp.Add(*[sp.Rational(-int(c), c0) * k for c, k in zip(coeffs[1:], consts) if c != 0])
    with mp.workdps(dps):
        approx = mp.mpf(str(sp.N(expr, dps)))
        res = abs(x - approx)
    if res > err * mp.mpf("1.01"):
        return None
    return expr, res


def _poly_candidate(coeffs, x, err, dps):
    """The minimal polynomial `coeffs` (highest degree first) if it is irreducible and has a root within the
    error of x. Returns (poly, root_expression, residual) or None."""
    X = sp.Symbol("x")
    poly = sp.Poly([int(c) for c in coeffs], X, domain="ZZ")
    if poly.degree() < 2 or not poly.is_irreducible:
        return None
    with mp.workdps(dps):
        try:
            roots = mp.polyroots([int(c) for c in coeffs], maxsteps=2000, extraprec=4 * dps)
        except (mp.NoConvergence, ZeroDivisionError):
            return None
        real = [r for r in roots if abs(mp.im(r)) < mp.mpf(10) ** (-dps // 2)]
        if not real:
            return None
        r = min(real, key=lambda t: abs(mp.re(t) - x))
        res = abs(mp.re(r) - x)
        if res > err * mp.mpf("1.01"):
            return None
    target = float(mp.re(r))
    root = min(sp.real_roots(poly), key=lambda t: abs(float(sp.N(t, 20)) - target))
    if poly.degree() == 2:
        try:
            root = min(sp.solve(poly.as_expr(), X), key=lambda t: abs(float(sp.N(t, 20)) - target))
        except (NotImplementedError, ValueError, TypeError):
            pass
    return poly, root, res


def _parse_basis(items):
    out = []
    for s in items:
        e = C.parse(s)
        C.check_function(e, [], f"basis element {s!r}")
        if not (e.is_number and e.is_real) or e.has(sp.oo, -sp.oo):
            raise ValueError(f"basis element {s!r} is not a finite real constant")
        if e.is_Rational:
            continue   # 1 is always there; a rational constant adds nothing to it
        out.append(e)
    uniq = []
    for e in out:
        if e not in uniq:
            uniq.append(e)
    return uniq


@registry.button(
    NAME,
    description="Turn a decimal into a closed form. Searches for an integer relation (PSLQ) between the number, "
                "1 and one or two constants from a basis (default pi, E, sqrt(2), sqrt(3), sqrt(5), log 2, log 3, "
                "Euler's gamma, zeta(3), Catalan's G, pi**2), for a rational, and for an integer polynomial the "
                "number is a root of (an algebraic number). Gives candidates, each with its residual and the "
                "digits used, simplest first. With fewer than 15 reliable digits a match is weak, and the result "
                "says so. Numeric agreement is evidence, not a proof.",
    input_schema=_SCHEMA,
)
def identify(inp: dict, ctx) -> Evidence:
    try:
        return _run(inp, ctx)
    except (_Bad, ValueError) as e:
        return alg.bad_input(NAME, str(e), scope="input rejected; nothing was computed")


def _run(inp: dict, ctx) -> Evidence:
    digits = int(inp.get("digits", 30))
    max_terms = int(inp.get("max_terms", 2))
    max_degree = int(inp.get("max_degree", 4))
    default_basis = "basis" not in inp
    x, n_dig, err, notes = _read_value(inp["value"], digits)
    try:
        basis = _parse_basis(inp["basis"] if not default_basis else DEFAULT_BASIS)
        if default_basis:
            basis += _parse_basis(EXTRA_DEFAULT)
    except ValueError as e:
        raise _Bad(str(e)) from None
    dps = max(n_dig, 15) + 30
    names = ["1"] + [str(b) for b in basis]

    max_exp = max(10 ** 1, int(10 ** min(8, max(1.0, 0.35 * n_dig))))
    cands: dict = {}   # expression string -> candidate dict
    sym: dict = {}     # expression string -> sympy expression
    stopped = False
    tried = 0

    def add(kind, expr, res, coeffs, extra=None):
        key = f"{kind}|{expr}"
        c = {"kind": kind, "expression": str(expr), "latex": sp.latex(expr), "residual": _fmt_err(res),
             "digits_used": n_dig,
             "agreeing_digits": round(float(-mp.log10(res / abs(x))), 1) if res > 0 else None,
             "coefficient_digits": round(_clen(coeffs), 2)}
        if extra:
            c.update(extra)
        c["_key"] = key
        old = cands.get(key)
        if old is None or c["coefficient_digits"] < old["coefficient_digits"]:
            cands[key] = c
            sym[key] = expr

    pool = list(basis)
    consts = [sp.Integer(1)] + pool
    with mp.workdps(dps):
        vals = [mp.mpf(1)] + [mp.mpf(str(sp.N(b, dps))) for b in pool]
        tol = err * 100
        subsets = [()] + [s for k in range(1, max_terms + 1) for s in itertools.combinations(range(len(pool)), k)]
        for si, sub in enumerate(subsets):
            if ctx.time_left() <= 0:
                stopped = True
                break
            tried += 1
            idx = [0] + [i + 1 for i in sub]
            vec = [x] + [vals[i] for i in idx]
            try:
                rel = mp.pslq(vec, tol=tol, maxcoeff=max_exp, maxsteps=20000)
            except (ValueError, ZeroDivisionError, OverflowError):
                rel = None
            if rel and rel[0] != 0 and all(rel[1 + j] != 0 for j, i in enumerate(idx) if i != 0) \
                    and _clen(rel) <= FILL * n_dig:
                got = _linear_candidate(rel, [consts[i] for i in idx], x, err, n_dig, dps)
                if got:
                    expr, res = got
                    add("rational" if not sub else "linear", expr, res, rel)
            if si % 8 == 0:
                ctx.progress({"result": {"candidates": list(cands.values()), "digits_used": n_dig},
                              "method": "numeric", "scope": f"{tried} of {len(subsets)} constant sets tried"})

        if not stopped:
            xs = sp.Symbol("x")
            for n in range(2, max_degree + 1):
                if ctx.time_left() <= 0:
                    stopped = True
                    break
                tried += 1
                ptol = tol * max(1, abs(x)) ** n * 10
                try:
                    co = mp.findpoly(x, n, maxcoeff=max_exp, tol=ptol, maxsteps=20000)
                except (ValueError, ZeroDivisionError, OverflowError):
                    co = None
                if co and co[0] < 0:
                    co = [-c for c in co]
                if co and _clen(co) <= FILL * n_dig:
                    got = _poly_candidate(co, x, err, dps)
                    if got:
                        poly, root, res = got
                        add("algebraic", root, res, co,
                            {"polynomial": str(poly.as_expr()), "coefficients": [int(c) for c in co],
                             "degree": poly.degree()})

    found = sorted(cands.values(), key=lambda c: (c["coefficient_digits"], len(c["expression"])))[:MAX_CANDIDATES]
    best_sym = sym[found[0]["_key"]] if found else None
    for c in found:
        c.pop("_key")
    rendered = mp.nstr(x, min(n_dig, 60)) if n_dig <= 60 else mp.nstr(x, 60)
    result = {"value": rendered, "digits_used": n_dig, "tolerance": mp.nstr(err, 3), "candidates": found,
              "basis": names}
    ev_notes = list(notes)
    flags = []
    if n_dig < RELIABLE_DIGITS:
        ev_notes.append(f"only {n_dig} digits were given, fewer than {RELIABLE_DIGITS} reliable digits: candidates "
                        f"are weak, since a short formula can match this few digits by chance")
        flags.append(("weak_evidence", f"{n_dig} digits is too few for a match to be convincing"))
    if not found and not stopped:
        ev_notes.append("no relation was found within the coefficient bound; that does not mean none exists "
                        "(the number may need other constants, larger coefficients or more digits)")
    if default_basis:
        ev_notes.append("the default basis was used (pi, E, sqrt(2), sqrt(3), sqrt(5), log 2, log 3, EulerGamma, "
                        "zeta(3), Catalan, and pi**2); a number outside the span of these will not be found")
    ev_notes.append("candidates are numeric agreement to the digits used, not proofs; the residual is the "
                    "difference from the given value")
    scope = (f"PSLQ search on {n_dig} digits (tolerance {mp.nstr(err, 2)}) for a rational, for combinations of 1 and "
             f"up to {max_terms} of {len(basis)} basis constants with coefficients up to {max_exp}, and for an "
             f"integer polynomial of degree 2 to {max_degree}; {tried} searches run; numeric agreement, not a proof")
    ev = Evidence(button=NAME, result=result, method="numeric", scope=scope, complete=not stopped,
                  precision={"digits": n_dig, "tolerance": mp.nstr(err, 3)}, notes=ev_notes)
    for code, msg in flags:
        ev.flag(code, msg)
    if stopped:
        C.budget_stop(ev, f"{tried} of {len(subsets) + max_degree - 1} searches were run, so the candidates "
                          f"may be incomplete")
    if "proposed" in inp:
        alg.compare(ev, inp["proposed"], best_sym, lambda s: C.parse(s))
    return ev
