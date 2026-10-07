"""links.jsonl and usage.jsonl (kit/06 s3, s4)."""
import json
import os
import re

import pytest

from abacus.library import links, usage

T1 = "osmosis:q:6b1f0a"
T2 = "osmosis:family:9c2e"
T3 = "other:q:abc"


@pytest.fixture
def lib(tmp_path, monkeypatch):
    d = tmp_path / "lib"
    monkeypatch.setenv("ABACUS_LIBRARY", str(d))
    return d


def lines(path):
    return path.read_text(encoding="utf-8").splitlines()


# ---- links -----------------------------------------------------------------

def test_add_writes_one_line_in_the_configured_library(lib):
    rec = links.add("nt.power-mod", T1, "minted", algo_hash="3f2a9c1e", seed=1739201, batch="b-01")
    assert list(rec) == ["algo", "target", "kind", "algo_hash", "seed", "batch", "at"]
    assert rec["algo"] == "nt.power-mod" and rec["target"] == T1 and rec["kind"] == "minted"
    assert rec["algo_hash"] == "3f2a9c1e" and rec["seed"] == 1739201 and rec["batch"] == "b-01"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", rec["at"])
    assert [json.loads(x) for x in lines(lib / "links.jsonl")] == [rec]


def test_optional_fields_default_to_null(lib):
    rec = links.add("nt.power-mod", T1, "checks")
    assert rec["algo_hash"] is None and rec["seed"] is None and rec["batch"] is None


def test_round_trip_add_list_find_rm(lib):
    a = links.add("nt.power-mod", T1, "minted")
    b = links.add("nt.power-mod", T2, "family")
    c = links.add("misc.one-off-sum", T1, "checks")
    assert links.list_links() == [a, b, c]
    assert links.list_links("nt.power-mod") == [a, b]
    assert links.find(T1) == [a, c]
    assert links.find("osmosis:q:nope") == []
    assert links.rm("nt.power-mod", T1) == 1
    assert links.list_links() == [b, c]
    assert links.find(T1) == [c]


def test_rm_leaves_other_lines_intact_byte_for_byte(lib):
    links.add("a.one", T1, "minted")
    links.add("a.one", T2, "minted")
    links.add("b.two", T1, "checks")
    before = lines(lib / "links.jsonl")
    assert links.rm("a.one", T2) == 1
    assert lines(lib / "links.jsonl") == [before[0], before[2]]


def test_rm_removes_every_matching_line(lib):
    links.add("a.one", T1, "minted")
    links.add("a.one", T1, "checks")
    links.add("b.two", T1, "minted")
    assert links.rm("a.one", T1) == 2
    assert [r["algo"] for r in links.list_links()] == ["b.two"]


def test_rm_of_nothing_removes_nothing_and_does_not_touch_the_file(lib):
    assert links.rm("a.one", T1) == 0  # no file at all
    links.add("a.one", T1, "minted")
    p = lib / "links.jsonl"
    before, mtime = p.read_bytes(), p.stat().st_mtime_ns
    assert links.rm("a.one", T2) == 0
    assert p.read_bytes() == before and p.stat().st_mtime_ns == mtime


def test_rm_never_touches_the_algorithm(lib):
    algo = lib / "a" / "one.py"
    algo.parent.mkdir(parents=True)
    algo.write_text("META = {}\n")
    links.add("a.one", T1, "minted")
    links.rm("a.one", T1)
    assert algo.read_text() == "META = {}\n"


def test_rm_keeps_lines_it_cannot_parse(lib):
    links.add("a.one", T1, "minted")
    p = lib / "links.jsonl"
    with p.open("a", encoding="utf-8") as f:
        f.write("<<<<<<< HEAD\n")
    links.add("a.one", T2, "minted")
    assert links.rm("a.one", T1) == 1
    assert lines(p)[0] == "<<<<<<< HEAD"
    assert [r["target"] for r in links.list_links()] == [T2]  # the junk line is skipped on read


def test_rm_rewrites_atomically_with_a_temp_file_and_os_replace(lib, monkeypatch):
    links.add("a.one", T1, "minted")
    links.add("a.one", T2, "minted")
    calls = []
    real = os.replace

    def spy(src, dst):
        calls.append((os.fspath(src), os.fspath(dst)))
        real(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    assert links.rm("a.one", T1) == 1
    assert len(calls) == 1 and calls[0][1] == str(lib / "links.jsonl") and calls[0][0] != calls[0][1]
    assert sorted(x.name for x in lib.iterdir()) == ["links.jsonl"]  # temp file is gone


def test_a_failed_rewrite_keeps_the_original_and_cleans_up(lib, monkeypatch):
    links.add("a.one", T1, "minted")
    links.add("a.one", T2, "minted")
    before = (lib / "links.jsonl").read_bytes()

    def boom(src, dst):
        raise OSError("disk on fire")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        links.rm("a.one", T1)
    assert (lib / "links.jsonl").read_bytes() == before
    assert sorted(x.name for x in lib.iterdir()) == ["links.jsonl"]


@pytest.mark.parametrize("target", [
    "", "osmosis", "osmosis:q", "osmosis:q:", ":q:x", "osmosis::x", "Osmosis:q:x", "osmo sis:q:x",
    "osmosis:q:x\ny", "osmosis:q:\n", 7, None,
])
def test_a_bad_target_raises_and_writes_nothing(lib, target):
    with pytest.raises(ValueError):
        links.add("a.one", target, "minted")
    assert not (lib / "links.jsonl").exists()


@pytest.mark.parametrize("kind", ["", "mint", "MINTED", None, "minted "])
def test_a_bad_kind_raises(lib, kind):
    with pytest.raises(ValueError):
        links.add("a.one", T1, kind)
    assert not (lib / "links.jsonl").exists()


def test_targets_are_opaque_after_the_second_colon(lib):
    target = "osmosis:q:6b1f\u2026:with:colons and spaces"
    rec = links.add("a.one", target, "minted")
    assert links.find(target) == [rec]


def test_a_bad_algo_raises(lib):
    for algo in ("", None, "has space", 3):
        with pytest.raises(ValueError):
            links.add(algo, T1, "minted")


def test_list_by_consumer_matches_the_prefix_not_a_longer_name(lib):
    a = links.add("a.one", T1, "minted")
    b = links.add("a.one", T2, "family")
    c = links.add("a.one", T3, "minted")
    d = links.add("a.one", "osmosisx:q:1", "minted")
    assert links.list_links(consumer="osmosis") == [a, b]
    assert links.list_links(consumer="osmosis:") == [a, b]
    assert links.list_links(consumer="osmosis:q") == [a]
    assert links.list_links(consumer="other") == [c]
    assert links.list_links(consumer="osmosisx") == [d]
    assert links.list_links("a.one", "nobody") == []
    assert links.list_links("zzz.none") == []


def test_target_matches():
    assert links.target_matches(T1, "osmosis") and links.target_matches(T1, T1)
    assert not links.target_matches(T1, "osmosi") and not links.target_matches(T1, T1 + "0")
    assert not links.target_matches("osmosisx:q:1", "osmosis")


def test_counts(lib):
    assert links.counts() == {}
    links.add("a.one", T1, "minted")
    links.add("a.one", T2, "family")
    links.add("b.two", T1, "checks")
    assert links.counts() == {"a.one": 2, "b.two": 1}
    links.rm("b.two", T1)
    assert links.counts() == {"a.one": 2}


def test_a_missing_file_means_no_links(lib):
    assert links.list_links() == [] and links.find(T1) == [] and links.counts() == {}
    assert not lib.exists()  # reading never creates the library


def test_the_file_follows_the_configured_library(tmp_path, monkeypatch):
    one, two = tmp_path / "one", tmp_path / "two"
    monkeypatch.setenv("ABACUS_LIBRARY", str(one))
    links.add("a.one", T1, "minted")
    monkeypatch.setenv("ABACUS_LIBRARY", str(two))
    assert links.list_links() == []
    links.add("b.two", T2, "minted")
    assert (one / "links.jsonl").exists() and (two / "links.jsonl").exists()
    assert [r["algo"] for r in links.list_links()] == ["b.two"]


def test_add_after_a_file_with_no_trailing_newline(lib):
    lib.mkdir()
    (lib / "links.jsonl").write_text(json.dumps({"algo": "a.one", "target": T1, "kind": "minted"}), encoding="utf-8")
    links.add("a.one", T2, "minted")
    assert [r["target"] for r in links.list_links()] == [T1, T2]


def test_files_are_written_with_lf_only(lib):
    links.add("a.one", T1, "minted")
    links.add("a.one", T2, "minted")
    links.rm("a.one", T1)
    assert b"\r" not in (lib / "links.jsonl").read_bytes()


# ---- usage -----------------------------------------------------------------

def test_record_appends_one_line_per_run(lib):
    usage.record("nt.power-mod", "compute", 0.25, True)
    usage.record("nt.power-mod", "check", 1.5, False)
    rows = [json.loads(x) for x in lines(lib / "usage.jsonl")]
    assert [list(r) for r in rows] == [["algo", "role", "at", "time_s", "complete"]] * 2
    assert rows[0]["algo"] == "nt.power-mod" and rows[0]["role"] == "compute"
    assert rows[0]["time_s"] == 0.25 and rows[0]["complete"] is True
    assert rows[1]["role"] == "check" and rows[1]["complete"] is False
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", rows[0]["at"])


def test_usage_counts(lib):
    assert usage.counts() == {}
    usage.record("a.one", "compute", 0.1, True)
    usage.record("a.one", "generate", 0.1, True)
    usage.record("b.two", "compute", 0.1, False)
    assert usage.counts() == {"a.one": 2, "b.two": 1}


def test_usage_missing_file_means_empty_and_reading_creates_nothing(lib):
    assert usage.counts() == {}
    assert not lib.exists()


def test_usage_skips_lines_it_cannot_parse(lib):
    usage.record("a.one", "compute", 0.1, True)
    with (lib / "usage.jsonl").open("a", encoding="utf-8") as f:
        f.write("not json\n\n[1, 2]\n")
    usage.record("a.one", "check", 0.1, True)
    assert usage.counts() == {"a.one": 2}


def test_usage_follows_the_configured_library(tmp_path, monkeypatch):
    monkeypatch.setenv("ABACUS_LIBRARY", str(tmp_path / "x"))
    usage.record("a.one", "compute", 0.1, True)
    assert (tmp_path / "x" / "usage.jsonl").exists()
    monkeypatch.setenv("ABACUS_LIBRARY", str(tmp_path / "y"))
    assert usage.counts() == {}


# ---- a relative ABACUS_LIBRARY, and the lock -------------------------------------

def test_a_relative_library_gives_absolute_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ABACUS_LIBRARY", "rel-lib")
    assert links.links_path().is_absolute() and usage.usage_path().is_absolute()
    assert links.links_path().resolve() == (tmp_path / "rel-lib" / "links.jsonl").resolve()
    assert usage.usage_path().resolve() == (tmp_path / "rel-lib" / "usage.jsonl").resolve()
    links.add("a.one", T1, "minted")
    usage.record("a.one", "compute", 0.1, True)
    assert (tmp_path / "rel-lib" / "links.jsonl").is_file() and (tmp_path / "rel-lib" / "usage.jsonl").is_file()


def test_concurrent_adds_and_rms_lose_nothing(lib):
    import threading

    n_adders, per_adder = 3, 40
    errors = []

    def adder(k):
        try:
            for i in range(per_adder):
                links.add(f"keep.t{k}", f"osmosis:q:{k}-{i}", "minted")
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    def churner(k):
        try:
            for i in range(per_adder):
                links.add(f"churn.t{k}", f"osmosis:q:tmp-{i}", "minted")
                assert links.rm(f"churn.t{k}", f"osmosis:q:tmp-{i}") == 1
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=adder, args=(k,)) for k in range(n_adders)]
    threads += [threading.Thread(target=churner, args=(k,)) for k in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    assert not errors, errors
    kept = [r for r in links.list_links() if r["algo"].startswith("keep.")]
    assert len(kept) == n_adders * per_adder  # no add was swallowed by a rm that read an older file
    assert not [r for r in links.list_links() if r["algo"].startswith("churn.")]
    assert sorted(x.name for x in lib.iterdir()) == ["links.jsonl"]  # no lock or temp file left behind


def test_the_lock_is_released_after_a_failure(lib, monkeypatch):
    links.add("a.one", T1, "minted")

    def boom(src, dst):
        raise OSError("disk on fire")

    with monkeypatch.context() as m:  # not monkeypatch.undo(): that would also undo the library's setenv
        m.setattr(os, "replace", boom)
        with pytest.raises(OSError):
            links.rm("a.one", T1)
    assert not (lib / "links.jsonl.lock").exists()
    links.add("a.one", T2, "minted")  # not blocked by a leftover lock


def test_a_held_lock_times_out_with_an_error_not_a_hang(lib, monkeypatch):
    from abacus.library import _jsonl

    links.add("a.one", T1, "minted")
    (lib / "links.jsonl.lock").write_text("held")
    monkeypatch.setattr(_jsonl, "LOCK_TIMEOUT_S", 0.3)
    with pytest.raises(TimeoutError):
        links.add("a.one", T2, "minted")
    with pytest.raises(TimeoutError):
        links.rm("a.one", T1)
    assert [r["target"] for r in links.list_links()] == [T1]


def test_a_stale_lock_from_a_dead_process_is_broken(lib, monkeypatch):
    from abacus.library import _jsonl

    links.add("a.one", T1, "minted")
    lock = lib / "links.jsonl.lock"
    lock.write_text("dead")
    old = lock.stat().st_mtime - 3600
    os.utime(lock, (old, old))
    monkeypatch.setattr(_jsonl, "LOCK_TIMEOUT_S", 0.3)
    links.add("a.one", T2, "minted")
    assert [r["target"] for r in links.list_links()] == [T1, T2] and not lock.exists()


def test_a_waiter_that_saw_a_stale_lock_does_not_break_a_fresh_one(lib, monkeypatch):
    """Two waiters see the same stale lock; the first breaks it and takes a fresh one; the second must not
    break that. Simulated: the lock on disk is fresh, but this waiter's staleness check is told it is old."""
    import time
    from abacus.library import _jsonl

    links.add("a.one", T1, "minted")
    lock = lib / "links.jsonl.lock"
    lock.write_text("held")  # the first waiter's fresh lock
    real_time, real_monotonic, real_sleep = time.time, time.monotonic, time.sleep

    class Clock:
        calls = 0
        monotonic = staticmethod(real_monotonic)
        sleep = staticmethod(real_sleep)

        @classmethod
        def time(cls):
            cls.calls += 1
            return real_time() + (3600 if cls.calls == 1 else 0)  # only the first look sees it as stale

    monkeypatch.setattr(_jsonl, "time", Clock)
    monkeypatch.setattr(_jsonl, "LOCK_TIMEOUT_S", 0.3)
    with pytest.raises(TimeoutError):  # the lock is the other waiter's, so this one must wait, not take it
        links.add("a.one", T2, "minted")
    assert lock.read_text() == "held"  # still there, still theirs
    assert [r["target"] for r in links.list_links()] == [T1]
    assert sorted(x.name for x in lib.iterdir()) == ["links.jsonl", "links.jsonl.lock"]  # no .stale left behind


def test_rm_retries_a_replace_that_windows_refuses(lib, monkeypatch):
    links.add("a.one", T1, "minted")
    links.add("a.one", T2, "minted")
    real, calls = os.replace, []

    def flaky(src, dst):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("the file is open elsewhere")
        real(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    assert links.rm("a.one", T1) == 1
    assert len(calls) == 3 and [r["target"] for r in links.list_links()] == [T2]
    assert sorted(x.name for x in lib.iterdir()) == ["links.jsonl"]


def test_rm_gives_up_on_a_replace_that_never_works(lib, monkeypatch):
    links.add("a.one", T1, "minted")
    before = (lib / "links.jsonl").read_bytes()

    def never(src, dst):
        raise PermissionError("locked")

    with monkeypatch.context() as m:
        m.setattr(os, "replace", never)
        with pytest.raises(PermissionError):
            links.rm("a.one", T1)
    assert (lib / "links.jsonl").read_bytes() == before
    assert sorted(x.name for x in lib.iterdir()) == ["links.jsonl"]
