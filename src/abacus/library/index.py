"""The search index: a SQLite FTS5 cache of the library's META, at `<library>/.index.sqlite` (kit/06 s2).

Files are the truth; this is only a cache. `search` rebuilds it when it is missing, corrupt, from
another schema version or another kit version (what it indexes can change with the kit), or stale (a
file was added, removed, or changed). Link and usage counts are not stored here: they are read from
links.jsonl and usage.jsonl at query time. The problems of the last build (files it could not index)
are kept in the meta table, for `info`.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import abacus

from ..algo.loader import AlgoImportError, MetaError, load_algo
from . import links, store, usage

SCHEMA = "1"
SORTS = ("recent", "most_linked", "most_used", "id")
_TOKEN = re.compile(r"[^\W_]+")  # runs of letters and digits, which FTS5 cannot mistake for syntax


def index_path() -> Path:
    return store.library_dir() / ".index.sqlite"


def _connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path, timeout=30, isolation_level=None)


def _snapshot() -> dict[str, tuple[int, int]]:
    """relative path -> (mtime_ns, size) of every candidate algorithm file, broken ones included."""
    lib = store.library_dir()
    snap = {}
    for p in store.list_files():
        try:
            st = p.stat()
        except OSError:
            continue  # gone since the walk
        snap[p.relative_to(lib).as_posix()] = (st.st_mtime_ns, st.st_size)
    return snap


def _load_all() -> tuple[list[dict], dict[str, tuple[int, int]], list[str]]:
    """Load every algorithm file. Returns the rows to index, the file snapshot, and the problems."""
    lib = store.library_dir()
    rows, snap, problems = [], {}, []
    for p in store.list_files():
        rel = p.relative_to(lib).as_posix()
        try:
            st = p.stat()
        except OSError:
            continue
        snap[rel] = (st.st_mtime_ns, st.st_size)
        try:
            algo_id = store.path_to_id(p)
        except ValueError as e:
            problems.append(f"{rel}: {e}")
            continue
        try:
            algo = load_algo(p)
        except MetaError as e:
            problems.append(f"{rel}: bad META: " + "; ".join(e.problems))
            continue
        except AlgoImportError as e:
            problems.append(f"{rel}: {e}")
            continue
        except SystemExit as e:
            problems.append(f"{rel}: the file called sys.exit({e.code!r}) when imported")
            continue
        except Exception as e:  # noqa: BLE001 - one bad file must not stop the rest
            problems.append(f"{rel}: {type(e).__name__}: {e}")
            continue
        m = algo.meta
        if m["id"] != algo_id:
            problems.append(f"{rel}: META id {m['id']!r} does not match the id {algo_id!r} that its path gives")
            continue
        rows.append({"id": algo_id, "title": m["title"], "summary": m["summary"], "roles": m["roles"],
                     "tags": m["tags"], "techniques": m["techniques"], "answer_format": m["answer"]["format"],
                     "hash": algo.hash, "mtime_ns": snap[rel][0]})
    return rows, snap, problems


def _write(con: sqlite3.Connection, rows: list[dict], snap: dict[str, tuple[int, int]],
           problems: list[str]) -> None:
    con.execute("BEGIN IMMEDIATE")
    try:
        for table in ("fts", "facets", "algos", "files", "meta"):
            con.execute(f"DROP TABLE IF EXISTS {table}")
        con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.execute("CREATE TABLE files (relpath TEXT PRIMARY KEY, mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL)")
        con.execute("CREATE TABLE algos (rowid INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE, title TEXT NOT NULL,"
                    " summary TEXT NOT NULL, roles TEXT NOT NULL, tags TEXT NOT NULL, techniques TEXT NOT NULL,"
                    " answer_format TEXT NOT NULL, hash TEXT NOT NULL, mtime_ns INTEGER NOT NULL)")
        con.execute("CREATE TABLE facets (algo_id TEXT NOT NULL, kind TEXT NOT NULL,"
                    " value TEXT NOT NULL COLLATE NOCASE, PRIMARY KEY (algo_id, kind, value))")
        con.execute("CREATE INDEX facets_lookup ON facets (kind, value)")
        con.execute("CREATE VIRTUAL TABLE fts USING fts5(id, title, summary, tags, techniques,"
                    " tokenize = 'porter unicode61 remove_diacritics 2')")
        con.executemany("INSERT INTO meta VALUES (?, ?)", [("schema", SCHEMA), ("kit", abacus.__version__),
                                                           ("problems", json.dumps(problems))])
        con.executemany("INSERT INTO files VALUES (?, ?, ?)", [(rel, *v) for rel, v in snap.items()])
        for n, r in enumerate(rows, 1):
            con.execute("INSERT INTO algos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (n, r["id"], r["title"], r["summary"], json.dumps(r["roles"]), json.dumps(r["tags"]),
                         json.dumps(r["techniques"]), r["answer_format"], r["hash"], r["mtime_ns"]))
            con.execute("INSERT INTO fts (rowid, id, title, summary, tags, techniques) VALUES (?, ?, ?, ?, ?, ?)",
                        (n, r["id"], r["title"], r["summary"], " ".join(r["tags"]), " ".join(r["techniques"])))
            con.executemany("INSERT OR IGNORE INTO facets VALUES (?, ?, ?)",
                            [(r["id"], kind, v) for kind, key in (("role", "roles"), ("tag", "tags"),
                                                                  ("technique", "techniques")) for v in r[key]])
        con.execute("COMMIT")
    except BaseException:
        try:
            con.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise


def _rebuild() -> list[str]:
    rows, snap, problems = _load_all()
    path = index_path()
    for attempt in (1, 2):
        con = _connect(path)
        try:
            _write(con, rows, snap, problems)
            return problems
        except sqlite3.OperationalError:  # busy or read-only: not something to paper over
            raise
        except sqlite3.DatabaseError:  # the file is not a database: throw it away and start again
            if attempt == 2:
                raise
        finally:
            con.close()
        path.unlink(missing_ok=True)
    return problems  # pragma: no cover - the loop returns or raises


def rebuild() -> list[str]:
    """Rebuild the index from the files. Returns the problems found, one string per file that could
    not be indexed (it does not load, its META is bad, or its id does not match its path). Such files
    are skipped, never raised."""
    store.library_dir().mkdir(parents=True, exist_ok=True)
    return _rebuild()


def _is_fresh(con: sqlite3.Connection, snap: dict[str, tuple[int, int]]) -> bool:
    try:
        stamp = dict(con.execute("SELECT key, value FROM meta WHERE key IN ('schema', 'kit')"))
        if stamp.get("schema") != SCHEMA or stamp.get("kit") != abacus.__version__:
            return False
        stored = {rel: (m, s) for rel, m, s in con.execute("SELECT relpath, mtime_ns, size FROM files")}
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            return False
        raise
    return stored == snap


def _open_fresh() -> sqlite3.Connection:
    """A connection to an index that matches the files, rebuilding first if it does not."""
    path = index_path()
    snap = _snapshot()
    if path.exists():
        con = _connect(path)
        try:
            fresh = _is_fresh(con, snap)
        except sqlite3.OperationalError:
            con.close()
            raise
        except sqlite3.DatabaseError:  # not an index at all
            fresh = False
        except BaseException:
            con.close()
            raise
        if fresh:
            return con
        con.close()
    _rebuild()
    return _connect(path)


def info() -> dict:
    """What the search index covers: `indexed`, how many algorithms it holds, and `problems`, the files
    of the last build that were left out of it (as `rebuild` returned them). Rebuilds first if stale."""
    if not store.library_dir().is_dir():
        return {"indexed": 0, "problems": []}
    con = _open_fresh()
    try:
        indexed = con.execute("SELECT count(*) FROM algos").fetchone()[0]
        row = con.execute("SELECT value FROM meta WHERE key = 'problems'").fetchone()
    finally:
        con.close()
    return {"indexed": indexed, "problems": json.loads(row[0]) if row else []}


def search(query: str = "", *, role=None, tag=None, technique=None, answer_format=None,
           linked=None, unlinked=False, sort="id", limit=50) -> list[dict]:
    """Algorithms matching the text and every filter.

    `query` is full text over id, title, summary, tags and techniques: every word must match, and a
    word matches by prefix and stem. `role`, `tag`, `technique` and `answer_format` are exact (case
    does not matter). `linked` is a consumer prefix ('osmosis') or a full target; `unlinked` keeps
    algorithms with no link at all. `sort` is recent (file mtime, newest first), most_linked,
    most_used, or id; ties break by id. `limit` None means all.
    """
    if sort not in SORTS:
        raise ValueError(f"sort must be one of {list(SORTS)}, got {sort!r}")
    if not store.library_dir().is_dir():
        return []
    sql = ["SELECT a.id, a.title, a.summary, a.roles, a.tags, a.techniques, a.answer_format, a.hash, a.mtime_ns"
           " FROM algos a WHERE 1 = 1"]
    params: list = []
    tokens = _TOKEN.findall(query or "")
    if tokens:
        sql.append("AND a.rowid IN (SELECT rowid FROM fts WHERE fts MATCH ?)")
        params.append(" ".join(f'"{t}"*' for t in tokens))
    for kind, value in (("role", role), ("tag", tag), ("technique", technique)):
        if value is not None:
            sql.append("AND EXISTS (SELECT 1 FROM facets f WHERE f.algo_id = a.id AND f.kind = ? AND f.value = ?)")
            params += [kind, value]
    if answer_format is not None:
        sql.append("AND a.answer_format = ? COLLATE NOCASE")
        params.append(answer_format)
    con = _open_fresh()
    try:
        found = con.execute(" ".join(sql), params).fetchall()
    finally:
        con.close()

    link_counts, use_counts = links.counts(), usage.counts()
    linked_algos = None if linked is None else {r["algo"] for r in links.list_links(consumer=linked)}
    out = []
    for algo_id, title, summary, roles, tags, techniques, fmt, h, mtime_ns in found:
        n_links = link_counts.get(algo_id, 0)
        if linked_algos is not None and algo_id not in linked_algos:
            continue
        if unlinked and n_links:
            continue
        out.append((mtime_ns, {"id": algo_id, "title": title, "summary": summary, "roles": json.loads(roles),
                               "tags": json.loads(tags), "techniques": json.loads(techniques),
                               "answer_format": fmt, "hash": h, "links": n_links,
                               "uses": use_counts.get(algo_id, 0)}))
    keys = {"id": lambda m, r: r["id"],
            "recent": lambda m, r: (-m, r["id"]),
            "most_linked": lambda m, r: (-r["links"], r["id"]),
            "most_used": lambda m, r: (-r["uses"], r["id"])}
    out.sort(key=lambda mr: keys[sort](*mr))
    rows = [r for _, r in out]
    return rows if limit is None else rows[:max(limit, 0)]
