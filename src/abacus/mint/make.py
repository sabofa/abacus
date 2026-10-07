"""`abacus mint make`: a batch of instances from one algorithm, with evidence and flags (kit/07 s2).

For each attempt i, the seed is derived from (S, i); `generate` runs, then `compute` and `check` (if the
algorithm has them) and `demo`. Their Evidence goes on the instance. Then, across the batch, flags are set.
Flags are facts for the AI to read; nothing is dropped because of one.

The one thing left out of the file is a repeat of params already in it: it is the same problem again.
Repeats are counted in the summary (`duplicates_skipped`, `duplicate_attempts`) and flagged
`duplicate_params` on the instance they repeat. Generation then goes on with the next seed until `count`
distinct instances exist, or until count x 5 attempts have been made.

The roles run in this process: `make` is meant to run inside a button, which is already a child process
under the time budget. A role that overruns its budget is flagged `incomplete`, not stopped.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

from ..algo.loader import LoadedAlgo, load_algo, validate_knobs
from ..algo.roles import Instance, run_role
from ..evidence import Evidence, jsonable, make_compare
from ..library import store

ATTEMPTS_PER_INSTANCE = 5  # kit/07 s2: stop after count x 5 attempts
MIN_ROLE_S = 0.05  # the least budget a role is given once the batch's own budget has run out
SIGNALS_NOTE = "signals on hold (difficulty design pending)"
# The spec's order (kit/07 s2); the flags on an instance are listed in this order.
FLAG_ORDER = ("duplicate_params", "duplicate_statement", "duplicate_answer",
              "derivations_disagree", "out_of_range", "incomplete")


def signals_for(instance: Instance) -> dict:
    """Difficulty signals for an instance (kit/08). On hold until the difficulty design is settled."""
    return {}


def derive_seed(seed: int, i: int) -> int:
    """The seed for attempt `i` of a batch made with seed `seed`: 32 bits of sha256 of "<seed>:<i>"."""
    return int.from_bytes(hashlib.sha256(f"{seed}:{i}".encode()).digest()[:4], "big")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _looks_like_path(ref: str) -> bool:
    return ref.endswith(".py") or "/" in ref or "\\" in ref or Path(ref).is_file()


def _load(algo_ref) -> LoadedAlgo:
    """A library id, or a path to an algorithm file."""
    if isinstance(algo_ref, Path) or (isinstance(algo_ref, str) and _looks_like_path(algo_ref)):
        return load_algo(algo_ref)
    return store.read(algo_ref)  # a bad id is a ValueError; a missing one is NoSuchAlgo


def _is_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _canon(x: Any) -> str:
    """A key that is equal for equal params, statements or answers."""
    return json.dumps(jsonable(x), sort_keys=True, ensure_ascii=False)


def _show(x: Any, limit: int = 80) -> str:
    text = json.dumps(jsonable(x), ensure_ascii=False)
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _as_number(v: Any) -> Fraction | float | int | None:
    if isinstance(v, (int, float, Fraction)) and not isinstance(v, bool):
        return v
    if isinstance(v, str):
        try:
            return Fraction(v)
        except (ValueError, ZeroDivisionError):
            return None
    return None


def _others(indexes: list[int]) -> str:
    shown = ", ".join(str(i) for i in indexes[:5])
    return shown + (f" and {len(indexes) - 5} more" if len(indexes) > 5 else "")


def _why(ev: Evidence) -> str:
    """What a role that did not finish said about it."""
    return "; ".join(f"{f['code']}: {f['message']}" for f in ev.flags) or ev.scope


def _unfinished(role: str, ev: Evidence) -> str | None:
    """Why a role's Evidence is `incomplete`, or None when it finished within its budget."""
    if not ev.complete:
        return f"{role}: {_why(ev)}"
    if ev.budget.get("stopped"):
        return f"{role}: the time budget ran out while it was running"
    return None


def _tidy(ev: Evidence) -> Evidence:
    """Trim what would make a stored Evidence differ between two runs, or between two machines: the
    limit the role was given (it is what was left of the batch's budget), the absolute path of the
    algorithm file, the arguments (they are the instance's own params and answer), and the note that the
    role ran in process. What is kept is the role's own work and how long it took."""
    ev.input = {}
    ev.notes = [n for n in ev.notes if not n.startswith("ran in process")]
    ev.budget = {k: ev.budget[k] for k in ("time_s", "stopped") if k in ev.budget}
    return ev


def _run(path: Path, role: str, *, time_s: float | None, **kw) -> Evidence:
    """One role, in this process. A role that calls sys.exit() ends the role, not the batch."""
    try:
        return _tidy(run_role(path, role, time_s=time_s, in_process=True, **kw))
    except SystemExit as e:
        ev = Evidence(button="algo_run", result=None, method="timed", complete=False,
                      scope=f"the {role} role called sys.exit({e.code!r})")
        ev.flag("error", f"SystemExit: {e.code!r}")
        return ev


def _taken_numbers(batches: Path, date: str, slug: str) -> list[int]:
    """The numbers in use for `<date>-<slug>-<nn>`: by a batch, or by anything exported from one."""
    pat = re.compile(rf"^{re.escape(date)}-{re.escape(slug)}-(\d+)(?:\.|$)")
    return [int(m.group(1)) for f in batches.iterdir() if (m := pat.match(f.name))]


def _line(row: dict) -> bytes:
    try:
        return json.dumps(row, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:  # a lone surrogate somewhere in a statement
        return json.dumps(row).encode("utf-8")


def _write_batch(slug: str, render) -> tuple[str, Path]:
    """Create the next free `<library>/batches/<date>-<slug>-<nn>.jsonl`, never over a file that is there.
    `render(batch_id)` gives the file's lines."""
    batches = store.library_dir() / "batches"
    batches.mkdir(parents=True, exist_ok=True)
    date = _today()
    n = max(_taken_numbers(batches, date, slug), default=0) + 1
    while True:
        batch_id = f"{date}-{slug}-{n:02d}"
        path = batches / f"{batch_id}.jsonl"
        try:
            with open(path, "xb") as f:
                f.write(b"\n".join(render(batch_id)) + b"\n")
        except FileExistsError:
            n += 1
            continue
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return batch_id, path


def _check_input(count: Any, seed: Any, knobs: Any, time_s: Any) -> dict:
    if not _is_int(count) or count < 1:
        raise ValueError(f"count must be an integer >= 1, got {count!r}")
    if not _is_int(seed) or seed < 0:
        raise ValueError(f"seed must be an integer >= 0, got {seed!r}")
    if knobs is not None and not isinstance(knobs, dict):
        raise ValueError(f"knobs must be an object, got {type(knobs).__name__}")
    if time_s is not None and (isinstance(time_s, bool) or not isinstance(time_s, (int, float))
                               or not math.isfinite(time_s) or time_s <= 0):
        raise ValueError(f"time_s must be a finite number > 0, got {time_s!r}")
    return dict(knobs or {})


def make_batch(algo_ref, *, count: int, seed: int, knobs: dict | None = None,
               time_s: float | None = None) -> tuple[Path, dict]:
    """Make a batch and write it. Returns the file's path and the summary it starts with.

    `time_s` is the budget for the whole batch: no attempt starts after it has passed, and a role that
    is running when it passes is flagged `incomplete`. ValueError for bad input (MetaError and
    NoSuchAlgo included); nothing is written then.
    """
    knobs = _check_input(count, seed, knobs, time_s)
    algo = _load(algo_ref)
    meta = algo.meta
    bad = validate_knobs(meta, knobs)
    if bad:
        raise ValueError("; ".join(bad))
    has = {r: callable(getattr(algo.module, r, None)) for r in ("generate", "compute", "check", "demo")}
    if not has["generate"]:
        raise ValueError(f"{meta['id']} has no generate role, so it cannot make a batch")

    t0 = time.monotonic()
    deadline = None if time_s is None else t0 + time_s
    max_attempts = count * ATTEMPTS_PER_INSTANCE
    rng_decl = meta["answer"].get("range")

    kept: list[dict] = []  # {"inst": Instance, "attempt": int, "flags": {code: message}}
    by_params: dict[str, dict] = {}
    repeats: dict[str, list[int]] = {}  # params key -> the attempts that repeated it
    skipped: list[int] = []
    failures: list[str] = []
    attempts, stopped_by = 0, None

    def call(role: str, **kw) -> Evidence:
        left = None if deadline is None else max(deadline - time.monotonic(), MIN_ROLE_S)
        return _run(algo.path, role, time_s=left, **kw)

    while len(kept) < count:
        if attempts >= max_attempts:
            stopped_by = "attempts"
            break
        if deadline is not None and time.monotonic() >= deadline:
            stopped_by = "time"
            break
        attempts += 1
        gen = call("generate", seed=derive_seed(seed, attempts), knobs=knobs)
        if not isinstance(gen.result, dict):
            failures.append(f"attempt {attempts}: generate gave no instance: {_why(gen)}")
            continue
        inst = Instance.from_dict(gen.result)
        key = _canon(inst.params)
        if key in by_params:
            skipped.append(attempts)
            repeats.setdefault(key, []).append(attempts)
            continue

        flags: dict[str, str] = {}
        undone = [_unfinished("generate", gen)]
        disagree: list[str] = []
        answer = inst.answer["value"]
        evidence: list[Evidence] = []
        if has["compute"]:
            ev = call("compute", args={"params": inst.params})
            evidence.append(ev)
            undone.append(_unfinished("compute", ev))
            if ev.complete:
                got = jsonable(ev.result)
                if not make_compare(answer, got)["equal"]:
                    disagree.append(f"compute returned {_show(got)} but generate's answer is {_show(answer)}")
        if has["check"]:
            ev = call("check", args={"params": inst.params, "proposed": answer})
            evidence.append(ev)
            undone.append(_unfinished("check", ev))
            verdict = ev.compare["equal"] if ev.compare else (ev.result if isinstance(ev.result, bool) else None)
            if verdict is False or (verdict is None and ev.complete):
                computed = f" (it computed {_show(ev.compare['computed'])})" if ev.compare else ""
                disagree.append(f"check does not accept generate's answer {_show(answer)}{computed}")
        inst.evidence = evidence
        if has["demo"]:
            ev = call("demo", args={"instance": inst})
            undone.append(_unfinished("demo", ev))
            inst.demo = ev.result if ev.complete else None
        inst.signals = signals_for(inst)

        if disagree:
            flags["derivations_disagree"] = "; ".join(disagree)
        if rng_decl is not None:
            n = _as_number(jsonable(answer))
            if n is None:
                flags["out_of_range"] = f"the answer {_show(answer)} is not a number, so it cannot be placed in {rng_decl}"
            elif not rng_decl[0] <= n <= rng_decl[1]:
                flags["out_of_range"] = f"the answer {_show(answer)} is outside the declared range {rng_decl}"
        undone = [u for u in undone if u]
        if undone:
            flags["incomplete"] = "; ".join(undone)
        rec = {"inst": inst, "attempt": attempts, "flags": flags}
        kept.append(rec)
        by_params[key] = rec

    # Across the batch.
    for key, again in repeats.items():
        many = len(again) > 1
        by_params[key]["flags"]["duplicate_params"] = (
            f"generate gave these params again on {len(again)} later attempt{'s' if many else ''} "
            f"({_others(again)}); the repeat{'s were' if many else ' was'} skipped")
    for code, what, of in (("duplicate_statement", "statement", lambda r: r["inst"].statement),
                           ("duplicate_answer", "answer", lambda r: r["inst"].answer["value"])):
        groups: dict[str, list[int]] = {}
        for pos, rec in enumerate(kept, start=1):
            groups.setdefault(_canon(of(rec)), []).append(pos)
        for members in groups.values():
            if len(members) > 1:
                for pos in members:
                    rest = [m for m in members if m != pos]
                    kept[pos - 1]["flags"][code] = f"same {what} as instance{'s' if len(rest) > 1 else ''} {_others(rest)}"

    rows = []
    by_code = dict.fromkeys(FLAG_ORDER, 0)
    for pos, rec in enumerate(kept, start=1):
        ordered = [{"code": c, "message": rec["flags"][c]} for c in FLAG_ORDER if c in rec["flags"]]
        for f in ordered:
            by_code[f["code"]] += 1
        rows.append({"index": pos, "attempt": rec["attempt"], **rec["inst"].to_dict(),
                     "flags": ordered, "decision": "keep"})

    made = len(kept)
    notes = [SIGNALS_NOTE]
    if not (has["compute"] or has["check"]):
        notes.append(f"{meta['id']} has no compute or check role, so no instance was cross-checked")
    if stopped_by == "attempts":
        notes.append(f"found {made} distinct instance{'s' if made != 1 else ''} in {attempts} attempts "
                     f"(the limit is count x {ATTEMPTS_PER_INSTANCE} = {max_attempts}); "
                     "generate keeps repeating params, so its knobs may leave too little room")
    elif stopped_by == "time":
        notes.append(f"stopped at the time budget of {time_s:g}s with {made} of {count} instances "
                     f"after {attempts} attempts")
    notes += failures[:3]
    if len(failures) > 3:
        notes.append(f"and {len(failures) - 3} more failed generate calls")

    summary = {
        "algo": meta["id"], "algo_hash": algo.hash, "seed": seed, "knobs": knobs, "batch": None,
        "count": count, "made": made, "attempts": attempts, "stopped_by": stopped_by,
        "duplicates_skipped": len(skipped), "duplicate_attempts": skipped,
        "generate_failures": len(failures),
        "flags_by_code": {c: n for c, n in by_code.items() if n},
        "answer_spread": len({_canon(r["answer"]["value"]) for r in rows}),
        "time_s": round(time.monotonic() - t0, 3), "notes": notes,
    }

    def render(batch_id: str) -> list[bytes]:
        summary["batch"] = batch_id
        return [_line({"summary": summary}), *map(_line, rows)]

    _, path = _write_batch(meta["id"].rsplit(".", 1)[-1], render)
    return path, summary


def make(algo_ref, *, count: int, seed: int, knobs: dict | None = None, time_s: float | None = None) -> Path:
    """Make a batch and return the path of its file. See `make_batch`."""
    return make_batch(algo_ref, count=count, seed=seed, knobs=knobs, time_s=time_s)[0]
