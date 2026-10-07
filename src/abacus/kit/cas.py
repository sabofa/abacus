"""`cas`: symbolic algebra (kit/04 s2).

One button, seventeen operations, all by sympy. What it adds is honesty about sympy's answers: a
conditional (Piecewise, ConditionSet) or unevaluated (Integral, Sum, Limit ...) result is said to be one,
an empty solution list is not read as "no solutions", and a two-sided limit is checked from both sides.
"""
from __future__ import annotations

import re

import sympy as sp
from sympy.core.relational import Relational
from sympy.polys.polyerrors import BasePolynomialError, NotAlgebraic

from .. import registry
from ..evidence import Evidence
from . import _algebra as alg

OPS = ("simplify", "expand", "factor", "solve", "solveset", "sum", "product", "limit", "series", "diff",
       "integrate", "apart", "together", "roots", "resultant", "minimal_polynomial", "nsimplify")

_NUM = {"type": ["string", "number"]}
_SCHEMA = {
    "type": "object", "required": ["op"], "additionalProperties": False,
    "properties": {
        "op": {"enum": list(OPS), "description": "The operation."},
        "expr": {"type": "string", "minLength": 1,
                 "description": "The expression (or, for solve and solveset, an equation such as 'x**2 = 4'; "
                                "a bare expression means 'expr = 0'). Give expr or exprs."},
        "exprs": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1,
                  "description": "Several expressions: the equations of a system for solve, the two "
                                 "polynomials for resultant. Every other op takes exactly one."},
        "vars": {"type": "array", "items": {"type": "string", "pattern": alg.IDENT},
                 "description": "The variables. solve solves for these; a one-variable op uses the only one "
                                "if `var` is not given."},
        "assumptions": {"type": "object", "additionalProperties": {"type": "string"},
                        "description": "Per variable, e.g. {'x': 'positive integer'}. Sympy then simplifies, "
                                       "solves and sums under them. Domain grammar: 'integer', 'real', "
                                       "'positive', 'integer >= 1', 'real in (0, pi)' ..."},
        "var": {"type": "string", "pattern": alg.IDENT,
                "description": "The variable of sum, product, limit, series, diff, integrate, apart, roots, "
                               "resultant, solveset and minimal_polynomial. Defaults to the only variable."},
        "lower": {**_NUM, "description": "sum, product: the lower bound of `var` (an expression, e.g. 1). "
                                         "integrate: with `upper`, makes it a definite integral."},
        "upper": {**_NUM, "description": "sum, product: the upper bound (e.g. 'n' or 'oo')."},
        "point": {**_NUM, "description": "limit: where `var` goes (e.g. 0, 'oo', 'pi'). series: the expansion "
                                         "point (default 0)."},
        "direction": {"enum": ["+", "-", "+-"],
                      "description": "limit: from the right, from the left, or both sides (default '+-': each "
                                     "side is computed and they must agree)."},
        "order": {"type": "integer", "minimum": 1, "maximum": 200,
                  "description": "series: the result is correct up to O(var**order) (default 6). diff: how many "
                                 "times to differentiate (default 1)."},
        "tolerance": {"type": "number", "exclusiveMinimum": 0,
                      "description": "nsimplify: how close the simple form must be to the number."},
        "proposed": {"description": "A value to compare with the computed one (an expression string; a list "
                                    "of solutions). Sets `compare`; a plain comparison, not a judgement."},
    },
}

_BAD = (ValueError, TypeError, ZeroDivisionError, ArithmeticError, BasePolynomialError)
_EQ = re.compile(r"(?<![<>=!])=(?!=)")


# ----------------------------------------------------------------------------- inputs


def _symbols(inp: dict) -> tuple[dict, list[str]]:
    """Symbols named by vars, var and assumptions (carrying their assumptions), and the assumption texts."""
    assumed = {}
    for name, spec in (inp.get("assumptions") or {}).items():
        if not re.match(alg.IDENT, name):
            raise ValueError(f"{name!r} is not a variable name")
        assumed[name] = alg.parse_domain(spec)
    names = list(dict.fromkeys([*(inp.get("vars") or []), *([inp["var"]] if inp.get("var") else []), *assumed]))
    syms = {n: sp.Symbol(n, **(assumed[n].assumptions() if n in assumed else {})) for n in names}
    texts = [f"{n}: {inp['assumptions'][n]}" for n in assumed]
    return syms, texts


def _parse_item(s: str, syms: dict, rational: bool):
    """One expression; a lone '=' makes it an equation."""
    parts = _EQ.split(s)
    if len(parts) == 1:
        return alg.parse(s, syms, rational=rational)
    if len(parts) > 2:
        raise ValueError(f"more than one '=' in {s!r}")
    return sp.Eq(alg.parse(parts[0], syms, rational=rational), alg.parse(parts[1], syms, rational=rational))


def _free(e) -> list:
    return sorted(e.free_symbols, key=lambda s: s.name)


def _one_var(inp: dict, syms: dict, exprs: list, op: str):
    """The variable of a one-variable op: `var`, else the only free symbol, else the only one in `vars`."""
    if inp.get("var"):
        return syms[inp["var"]]
    free = sorted({s for e in exprs for s in _free(e)}, key=lambda s: s.name)
    if len(free) == 1:
        return free[0]
    listed = [syms[v] for v in inp.get("vars") or [] if syms[v] in free]
    if len(listed) == 1:
        return listed[0]
    if free:
        raise ValueError(f"{op} works in one variable, but the expression has {', '.join(map(str, free))}: "
                         f"pass `var`")
    raise ValueError(f"{op} works in one variable and the expression has none: pass `var`")


def _need(inp: dict, op: str, *keys: str):
    for k in keys:
        if inp.get(k) is None:
            raise ValueError(f"{op} needs `{k}`")
    return [inp[k] for k in keys]


def _bound(inp: dict, key: str, syms: dict):
    return alg.parse(str(inp[key]), syms, rational=True)


# ----------------------------------------------------------------------------- result checks


def _result_notes(res) -> list[str]:
    """Say so when sympy's answer is unevaluated, conditional or only bounds (kit/03 s2, kit/04 s2)."""
    found = list(alg.walk(res))
    has = lambda *cls: any(b.has(*cls) for b in found)  # noqa: E731
    out = []
    for cls, name in ((sp.Integral, "Integral"), (sp.Sum, "Sum"), (sp.Product, "Product"), (sp.Limit, "Limit")):
        if has(cls):
            out.append(f"unevaluated {name} in the result: sympy found no closed form (or gave up). That does "
                       f"not mean none exists, and it is not a proof that none does")
    if has(sp.Piecewise):
        out.append("conditional result: the Piecewise lists cases, and each branch holds only where its "
                   "condition does (read the conditions before using the value)")
    if has(sp.ConditionSet):
        out.append("sympy returned a ConditionSet: it could not solve the equation in closed form; the set is "
                   "the unsolved condition, not a solution")
    if has(sp.Intersection, sp.Complement):
        out.append("an unevaluated Intersection or Complement: sympy could not work out the common part of two "
                   "sets, so the set is not in simplest form (it may be much smaller than it looks)")
    if has(sp.AccumBounds):
        out.append("AccumBounds: the function oscillates or has no single limit there; sympy gives the interval "
                   "it stays in, not a limit")
    if has(sp.CRootOf):
        out.append("roots are given as CRootOf: exact, but implicit (no radical form)")
    if has(sp.nan, sp.zoo):
        out.append("the result contains zoo or nan (complex infinity, or an undefined form such as 0/0)")
    return out


def _num_key(r):
    try:
        z = complex(sp.N(r, 15))
        return (0, z.real, z.imag, "")
    except (TypeError, ValueError):
        return (1, 0.0, 0.0, str(r))


# ----------------------------------------------------------------------------- the button


@registry.button(
    "cas",
    description="Symbolic algebra by sympy: simplify, expand, factor, solve, solveset, sum, product, limit, "
                "series, diff, integrate, apart, together, roots, resultant, minimal_polynomial, nsimplify. "
                "Returns the value as a string and LaTeX. Says when sympy's answer is unevaluated (Integral, "
                "Sum, Limit) or conditional (Piecewise, ConditionSet). An empty solution list is not read as "
                "'no solutions'.",
    input_schema=_SCHEMA,
)
def cas(inp: dict, ctx) -> Evidence:
    op = inp["op"]
    try:
        syms, assumption_texts = _symbols(inp)
        if inp.get("expr") is not None and inp.get("exprs") is not None:
            raise ValueError("give `expr` or `exprs`, not both")
        sources = [inp["expr"]] if inp.get("expr") is not None else list(inp.get("exprs") or [])
        if not sources:
            raise ValueError("give `expr` (or `exprs`)")
        if op == "resultant" and len(sources) != 2:
            raise ValueError(f"resultant takes two polynomials in `exprs`, but {len(sources)} were given")
        if op not in ("resultant", "solve") and len(sources) != 1:
            raise ValueError(f"{op} takes one expression, but {len(sources)} were given")
        rational = op != "nsimplify"
        exprs = [_parse_item(s, syms, rational) for s in sources]
        notes = alg.input_notes(sources, rational)
        undefined = alg.undefined_function_note(*exprs)
        if undefined:
            notes.append(undefined)
        res, extra, scope_what = _compute(op, inp, syms, exprs, notes)
    except NotImplementedError as e:
        ev = Evidence(button="cas", result=None, method="symbolic",
                      scope=f"sympy has no method for this {op}; nothing was computed", complete=False)
        ev.flag("unsupported", f"sympy cannot do this: {e}")
        return ev
    except NotAlgebraic as e:
        ev = Evidence(button="cas", result=None, method="symbolic",
                      scope="sympy could not show the number is algebraic; nothing was computed", complete=False)
        ev.flag("unsupported", f"sympy cannot do this: {e}")
        return ev
    except _BAD as e:
        return alg.bad_input("cas", f"{op}: {e}")

    if extra is not None:
        result = extra
    else:
        text, latex = alg.render(res)
        result = {"value": text, "latex": latex}
    notes.extend(_result_notes(res))
    scope = f"sympy {scope_what}, symbolic" + (f"; assumptions {', '.join(assumption_texts)}" if assumption_texts else "")
    ev = Evidence(button="cas", result=result, method="symbolic", scope=scope, complete=True, notes=notes)
    if "proposed" in inp:
        reshape = _reshaper(op, inp, syms)
        if reshape is not None:
            ev.notes.append("solutions are compared as sets, in any order; for a system each solution is a "
                            "tuple of values in the order of `vars`")
        alg.compare(ev, inp["proposed"], res, lambda s: _parse_item(s, syms, rational), reshape)
    return ev


def _reshaper(op: str, inp: dict, syms: dict):
    """Solutions are compared as sets, whatever order sympy or the caller listed them in."""
    if op not in ("solve", "solveset"):
        return None
    order = [syms[v] for v in inp.get("vars") or []] or None

    def reshape(x):
        if isinstance(x, sp.FiniteSet):
            x = list(x.args)
        if not isinstance(x, (list, tuple, set, frozenset)):
            return x
        out = set()
        for item in x:
            if isinstance(item, dict):
                keys = order or sorted(item, key=str)
                item = tuple(item.get(k, item.get(str(k))) for k in keys)
            elif isinstance(item, list):
                item = tuple(item)
            out.add(item)
        return out

    return reshape


def _compute(op: str, inp: dict, syms: dict, exprs: list, notes: list[str]):
    """(result object, replacement result dict or None, what was done)."""
    e = exprs[0]

    if op in ("simplify", "expand", "factor", "together"):
        return getattr(sp, op)(e), None, op

    if op == "nsimplify":
        tol = inp.get("tolerance")
        notes.append("nsimplify looks for a simple expression close to the number, within a tolerance; it is a "
                     "guess about the number, not proof that the number equals it")
        res = sp.nsimplify(e, tolerance=tol) if tol else sp.nsimplify(e)
        return res, None, "nsimplify" + (f" (tolerance {tol})" if tol else " (sympy's default tolerance)")

    if op == "apart":
        x = _one_var(inp, syms, exprs, op)
        return sp.apart(e, x), None, f"apart in {x}"

    if op == "diff":
        x = _one_var(inp, syms, exprs, op)
        n = int(inp.get("order", 1))
        return sp.diff(e, x, n), None, f"diff w.r.t. {x}" + (f", {n} times" if n != 1 else "")

    if op == "integrate":
        x = _one_var(inp, syms, exprs, op)
        lo, hi = inp.get("lower"), inp.get("upper")
        if (lo is None) != (hi is None):
            raise ValueError("a definite integral needs both `lower` and `upper`")
        if lo is None:
            notes.append("indefinite integral: sympy leaves out the constant of integration")
            return sp.integrate(e, x), None, f"integrate w.r.t. {x}"
        a, b = _bound(inp, "lower", syms), _bound(inp, "upper", syms)
        return sp.integrate(e, (x, a, b)), None, f"integrate w.r.t. {x} from {a} to {b}"

    if op in ("sum", "product"):
        _need(inp, op, "lower", "upper")
        x = _one_var(inp, syms, exprs, op)
        a, b = _bound(inp, "lower", syms), _bound(inp, "upper", syms)
        cls = sp.Sum if op == "sum" else sp.Product
        return cls(e, (x, a, b)).doit(), None, f"{op} over {x} from {a} to {b}"

    if op == "limit":
        _need(inp, op, "point")
        x = _one_var(inp, syms, exprs, op)
        p = alg.parse(str(inp["point"]), syms, rational=True)
        d = inp.get("direction", "+-")
        if p in (sp.oo, -sp.oo) or d != "+-":
            side = "" if p in (sp.oo, -sp.oo) else f" from the {'right' if d == '+' else 'left'}"
            dd = "-" if p == sp.oo else "+" if p == -sp.oo else d
            return sp.limit(e, x, p, dir=dd), None, f"limit as {x} -> {p}{side}"
        left, right = sp.limit(e, x, p, dir="-"), sp.limit(e, x, p, dir="+")
        same = left == right
        if not same:
            try:
                same = bool(sp.simplify(left - right) == 0)
            except (ValueError, TypeError, ArithmeticError):
                same = False
        if same:
            return right, None, f"limit as {x} -> {p}, from both sides"
        notes.append("the left and right limits differ, so the two-sided limit does not exist (sympy computed "
                     "each side separately)")
        lt, rt = alg.render(left)[0], alg.render(right)[0]
        return (left, right), {"value": None, "latex": None, "left": lt, "right": rt}, \
            f"limit as {x} -> {p}, from both sides"

    if op == "series":
        x = _one_var(inp, syms, exprs, op)
        p = alg.parse(str(inp.get("point", 0)), syms, rational=True)
        n = int(inp.get("order", 6))
        notes.append("the series ends with an O(...) remainder term: it marks what was cut off, it is not "
                     "part of the function")
        return sp.series(e, x, p, n), None, f"series in {x} at {p} to order {n}"

    if op == "solve":
        eqs = exprs
        if any(isinstance(q, Relational) and not isinstance(q, sp.Eq) for q in eqs):
            raise ValueError("solve takes equations; use solveset for an inequality such as x**2 <= 4")
        names = [syms[v] for v in (inp.get("vars") or [])]
        if inp.get("var"):
            names = [syms[inp["var"]]]
        if not names:
            free = sorted({s for q in eqs for s in _free(q)}, key=lambda s: s.name)
            if len(free) != 1:
                raise ValueError(f"solve needs to know the unknowns: pass `vars` ({'the expression has ' + ', '.join(map(str, free)) if free else 'it has no variable'})")
            names = free
        sols = sp.solve(eqs if len(eqs) > 1 else eqs[0], names, dict=True)
        if len(names) == 1 and all(names[0] in s for s in sols):
            res = [s[names[0]] for s in sols]
        else:
            res = sols
        if not res:
            notes.append("sympy returned no solutions. That does not prove there are none: for an equation it "
                         "cannot fully analyse, an empty list can also mean it found none")
        return res, None, "solve for " + ", ".join(map(str, names))

    if op == "solveset":
        x = _one_var(inp, syms, exprs, op)
        inequality = isinstance(e, Relational) and not isinstance(e, sp.Eq)
        dom = (sp.S.Integers if x.is_integer else sp.S.Reals if x.is_real or inequality else sp.S.Complexes)
        if inequality and not x.is_real and not x.is_integer:
            notes.append("an inequality has no meaning over the complex numbers, so it was solved over the reals")
        return sp.solveset(e, x, dom), None, f"solveset for {x} over the {dom}"

    if op == "roots":
        x = _one_var(inp, syms, exprs, op)
        poly = e.lhs - e.rhs if isinstance(e, sp.Eq) else e
        deg = sp.Poly(poly, x).degree()
        found = sp.roots(poly, x)
        res = dict(sorted(found.items(), key=lambda kv: _num_key(kv[0])))
        got = sum(res.values())
        if got < deg:
            notes.append(f"sympy found {got} of {deg} roots (counted with multiplicity); it returns only the "
                         f"roots it can write in closed form, so the rest exist but are not listed")
        return res, None, f"roots of a degree-{deg} polynomial in {x}"

    if op == "resultant":
        x = _one_var(inp, syms, exprs, op)
        return sp.resultant(exprs[0], exprs[1], x), None, f"resultant in {x}"

    if op == "minimal_polynomial":
        x = syms[inp["var"]] if inp.get("var") else syms[inp["vars"][0]] if inp.get("vars") else sp.Symbol("x")
        return sp.minimal_polynomial(e, x), None, f"minimal polynomial in {x}"

    raise ValueError(f"unknown op {op!r}")  # the schema's enum keeps this unreachable
