"""`abacus algo lint`: run an algorithm through the kit and report what was found (spec 05 s7).

Nothing here is a verdict. Each check is reported as ok, problem or skipped, with the detail
that backs it; the algorithm is never stopped from being stored.
"""
from __future__ import annotations

import importlib
import time
from fractions import Fraction
from pathlib import Path
from typing import Any

from ..evidence import Evidence, make_compare
from .loader import AlgoImportError, MetaError, algo_hash, load_algo
from .rng import AbacusRNG
from .roles import normalise_instance

BUTTON = "algo_lint"  # an algorithm-file surface, not a spec button (tests/test_surfaces_agree.py INTERNAL)
CHECKS = ("header", "roles exist", "requires", "determinism", "agreement", "range", "spread", "cost")
DEFAULT_K = 5


def _c(name: str, status: str, detail: Any) -> dict:
    return {"check": name, "status": status, "detail": detail}


def _err(e: BaseException) -> str:
    return f"{type(e).__name__}: {e}"


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
    """Lint the algorithm file at `path` on `k` seeds. Reports; never judges."""
    k = max(1, int(k))
    t_start = time.monotonic()
    p = Path(path)
    checks: dict[str, dict] = {}
    timings: dict[str, float] = {}
    result: dict = {"file": str(p), "hash": None, "id": None, "k": k, "seeds": list(range(1, k + 1)),
                    "checks": [], "role_seconds": timings, "distinct_answers": None}
    notes: list[str] = []

    def finish(complete: bool = True) -> Evidence:
        for name in CHECKS:
            checks.setdefault(name, _c(name, "skipped", "not run"))
        result["checks"] = [checks[n] for n in CHECKS]
        return Evidence(button=BUTTON, result=result, method="sampled", complete=complete, notes=notes,
                        scope=f"lint of {p.name} on seeds 1..{k}, run in process; "
                              "it reports findings and passes no judgement")

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
    complete = True
    if gen is None:
        for n in ("determinism", "agreement", "range", "spread"):
            checks[n] = _c(n, "skipped", "no generate role")
    else:
        def make(seed: int):
            raw = timed("generate", gen, AbacusRNG(seed), {})
            return normalise_instance(raw, algo, seed)

        for seed in result["seeds"]:
            if time_s is not None and time.monotonic() - t_start > time_s:
                complete = False
                notes.append(f"time budget of {time_s}s ran out after {len(instances)} of {k} seeds")
                break
            try:
                instances[seed] = make(seed)
            except Exception as e:  # noqa: BLE001
                gen_errors.append(f"seed {seed}: {_err(e)}")

        # determinism
        if not instances:
            checks["determinism"] = _c("determinism", "problem" if gen_errors else "skipped",
                                       gen_errors or "no instance was generated")
        else:
            diff = []
            for seed, first in instances.items():
                try:
                    again = make(seed)
                except Exception as e:  # noqa: BLE001
                    diff.append(f"seed {seed}: second run raised {_err(e)}")
                    continue
                if again.to_dict() != first.to_dict():
                    diff.append(f"seed {seed}: two runs differ")
            if diff or gen_errors:
                checks["determinism"] = _c("determinism", "problem", diff + gen_errors)
            else:
                checks["determinism"] = _c("determinism", "ok",
                                           f"generate gave identical instances twice on {len(instances)} seeds")

        # agreement
        if comp is None and chk is None:
            checks["agreement"] = _c("agreement", "skipped", "no compute or check role")
        elif not instances:
            checks["agreement"] = _c("agreement", "skipped", "no instance was generated")
        else:
            dis = []
            for seed, inst in instances.items():
                val = inst.answer["value"]
                if comp is not None:
                    try:
                        got = timed("compute", comp, inst.params)
                        if not make_compare(val, got)["equal"]:
                            dis.append({"seed": seed, "role": "compute", "generated": val, "returned": got})
                    except Exception as e:  # noqa: BLE001
                        dis.append({"seed": seed, "role": "compute", "error": _err(e)})
                if chk is not None:
                    try:
                        ev = timed("check", chk, inst.params, val)
                        eq = (ev.compare["equal"] if ev.compare else ev.result) if isinstance(ev, Evidence) else None
                        if eq is not True:
                            dis.append({"seed": seed, "role": "check", "reported_equal": eq, "answer": val})
                    except Exception as e:  # noqa: BLE001
                        dis.append({"seed": seed, "role": "check", "error": _err(e)})
            ran = [n for n, f in (("compute", comp), ("check", chk)) if f is not None]
            checks["agreement"] = (_c("agreement", "problem", dis) if dis else
                                   _c("agreement", "ok", f"{ran} agree with generate on {len(instances)} seeds"))

        # range / format
        ans = algo.meta["answer"]
        rng_decl, fmt = ans.get("range"), ans["format"]
        if not instances:
            checks["range"] = _c("range", "skipped", "no instance was generated")
        else:
            out = []
            for seed, inst in instances.items():
                v = inst.answer["value"]
                if fmt == "integer" and not (isinstance(v, int) and not isinstance(v, bool)):
                    out.append(f"seed {seed}: {v!r} is not an integer")
                    continue
                if rng_decl is not None:
                    n = _as_number(v)
                    if n is None:
                        out.append(f"seed {seed}: {v!r} is not a number, so it cannot be placed in {rng_decl}")
                    elif not rng_decl[0] <= n <= rng_decl[1]:
                        out.append(f"seed {seed}: {v!r} is outside {rng_decl}")
            what = f"format {fmt}" + (f", range {rng_decl}" if rng_decl else ", no range declared")
            checks["range"] = (_c("range", "problem", out) if out else _c("range", "ok", f"every answer fits {what}"))

        # spread
        if not instances:
            checks["spread"] = _c("spread", "skipped", "no instance was generated")
        else:
            distinct = len({repr(i.answer["value"]) for i in instances.values()})
            result["distinct_answers"] = distinct
            checks["spread"] = _c("spread", "ok", {"distinct": distinct, "seeds": len(instances),
                                                    "share": round(distinct / len(instances), 4)})

    if timings:
        slow = max(timings, key=timings.get)
        checks["cost"] = _c("cost", "ok", {"slowest_role": slow, "slowest_seconds": timings[slow],
                                           "per_role_seconds": dict(timings)})
    else:
        checks["cost"] = _c("cost", "skipped", "no role was run")
    result["total_seconds"] = round(time.monotonic() - t_start, 4)
    return finish(complete)
