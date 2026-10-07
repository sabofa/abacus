"""The small JSON-lines helpers that links.jsonl and usage.jsonl share."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


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
