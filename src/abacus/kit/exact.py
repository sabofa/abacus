"""`exact`: exact evaluation of an expression (kit/04 s1).

Big integers, rationals, surds, modular arithmetic and number theory, all evaluated by sympy with no
floating point: 2**100 % 1000 is computed with the 31-digit integer, never a float.
"""
from __future__ import annotations

import ast
from fractions import Fraction

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


class _NoFastPath(Exception):
    """The expression is not plain integer arithmetic (or a step would be too big): evaluate it in full."""


_MAX_EXACT_BITS = 2_000_000   # an exponent subtree is built exactly only below this size


def _ipow_exact(b: int, e: int) -> int:
    if e < 0 or (e > 1 and abs(b) > 1 and e * abs(b).bit_length() > _MAX_EXACT_BITS):
        raise _NoFastPath
    return b ** e


def _mod_eval(node, m: int | None):
    """Integer value of a +, -, *, ** tree of integer literals: reduced mod m throughout when m is given
    (a power uses the three-argument pow, so 2**(10**12) is never built), else exact."""
    if isinstance(node, ast.Expression):
        return _mod_eval(node.body, m)
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value % m if m else node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _mod_eval(node.operand, m)
        v = -v if isinstance(node.op, ast.USub) else v
        return v % m if m else v
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Pow):
            e = _mod_eval(node.right, None)
            if m is None:
                return _ipow_exact(_mod_eval(node.left, None), e)
            if e < 0:
                raise _NoFastPath
            return pow(_mod_eval(node.left, m), e, m)
        if isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            a, b = _mod_eval(node.left, m), _mod_eval(node.right, m)
            v = a + b if isinstance(node.op, ast.Add) else a - b if isinstance(node.op, ast.Sub) else a * b
            return v % m if m else v
    raise _NoFastPath


def _fast_mod(src: str, m: int) -> int | None:
    """expr mod m for plain integer arithmetic, using modular exponentiation; None if the text is anything else."""
    try:
        tree = ast.parse(src.strip().replace("^", "**"), mode="eval")
        return _mod_eval(tree, m)
    except (_NoFastPath, SyntaxError, ValueError, MemoryError, RecursionError):
        return None


def _is_plain_value(v) -> bool:
    """A sympy object, an int, a Fraction, None (a function that found no result), or a list, tuple,
    set or dict of these. Anything else (a class, a bound method, a string) is never reported."""
    if v is None or isinstance(v, (sp.Basic, int, Fraction)):
        return True
    if isinstance(v, (list, tuple, set, frozenset)):
        return all(_is_plain_value(i) for i in v)
    if isinstance(v, dict):
        return all(_is_plain_value(k) and _is_plain_value(i) for k, i in v.items())
    return False


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
        alg.parsing.check_text(src)   # the fast path below must not see text the parser would reject
    except ValueError as e:
        return alg.bad_input("exact", str(e))
    fast = _fast_mod(src, mod) if mod is not None else None
    if fast is not None:
        v = sp.Integer(fast)
    else:
        try:
            v = alg.parse(src, namespace=alg.exact_namespace(), rational=True)
        except ValueError as e:
            return alg.bad_input("exact", str(e))
        syms, funcs = alg.unbound_names(v)
        if syms or funcs:
            return alg.bad_input(
                "exact", f"exact evaluates closed-form expressions, but {', '.join(syms + funcs)} is not "
                         f"defined (a misspelt function name is read as an unknown symbol); the names it "
                         f"knows: {_NAMES_HELP}")

    if not _is_plain_value(v):
        return alg.bad_input("exact", "the expression did not evaluate to a number, expression or "
                                      "list/dict of them")

    notes = alg.input_notes([src])
    if mod is not None and fast is None:
        notes.append(f"mod {mod} was applied after the whole value was evaluated, not by modular "
                     f"exponentiation (that is used only for plain integer +, -, * and ** expressions)")
    # A number that is not already an integer or rational is put in its simplest exact form
    # (sympy leaves (1 + sqrt(5))*(1 - sqrt(5)) as a product).
    if isinstance(v, sp.Expr) and v.is_number and not v.is_Rational and not v.has(sp.Float, sp.nan, sp.zoo, sp.oo):
        try:
            v = sp.simplify(v)
        except (ValueError, TypeError, ArithmeticError):
            pass
    try:
        if mod is not None and fast is None:
            v = _reduce(v, mod)
    except ValueError as e:
        return alg.bad_input("exact", str(e))

    flags = []
    if isinstance(v, sp.Basic) and v.has(sp.Float):
        flags.append(("inexact", "the result contains floating-point numbers, so it is not exact (a float came "
                                 "from a function such as evalf)"))
    if isinstance(v, sp.Basic) and v.has(sp.nan, sp.zoo):
        flags.append(("undefined_value", "the expression is undefined (zoo is complex infinity, from a "
                                         "division by zero; nan is an undefined form such as 0/0)"))
    complete = True
    if v is None:
        complete = False
        flags.append(("no_result", "the function returned None: it found no result (for crt or sqrt_mod, "
                                   "none exists)"))
    notes.extend(n for n in alg.result_notes(v) if "zoo or nan" not in n)

    text, latex = alg.render(v) if v is not None else (None, None)
    dec = _decimal(v)
    if text is None:
        result = {"value": None, "latex": None, "decimal": None}
    elif len(text) > MAX_VALUE_CHARS:
        digits = len(text.lstrip("-"))
        result = {"value": None, "latex": None, "decimal": dec, "digits": digits,
                  "head": text[:40], "tail": text[-40:]}
        flags.append(("value_too_long", f"the value has {digits} digits, too long to print; `head` and `tail` "
                                        f"are its first and last 40 characters. Use `mod` for a residue."))
    else:
        result = {"value": text, "latex": latex, "decimal": dec}
    if mod is not None:
        result["mod"] = mod

    if fast is not None:
        scope = f"evaluated exactly mod {mod} with unbounded integers, powers by modular exponentiation (no float)"
    else:
        scope = ("evaluated exactly by sympy with unbounded integers and rationals (no floating point)"
                 + (f", then reduced mod {mod}" if mod is not None else ""))
    ev = Evidence(button="exact", result=result, method="symbolic", scope=scope, complete=complete, notes=notes)
    for code, msg in flags:
        ev.flag(code, msg)
    if "proposed" in inp:
        alg.compare(ev, inp["proposed"], v, lambda s: alg.parse(s, namespace=alg.exact_namespace(), rational=True))
    return ev
