"""What the algebra buttons (exact, cas, identity) share: parsing against the whitelist, the domain
grammar, and the small helpers that report bad input and render values.

No button is registered here.
"""
from __future__ import annotations

import math
import operator
import re
import sys
from contextlib import contextmanager
from typing import Any, Callable, Iterable

import sympy as sp
from sympy.core.function import AppliedUndef
from sympy.ntheory.modular import crt as _crt
from sympy.parsing.sympy_parser import convert_xor, rationalize, standard_transformations
from sympy.parsing.sympy_parser import parse_expr as _sympy_parse

from .. import parsing
from ..evidence import Evidence, make_compare

IDENT = r"^[A-Za-z_][A-Za-z0-9_]*$"

# How far past a finite end a one-sided or unbounded domain is sampled.
INT_SPAN = 30
REAL_SPAN = 10.0
COMPLEX_SPAN = 5.0

_FLOAT_PARSE = standard_transformations + (convert_xor,)
_RATIONAL_PARSE = standard_transformations + (rationalize, convert_xor)


# ----------------------------------------------------------------------------- parsing


def _multinomial(*ks) -> sp.Integer:
    """(k1 + k2 + ...)! / (k1! k2! ...), as a product of binomials so it stays exact and quick."""
    ks = [operator.index(k) for k in ks]
    if not ks or any(k < 0 for k in ks):
        raise ValueError("multinomial needs one or more non-negative integers")
    out, running = 1, 0
    for k in ks:
        running += k
        out *= math.comb(running, k)
    return sp.Integer(out)


def _powmod(base, exp, mod) -> sp.Integer:
    """base**exp mod m by repeated squaring (a negative exp needs base invertible mod m)."""
    return sp.Integer(pow(operator.index(base), operator.index(exp), operator.index(mod)))


def exact_namespace() -> dict:
    """The whitelist of `parsing` plus the number theory names of the `exact` button (spec 04 s1)."""
    ns = parsing._whitelist()
    ns.update({
        "multinomial": _multinomial,
        "powmod": _powmod,
        "partition": getattr(sp, "partition", None) or sp.npartitions,
        "legendre": sp.legendre_symbol,
        "jacobi": sp.jacobi_symbol,
        "discrete_log": sp.discrete_log,
        "sqrt_mod": sp.sqrt_mod,
        "crt": _crt,
        "n_order": sp.n_order,
        "primitive_root": sp.primitive_root,
    })
    return ns


def parse(s: Any, symbols: dict | None = None, namespace: dict | None = None, rational: bool = True):
    """Parse one expression string against a whitelisted namespace. Raises ValueError.

    `^` is read as a power, not XOR (sympy's own parser would give 2^100 == 102). With `rational`,
    a decimal literal is an exact rational (0.1 is 1/10), so nothing inexact enters unannounced.
    """
    if not isinstance(s, str) or not s.strip():
        raise ValueError("the expression is empty")
    parsing.check_text(s)
    try:
        return _sympy_parse(s.strip(), local_dict=dict(symbols or {}),
                            global_dict=dict(namespace) if namespace is not None else parsing._whitelist(),
                            transformations=_RATIONAL_PARSE if rational else _FLOAT_PARSE)
    except Exception as e:  # noqa: BLE001  (a bad string raises SyntaxError, TypeError, NameError ...; a call
        # that parses but cannot be evaluated, such as n_order(2, 4), raises its own ValueError)
        kind = "" if isinstance(e, ValueError) else f"{type(e).__name__}: "
        raise ValueError(f"could not parse or evaluate {s!r}: {kind}{e}") from e


_DECIMAL = re.compile(r"\d*\.\d+|\d+\.(?!\.)|\d[eE][+-]?\d")


def input_notes(strings: Iterable[str], rational: bool = True) -> list[str]:
    """Caveats about how the input text was read (a `^`, a decimal literal)."""
    notes = []
    strings = [s for s in strings if isinstance(s, str)]
    if any("^" in s for s in strings):
        notes.append("`^` was read as exponentiation (**), not as XOR")
    if rational and any(_DECIMAL.search(s) for s in strings):
        notes.append("decimal literals were read as exact rationals (0.1 is 1/10), not as floating point")
    return notes


def walk(obj: Any):
    """Every sympy object inside a result that may be a list, tuple, set or dict of them."""
    if isinstance(obj, sp.Basic):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(k)
            yield from walk(v)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for i in obj:
            yield from walk(i)


def unbound_names(obj: Any) -> tuple[list[str], list[str]]:
    """(free symbols, undefined function names) found anywhere in a result."""
    syms, funcs = set(), set()
    for b in walk(obj):
        syms |= {s.name for s in b.free_symbols}
        funcs |= {type(a).__name__ for a in b.atoms(AppliedUndef)}
    return sorted(syms), sorted(funcs)


def result_notes(res) -> list[str]:
    """Say so when sympy's answer is unevaluated, conditional or only bounds (kit/03 s2, kit/04 s2)."""
    found = list(walk(res))
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


def undefined_function_note(*exprs: Any) -> str | None:
    _, funcs = unbound_names(list(exprs))
    if not funcs:
        return None
    return (f"undefined function(s) {', '.join(funcs)}: names outside the whitelist are treated as abstract "
            f"functions, so a misspelt name is not an error here")


# ----------------------------------------------------------------------------- evidence helpers


def bad_input(button: str, message: str, scope: str | None = None) -> Evidence:
    """The Evidence for input the button could not use (unparseable, ambiguous, impossible). Never raised."""
    ev = Evidence(button=button, result=None, method="symbolic",
                  scope=scope or "input rejected; nothing was computed", complete=False)
    ev.flag("bad_input", message)
    return ev


@contextmanager
def big_ints():
    """Python refuses to print an int of more than 4300 digits unless the limit is lifted; an exact
    button has to be able to print a 5000-digit factorial."""
    old = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(0)
    try:
        yield
    finally:
        sys.set_int_max_str_digits(old)


def render(obj: Any) -> tuple[str, str]:
    """(plain string, LaTeX) of a sympy object or a plain Python value."""
    with big_ints():
        return str(obj), sp.latex(obj)


def _stringify_big(x: Any) -> Any:
    if isinstance(x, int) and not isinstance(x, bool) and x.bit_length() > 10_000:
        with big_ints():
            return str(x)
    if isinstance(x, list):
        return [_stringify_big(i) for i in x]
    if isinstance(x, dict):
        return {k: _stringify_big(v) for k, v in x.items()}
    return x


def parse_proposed(p: Any, parse_fn: Callable[[str], Any], unparsed: list[str]) -> Any:
    """A `proposed` value from JSON: its strings are parsed as expressions (a string that will not
    parse is left as text and recorded in `unparsed`)."""
    if isinstance(p, str):
        try:
            return parse_fn(p)
        except ValueError:
            unparsed.append(p)
            return p
    if isinstance(p, list):
        return [parse_proposed(i, parse_fn, unparsed) for i in p]
    if isinstance(p, dict):
        return {parse_proposed(k, parse_fn, unparsed): parse_proposed(v, parse_fn, unparsed) for k, v in p.items()}
    return p


def compare(ev: Evidence, proposed: Any, computed: Any, parse_fn: Callable[[str], Any],
            reshape: Callable[[Any], Any] | None = None) -> None:
    """Set `ev.compare` from a `proposed` value: a plain comparison of two values, nothing more.

    `reshape` puts both sides in the same shape first (e.g. a solution list as a set)."""
    unparsed: list[str] = []
    p = parse_proposed(proposed, parse_fn, unparsed)
    if unparsed:
        ev.notes.append(f"proposed {unparsed[0]!r} could not be parsed as an expression, so it was compared "
                        f"as text with the computed value's string")
        cmp = make_compare(proposed, render(computed)[0])
    else:
        if reshape is not None:
            p, computed = reshape(p), reshape(computed)
        cmp = make_compare(p, computed)
    ev.compare = _stringify_big(cmp)


# ----------------------------------------------------------------------------- domains


_KINDS = {"integer": "integer", "int": "integer", "real": "real", "complex": "complex"}
# modifier -> (side, inclusive); every one is a bound at 0
_SIGNS = {"positive": ("lo", False), "nonnegative": ("lo", True),
          "negative": ("hi", False), "nonpositive": ("hi", True)}
_IN = re.compile(r"^in\s*([\(\[])(.*)([\)\]])\s*$", re.I | re.S)
_CMP = re.compile(r"^(>=|<=|>|<)\s*(.+)$", re.S)
_HELP = "a domain looks like 'integer >= 1', 'real in (0, pi)', 'positive integer', 'real' or 'complex'"


def _split_top(s: str, sep: str = ",") -> list[str]:
    parts, depth, cur = [], 0, []
    for ch in s:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts]


def _bound(text: str):
    """(exact value, float) of a bound; +-oo come back as (+-sp.oo, +-inf)."""
    e = parse(text, rational=True)
    if not isinstance(e, sp.Basic) or e.free_symbols:
        raise ValueError(f"the bound {text!r} must be a number")
    if e in (sp.oo, -sp.oo):
        return e, math.inf if e == sp.oo else -math.inf
    if not (e.is_number and e.is_real):
        raise ValueError(f"the bound {text!r} must be a real number")
    return e, float(sp.N(e, 30))


class Domain:
    """Where a variable lives: integer, real or complex, optionally cut by bounds.

    The same grammar serves `identity` (where it also says where to sample) and `cas` assumptions
    (where it becomes sympy symbol assumptions).
    """

    def __init__(self, kind: str, lo, lo_incl: bool, hi, hi_incl: bool):
        self.kind = kind
        self.lo, self.lo_incl, self.hi, self.hi_incl = lo, lo_incl, hi, hi_incl
        self.ilo = self.ihi = None
        if kind == "integer":
            if lo is not None:
                self.ilo = int(sp.ceiling(lo)) if lo_incl else int(sp.floor(lo)) + 1
            if hi is not None:
                self.ihi = int(sp.floor(hi)) if hi_incl else int(sp.ceiling(hi)) - 1
            if self.ilo is not None and self.ihi is not None and self.ilo > self.ihi:
                raise ValueError(f"the domain {self.text} has no integers in it")
        elif kind == "real" and lo is not None and hi is not None:
            fl, fh = float(sp.N(lo, 30)), float(sp.N(hi, 30))
            if fl > fh or (fl == fh and not (lo_incl and hi_incl)):
                raise ValueError(f"the domain {self.text} is empty")

    # -- description

    @property
    def text(self) -> str:
        if self.kind == "complex" or (self.lo is None and self.hi is None):
            return self.kind
        lo = f"{'[' if self.lo_incl else '('}{self.lo}" if self.lo is not None else "(-oo"
        hi = f"{self.hi}{']' if self.hi_incl else ')'}" if self.hi is not None else "oo)"
        return f"{self.kind} in {lo}, {hi}"

    def assumptions(self) -> dict:
        """The sympy symbol assumptions this domain justifies (a superset domain, so anything sympy
        proves under them holds on this domain)."""
        a: dict[str, bool] = {}
        if self.kind == "integer":
            a["integer"] = True
        elif self.kind == "real":
            a["real"] = True
        if self.lo is not None:
            if self.lo.is_positive or (self.lo.is_zero and not self.lo_incl):
                a["positive"] = True
            elif self.lo.is_zero:
                a["nonnegative"] = True
        if self.hi is not None:
            if self.hi.is_negative or (self.hi.is_zero and not self.hi_incl):
                a["negative"] = True
            elif self.hi.is_zero:
                a["nonpositive"] = True
        return a

    # -- sampling

    @property
    def window(self) -> tuple:
        """The interval that is actually sampled: the domain, cut to a bounded piece if it is unbounded."""
        if self.kind == "integer":
            lo, hi = self.ilo, self.ihi
            if lo is None and hi is None:
                return (-INT_SPAN, INT_SPAN)
            if lo is None:
                return (hi - INT_SPAN, hi)
            if hi is None:
                return (lo, lo + INT_SPAN)
            return (lo, hi)
        if self.kind == "complex":
            return (-COMPLEX_SPAN, COMPLEX_SPAN)
        lo = None if self.lo is None else float(sp.N(self.lo, 30))
        hi = None if self.hi is None else float(sp.N(self.hi, 30))
        if lo is None and hi is None:
            return (-REAL_SPAN, REAL_SPAN)
        if lo is None:
            return (hi - REAL_SPAN, hi)
        if hi is None:
            return (lo, lo + REAL_SPAN)
        return (lo, hi)

    @property
    def count(self) -> int | None:
        """How many points the sampling window holds (integers only)."""
        if self.kind != "integer":
            return None
        lo, hi = self.window
        return hi - lo + 1

    def is_infinite(self) -> bool:
        """Whether the domain itself (not just its window) holds infinitely many points."""
        if self.kind == "integer":
            return self.ilo is None or self.ihi is None
        lo, hi = self.window
        return lo < hi or self.kind == "complex"

    def sample(self, rng):
        """(exact sympy value, JSON-able Python value) of one random point of the window."""
        lo, hi = self.window
        if self.kind == "integer":
            v = rng.randint(lo, hi)
            return sp.Integer(v), v
        if self.kind == "complex":
            re_, im_ = (rng.uniform(lo, hi) for _ in range(2))
            z = sp.Rational(re_) + sp.I * sp.Rational(im_)
            return z, f"{re_!r}{'+' if im_ >= 0 else '-'}{abs(im_)!r}*I"
        for _ in range(100):
            v = lo + (hi - lo) * rng.random() if hi > lo else lo
            above_lo = v > lo or (v == lo and (self.lo is None or self.lo_incl))
            below_hi = v < hi or (v == hi and (self.hi is None or self.hi_incl))
            if above_lo and below_hi:
                return sp.Rational(v), v
        return sp.Rational((lo + hi) / 2), (lo + hi) / 2  # a very thin interval: its middle


def parse_domain(spec: str) -> Domain:
    """Parse 'integer >= 1', 'real in (0, pi)', 'positive integer', ... Raises ValueError with the grammar."""
    try:
        return _parse_domain(spec)
    except ValueError as e:
        msg = str(e)
        raise ValueError(msg if "domain looks like" in msg else f"{msg} ({_HELP})") from None


def _parse_domain(spec: Any) -> Domain:
    if not isinstance(spec, str) or not spec.strip():
        raise ValueError("a domain is empty")
    text = spec.strip()
    m = re.search(r"\bin\s*[\(\[]|[<>]", text, re.I)
    head, rest = (text[:m.start()], text[m.start():]) if m else (text, "")
    kind = None
    lows: list[tuple] = []   # (exact, float, inclusive)
    highs: list[tuple] = []
    for w in head.replace(",", " ").split():
        lw = w.lower()
        if lw in _KINDS:
            if kind is not None:
                raise ValueError(f"more than one kind of number in {spec!r}")
            kind = _KINDS[lw]
        elif lw in _SIGNS:
            side, incl = _SIGNS[lw]
            (lows if side == "lo" else highs).append((sp.Integer(0), 0.0, incl))
        elif lw != "and":
            raise ValueError(f"unknown word {w!r} in the domain {spec!r}")
    rest = rest.strip()
    if rest:
        mi = _IN.match(rest)
        if mi:
            parts = _split_top(mi.group(2))
            if len(parts) != 2:
                raise ValueError(f"an interval needs two ends in {spec!r}")
            (le, lf), (he, hf) = _bound(parts[0]), _bound(parts[1])
            if lf != -math.inf:
                lows.append((le, lf, mi.group(1) == "["))
            if hf != math.inf:
                highs.append((he, hf, mi.group(3) == "]"))
            if lf == math.inf or hf == -math.inf:
                raise ValueError(f"the interval in {spec!r} is empty")
        elif rest.startswith("in"):
            raise ValueError(f"an interval needs brackets, as in 'real in (0, 1]', in {spec!r}")
        else:
            for piece in _split_top(re.sub(r"\s+and\s+", ",", rest)):
                mc = _CMP.match(piece)
                if not mc:
                    raise ValueError(f"cannot read {piece!r} in {spec!r}")
                op, (e, f) = mc.group(1), _bound(mc.group(2))
                if op in (">", ">="):
                    if f == math.inf:
                        raise ValueError(f"nothing is {op} oo in {spec!r}")
                    if f != -math.inf:
                        lows.append((e, f, op == ">="))
                else:
                    if f == -math.inf:
                        raise ValueError(f"nothing is {op} -oo in {spec!r}")
                    if f != math.inf:
                        highs.append((e, f, op == "<="))
    if kind is None:
        kind = "real"
    if kind == "complex" and (lows or highs):
        raise ValueError(f"a complex number has no order, so it cannot be bounded: {spec!r}")
    lo = max(lows, key=lambda b: (b[1], not b[2]), default=None)
    hi = min(highs, key=lambda b: (b[1], b[2]), default=None)
    return Domain(kind, lo[0] if lo else None, lo[2] if lo else False, hi[0] if hi else None, hi[2] if hi else False)
