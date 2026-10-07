"""simulate: Monte Carlo for a trial the caller writes (kit/04 s7).

An estimate, never an exact value: the result carries its interval, the scope says how many trials it came from,
and a run the budget stops early still returns the estimate so far with ``complete=False``.
"""
from __future__ import annotations

import math
import numbers
import random
import secrets
import time
from fractions import Fraction
from typing import Any

import numpy as np

from .. import registry
from ..evidence import Evidence, jsonable, make_compare
from ..parsing import parse_expr
from . import _discrete as D
from ._discrete import BadInput

NAME = "simulate"
DEFAULT_TRIALS = 1_000_000
MAX_DISTINCT = 30            # a histogram is kept while there are at most this many distinct outcomes
MAX_SCALAR_CHUNK = 200_000
MAX_VECTOR_CHUNK = 2_000_000
Z95 = 1.959963984540054

DESCRIPTION = (
    "Monte Carlo. trial is Python code for one trial, a function of rng that returns a number or a bool: an "
    "expression (rng.randint(1, 6) + rng.randint(1, 6) == 7), a lambda or a def; math, itertools, Fraction, "
    "sp (sympy) and np (numpy) are available. rng is a numpy.random.Generator (integers, normal, uniform, "
    "binomial, ...) that also answers to Python's random module: rng.randint(a, b) is inclusive, and "
    "rng.random(), rng.choice(seq), rng.shuffle(list), rng.sample(seq, k) work as in random; rng.py is the "
    "random.Random itself. trials defaults to 1000000 (fewer if the time budget stops the run). "
    "vectorized: true makes trial a function of (rng, n) that returns an array of n outcomes, which is much "
    "faster for numpy code. Seeded: the same seed gives the same result. "
    "Result for bool trials: probability with its Wilson 95% interval, successes, variance. For numeric "
    "trials: mean, ci95 (normal approximation), variance, std_error, min and max, and a histogram when there "
    "are few distinct outcomes. Always trials_run. proposed (a number, '1/6' or an expression) adds a z-score "
    "to compare. This is an estimate with sampling error, not an exact value; a run the budget stops early "
    "returns the estimate so far with complete false."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "trial": {"type": "string"},
        "trials": {"type": "integer"},
        "vectorized": {"type": "boolean"},
        "proposed": {"type": ["number", "string"]},
    },
    "required": ["trial"],
}


# ------------------------------------------------------------------------------------------------ the rng

class Rng(np.random.Generator):
    """A numpy Generator that also answers to the parts of Python's ``random`` that a trial reaches for.

    Scalar calls with the plain ``random`` signature use a ``random.Random`` seeded alike (``rng.py``), which is
    several times faster than numpy for one number at a time; every other call is numpy's own.
    """

    def __init__(self, seed: int):
        super().__init__(np.random.PCG64(seed))
        self.py = random.Random(seed)

    def randint(self, a: int, b: int, size=None):
        """Uniform integer in [a, b], both ends included (as random.randint)."""
        if size is None:
            return self.py.randint(a, b)
        return self.integers(a, b + 1, size)

    def random(self, size=None, *args, **kw):
        if size is None and not args and not kw:
            return self.py.random()
        return super().random(size, *args, **kw)

    def choice(self, a, *args, **kw):
        if not args and not kw and isinstance(a, (list, tuple, str, range)):
            return self.py.choice(a)
        return super().choice(a, *args, **kw)

    def shuffle(self, x, *args, **kw):
        if isinstance(x, list) and not args and not kw:
            self.py.shuffle(x)
            return None
        return super().shuffle(x, *args, **kw)

    def sample(self, seq, k):
        """k distinct items of seq, as random.sample."""
        return self.py.sample(seq, k)


# ------------------------------------------------------------------------------------------- statistics

def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """The Wilson score interval for k successes in n trials."""
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


class Acc:
    """Running count, mean and sum of squared deviations (merged chunk by chunk), plus a small histogram."""

    def __init__(self):
        self.n = 0
        self.mean = 0.0
        self.m2 = 0.0
        self.k = 0                  # successes, for bool trials
        self.lo = math.inf
        self.hi = -math.inf
        self.mode: str | None = None    # "bool" or "num"
        self.hist: dict | None = {}     # value -> count, or None once there are too many distinct values

    def add(self, x: np.ndarray, keys: np.ndarray | None = None) -> None:
        m = x.size
        cm = float(x.mean())
        cm2 = float(((x - cm) ** 2).sum())
        tot = self.n + m
        d = cm - self.mean
        self.mean += d * m / tot
        self.m2 += cm2 + d * d * self.n * m / tot
        self.n = tot
        if self.mode == "bool":
            self.k += int(x.sum())
            return
        self.lo, self.hi = min(self.lo, float(x.min())), max(self.hi, float(x.max()))
        if self.hist is not None:
            u, c = np.unique(keys if keys is not None else x, return_counts=True)
            if len(u) > MAX_DISTINCT:
                self.hist = None
            else:
                for v, cnt in zip(u.tolist(), c.tolist()):
                    self.hist[v] = self.hist.get(v, 0) + cnt
                if len(self.hist) > MAX_DISTINCT:
                    self.hist = None

    def variance(self) -> float | None:
        if self.n < 2:
            return None
        if self.mode == "bool":
            return self.k * (self.n - self.k) / (self.n * (self.n - 1))
        return max(0.0, self.m2 / (self.n - 1))

    def std_error(self) -> float | None:
        v = self.variance()
        return math.sqrt(v / self.n) if v is not None else None

    def snapshot(self) -> dict:
        n = self.n
        if n == 0:
            return {"trials_run": 0}
        if self.mode == "bool":
            lo, hi = wilson(self.k, n)
            p = self.k / n
            return {"probability": p, "successes": self.k, "trials_run": n, "mean": p,
                    "variance": self.variance(), "ci95": [lo, hi],
                    "interval": "Wilson score interval, 95%"}
        se = self.std_error()
        res: dict[str, Any] = {"mean": self.mean, "variance": self.variance(), "std_error": se,
                               "ci95": ([self.mean - Z95 * se, self.mean + Z95 * se] if se is not None
                                        else [-math.inf, math.inf]),
                               "trials_run": n, "min": self.lo, "max": self.hi,
                               "interval": "mean +/- 1.96 standard errors (normal approximation), 95%"}
        if self.hist:
            res["histogram"] = [{"value": v, "count": c, "fraction": c / n} for v, c in sorted(self.hist.items())]
        return res

    def halfwidth(self) -> float | None:
        if self.n == 0:
            return None
        if self.mode == "bool":
            lo, hi = wilson(self.k, self.n)
            return (hi - lo) / 2
        se = self.std_error()
        return Z95 * se if se is not None else None


# ------------------------------------------------------------------------------------------------ chunks

_BOOL_TYPES = (bool, np.bool_)


class TrialError(Exception):
    pass


def _scalar_chunk(vals: list, acc: Acc) -> None:
    """Fold a list of trial outcomes into acc; raises TrialError for outcomes that cannot be used."""
    types = set(map(type, vals))
    is_bool = all(issubclass(t, _BOOL_TYPES) for t in types)
    if acc.mode is None:
        acc.mode = "bool" if is_bool else "num"
    if acc.mode == "bool":
        if not is_bool:
            raise TrialError("trial returned a bool and then something else; return only bools (a probability) "
                             "or only numbers (a mean)")
        x = np.asarray(vals, dtype=np.float64)
        acc.add(x)
        return
    if any(issubclass(t, _BOOL_TYPES) for t in types):
        raise TrialError("trial returned numbers and then a bool; return only bools or only numbers")
    bad = [t for t in types if not issubclass(t, numbers.Number)]
    if bad:
        raise TrialError(f"trial must return a number or a bool, got {bad[0].__name__}")
    if all(issubclass(t, (int, np.integer)) for t in types):
        try:
            keys = np.asarray(vals, dtype=np.int64)
        except OverflowError:
            keys = None
        x = keys.astype(np.float64) if keys is not None else np.asarray([float(v) for v in vals])
    else:
        keys = None
        try:
            x = np.asarray(vals, dtype=np.float64)
        except (TypeError, ValueError, OverflowError) as e:
            raise TrialError(f"trial returned a value that is not a real number ({e})") from None
    if not np.isfinite(x).all():
        raise TrialError("trial returned nan or inf")
    acc.add(x, keys)


def _vector_chunk(arr: Any, c: int, acc: Acc) -> None:
    arr = np.asarray(arr)
    if arr.shape != (c,):
        raise TrialError(f"a vectorized trial must return an array of n={c} outcomes, got shape {arr.shape}")
    kind = arr.dtype.kind
    if kind not in "biuf":
        raise TrialError(f"a vectorized trial must return bools or numbers, got dtype {arr.dtype}")
    mode = "bool" if kind == "b" else "num"
    if acc.mode is None:
        acc.mode = mode
    elif acc.mode != mode:
        raise TrialError("trial returned bools and then numbers (or the reverse); return only one kind")
    x = arr.astype(np.float64)
    if not np.isfinite(x).all():
        raise TrialError("trial returned nan or inf")
    acc.add(x, arr if kind in "iu" else None)


# --------------------------------------------------------------------------------------------- the run

def _parse_proposed(p: Any) -> tuple[Any, float]:
    """(value to show, float to compare with)."""
    if isinstance(p, bool):
        raise BadInput("proposed must be a number, a string like '1/6', or an expression")
    if isinstance(p, (int, float)):
        if not math.isfinite(p):
            raise BadInput("proposed must be finite")
        return p, float(p)
    if isinstance(p, str):
        try:
            f = Fraction(p.strip())
            return f, float(f)
        except (ValueError, ZeroDivisionError):
            pass
        try:
            v = float(parse_expr(p))
        except Exception:  # noqa: BLE001
            raise BadInput(f"proposed {p!r} could not be read as a number, a fraction or an expression") from None
        if not math.isfinite(v):
            raise BadInput(f"proposed {p!r} is not finite")
        return p, v
    raise BadInput("proposed must be a number, a string like '1/6', or an expression")


def _compare(ev: Evidence, shown: Any, p0: float, acc: Acc) -> None:
    n = acc.n
    if n == 0:
        ev.compare = make_compare(shown, None)
        return
    est = acc.k / n if acc.mode == "bool" else acc.mean
    if acc.mode == "bool":
        se = math.sqrt(p0 * (1 - p0) / n) if 0 < p0 < 1 else 0.0     # under the proposed value
        se_note = "standard error under the proposed probability"
    else:
        se = acc.std_error()
        se_note = "standard error of the estimate"
    if se is None:
        z = None
    elif se == 0:
        z = 0.0 if est == p0 else math.copysign(math.inf, est - p0)
    else:
        z = (est - p0) / se
    cmp = make_compare(shown, est)
    cmp["z"] = z
    cmp["standard_error"] = se
    cmp["z_note"] = f"(estimate - proposed) / {se_note}; |z| above about 3 is unlikely by chance alone"
    ev.compare = jsonable(cmp)


def _run(inp: dict, ctx) -> Evidence:
    vec = inp.get("vectorized", False)
    total = inp.get("trials", DEFAULT_TRIALS)
    if not D.is_int(total) or total < 1:
        raise BadInput("trials must be an integer >= 1")
    shown = p0 = None
    if inp.get("proposed") is not None:
        shown, p0 = _parse_proposed(inp["proposed"])
    fn = D.UserFn(inp.get("trial"), "trial", ["rng", "n"] if vec else ["rng"], whole_object=not vec)
    seed = ctx.seed if ctx.seed is not None else secrets.randbelow(2 ** 32)
    rng = Rng(seed)
    acc = Acc()
    kind = "vectorized trial" if vec else "trial"

    def scope_for(status: str) -> str:
        if status == "done":
            return (f"{acc.n} independent {kind}s, seed {seed}; a Monte Carlo estimate with a 95% interval, "
                    "not an exact value")
        if status == "error":
            return f"stopped at an error in the trial after {acc.n} of {total} trials (seed {seed}); the estimate is from those"
        return (f"stopped at the time budget after {acc.n} of {total} trials (seed {seed}); "
                "the estimate is from those trials only")

    def partial() -> dict:
        return {"result": jsonable(acc.snapshot()), "method": "sampled", "scope": scope_for("stopped")}

    status, err = "done", None
    size = 1
    last = time.monotonic()
    ctx.progress(partial())
    cap = MAX_VECTOR_CHUNK if vec else MAX_SCALAR_CHUNK
    while acc.n < total:
        if ctx.time_left() <= 0.05:
            status = "stopped"
            break
        c = min(size, total - acc.n)
        t0 = time.monotonic()
        try:
            if vec:
                _vector_chunk(fn.call(rng, c), c, acc)
            else:
                vals = [fn.call(rng) for _ in range(c)]
                _scalar_chunk(vals, acc)
        except TrialError as e:
            status, err = "error", str(e)
            break
        except Exception as e:  # noqa: BLE001
            status, err = "error", f"trial raised {type(e).__name__}: {e}"
            break
        dt = time.monotonic() - t0
        target = 0.1 if vec else 0.05
        grow = target / dt if dt > 0 else 10
        size = int(min(cap, max(1, c * min(grow, 10 if vec else 4))))
        if time.monotonic() - last >= 0.2:
            last = time.monotonic()
            ctx.progress(partial())

    n = acc.n
    snap = acc.snapshot()
    ev = Evidence(button=NAME, result=jsonable(snap), method="sampled", scope=scope_for(status),
                  complete=status == "done", seed=seed)
    hw = acc.halfwidth()
    if hw is not None:
        ev.precision = {"ci95_halfwidth": hw, "trials": n,
                        "interval": snap.get("interval")}
    if status == "error":
        ev.flag("bad_input", err)
    if n and acc.mode == "num" and acc.hist and set(acc.hist) <= {0, 1, 0.0, 1.0} and len(acc.hist) <= 2:
        ev.notes.append("every outcome was 0 or 1; return a bool from the trial to get a probability with a "
                        "Wilson interval")
    if status == "stopped":
        ev.notes.append("the estimate is from fewer trials than asked for, so its interval is wider")
    if p0 is not None:
        _compare(ev, shown, p0, acc)
    return ev


@registry.button(NAME, description=DESCRIPTION, input_schema=SCHEMA, uses_seed=True)
def simulate_button(inp: dict, ctx) -> Evidence:
    try:
        return _run(inp, ctx)
    except BadInput as e:
        return D.bad_input(NAME, "sampled", str(e))
