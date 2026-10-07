"""The small JSON-lines helpers that links.jsonl and usage.jsonl share."""
from __future__ import annotations

import contextlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

LOCK_TIMEOUT_S = 5.0  # how long a writer waits for the lock before giving up
LOCK_STALE_S = 60.0  # a lock file this old was left by a process that died holding it


def now_iso() -> str:
    """The current time as ISO 8601 in UTC, to the second: 2026-10-07T14:02:11Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_line(line: str) -> dict | None:
    """One line as a dict, or None for a blank line, bad JSON, or JSON that is not an object."""
    line = line.strip()
    if not line:
        return None
    try:
        row = json.loads(line)
    except ValueError:
        return None
    return row if isinstance(row, dict) else None


def read_rows(path: Path) -> list[dict]:
    """Every readable row of the file, in order. A missing file is empty. Bad lines are skipped."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    return [row for row in map(parse_line, text.split("\n")) if row is not None]


@contextlib.contextmanager
def file_lock(path: Path):
    """Hold an exclusive lock on `path` while the block runs, for writers that read then replace it.

    The lock is a file next to it, `<name>.lock`, made with O_CREAT | O_EXCL and removed afterwards.
    A writer that finds it there retries every few milliseconds and raises TimeoutError after
    LOCK_TIMEOUT_S. A lock older than LOCK_STALE_S is the leftover of a crash and is broken.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    while True:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except (FileExistsError, PermissionError):  # Windows says "permission" for a lock being deleted
            try:
                if time.time() - lock.stat().st_mtime > LOCK_STALE_S:
                    lock.unlink(missing_ok=True)
                    continue
            except OSError:
                pass  # gone since we looked, or not ours to touch: the deadline decides
            if time.monotonic() >= deadline:
                raise TimeoutError(f"could not take the lock {lock} within {LOCK_TIMEOUT_S:g} s; if no abacus "
                                   "process is running, delete it") from None
            time.sleep(0.01)
    try:
        yield
    finally:
        try:
            os.unlink(lock)
        except OSError:
            pass


def replace_file(src, dst, attempts: int = 5) -> None:
    """os.replace, retried briefly on PermissionError: on Windows the replace fails while a reader (or a
    virus scanner) has the target open, and that is over in a few milliseconds."""
    for attempt in range(1, attempts + 1):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts:
                raise
            time.sleep(0.02 * attempt)


def append_row(path: Path, row: dict) -> None:
    """Append one JSON object as one LF-terminated line, creating the directory and file if needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(row) + "\n").encode("utf-8")
    with open(path, "a+b") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        if size:  # a hand-edited file may lack its final newline; do not glue two rows together
            f.seek(size - 1)
            if f.read(1) != b"\n":
                data = b"\n" + data
        f.write(data)
