"""`exact`: exact evaluation of an expression (kit/04 s1).

Big integers, rationals, surds, modular arithmetic and number theory, all evaluated by sympy with no
floating point: 2**100 % 1000 is computed with the 31-digit integer, never a float.
"""
from __future__ import annotations

import sympy as sp

from .. import registry
from ..evidence import Evidence
from . import _algebra as alg

MAX_VALUE_CHARS = 10_000   # a value longer than this is summarised, not printed whole
_SIG_DIGITS = 30

_NAMES_HELP = ("factorint divisors totient mobius primepi isprime nextprime gcd lcm binomial multinomial factorial "
               "fibonacci catalan partition legendre jacobi n_order primitive_root discrete_log crt sqrt_mod "
               "powmod(a, b, m), plus sqrt, Rational, pi, E, I, oo and the usual functions")

_SCHEMA = {
    "type": "object", "required": ["expr"], "additionalProperties": False,
    "properties": {
        "expr": {"type": "string", "minLength": 1,
                 "description": "The expression to evaluate exactly, e.g. '2**100', 'totient(1000)', "
                                f"'sqrt(8)*3'. Names available: {_NAMES_HELP}. `^` means a power; a decimal "
                                "literal such as 0.1 is read as the exact rational 1/10."},
        "mod": {"type": "integer", "minimum": 1,
                "description": "Reduce an integer (or a rational with a denominator invertible mod m) "
                               "modulo this, to the residue in [0, mod)."},
        "proposed": {"description": "A value to compare with the computed one (a number, or an expression "
                                    "string). Sets `compare`; it is a plain comparison, not a judgement."},
    },
}


def _reduce(v, m: int):
    """v mod m, for an integer or a rational whose denominator is invertible mod m."""
    if isinstance(v, bool) or not isinstance(v, (int, sp.Rational)):
        raise ValueError(f"mod needs an integer or rational value, but the expression gave {alg.render(v)[0]}")
    v = sp.Rational(v)
    if v.q == 1:
        return sp.Integer(int(v.p) % m)
    if sp.igcd(int(v.q), m) != 1:
        raise ValueError(f"{v} cannot be reduced mod {m}: its denominator {v.q} shares a factor with {m}, "
                         f"so it has no inverse")
    return sp.Integer(int(v.p) * pow(int(v.q), -1, m) % m)


def _decimal(v) -> str | None:
    """30 significant digits of a numeric value; None for a list, a boolean, a dict ..."""
    if isinstance(v, bool) or not isinstance(v, sp.Expr) or not v.is_number:
        return None
    try:
        with alg.big_ints():
            return str(sp.N(v, _SIG_DIGITS))
    except (ValueError, TypeError, ArithmeticError):
        return None


@registry.button(
    "exact",
    description="Evaluate an expression exactly: big integers, rationals, surds, modular arithmetic and number "
                "theory (factorint, totient, binomial, partition, crt, discrete_log ...). Returns the exact value "
                "as a string and LaTeX, plus 30 significant digits. Symbolic: nothing is rounded.",
    input_schema=_SCHEMA,
)
def exact(inp: dict, ctx) -> Evidence:
    src, mod = inp["expr"], inp.get("mod")
    mod = None if mod is None else int(mod)   # 1000.0 passes the schema's "integer"
    try:
        v = alg.parse(src, namespace=alg.exact_namespace(), rational=True)
    except ValueError as e:
        return alg.bad_input("exact", str(e))
    syms, funcs = alg.unbound_names(v)
    if syms or funcs:
        return alg.bad_input(
            "exact", f"exact evaluates closed-form expressions, but {', '.join(syms + funcs)} is not defined "
                     f"(a misspelt function name is read as an unknown symbol); the names it knows: {_NAMES_HELP}")

    notes = alg.input_notes([src])
    # A number that is not already an integer or rational is put in its simplest exact form
    # (sympy leaves (1 + sqrt(5))*(1 - sqrt(5)) as a product).
    if isinstance(v, sp.Expr) and v.is_number and not v.is_Rational and not v.has(sp.Float, sp.nan, sp.zoo, sp.oo):
        try:
            v = sp.simplify(v)
        except (ValueError, TypeError, ArithmeticError):
            pass
    try:
        if mod is not None:
            v = _reduce(v, mod)
    except ValueError as e:
        return alg.bad_input("exact", str(e))

    flags = []
    if isinstance(v, sp.Basic) and v.has(sp.Float):
        flags.append(("inexact", "the result contains floating-point numbers, so it is not exact (a float came "
                                 "from a function such as evalf)"))
    if isinstance(v, sp.Basic) and v.has(sp.nan, sp.zoo):
        notes.append("the expression is undefined (zoo is complex infinity, from a division by zero; nan is "
                     "an undefined form such as 0/0)")
    if v is None:
        notes.append("the function returned None: it found no result (for crt or sqrt_mod, none exists)")

    text, latex = alg.render(v)
    dec = _decimal(v)
    if len(text) > MAX_VALUE_CHARS:
        digits = len(text.lstrip("-"))
        result = {"value": None, "latex": None, "decimal": dec, "digits": digits,
                  "head": text[:40], "tail": text[-40:]}
        flags.append(("value_too_long", f"the value has {digits} digits, too long to print; `head` and `tail` "
                                        f"are its first and last 40 characters. Use `mod` for a residue."))
    else:
        result = {"value": text, "latex": latex, "decimal": dec}
    if mod is not None:
        result["mod"] = mod

    scope = ("evaluated exactly by sympy with unbounded integers and rationals (no floating point)"
             + (f", then reduced mod {mod}" if mod is not None else ""))
    ev = Evidence(button="exact", result=result, method="symbolic", scope=scope, complete=True, notes=notes)
    for code, msg in flags:
        ev.flag(code, msg)
    if "proposed" in inp:
        alg.compare(ev, inp["proposed"], v, lambda s: alg.parse(s, namespace=alg.exact_namespace(), rational=True))
    return ev
