"""growth: how does running time grow with input size? (kit/04 s14)

Timed, so noisy. The fit is a ranking of seven classes by how well t = c * g(n) holds in log space, reported as a
number (the relative RMS residual), never as a verdict. With fewer than 4 sizes no class is named.
"""
from __future__ import annotations

import copy
import gc
import inspect
import math
import random
import statistics
import time
from typing import Any, Callable

import numpy as np

from .. import registry
from ..evidence import Evidence
from . import _discrete as D
from ._cs import compile_callable
from ._discrete import BadInput

NAME = "growth"
START = 16                      # default sizes double from 2^4
MAX_DEFAULT_SIZES = 19          # ... and stop here at the latest (16 .. 2^22)
MAX_SIZE = 2 ** 40
MAX_SIZES_GIVEN = 64
MAX_REPEATS = 1000
DEFAULT_REPEATS = 5
MIN_SIZES = 4                   # fewer than this and no class is named
BATCH_TARGET_S = 2e-3           # a timed block of pure calls is made at least this long
RESERVE_S = 0.05
POOR_FIT = 0.35                 # relative RMS residual above which no class describes the timings well
TIMER_NOISE_S = 1e-4            # a slowest median under this is mostly timer and call overhead
DROPPED_RATIO = 3.0             # a size left out of the fit that is this far above or below the fitted curve is flagged
OVERHEAD_MULT = 20              # a size whose median is under this many call overheads is left out of the fit

DESCRIPTION = (
    "Measure how a function's running time grows with input size. fn is code (a lambda, a def, or an expression in "
    "x); make_input is code mapping n to an input (a lambda, a def, or an expression in n; the random generators are "
    "seeded by n, so the same input is built each run). sizes defaults to doubling from 16 until the next doubling is "
    "predicted not to fit the time budget; repeats (default 5) is how many timed calls per size, after a warm-up call. "
    "Result: the median time per size, the best-fitting class among 1, log n, n, n log n, n^2, n^3 and 2^n with the "
    "fit's relative RMS residual in log space, and the runner-up. The cost of calling an empty function is measured "
    "and subtracted from every median, and sizes whose median is under 20 times that cost are left out of the fit "
    "(the scope lists the sizes the fit used); if none is above it, no class is named. Timings are noisy and fits on "
    "small n are unreliable; with fewer than 4 sizes no class is named. A function that changes its input gets a "
    "fresh copy for every timed call; one that does not is timed repeatedly on the same input, so a cache or "
    "memoised function is timed hot (the warm-up call fills it) and its growth is not what a first call would show. "
    "A garbage collection runs before timed blocks (collection stays on); one that costs more than twice the block it "
    "precedes runs once per size instead of before every block. When many sizes are above the overhead only the "
    "larger half is fitted; if a size left out of the fit lies more than about 3 times above or below the fitted "
    "curve, the flag dropped_sizes_disagree names it. If the budget cuts a size short, that size's "
    "median comes from fewer repeats and the result is incomplete. fn and make_input are Python code that is "
    "executed, not sandboxed."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "fn": {"type": "string"},
        "make_input": {"type": "string"},
        "sizes": {"type": "array", "items": {"type": "integer"}},
        "repeats": {"type": "integer"},
    },
    "required": ["fn", "make_input"],
}


# ------------------------------------------------------------------------------------------------ the fit

# log of each class's growth function g(n); a constant factor drops out of the fit
CLASSES: dict[str, Callable[[float], float]] = {
    "1": lambda n: 0.0,
    "log n": lambda n: math.log(math.log(n)),
    "n": lambda n: math.log(n),
    "n log n": lambda n: math.log(n) + math.log(math.log(n)),
    "n^2": lambda n: 2 * math.log(n),
    "n^3": lambda n: 3 * math.log(n),
    "2^n": lambda n: n * math.log(2),
}


def fit_classes(sizes: list[int], times: list[float]) -> list[dict]:
    """Rank the classes by how constant t / g(n) is: for each, fit a free constant to log t - log g(n) and report
    the RMS of what is left (about the relative error of the fit). Smallest first. Needs 2+ sizes of at least 3."""
    y = [math.log(max(t, 1e-12)) for t in times]
    out = []
    for name, lg in CLASSES.items():
        r = [yi - lg(n) for yi, n in zip(y, sizes)]
        c = sum(r) / len(r)
        rms = math.sqrt(sum((ri - c) ** 2 for ri in r) / len(r))
        out.append({"class": name, "rms_log_residual": rms, "constant_s": math.exp(c) if c < 700 else math.inf})
    out.sort(key=lambda d: (d["rms_log_residual"], list(CLASSES).index(d["class"])))
    return out


# ------------------------------------------------------------------------------------------------ one size

class _UserError(Exception):
    def __init__(self, role: str, n: int, exc: BaseException):
        super().__init__(role)
        self.role, self.n, self.exc = role, n, exc


def _snapshot(x: Any, deep: bool) -> Any:
    if isinstance(x, np.ndarray):
        return x.copy()
    if deep:
        return copy.deepcopy(x)
    if isinstance(x, (list, dict, set, bytearray)):
        return copy.copy(x)
    return x


def _same(a: Any, b: Any) -> bool:
    try:
        if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
            return bool(np.array_equal(a, b))
        return bool(a == b)
    except Exception:  # noqa: BLE001
        return repr(a) == repr(b)


def _small(x: Any) -> bool:
    try:
        return len(x) <= 10_000
    except TypeError:
        return True


def _spreads(fn: Callable) -> bool:
    """fn takes two or more positional arguments, so a tuple from make_input is its argument list."""
    try:
        ps = [p for p in inspect.signature(fn).parameters.values()
              if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.default is p.empty]
    except (TypeError, ValueError):
        return False
    return len(ps) >= 2


def _noop(*_a: Any) -> None:
    return None


class Timer:
    def __init__(self, fn: Callable, make: Callable, repeats: int, ctx):
        self.fn, self.make, self.repeats, self.ctx = fn, make, repeats, ctx
        self.spread = _spreads(fn)
        self.mutating = False     # set if any size's input changed under fn
        self.gc_cost = 0.0        # seconds the last collection took
        self.overhead = self._measure_overhead()

    def _invoke(self, fn: Callable, arg: Any):
        return fn(*arg) if self.spread and isinstance(arg, tuple) else fn(arg)

    def _call(self, arg: Any):
        return self._invoke(self.fn, arg)

    def _measure_overhead(self) -> float:
        """Seconds one call costs when fn does nothing: the same call path, timed both in a batch and singly."""
        arg: Any = (0, 0) if self.spread else 0
        reps, best = 20_000, math.inf
        for _ in range(3):
            t = time.perf_counter()
            for _ in range(reps):
                self._invoke(_noop, arg)
            best = min(best, (time.perf_counter() - t) / reps)
        singles = []
        for _ in range(200):
            t = time.perf_counter()
            self._invoke(_noop, arg)
            singles.append(time.perf_counter() - t)
        return max(best, statistics.median(singles), 5e-8)

    def _collect(self, block_s: float, first: bool) -> None:
        """A collection before a timed block, so a pause from garbage left by the last block is not timed.
        Collection stays on. A collection that costs far more than the block it precedes is run once per size only."""
        if first or self.gc_cost <= 2 * block_s:
            t = time.perf_counter()
            gc.collect()
            self.gc_cost = time.perf_counter() - t

    def build(self, n: int) -> Any:
        """make_input(n) with the global random generators seeded by n (and put back after)."""
        st_py, st_np = random.getstate(), np.random.get_state()
        try:
            random.seed(n)
            np.random.seed(n % 2 ** 32)
            return self.make(n)
        except Exception as e:  # noqa: BLE001
            raise _UserError("make_input", n, e) from None
        finally:
            random.setstate(st_py)
            np.random.set_state(st_np)

    def measure(self, n: int) -> tuple[float, int, bool] | None:
        """(median seconds per call, timed calls, cut) at size n; ``cut`` is true when the budget ended the repeats
        early, so the median is from fewer calls than asked. None if the budget ran out before 3 calls."""
        arg = self.build(n)
        before = _snapshot(arg, deep=_small(arg))
        try:
            t = time.perf_counter()
            self._call(arg)
            warm = time.perf_counter() - t
        except Exception as e:  # noqa: BLE001
            raise _UserError("fn", n, e) from None
        pure = _same(arg, before)
        del before
        if not pure:
            self.mutating = True
        batch = 1
        if pure and warm < BATCH_TARGET_S / 2:
            batch = min(100_000, max(1, math.ceil(BATCH_TARGET_S / max(warm, 5e-8))))
        times: list[float] = []
        cut = False
        block_est = warm * batch if pure else warm
        for i in range(self.repeats):
            if self.ctx.time_left() <= RESERVE_S:
                cut = True
                break
            try:
                if pure:
                    self._collect(block_est, first=(i == 0))
                    t = time.perf_counter()
                    for _ in range(batch):
                        self._call(arg)
                    dt = (time.perf_counter() - t) / batch
                else:
                    fresh = self.build(n)       # a freshly built input; building it is not timed
                    self._collect(block_est, first=(i == 0))
                    t = time.perf_counter()
                    self._call(fresh)
                    dt = time.perf_counter() - t
            except _UserError:
                raise
            except Exception as e:  # noqa: BLE001
                raise _UserError("fn", n, e) from None
            times.append(dt)
        need = min(3, self.repeats)
        if len(times) < need:
            return None
        return statistics.median(times), len(times), cut


# ------------------------------------------------------------------------------------------------ the button

def _parse_sizes(sizes: Any) -> list[int] | None:
    if sizes is None:
        return None
    if not isinstance(sizes, list) or not sizes:
        raise BadInput("sizes must be a non-empty list of integers >= 2")
    if len(sizes) > MAX_SIZES_GIVEN:
        raise BadInput(f"sizes: at most {MAX_SIZES_GIVEN} sizes")
    if not all(D.is_int(s) and 2 <= s <= MAX_SIZE for s in sizes):
        raise BadInput(f"sizes must be integers from 2 to {MAX_SIZE}")
    return sorted(set(sizes))


def _run(inp: dict, ctx) -> Evidence:
    repeats = inp.get("repeats", DEFAULT_REPEATS)
    if not D.is_int(repeats) or not 1 <= repeats <= MAX_REPEATS:
        raise BadInput(f"repeats must be an integer from 1 to {MAX_REPEATS}")
    given = _parse_sizes(inp.get("sizes"))
    fn = compile_callable(inp.get("fn"), "fn", ["x"])
    make = compile_callable(inp.get("make_input"), "make_input", ["n"])

    timer = Timer(fn, make, repeats, ctx)
    sizes: list[int] = []
    medians: list[float] = []
    counts: list[int] = []
    costs: list[float] = []
    err: _UserError | None = None
    interrupted = False       # the budget ran out while timing a size
    cut_size: tuple[int, int] | None = None   # (n, repeats it got) when the budget ended a size's repeats early
    skipped: list[int] = []   # requested sizes that were not timed

    def partial() -> dict:
        return {"result": _result(sizes, medians, counts, timer.overhead), "method": "timed",
                "scope": f"stopped at the time budget after timing {len(sizes)} size(s); the rest were not timed"}

    pending = list(given) if given is not None else None
    n = pending[0] if pending else START
    idx = 0
    stop_reason = ""
    try:
        ctx.progress(partial())
        while True:
            if ctx.time_left() <= RESERVE_S:
                interrupted = True
                stop_reason = "the time budget was spent"
                break
            t0 = time.monotonic()
            got = timer.measure(n)
            cost = time.monotonic() - t0
            if got is None:
                interrupted = True
                stop_reason = "the time budget ran out while timing"
                break
            sizes.append(n)
            medians.append(got[0])
            counts.append(got[1])
            costs.append(cost)
            ctx.progress(partial())
            if got[2]:
                interrupted = True
                cut_size = (n, got[1])
                stop_reason = f"the time budget ended the repeats at n = {n} early"
                break
            # the next size
            if pending is not None:
                idx += 1
                if idx >= len(pending):
                    break
                nxt = pending[idx]
            else:
                if len(sizes) >= MAX_DEFAULT_SIZES or n * 2 > MAX_SIZE:
                    stop_reason = "the cap on default sizes was reached"
                    break
                nxt = n * 2
            if len(sizes) >= 2:
                s = n / sizes[-2]
                p = min(3.5, max(1.0, math.log(max(cost, 1e-9) / max(costs[-2], 1e-9)) / math.log(s)))
            else:
                p = 1.0
            predicted = cost * (nxt / n) ** p
            if predicted > ctx.time_left() * 0.85 - RESERVE_S:
                stop_reason = f"the next size ({nxt}) was predicted not to fit the time budget"
                break
            n = nxt
    except _UserError as e:
        err = e

    if pending is not None:
        skipped = pending[len(sizes):]
    given_cut = bool(skipped)
    complete = err is None and not interrupted and not given_cut
    if not sizes and err is None:
        complete = False

    result = _result(sizes, medians, counts, timer.overhead)
    fit_sizes = result["fit_sizes"]
    notes = ["timings are noisy, and fits on small n are unreliable; run it again, or give larger sizes, "
             "to see how far the ranking moves"]
    ev_flags: list[tuple[str, str]] = []
    k = len(sizes)
    notes.append(f"{k} size{'s' if k != 1 else ''} used" + (f" (n = {sizes[0]} to {sizes[-1]})" if k else ""))
    if timer.mutating:
        notes.append("fn changed its input, so every timed call got a freshly built input (building it is not timed)")
    if 0 < k < MIN_SIZES:
        notes.append(f"with {k} size{'s' if k != 1 else ''} (fewer than {MIN_SIZES}) the fit is unreliable; "
                     "no class is named")
        ev_flags.append(("unreliable_fit", f"only {k} size(s) were timed; the ranking is shown but no class is named"))
    rank = result["ranking"]
    kf = len(fit_sizes)
    floor_s = OVERHEAD_MULT * timer.overhead
    if k >= MIN_SIZES and kf == 0:
        ev_flags.append(("unreliable_fit", f"every median is under {OVERHEAD_MULT} times the call overhead "
                         f"({timer.overhead:.1e} s), so the timings show the cost of calling, not growth; no class "
                         "is named. Use larger sizes or a heavier fn"))
    elif k >= MIN_SIZES and kf < MIN_SIZES:
        ev_flags.append(("unreliable_fit", f"only {kf} of {k} sizes are above {OVERHEAD_MULT} times the call "
                         f"overhead ({floor_s:.1e} s); no class is named"))
    if k >= MIN_SIZES and kf >= MIN_SIZES and rank:
        best, run_up = rank[0], rank[1]
        if best["rms_log_residual"] > POOR_FIT:
            ev_flags.append(("unreliable_fit", f"the best fit leaves a relative RMS residual of "
                             f"{best['rms_log_residual']:.2f}; none of the classes describes these timings well"))
        elif max(medians) < TIMER_NOISE_S:
            ev_flags.append(("unreliable_fit", f"the slowest median is {max(medians):.1e} s, close to timer and "
                             "call overhead; use larger sizes"))
        if run_up["rms_log_residual"] < 1.5 * best["rms_log_residual"] + 0.02:
            notes.append(f"{best['class']} and {run_up['class']} fit about equally well "
                         f"({best['rms_log_residual']:.3f} and {run_up['rms_log_residual']:.3f}); "
                         "these sizes do not separate them")
    if result["dropped_disagree"]:
        dd = result["dropped_disagree"]
        parts = [f"n = {d['size']} ({d['median_s']:.1e} s measured, {d['fitted_s']:.1e} s on the fitted "
                 f"{rank[0]['class']} curve, {d['ratio']:.2g}x)" for d in dd]
        msg = ("size(s) left out of the fit disagree with the fitted curve by more than "
               f"{DROPPED_RATIO:g}x: " + "; ".join(parts) + ". The fit does not describe them (a spike, a "
               "start-up or cache effect, or a change of growth); see median_s")
        ev_flags.append(("dropped_sizes_disagree", msg))
        notes.append(msg)
    notes.append("the classes are 1, log n, n, n log n, n^2, n^3 and 2^n only; a growth between them "
                 "(n^1.5, say) is shown as the nearest one")

    cut_text = (f"; the repeats at n = {cut_size[0]} were cut by the time budget (it got {cut_size[1]} of "
                f"{repeats} repeats, so that median is from fewer calls)" if cut_size else "")
    if k:
        span = f"n = {sizes[0]}..{sizes[-1]} ({k} sizes, median of up to {repeats} calls each after a warm-up call, " \
               "time.perf_counter)"
    else:
        span = "no size could be timed"
    if err is not None:
        scope = f"fn/make_input raised at n = {err.n} after timing {k} size(s); " + span
    elif not complete:
        if given_cut:
            scope = (f"stopped at the time budget after timing {span}{cut_text}; the requested sizes "
                     f"{skipped[:6]}{'...' if len(skipped) > 6 else ''} were not timed")
        else:
            scope = f"stopped at the time budget after timing {span}{cut_text}; larger sizes were not timed"
    else:
        scope = f"timed {span}"
        if stop_reason:
            scope += f"; sizes stopped there because {stop_reason}"
    if k:
        if kf:
            used = f"n = {fit_sizes[0]}..{fit_sizes[-1]}" if kf > 1 else f"n = {fit_sizes[0]}"
            under = k - result["above_overhead"]
            halved = result["above_overhead"] - kf
            left = []
            if under:
                left.append(f"the {under} smaller size(s) whose median is under {OVERHEAD_MULT} times the measured "
                            f"call overhead of {timer.overhead:.1e} s")
            if halved:
                left.append(f"the {halved} next-smaller size(s), since {2 * MIN_SIZES} or more sizes were above "
                            "the overhead and only the larger half is fitted")
            scope += (f"; the fit used {used} ({kf} of {k} sizes)"
                      + (", leaving out " + " and ".join(left) if left else "")
                      + ", with the call overhead subtracted from each median")
        else:
            scope += (f"; the fit used no size: every median is under {OVERHEAD_MULT} times the measured call "
                      f"overhead of {timer.overhead:.1e} s")
    scope += ("; ranked against 1, log n, n, n log n, n^2, n^3 and 2^n. This is the time on these inputs at these "
              "sizes: other input shapes, the worst case and larger n are not covered")
    if 0 < k < MIN_SIZES:
        scope += "; the fit is unreliable with so few sizes"

    ev = Evidence(button=NAME, result=result, method="timed", scope=scope, complete=complete)
    for code, msg in ev_flags:
        ev.flag(code, msg)
    if err is not None:
        what = "make_input" if err.role == "make_input" else "fn"
        ev.flag("bad_input", f"{what} raised {type(err.exc).__name__}: {err.exc} at n = {err.n}")
    ev.notes.extend(notes)
    return ev


def _dropped_disagree(best: dict, dropped: list[tuple[int, float]], overhead: float) -> list[dict]:
    """The sizes left out of the fit (above the overhead floor, in the smaller half) whose median, overhead taken
    off, is more than DROPPED_RATIO times the fitted curve's value or less than 1/DROPPED_RATIO of it."""
    out = []
    c = best["constant_s"]
    if not (math.isfinite(c) and c > 0):
        return out
    for n, med in dropped:
        try:
            fitted = c * math.exp(CLASSES[best["class"]](n))
        except OverflowError:
            continue
        t = med - overhead
        if fitted > 0 and math.isfinite(fitted) and t > 0:
            ratio = t / fitted
            if ratio > DROPPED_RATIO or ratio < 1 / DROPPED_RATIO:
                out.append({"size": n, "median_s": med, "fitted_s": fitted, "ratio": ratio})
    return out


def _result(sizes: list[int], medians: list[float], counts: list[int], overhead: float) -> dict:
    """The timings, and the ranking fitted on the sizes whose median is well above the call overhead (the overhead
    subtracted)."""
    k = len(sizes)
    keep = [i for i, t in enumerate(medians) if t >= OVERHEAD_MULT * overhead]
    above = len(keep)
    if above >= 2 * MIN_SIZES:          # plenty of sizes: fit the larger half, where the growth shows (not the cache
        keep = keep[above - math.ceil(above / 2):]   # and start-up effects of the smaller ones)
    dropped = [i for i in range(k) if i not in keep and medians[i] >= OVERHEAD_MULT * overhead]   # above the floor, not fitted
    fs = [sizes[i] for i in keep]
    ft = [medians[i] - overhead for i in keep]
    res: dict[str, Any] = {"sizes": list(sizes), "median_s": list(medians), "repeats": list(counts),
                           "overhead_s": overhead, "above_overhead": above, "fit_sizes": fs,
                           "best": None, "runner_up": None, "fit": None, "ranking": [], "dropped_disagree": []}
    if len(fs) >= 2:
        rank = fit_classes(fs, ft)
        res["ranking"] = rank
        if len(fs) >= MIN_SIZES:
            res["best"], res["runner_up"] = rank[0]["class"], rank[1]["class"]
            res["fit"] = {"rms_log_residual": rank[0]["rms_log_residual"], "constant_s": rank[0]["constant_s"],
                          "runner_up_rms_log_residual": rank[1]["rms_log_residual"]}
            res["dropped_disagree"] = _dropped_disagree(rank[0], [(sizes[i], medians[i]) for i in dropped], overhead)
    return res


@registry.button(NAME, description=DESCRIPTION, input_schema=SCHEMA)
def growth_button(inp: dict, ctx) -> Evidence:
    try:
        return _run(inp, ctx)
    except BadInput as e:
        return D.bad_input(NAME, "timed", str(e))
