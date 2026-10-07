"""What the continuous buttons (identify, extremum, numeric) share: the expression namespace, the
checks that an expression is a plain function of the named variables, a tolerance-based `compare`,
and the budget stop. No button is registered here.
"""
from __future__ import annotations

from typing import Any, Iterable

import mpmath as mp
import sympy as sp
from sympy.core.function import AppliedUndef

from ..evidence import Evidence, make_compare
from . import _algebra as alg

# Sympy names beyond the shared whitelist that a numeric expression may need.
_EXTRA = ("EulerGamma", "Catalan", "GoldenRatio", "erf", "erfc", "erfi", "Ei", "Si", "Ci", "li", "besselj",
          "bessely", "besseli", "besselk", "airyai", "airybi", "polylog", "loggamma", "digamma", "polygamma",
          "lowergamma", "uppergamma", "elliptic_k", "elliptic_e", "hyper", "Heaviside", "sinc", "tanh", "sinh",
          "cosh", "acot", "asec", "acsc")


class Stopped(Exception):
    """Raised inside a callback when the time budget is used up."""


def namespace() -> dict:
    ns = alg.parsing._whitelist()
    for n in _EXTRA:
        if hasattr(sp, n):
            ns[n] = getattr(sp, n)
    ns["inf"] = sp.oo
    ns["abs"] = sp.Abs
    return ns


def parse(src: Any, names: Iterable[str] = ()) -> sp.Expr:
    """Parse an expression string against the whitelist, with `names` as bare symbols. Raises ValueError."""
    if not isinstance(src, str) or not src.strip():
        raise ValueError("the expression is empty")
    syms = {n: sp.Symbol(n) for n in names}
    e = alg.parse(src, symbols=syms, namespace=namespace(), rational=True)
    if not isinstance(e, sp.Basic):
        raise ValueError(f"{src!r} did not evaluate to an expression")
    return e


def check_function(e: sp.Basic, allowed: Iterable[str], what: str = "the expression") -> None:
    """Raise ValueError unless `e` is a plain function of the `allowed` names."""
    allowed = set(allowed)
    extra = sorted(s.name for s in e.free_symbols if s.name not in allowed)
    if extra:
        raise ValueError(f"{what} uses {', '.join(extra)}, which is not one of the variables "
                         f"({', '.join(sorted(allowed)) or 'none'}); write every other quantity as a number")
    funcs = sorted({type(a).__name__ for a in e.atoms(AppliedUndef)})
    if funcs:
        raise ValueError(f"{what} calls {', '.join(funcs)}, which is not a known function (a misspelt name is "
                         f"read as an unknown function)")
    for cls, nm in ((sp.Integral, "Integral"), (sp.Sum, "Sum"), (sp.Product, "Product"), (sp.Limit, "Limit"),
                    (sp.Derivative, "Derivative")):
        if e.has(cls):
            raise ValueError(f"{what} contains an unevaluated {nm}; evaluate it first or use the "
                             f"matching op")
    if e.has(sp.nan, sp.zoo):
        raise ValueError(f"{what} is undefined (it contains nan or complex infinity)")


def stop_check(ctx) -> None:
    if ctx.time_left() <= 0:
        raise Stopped


def budget_stop(ev: Evidence, what: str) -> Evidence:
    """Mark Evidence as cut short by the time budget."""
    ev.complete = False
    ev.flag("budget_stop", f"stopped at the time budget; {what}")
    return ev


def tolerance_compare(ev: Evidence, proposed: Any, computed: Any, tol: float, parse_fn) -> None:
    """Set `ev.compare` for a numeric result: the two numbers, their difference and the tolerance used.
    `equal` means equal within `tol` (the result's own precision), not exactly equal."""
    try:
        p = parse_fn(proposed) if isinstance(proposed, str) else proposed
        if isinstance(p, sp.Basic):
            pv = mp.mpmathify(str(sp.N(p, 40)))
        else:
            pv = mp.mpmathify(p)
    except Exception:  # noqa: BLE001
        ev.compare = make_compare(proposed, str(computed))
        ev.compare["equal"] = False
        ev.notes.append(f"proposed {proposed!r} could not be read as a number, so it was compared as text")
        return
    cv = mp.mpmathify(computed)
    diff = abs(pv - cv)
    cmp = make_compare(mp.nstr(pv, 20), mp.nstr(cv, 20))
    cmp["equal"] = bool(diff <= tol)
    cmp["difference"] = mp.nstr(diff, 5)
    cmp["tolerance"] = mp.nstr(mp.mpf(tol), 5)
    cmp["note"] = "equal means within the stated tolerance (the result's own precision), not exactly equal"
    ev.compare = cmp
