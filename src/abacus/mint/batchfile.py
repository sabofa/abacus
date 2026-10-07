"""Reading and writing a batch file, for `mint review` and `mint export` (kit/07 s3, s4).

A batch is `<library>/batches/<batch-id>.jsonl`: a summary line, then one instance per line (`make.py`
writes it). A batch reference is a batch id or a path. Files are replaced atomically: the new content
goes to a temp file beside the old one, then `os.replace`, so a reader sees the old file or the new one.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from ..library import store

SUFFIX = ".jsonl"
# What may be a batch id: no separator, no leading dot or dash. `make` writes <date>-<slug>-<nn>.
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class NoSuchBatch(FileNotFoundError):
    """No batch file has this id or path."""


class BadBatch(ValueError):
    """The file is not a batch: a line that is not JSON, or an instance with no usable `index`."""


def is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def resolve(batch_ref) -> Path:
    """The batch file for an id (`2026-10-07-power-mod-01`, with or without `.jsonl`) or a path.

    A reference is a path when it is a `Path`, has a separator, or names a file that exists; otherwise
    it is an id in `<library>/batches/`. ValueError for a bad id; NoSuchBatch when there is no such file.
    """
    if isinstance(batch_ref, Path) or (isinstance(batch_ref, str) and ("/" in batch_ref or "\\" in batch_ref)):
        path = Path(batch_ref)
    elif isinstance(batch_ref, str) and Path(batch_ref).is_file():
        path = Path(batch_ref)
    elif isinstance(batch_ref, str):
        batch_id = batch_ref[:-len(SUFFIX)] if batch_ref.endswith(SUFFIX) else batch_ref
        if not _ID.fullmatch(batch_id):
            raise ValueError(f"bad batch id {batch_ref!r}: use a batch id such as '2026-10-07-power-mod-01', "
                             "or a path to a batch file")
        path = store.library_dir() / "batches" / (batch_id + SUFFIX)
    else:
        raise ValueError(f"a batch is an id or a path, got {batch_ref!r}")
    if not path.is_file():
        raise NoSuchBatch(f"no batch file at {path}")
    return path


def batch_id(path: Path, head: dict | None) -> str:
    """The id in the summary line when it is a usable name, else the file's name without `.jsonl`."""
    named = (head or {}).get("batch")
    if isinstance(named, str) and _ID.fullmatch(named):
        return named
    return path.name[:-len(SUFFIX)] if path.name.endswith(SUFFIX) else path.stem


def read(path: Path) -> tuple[dict | None, list[dict]]:
    """The summary (the contents of line 1's `summary`, None when the file has no summary line) and the
    instance rows, in file order. BadBatch when a line is not a JSON object, or an instance has no integer
    `index` or repeats one."""
    head, rows, seen = None, [], set()
    text = path.read_text(encoding="utf-8-sig")
    for n, line in enumerate(text.split("\n"), start=1):  # not splitlines(): U+2028 may sit inside a string
        line = line.rstrip("\r")
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as e:
            raise BadBatch(f"{path.name} line {n} is not JSON: {e}") from None
        if not isinstance(row, dict):
            raise BadBatch(f"{path.name} line {n} is not a JSON object")
        if not rows and head is None and "summary" in row and "index" not in row:
            head = row["summary"] if isinstance(row["summary"], dict) else {}
            continue
        if not is_int(row.get("index")):
            raise BadBatch(f"{path.name} line {n}: an instance needs an integer `index`")
        if row["index"] in seen:
            raise BadBatch(f"{path.name} line {n}: index {row['index']} is used twice")
        seen.add(row["index"])
        rows.append(row)
    return head, rows


def encode(obj, **kw) -> bytes:
    """JSON as UTF-8. A lone surrogate in a string (it cannot be encoded) is written as an escape."""
    try:
        return json.dumps(obj, ensure_ascii=False, **kw).encode("utf-8")
    except UnicodeEncodeError:
        return json.dumps(obj, **kw).encode("utf-8")


def render(head: dict | None, rows: list[dict]) -> bytes:
    """The file's bytes: the summary line, if there is one, then the instances; every line ends in a newline."""
    lines = ([] if head is None else [encode({"summary": head})]) + [encode(r) for r in rows]
    return b"\n".join(lines) + b"\n"


def _rename_new(tmp: str, path: Path) -> None:
    """Windows: `os.rename` raises FileExistsError, atomically, when `path` exists; `os.replace` would
    overwrite it. So a look and then a replace is never used here: a file made in between would be lost."""
    os.rename(tmp, path)


def _create_new(tmp: str, path: Path) -> None:
    """Elsewhere: `path` is made with O_EXCL (FileExistsError if it exists, and the file there is not
    touched), then `tmp`'s bytes are copied in. A reader could see it part-written; it never replaces one
    that was already there. If the copy fails the half-written file is removed, as it is ours."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o666)
    try:
        with os.fdopen(fd, "wb") as out, open(tmp, "rb") as src:
            shutil.copyfileobj(src, out)
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        Path(path).unlink(missing_ok=True)
        raise


def _link_new(tmp: str, path: Path) -> None:
    """Give `tmp`'s content the name `path` unless a file has it already (FileExistsError). A hard link does
    it in one step; where the file system has none (FAT, a network drive), a rename that refuses to
    overwrite does it on Windows, and an exclusive create and a copy elsewhere."""
    try:
        os.link(tmp, path)
    except FileExistsError:
        raise
    except OSError:
        if os.name == "nt":
            _rename_new(tmp, path)
        else:
            _create_new(tmp, path)


def write_atomic(path: Path, data: bytes, *, exclusive: bool = False) -> None:
    """Replace `path` with `data`, or leave it as it was. The temp file is removed if anything fails.

    With `exclusive`, a file already at `path` is never replaced: FileExistsError, and it is left alone.
    """
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if exclusive:
            _link_new(tmp, path)
        else:
            os.replace(tmp, path)
    finally:
        try:
            Path(tmp).unlink(missing_ok=True)  # gone already after a replace; the link leaves it to go
        except OSError:
            pass  # held (antivirus, an indexer) on Windows: the batch is published already, so say nothing
