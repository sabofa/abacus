"""Runaway guard: run a button in a child process with a time budget and a memory cap (spec 02 s5)."""
from __future__ import annotations

import importlib
import multiprocessing as mp
import secrets
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable

import jsonschema

from . import registry
from .config import get_config
from .evidence import Evidence, jsonable

STARTUP_S = 120.0  # the clock starts when the child is ready; this only bounds a child that never starts


@dataclass
class Ctx:
    seed: int | None
    deadline: float
    progress: Callable[[dict], None]

    def time_left(self) -> float:
        return max(0.0, self.deadline - time.monotonic())


def _err(name: str, msg: str) -> Evidence:
    ev = Evidence(button=name, result=None, method="timed", scope="the button raised an error", complete=False)
    ev.flag("error", msg)
    return ev


def _child(name: str, module: str, inp: dict, seed, limit: float, mem_mb: int, conn) -> None:
    try:
        if sys.platform != "win32":
            import resource
            cap = mem_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
        import abacus  # noqa: F401
        registry.load_all()
        if module:
            importlib.import_module(module)
        b = registry.get(name)
        conn.send(("ready", None))
        ctx = Ctx(seed, time.monotonic() + limit, lambda p: conn.send(("progress", jsonable(p))))
        conn.send(("done", b.fn(inp, ctx).to_dict(full=True)))
    except BaseException as e:  # noqa: BLE001
        conn.send(("error", f"{type(e).__name__}: {e}"))
    finally:
        conn.close()


def call(name: str, inp: dict, *, time_s=None, mem_mb=None, in_process=False, full=False) -> Evidence:
    b = registry.get(name)
    cfg = get_config()
    inp = dict(inp)
    try:
        jsonschema.validate({k: v for k, v in inp.items() if k != "seed"}, b.input_schema)
    except jsonschema.ValidationError as e:
        ev = Evidence(button=name, result=None, method="timed",
                      scope="input rejected before running", complete=False, input=jsonable(inp))
        ev.flag("bad_input", e.message)
        return ev
    seed = inp.get("seed")
    if seed is None and b.uses_seed:
        seed = secrets.randbelow(2**32)
    if seed is not None:
        inp["seed"] = seed
    limit = min(float(time_s or b.default_time_s or cfg.time_s), cfg.time_max_s)
    mem_mb = mem_mb or cfg.mem_mb
    enforced = (not in_process) and sys.platform != "win32"
    t0 = time.monotonic()
    stopped, notes, last = False, [], {}

    if in_process:
        def prog(p): last.update(p)
        try:
            ev = b.fn(dict(inp), Ctx(seed, t0 + limit, prog))
        except Exception as e:  # noqa: BLE001
            ev = _err(name, f"{type(e).__name__}: {e}")
        notes.append("ran in process; the time limit is not enforced in process")
        stopped = time.monotonic() > t0 + limit
    else:
        ctx_mp = mp.get_context("spawn")
        parent, child = ctx_mp.Pipe(duplex=False)
        proc = ctx_mp.Process(target=_child, args=(name, b.fn.__module__, dict(inp), seed, limit, mem_mb, child), daemon=True)
        proc.start()
        child.close()
        wait_end, ev = time.monotonic() + STARTUP_S, None
        try:
            while True:
                if not parent.poll(max(0.0, wait_end - time.monotonic())):
                    stopped = True
                    break
                try:
                    kind, data = parent.recv()
                except EOFError:
                    ev = _err(name, "the child process died without a result")
                    break
                if kind == "ready":
                    t0 = time.monotonic()
                    wait_end = t0 + limit
                elif kind == "progress":
                    last = data
                elif kind == "done":
                    ev = Evidence(**data)
                    break
                else:
                    ev = _err(name, data)
                    break
        finally:
            if proc.is_alive():
                proc.terminate()
                proc.join(2)
                if proc.is_alive():
                    proc.kill()
            proc.join(2)
        if stopped:
            ev = Evidence(button=name, result=last.get("result"), method=last.get("method") or "timed",
                          scope=last.get("scope") or "stopped at the time budget before any progress", complete=False)

    ev.notes.extend(notes)
    ev.input, ev.seed = jsonable(inp), seed
    ev.budget = {"time_s": round(time.monotonic() - t0, 3), "limit_s": limit,
                 "stopped": stopped, "mem_enforced": enforced}
    return ev
