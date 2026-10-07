"""`abacus mint review`: record the AI's decisions in a batch (kit/07 s3).

Each instance gets `decision`, `keep` (the default) or `drop`, and an optional `note`. This is bookkeeping
and nothing else: no condition is attached to a decision, and a dropped instance stays in the file.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Mapping

from . import batchfile

KEEP, DROP = "keep", "drop"


def _indexes(values: Iterable, what: str) -> list[int]:
    if isinstance(values, (str, bytes)) or not hasattr(values, "__iter__"):
        raise ValueError(f"{what} must be a list of instance indexes, got {values!r}")
    out = list(values)
    for v in out:
        if not batchfile.is_int(v):
            raise ValueError(f"{what}: an instance index is an integer, got {v!r}")
    return out


def _notes(notes: Mapping[int, str] | None) -> dict[int, str]:
    if notes is None:
        return {}
    if not isinstance(notes, Mapping):
        raise ValueError(f"notes must map instance indexes to text, got {notes!r}")
    for k, v in notes.items():
        if not batchfile.is_int(k):
            raise ValueError(f"notes: an instance index is an integer, got {k!r}")
        if not isinstance(v, str):
            raise ValueError(f"notes: the note for instance {k} must be text, got {v!r}")
    return dict(notes)


def review_batch(batch_ref, *, drop: Iterable[int] = (), keep: Iterable[int] = (),
                 notes: Mapping[int, str] | None = None) -> tuple[Path, dict]:
    """Record decisions and notes, and rewrite the batch file atomically. Returns its path and a summary.

    `drop` and `keep` are instance `index` values; `notes` maps an index to text, and an empty text removes
    the note. ValueError for an index the batch does not have, one in both `drop` and `keep`, or a bad
    argument (nothing is written then); NoSuchBatch if there is no such batch; BadBatch if the file is not one.
    """
    drop, keep, notes = _indexes(drop, "drop"), _indexes(keep, "keep"), _notes(notes)
    path = batchfile.resolve(batch_ref)
    head, rows = batchfile.read(path)
    by_index = {r["index"]: r for r in rows}
    both = sorted(set(drop) & set(keep))
    if both:
        raise ValueError(f"instance{'s' if len(both) > 1 else ''} {', '.join(map(str, both))} "
                         "in both drop and keep")
    unknown = sorted({*drop, *keep, *notes} - by_index.keys())
    if unknown:
        have = f"; its indexes are {min(by_index)} to {max(by_index)}" if by_index else "; it has no instances"
        raise ValueError(f"no instance has index {', '.join(map(str, unknown))} in {path.name}{have}")

    changed = sorted({*drop, *keep, *notes})
    for i in drop:
        by_index[i]["decision"] = DROP
    for i in keep:
        by_index[i]["decision"] = KEEP
    for i, text in notes.items():
        if text:
            by_index[i]["note"] = text
        else:
            by_index[i].pop("note", None)
    if changed:
        for r in rows:
            r.setdefault("decision", KEEP)
        batchfile.write_atomic(path, batchfile.render(head, rows))

    dropped = sorted(r["index"] for r in rows if r.get("decision", KEEP) == DROP)
    kept = sum(1 for r in rows if r.get("decision", KEEP) == KEEP)
    return path, {"batch": batchfile.batch_id(path, head), "path": str(path), "instances": len(rows),
                  "kept": kept, "dropped": len(dropped), "dropped_indexes": dropped, "changed": changed}


def review(batch_ref, *, drop: Iterable[int] = (), keep: Iterable[int] = (),
           notes: Mapping[int, str] | None = None) -> Path:
    """Record decisions and notes in a batch and return the path of its file. See `review_batch`."""
    return review_batch(batch_ref, drop=drop, keep=keep, notes=notes)[0]
