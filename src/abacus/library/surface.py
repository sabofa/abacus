"""Buttons that expose the algorithm library to the MCP surface and the registry (not spec buttons):
`algo_search`, `algo_show`, `link_add`, `link_rm`, `link_find` (kit/06 s2, s3).

Each returns Evidence. A bad id, target or kind, or a missing algorithm, is a flagged Evidence with no
result, never an exception.
"""
from __future__ import annotations

import sqlite3

from .. import registry
from ..algo.loader import AlgoImportError, MetaError
from ..evidence import Evidence
from . import index, links, store, usage

_STR = {"type": "string"}


def show_record(algo_id: str) -> dict:
    """What the library knows of one algorithm: its hash, path and META, its links and its usage count.
    Raises what `store.read` raises (ValueError for a bad id, NoSuchAlgo, MetaError, AlgoImportError)."""
    algo = store.read(algo_id)
    return {"hash": algo.hash, "path": str(algo.path), "meta": algo.meta,
            "links": links.list_links(algo=algo_id), "uses": usage.counts().get(algo_id, 0)}


def _fail(button: str, code: str, msg: str, scope: str) -> Evidence:
    ev = Evidence(button=button, result=None, method="timed", scope=scope, complete=False)
    ev.flag(code, msg)
    return ev


@registry.button(
    "algo_search",
    description="Search the algorithm library: full text over id, title, summary, tags and techniques (every "
                "word must match), plus exact filters role, tag, technique, answer_format; `linked` (a consumer "
                "such as 'osmosis', or one full target) and `unlinked`; sort by id, recent, most_linked or "
                "most_used. Returns a list of {id, title, summary, roles, tags, techniques, answer_format, "
                "hash, links, uses}.",
    input_schema={
        "type": "object",
        "properties": {
            "query": _STR, "role": _STR, "tag": _STR, "technique": _STR, "answer_format": _STR, "linked": _STR,
            "unlinked": {"type": "boolean"},
            "sort": {"enum": list(index.SORTS)},
            "limit": {"type": "integer", "minimum": 1},
        },
    },
    default_time_s=60,
)
def algo_search(inp: dict, ctx) -> Evidence:
    limit = inp.get("limit", 50)
    try:
        found = index.search(inp.get("query") or "", role=inp.get("role"), tag=inp.get("tag"),
                             technique=inp.get("technique"), answer_format=inp.get("answer_format"),
                             linked=inp.get("linked"), unlinked=bool(inp.get("unlinked")),
                             sort=inp.get("sort", "id"), limit=limit)
    except ValueError as e:
        return _fail("algo_search", "bad_input", str(e), "input rejected before searching")
    except sqlite3.Error as e:
        return _fail("algo_search", "index_error", f"{type(e).__name__}: {e}",
                     "the search index could not be read; `abacus index rebuild` makes a new one")
    lib = store.library_dir()
    ev = Evidence(button="algo_search", result=found, method="search",
                  scope=f"searched {len(store.list_files())} algorithms in {lib}; {len(found)} matched")
    if len(found) >= limit:
        ev.notes.append(f"{len(found)} results is the limit; raise limit if there may be more")
    return ev


@registry.button(
    "algo_show",
    description="Show one library algorithm by id: its hash, file path and META header, every link to it, "
                "and how many role runs are recorded for it.",
    input_schema={"type": "object", "properties": {"id": _STR}, "required": ["id"]},
    default_time_s=30,
)
def algo_show(inp: dict, ctx) -> Evidence:
    algo_id = inp["id"]
    try:
        rec = show_record(algo_id)
    except store.NoSuchAlgo as e:  # before AlgoImportError and ValueError, which it is not a kind of
        return _fail("algo_show", "no_such_algo", str(e), "no algorithm with this id is in the library")
    except MetaError as e:  # a ValueError, so before the bad id case
        return _fail("algo_show", "bad_meta", str(e), "the algorithm's META is invalid")
    except AlgoImportError as e:
        return _fail("algo_show", "import_error", str(e), "the algorithm file could not be imported")
    except ValueError as e:
        return _fail("algo_show", "bad_input", str(e), "input rejected before looking")
    return Evidence(button="algo_show", result=rec, method="search",
                    scope=f"the library's record of {algo_id} [{rec['hash']}]: header, links and usage count")


@registry.button(
    "link_add",
    description="Tie an algorithm to one item in a consumer: target is '<consumer>:<kind>:<id>', such as "
                "'osmosis:q:6b1f0a'; kind is minted (made from the algorithm), checks (the algorithm checks "
                "an item it did not make) or family. Appends one line to links.jsonl. The optional seed is the "
                "one the item was generated with.",
    input_schema={
        "type": "object",
        "properties": {
            "algo": _STR, "target": _STR, "kind": {"enum": list(links.KINDS)}, "algo_hash": _STR,
            "seed": {"type": "integer", "minimum": 0}, "batch": _STR,
        },
        "required": ["algo", "target", "kind"],
    },
    default_time_s=10,
)
def link_add(inp: dict, ctx) -> Evidence:
    try:
        rec = links.add(inp["algo"], inp["target"], inp["kind"], algo_hash=inp.get("algo_hash"),
                        seed=inp.get("seed"), batch=inp.get("batch"))
    except ValueError as e:
        return _fail("link_add", "bad_input", str(e), "input rejected; nothing was written")
    return Evidence(button="link_add", result=rec, method="timed",
                    scope=f"appended one {rec['kind']} link from {rec['algo']} to {rec['target']} "
                          f"in {links.links_path()}")


@registry.button(
    "link_rm",
    description="Remove every link between one algorithm and one target from links.jsonl. Returns how many "
                "lines went. It never touches the algorithm or the consumer's item.",
    input_schema={"type": "object", "properties": {"algo": _STR, "target": _STR}, "required": ["algo", "target"]},
    default_time_s=10,
)
def link_rm(inp: dict, ctx) -> Evidence:
    n = links.rm(inp["algo"], inp["target"])
    return Evidence(button="link_rm", result={"removed": n}, method="timed",
                    scope=f"removed {n} link(s) from {inp['algo']} to {inp['target']} in {links.links_path()}")


@registry.button(
    "link_find",
    description="Reverse lookup: every link to exactly this target ('<consumer>:<kind>:<id>'), which tells "
                "which algorithm made or checks an item.",
    input_schema={"type": "object", "properties": {"target": _STR}, "required": ["target"]},
    default_time_s=10,
)
def link_find(inp: dict, ctx) -> Evidence:
    found = links.find(inp["target"])
    return Evidence(button="link_find", result=found, method="search",
                    scope=f"searched {len(links.list_links())} links in {links.links_path()} "
                          f"for the target {inp['target']}; {len(found)} found")
