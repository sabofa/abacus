"""`abacus mint export`: the kept instances of a batch as a consumer's payload (kit/07 s4).

Nothing here calls the consumer. The payload is written next to the batch, `<batch-id>.osmosis.json`, and the
AI sends it. Problems in the payload are facts for the AI to read and are returned, never raised: the file
is written anyway.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ..adapters import osmosis
from . import batchfile
from .review import DROP, KEEP

TARGETS = ("osmosis",)
BAD_DECISION = "bad_decision"


def export_batch(batch_ref, *, to: str = "osmosis", tags, node_keys: Iterable[str] | None = None,
                 family_id: str | None = None) -> tuple[Path, dict]:
    """Write the payload for the kept instances, in index order. Returns the file's path and a summary:
    `{batch, path, to, questions, dropped, problems: [{code, message}]}`.

    An instance with no `decision` is kept. One whose decision is neither `keep` nor `drop` is left out
    and reported (a dropped instance is the AI's choice; a misspelt one is a mistake worth a look).
    Re-exporting a batch replaces its file. ValueError for an unknown target; NoSuchBatch and BadBatch
    as for `review`.
    """
    if to not in TARGETS:
        raise ValueError(f"cannot export to {to!r}; the only target is {', '.join(TARGETS)}")
    path = batchfile.resolve(batch_ref)
    head, rows = batchfile.read(path)
    batch = batchfile.batch_id(path, head)

    kept, dropped, problems = [], 0, []
    for row in sorted(rows, key=lambda r: r["index"]):
        decision = row.get("decision", KEEP)
        if decision == KEEP:
            kept.append(row)
        elif decision == DROP:
            dropped += 1
        else:
            problems.append(f"{BAD_DECISION}: instance {row['index']} has decision {decision!r}, "
                            f"not {KEEP!r} or {DROP!r}; it was left out of the export")
    payload, found = osmosis.to_create_questions(kept, tags=tags, node_keys=node_keys, family_id=family_id,
                                                 batch_id=batch)
    out = path.with_name(f"{batch}.osmosis.json")
    batchfile.write_atomic(out, batchfile.encode(payload, indent=2) + b"\n")
    return out, {"batch": batch, "path": str(out), "to": to, "questions": len(kept), "dropped": dropped,
                 "problems": [dict(zip(("code", "message"), osmosis.split_problem(p))) for p in problems + found]}


def export(batch_ref, *, to: str = "osmosis", tags, node_keys: Iterable[str] | None = None,
           family_id: str | None = None) -> Path:
    """Write the payload for a batch's kept instances and return the path of its file. See `export_batch`."""
    return export_batch(batch_ref, to=to, tags=tags, node_keys=node_keys, family_id=family_id)[0]
