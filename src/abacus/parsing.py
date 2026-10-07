"""Safe-ish expression parsing and code compilation."""
from __future__ import annotations

import collections
import functools
import io
import itertools
import math
import tokenize
from fractions import Fraction
from typing import Callable, Iterable, Literal, Sequence

import numpy as np
import sympy as sp
from sympy.parsing.sympy_parser import parse_expr as _sympy_parse
from sympy.parsing.sympy_parser import standard_transformations

_NAMES = """
sqrt cbrt root factorint factorrat primefactors divisors divisor_count divisor_sigma binomial
factorial factorial2 gcd lcm Rational Integer Float pi E I oo zoo nan sin cos tan cot sec csc
asin acos atan atan2 sinh cosh tanh asinh acosh atanh exp log ln floor ceiling frac Mod isprime
prime primepi nextprime prevprime totient mobius reduced_totient Sum Product Integral Derivative
Limit diff integrate limit summation product simplify expand factor cancel apart together
Abs sign Min Max re im conjugate arg fibonacci lucas catalan bell harmonic gamma beta zeta
Matrix Eq Ne Lt Le Gt Ge And Or Not Piecewise Symbol Poly Function Lambda
legendre_symbol jacobi_symbol n_order primitive_root igcd ilcm
""".split()

_BAD_SUBSTRINGS = ("__", "import", "lambda", "exec", "eval", "open")

# No expression may contain a string literal. Sympy's own parser (sympify) evaluates a string argument
# with full builtins, so a string built at runtime (S("_"*2+"imp"+...)) would get past the text scan
# above. S, sympify, parse_expr and symbols (which evaluate or split a string) are not in _NAMES either.
# Symbol and Function stay: sympy's own auto_symbol transform emits calls to them for every bare name.
# They only store the string, and with no string literal possible they can only be handed a name.
QUOTE_CHARS = ("'", '"')


def _has_attribute_access(s: str) -> bool:
    """True if `s` has a `.` that is not part of a numeric literal (0.5, .5, 1., 1.5e3).

    Python's own tokenizer reads the numbers first, so only an attribute dot is left as an operator.
    Tokens read before a tokenizer error still count: text that fails to tokenize fails to parse too.
    """
    try:
        for tok in tokenize.generate_tokens(io.StringIO(s).readline):
            if tok.type == tokenize.OP and tok.string in (".", "..."):
                return True
    except (tokenize.TokenError, SyntaxError, IndentationError):
        pass
    return False


def check_text(s: str) -> None:
    """Raise ValueError for text that must never reach the evaluator."""
    low = s.lower()
    for bad in _BAD_SUBSTRINGS:
        if bad in low:
            raise ValueError(f"expression rejected: contains {bad!r}")
    if any(q in s for q in QUOTE_CHARS):
        raise ValueError("expression rejected: contains a quote character; string literals are not "
                         "allowed (write names bare: x, not 'x')")
    if _has_attribute_access(s):
        raise ValueError("expression rejected: attribute access is not allowed in expressions (a '.' is "
                         "only read inside a number such as 0.5; write x, not x.name)")


def _whitelist() -> dict:
    ns = {n: getattr(sp, n) for n in _NAMES if hasattr(sp, n)}
    ns["__builtins__"] = {}
    return ns


def parse_expr(s: str, symbols: Iterable[str] = ()) -> sp.Expr:
    check_text(s)
    local = {n: sp.Symbol(n) for n in symbols}
    try:
        return _sympy_parse(s, local_dict=local, global_dict=_whitelist(),
                            transformations=standard_transformations)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"could not parse {s!r}: {e}") from e


def _std_ns() -> dict:
    ns = {"math": math, "itertools": itertools, "functools": functools,
          "collections": collections, "Fraction": Fraction, "sp": sp, "np": np}
    try:
        import abacus.kit as ak
        ns["ak"] = ak
    except ModuleNotFoundError as e:
        if e.name != "abacus.kit":
            raise
    return ns


def compile_code(src: str, *, kind: Literal["expr", "func"], name: str | None = None,
                 args: Sequence[str] = ()) -> Callable:
    ns = _std_ns()
    if kind == "expr":
        code = compile(src, "<expr>", "eval")
        argnames = tuple(args)

        def f(*a):
            if len(a) != len(argnames):
                raise TypeError(f"expected {len(argnames)} arguments, got {len(a)}")
            return eval(code, ns, dict(zip(argnames, a)))
        return f
    if kind == "func":
        if not name:
            raise ValueError("kind='func' requires name")
        exec(compile(src, "<func>", "exec"), ns)
        fn = ns.get(name)
        if not callable(fn):
            raise ValueError(f"source does not define a function {name!r}")
        return fn
    raise ValueError(f"unknown kind {kind!r}")
