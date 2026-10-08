"""`abacus mint link`: pair a `create_questions` response with a batch's kept instances and write links (kit/07 s5).

The response is `{"created": [{"id", "lineage_id", "prompt_preview"}, ...]}`. Entries are paired with the kept
instances (decision `keep`, in index order) by order, when there are as many entries as instances and every
preview agrees with its instance's statement. Otherwise each entry is matched on its prompt preview. Whatever
cannot be paired is reported, never guessed.

Each pair gets one `minted` link `osmosis:q:<lineage_id>` (with the algorithm's hash, the instance's seed and
the batch id), and the batch row records `lineage_id` and `osmosis_id`. Linking the same response again adds
no second link.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..library import links
from . import batchfile
from .review import KEEP

TARGET_PREFIX = "osmosis:q:"
BAD_ENTRY, COUNT_MISMATCH, NO_MATCH, UNMATCHED = "bad_entry", "count_mismatch", "no_match", "unmatched_instance"


def _norm(text: Any) -> str:
    return " ".join(str(text or "").split())


def _preview(entry: dict) -> str:
    """The entry's preview with the ellipsis a truncation leaves removed."""
    text = _norm(entry.get("prompt_preview"))
    for tail in ("…", "..."):
        if text.endswith(tail):
            text = text[:-len(tail)].rstrip()
    return text


def _agrees(entry: dict, row: dict) -> bool:
    """True when the entry's preview is the start of the instance's statement (or the whole of it); an
    entry with no preview agrees with anything, as it has nothing to disagree with."""
    p = _preview(entry)
    return not p or _norm(row.get("statement")).startswith(p)


def read_created(created: Any) -> list[dict]:
    """The `created` list of a response given as a dict, a JSON string, or the path of a JSON file."""
    if isinstance(created, (str, Path)):
        text = str(created)
        if text.lstrip().startswith(("{", "[")):
            created = json.loads(text)
        else:
            created = json.loads(Path(text).read_text(encoding="utf-8-sig"))
    if isinstance(created, list):
        entries = created
    elif isinstance(created, dict) and isinstance(created.get("created"), list):
        entries = created["created"]
    else:
        raise ValueError("the response must be {'created': [{id, lineage_id, prompt_preview}, ...]}")
    return entries


def _pair(entries: list[dict], kept: list[dict], problems: list[str]) -> tuple[list[tuple[dict, dict]], str]:
    """(entry, row) pairs and how they were made: 'order' or 'prompt'."""
    if len(entries) == len(kept) and all(_agrees(e, r) for e, r in zip(entries, kept)):
        return list(zip(entries, kept)), "order"
    if len(entries) != len(kept):
        problems.append(f"{COUNT_MISMATCH}: the response has {len(entries)} entries and the batch has "
                        f"{len(kept)} kept instances, so entries were matched on their prompt previews")
    else:
        problems.append(f"{NO_MATCH}: an entry's prompt_preview does not start its instance's statement, "
                        "so entries were matched on their prompt previews instead of by order")
    free = list(kept)
    pairs = []
    for n, e in enumerate(entries, start=1):
        hit = next((r for r in free if _preview(e) and _agrees(e, r)), None)
        if hit is None:
            problems.append(f"{NO_MATCH}: entry {n} (lineage {e.get('lineage_id')!r}) matches no kept instance")
            continue
        free.remove(hit)
        pairs.append((e, hit))
    for r in free:
        problems.append(f"{UNMATCHED}: instance {r['index']} was not paired with any entry")
    return pairs, "prompt"


def link_batch(batch_ref, created: Any) -> tuple[Path, dict]:
    """Write the links and record the lineage ids in the batch file. Returns its path and a summary:
    `{batch, path, matched_by, linked, already_linked, problems: [{code, message}]}`.

    ValueError for a response that is not a `created` list; NoSuchBatch and BadBatch as for `review`.
    A malformed entry, a count mismatch and an unpaired instance are reported as problems.
    """
    entries = read_created(created)
    path = batchfile.resolve(batch_ref)
    head, rows = batchfile.read(path)
    batch = batchfile.batch_id(path, head)
    kept = sorted((r for r in rows if r.get("decision", KEEP) == KEEP), key=lambda r: r["index"])

    problems: list[str] = []
    good = []
    for n, e in enumerate(entries, start=1):
        lineage = e.get("lineage_id") if isinstance(e, dict) else None
        if isinstance(lineage, str) and lineage.strip():
            good.append(e)
        else:
            problems.append(f"{BAD_ENTRY}: entry {n} has no lineage_id, so it was skipped")
    pairs, how = _pair(good, kept, problems)

    linked = already = 0
    for e, row in pairs:
        target = TARGET_PREFIX + e["lineage_id"].strip()
        row["lineage_id"], row["osmosis_id"] = e["lineage_id"].strip(), e.get("id")
        same = [x for x in links.find(target) if x["algo"] == row["algo"] and x["kind"] == "minted"
                and x.get("batch") == batch]
        if same:
            already += 1
            continue
        links.add(row["algo"], target, "minted", algo_hash=row.get("algo_hash"), seed=row.get("seed"), batch=batch)
        linked += 1
    if pairs:
        batchfile.write_atomic(path, batchfile.render(head, rows))
    return path, {"batch": batch, "path": str(path), "matched_by": how, "linked": linked,
                  "already_linked": already,
                  "problems": [dict(zip(("code", "message"), p.partition(": ")[::2])) for p in problems]}


def link(batch_ref, created: Any) -> Path:
    """Link a batch to a `create_questions` response and return the batch file's path. See `link_batch`."""
    return link_batch(batch_ref, created)[0]
