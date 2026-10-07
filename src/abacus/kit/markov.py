"""markov: exact Markov chains, optimal stopping and small zero-sum games (kit/04 s8).

Small chains (at most 200 states) are solved in exact rational arithmetic; larger ones in floating point, and
the result says which. The chain is a matrix, or a start state plus a step function whose states are found by
search from the start (capped at 5000 by default, and flagged when the cap is hit).
"""
from __future__ import annotations

import decimal
import math
import time
from fractions import Fraction
from typing import Any, Callable

import numpy as np
import sympy as sp

from .. import registry
from ..evidence import Evidence, jsonable, make_compare
from . import _discrete as D
from ._discrete import BadInput

NAME = "markov"
MAX_STATES = 5000
EXACT_MAX = 200            # states: more than this and the arithmetic is floating point
GAME_EXACT_MAX = 40        # rows and columns: a bigger game is solved by scipy's linprog, in floats
ROW_TOL = 1e-9             # how far a float row may be from summing to 1
BY_TIME_MAX = 3000         # (time, state) entries of a stopping problem listed in full
OPS = ["absorb", "hitting", "stationary", "stop", "game"]

DESCRIPTION = (
    "Exact Markov chains, optimal stopping and small matrix games. op is one of: absorb (the probability of "
    "ending in each absorbing state or closed class, from every state, and the expected steps until absorbed), "
    "hitting (expected steps to reach a target set; target is a list of states, or a Python predicate over "
    "`state` as a string, e.g. \"state[0] >= 3\"), stationary (the stationary distribution of each recurrent "
    "class, with its period), stop (optimal stopping by backward induction: needs payoff, the payoff of "
    "stopping in a state, as a Python expression/lambda/def of `state` or a table {state: value}, and horizon, "
    "the last time step at which you may stop (you must stop there); optional discount in (0, 1]; ties stop), "
    "game (value and an optimal mixed strategy for each side of the zero-sum matrix game `matrix`; the row "
    "player picks a row and maximizes). "
    "The chain is either matrix (a square list of rows; entries are ints, floats or strings like \"1/6\"), with "
    "optional states (labels, default 0..n-1), or start plus step: step is Python code, a function of `state` "
    "returning [(next_state, probability), ...] (an expression, lambda or def; a state for which it returns "
    "nothing is treated as absorbing). States are found by search from start, and may be any hashable "
    "(ints, strings, tuples; JSON lists are read as tuples); max_states (default 5000) caps the search and the "
    "result is flagged state_cap if it is hit. Probabilities are read as fractions: 1/6, '1/6', 0.25 and "
    "0.1666666666666667 are all taken as the simple fraction they are; each row must sum to 1. "
    "Up to 200 states the arithmetic is exact (sympy-style rationals, method symbolic); above that, or when "
    "an entry is a float that is not a simple fraction, it is floating point (method numeric) and a note says "
    "why. Games up to 40x40 are solved exactly and verified exactly; larger ones by linear programming in floats. "
    "Results are keyed by the state's label (str(state), or repr for tuples)."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "op": {"enum": OPS},
        "matrix": {"type": "array"},
        "states": {"type": "array"},
        "start": {},
        "step": {"type": "string"},
        "max_states": {"type": "integer"},
        "target": {"type": ["array", "string"]},
        "payoff": {"type": ["string", "object", "array"]},
        "horizon": {"type": "integer"},
        "discount": {"type": ["number", "string"]},
        "proposed": {},
    },
    "required": ["op"],
}


class StateCap(Exception):
    def __init__(self, found: int, cap: int, matrix: bool = False):
        super().__init__(found, cap, matrix)
        self.found, self.cap, self.matrix = found, cap, matrix


class Stopped(Exception):
    pass


class ExactTimeout(Exception):
    """Exact arithmetic used up its share of the time budget; the float path can still finish."""


class Singular(Exception):
    pass


# ----------------------------------------------------------------------------------------------- numbers

class Nums:
    """Reads the caller's numbers as fractions, and remembers what stops the arithmetic from being exact."""

    def __init__(self):
        self.clean = True         # False once a float that is not a simple fraction has been read
        self.simplified = False   # a long float was read as a nearby simple fraction
        self.inexact_rows = False # a row of floats sums to 1 only approximately

    def num(self, x: Any, role: str) -> Fraction:
        if isinstance(x, bool):
            raise BadInput(f"{role}: {x!r} is not a number")
        if isinstance(x, Fraction):
            return x
        if isinstance(x, (int, np.integer)):
            return Fraction(int(x))
        if isinstance(x, sp.Basic):
            if x.is_Rational:
                return Fraction(int(x.p), int(x.q))
            x = float(x)
        if isinstance(x, (float, np.floating)):
            x = float(x)
            if not math.isfinite(x):
                raise BadInput(f"{role}: {x} is not a finite number")
            exact = Fraction(repr(x))
            digits = len(decimal.Decimal(repr(x)).as_tuple().digits)
            if digits <= 15:
                return exact
            # a long float is read as a simple fraction only when it is within a few ulps of one (so 1/3 written
            # as 0.3333333333333333 is 1/3, but 3.333333333333333e-14 is not 0 and 0.9999999999999667 is not 1)
            near = Fraction(x).limit_denominator(10 ** 6)
            if near != 0 and abs(float(near) - x) <= 1e-15 * abs(x):
                self.simplified = True
                return near
            self.clean = False
            return exact
        if isinstance(x, str):
            try:
                return Fraction(x.strip())
            except (ValueError, ZeroDivisionError):
                raise BadInput(f"{role}: {x!r} is not a number (use an int, a float, or a string like \"1/6\")") from None
        raise BadInput(f"{role}: {D.short(x, 40)} is not a number")


def norm_state(x: Any) -> Any:
    """A hashable state: JSON lists become tuples, numpy scalars Python ones."""
    if isinstance(x, list):
        return tuple(norm_state(i) for i in x)
    if isinstance(x, np.generic):
        x = x.item()
    try:
        hash(x)
    except TypeError:
        raise BadInput(f"state {D.short(x, 40)} is not hashable (use ints, strings or tuples)") from None
    return x


def lab(s: Any) -> str:
    return s if isinstance(s, str) else repr(s)


# ----------------------------------------------------------------------------------------------- the chain

class Chain:
    """States and sparse rows [(j, Fraction)], found lazily from a step function or taken from a matrix."""

    def __init__(self, nums: Nums, cap: int, ctx):
        self.nums, self.cap, self.ctx = nums, cap, ctx
        self.states: list = []
        self.index: dict = {}
        self.rows: list[list[tuple[int, Fraction]] | None] = []
        self.step: Callable | None = None
        self.implicit = 0                # states with no transitions, made absorbing
        self._last = time.monotonic()

    def add(self, s: Any) -> int:
        i = self.index.get(s)
        if i is None:
            if len(self.states) >= self.cap:
                raise StateCap(len(self.states), self.cap)
            i = self.index[s] = len(self.states)
            self.states.append(s)
            self.rows.append(None)
        return i

    def set_row(self, i: int, raw: dict) -> None:
        """raw: {state index: Fraction}."""
        row = [(j, p) for j, p in raw.items() if p != 0]
        if any(p < 0 for _, p in row):
            raise BadInput(f"state {lab(self.states[i])}: a probability is negative")
        if not row:
            row = [(i, Fraction(1))]
            self.implicit += 1
        total = sum((p for _, p in row), Fraction(0))
        if total != 1:
            if abs(float(total) - 1) <= ROW_TOL:
                self.nums.inexact_rows = True
            else:
                raise BadInput(f"the probabilities out of state {lab(self.states[i])} sum to {total}, not 1")
        self.rows[i] = row

    def row(self, i: int) -> list[tuple[int, Fraction]]:
        if self.rows[i] is None:
            self._expand(i)
        return self.rows[i]

    def _expand(self, i: int) -> None:
        s = self.states[i]
        if time.monotonic() - self._last >= 0.2:
            self._last = time.monotonic()
            self.ctx.progress({"result": {"states_discovered": len(self.states)}, "method": "symbolic",
                               "scope": f"searching for states from the start: {len(self.states)} found so far; "
                                        "nothing solved yet"})
        if self.ctx.time_left() <= 0.05:
            raise Stopped()
        try:
            out = self.step(s)
            items = list(out.items()) if isinstance(out, dict) else list(out)
        except Exception as e:  # noqa: BLE001
            raise BadInput(f"step raised {type(e).__name__}: {e} at state {lab(s)}") from None
        raw: dict[int, Fraction] = {}
        for it in items:
            try:
                nxt, p = it
            except (TypeError, ValueError):
                raise BadInput(f"step must return [(next_state, probability), ...]; got {D.short(it, 40)} "
                               f"at state {lab(s)}") from None
            j = self.add(norm_state(nxt))
            raw[j] = raw.get(j, Fraction(0)) + self.nums.num(p, f"probability out of state {lab(s)}")
        self.set_row(i, raw)

    def expand_all(self) -> None:
        i = 0
        while i < len(self.states):
            self.row(i)
            i += 1

    @property
    def n(self) -> int:
        return len(self.states)

    def labels(self) -> list[str]:
        labs = [lab(s) for s in self.states]
        if len(set(labs)) < len(labs):
            labs = [repr(s) for s in self.states]
        return labs

    def succ(self) -> list[list[int]]:
        return [[j for j, _ in self.row(i)] for i in range(self.n)]


def build_chain(inp: dict, ctx, nums: Nums) -> Chain:
    cap = inp.get("max_states", MAX_STATES)
    if not D.is_int(cap) or cap < 1:
        raise BadInput("max_states must be an integer >= 1")
    chain = Chain(nums, cap, ctx)
    has_m, has_s = inp.get("matrix") is not None, inp.get("step") is not None
    if has_m and has_s:
        raise BadInput("give the chain either as a matrix or as start and step, not both")
    if has_m:
        m = inp["matrix"]
        if not isinstance(m, list) or not m or not all(isinstance(r, list) for r in m):
            raise BadInput("matrix must be a non-empty list of rows, each a list of probabilities")
        n = len(m)
        if any(len(r) != n for r in m):
            raise BadInput(f"matrix must be square: {n} rows, but the row lengths are {sorted({len(r) for r in m})}")
        if n > cap:
            raise StateCap(n, cap, matrix=True)
        st = inp.get("states")
        if st is None:
            st = list(range(n))
        elif not isinstance(st, list) or len(st) != n:
            raise BadInput(f"states must be a list of {n} labels, one per row of the matrix")
        for s in st:
            chain.add(norm_state(s))
        if chain.n != n:
            raise BadInput("states must be distinct")
        for i, r in enumerate(m):
            chain.set_row(i, {j: nums.num(p, f"matrix[{i}][{j}]") for j, p in enumerate(r)})
        return chain
    if has_s:
        if "start" not in inp:
            raise BadInput("a step function needs a start state")
        chain.step = D.UserFn(inp["step"], "step", ["state"], whole_object=True).call
        chain.add(norm_state(inp["start"]))
        return chain
    raise BadInput("give the chain as a matrix, or as a start state and a step function")


def start_index(chain: Chain, inp: dict) -> int | None:
    if "start" not in inp or inp["start"] is None:
        return None
    s = norm_state(inp["start"])
    if s not in chain.index:
        raise BadInput(f"start {lab(s)} is not a state of the chain")
    return chain.index[s]


# ----------------------------------------------------------------------------------------------- graphs

def sccs(succ: list[list[int]]) -> list[list[int]]:
    n = len(succ)
    idx, low, on = [-1] * n, [0] * n, [False] * n
    stack: list[int] = []
    comps: list[list[int]] = []
    counter = 0
    for root in range(n):
        if idx[root] != -1:
            continue
        work = [(root, 0)]
        while work:
            v, i = work.pop()
            if i == 0:
                idx[v] = low[v] = counter
                counter += 1
                stack.append(v)
                on[v] = True
            descended = False
            for k in range(i, len(succ[v])):
                w = succ[v][k]
                if idx[w] == -1:
                    work.append((v, k + 1))
                    work.append((w, 0))
                    descended = True
                    break
                if on[w]:
                    low[v] = min(low[v], idx[w])
            if descended:
                continue
            if low[v] == idx[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on[w] = False
                    comp.append(w)
                    if w == v:
                        break
                comps.append(sorted(comp))
            if work:
                u = work[-1][0]
                low[u] = min(low[u], low[v])
    return comps


def closed_classes(succ: list[list[int]]) -> tuple[list[list[int]], list[int]]:
    """(recurrent classes ordered by first state, class index per state or -1 for transient)."""
    comps = sccs(succ)
    comp_of = {}
    for c, comp in enumerate(comps):
        for s in comp:
            comp_of[s] = c
    rec = [comp for c, comp in enumerate(comps) if all(comp_of[w] == c for s in comp for w in succ[s])]
    rec.sort(key=lambda c: c[0])
    cls = [-1] * len(succ)
    for k, comp in enumerate(rec):
        for s in comp:
            cls[s] = k
    return rec, cls


def reverse_reach(seeds: list[int], pred: list[list[int]]) -> set[int]:
    seen = set(seeds)
    todo = list(seeds)
    while todo:
        v = todo.pop()
        for u in pred[v]:
            if u not in seen:
                seen.add(u)
                todo.append(u)
    return seen


# ----------------------------------------------------------------------------------------------- linear algebra

def linsolve(ctx, n: int, coeffs: list[dict], rhs: list[dict], exact: bool, soft: float | None = None) -> list[list]:
    """Solve A X = B. coeffs[r] is row r of A as {col: Fraction}; rhs[k] is column k of B as {row: Fraction}.
    Returns X as n lists of len(rhs) values (Fractions when exact, else floats). Exact elimination raises
    ExactTimeout once time.monotonic() passes `soft`, and Stopped when the whole budget is spent."""
    k = len(rhs)
    if n == 0:
        return []
    if exact:
        rows = []
        for r in range(n):
            d = dict(coeffs[r])
            for c, col in enumerate(rhs):
                v = col.get(r)
                if v:
                    d[n + c] = Fraction(v)
            rows.append(d)
        remaining = set(range(n))
        pivot_of: dict[int, int] = {}
        for c in range(n):
            if soft is not None and time.monotonic() > soft:
                raise ExactTimeout()
            if ctx.time_left() <= 0.05:
                raise Stopped()
            cand = [r for r in remaining if c in rows[r]]
            if not cand:
                raise Singular()
            p = min(cand, key=lambda r: len(rows[r]))
            remaining.discard(p)
            inv = 1 / rows[p][c]
            prow = {key: v * inv for key, v in rows[p].items()}
            rows[p] = prow
            for r in range(n):
                if soft is not None and time.monotonic() > soft:
                    raise ExactTimeout()
                if r != p and c in rows[r]:
                    f = rows[r][c]
                    rr = rows[r]
                    for key, v in prow.items():
                        nv = rr.get(key, 0) - f * v
                        if nv:
                            rr[key] = nv
                        else:
                            rr.pop(key, None)
            pivot_of[c] = p
        return [[rows[pivot_of[i]].get(n + c, Fraction(0)) for c in range(k)] for i in range(n)]
    import scipy.sparse as sps
    import scipy.sparse.linalg as spl
    rs, cs, vs = [], [], []
    for r in range(n):
        for c, v in coeffs[r].items():
            rs.append(r)
            cs.append(c)
            vs.append(float(v))
    A = sps.csc_matrix((vs, (rs, cs)), shape=(n, n))
    B = np.zeros((n, k))
    for c, col in enumerate(rhs):
        for r, v in col.items():
            B[r, c] = float(v)
    try:
        X = spl.splu(A).solve(B)
    except RuntimeError:
        raise Singular() from None
    resid = np.abs(A @ X - B).max() if B.size else 0.0
    if not np.isfinite(X).all() or resid > 1e-6 * max(1.0, float(np.abs(B).max() if B.size else 1.0)):
        raise Singular()
    return X.tolist()


# ----------------------------------------------------------------------------------------------- the run

class Run:
    """What the ops share: how the numbers are held and said."""

    def __init__(self, chain: Chain | None, nums: Nums, ctx):
        self.chain, self.nums, self.ctx = chain, nums, ctx
        self.exact = True
        self.notes: list[str] = []
        self.flags: list[tuple[str, str]] = []
        self.labels: list[str] = []

    def decide(self, n: int, what: str = "states") -> None:
        reasons = []
        if n > EXACT_MAX:
            reasons.append(f"{n} {what}, more than {EXACT_MAX}")
        if not self.nums.clean:
            reasons.append("some entries are floats that are not simple fractions")
        if self.nums.inexact_rows:
            reasons.append("rows of float probabilities sum to 1 only approximately")
        self.exact = not reasons
        if self.exact:
            self.notes.append(f"exact rational arithmetic ({n} {what}, at most {EXACT_MAX})")
        else:
            self.notes.append("floating point (float64), not exact: " + "; ".join(reasons))

    def finish_notes(self) -> None:
        """Notes that depend on how the run ended (so on whether the arithmetic stayed exact)."""
        if self.nums.simplified:
            self.notes.append("float entries with many digits (such as 0.3333333333333333) were read as the "
                              "nearest simple fraction (1/3)" + ("" if self.exact else
                                                                 ", but the arithmetic is floating point anyway"))

    def fall_back(self, how: str = "floats used (floating point, float64, not exact)") -> None:
        """Exact arithmetic ran out of its share of the time budget: say so and carry on in floating point."""
        self.exact = False
        self.notes = [n for n in self.notes if not n.startswith("exact rational arithmetic")]
        self.notes.append(f"exact arithmetic exceeded the time budget; {how}")
        self.flags.append(("exact_timeout", "exact arithmetic did not finish within its share of the time budget, "
                           "so the result was computed in floating point (float64) and is not exact"))

    def solve(self, n: int, coeffs: list[dict], rhs: list[dict]) -> list[list]:
        """linsolve in the run's arithmetic; exact falls back to floats if it takes more than half the time left."""
        if self.exact:
            soft = time.monotonic() + 0.5 * self.ctx.time_left()
            try:
                return linsolve(self.ctx, n, coeffs, rhs, True, soft)
            except ExactTimeout:
                self.fall_back()
        if self.ctx.time_left() <= 0.05:
            raise Stopped()
        return linsolve(self.ctx, n, coeffs, rhs, False)

    def out(self, x: Fraction) -> Any:
        return sp.Rational(x.numerator, x.denominator) if self.exact else float(x)

    def val(self, x: Any) -> Any:
        """A solved value (Fraction or float) as it is reported."""
        return self.out(x) if isinstance(x, Fraction) else float(x)

    @property
    def method(self) -> str:
        return "symbolic" if self.exact else "numeric"


def _ones(n: int) -> dict:
    return {i: Fraction(1) for i in range(n)}


def op_absorb(inp: dict, run: Run) -> tuple[dict, str, Any]:
    ch = run.chain
    ch.expand_all()
    n = ch.n
    run.decide(n)
    labs = run.labels = ch.labels()
    succ = ch.succ()
    rec, cls = closed_classes(succ)
    names = [labs[c[0]] if len(c) == 1 else "{" + ", ".join(labs[s] for s in c) + "}" for c in rec]
    trans = [i for i in range(n) if cls[i] == -1]
    pos = {s: k for k, s in enumerate(trans)}
    coeffs = [{k: Fraction(1)} for k in range(len(trans))]
    rhs = [dict() for _ in range(len(rec) + 1)]
    for s in trans:
        k = pos[s]
        for j, p in ch.rows[s]:
            if j in pos:
                coeffs[k][pos[j]] = coeffs[k].get(pos[j], 0) - p
            else:
                rhs[cls[j]][k] = rhs[cls[j]].get(k, Fraction(0)) + p
    rhs[len(rec)] = _ones(len(trans))
    X = run.solve(len(trans), coeffs, rhs)
    absorption, steps = {}, {}
    one = run.out(Fraction(1))
    for i in range(n):
        if cls[i] != -1:
            absorption[labs[i]] = {names[cls[i]]: one}
            steps[labs[i]] = run.out(Fraction(0))
        else:
            row = X[pos[i]]
            absorption[labs[i]] = {names[c]: run.val(row[c]) for c in range(len(rec)) if row[c] != 0}
            steps[labs[i]] = run.val(row[len(rec)])
    res: dict[str, Any] = {"absorption": absorption, "expected_steps": steps, "absorbing": names,
                           "transient": [labs[i] for i in trans]}
    headline: Any = absorption
    s0 = start_index(ch, run.inp)
    if s0 is not None:
        res["from_start"] = absorption[labs[s0]]
        res["expected_steps_from_start"] = steps[labs[s0]]
        headline = absorption[labs[s0]]
    if ch.implicit:
        run.notes.append(f"{ch.implicit} state(s) with no transitions were treated as absorbing")
    scope = (f"all {n} states of the chain; absorption into each of the {len(rec)} closed class(es) "
             f"from each of the {len(trans)} transient state(s)")
    return res, scope, headline


def _target_set(inp: dict, ch: Chain) -> list[int]:
    t = inp.get("target")
    if t is None:
        raise BadInput("hitting needs a target: a list of states, or a predicate over state as a string")
    if isinstance(t, str):
        pred = D.UserFn(t, "target", ["state"], whole_object=True).call
        idx = []
        for i, s in enumerate(ch.states):
            try:
                if pred(s):
                    idx.append(i)
            except Exception as e:  # noqa: BLE001
                raise BadInput(f"target raised {type(e).__name__}: {e} at state {lab(s)}") from None
    else:
        idx = []
        for x in t:
            s = norm_state(x)
            if s not in ch.index:
                raise BadInput(f"target state {lab(s)} is not a state of the chain")
            idx.append(ch.index[s])
    idx = sorted(set(idx))
    if not idx:
        raise BadInput("the target set is empty: none of the states is in it")
    return idx


def op_hitting(inp: dict, run: Run) -> tuple[dict, str, Any]:
    ch = run.chain
    ch.expand_all()
    n = ch.n
    run.decide(n)
    labs = run.labels = ch.labels()
    target = _target_set(inp, ch)
    tset = set(target)
    pred: list[list[int]] = [[] for _ in range(n)]
    for i in range(n):
        if i in tset:
            continue
        for j, _ in ch.rows[i]:
            pred[j].append(i)
    reach = reverse_reach(target, pred)
    never = [i for i in range(n) if i not in reach]
    doomed = reverse_reach(never, pred) if never else set()
    unknown = [i for i in range(n) if i not in doomed and i not in tset]
    pos = {s: k for k, s in enumerate(unknown)}
    coeffs = [{k: Fraction(1)} for k in range(len(unknown))]
    for s in unknown:
        k = pos[s]
        for j, p in ch.rows[s]:
            if j in pos:
                coeffs[k][pos[j]] = coeffs[k].get(pos[j], 0) - p
    X = run.solve(len(unknown), coeffs, [_ones(len(unknown))])
    steps: dict[str, Any] = {}
    for i in range(n):
        if i in tset:
            steps[labs[i]] = run.out(Fraction(0))
        elif i in doomed:
            steps[labs[i]] = math.inf
        else:
            steps[labs[i]] = run.val(X[pos[i]][0])
    res: dict[str, Any] = {"expected_steps": steps, "target": [labs[i] for i in target]}
    headline: Any = steps
    s0 = start_index(ch, run.inp)
    if s0 is not None:
        res["from_start"] = steps[labs[s0]]
        headline = steps[labs[s0]]
    if doomed:
        run.notes.append(f"{len(doomed)} state(s) reach the target with probability less than 1, so their "
                         "expected number of steps is infinite (inf)")
    if ch.implicit:
        run.notes.append(f"{ch.implicit} state(s) with no transitions were treated as absorbing")
    return res, f"all {n} states of the chain; expected steps to reach any of {len(target)} target state(s)", headline


def _period(members: list[int], succ: list[list[int]]) -> int:
    inside = set(members)
    level = {members[0]: 0}
    todo = [members[0]]
    for v in todo:
        for w in succ[v]:
            if w in inside and w not in level:
                level[w] = level[v] + 1
                todo.append(w)
    g = 0
    for u in members:
        for v in succ[u]:
            if v in inside:
                g = math.gcd(g, level[u] + 1 - level[v])
    return abs(g)


def op_stationary(inp: dict, run: Run) -> tuple[dict, str, Any]:
    ch = run.chain
    ch.expand_all()
    n = ch.n
    run.decide(n)
    labs = run.labels = ch.labels()
    succ = ch.succ()
    rec, _ = closed_classes(succ)
    classes, dists = [], []
    for members in rec:
        m = len(members)
        pos = {s: k for k, s in enumerate(members)}
        if m == 1:
            dist = {members[0]: Fraction(1)}
        else:
            coeffs: list[dict] = [dict() for _ in range(m)]
            for s in members:
                for j, p in ch.rows[s]:
                    if j in pos:
                        coeffs[pos[j]][pos[s]] = coeffs[pos[j]].get(pos[s], 0) + p
            for k in range(m):
                coeffs[k][k] = coeffs[k].get(k, 0) - 1
            coeffs[m - 1] = _ones(m)
            X = run.solve(m, coeffs, [{m - 1: Fraction(1)}])
            dist = {s: X[pos[s]][0] for s in members}
        dists.append(dist)
        classes.append({"states": [labs[s] for s in members], "period": _period(members, succ)})
    res: dict[str, Any] = {"recurrent_classes": classes}
    headline: Any = None
    if len(rec) == 1:
        full = {labs[i]: run.val(dists[0].get(i, Fraction(0))) for i in range(n)}
        res["stationary"] = full
        headline = full
    else:
        res["stationary"] = None
        for c, d in zip(classes, dists):
            c["stationary"] = {labs[s]: run.val(v) for s, v in d.items()}
        run.notes.append(f"the chain has {len(rec)} recurrent classes, so there is no single stationary "
                         "distribution; one is given for each class (see recurrent_classes)")
    for c in classes:
        if c["period"] > 1:
            run.notes.append(f"the class {{{', '.join(c['states'])}}} has period {c['period']}: its stationary "
                             "distribution is the long-run fraction of time in each state, not the limit of P^n")
    if ch.implicit:
        run.notes.append(f"{ch.implicit} state(s) with no transitions were treated as absorbing")
    return res, f"all {n} states of the chain; {len(rec)} recurrent class(es)", headline


# -------------------------------------------------------------------------------------------- stopping

def op_stop(inp: dict, run: Run) -> tuple[dict, str, Any]:
    ch, nums, ctx = run.chain, run.nums, run.ctx
    T = inp.get("horizon")
    if not D.is_int(T) or T < 0:
        raise BadInput("stop needs horizon, an integer >= 0: the last time step at which you may stop")
    if inp.get("payoff") is None:
        raise BadInput("stop needs payoff: Python code of state, or a table {state: value}")
    beta = Fraction(1)
    if inp.get("discount") is not None:
        beta = nums.num(inp["discount"], "discount")
        if not 0 < beta <= 1:
            raise BadInput("discount must be in (0, 1]")
    s0 = start_index(ch, inp)
    if s0 is None and ch.step is not None:
        raise BadInput("stop with a step function needs start")
    # the (time, state) pairs that can occur, forward from the start
    layers: list[list[int]] = [[s0] if s0 is not None else list(range(ch.n))]
    for t in range(T):
        if ctx.time_left() <= 0.05:
            raise Stopped()
        if s0 is None:
            layers.append(layers[0])
            continue
        nxt: dict[int, None] = {}
        for i in layers[t]:
            for j, _ in ch.row(i):
                nxt[j] = None
        layers.append(list(nxt))
    n = ch.n
    labs = run.labels = ch.labels()
    seen = sorted({i for layer in layers for i in layer})
    payoff = inp["payoff"]
    g: dict[int, Fraction] = {}
    if isinstance(payoff, str):
        fn = D.UserFn(payoff, "payoff", ["state"], whole_object=True).call
        for i in seen:
            try:
                g[i] = nums.num(fn(ch.states[i]), f"payoff of state {labs[i]}")
            except BadInput:
                raise
            except Exception as e:  # noqa: BLE001
                raise BadInput(f"payoff raised {type(e).__name__}: {e} at state {labs[i]}") from None
    else:
        if isinstance(payoff, dict):
            table = {k: v for k, v in payoff.items()}
            keyed = {labs[i]: i for i in range(n)}
            for i in seen:
                if labs[i] not in table:
                    raise BadInput(f"the payoff table has no entry for state {labs[i]}")
                g[i] = nums.num(table[labs[i]], f"payoff of state {labs[i]}")
            extra = [k for k in table if k not in keyed]
            if extra:
                run.notes.append(f"payoff entries for {len(extra)} label(s) that are not states were ignored")
        else:
            table = {}
            for pair in payoff:
                try:
                    s, v = pair
                except (TypeError, ValueError):
                    raise BadInput("a payoff list must be [[state, value], ...]") from None
                table[norm_state(s)] = v
            for i in seen:
                if ch.states[i] not in table:
                    raise BadInput(f"the payoff table has no entry for state {labs[i]}")
                g[i] = nums.num(table[ch.states[i]], f"payoff of state {labs[i]}")
    run.decide(n)
    one = Fraction(1)
    conv: Callable = (lambda f: f) if run.exact else float
    b = conv(beta)
    gv = {i: conv(v) for i, v in g.items()}
    by_time: list[dict | None] = [None] * (T + 1)
    keep = sum(len(layer) for layer in layers) <= BY_TIME_MAX
    vnext = {i: gv[i] for i in layers[T]}
    if keep:
        by_time[T] = {"t": T, "value": {labs[i]: run.val(vnext[i]) for i in layers[T]},
                      "stop": [labs[i] for i in layers[T]]}
    policy_now = {i: "stop" for i in layers[T]}
    for t in range(T - 1, -1, -1):
        if ctx.time_left() <= 0.05:
            raise Stopped()
        v: dict[int, Any] = {}
        stops, pol = [], {}
        for i in layers[t]:
            cont = b * sum((conv(p) * vnext[j] for j, p in ch.rows[i]), conv(Fraction(0)))
            if gv[i] >= cont:
                v[i], pol[i] = gv[i], "stop"
                stops.append(labs[i])
            else:
                v[i], pol[i] = cont, "continue"
        vnext, policy_now = v, pol
        if keep:
            by_time[t] = {"t": t, "value": {labs[i]: run.val(v[i]) for i in layers[t]}, "stop": stops}
    res: dict[str, Any] = {"horizon": T, "discount": run.out(beta),
                           "value": {labs[i]: run.val(vnext[i]) for i in layers[0]},
                           "policy": {labs[i]: policy_now[i] for i in layers[0]}}
    headline: Any = res["value"]
    if s0 is not None:
        res["value_at_start"] = res["value"][labs[s0]]
        headline = res["value_at_start"]
    if keep:
        res["by_time"] = by_time
    else:
        run.notes.append(f"by_time (the value and stopping set at every step) is left out: more than "
                         f"{BY_TIME_MAX} (time, state) pairs; value and policy are those at time 0")
    run.notes.append("on a tie between stopping and continuing, the policy stops; at the horizon you must stop")
    if ch.implicit:
        run.notes.append(f"{ch.implicit} state(s) with no transitions were treated as absorbing")
    scope = (f"backward induction over {T} step(s) from time 0 to the horizon {T}, on the "
             f"{len(seen)} state(s) that can occur" + ("" if s0 is None else " from the start"))
    return res, scope, headline


# -------------------------------------------------------------------------------------------------- game

def _simplex_game(A: list[list[Fraction]], soft: float | None = None) -> tuple[Fraction, list[Fraction], list[Fraction]]:
    """Value, row strategy and column strategy of the game A (the row player maximizes), exactly.
    Raises ExactTimeout once time.monotonic() passes `soft`."""
    m, n = len(A), len(A[0])
    shift = 1 - min(min(r) for r in A)
    B = [[a + shift for a in r] for r in A]              # all entries >= 1
    # maximize sum(w) subject to B w <= 1, w >= 0; w = y / value, and the duals give x / value
    cols = n + m
    tab = [list(B[i]) + [Fraction(1) if k == i else Fraction(0) for k in range(m)] + [Fraction(1)]
           for i in range(m)]
    obj = [Fraction(-1)] * n + [Fraction(0)] * m + [Fraction(0)]
    basis = [n + i for i in range(m)]
    while True:
        if soft is not None and time.monotonic() > soft:
            raise ExactTimeout()
        j = next((c for c in range(cols) if obj[c] < 0), None)
        if j is None:
            break
        best = None
        for i in range(m):
            if tab[i][j] > 0:
                ratio = tab[i][-1] / tab[i][j]
                if best is None or ratio < best[0] or (ratio == best[0] and basis[i] < basis[best[1]]):
                    best = (ratio, i)
        if best is None:
            raise Singular()
        r = best[1]
        pv = tab[r][j]
        tab[r] = [v / pv for v in tab[r]]
        for i in range(m):
            if soft is not None and time.monotonic() > soft:
                raise ExactTimeout()
            if i != r and tab[i][j] != 0:
                f = tab[i][j]
                tab[i] = [a - f * b for a, b in zip(tab[i], tab[r])]
        f = obj[j]
        obj = [a - f * b for a, b in zip(obj, tab[r])]
        basis[r] = j
    z = obj[-1]
    w = [Fraction(0)] * n
    for i, bv in enumerate(basis):
        if bv < n:
            w[bv] = tab[i][-1]
    y = [v / z for v in w]
    x = [obj[n + i] / z for i in range(m)]
    return 1 / z - shift, x, y


def _verify_game(A, v, x, y) -> bool:
    m, n = len(A), len(A[0])
    if any(p < 0 for p in x) or any(p < 0 for p in y) or sum(x) != 1 or sum(y) != 1:
        return False
    if any(sum(x[i] * A[i][j] for i in range(m)) < v for j in range(n)):
        return False
    return all(sum(A[i][j] * y[j] for j in range(n)) <= v for i in range(m))


def _linprog_game(A: np.ndarray) -> tuple[float, list[float], list[float]]:
    from scipy.optimize import linprog
    m, n = A.shape
    # row player: maximize v subject to A^T x >= v, sum x = 1, x >= 0
    c = np.zeros(m + 1)
    c[-1] = -1
    res = linprog(c, A_ub=np.hstack([-A.T, np.ones((n, 1))]), b_ub=np.zeros(n),
                  A_eq=[[1.0] * m + [0.0]], b_eq=[1.0], bounds=[(0, None)] * m + [(None, None)], method="highs")
    if res.status != 0:
        raise Singular()
    # column player: minimize w subject to A y <= w, sum y = 1, y >= 0
    c2 = np.zeros(n + 1)
    c2[-1] = 1
    res2 = linprog(c2, A_ub=np.hstack([A, -np.ones((m, 1))]), b_ub=np.zeros(m),
                   A_eq=[[1.0] * n + [0.0]], b_eq=[1.0], bounds=[(0, None)] * n + [(None, None)], method="highs")
    if res2.status != 0:
        raise Singular()
    x = np.clip(res.x[:m], 0, None)
    y = np.clip(res2.x[:n], 0, None)
    return float(res.x[-1]), (x / x.sum()).tolist(), (y / y.sum()).tolist()


def op_game(inp: dict, run: Run) -> tuple[dict, str, Any]:
    nums = run.nums
    M = inp.get("matrix")
    if not isinstance(M, list) or not M or not all(isinstance(r, list) and r for r in M):
        raise BadInput("game needs matrix: a non-empty list of rows of payoffs to the row player")
    m, n = len(M), len(M[0])
    if any(len(r) != n for r in M):
        raise BadInput("every row of the game matrix must have the same length")
    A = [[nums.num(v, f"matrix[{i}][{j}]") for j, v in enumerate(r)] for i, r in enumerate(M)]
    reasons = []
    if max(m, n) > GAME_EXACT_MAX:
        reasons.append(f"the game is {m}x{n}, larger than {GAME_EXACT_MAX}x{GAME_EXACT_MAX}")
    if not nums.clean:
        reasons.append("some entries are floats that are not simple fractions")
    run.exact = not reasons
    timed_out = False
    if run.exact:
        soft = time.monotonic() + 0.5 * run.ctx.time_left()
        try:
            v, x, y = _simplex_game(A, soft)
        except ExactTimeout:
            run.fall_back("floats used (floating point, float64, scipy linprog, not exact)")
            timed_out = True
        else:
            if _verify_game(A, v, x, y):
                run.notes.append("exact rational arithmetic (simplex over fractions); the strategies were "
                                 "checked exactly against the value")
                res: dict[str, Any] = {"value": run.out(v), "row_strategy": [run.out(p) for p in x],
                                       "col_strategy": [run.out(p) for p in y], "verified_exactly": True}
                return res, f"the {m}x{n} zero-sum game; the row player maximizes", res["value"]
            run.exact = False
            reasons.append("the exact solution failed its own check")
    if not timed_out:
        run.notes.append("floating point (float64, scipy linprog), not exact: " + "; ".join(reasons))
    if run.ctx.time_left() <= 0.05:
        raise Stopped()
    vf, xf, yf = _linprog_game(np.array([[float(a) for a in r] for r in A]))
    res = {"value": vf, "row_strategy": xf, "col_strategy": yf, "verified_exactly": False}
    return res, f"the {m}x{n} zero-sum game; the row player maximizes", vf


OPS_FN = {"absorb": op_absorb, "hitting": op_hitting, "stationary": op_stationary, "stop": op_stop,
          "game": op_game}


def _parse_proposed(p: Any, run: Run, nums: Nums) -> Any:
    """proposed, in the run's number type. `nums` is its own reader, apart from the chain's, so the notes about
    the chain's entries stay about the chain."""
    if isinstance(p, dict):
        return {k: _parse_proposed(v, run, nums) for k, v in p.items()}
    if isinstance(p, list):
        return [_parse_proposed(v, run, nums) for v in p]
    if p is None:
        return None
    try:
        return run.out(nums.num(p, "proposed"))
    except BadInput:
        raise BadInput(f"proposed {D.short(p, 40)} could not be read as a number or a string like \"1/6\"") from None


def _run(inp: dict, ctx) -> Evidence:
    op = inp["op"]
    nums = Nums()
    chain = None
    run = Run(None, nums, ctx)
    run.inp = inp
    try:
        if op != "game":
            chain = run.chain = build_chain(inp, ctx, nums)
        res, scope, headline = OPS_FN[op](inp, run)
    except StateCap as e:
        if e.matrix:
            ev = Evidence(button=NAME, result={"matrix_states": e.found}, method="symbolic", complete=False,
                          scope=f"the matrix has {e.found} states, more than the cap of {e.cap} (max_states); "
                                "nothing was solved")
            ev.flag("state_cap", f"the matrix has {e.found} states but max_states is {e.cap}; raise max_states, "
                    "or give a smaller matrix")
            return ev
        ev = Evidence(button=NAME, result={"states_discovered": e.found}, method="symbolic", complete=False,
                      scope=f"search from the start stopped at the cap of {e.cap} states; nothing was solved "
                            "because the reachable set is larger than that (it may be infinite)")
        ev.flag("state_cap", f"more than {e.cap} states are reachable from the start; raise max_states, or "
                "give a smaller chain")
        return ev
    except Stopped:
        found = chain.n if chain else 0
        ev = Evidence(button=NAME, result={"states_discovered": found}, method=run.method, complete=False,
                      scope=f"stopped at the time budget before a result was computed ({found} states found); "
                            "no result")
        ev.flag("stopped_before_result", "the time budget ran out before any result was computed; give a "
                "larger time budget or a smaller chain")
        for code, msg in run.flags:
            ev.flag(code, msg)
        return ev
    except Singular:
        ev = Evidence(button=NAME, result=None, method=run.method, complete=False,
                      scope="the linear system for this chain could not be solved (singular or ill-conditioned); "
                            "no result")
        ev.flag("singular", "the linear system was singular or too ill-conditioned to solve")
        return ev
    run.finish_notes()
    p0 = None
    if inp.get("proposed") is not None:
        pnums = Nums()
        p0 = _parse_proposed(inp["proposed"], run, pnums)
        if pnums.simplified:
            run.notes.append("proposed: a float with many digits was read as the nearest simple fraction")
    ev = Evidence(button=NAME, result=jsonable(res), method=run.method, scope=scope, complete=True,
                  precision=None if run.exact else "float64")
    ev.notes.extend(run.notes)
    for code, msg in run.flags:
        ev.flag(code, msg)
    if p0 is not None:
        if headline is None:
            ev.notes.append("there is no single value to compare proposed with")
        else:
            cmp = make_compare(p0, headline)
            if not run.exact and not isinstance(headline, (dict, list)) and isinstance(p0, (int, float)):
                cmp["difference"] = headline - p0
            ev.compare = jsonable(cmp)
    return ev


@registry.button(NAME, description=DESCRIPTION, input_schema=SCHEMA)
def markov_button(inp: dict, ctx) -> Evidence:
    try:
        return _run(inp, ctx)
    except BadInput as e:
        return D.bad_input(NAME, "symbolic", str(e))
