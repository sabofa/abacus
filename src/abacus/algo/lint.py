"""`abacus algo lint`: run an algorithm through the kit and report what was found (spec 05 s7).

Nothing here is a verdict. Each check is reported as ok, problem or skipped, with the detail
that backs it; the algorithm is never stopped from being stored.
"""
from __future__ import annotations

import importlib
import json
import time
from fractions import Fraction
from pathlib import Path
from typing import Any

from ..evidence import Evidence, jsonable, make_compare
from .loader import AlgoImportError, MetaError, algo_hash, load_algo
from .rng import AbacusRNG
from .roles import normalise_instance

BUTTON = "algo_lint"  # an algorithm-file surface, not a spec button (tests/test_surfaces_agree.py INTERNAL)
CHECKS = ("header", "roles exist", "requires", "determinism", "agreement", "range", "spread", "cost")
DEFAULT_K = 20  # spec 05 s7
_ROLE_ERRORS = (Exception, SystemExit)  # a role that calls sys.exit() is reported, not fatal


def _c(name: str, status: str, detail: Any) -> dict:
    return {"check": name, "status": status, "detail": detail}


def _err(e: BaseException) -> str:
    return f"{type(e).__name__}: {e}"


def _msg(detail: Any) -> str:
    """A problem's detail as one line of text for its flag."""
    def one(x: Any) -> str:
        return x if isinstance(x, str) else json.dumps(jsonable(x), ensure_ascii=False)

    if isinstance(detail, list):
        text = "; ".join(one(x) for x in detail[:3])
        return text + (f"; and {len(detail) - 3} more" if len(detail) > 3 else "")
    return one(detail)


def _as_number(v: Any) -> Any:
    if isinstance(v, (int, float, Fraction)) and not isinstance(v, bool):
        return v
    if isinstance(v, str):
        try:
            return Fraction(v)
        except (ValueError, ZeroDivisionError):
            return None
    return None


def lint(path, *, k: int = DEFAULT_K, time_s: float | None = None) -> Evidence:
    """Lint the algorithm file at `path` on `k` seeds. Reports; never judges.

    `time_s` is a deadline for the whole lint, checked before every role call. When it passes, what has
    finished is reported, the rest is skipped, and the Evidence is marked incomplete.
    """
    k = max(1, int(k))
    t_start = time.monotonic()
    deadline = None if time_s is None else t_start + float(time_s)
    stopped: list[str] = []  # where the deadline fell, once it has
    p = Path(path)
    checks: dict[str, dict] = {}
    timings: dict[str, float] = {}
    result: dict = {"file": str(p), "hash": None, "id": None, "k": k, "seeds": list(range(1, k + 1)),
                    "checks": [], "role_seconds": timings, "distinct_answers": None}
    notes: list[str] = []

    def out_of_time(stage: str, done: int, of: int) -> bool:
        """True once the deadline has passed; remembers the first place it fell."""
        if deadline is None or time.monotonic() < deadline:
            return False
        if not stopped:
            stopped.append(f"{stage}, after {done} of {of} seeds")
            notes.append(f"time budget of {time_s:g}s ran out during {stopped[0]}")
        return True

    def finish() -> Evidence:
        for name in CHECKS:
            checks.setdefault(name, _c(name, "skipped", "not run"))
        result["checks"] = [checks[n] for n in CHECKS]
        if stopped:
            scope = (f"lint of {p.name} on seeds 1..{k}, stopped at the time budget of {time_s:g}s during "
                     f"{stopped[0]}; checks that did not finish are skipped; it reports findings and passes "
                     "no judgement")
        else:
            scope = f"lint of {p.name} on seeds 1..{k}; it reports findings and passes no judgement"
        ev = Evidence(button=BUTTON, result=result, method="sampled", complete=not stopped, notes=notes,
                      scope=scope)
        for name in CHECKS:
            if checks[name]["status"] == "problem":
                ev.flag(name, _msg(checks[name]["detail"]))
        return ev

    def skip_rest(why: str) -> None:
        for name in CHECKS:
            checks.setdefault(name, _c(name, "skipped", why))

    try:
        if p.is_file():
            result["hash"] = algo_hash(p)
        algo = load_algo(p)
    except AlgoImportError as e:
        checks["header"] = _c("header", "problem", str(e))
        skip_rest("the file could not be imported")
        return finish()
    except MetaError as e:
        checks["header"] = _c("header", "problem", str(e))
        skip_rest("META did not load")
        return finish()
    result["id"] = algo.meta["id"]
    checks["header"] = _c("header", "ok", f"META loads and validates ({algo.meta['id']})")

    def role(name: str):
        fn = getattr(algo.module, name, None)
        return fn if callable(fn) else None

    declared = algo.meta["roles"]
    absent = [r for r in declared if role(r) is None]
    checks["roles exist"] = (_c("roles exist", "problem", f"declared in META but not defined: {absent}")
                             if absent else _c("roles exist", "ok", f"all declared roles are defined: {declared}"))

    bad_req = []
    for mod in algo.meta["requires"]:
        try:
            importlib.import_module(mod)
        except Exception as e:  # noqa: BLE001
            bad_req.append(f"{mod}: {_err(e)}")
    checks["requires"] = (_c("requires", "problem", bad_req) if bad_req
                          else _c("requires", "ok", algo.meta["requires"] or "nothing required"))

    def timed(rolename: str, fn, *a):
        t0 = time.monotonic()
        try:
            return fn(*a)
        finally:
            timings[rolename] = max(timings.get(rolename, 0.0), round(time.monotonic() - t0, 4))

    gen, comp, chk = role("generate"), role("compute"), role("check")
    instances: dict[int, Any] = {}
    gen_errors: list[str] = []
    if gen is None:
        for n in ("determinism", "agreement", "range", "spread"):
            checks[n] = _c(n, "skipped", "no generate role")
    else:
        def make(seed: int):
            raw = timed("generate", gen, AbacusRNG(seed), {})
            return normalise_instance(raw, algo, seed)

        for done, seed in enumerate(result["seeds"]):
            if out_of_time("generate", done, k):
                break
            try:
                instances[seed] = make(seed)
            except _ROLE_ERRORS as e:
                gen_errors.append(f"seed {seed}: {_err(e)}")
        n_inst = len(instances)

        def cut_detail(what: str, done: int, of: int) -> str:
            return (f"the time budget ran out during {what} after {done} of {of} seeds; "
                    "nothing wrong was found in those")

        # determinism
        if not instances:
            checks["determinism"] = _c("determinism", "problem" if gen_errors else "skipped",
                                       gen_errors or ("the time budget ran out before any instance was generated"
                                                      if stopped else "no instance was generated"))
        else:
            diff, cut = [], None
            for done, (seed, first) in enumerate(instances.items()):
                if out_of_time("determinism", done, n_inst):
                    cut = done
                    break
                try:
                    again = make(seed)
                except _ROLE_ERRORS as e:
                    diff.append(f"seed {seed}: second run raised {_err(e)}")
                    continue
                if again.to_dict() != first.to_dict():
                    diff.append(f"seed {seed}: two runs differ")
            if diff or gen_errors:
                checks["determinism"] = _c("determinism", "problem", diff + gen_errors)
            elif cut is not None:
                checks["determinism"] = _c("determinism", "skipped", cut_detail("determinism", cut, n_inst))
            else:
                checks["determinism"] = _c("determinism", "ok",
                                           f"generate gave identical instances twice on {n_inst} seeds")

        # agreement
        if comp is None and chk is None:
            checks["agreement"] = _c("agreement", "skipped", "no compute or check role")
        elif not instances:
            checks["agreement"] = _c("agreement", "skipped", "no instance was generated")
        else:
            dis, cut = [], None
            for done, (seed, inst) in enumerate(instances.items()):
                val = inst.answer["value"]
                if comp is not None:
                    if out_of_time("agreement", done, n_inst):
                        cut = done
                        break
                    try:
                        got = timed("compute", comp, inst.params)
                        if not make_compare(val, got)["equal"]:
                            dis.append({"seed": seed, "role": "compute", "generated": val, "returned": got})
                    except _ROLE_ERRORS as e:
                        dis.append({"seed": seed, "role": "compute", "error": _err(e)})
                if chk is not None:
                    if out_of_time("agreement", done, n_inst):
                        cut = done
                        break
                    try:
                        ev = timed("check", chk, inst.params, val)
                        eq = (ev.compare["equal"] if ev.compare else ev.result) if isinstance(ev, Evidence) else None
                        if eq is not True:
                            dis.append({"seed": seed, "role": "check", "reported_equal": eq, "answer": val})
                    except _ROLE_ERRORS as e:
                        dis.append({"seed": seed, "role": "check", "error": _err(e)})
            ran = [n for n, f in (("compute", comp), ("check", chk)) if f is not None]
            if dis:
                checks["agreement"] = _c("agreement", "problem", dis)
            elif cut is not None:
                checks["agreement"] = _c("agreement", "skipped", cut_detail("agreement", cut, n_inst))
            else:
                checks["agreement"] = _c("agreement", "ok", f"{ran} agree with generate on {n_inst} seeds")

        # range / format
        ans = algo.meta["answer"]
        rng_decl, fmt = ans.get("range"), ans["format"]
        if not instances:
            checks["range"] = _c("range", "skipped", "no instance was generated")
        else:
            out = []
            for seed, inst in instances.items():
                raw = inst.answer["value"]
                v = jsonable(raw)  # sympy and numpy numbers become plain ints, floats or "p/q" strings
                if fmt == "integer" and not (isinstance(v, int) and not isinstance(v, bool)):
                    out.append(f"seed {seed}: {raw!r} is not an integer")
                    continue
                if rng_decl is not None:
                    n = _as_number(v)
                    if n is None:
                        out.append(f"seed {seed}: {raw!r} is not a number, so it cannot be placed in {rng_decl}")
                    elif not rng_decl[0] <= n <= rng_decl[1]:
                        out.append(f"seed {seed}: {raw!r} is outside {rng_decl}")
            what = f"format {fmt}" + (f", range {rng_decl}" if rng_decl else ", no range declared")
            if n_inst < k:
                what += f" (on {n_inst} of {k} seeds)"
            checks["range"] = (_c("range", "problem", out) if out else _c("range", "ok", f"every answer fits {what}"))

        # spread
        if not instances:
            checks["spread"] = _c("spread", "skipped", "no instance was generated")
        else:
            distinct = len({repr(jsonable(i.answer["value"])) for i in instances.values()})
            result["distinct_answers"] = distinct
            detail = {"distinct": distinct, "seeds": n_inst, "share": round(distinct / n_inst, 4)}
            status, knobs = "ok", algo.meta["knobs"]
            if distinct == 1 and not knobs:
                detail["note"] = "one answer is expected: META declares no knobs, so this is a one-off"
            elif n_inst < 2:
                detail["note"] = "only one instance was generated, so the spread was not measured"
            elif distinct == 1:
                status = "problem"
                detail["note"] = (f"the answer was the same on all {n_inst} seeds although META declares knobs "
                                  f"{sorted(knobs)}; the answer may not depend on the parameters")
            checks["spread"] = _c("spread", status, detail)

    if timings:
        slow = max(timings, key=timings.get)
        checks["cost"] = _c("cost", "ok", {"slowest_role": slow, "slowest_seconds": timings[slow],
                                           "per_role_seconds": dict(timings)})
    else:
        checks["cost"] = _c("cost", "skipped", "no role was run")
    result["total_seconds"] = round(time.monotonic() - t_start, 4)
    return finish()
