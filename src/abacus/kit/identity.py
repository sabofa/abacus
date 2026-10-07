"""`identity`: are two expressions equal? (kit/04 s3)

Two separate answers, kept separate. The symbolic one is sympy's: `equal` only when sympy reduces
lhs - rhs to 0, `not_equal` only when sympy shows lhs - rhs cannot vanish, otherwise `unknown`
(and unknown is not a no). The numeric one evaluates both sides at random points of the stated
domain at high precision and reports the largest difference and the first point where they differ.
Numeric agreement never turns an `unknown` into an `equal`.
"""
from __future__ import annotations

import itertools
import math
import random
import re

import sympy as sp
from sympy.polys.polyerrors import BasePolynomialError

from .. import registry
from ..evidence import Evidence, make_compare
from . import _algebra as alg

DEFAULT_POINTS = 50
DEFAULT_DIGITS = 30
MAX_EXAMPLES = 20
_GUARD = 15   # extra digits the sides are evaluated with, beyond those compared

_SCHEMA = {
    "type": "object", "required": ["lhs", "rhs"], "additionalProperties": False,
    "properties": {
        "lhs": {"type": "string", "minLength": 1, "description": "The left side, e.g. 'sin(x)**2 + cos(x)**2'."},
        "rhs": {"type": "string", "minLength": 1, "description": "The right side, e.g. '1'."},
        "vars": {"type": "array", "items": {"type": "string", "pattern": alg.IDENT},
                 "description": "The variables. A symbol that appears in the expressions but is not listed is "
                                "still sampled (and noted)."},
        "domain": {"type": "object", "additionalProperties": {"type": "string"},
                   "description": "Per variable, where it lives: 'integer >= 1', 'real in (0, pi)', "
                                  "'positive integer', 'real > 0', 'complex' ... A variable with no domain is "
                                  "real (sampled on (-10, 10)). Sympy simplifies under the same assumptions."},
        "points": {"type": "integer", "minimum": 1, "maximum": 2000, "default": DEFAULT_POINTS,
                   "description": "How many points to try (fewer if the domain has fewer points)."},
        "digits": {"type": "integer", "minimum": 5, "maximum": 100, "default": DEFAULT_DIGITS,
                   "description": "Digits of agreement required: |lhs - rhs| <= 10^-digits * max(1, |lhs|, |rhs|)."},
        "seed": {"type": "integer", "minimum": 0, "description": "Seeds the random points; the same seed gives "
                                                                  "the same points."},
        "proposed": {"enum": ["equal", "not_equal", True, False],
                     "description": "Your claim about the symbolic result (true means 'equal'). Sets `compare`, "
                                    "a plain comparison with sympy's answer, not a judgement."},
    },
}


# ----------------------------------------------------------------------------- symbolic stage


def _symbolic(lhs, rhs, variables, doms, ctx):
    """(relation, source, finished). Sympy's answer to 'is lhs - rhs zero', and what it rests on."""
    if lhs == rhs:
        return "equal", "the two sides are identical after parsing", True
    diff = lhs - rhs
    steps = (("expand", sp.expand),
             ("simplify", sp.simplify),
             ("expand_func then simplify", lambda e: sp.simplify(sp.expand_func(e))))
    left = diff   # the simplest form of lhs - rhs reached, for the analysis below
    for name, step in steps:
        if ctx.time_left() <= 0:
            return "unknown", (f"stopped at the time budget before sympy {name}; unknown is not a no"), False
        try:
            out = step(diff)
        except (ValueError, TypeError, ArithmeticError, NotImplementedError, BasePolynomialError):
            continue
        if out == 0:
            return "equal", f"sympy {name} → 0", True
        if name == "simplify" or left is diff:
            left = out
    if not diff.free_symbols:
        try:
            if diff.equals(0):
                return "equal", "sympy equals → True (the difference is a constant that sympy proves is 0)", True
        except (ValueError, TypeError, ArithmeticError, NotImplementedError):
            pass
    if left.is_zero is False:
        return "not_equal", (f"sympy: lhs - rhs simplifies to {left}, which sympy proves is never 0 under "
                             f"the assumptions"), True
    syms = list(variables)
    if syms and all(doms[v.name].is_infinite() for v in syms):
        try:
            poly = sp.Poly(sp.expand(left), *syms)
        except (BasePolynomialError, ValueError, TypeError):
            poly = None
        if poly is not None and any(c.is_zero is False for c in poly.coeffs()):
            return "not_equal", (f"lhs - rhs expands to the nonzero polynomial {sp.expand(left)}; a nonzero "
                                 f"polynomial cannot vanish on a whole infinite domain"), True
    shown = str(left)
    shown = shown if len(shown) <= 120 else shown[:117] + "..."
    return "unknown", (f"sympy could not reduce lhs - rhs to 0 (it got as far as {shown}); "
                       f"unknown is not a no"), True


# ----------------------------------------------------------------------------- numeric stage


def _value(expr, subs: dict, dps: int):
    """(number, None) or (None, reason): evaluate at an exact point, then to dps digits."""
    try:
        v = expr.subs(subs)
        if v.has(sp.nan, sp.zoo, sp.oo, -sp.oo):
            return None, "undefined"
        v = sp.N(v, dps)
    except Exception:  # noqa: BLE001  (sympy has many ways to fail on a point it cannot evaluate)
        return None, "error"
    if not v.is_number:
        return None, "unevaluated"
    if v.has(sp.nan, sp.zoo, sp.oo, -sp.oo):
        return None, "undefined"
    return v, None


def _points(variables: list, doms: dict, n: int, rng) -> tuple[list, bool]:
    """(points, enumerated). Each point is a tuple of (exact value, JSON value), one per variable.
    A domain window with no more than n points is enumerated whole; otherwise points are random."""
    if not variables:
        return [()], True
    counts = [doms[v.name].count for v in variables]
    if all(c is not None for c in counts) and math.prod(counts) <= n:
        ranges = [range(doms[v.name].window[0], doms[v.name].window[1] + 1) for v in variables]
        return [tuple((sp.Integer(i), i) for i in combo) for combo in itertools.product(*ranges)], True
    seen, out = set(), []
    for _ in range(n * 20):
        if len(out) >= n:
            break
        pt = tuple(doms[v.name].sample(rng) for v in variables)
        key = tuple(py for _, py in pt)
        if key not in seen:
            seen.add(key)
            out.append(pt)
    return out, False


def _fmt(v, digits: int) -> str:
    return str(sp.N(v, digits))


def _numeric(lhs, rhs, variables: list, doms: dict, points: int, digits: int, seed: int, ctx) -> dict:
    dps = digits + _GUARD
    pts, enumerated = _points(variables, doms, points, random.Random(seed))
    tol = sp.Rational(1, 10 ** digits)
    tested = skipped = one_side = mismatches = 0
    max_diff = sp.Integer(0)
    examples: list[dict] = []
    stopped = None
    for i, pt in enumerate(pts):
        if ctx.time_left() <= 0:
            stopped = i
            break
        subs = {v: val for v, (val, _) in zip(variables, pt, strict=True)}
        lv, lwhy = _value(lhs, subs, dps)
        rv, rwhy = _value(rhs, subs, dps)
        if lv is None or rv is None:
            skipped += 1
            if (lv is None) != (rv is None) and (lwhy if lv is None else rwhy) == "undefined":
                one_side += 1
            continue
        tested += 1
        diff = sp.N(sp.Abs(lv - rv), dps)
        scale = max(1, sp.N(sp.Abs(lv), dps), sp.N(sp.Abs(rv), dps))
        if diff > max_diff:
            max_diff = diff
        if diff > tol * scale:
            mismatches += 1
            if len(examples) < MAX_EXAMPLES:
                examples.append({"point": {v.name: py for v, (_, py) in zip(variables, pt, strict=True)},
                                 "lhs": _fmt(lv, digits), "rhs": _fmt(rv, digits), "abs_diff": _fmt(diff, 6)})
    return {
        "points_requested": points, "points_tested": tested, "points_skipped": skipped,
        "one_side_undefined": one_side, "mismatches": mismatches,
        "max_abs_diff": _fmt(max_diff, 6), "counterexample": examples[0] if examples else None,
        "enumerated": enumerated,
        "domain_covered": enumerated and all(not doms[v.name].is_infinite() for v in variables),
        "examples": examples, "stopped_after": stopped, "sampled": len(pts),
    }


def _window_text(d) -> str:
    lo, hi = d.window
    if d.kind == "complex":
        return f"re and im in [{lo:g}, {hi:g}]"
    return f"[{lo}, {hi}]" if d.kind == "integer" else f"[{lo:g}, {hi:g}]"


# ----------------------------------------------------------------------------- the button


@registry.button(
    "identity",
    description="Are two expressions equal? Two separate answers: sympy's symbolic one (equal only if sympy "
                "reduces lhs - rhs to 0, not_equal only if it shows the difference cannot vanish, otherwise "
                "unknown, which is not a no) and a numeric one (both sides evaluated to `digits` digits at "
                "random points of the stated domain: the largest difference and the first counterexample). "
                "Numeric agreement is evidence, never proof. Seeded.",
    input_schema=_SCHEMA,
    uses_seed=True,
)
def identity(inp: dict, ctx) -> Evidence:
    points = int(inp.get("points", DEFAULT_POINTS))
    digits = int(inp.get("digits", DEFAULT_DIGITS))
    seed = ctx.seed if ctx.seed is not None else 0
    try:
        declared = {n: alg.parse_domain(s) for n, s in (inp.get("domain") or {}).items()}
        for n in declared:
            if not re.match(alg.IDENT, n):
                raise ValueError(f"{n!r} is not a variable name")
        for n in inp.get("vars") or []:
            if not isinstance(n, str) or not re.match(alg.IDENT, n):
                raise ValueError(f"{n!r} in vars is not a variable name (a plain identifier such as x or x_1)")
        default = alg.parse_domain("real")
        names = list(dict.fromkeys([*(inp.get("vars") or []), *declared]))
        sources = [inp["lhs"], inp["rhs"]]

        def build(names):
            syms = {n: sp.Symbol(n, **(declared.get(n) or default).assumptions()) for n in names}
            return syms, [alg.parse(s, syms, rational=True) for s in sources]

        syms, (lhs, rhs) = build(names)
        extra = sorted({s.name for e in (lhs, rhs) if isinstance(e, sp.Basic) for s in e.free_symbols} - set(names))
        if extra:   # a symbol the caller did not list: real, like any variable with no domain
            syms, (lhs, rhs) = build([*names, *extra])
        for side, e in (("lhs", lhs), ("rhs", rhs)):
            if not isinstance(e, sp.Expr):
                raise ValueError(f"{side} must be an expression, not {type(e).__name__} (a relation, a list ...)")
    except ValueError as e:
        return alg.bad_input("identity", str(e))

    doms = {n: declared.get(n) or default for n in syms}
    used = sorted({s for e in (lhs, rhs) for s in e.free_symbols}, key=lambda s: s.name)
    notes = alg.input_notes(sources, True)
    note = alg.undefined_function_note(lhs, rhs)
    if note:
        notes.append(note)
    if extra:
        notes.append(f"{', '.join(extra)} appear in the expressions but not in `vars`; sampled as real "
                     f"(the default domain)")
    unused = [n for n in declared if n not in {s.name for s in used}]
    if unused:
        notes.append(f"a domain was given for {', '.join(unused)}, which does not appear in the expressions")
    defaulted = [s.name for s in used if s.name not in declared]
    if defaulted:
        notes.append(f"{', '.join(defaulted)} had no domain, so it was taken as real (sampled on [-10, 10])")

    num = _numeric(lhs, rhs, used, doms, points, digits, seed, ctx)
    parts = []
    for s in used:
        d = doms[s.name]
        parts.append(f"{s.name}: {d.text}" + (f" sampled on {_window_text(d)}" if d.is_infinite() else ""))
    where = "; ".join(parts) or "no variables"
    how = (f"every one of the {num['sampled']} points of the window" if num["enumerated"]
           else f"{num['sampled']} random points, seed {seed}")
    num_scope = (f"numeric: {num['points_tested']} of {num['sampled']} points evaluated on both sides at "
                 f"{digits} digits ({how}; {where})")
    precision = {"digits": digits, "working_digits": digits + _GUARD,
                 "agreement": f"|lhs - rhs| <= 1e-{digits} * max(1, |lhs|, |rhs|)"}
    numeric = {k: num[k] for k in ("points_requested", "points_tested", "points_skipped", "one_side_undefined",
                                   "mismatches", "max_abs_diff", "counterexample", "enumerated", "domain_covered")}
    numeric["domains"] = {s.name: doms[s.name].text for s in used}
    # If sympy hangs and the child is killed, this is what survives.
    ctx.progress({"result": {"symbolic": {"relation": "unknown", "source": "not finished: the time budget ended "
                                                                           "during the symbolic stage"},
                             "numeric": numeric},
                  "scope": f"numeric stage only; {num_scope}", "method": "symbolic"})

    rel, source, finished = _symbolic(lhs, rhs, used, doms, ctx)
    complete = finished and num["stopped_after"] is None
    scope = ("symbolic: sympy " + ("simplification of lhs - rhs under the domains' assumptions"
                                   if finished else "simplification of lhs - rhs, stopped at the time budget")
             + "; " + num_scope + (f"; stopped after {num['stopped_after']} of {num['sampled']} points at the "
                                   f"time budget" if num["stopped_after"] is not None else ""))

    ev = Evidence(button="identity", result={"symbolic": {"relation": rel, "source": source}, "numeric": numeric},
                  method="symbolic", scope=scope, complete=complete, precision=precision, notes=notes,
                  examples=num["examples"], seed=seed)
    if rel == "equal":
        ev.notes.append("equal as expressions: sympy cancels common factors, so they agree wherever both sides "
                        "are defined; a removable singularity (as in (x**2-1)/(x-1) against x+1 at x = 1) is "
                        "not reported as a difference")
    if num["mismatches"]:
        ev.flag("counterexample_found", f"lhs and rhs differ at {num['counterexample']['point']} "
                                        f"(|lhs - rhs| = {num['counterexample']['abs_diff']}); {num['mismatches']} "
                                        f"of {num['points_tested']} tested points differ")
    if num["points_tested"] == 0:
        ev.flag("no_points_tested", "no point could be evaluated on both sides, so the numeric part says "
                                    "nothing (undefined functions, poles, or an expression sympy cannot evaluate)")
    if rel == "equal" and num["mismatches"]:
        ev.flag("symbolic_numeric_disagree", "sympy reduced lhs - rhs to 0 but the numeric part found a point "
                                             "where the sides differ: check the domain, the branch of any "
                                             "multivalued function, and the precision")
    if rel == "not_equal" and num["points_tested"] and not num["mismatches"]:
        ev.flag("symbolic_numeric_disagree", "sympy shows lhs - rhs cannot vanish everywhere, but every tested "
                                             "point agrees: the sides may differ only by something very small "
                                             "or somewhere the sample did not reach")
    if rel == "unknown" and num["points_tested"] and not num["mismatches"]:
        ev.notes.append(f"sympy could not decide (unknown is not a no). The sides agree to {digits} digits at all "
                        f"{num['points_tested']} tested points, which is evidence, not a proof")
    if num["one_side_undefined"]:
        ev.notes.append(f"at {num['one_side_undefined']} point(s) exactly one side was undefined (a pole or a "
                        f"removable singularity), so the point was skipped, not counted as a difference")
    if num["domain_covered"] and not num["mismatches"] and num["points_tested"] and not num["points_skipped"]:
        ev.notes.append("the whole (finite) domain was tried point by point and the sides agreed at every one, "
                        "to the stated precision")
    if "proposed" in inp:
        p = inp["proposed"]
        p = "equal" if p is True else "not_equal" if p is False else p
        ev.compare = make_compare(p, rel)
    return ev
