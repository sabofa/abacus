"""The library store (ids, paths, read, write) and the derived search index (kit/06 s1, s2)."""
import os
import sqlite3
from pathlib import Path

import pytest

from abacus.algo.loader import AlgoImportError, MetaError, algo_hash, load_algo
from abacus.library import index, links, store, usage

FIX = Path(__file__).parent / "fixtures" / "algos"
FAM_SRC = (FIX / "nt_power_mod.py").read_text(encoding="utf-8")
ONE_SRC = (FIX / "one_off.py").read_text(encoding="utf-8")
FAM_ID = load_algo(FIX / "nt_power_mod.py").meta["id"]  # nt.power-mod
ONE_ID = load_algo(FIX / "one_off.py").meta["id"]  # misc.one-off-sum


def algo_src(algo_id, title="A title", summary="A summary.", roles=("compute",), tags=(),
             techniques=(), fmt="integer"):
    meta = {"id": algo_id, "title": title, "summary": summary, "roles": list(roles), "tags": list(tags),
            "techniques": list(techniques), "answer": {"format": fmt}}
    return f"META = {meta!r}\n\n\ndef compute(params):\n    return 1\n"


@pytest.fixture
def lib(tmp_path, monkeypatch):
    d = tmp_path / "lib"
    monkeypatch.setenv("ABACUS_LIBRARY", str(d))
    return d


@pytest.fixture
def two(lib):
    """The two fixture algorithms, each written at the path matching its id."""
    store.write(FAM_ID, FAM_SRC)
    store.write(ONE_ID, ONE_SRC)
    return lib


def ids(rows):
    return [r["id"] for r in rows]


def set_mtime(algo_id, ns):
    p = store.id_to_path(algo_id)
    os.utime(p, ns=(ns, ns))


# ---- store: ids and paths ----------------------------------------------------

def test_id_to_path_and_back(lib):
    p = store.id_to_path("nt.last-three-digits-of-tower")
    assert p == lib / "nt" / "last-three-digits-of-tower.py"
    assert store.path_to_id(p) == "nt.last-three-digits-of-tower"
    deep = store.id_to_path("nt.sub.x1")
    assert deep == lib / "nt" / "sub" / "x1.py" and store.path_to_id(deep) == "nt.sub.x1"


def test_path_to_id_takes_relative_paths_from_the_library(lib):
    assert store.path_to_id(Path("nt") / "power-mod.py") == "nt.power-mod"
    assert store.path_to_id("nt/power-mod.py") == "nt.power-mod"


def test_path_to_id_refuses_paths_that_are_not_algorithms(lib, tmp_path):
    for bad in (tmp_path / "elsewhere" / "x.py", lib / "nt" / "power-mod.txt", lib / "nt" / "Power_Mod.py",
                lib / "nt" / "_private.py", lib / "top.py", lib / ".." / "x" / "y.py", lib):
        with pytest.raises(ValueError):
            store.path_to_id(bad)


@pytest.mark.parametrize("bad", [
    "", "nt", "Nt.x", "nt.X", "nt.x_y", "nt..x", ".nt.x", "nt.x.", "-nt.x", "nt.-x", "nt/x", "nt.x/../y",
    "nt\\x", "nt.x y", "nt.x\n", "batches.x", "nt.con", "nt.NUL", "aux.x", "nt.com1", "nt.é", None, 7,
])
def test_a_bad_id_raises(lib, bad):
    with pytest.raises(ValueError):
        store.id_to_path(bad)
    with pytest.raises(ValueError):
        store.write(bad, algo_src("nt.x"))
    assert not lib.exists()


@pytest.mark.parametrize("good", ["nt.x", "a1.b2", "nt.last-three-digits-of-tower", "0.1", "a.b.c.d", "nt.x-"])
def test_good_ids(lib, good):
    assert store.path_to_id(store.id_to_path(good)) == good


# ---- store: list, read, write -------------------------------------------------

def test_list_ids_skips_batches_and_private_names(lib):
    for algo_id in ("nt.b-one", "nt.a-one", "examples.demo", "comb.deep.x"):
        store.write(algo_id, algo_src(algo_id))
    (lib / "batches" / "2026-09-26").mkdir(parents=True)
    (lib / "batches" / "2026-09-26" / "inst.py").write_text(algo_src("nt.in-batch"))
    (lib / "batches" / "plain.py").write_text(algo_src("nt.in-batch2"))
    (lib / "nt" / "_helper.py").write_text("X = 1\n")
    (lib / "nt" / ".hidden.py").write_text(algo_src("nt.hidden"))
    (lib / "_scratch").mkdir()
    (lib / "_scratch" / "x.py").write_text(algo_src("nt.scratch"))
    (lib / ".git").mkdir()
    (lib / ".git" / "y.py").write_text(algo_src("nt.git"))
    (lib / "nt" / "__pycache__").mkdir()
    (lib / "nt" / "__pycache__" / "a-one.cpython-314.pyc").write_bytes(b"\x00")
    (lib / "nt" / "notes.txt").write_text("hello")
    (lib / "links.jsonl").write_text("")
    assert store.list_ids() == ["comb.deep.x", "examples.demo", "nt.a-one", "nt.b-one"]


def test_list_ids_of_a_missing_or_empty_library(lib):
    assert store.list_ids() == []
    lib.mkdir()
    assert store.list_ids() == []


def test_write_creates_directories_and_returns_the_path(lib):
    p = store.write("nt.new-one", "META = 1\n")
    assert p == lib / "nt" / "new-one.py" and p.read_text() == "META = 1\n"


def test_write_keeps_the_source_byte_for_byte(lib):
    src = "# café\r\nX = 1\r\n"
    p = store.write("nt.bytes", src)
    assert p.read_bytes() == src.encode("utf-8")


def test_write_refuses_to_overwrite_unless_asked(lib):
    p = store.write("nt.once", "A = 1\n")
    with pytest.raises(FileExistsError):
        store.write("nt.once", "A = 2\n")
    assert p.read_text() == "A = 1\n"
    assert store.write("nt.once", "A = 2\n", overwrite=True) == p
    assert p.read_text() == "A = 2\n"
    assert sorted(x.name for x in p.parent.iterdir()) == ["once.py"]  # no temp file left behind


def test_read_loads_the_algorithm(two):
    a = store.read(FAM_ID)
    assert a.meta["id"] == FAM_ID and callable(a.module.generate)
    assert a.path == store.id_to_path(FAM_ID).resolve()
    assert a.hash == algo_hash(store.id_to_path(FAM_ID))


def test_read_of_a_missing_algorithm(lib):
    with pytest.raises(AlgoImportError) as ei:
        store.read("nt.nothing-here")
    assert isinstance(ei.value, FileNotFoundError) and "nt.nothing-here" in str(ei.value)


def test_read_lets_a_broken_file_raise_the_loaders_error(lib):
    store.write("nt.bad-meta", "META = {'id': 'nt.bad-meta'}\n")
    with pytest.raises(MetaError):
        store.read("nt.bad-meta")
    store.write("nt.bad-code", "raise RuntimeError('boom')\n")
    with pytest.raises(AlgoImportError):
        store.read("nt.bad-code")


# ---- index: rebuild and search ------------------------------------------------

def test_two_fixture_algorithms_index_and_are_found_by_title_word_and_tag(two):
    assert index.rebuild() == []
    assert (two / ".index.sqlite").is_file()
    assert ids(index.search("fixed")) == [ONE_ID]  # title word of the one-off
    assert ids(index.search("remainder")) == []  # not in any indexed field
    assert ids(index.search("number-theory")) == [FAM_ID]  # a tag
    assert ids(index.search("modular")) == [FAM_ID]
    assert ids(index.search("mod")) == [FAM_ID]  # title word and id fragment
    assert ids(index.search("")) == sorted([FAM_ID, ONE_ID])


def test_a_result_row_carries_the_listed_fields(two):
    row, = index.search("fixed")
    assert row == {"id": ONE_ID, "title": "A fixed sum", "summary": "One fixed problem with no knobs.",
                   "roles": ["generate", "compute"], "tags": [], "techniques": [],
                   "answer_format": "integer", "hash": algo_hash(store.id_to_path(ONE_ID)),
                   "links": 0, "uses": 0}
    fam, = index.search("power")
    assert fam["tags"] == ["number-theory", "modular-arithmetic"] and fam["techniques"] == ["fast-exponentiation"]
    assert fam["roles"] == ["generate", "compute", "check", "hand_space"]


def test_full_text_covers_id_title_summary_tags_and_techniques(lib):
    store.write("zz.alpha", algo_src("zz.alpha", title="Gizmo", summary="Frobnicates widgets",
                                     tags=["quartz-tag"], techniques=["sieve-of-eratosthenes"]))
    store.write("zz.beta", algo_src("zz.beta", title="Other", summary="Nothing relevant"))
    for q in ("alpha", "gizmo", "frobnicates", "widgets", "quartz", "quartz-tag", "sieve", "eratosthenes",
              "ALPHA", "Sieve Of", "gizmo widgets", "widget", "frobnicate"):
        assert ids(index.search(q)) == ["zz.alpha"], q
    assert ids(index.search("gizmo nothing")) == []  # every word must match
    assert ids(index.search("zz")) == ["zz.alpha", "zz.beta"]


@pytest.mark.parametrize("q", ['a-b "c" OR (d', "NEAR(", "x*", "^", "title:gizmo", "AND", '"', "'; DROP TABLE algos;--",
                               "   ", "—", "a:b:c"])
def test_search_text_is_never_taken_as_fts_syntax(two, q):
    index.search(q)  # must not raise


def test_filters(two):
    assert ids(index.search(role="check")) == [FAM_ID]
    assert ids(index.search(role="generate")) == sorted([FAM_ID, ONE_ID])
    assert ids(index.search(role="hand_space")) == [FAM_ID]
    assert index.search(role="solution") == []
    assert ids(index.search(tag="modular-arithmetic")) == [FAM_ID]
    assert ids(index.search(tag="Modular-Arithmetic")) == [FAM_ID]
    assert index.search(tag="modular") == []  # a filter is exact, unlike text
    assert ids(index.search(technique="fast-exponentiation")) == [FAM_ID]
    assert ids(index.search(answer_format="integer")) == sorted([FAM_ID, ONE_ID])
    assert index.search(answer_format="set") == []
    assert ids(index.search("power", role="check", tag="number-theory", answer_format="integer")) == [FAM_ID]
    assert index.search("fixed", role="check") == []


def test_linked_and_unlinked(two):
    links.add(FAM_ID, "osmosis:q:aaa", "minted")
    links.add(FAM_ID, "osmosis:q:bbb", "minted")
    links.add(ONE_ID, "other:q:ccc", "checks")
    assert ids(index.search(linked="osmosis")) == [FAM_ID]
    assert ids(index.search(linked="other")) == [ONE_ID]
    assert ids(index.search(linked="osmosis:q:bbb")) == [FAM_ID]
    assert index.search(linked="osmosis:q:zzz") == []
    assert index.search(linked="osmos") == []
    assert index.search(unlinked=True) == []
    links.rm(ONE_ID, "other:q:ccc")
    assert ids(index.search(unlinked=True)) == [ONE_ID]
    assert ids(index.search(linked="osmosis", unlinked=True)) == []
    assert {r["id"]: r["links"] for r in index.search()} == {FAM_ID: 2, ONE_ID: 0}


def test_sorts(lib):
    for algo_id in ("a.one", "b.two", "c.three"):
        store.write(algo_id, algo_src(algo_id))
    set_mtime("a.one", 1_000_000_000_000_000_000)
    set_mtime("b.two", 3_000_000_000_000_000_000)
    set_mtime("c.three", 2_000_000_000_000_000_000)
    links.add("a.one", "x:q:1", "minted")
    links.add("c.three", "x:q:2", "minted")
    links.add("c.three", "x:q:3", "minted")
    for _ in range(3):
        usage.record("b.two", "compute", 0.1, True)
    usage.record("a.one", "compute", 0.1, True)
    assert ids(index.search(sort="id")) == ["a.one", "b.two", "c.three"]
    assert ids(index.search(sort="recent")) == ["b.two", "c.three", "a.one"]
    assert ids(index.search(sort="most_linked")) == ["c.three", "a.one", "b.two"]
    assert ids(index.search(sort="most_used")) == ["b.two", "a.one", "c.three"]
    by_id = {r["id"]: r for r in index.search()}
    assert (by_id["c.three"]["links"], by_id["b.two"]["uses"], by_id["b.two"]["links"]) == (2, 3, 0)


def test_sort_ties_break_by_id(lib):
    for algo_id in ("a.one", "b.two", "c.three"):
        store.write(algo_id, algo_src(algo_id))
    for algo_id in ("a.one", "b.two", "c.three"):
        set_mtime(algo_id, 5_000_000_000_000_000_000)
    assert ids(index.search(sort="recent")) == ["a.one", "b.two", "c.three"]
    assert ids(index.search(sort="most_linked")) == ["a.one", "b.two", "c.three"]
    assert ids(index.search(sort="most_used")) == ["a.one", "b.two", "c.three"]


def test_a_bad_sort_raises(two):
    with pytest.raises(ValueError):
        index.search(sort="newest")


def test_limit(lib):
    for n in range(5):
        store.write(f"a.x{n}", algo_src(f"a.x{n}"))
    assert ids(index.search(limit=2)) == ["a.x0", "a.x1"]
    assert len(index.search()) == 5 and index.search(limit=0) == []
    assert len(index.search(limit=None)) == 5


def test_counts_are_read_at_query_time_not_from_the_index(two):
    index.rebuild()
    before = (two / ".index.sqlite").stat().st_mtime_ns
    links.add(FAM_ID, "osmosis:q:aaa", "minted")
    usage.record(FAM_ID, "compute", 0.1, True)
    usage.record(FAM_ID, "compute", 0.1, True)
    row, = index.search("power")
    assert (row["links"], row["uses"]) == (1, 2)
    assert (two / ".index.sqlite").stat().st_mtime_ns == before  # no rebuild was needed


# ---- index: broken files, staleness --------------------------------------------

def test_a_broken_file_is_reported_and_skipped(two):
    (two / "bad").mkdir()
    (two / "bad" / "syntax.py").write_text("def (:\n")
    (two / "bad" / "meta.py").write_text("META = {'id': 'bad.meta'}\n")
    (two / "bad" / "boom.py").write_text("raise RuntimeError('kaboom')\n")
    (two / "bad" / "exits.py").write_text("import sys\nsys.exit(3)\n")
    (two / "bad" / "elsewhere.py").write_text(algo_src("nt.not-where-it-lives"))
    (two / "bad" / "Mixed_Name.py").write_text(algo_src("bad.mixed-name"))
    problems = index.rebuild()
    assert len(problems) == 6
    text = "\n".join(problems)
    for frag in ("syntax.py", "meta.py", "boom.py", "kaboom", "exits.py", "elsewhere.py", "nt.not-where-it-lives",
                 "Mixed_Name.py"):
        assert frag in text, frag
    assert ids(index.search("")) == sorted([FAM_ID, ONE_ID])  # the broken ones are skipped, the rest found


def test_a_broken_file_does_not_make_every_search_rebuild(two):
    (two / "bad").mkdir()
    (two / "bad" / "syntax.py").write_text("def (:\n")
    index.rebuild()
    before = (two / ".index.sqlite").stat().st_mtime_ns
    index.search("fixed")
    index.search("power")
    assert (two / ".index.sqlite").stat().st_mtime_ns == before


def test_search_builds_a_missing_index(two):
    assert not (two / ".index.sqlite").exists()
    assert ids(index.search("fixed")) == [ONE_ID]
    assert (two / ".index.sqlite").is_file()


def test_adding_a_file_triggers_a_rebuild(two):
    assert ids(index.search("gizmo")) == []
    store.write("zz.new", algo_src("zz.new", title="Gizmo"))
    assert ids(index.search("gizmo")) == ["zz.new"]


def test_removing_a_file_triggers_a_rebuild(two):
    assert ids(index.search("fixed")) == [ONE_ID]
    store.id_to_path(ONE_ID).unlink()
    assert index.search("fixed") == []
    assert ids(index.search("")) == [FAM_ID]


def test_editing_a_file_triggers_a_rebuild(lib):
    p = store.write("zz.edit", algo_src("zz.edit", title="Alpha"))
    old = p.stat().st_mtime_ns
    assert ids(index.search("alpha")) == ["zz.edit"]
    p.write_bytes(algo_src("zz.edit", title="Omega").encode())  # same length
    os.utime(p, ns=(old + 2_000_000_000, old + 2_000_000_000))
    assert index.search("alpha") == [] and ids(index.search("omega")) == ["zz.edit"]


def test_touching_a_file_updates_recent(lib):
    for algo_id in ("a.one", "b.two"):
        store.write(algo_id, algo_src(algo_id))
    set_mtime("a.one", 1_000_000_000_000_000_000)
    set_mtime("b.two", 2_000_000_000_000_000_000)
    assert ids(index.search(sort="recent")) == ["b.two", "a.one"]
    set_mtime("a.one", 3_000_000_000_000_000_000)
    assert ids(index.search(sort="recent")) == ["a.one", "b.two"]


def test_a_file_that_gets_fixed_comes_back(lib):
    store.write("zz.fix", "META = {'id': 'zz.fix'}\n")
    assert len(index.rebuild()) == 1 and index.search("") == []
    store.write("zz.fix", algo_src("zz.fix"), overwrite=True)
    assert ids(index.search("")) == ["zz.fix"]


def test_a_deleted_or_corrupt_index_is_rebuilt(two):
    index.rebuild()
    (two / ".index.sqlite").unlink()
    assert ids(index.search("fixed")) == [ONE_ID]
    (two / ".index.sqlite").write_bytes(b"this is not a sqlite database" * 100)
    assert ids(index.search("fixed")) == [ONE_ID]


def test_an_index_from_another_schema_version_is_rebuilt(two):
    index.rebuild()
    con = sqlite3.connect(two / ".index.sqlite")
    con.execute("UPDATE meta SET value = '0' WHERE key = 'schema'")
    con.commit()
    con.close()
    assert ids(index.search("fixed")) == [ONE_ID]
    con = sqlite3.connect(two / ".index.sqlite")
    try:
        assert con.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()[0] != "0"
    finally:
        con.close()


def test_files_outside_the_algorithm_set_do_not_trigger_a_rebuild(two):
    index.rebuild()
    before = (two / ".index.sqlite").stat().st_mtime_ns
    (two / "batches").mkdir()
    (two / "batches" / "x.py").write_text("raise SystemExit\n")
    (two / "_x.py").write_text("raise SystemExit\n")
    (two / "notes.md").write_text("hi")
    links.add(FAM_ID, "osmosis:q:aaa", "minted")
    usage.record(FAM_ID, "compute", 0.1, True)
    assert ids(index.search("")) == sorted([FAM_ID, ONE_ID])
    assert (two / ".index.sqlite").stat().st_mtime_ns == before


def test_a_missing_library_searches_empty_and_is_not_created(lib):
    assert index.search("anything") == []
    assert not lib.exists()


def test_rebuild_of_an_empty_library(lib):
    assert index.rebuild() == []
    assert index.search("") == []


# ---- a relative ABACUS_LIBRARY, quiet imports, the kit version ----------------

def test_a_relative_library_indexes_and_searches(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ABACUS_LIBRARY", "rel-lib")
    assert store.library_dir().is_absolute()
    assert store.library_dir().resolve() == (tmp_path / "rel-lib").resolve()
    store.write(FAM_ID, FAM_SRC)
    store.write(ONE_ID, ONE_SRC)
    assert index.rebuild() == []  # not "META id 'nt.power-mod' does not match the id 'rel-lib.nt.power-mod'"
    assert ids(index.search("")) == sorted([FAM_ID, ONE_ID])
    assert store.path_to_id("nt/power-mod.py") == FAM_ID  # a relative path is taken from the library
    assert store.path_to_id(store.id_to_path(FAM_ID)) == FAM_ID
    assert store.list_ids() == sorted([FAM_ID, ONE_ID])


PRINTING_SRC = "print('hello from import')\n" + algo_src("zz.chatty", title="Chatty")


def test_import_time_prints_do_not_reach_stdout(lib, capsys):
    store.write("zz.chatty", PRINTING_SRC)
    store.write(ONE_ID, ONE_SRC)
    capsys.readouterr()
    assert index.rebuild() == []
    assert ids(index.search("chatty")) == ["zz.chatty"]
    store.read("zz.chatty")
    out, err = capsys.readouterr()
    assert out == ""
    assert "hello from import" in err  # kept, but on stderr


def _stamp_of(path):
    con = sqlite3.connect(path)
    try:
        return dict(con.execute("SELECT key, value FROM meta"))
    finally:
        con.close()


def test_a_new_kit_version_rebuilds_the_index(two, monkeypatch):
    import abacus
    index.rebuild()
    old = _stamp_of(two / ".index.sqlite")
    assert abacus.__version__ in "".join(old.values())
    before = (two / ".index.sqlite").stat().st_mtime_ns
    assert ids(index.search("fixed")) == [ONE_ID]
    assert (two / ".index.sqlite").stat().st_mtime_ns == before  # same version: still fresh
    monkeypatch.setattr(abacus, "__version__", "9.9.9")
    assert ids(index.search("fixed")) == [ONE_ID]
    assert "9.9.9" in "".join(_stamp_of(two / ".index.sqlite").values())  # rebuilt under the new version


# ---- the problems of the last build ---------------------------------------------

def test_info_counts_indexed_rows_and_keeps_the_problems(two):
    (two / "bad").mkdir()
    (two / "bad" / "syntax.py").write_text("def (:\n")
    info = index.info()
    assert info["indexed"] == 2 and len(info["problems"]) == 1 and "syntax.py" in info["problems"][0]
    (two / "bad" / "syntax.py").unlink()
    info = index.info()  # the broken file is gone: the problems go with it
    assert info == {"indexed": 2, "problems": []}


def test_info_of_a_missing_library(lib):
    assert index.info() == {"indexed": 0, "problems": []}
    assert not lib.exists()
