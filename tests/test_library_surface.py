"""The library on the CLI and the MCP, and usage recording on every role run (kit/06 s2-s4)."""
import json
import os
import time
from pathlib import Path

import pytest

from abacus import budget, mcp_server
from abacus.algo.roles import run_role
from abacus.cli import main
from abacus.library import links, store, usage

FIX = Path(__file__).parent / "fixtures" / "algos"
NT, MISC = "nt.power-mod", "misc.one-off-sum"
T1, T2 = "osmosis:q:6b1f0a", "osmosis:family:9c2e"


@pytest.fixture
def lib(tmp_path, monkeypatch):
    d = tmp_path / "lib"
    monkeypatch.setenv("ABACUS_LIBRARY", str(d))
    store.write(NT, (FIX / "nt_power_mod.py").read_text(encoding="utf-8"))
    store.write(MISC, (FIX / "one_off.py").read_text(encoding="utf-8"))
    return d


def cli(capsys, *argv):
    capsys.readouterr()
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def ok(capsys, *argv):
    code, out, err = cli(capsys, *argv)
    assert code == 0, err
    return json.loads(out)


def fails(capsys, *argv):
    """The command must exit 2 with a one-line message on stderr and nothing on stdout."""
    code, out, err = cli(capsys, *argv)
    assert code == 2, (code, out, err)
    assert out == ""
    assert err.startswith("abacus: ") and len(err.strip().splitlines()) == 1, err
    assert "Traceback" not in err
    return err


def ids(rows):
    return [r["id"] for r in rows]


# ---- algo search -----------------------------------------------------------

def test_search_lists_everything_by_id(lib, capsys):
    rows = ok(capsys, "algo", "search")
    assert ids(rows) == [MISC, NT]
    assert set(rows[0]) == {"id", "title", "summary", "roles", "tags", "techniques", "answer_format",
                            "hash", "links", "uses"}


def test_search_text_and_filters(lib, capsys):
    assert ids(ok(capsys, "algo", "search", "modular")) == [NT]
    assert ids(ok(capsys, "algo", "search", "fixed sum")) == [MISC]
    assert ids(ok(capsys, "algo", "search", "--role", "hand_space")) == [NT]
    assert ids(ok(capsys, "algo", "search", "--tag", "number-theory")) == [NT]
    assert ids(ok(capsys, "algo", "search", "--technique", "fast-exponentiation")) == [NT]
    assert ids(ok(capsys, "algo", "search", "--format", "integer")) == [MISC, NT]
    assert ids(ok(capsys, "algo", "search", "--format", "set")) == []
    assert ids(ok(capsys, "algo", "search", "--limit", "1")) == [MISC]
    assert ids(ok(capsys, "algo", "search", "--role", "check", "--tag", "number-theory", "modular")) == [NT]


def test_search_linked_and_unlinked(lib, capsys):
    links.add(NT, T1, "minted")
    assert ids(ok(capsys, "algo", "search", "--linked", "osmosis")) == [NT]
    assert ids(ok(capsys, "algo", "search", "--linked", T1)) == [NT]
    assert ids(ok(capsys, "algo", "search", "--linked", "other")) == []
    assert ids(ok(capsys, "algo", "search", "--unlinked")) == [MISC]
    assert ok(capsys, "algo", "search", "modular")[0]["links"] == 1


def test_search_sorts(lib, capsys):
    t0 = time.time()
    os.utime(lib / "nt" / "power-mod.py", (t0, t0))
    os.utime(lib / "misc" / "one-off-sum.py", (t0 + 100, t0 + 100))
    assert ids(ok(capsys, "algo", "search", "--sort", "id")) == [MISC, NT]
    assert ids(ok(capsys, "algo", "search", "--sort", "recent")) == [MISC, NT]
    os.utime(lib / "nt" / "power-mod.py", (t0 + 200, t0 + 200))
    assert ids(ok(capsys, "algo", "search", "--sort", "recent")) == [NT, MISC]
    links.add(NT, T1, "minted")
    links.add(NT, T2, "family")
    links.add(MISC, "osmosis:q:zz", "checks")
    assert ids(ok(capsys, "algo", "search", "--sort", "most_linked")) == [NT, MISC]
    usage.record(MISC, "compute", 0.1, True)
    usage.record(MISC, "compute", 0.1, True)
    usage.record(NT, "compute", 0.1, True)
    rows = ok(capsys, "algo", "search", "--sort", "most_used")
    assert ids(rows) == [MISC, NT] and [r["uses"] for r in rows] == [2, 1]


def test_search_an_empty_or_missing_library_is_an_empty_list(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ABACUS_LIBRARY", str(tmp_path / "nowhere"))
    assert ok(capsys, "algo", "search") == []


def test_search_bad_sort_exits_2(lib, capsys):
    assert cli(capsys, "algo", "search", "--sort", "bogus")[0] == 2


# ---- algo show -------------------------------------------------------------

def test_show_by_id_includes_links_and_usage(lib, capsys):
    rec = links.add(NT, T1, "minted", algo_hash="3f2a9c1e", seed=7, batch="b-01")
    usage.record(NT, "compute", 0.1, True)
    usage.record(NT, "check", 0.1, False)
    out = ok(capsys, "algo", "show", NT)
    assert out["meta"]["id"] == NT and out["hash"] and out["path"].endswith("power-mod.py")
    assert out["links"] == [rec]
    assert out["uses"] == 2
    again = ok(capsys, "algo", "show", MISC)
    assert again["links"] == [] and again["uses"] == 0


def test_show_by_path_is_unchanged(lib, capsys):
    out = ok(capsys, "algo", "show", str(lib / "nt" / "power-mod.py"))
    assert set(out) == {"hash", "path", "meta"} and out["meta"]["id"] == NT
    by_id = ok(capsys, "algo", "show", NT)
    assert by_id["hash"] == out["hash"] and by_id["meta"] == out["meta"]


def test_show_errors_exit_2_with_one_line(lib, capsys):
    assert "no algorithm" in fails(capsys, "algo", "show", "nt.nothing")
    assert "bad id" in fails(capsys, "algo", "show", "Not An Id")
    assert "bad id" in fails(capsys, "algo", "show", "power-mod")  # no area
    assert "no such algorithm file" in fails(capsys, "algo", "show", str(lib / "nt" / "gone.py"))


def test_show_a_broken_algorithm_exits_2_with_one_line(lib, capsys):
    store.write("nt.broken", "META = {}\n")
    fails(capsys, "algo", "show", "nt.broken")


# ---- link ------------------------------------------------------------------

def test_link_round_trip(lib, capsys):
    a = ok(capsys, "link", "add", NT, T1, "--kind", "minted", "--hash", "3f2a9c1e", "--seed", "7", "--batch", "b-01")
    assert a["algo"] == NT and a["target"] == T1 and a["kind"] == "minted"
    assert a["algo_hash"] == "3f2a9c1e" and a["seed"] == 7 and a["batch"] == "b-01"
    b = ok(capsys, "link", "add", NT, T2, "--kind", "family")
    c = ok(capsys, "link", "add", MISC, T1, "--kind", "checks")
    assert b["algo_hash"] is None and b["seed"] is None and b["batch"] is None
    assert ok(capsys, "link", "list") == [a, b, c]
    assert ok(capsys, "link", "list", "--algo", NT) == [a, b]
    assert ok(capsys, "link", "list", "--consumer", "osmosis:family") == [b]
    assert ok(capsys, "link", "list", "--algo", NT, "--consumer", "osmosis:q") == [a]
    assert ok(capsys, "link", "find", T1) == [a, c]
    assert ok(capsys, "link", "find", "osmosis:q:nope") == []
    assert ok(capsys, "link", "rm", NT, T1) == {"removed": 1}
    assert ok(capsys, "link", "rm", NT, T1) == {"removed": 0}
    assert ok(capsys, "link", "list") == [b, c]
    assert ok(capsys, "link", "find", T1) == [c]


def test_link_errors_exit_2_with_one_line(lib, capsys):
    assert "target" in fails(capsys, "link", "add", NT, "notatarget", "--kind", "minted")
    assert "kind" in fails(capsys, "link", "add", NT, T1, "--kind", "bogus")
    assert "algo" in fails(capsys, "link", "add", "bad id", T1, "--kind", "minted")
    assert links.list_links() == []
    assert cli(capsys, "link", "add", NT, T1)[0] == 2  # --kind is required
    assert cli(capsys, "link")[0] == 2
    assert cli(capsys, "link", "nonsense")[0] == 2


# ---- index -----------------------------------------------------------------

def test_index_rebuild_prints_the_problems(lib, capsys):
    assert ok(capsys, "index", "rebuild") == []
    assert (lib / ".index.sqlite").is_file()
    store.write("nt.broken", "META = {}\n")
    store.write("nt.wrong-id", (FIX / "one_off.py").read_text(encoding="utf-8"))
    problems = ok(capsys, "index", "rebuild")
    assert len(problems) == 2 and all(isinstance(p, str) for p in problems)
    assert any("broken.py" in p for p in problems) and any("wrong-id.py" in p for p in problems)
    assert ids(ok(capsys, "algo", "search")) == [MISC, NT]  # the bad files are skipped, not fatal


def test_index_needs_a_subcommand(lib, capsys):
    assert cli(capsys, "index")[0] == 2


# ---- the MCP buttons -------------------------------------------------------

def call(name, inp):
    return budget.call(name, inp, in_process=True)


def test_the_buttons_are_listed_as_mcp_tools():
    names = {t.name for t in mcp_server.list_tools()}
    assert {"algo_search", "algo_show", "link_add", "link_rm", "link_find"} <= names


def test_algo_search_button(lib):
    ev = call("algo_search", {"query": "modular"})
    assert ev.complete and ev.method == "search" and ev.button == "algo_search"
    assert ids(ev.result) == [NT]
    assert "searched 2 indexed algorithms" in ev.scope and str(lib) in ev.scope
    ev = call("algo_search", {"sort": "most_used", "limit": 1, "unlinked": True, "role": "compute",
                              "tag": "number-theory", "technique": "fast-exponentiation",
                              "answer_format": "integer"})
    assert ev.complete and ids(ev.result) == [NT]
    assert ids(call("algo_search", {}).result) == [MISC, NT]


def test_algo_search_rejects_a_bad_sort(lib):
    ev = call("algo_search", {"sort": "bogus"})
    assert not ev.complete and ev.flags[0]["code"] == "bad_input"


def test_algo_show_button(lib):
    rec = links.add(NT, T1, "minted")
    usage.record(NT, "compute", 0.1, True)
    ev = call("algo_show", {"id": NT})
    assert ev.complete and ev.method == "search"
    assert ev.result["meta"]["id"] == NT and ev.result["links"] == [rec] and ev.result["uses"] == 1
    assert ev.result["hash"] in ev.scope


def test_algo_show_button_errors_are_flagged(lib):
    ev = call("algo_show", {"id": "nt.nothing"})
    assert not ev.complete and ev.result is None and ev.flags[0]["code"] == "no_such_algo"
    ev = call("algo_show", {"id": "Not An Id"})
    assert not ev.complete and ev.flags[0]["code"] == "bad_input"
    store.write("nt.broken", "META = {}\n")
    ev = call("algo_show", {"id": "nt.broken"})
    assert not ev.complete and ev.flags[0]["code"] == "bad_meta"
    assert call("algo_show", {}).flags[0]["code"] == "bad_input"  # id is required


def test_link_buttons_round_trip(lib):
    ev = call("link_add", {"algo": NT, "target": T1, "kind": "minted", "algo_hash": "3f2a9c1e",
                           "seed": 7, "batch": "b-01"})
    assert ev.complete and ev.method == "timed"
    assert ev.result["algo"] == NT and ev.result["seed"] == 7 and ev.result["batch"] == "b-01"
    call("link_add", {"algo": MISC, "target": T1, "kind": "checks"})
    found = call("link_find", {"target": T1})
    assert found.complete and found.method == "search" and found.button == "link_find"
    assert [r["algo"] for r in found.result] == [NT, MISC]
    assert call("link_find", {"target": "osmosis:q:nope"}).result == []
    assert links.list_links() == found.result
    gone = call("link_rm", {"algo": NT, "target": T1})
    assert gone.complete and gone.method == "timed" and gone.result == {"removed": 1}
    assert call("link_rm", {"algo": NT, "target": T1}).result == {"removed": 0}
    assert [r["algo"] for r in call("link_find", {"target": T1}).result] == [MISC]


def test_link_buttons_flag_bad_input_and_write_nothing(lib):
    ev = call("link_add", {"algo": NT, "target": "notatarget", "kind": "minted"})
    assert not ev.complete and ev.flags[0]["code"] == "bad_input" and "target" in ev.flags[0]["message"]
    ev = call("link_add", {"algo": NT, "target": T1, "kind": "bogus"})
    assert not ev.complete and ev.flags[0]["code"] == "bad_input"
    ev = call("link_add", {"algo": "bad id", "target": T1, "kind": "minted"})
    assert not ev.complete and ev.flags[0]["code"] == "bad_input"
    assert links.list_links() == []
    for name, inp in (("link_add", {}), ("link_rm", {"algo": NT}), ("link_find", {})):
        assert call(name, inp).flags[0]["code"] == "bad_input"


def test_buttons_run_in_a_child_process_too(lib):
    ev = budget.call("link_add", {"algo": NT, "target": T1, "kind": "minted"}, time_s=60)
    assert ev.complete, ev.flags
    assert [r["target"] for r in links.list_links()] == [T1]
    ev = budget.call("algo_search", {"query": "modular"}, time_s=60)
    assert ev.complete and ids(ev.result) == [NT]


# ---- usage recording -------------------------------------------------------

def rows(lib):
    p = lib / "usage.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


PARAMS = {"params": {"a": 3, "b": 4, "m": 7}}


def test_run_role_on_a_library_algorithm_records_usage(lib):
    ev = run_role(lib / "nt" / "power-mod.py", "compute", args=PARAMS, in_process=True)
    assert ev.complete and ev.result == pow(3, 4, 7)
    (row,) = rows(lib)
    assert row["algo"] == NT and row["role"] == "compute" and row["complete"] is True
    assert isinstance(row["time_s"], (int, float)) and row["time_s"] >= 0
    run_role(lib / "nt" / "power-mod.py", "check", args={**PARAMS, "proposed": 4}, in_process=True)
    assert [r["role"] for r in rows(lib)] == ["compute", "check"]
    assert usage.counts() == {NT: 2}


def test_run_role_records_a_failed_run_as_incomplete(lib):
    ev = run_role(lib / "nt" / "power-mod.py", "compute", args={"params": {}}, in_process=True)
    assert not ev.complete
    (row,) = rows(lib)
    assert row["algo"] == NT and row["complete"] is False


def test_run_role_accepts_a_string_path_and_a_dotted_path(lib, monkeypatch):
    monkeypatch.chdir(lib)
    run_role("nt/power-mod.py", "compute", args=PARAMS, in_process=True)
    run_role(str(lib / "nt" / ".." / "nt" / "power-mod.py"), "compute", args=PARAMS, in_process=True)
    assert [r["algo"] for r in rows(lib)] == [NT, NT]


def test_run_role_outside_the_library_records_nothing(lib, tmp_path):
    outside = tmp_path / "outside.py"
    outside.write_text((FIX / "nt_power_mod.py").read_text(encoding="utf-8"), encoding="utf-8")
    ev = run_role(outside, "compute", args=PARAMS, in_process=True)
    assert ev.complete
    assert rows(lib) == []


def test_a_relative_path_is_taken_from_the_working_directory_not_the_library(lib, tmp_path, monkeypatch):
    work = tmp_path / "work"
    (work / "nt").mkdir(parents=True)
    (work / "nt" / "power-mod.py").write_text((FIX / "nt_power_mod.py").read_text(encoding="utf-8"),
                                              encoding="utf-8")
    monkeypatch.chdir(work)
    ev = run_role("nt/power-mod.py", "compute", args=PARAMS, in_process=True)
    assert ev.complete  # the copy in the working directory ran, not the library's
    assert rows(lib) == []


def test_a_run_that_never_started_records_nothing(lib):
    run_role(lib / "nt" / "no-such-file.py", "compute", args=PARAMS, in_process=True)
    run_role(lib / "nt" / "power-mod.py", "not_a_role", args=PARAMS, in_process=True)
    bad = run_role(lib / "nt" / "power-mod.py", "generate", seed=-1, in_process=True)  # rejected by the budget
    assert bad.flags[0]["code"] == "bad_input"
    assert rows(lib) == []


def test_a_child_that_never_started_records_no_usage(lib, monkeypatch):
    monkeypatch.setattr(budget, "STARTUP_S", 0.01)  # the child cannot report ready in time
    ev = run_role(lib / "nt" / "power-mod.py", "compute", args=PARAMS)
    assert [f["code"] for f in ev.flags] == ["startup_timeout"]
    assert rows(lib) == [] and usage.counts() == {}


def test_a_usage_failure_never_fails_the_run(lib, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(usage, "record", boom)
    ev = run_role(lib / "nt" / "power-mod.py", "compute", args=PARAMS, in_process=True)
    assert ev.complete and ev.result == pow(3, 4, 7)


def test_an_unwritable_usage_file_never_fails_the_run(lib):
    (lib / "usage.jsonl").mkdir()  # appending to a directory raises
    ev = run_role(lib / "nt" / "power-mod.py", "compute", args=PARAMS, in_process=True)
    assert ev.complete and ev.result == pow(3, 4, 7)


# ---- usage is recorded where every path goes through: budget.call ---------------

def algo_run_input(role="compute", **extra):
    return {"path": str(Path(os.environ["ABACUS_LIBRARY"]) / "nt" / "power-mod.py"), "role": role,
            "args": PARAMS, **extra}


def test_mcp_algo_run_appends_exactly_one_usage_row(lib):
    text, is_error = mcp_server.call_tool("algo_run", algo_run_input())
    ev = json.loads(text)
    assert not is_error and ev["complete"] is True and ev["result"] == pow(3, 4, 7), ev
    (row,) = rows(lib)
    assert row["algo"] == NT and row["role"] == "compute" and row["complete"] is True
    assert usage.counts() == {NT: 1}


def test_the_cli_algo_run_button_appends_exactly_one_usage_row(lib, capsys):
    out = ok(capsys, "algo_run", json.dumps(algo_run_input()))
    assert out["complete"] is True and out["result"] == pow(3, 4, 7)
    (row,) = rows(lib)
    assert row["algo"] == NT and row["role"] == "compute"


def test_run_role_appends_exactly_one_row_in_a_child_process_too(lib):
    ev = run_role(lib / "nt" / "power-mod.py", "compute", args=PARAMS)
    assert ev.complete and ev.result == pow(3, 4, 7)
    assert len(rows(lib)) == 1 and usage.counts() == {NT: 1}


def test_budget_call_in_process_records_one_row_and_run_role_does_not_add_another(lib):
    ev = budget.call("algo_run", algo_run_input(), in_process=True)
    assert ev.complete and len(rows(lib)) == 1
    run_role(lib / "nt" / "power-mod.py", "compute", args=PARAMS, in_process=True)
    assert len(rows(lib)) == 2


def test_other_buttons_record_nothing(lib):
    budget.call("algo_search", {"query": "modular"}, in_process=True)
    budget.call("algo_show", {"id": NT}, in_process=True)
    assert rows(lib) == []


def test_an_algo_run_rejected_by_the_budget_records_nothing(lib):
    ev = budget.call("algo_run", algo_run_input(seed=-1), in_process=True)
    assert ev.flags[0]["code"] == "bad_input"
    ev = budget.call("algo_run", {"path": str(lib / "nt" / "power-mod.py"), "role": "nonsense"}, in_process=True)
    assert ev.flags[0]["code"] == "bad_input"
    assert rows(lib) == []


# ---- algo_search says what it did not search ------------------------------------

def test_algo_search_counts_indexed_algorithms_and_flags_skipped_files(tmp_path, monkeypatch):
    d = tmp_path / "lib2"
    monkeypatch.setenv("ABACUS_LIBRARY", str(d))
    store.write(NT, (FIX / "nt_power_mod.py").read_text(encoding="utf-8"))
    (d / "bad").mkdir()
    (d / "bad" / "broken.py").write_text("def (:\n")
    ev = call("algo_search", {})
    assert ids(ev.result) == [NT] and ev.complete
    assert "searched 1 indexed algorithm" in ev.scope and str(d) in ev.scope
    (flag,) = [f for f in ev.flags if f["code"] == "skipped_files"]
    assert "broken.py" in flag["message"] and "1" in flag["message"]
    # a clean library carries no such flag
    (d / "bad" / "broken.py").unlink()
    ev = call("algo_search", {})
    assert not [f for f in ev.flags if f["code"] == "skipped_files"] and "searched 1 indexed algorithm" in ev.scope


def test_the_skipped_files_message_names_only_the_first_few(tmp_path, monkeypatch):
    d = tmp_path / "lib3"
    monkeypatch.setenv("ABACUS_LIBRARY", str(d))
    store.write(NT, (FIX / "nt_power_mod.py").read_text(encoding="utf-8"))
    (d / "bad").mkdir()
    for n in range(8):
        (d / "bad" / f"broken{n}.py").write_text("def (:\n")
    (flag,) = [f for f in call("algo_search", {}).flags if f["code"] == "skipped_files"]
    assert "8" in flag["message"] and "broken0.py" in flag["message"] and "broken7.py" not in flag["message"]


# ---- an algorithm that prints at import cannot corrupt the CLI's JSON -------------

CHATTY = (FIX / "nt_power_mod.py").read_text(encoding="utf-8").replace(
    "\nMETA", "\nprint('chatty import')\nMETA", 1)


def test_import_time_prints_do_not_corrupt_cli_json(lib, capsys):
    assert CHATTY != (FIX / "nt_power_mod.py").read_text(encoding="utf-8")
    store.write(NT, CHATTY, overwrite=True)
    assert ids(ok(capsys, "algo", "search")) == [MISC, NT]
    assert ok(capsys, "algo", "show", NT)["meta"]["id"] == NT
    ev = ok(capsys, "algo", "show", str(lib / "nt" / "power-mod.py"))
    assert ev["meta"]["id"] == NT
    assert call("algo_show", {"id": NT}).complete
