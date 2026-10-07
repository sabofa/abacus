"""Runaway guard: run a button in a child process with a time budget and a memory cap (spec 02 s5)."""
from __future__ import annotations

import importlib
import math
import multiprocessing as mp
import os
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


def _err(name: str, msg: str, last: dict | None = None) -> Evidence:
    last = last or {}
    ev = Evidence(button=name, result=last.get("result"), method=last.get("method") or "timed",
                  scope=last.get("scope") or "the button raised an error", complete=False)
    ev.flag("error", msg)
    return ev


def _bad(name: str, inp: dict, msg: str) -> Evidence:
    ev = Evidence(button=name, result=None, method="timed",
                  scope="input rejected before running", complete=False, input=jsonable(inp))
    ev.flag("bad_input", msg)
    return ev


def _grace(limit: float) -> float:
    """Extra wait past the limit so a button that stops itself at the deadline can finish sending."""
    return max(0.25, min(2.0, 0.1 * limit))


def _flush_std() -> None:
    """Flush what the role printed (a partial line stays buffered) before the parent can kill the child."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:  # noqa: BLE001
            pass


def _child(name: str, module: str, inp: dict, seed, limit: float, mem_mb: int, conn) -> None:
    try:
        # fd 1 is the parent's stdout (the CLI's JSON, the MCP stream) and a spawned child inherits it, so
        # anything the role prints would land in the parent's output. Send it to stderr instead, at the fd
        # level (C code, subprocesses) and at the Python level. sandbox._execute's redirect_stdout nests
        # inside this, so the `run` button still captures its own stdout.
        os.dup2(2, 1)
        sys.stdout = sys.stderr
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
        result = b.fn(inp, ctx).to_dict(full=True)
        _flush_std()  # the parent may terminate this process the moment it has the result
        conn.send(("done", result))
    except BaseException as e:  # noqa: BLE001
        _flush_std()
        conn.send(("error", f"{type(e).__name__}: {e}"))
    finally:
        conn.close()


def call(name: str, inp: dict, *, time_s=None, mem_mb=None, in_process=False, full=False) -> Evidence:
    b = registry.get(name)
    t_call = time.monotonic()
    cfg = get_config()
    inp = dict(inp)
    if inp.get("seed") is not None:
        sd = inp["seed"]
        if isinstance(sd, bool) or not isinstance(sd, int) or sd < 0:
            return _bad(name, inp, "seed must be an integer >= 0")
    try:
        jsonschema.validate({k: v for k, v in inp.items() if k != "seed"}, b.input_schema)
    except jsonschema.ValidationError as e:
        return _bad(name, inp, e.message)
    seed = inp.get("seed")
    if seed is None and b.uses_seed:
        seed = secrets.randbelow(2**32)
    if seed is not None:
        inp["seed"] = seed
    if time_s is None:
        time_s = b.default_time_s or cfg.time_s
    if isinstance(time_s, bool) or not isinstance(time_s, (int, float)) or not math.isfinite(time_s) or time_s <= 0:
        return _bad(name, inp, "time_s must be a finite number > 0")
    limit = min(float(time_s), cfg.time_max_s)
    mem_mb = mem_mb or cfg.mem_mb
    enforced = (not in_process) and sys.platform != "win32"
    t0 = time.monotonic()
    stopped, notes, last = False, [], {}

    if in_process:
        def prog(p): last.update(p)
        try:
            ev = b.fn(dict(inp), Ctx(seed, t0 + limit, prog))
        except Exception as e:  # noqa: BLE001
            # KeyboardInterrupt / SystemExit are BaseExceptions and deliberately propagate.
            ev = _err(name, f"{type(e).__name__}: {e}", last)
        notes.append("ran in process; the time limit is not enforced in process")
        stopped = time.monotonic() > t0 + limit
    else:
        ctx_mp = mp.get_context("spawn")
        parent, child = ctx_mp.Pipe(duplex=False)
        proc = ctx_mp.Process(target=_child, args=(name, b.fn.__module__, dict(inp), seed, limit, mem_mb, child), daemon=True)
        proc.start()
        child.close()
        # The child's Ctx deadline is `limit` from its ready instant; the parent waits `limit + grace`
        # from its own ready instant, so a button that stops itself at the limit can deliver its Evidence.
        wait_end, ev, ready, start_timeout = time.monotonic() + STARTUP_S, None, False, False
        try:
            while True:
                if not parent.poll(max(0.0, wait_end - time.monotonic())):
                    if ready:
                        stopped = True
                    else:
                        start_timeout = True
                    break
                try:
                    kind, data = parent.recv()
                except EOFError:
                    ev = _err(name, "the child process died without a result", last)
                    break
                if kind == "ready":
                    ready = True
                    t0 = time.monotonic()
                    wait_end = t0 + limit + _grace(limit)
                elif kind == "progress":
                    last = data
                elif kind == "done":
                    ev = Evidence(**data)
                    break
                else:
                    ev = _err(name, data, last)
                    break
        finally:
            parent.close()
            # On Windows terminate() kills only the child; any grandchild it spawned is orphaned (not handled).
            if proc.is_alive():
                proc.terminate()
                proc.join(2)
                if proc.is_alive():
                    proc.kill()
            proc.join(2)
        if start_timeout:
            ev = Evidence(button=name, result=None, method="timed",
                          scope=f"the child process did not start within {STARTUP_S:g} s", complete=False)
            ev.flag("startup_timeout", f"no ready signal within {STARTUP_S:g} s")
        elif stopped:
            ev = Evidence(button=name, result=last.get("result"), method=last.get("method") or "timed",
                          scope=last.get("scope") or "stopped at the time budget before any progress", complete=False)

    ev.notes.extend(notes)
    ev.input = jsonable(inp)
    if seed is not None:  # the caller's seed wins; a seed the button drew itself is kept when there is none
        ev.seed = seed
    ev.budget = {"time_s": round(time.monotonic() - t0, 3), "limit_s": limit,
                 "stopped": stopped, "mem_enforced": enforced}
    if name == "algo_run":
        # Every role run goes through here (run_role, the CLI's `abacus algo_run`, the MCP tool), so this
        # is the one place a run is recorded in usage.jsonl (kit/06 s4). Imported late: roles imports budget.
        # A run that never started (startup_timeout) did not use the algorithm, so it is not recorded.
        if not any(f.get("code") == "startup_timeout" for f in ev.flags):
            from .algo.roles import record_usage
            record_usage(inp.get("path"), inp.get("role"), ev, time.monotonic() - t_call)
    return ev
