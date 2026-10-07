"""sequence: guess a closed form or recurrence from terms (kit/04 s5).

Every guess is fitted on the first terms and then asked to predict the held-out last ones from the fit alone.
A guess is a guess: nothing here proves a formula.
"""
from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Callable

import sympy as sp

from .. import registry
from ..config import get_config
from ..evidence import Evidence
from . import _discrete as D
from ._discrete import BadInput

NAME = "sequence"
METHOD = "fit"
MAX_TERMS = 500
MAX_DEGREE = 30          # polynomials above this degree are not offered
MAX_ORDER = 40           # recurrences (and generating functions) above this order are not offered
SHIFT_MAX = 8            # how far into a known sequence a list may start
MIN_FIT = 2              # the holdout is lowered so that at least this many terms are fitted
MIN_FIT_PREFERRED = 3    # from 4 terms on, at least this many are fitted
MAX_RATIO_DEGREE = 3     # hypergeometric: a(n+1)/a(n) = P(n)/Q(n) with both degrees at most this

DESCRIPTION = (
    "Find a closed form or recurrence from terms. Give terms (a list of integers or 'p/q' strings, the first at index "
    "offset, default 0) or code (an expression in n, or a def f(n)) with n_range [a, b]. The last holdout terms "
    "(default 3) are kept back: each guess is fitted on the rest and then must predict the held-out terms from the "
    "fit alone. Result: candidates, each with a form (known sequence from a built-in list of Catalan, Fibonacci, "
    "Bell, Motzkin, derangements, powers of 2, factorials and triangular numbers; polynomial by finite differences; "
    "linear recurrence by Berlekamp-Massey over the rationals; rational generating function; hypergeometric), its "
    "expression, fitted_on (terms used) and held_out (how many held-out terms it predicted, out of held_out_tested). "
    "Guesses that miss a held-out term are dropped and counted in refuted. With no terms held back a candidate "
    "carries held_out 0 and a note that it is unsupported. OEIS is consulted only when ABACUS_NETWORK is on. "
    "These are fits, not proofs."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "terms": {"type": "array"},
        "offset": {"type": "integer"},
        "code": {"type": "string"},
        "n_range": {"type": "array"},
        "holdout": {"type": "integer"},
    },
}


# --------------------------------------------------------------------------------------------- terms

def _as_fraction(v: Any, where: str) -> Fraction:
    if D.is_int(v):
        return Fraction(v)
    if isinstance(v, float):
        if v.is_integer():
            return Fraction(int(v))
        raise BadInput(f"{where}: {v!r} is a float; give exact rationals as 'p/q' strings")
    if isinstance(v, str):
        try:
            return Fraction(v.strip())
        except (ValueError, ZeroDivisionError):
            raise BadInput(f"{where}: {v!r} is not an integer or a 'p/q' rational") from None
    if isinstance(v, Fraction):
        return v
    if isinstance(v, sp.Rational):
        return Fraction(int(v.p), int(v.q))
    raise BadInput(f"{where}: expected an integer or a 'p/q' string, got {D.short(v)}")


def _frac_str(c: Fraction) -> str:
    return str(c.numerator) if c.denominator == 1 else f"{c.numerator}/{c.denominator}"


def _terms_from_code(inp: dict, ctx) -> tuple[list[Fraction], int, bool]:
    rng = inp.get("n_range")
    if not (isinstance(rng, list) and len(rng) == 2 and all(D.is_int(v) for v in rng)):
        raise BadInput("code needs n_range [a, b] with integers")
    a, b = rng
    if b < a or b - a + 1 > MAX_TERMS:
        raise BadInput(f"n_range must have a <= b and at most {MAX_TERMS} values")
    if inp.get("offset") not in (None, a):
        raise BadInput(f"offset {inp['offset']} conflicts with n_range starting at {a}; leave offset out with code")
    f = D.UserFn(inp["code"], "f", ["n"], whole_object=True)
    out: list[Fraction] = []
    for n in range(a, b + 1):
        if ctx.time_left() <= 0.05:
            return out, a, False
        try:
            v = f.call(n)
        except Exception as e:  # noqa: BLE001
            raise BadInput(f"code raised {type(e).__name__}: {e} at n={n}") from None
        out.append(_as_fraction(v, f"code at n={n}"))
    return out, a, True


# --------------------------------------------------------------------------------------------- exact helpers

def berlekamp_massey(s: list[Fraction], max_order: int | None = None) -> tuple[list[Fraction], int] | None:
    """Shortest linear recurrence of s over the rationals: (C, L) with C = [1, c1, ..., cL] and
    sum_{i=0..L} C[i] * s[n - i] = 0 for every n >= L. None as soon as L passes ``max_order``: the length only
    grows, and exact rationals blow up on data with no recurrence in it."""
    C, B = [Fraction(1)], [Fraction(1)]
    L, m, b = 0, 1, Fraction(1)
    for n in range(len(s)):
        d = s[n] + sum((C[i] * s[n - i] for i in range(1, L + 1)), Fraction(0))
        if d == 0:
            m += 1
            continue
        coef = d / b
        T = C[:]
        need = len(B) + m
        if len(C) < need:
            C = C + [Fraction(0)] * (need - len(C))
        for i, bi in enumerate(B):
            C[i + m] -= coef * bi
        if 2 * L <= n:
            L, B, b, m = n + 1 - L, T, d, 1
        else:
            m += 1
        if max_order is not None and L > max_order:
            return None
        if len(C) < L + 1:
            C = C + [Fraction(0)] * (L + 1 - len(C))
    return (C + [Fraction(0)] * (L + 1 - len(C)))[: L + 1], L


def _differences(fit: list[Fraction], max_degree: int) -> list | None:
    """First entry of each row of the difference table (a0, d1a0, d2a0, ...) up to the first all-zero row;
    None if that takes more than ``max_degree`` + 1 rows."""
    row = [int(t) for t in fit] if all(t.denominator == 1 for t in fit) else list(fit)
    firsts = []
    while row and any(row):
        if len(firsts) > max_degree:
            return None
        firsts.append(row[0])
        row = [y - x for x, y in zip(row, row[1:])]
    return firsts


def _nullspace(rows: list[list[Fraction]], cols: int) -> list[list[Fraction]]:
    """Basis of {v : rows . v = 0}, exactly."""
    m = [r[:] for r in rows]
    pivots, r = [], 0
    for c in range(cols):
        p = next((i for i in range(r, len(m)) if m[i][c] != 0), None)
        if p is None:
            continue
        m[r], m[p] = m[p], m[r]
        inv = 1 / m[r][c]
        m[r] = [v * inv for v in m[r]]
        for i in range(len(m)):
            if i != r and m[i][c] != 0:
                f = m[i][c]
                m[i] = [a - f * b for a, b in zip(m[i], m[r])]
        pivots.append(c)
        r += 1
        if r == len(m):
            break
    free = [c for c in range(cols) if c not in pivots]
    basis = []
    for fc in free:
        v = [Fraction(0)] * cols
        v[fc] = Fraction(1)
        for i, pc in enumerate(pivots):
            v[pc] = -m[i][fc]
        basis.append(v)
    return basis


# --------------------------------------------------------------------------------------------- known sequences

def _catalan(k):
    return [math.comb(2 * n, n) // (n + 1) for n in range(k)]


def _fibonacci(k):
    a, b, out = 0, 1, []
    for _ in range(k):
        out.append(a)
        a, b = b, a + b
    return out


def _bell(k):
    out, row = [], [1]
    for _ in range(k):
        out.append(row[0])
        nxt = [row[-1]]
        for v in row:
            nxt.append(nxt[-1] + v)
        row = nxt
    return out


def _motzkin(k):
    m = [1, 1]
    for n in range(2, k):
        m.append(((2 * n + 1) * m[n - 1] + (3 * n - 3) * m[n - 2]) // (n + 2))
    return m[:k]


def _derangements(k):
    d = [1, 0]
    for n in range(2, k):
        d.append((n - 1) * (d[n - 1] + d[n - 2]))
    return d[:k]


KNOWN: list[tuple[str, str, Callable[[int], list[int]]]] = [
    ("Catalan numbers", "catalan({a})", _catalan),
    ("Fibonacci numbers", "fibonacci({a})", _fibonacci),
    ("Bell numbers", "bell({a})", _bell),
    ("Motzkin numbers", "motzkin({a})", _motzkin),
    ("derangements (subfactorials)", "subfactorial({a})", _derangements),
    ("powers of 2", "2**({a})", lambda k: [2 ** n for n in range(k)]),
    ("factorials", "factorial({a})", lambda k: [math.factorial(n) for n in range(k)]),
    ("triangular numbers", "({a})*({a} + 1)/2", lambda k: [n * (n + 1) // 2 for n in range(k)]),
]


# --------------------------------------------------------------------------------------------- models

@dataclass
class Model:
    form: str
    expression: Callable[[], str]                  # built only for a model that is kept: sympy can be slow
    params: int                                    # numbers the fit had to pin down
    predict: Callable[[int], list]                 # the next k terms after the fit, from the fit alone
    extra: dict = field(default_factory=dict)


def _arg(shift: int) -> str:
    return "n" if shift == 0 else (f"n + {shift}" if shift > 0 else f"n - {-shift}")


def _known_models(fit: list[Fraction], n_total: int, offset: int) -> list[Model]:
    F = len(fit)
    if F < 3 or any(t.denominator != 1 for t in fit):
        return []
    ints = [int(t) for t in fit]
    out = []
    for name, pattern, gen in KNOWN:
        seq = gen(n_total + SHIFT_MAX + 1)
        for s in range(SHIFT_MAX + 1):
            if seq[s:s + F] == ints:
                shift = s - offset
                arg = _arg(shift)

                def predict(k, seq=seq, s=s):
                    return [Fraction(seq[s + F + j]) for j in range(k)]

                out.append(Model("known sequence", lambda pattern=pattern, arg=arg: pattern.format(a=arg), 0, predict,
                                 {"name": name}))
    return out


def _polynomial_model(fit: list[Fraction], offset: int, capped: list[str] | None = None) -> Model | None:
    firsts = _differences(fit, MAX_DEGREE)
    if firsts is None:
        if capped is not None:
            capped.append(f"polynomial_degree<={MAX_DEGREE}")
        return None
    deg = max(len(firsts) - 1, 0)
    def expression():
        if not firsts:
            return "0"
        n = sp.Symbol("n")
        pts = [(offset + i, sp.Rational(fit[i].numerator, fit[i].denominator)) for i in range(deg + 1)]
        return str(sp.expand(sp.interpolate(pts, n)) if deg > 0 else pts[0][1])

    def predict(k):
        out = []
        for j in range(k):
            i = len(fit) + j
            out.append(sum((c * math.comb(i, d) for d, c in enumerate(firsts)), Fraction(0)))
        return out

    return Model("polynomial", expression, deg + 1, predict, {"degree": deg})


def _recurrence_models(fit: list[Fraction], offset: int, capped: list[str] | None = None) -> list[Model]:
    bm = berlekamp_massey(fit, MAX_ORDER)
    if bm is None and capped is not None:
        capped.append(f"recurrence<={MAX_ORDER}")
    if bm is None or bm[1] == 0:
        return []
    C, L = bm

    def predict(k):
        seq = list(fit)
        for _ in range(k):
            seq.append(-sum((C[i] * seq[-i] for i in range(1, L + 1)), Fraction(0)))
        return seq[len(fit):]

    def recurrence():
        terms = []
        for i in range(1, L + 1):
            r = -C[i]
            if r == 0:
                continue
            mag = abs(r)
            body = f"a(n-{i})" if mag == 1 else f"{_frac_str(mag)}*a(n-{i})"
            terms.append(("- " if r < 0 else "+ ") + body)
        rhs = " ".join(terms)
        rhs = rhs[2:] if rhs.startswith("+ ") else ("-" + rhs[2:] if rhs.startswith("- ") else rhs)
        return f"a(n) = {rhs or '0'}"

    def generating_function():
        # P(x) / Q(x): Q is the connection polynomial, P is (sum a_i x^i) * Q cut below x^L.
        x = sp.Symbol("x")
        Q = sum((sp.Rational(c.numerator, c.denominator) * x ** i for i, c in enumerate(C)), sp.Integer(0))
        A = sum((sp.Rational(t.numerator, t.denominator) * x ** i for i, t in enumerate(fit[:L])), sp.Integer(0))
        AQ = sp.expand(A * Q)
        P = sum((AQ.coeff(x, i) * x ** i for i in range(L)), sp.Integer(0))
        return str(sp.cancel(P / Q))

    initial = [_frac_str(t) for t in fit[:L]]
    at = f"a({offset})" if L == 1 else f"a({offset}..{offset + L - 1})"
    rec = Model("linear recurrence", recurrence, 2 * L, predict,
                {"order": L, "initial": initial, "reading": f"holds for n >= {offset + L}; {at} = {', '.join(initial)}"})
    gf = Model("rational generating function", generating_function, 2 * L, predict,
               {"order": L, "reading": f"the coefficient of x^i is the term at n = {offset} + i"})
    return [rec, gf]


def _hypergeometric_model(fit: list[Fraction], offset: int) -> Model | None:
    F = len(fit)
    if F < 4 or any(t == 0 for t in fit):
        return None
    pairs = sorted(((dp, dq) for dp in range(MAX_RATIO_DEGREE + 1) for dq in range(MAX_RATIO_DEGREE + 1)),
                   key=lambda p: (p[0] + p[1], p[0]))
    for dp, dq in pairs:
        cols = dp + dq + 2
        if F - 1 < cols:
            continue  # fewer equations than unknowns: anything fits
        rows = []
        for i in range(F - 1):
            n = Fraction(offset + i)
            rows.append([-fit[i] * n ** k for k in range(dp + 1)] + [fit[i + 1] * n ** k for k in range(dq + 1)])
        # A few rows decide most pairs; only a pair that survives is checked against all of them.
        basis = _nullspace(rows[:cols + 2], cols)
        if not basis:
            continue
        if len(basis) == 1 and all(sum((a * b for a, b in zip(r, basis[0])), Fraction(0)) == 0 for r in rows):
            pass
        else:
            basis = _nullspace(rows, cols)
            if not basis:
                continue
            if len(basis) > 1:
                return None
        v = basis[0]
        den = math.lcm(*(c.denominator for c in v))
        ints = [int(c * den) for c in v]
        g = math.gcd(*ints) or 1
        ints = [c // g for c in ints]
        p, q = ints[:dp + 1], ints[dp + 1:]
        if all(c == 0 for c in q):
            return None
        def ratio(p=p, q=q):
            n = sp.Symbol("n")
            P = sum(c * n ** k for k, c in enumerate(p))
            Q = sum(c * n ** k for k, c in enumerate(q))
            return str(sp.factor(sp.cancel(P / Q)))

        def predict(k, p=p, q=q):
            out, cur = [], fit[-1]
            for j in range(k):
                nn = offset + len(fit) - 1 + j
                qv = sum(c * nn ** e for e, c in enumerate(q))
                if qv == 0:
                    out.extend([None] * (k - j))
                    break
                cur = cur * Fraction(sum(c * nn ** e for e, c in enumerate(p)), qv)
                out.append(cur)
            return out

        a0 = _frac_str(fit[0])
        return Model("hypergeometric", lambda: f"a(n+1)/a(n) = {ratio()}", cols, predict,
                     {"reading": f"a({offset}) = {a0}", "_ratio": ratio})
    return None


# --------------------------------------------------------------------------------------------- OEIS

def _oeis(terms: list[Fraction], ctx) -> tuple[list[dict] | None, str | None]:
    """Search oeis.org for the terms. Only called when ABACUS_NETWORK is on."""
    if len(terms) < 4 or any(t.denominator != 1 for t in terms):
        return None, "OEIS not queried: it needs at least 4 integer terms"
    q = ",".join(str(int(t)) for t in terms[:20])
    url = "https://oeis.org/search?" + urllib.parse.urlencode({"q": q, "fmt": "json"})
    timeout = max(1.0, min(8.0, ctx.time_left() - 0.5))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "abacus-kit"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            data = json.load(resp)
        rows = data if isinstance(data, list) else (data.get("results") or [])
        return [{"a_number": "A%06d" % int(r["number"]), "name": r.get("name"),
                 "data": (r.get("data") or "")[:120]} for r in rows[:5]], None
    except Exception as e:  # noqa: BLE001
        return None, f"OEIS query failed ({type(e).__name__}: {e})"


# --------------------------------------------------------------------------------------------- the run

FORM_ORDER = {"known sequence": 0, "polynomial": 1, "hypergeometric": 2, "linear recurrence": 3,
              "rational generating function": 4}
TRIED = ("known sequences (Catalan, Fibonacci, Bell, Motzkin, derangements, powers of 2, factorials, triangular), "
         f"polynomials up to degree {MAX_DEGREE}, linear recurrences (Berlekamp-Massey over the rationals, order up "
         f"to {MAX_ORDER}), rational generating functions, and hypergeometric terms with a ratio of polynomials of "
         f"degree at most {MAX_RATIO_DEGREE}")


def _run(inp: dict, ctx) -> Evidence:
    has_terms, has_code = inp.get("terms") is not None, inp.get("code") is not None
    if has_terms == has_code:
        raise BadInput("give exactly one of terms and code (with n_range)")
    complete_terms = True
    if has_terms:
        raw = inp["terms"]
        if not isinstance(raw, list) or not raw:
            raise BadInput("terms must be a non-empty list")
        if len(raw) > MAX_TERMS:
            raise BadInput(f"at most {MAX_TERMS} terms are fitted; got {len(raw)}")
        terms = [_as_fraction(v, f"terms[{i}]") for i, v in enumerate(raw)]
        offset = inp.get("offset", 0)
        if not D.is_int(offset):
            raise BadInput("offset must be an integer")
    else:
        terms, offset, complete_terms = _terms_from_code(inp, ctx)
    h_req = inp.get("holdout", 3)
    if not D.is_int(h_req) or h_req < 0:
        raise BadInput("holdout must be an integer >= 0")

    N = len(terms)
    if not complete_terms:
        ev = Evidence(button=NAME, result={"candidates": [], "terms": N, "offset": offset}, method=METHOD,
                      complete=False,
                      scope=f"stopped at the time budget while computing f(n): {N} terms (n = {offset}..{offset + N - 1}) "
                            "were computed and nothing was fitted")
        return ev
    # Never hold back more than half the terms, and from 4 terms on keep at least 3 to fit.
    eff = min(h_req, N // 2, max(0, N - MIN_FIT))
    if N >= MIN_FIT_PREFERRED + 1:
        eff = min(eff, N - MIN_FIT_PREFERRED)
    F = N - eff
    fit, held = terms[:F], terms[F:]
    notes = []
    if eff < h_req:
        notes.append(f"holdout lowered from {h_req} to {eff}: with {N} terms, at most half are held back and "
                     f"{F} are left to fit"
                     if eff else f"holdout lowered from {h_req} to 0: {N} terms are too few to keep any back")
    if eff and (eff < 3 or F < 4):
        notes.append(f"thin evidence: fitted on {F} terms and tested on {eff}; a guess that survives has little "
                     "behind it, so give more terms to test it properly")

    steps: list[tuple[str, Callable[[], list[Model]]]] = [
        ("known sequences", lambda: _known_models(fit, N, offset)),
        ("polynomial", lambda: [m for m in [_polynomial_model(fit, offset, capped)] if m]),
        ("recurrence", lambda: _recurrence_models(fit, offset, capped)),
        ("hypergeometric", lambda: [m for m in [_hypergeometric_model(fit, offset)] if m]),
    ]
    refuted, vacuous = 0, 0
    kept: list[dict] = []
    capped: list[str] = []

    def result() -> dict:
        res = {"candidates": list(kept), "terms": N, "offset": offset, "fit_terms": F, "holdout": eff,
               "holdout_requested": h_req, "refuted": refuted}
        if not eff:
            res["unlisted_unsupported"] = vacuous
        if capped:
            res["capped"] = list(dict.fromkeys(capped))
        return res

    span = f"{N} terms (n = {offset}..{offset + N - 1})"
    how = (f"fitted on the first {F}, with the last {eff} kept back and predicted from the fit alone" if eff
           else "fitted on every term, with none held back to test the fit")
    stopped_at = None
    for label, make in steps:
        if ctx.time_left() <= 0.05:
            stopped_at = label
            break
        for m in make():
            if eff:
                pred = m.predict(eff)
                correct = sum(1 for p, a in zip(pred, held) if p is not None and p == a)
                if correct != eff:
                    refuted += 1
                    continue
            else:
                correct = 0
                if m.params >= F:  # pinned down by every term, so any list would fit: not worth listing
                    vacuous += 1
                    continue
            extra = dict(m.extra)
            if "_ratio" in extra:
                extra["ratio"] = extra.pop("_ratio")()
            cand = {"form": m.form, "expression": m.expression(), "fitted_on": F, "held_out": correct,
                    "held_out_tested": eff, **extra}
            if not eff:
                cand["note"] = "unsupported: it was fitted on every term, so nothing was held back to test it"
            kept.append(cand)
        ctx.progress({"result": result(), "method": METHOD,
                      "scope": f"{span}: {how}; stopped at the time budget after {label}"})
    kept.sort(key=lambda c: (c["held_out_tested"] == 0, FORM_ORDER[c["form"]]))

    ev = Evidence(button=NAME, result=result(), method=METHOD, scope="x")
    if stopped_at is None:
        ev.scope = f"{span}: {how}; tried {TRIED}. A fit that survives is a guess, not a proof."
    else:
        ev.complete = False
        ev.scope = f"{span}: {how}; stopped at the time budget before trying {stopped_at} and the forms after it"
    if not eff:
        ev.notes.append("holdout is 0: every candidate is unsupported, since it was fitted on every term and "
                        "nothing was held back to test it")
        if vacuous:
            ev.notes.append(f"{vacuous} form(s) that would need every term to pin down were not listed: "
                            "without held-out terms any list fits them")
    ev.notes.extend(notes)
    if capped:
        ev.notes.append("search stopped at its limits, which is not the same as finding no structure: "
                        + "; ".join(dict.fromkeys(capped)) + " (a polynomial of higher degree or a recurrence of "
                        "higher order than these was not looked for)")
    if refuted:
        ev.notes.append(f"{refuted} guess(es) fitted the first {F} terms but missed a held-out term, and are dropped")
    if get_config().network:
        found, problem = _oeis(terms, ctx)
        if found is not None:
            ev.result["oeis"] = found
            ev.scope += " OEIS was queried with the first terms."
        if problem:
            ev.notes.append(problem)
    return ev


@registry.button(NAME, description=DESCRIPTION, input_schema=SCHEMA, default_time_s=10)
def sequence_button(inp: dict, ctx) -> Evidence:
    try:
        return _run(inp, ctx)
    except BadInput as e:
        return D.bad_input(NAME, METHOD, str(e))

