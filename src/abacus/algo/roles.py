"""Run an algorithm's roles under the time budget, in a child process (spec 05 s3, s4)."""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from .. import __version__, budget, registry
from ..evidence import Evidence, jsonable
from .loader import AlgoImportError, LoadedAlgo, MetaError, load_algo, validate_knobs
from .rng import AbacusRNG

RUN_ROLES = ("compute", "check", "generate", "demo", "hand_space")
BUTTON = "algo_run"  # an algorithm-file surface, not a spec button (tests/test_surfaces_agree.py INTERNAL)


@dataclass
class Instance:
    """One generated problem (spec 05 s4). `solution` is reserved and always None for now."""
    params: dict = field(default_factory=dict)
    statement: str = ""
    answer: Any = None  # {"format": ..., "value": ...}; a bare value is wrapped from META
    algo: str = ""
    algo_hash: str = ""
    kit: str = __version__
    seed: int | None = None
    choices: list | None = None
    solution: None = None
    demo: Any = None
    evidence: list = field(default_factory=list)
    signals: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {f.name: getattr(self, f.name) for f in fields(self)}
        d["evidence"] = [e.to_dict(full=True) if isinstance(e, Evidence) else e for e in (self.evidence or [])]
        return jsonable(d)

    @classmethod
    def from_dict(cls, d: dict) -> "Instance":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


def _wrap_answer(ans: Any, fmt: str) -> dict:
    if isinstance(ans, dict) and set(ans) == {"format", "value"}:
        return dict(ans)
    return {"format": fmt, "value": ans}


def normalise_instance(raw: Any, algo: LoadedAlgo, seed: int | None) -> Instance:
    """Turn what `generate` returned (an Instance, a dict, or an object) into an Instance."""
    if isinstance(raw, Instance):
        d = {f.name: getattr(raw, f.name) for f in fields(Instance)}
    elif isinstance(raw, dict):
        d = dict(raw)
    else:
        d = {f.name: getattr(raw, f.name) for f in fields(Instance) if hasattr(raw, f.name)}
    missing = [k for k in ("params", "statement", "answer") if d.get(k) is None or (k == "statement" and not d[k])]
    if missing:
        raise ValueError(f"generate must return params, statement and answer; missing {missing}")
    if not isinstance(d["params"], dict):
        raise ValueError("generate: params must be a dict")
    fmt = algo.meta["answer"]["format"]
    d["answer"] = _wrap_answer(d["answer"], fmt)
    d["solution"] = None  # deferred (Ben, 2026-10-07)
    d["algo"], d["algo_hash"], d["kit"], d["seed"] = algo.meta["id"], algo.hash, __version__, seed
    d.setdefault("evidence", [])
    d["evidence"] = d["evidence"] or []
    d["signals"] = d.get("signals") or {}
    return Instance.from_dict(d)


def _missing(role: str, algo: LoadedAlgo) -> Evidence:
    ev = Evidence(button=BUTTON, result=None, method="timed",
                  scope=f"the algorithm {algo.meta['id']!r} does not define the {role!r} role", complete=False)
    ev.flag("missing_role", f"{algo.path.name} has no callable {role}()")
    return ev


def _fail(code: str, msg: str, scope: str) -> Evidence:
    ev = Evidence(button=BUTTON, result=None, method="timed", scope=scope, complete=False)
    ev.flag(code, msg)
    return ev


@registry.button(
    BUTTON,
    description="Run one role (compute, check, generate, demo, hand_space) of an algorithm file under the time "
                "budget. `args` holds the role's own arguments: params (compute, check, hand_space), "
                "proposed (check), instance (demo). generate takes `knobs` and, optionally, `seed`; "
                "the seed it used is recorded in the evidence.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "role": {"enum": list(RUN_ROLES)},
            "knobs": {"type": "object"},
            "args": {"type": "object"},
        },
        "required": ["path", "role"],
    },
    default_time_s=30,
)
def algo_run(inp: dict, ctx) -> Evidence:
    role, args, knobs = inp["role"], inp.get("args") or {}, inp.get("knobs") or {}
    try:
        algo = load_algo(inp["path"])
    except MetaError as e:
        return _fail("bad_meta", str(e), "the algorithm's META is invalid, so no role ran")
    except AlgoImportError as e:
        return _fail("import_error", str(e), "the algorithm file could not be imported, so no role ran")
    fn = getattr(algo.module, role, None)
    if not callable(fn):
        return _missing(role, algo)

    if role == "generate":
        bad = validate_knobs(algo.meta, knobs)
        if bad:
            return _fail("bad_knobs", "; ".join(bad), "the knob values were rejected, so generate did not run")
        # With no seed given, draw one and record it in Evidence.seed so the run can be repeated.
        seed = ctx.seed if ctx.seed is not None else secrets.randbelow(2**32)
        inst = normalise_instance(fn(AbacusRNG(seed), dict(knobs)), algo, seed)
        return Evidence(button=BUTTON, result=inst.to_dict(), method="sampled", seed=seed,
                        scope=f"one instance from generate(rng, knobs) of {algo.meta['id']} [{algo.hash}], seed {seed}")
    if role == "compute":
        value = fn(args.get("params") or {})
        return Evidence(button=BUTTON, result=value, method="timed",
                        scope=f"the value compute(params) returned for {algo.meta['id']} [{algo.hash}]")
    if role == "check":
        ev = fn(args.get("params") or {}, args.get("proposed"))
        if not isinstance(ev, Evidence):
            return _fail("bad_return", f"check must return an Evidence, got {type(ev).__name__}",
                         "check returned something other than Evidence")
        ev.notes.append(f"produced by the check role of {algo.meta['id']} [{algo.hash}]")
        return ev
    if role == "demo":
        inst = args.get("instance")
        show = fn(Instance.from_dict(inst) if isinstance(inst, dict) else inst)
        return Evidence(button=BUTTON, result=show, method="timed",
                        scope=f"the show payload demo(instance) returned for {algo.meta['id']} [{algo.hash}]")
    value = fn(args.get("params") or {})  # hand_space
    return Evidence(button=BUTTON, result=value, method="timed",
                    scope=f"the naive-search size hand_space(params) returned for {algo.meta['id']} [{algo.hash}]")


def _record_usage(algo_path, role: str, ev: Evidence, elapsed_s: float) -> None:
    """One usage.jsonl line for a run of an algorithm that lives in the library (kit/06 s4). Anything
    else is not recorded, nor is an input the budget rejected before it ran (it sets no `budget`).
    This can never fail a run: every error is swallowed."""
    try:
        from ..library import store, usage

        # Resolve against the working directory first: store.path_to_id reads a relative path as
        # library-relative, but the file that ran is the one that load_algo found from here.
        p = Path(algo_path).resolve()
        if ev.budget and p.is_file():
            usage.record(store.path_to_id(p), role, round(elapsed_s, 3), ev.complete)
    except Exception:  # noqa: BLE001 - not an algorithm in the library, or no way to write the log
        pass


def run_role(algo_path, role: str, *, args: dict | None = None, seed: int | None = None,
             knobs: dict | None = None, time_s: float | None = None, in_process: bool = False) -> Evidence:
    """Run one role of an algorithm file. `args` holds the role's own arguments and nothing else:
    compute/hand_space take `params`; check takes `params` and `proposed`; demo takes `instance`.
    `seed`, `knobs`, `time_s` and `in_process` steer the run itself and are separate keywords."""
    if role not in RUN_ROLES:
        return _fail("bad_input", f"role must be one of {list(RUN_ROLES)}, got {role!r}",
                     "input rejected before running")
    if args is not None and not isinstance(args, dict):
        return _fail("bad_input", f"args must be an object, got {type(args).__name__}",
                     "input rejected before running")
    args = dict(args or {})
    if isinstance(args.get("instance"), Instance):
        args["instance"] = args["instance"].to_dict()
    inp: dict = {"path": str(algo_path), "role": role, "knobs": dict(knobs or {}), "args": args}
    if seed is not None:
        inp["seed"] = seed
    t0 = time.monotonic()
    ev = budget.call(BUTTON, inp, time_s=time_s, in_process=in_process, full=True)
    _record_usage(algo_path, role, ev, time.monotonic() - t0)
    return ev
