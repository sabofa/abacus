"""usage.jsonl: one line per role run (kit/06 s4). Local to each machine; it powers the most_used sort."""
from __future__ import annotations

from pathlib import Path

from . import store
from ._jsonl import append_row, now_iso, read_rows


def usage_path() -> Path:
    return store.library_dir() / "usage.jsonl"


def record(algo: str, role: str, time_s: float, complete: bool) -> None:
    """Append one role run."""
    append_row(usage_path(), {"algo": algo, "role": role, "at": now_iso(),
                              "time_s": time_s, "complete": bool(complete)})


def counts() -> dict[str, int]:
    """Number of recorded runs per algorithm id. A missing file means none."""
    out: dict[str, int] = {}
    for r in read_rows(usage_path()):
        algo = r.get("algo")
        if isinstance(algo, str):
            out[algo] = out.get(algo, 0) + 1
    return out
