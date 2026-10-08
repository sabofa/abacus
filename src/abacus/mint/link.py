"""`abacus mint link`: pair a consumer's creation response with a batch's kept instances and write links (kit/07 s5).

The consumer's adapter (`adapters/osmosis.py` for Osmosis) turns the response into neutral entries,
`{remote_id, target, preview}`: the id the consumer gave the item, the link target (`<consumer>:<kind>:<id>`)
and the start of its prompt. This module knows nothing else about the response.

Entries are paired with the kept instances (decision `keep`, in index order) by order, when there are as many
entries as instances and every preview agrees with its instance's statement. Otherwise each entry is matched
on its preview, and an entry whose preview fits more than one free instance is reported as `ambiguous` and
not linked. Whatever cannot be paired is reported, never guessed.

Each pair gets one `minted` link to the entry's target (with the algorithm's hash, the instance's seed and the
batch id), and the batch row records `remote_id` and `target`. An instance already linked to that target is
left as it is. An instance already linked to a different target keeps its first link: the new entry is
reported as `relinked_conflict` and nothing is written for it. So an instance never has two minted links.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..adapters import osmosis
from ..library import links
from ..library._jsonl import file_lock
from . import batchfile
from .review import KEEP

BAD_ENTRY, COUNT_MISMATCH, NO_MATCH, UNMATCHED = "bad_entry", "count_mismatch", "no_match", "unmatched_instance"
AMBIGUOUS, RELINKED_CONFLICT, BAD_TARGET = "ambiguous", "relinked_conflict", "bad_target"
KIND = "minted"


def _norm(text: Any) -> str:
    return " ".join(str(text or "").split())


def _preview(entry: dict) -> str:
    """The entry's preview with the ellipsis a truncation leaves removed."""
    text = _norm(entry.get("preview"))
    for tail in ("…", "..."):
        if text.endswith(tail):
            text = text[:-len(tail)].rstrip()
    return text


def _agrees(entry: dict, row: dict) -> bool:
    """True when the entry's preview is the start of the instance's statement (or the whole of it); an
    entry with no preview agrees with anything, as it has nothing to disagree with."""
    p = _preview(entry)
    return not p or _norm(row.get("statement")).startswith(p)


def load_response(created: Any) -> Any:
    """A response given as a dict, a list, a JSON string, or the path of a JSON file, as parsed JSON."""
    if isinstance(created, (str, Path)):
        text = str(created)
        if text.lstrip().startswith(("{", "[")):
            return json.loads(text)
        return json.loads(Path(text).read_text(encoding="utf-8-sig"))
    return created


def _label(n: int, entry: dict) -> str:
    return f"entry {n} ({entry.get('target')})"


def _fits(entry: dict, free: list[dict]) -> list[dict]:
    """The free instances a preview could belong to. An entry with no preview fits none: it says nothing."""
    return [r for r in free if _preview(entry) and _agrees(entry, r)]


def _pair_by_prompt(entries: list[tuple[int, dict]], kept: list[dict],
                    problems: list[str]) -> list[tuple[dict, dict]]:
    """Pair on previews. An entry that fits exactly one free instance, and that no other entry wants, takes
    it; this repeats while it makes progress. What is left is `ambiguous` (it fits several instances, or its
    one instance is wanted by another entry too) or `no_match`."""
    free, todo, pairs = list(kept), list(entries), []
    while todo:
        fit = {n: _fits(e, free) for n, e in todo}
        wanted: dict[int, int] = {}
        for rs in fit.values():
            if len(rs) == 1:
                wanted[rs[0]["index"]] = wanted.get(rs[0]["index"], 0) + 1
        took = [(n, e) for n, e in todo if len(fit[n]) == 1 and wanted[fit[n][0]["index"]] == 1]
        if not took:
            break
        for n, e in took:
            row = fit[n][0]
            free.remove(row)
            todo.remove((n, e))
            pairs.append((e, row))
    for n, e in todo:
        rs = _fits(e, free)
        if rs:
            idx = ", ".join(str(r["index"]) for r in rs)
            why = "another entry fits it too" if len(rs) == 1 else "its preview fits all of them"
            problems.append(f"{AMBIGUOUS}: {_label(n, e)} could be instance {idx}: {why}; it was not linked")
        else:
            problems.append(f"{NO_MATCH}: {_label(n, e)} matches no kept instance")
    for r in free:
        problems.append(f"{UNMATCHED}: instance {r['index']} was not paired with any entry")
    return pairs


def _pair(entries: list[tuple[int, dict]], kept: list[dict],
          problems: list[str]) -> tuple[list[tuple[dict, dict]], str]:
    """(entry, row) pairs and how they were made: 'order' or 'prompt'."""
    if len(entries) == len(kept) and all(_agrees(e, r) for (_, e), r in zip(entries, kept)):
        return [(e, r) for (_, e), r in zip(entries, kept)], "order"
    if len(entries) != len(kept):
        problems.append(f"{COUNT_MISMATCH}: the response has {len(entries)} entries and the batch has "
                        f"{len(kept)} kept instances, so entries were matched on their previews")
    else:
        problems.append(f"{NO_MATCH}: an entry's preview does not start its instance's statement, "
                        "so entries were matched on their previews instead of by order")
    return _pair_by_prompt(entries, kept, problems), "prompt"


def _existing_targets(row: dict, batch: str) -> set[str]:
    """The targets this instance (same algorithm, batch and seed) already has a minted link to."""
    found = {x["target"] for x in links.list_links(algo=row["algo"])
             if x["kind"] == KIND and x.get("batch") == batch and x.get("seed") == row.get("seed")}
    if isinstance(row.get("target"), str):
        found.add(row["target"])
    return found


def link_batch(batch_ref, created: Any) -> tuple[Path, dict]:
    """Write the links and record the targets in the batch file. Returns its path and a summary:
    `{batch, path, matched_by, linked, already_linked, problems: [{code, message}]}`.

    ValueError for a response that is not a `created` list (nothing is written); NoSuchBatch and BadBatch as
    for `review`. A malformed entry, a count mismatch, an unpaired instance, an ambiguous entry and a
    conflict with an earlier link are reported as problems. Every target is checked before anything is
    written, and the batch file is held under the lock `review` takes.
    """
    entries = osmosis.parse_created(load_response(created))
    path = batchfile.resolve(batch_ref)
    with file_lock(path):
        return _link_locked(path, entries)


def _link_locked(path: Path, entries: list[dict]) -> tuple[Path, dict]:
    head, rows = batchfile.read(path)
    batch = batchfile.batch_id(path, head)
    kept = sorted((r for r in rows if r.get("decision", KEEP) == KEEP), key=lambda r: r["index"])

    problems: list[str] = []
    good: list[tuple[int, dict]] = []
    for n, e in enumerate(entries, start=1):
        if e["target"]:
            good.append((n, e))
        else:
            problems.append(f"{BAD_ENTRY}: entry {n} has no link target, so it was skipped")
    pairs, how = _pair(good, kept, problems)

    todo, already = [], 0
    for e, row in pairs:
        try:
            links.validate(row["algo"], e["target"], KIND)
        except ValueError as err:
            problems.append(f"{BAD_TARGET}: {err}")
            continue
        have = _existing_targets(row, batch)
        if e["target"] in have:
            already += 1
            row["remote_id"], row["target"] = e["remote_id"], e["target"]
        elif have:
            problems.append(f"{RELINKED_CONFLICT}: instance {row['index']} is already linked to "
                            f"{', '.join(sorted(have))}; the new entry's target {e['target']} was not linked")
        else:
            todo.append((e, row))

    for e, row in todo:
        links.add(row["algo"], e["target"], KIND, algo_hash=row.get("algo_hash"), seed=row.get("seed"), batch=batch)
        row["remote_id"], row["target"] = e["remote_id"], e["target"]
    if todo or already:
        batchfile.write_atomic(path, batchfile.render(head, rows))
    return path, {"batch": batch, "path": str(path), "matched_by": how, "linked": len(todo),
                  "already_linked": already,
                  "problems": [dict(zip(("code", "message"), p.partition(": ")[::2])) for p in problems]}


def link(batch_ref, created: Any) -> Path:
    """Link a batch to a creation response and return the batch file's path. See `link_batch`."""
    return link_batch(batch_ref, created)[0]
