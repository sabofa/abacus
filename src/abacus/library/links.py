"""links.jsonl: which algorithm made, checks, or belongs to which item in a consumer (kit/06 s3).

A link ties an algorithm to one target, written `<consumer>:<kind>:<id>`. The core treats the target
as an opaque string with a prefix; only an adapter knows what `osmosis:q:` means. Links are
reversible: `rm` deletes lines from links.jsonl and never touches an algorithm.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

from ..config import get_config
from ._jsonl import append_row, now_iso, parse_line, read_rows

KINDS = ("minted", "checks", "family")
_TARGET_RE = re.compile(r"[a-z0-9_-]+:[a-z0-9_-]+:.+")
_ALGO_RE = re.compile(r"\S+")


def links_path() -> Path:
    return get_config().library / "links.jsonl"


def _check(algo, target, kind) -> None:
    if not (isinstance(algo, str) and _ALGO_RE.fullmatch(algo)):
        raise ValueError(f"algo must be a non-empty string with no spaces, got {algo!r}")
    if not (isinstance(target, str) and _TARGET_RE.fullmatch(target)):
        raise ValueError(f"target must look like <consumer>:<kind>:<id>, such as 'osmosis:q:6b1f', got {target!r}")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {list(KINDS)}, got {kind!r}")


def target_matches(target: str, spec: str) -> bool:
    """True when `spec` is this exact target, or a consumer prefix of it: 'osmosis' or 'osmosis:q'."""
    return target == spec or target.startswith(spec.rstrip(":") + ":")


def add(algo: str, target: str, kind: str, *, algo_hash: str | None = None,
        seed: int | None = None, batch: str | None = None) -> dict:
    """Append one link and return it. Raises ValueError, writing nothing, on a bad algo, target or kind."""
    _check(algo, target, kind)
    rec = {"algo": algo, "target": target, "kind": kind, "algo_hash": algo_hash,
           "seed": seed, "batch": batch, "at": now_iso()}
    append_row(links_path(), rec)
    return rec


def _is_link(row: dict) -> bool:
    return isinstance(row.get("algo"), str) and isinstance(row.get("target"), str)


def _rows() -> list[dict]:
    return [r for r in read_rows(links_path()) if _is_link(r)]


def rm(algo: str, target: str) -> int:
    """Delete every line linking `algo` to `target`; return how many. Other lines are kept verbatim,
    including any this module cannot parse. The file is replaced atomically, only if a line went."""
    path = links_path()
    try:
        text = path.read_bytes().decode("utf-8", errors="surrogateescape")
    except FileNotFoundError:
        return 0
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    kept, removed = [], 0
    for line in lines:
        row = parse_line(line)
        if row is not None and row.get("algo") == algo and row.get("target") == target:
            removed += 1
        else:
            kept.append(line)
    if not removed:
        return 0
    data = "".join(line + "\n" for line in kept).encode("utf-8", errors="surrogateescape")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".links-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        try:
            shutil.copymode(path, tmp)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return removed


def list_links(algo: str | None = None, consumer: str | None = None) -> list[dict]:
    """Links in file order, optionally only those of one algorithm and/or one consumer prefix."""
    return [r for r in _rows()
            if (algo is None or r["algo"] == algo)
            and (consumer is None or target_matches(r["target"], consumer))]


def find(target: str) -> list[dict]:
    """Reverse lookup: every link to exactly this target."""
    return [r for r in _rows() if r["target"] == target]


def counts() -> dict[str, int]:
    """Number of links per algorithm id."""
    out: dict[str, int] = {}
    for r in _rows():
        out[r["algo"]] = out.get(r["algo"], 0) + 1
    return out
