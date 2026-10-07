"""`abacus mint make`: batches, evidence, flags (kit/07 s2)."""
import hashlib
import json
import re
from pathlib import Path

import pytest

from abacus import budget, mcp_server, registry
from abacus.algo.loader import MetaError
from abacus.cli import main
from abacus.library import store
from abacus.mint import make as mk
from abacus.mint.make import derive_seed, make, make_batch

FIX = Path(__file__).parent / "fixtures" / "algos"
DAY = "2026-10-07"

# Library ids are the META ids of the fixture files.
POWER, CONST, DISAGREE, RANGE = "nt.power-mod", "lint.const", "lint.disagree", "lint.range"
ONE_OFF, SLOW = "misc.one-off-sum", "lint.slow-gen"

_HEAD = 'from abacus.evidence import Evidence, make_compare\n'


def _meta(algo_id, roles, **extra):
    m = {"id": algo_id, "title": "T", "summary": "S.", "roles": roles, "answer": {"format": "integer"}, **extra}
    return f"META = {m!r}\n"


CHECK_NO = _HEAD + _meta("tmp.check-no", ["generate", "compute", "check"]) + '''
def compute(params):
    return params["a"]


def check(params, proposed):
    ev = Evidence(button="check", result=False, method="exhaustive", scope="always says no")
    ev.compare = make_compare(proposed, params["a"] + 1)
    return ev


def generate(rng, knobs):
    a = rng.randint(0, 10**6)
    return {"params": {"a": a}, "statement": f"Find {a}.", "answer": a}
'''

POOL = _meta("tmp.small-pool", ["generate", "compute"], knobs={"n": {"int": [1, 4]}}) + '''
def compute(params):
    return params["n"]


def generate(rng, knobs):
    n = rng.randint(1, 4)
    return {"params": {"n": n}, "statement": f"Find {n}.", "answer": n}
'''

PINNED = _meta("tmp.pinned", ["generate", "compute"], knobs={"k": {"int": [5, 5]}}) + '''
def compute(params):
    return params["k"]


def generate(rng, knobs):
    k = knobs.get("k", rng.randint(5, 5))
    return {"params": {"k": k}, "statement": f"Find {k}.", "answer": k}
'''

FLAKY = _meta("tmp.flaky", ["generate", "compute"]) + '''
def compute(params):
    return params["a"]


def generate(rng, knobs):
    a = rng.randint(1, 10**6)
    if a % 2:
        raise ValueError("odd draw")
    return {"params": {"a": a}, "statement": f"Find {a}.", "answer": a}
'''

BAD_COMPUTE = _meta("tmp.bad-compute", ["generate", "compute"]) + '''
def compute(params):
    raise RuntimeError("compute is broken")


def generate(rng, knobs):
    a = rng.randint(0, 10**6)
    return {"params": {"a": a}, "statement": f"Find {a}.", "answer": a}
'''

WITH_DEMO = _meta("tmp.with-demo", ["generate", "compute", "demo"]) + '''
def compute(params):
    return params["a"]


def demo(instance):
    return {"steps": ["start", instance.params["a"]]}


def generate(rng, knobs):
    a = rng.randint(0, 10**6)
    return {"params": {"a": a}, "statement": f"Find {a}.", "answer": a}
'''

GEN_ONLY = _meta("tmp.gen-only", ["generate"]) + '''
def generate(rng, knobs):
    a = rng.randint(0, 10**6)
    return {"params": {"a": a}, "statement": f"Find {a}.", "answer": a}
'''

NO_GENERATE = _meta("tmp.no-generate", ["compute"]) + '''
def compute(params):
    return 1
'''

TEXT_ANSWER = ('META = {"id": "tmp.text-answer", "title": "T", "summary": "S.", "roles": ["generate"], '
               '"answer": {"format": "text", "range": [0, 5]}}\n') + '''
def generate(rng, knobs):
    a = rng.randint(0, 10**6)
    return {"params": {"a": a}, "statement": f"Name it {a}.", "answer": "x squared"}
'''


@pytest.fixture
def lib(tmp_path, monkeypatch):
    d = tmp_path / "lib"
    monkeypatch.setenv("ABACUS_LIBRARY", str(d))
    monkeypatch.setattr(mk, "_today", lambda: DAY)
    for algo_id, name in ((POWER, "nt_power_mod.py"), (CONST, "lint_const.py"), (DISAGREE, "lint_disagree.py"),
                          (RANGE, "lint_range.py"), (ONE_OFF, "one_off.py"), (SLOW, "lint_slow_gen.py")):
        store.write(algo_id, (FIX / name).read_text(encoding="utf-8"))
    for source in (CHECK_NO, POOL, PINNED, FLAKY, BAD_COMPUTE, WITH_DEMO, GEN_ONLY, NO_GENERATE, TEXT_ANSWER):
        store.write(re.search(r"""['"]id['"]: ['"]([^'"]+)['"]""", source).group(1), source)
    return d


def read_batch(path):
    lines = Path(path).read_text(encoding="utf-8").split("\n")
    assert lines[-1] == "", "every line, the last too, ends in a newline"
    rows = [json.loads(line) for line in lines[:-1]]
    assert list(rows[0]) == ["summary"]
    return rows[0]["summary"], rows[1:]


def codes(inst):
    return [f["code"] for f in inst["flags"]]


def message(inst, code):
    return next(f["message"] for f in inst["flags"] if f["code"] == code)


def strip_time(x):
    """Everything is the same between two runs but the clock, and the batch id the second run takes."""
    if isinstance(x, dict):
        return {k: strip_time(v) for k, v in x.items() if k not in ("time_s", "batch")}
    if isinstance(x, (list, tuple)):
        return [strip_time(v) for v in x]
    return x


# ---- the file ---------------------------------------------------------------

def test_batch_file_has_id_summary_then_instances(lib):
    path = make(POWER, count=5, seed=11)
    assert path == lib / "batches" / f"{DAY}-power-mod-01.jsonl"
    summary, insts = read_batch(path)
    assert len(insts) == 5
    assert summary["algo"] == POWER and summary["batch"] == f"{DAY}-power-mod-01"
    assert summary["count"] == 5 and summary["made"] == 5 and summary["seed"] == 11
    assert len(summary["algo_hash"]) == 8 and summary["time_s"] >= 0
    assert summary["attempts"] >= 5 and summary["duplicates_skipped"] == summary["attempts"] - 5
    assert set(summary) >= {"flags_by_code", "answer_spread", "notes", "knobs"}
    for pos, inst in enumerate(insts, start=1):
        assert inst["index"] == pos and inst["decision"] == "keep"
        assert inst["algo"] == POWER and inst["algo_hash"] == summary["algo_hash"]
        assert inst["seed"] == derive_seed(11, inst["attempt"])
        assert inst["statement"] and inst["params"] and inst["answer"]["format"] == "integer"
        assert [e["button"] for e in inst["evidence"]] == ["algo_run", "check"]
        assert inst["evidence"][0]["result"] == inst["answer"]["value"]
        assert not {"derivations_disagree", "out_of_range", "incomplete"} & set(codes(inst))
        assert inst["solution"] is None and inst["signals"] == {}


def test_next_free_number_per_date_and_slug(lib):
    assert make(POWER, count=2, seed=1).name == f"{DAY}-power-mod-01.jsonl"
    assert make(POWER, count=2, seed=1).name == f"{DAY}-power-mod-02.jsonl"
    batches = lib / "batches"
    (batches / f"{DAY}-power-mod-07.osmosis.json").write_text("{}", encoding="utf-8")  # an export counts as taken
    (batches / f"{DAY}-const-09.jsonl").write_text("", encoding="utf-8")
    (batches / "2026-10-06-power-mod-40.jsonl").write_text("", encoding="utf-8")
    assert make(POWER, count=2, seed=1).name == f"{DAY}-power-mod-08.jsonl"
    assert make(CONST, count=2, seed=1).name == f"{DAY}-const-10.jsonl"  # the slug is the id's last segment


def test_an_existing_batch_file_is_never_overwritten(lib, monkeypatch):
    batches = lib / "batches"
    batches.mkdir(parents=True)
    taken = batches / f"{DAY}-power-mod-01.jsonl"
    taken.write_text("keep me", encoding="utf-8")
    monkeypatch.setattr(mk, "_taken_numbers", lambda *a: [])  # the scan misses it, as in a race
    assert make(POWER, count=2, seed=1).name == f"{DAY}-power-mod-02.jsonl"
    assert taken.read_text(encoding="utf-8") == "keep me"


def test_algo_by_file_path(lib):
    path = make(str(FIX / "lint_const.py"), count=2, seed=3)
    summary, insts = read_batch(path)
    assert summary["algo"] == CONST and len(insts) == 2 and path.parent == lib / "batches"


# ---- determinism ------------------------------------------------------------

def test_seeds_are_derived_from_the_batch_seed_and_the_attempt():
    expect = int.from_bytes(hashlib.sha256(b"7:3").digest()[:4], "big")
    assert derive_seed(7, 3) == expect
    assert len({derive_seed(7, i) for i in range(1, 50)}) == 49
    assert derive_seed(7, 3) != derive_seed(8, 3)


def test_same_algo_seed_and_knobs_give_the_same_instances(lib):
    runs = [read_batch(make(POWER, count=6, seed=5, knobs={"m": 12})) for _ in range(2)]
    assert strip_time(runs[0]) == strip_time(runs[1])
    timed = read_batch(make(POWER, count=6, seed=5, knobs={"m": 12}, time_s=60))  # a budget changes nothing else
    assert strip_time(timed[1]) == strip_time(runs[0][1])
    other = read_batch(make(POWER, count=6, seed=6, knobs={"m": 12}))
    assert [i["params"] for i in other[1]] != [i["params"] for i in runs[0][1]]
    assert all(i["params"]["m"] == 12 for i in runs[0][1])
    assert runs[0][0]["knobs"] == {"m": 12}


# ---- flags ------------------------------------------------------------------

def test_duplicate_answer_for_an_algorithm_that_always_answers_seven(lib):
    summary, insts = read_batch(make(CONST, count=4, seed=2))
    assert len(insts) == 4
    assert all("duplicate_answer" in codes(i) for i in insts)  # every one shares its answer with another
    assert summary["flags_by_code"]["duplicate_answer"] == 4
    assert summary["answer_spread"] == 1
    msg = message(insts[0], "duplicate_answer")
    assert "2" in msg and "3" in msg and "4" in msg  # it names the other instances
    assert all(i["decision"] == "keep" for i in insts)  # flags never drop anything


def test_duplicate_statement_when_params_differ(lib):
    # A statement that ignores the one parameter that differs.
    src = _meta("tmp.same-words", ["generate"], knobs={"n": {"int": [1, 99]}}) + '''
def generate(rng, knobs):
    return {"params": {"n": rng.randint(1, 10**6)}, "statement": "Find the number.", "answer": rng.randint(1, 10**6)}
'''
    store.write("tmp.same-words", src)
    summary, insts = read_batch(make("tmp.same-words", count=3, seed=4))
    assert [codes(i) for i in insts] == [["duplicate_statement"]] * 3
    assert summary["flags_by_code"] == {"duplicate_statement": 3}


def test_a_family_with_distinct_answers_has_a_wide_spread(lib):
    summary, insts = read_batch(make("tmp.small-pool", count=3, seed=9))
    assert summary["answer_spread"] == 3 and len({i["answer"]["value"] for i in insts}) == 3
    assert "duplicate_answer" not in summary["flags_by_code"]


def test_derivations_disagree_when_compute_differs_from_generate(lib):
    summary, insts = read_batch(make(DISAGREE, count=4, seed=1))
    assert len(insts) == 4  # flagged, not dropped
    assert all("derivations_disagree" in codes(i) for i in insts)
    assert summary["flags_by_code"]["derivations_disagree"] == 4
    msg = message(insts[0], "derivations_disagree")
    assert "compute" in msg and str(insts[0]["answer"]["value"]) in msg


def test_derivations_disagree_when_check_rejects_the_generated_answer(lib):
    summary, insts = read_batch(make("tmp.check-no", count=3, seed=1))
    assert all(codes(i) == ["derivations_disagree"] for i in insts)  # compute agrees; only check says no
    msg = message(insts[0], "derivations_disagree")
    assert msg.startswith("check") and "compute returned" not in msg
    assert [e["button"] for e in insts[0]["evidence"]] == ["algo_run", "check"]


def test_out_of_range(lib):
    summary, insts = read_batch(make(RANGE, count=3, seed=1))
    assert all("out_of_range" in codes(i) for i in insts)
    assert summary["flags_by_code"]["out_of_range"] == 3
    assert "[0, 5]" in message(insts[0], "out_of_range")
    _, ok = read_batch(make(POWER, count=3, seed=1))
    assert not any("out_of_range" in codes(i) for i in ok)


def test_an_answer_that_is_not_a_number_is_out_of_a_declared_range(lib):
    _, insts = read_batch(make("tmp.text-answer", count=2, seed=1))
    assert all(codes(i) == ["duplicate_answer", "out_of_range"] for i in insts)
    assert "not a number" in message(insts[0], "out_of_range")


def test_incomplete_when_a_role_runs_into_the_time_budget(lib):
    summary, insts = read_batch(make(SLOW, count=3, seed=1, time_s=0.1))
    assert len(insts) == 1 and summary["made"] == 1 and summary["stopped_by"] == "time"
    assert codes(insts[0]) == ["incomplete"]
    assert "generate" in message(insts[0], "incomplete") and "time budget" in message(insts[0], "incomplete")
    assert any("time budget" in n for n in summary["notes"])


def test_a_role_that_raises_is_incomplete_not_a_disagreement(lib):
    summary, insts = read_batch(make("tmp.bad-compute", count=2, seed=1))
    assert [codes(i) for i in insts] == [["incomplete"]] * 2
    assert "compute is broken" in message(insts[0], "incomplete")
    assert insts[0]["evidence"][0]["complete"] is False


def test_flags_come_in_the_order_the_spec_lists_them(lib):
    src = _meta("tmp.everything", ["generate", "compute"], answer={"format": "integer", "range": [0, 5]}) + '''
def compute(params):
    return 3


def generate(rng, knobs):
    return {"params": {"a": rng.randint(1, 10**9)}, "statement": "Same.", "answer": 9}
'''
    store.write("tmp.everything", src)
    _, insts = read_batch(make("tmp.everything", count=2, seed=1))
    assert codes(insts[0]) == ["duplicate_statement", "duplicate_answer", "derivations_disagree", "out_of_range"]


# ---- duplicates and the attempt limit ---------------------------------------

def test_a_one_off_stops_after_count_times_five_attempts(lib):
    path, summary = make_batch(ONE_OFF, count=3, seed=1)
    s, insts = read_batch(path)
    assert s == summary
    assert len(insts) == 1 and s["made"] == 1 and s["attempts"] == 15 and s["duplicates_skipped"] == 14
    assert s["duplicate_attempts"] == list(range(2, 16)) and s["stopped_by"] == "attempts"
    assert any("1 distinct instance" in n and "15 attempts" in n for n in s["notes"])
    # The one instance made is flagged: its params came up again, and the repeats were skipped.
    assert codes(insts[0]) == ["duplicate_params"]
    assert "14 later attempts" in message(insts[0], "duplicate_params")


def test_a_knob_range_of_size_one_stops_after_count_times_five_attempts(lib):
    s, insts = read_batch(make("tmp.pinned", count=4, seed=1))
    assert len(insts) == 1 and s["attempts"] == 20 and s["duplicates_skipped"] == 19
    s2, insts2 = read_batch(make(CONST, count=2, seed=1, knobs={"n": 3}))  # a knob pinned to one value
    assert len(insts2) == 1 and s2["attempts"] == 10 and s2["knobs"] == {"n": 3}


def test_duplicates_are_skipped_and_generation_goes_on_until_count_distinct(lib):
    s, insts = read_batch(make("tmp.small-pool", count=3, seed=9))
    assert len(insts) == 3 and s["made"] == 3
    assert len({json.dumps(i["params"], sort_keys=True) for i in insts}) == 3
    assert s["attempts"] == 3 + s["duplicates_skipped"] and s["attempts"] <= 15
    assert s["duplicates_skipped"] >= 1  # this seed does repeat, so the skip is exercised
    assert 1 <= s["flags_by_code"]["duplicate_params"] <= 3  # each repeated instance says so, once
    assert len(s["duplicate_attempts"]) == s["duplicates_skipped"]
    assert [i["index"] for i in insts] == [1, 2, 3]
    assert [i["attempt"] for i in insts] == sorted({i["attempt"] for i in insts})


def test_a_generate_that_raises_is_counted_and_generation_goes_on(lib):
    s, insts = read_batch(make("tmp.flaky", count=4, seed=1))
    assert len(insts) == 4 and s["generate_failures"] >= 1
    assert s["attempts"] == 4 + s["generate_failures"] + s["duplicates_skipped"]
    assert any("odd draw" in n for n in s["notes"])


# ---- the other roles --------------------------------------------------------

def test_demo_is_stored_on_the_instance(lib):
    _, insts = read_batch(make("tmp.with-demo", count=2, seed=1))
    for inst in insts:
        assert inst["demo"] == {"steps": ["start", inst["params"]["a"]]}
        assert [e["button"] for e in inst["evidence"]] == ["algo_run"]  # compute only; no check role


def test_an_algorithm_with_only_generate_still_makes_a_batch(lib):
    s, insts = read_batch(make("tmp.gen-only", count=3, seed=1))
    assert len(insts) == 3 and all(i["evidence"] == [] and i["flags"] == [] for i in insts)
    assert any("compute" in n and "check" in n for n in s["notes"])


def test_stored_evidence_is_the_roles_work_without_run_specific_detail(lib):
    _, insts = read_batch(make(POWER, count=2, seed=1, time_s=60))
    for ev in insts[0]["evidence"] + insts[1]["evidence"]:
        assert ev["input"] == {} and set(ev["budget"]) == {"time_s", "stopped"} and ev["budget"]["stopped"] is False
        assert not any("in process" in n for n in ev["notes"])
    assert "produced by the check role" in insts[0]["evidence"][1]["notes"][0]
    assert str(FIX) not in json.dumps(insts) and str(lib) not in json.dumps(insts)


def test_signals_are_on_hold(lib):
    assert mk.signals_for(object()) == {}
    s, insts = read_batch(make(POWER, count=2, seed=1))
    assert "signals on hold (difficulty design pending)" in s["notes"]
    assert all(i["signals"] == {} for i in insts)


# ---- bad input --------------------------------------------------------------

@pytest.mark.parametrize("kw", [
    {"count": 0, "seed": 1}, {"count": -3, "seed": 1}, {"count": True, "seed": 1}, {"count": 2.5, "seed": 1},
    {"count": 2, "seed": -1}, {"count": 2, "seed": True}, {"count": 2, "seed": "a"},
    {"count": 2, "seed": 1, "time_s": 0}, {"count": 2, "seed": 1, "time_s": float("nan")},
    {"count": 2, "seed": 1, "knobs": {"zz": 1}}, {"count": 2, "seed": 1, "knobs": {"m": 500}},
    {"count": 2, "seed": 1, "knobs": [1]},
])
def test_bad_input_raises_and_writes_nothing(lib, kw):
    with pytest.raises(ValueError):
        make(POWER, **kw)
    assert not (lib / "batches").exists() or not list((lib / "batches").iterdir())


def test_a_missing_or_broken_algorithm_raises(lib):
    with pytest.raises(store.NoSuchAlgo):
        make("nt.nope", count=2, seed=1)
    with pytest.raises(ValueError):
        make("not an id", count=2, seed=1)
    with pytest.raises(ValueError, match="generate"):
        make("tmp.no-generate", count=2, seed=1)
    store.write("tmp.broken", "META = {}\n")
    with pytest.raises(MetaError):
        make("tmp.broken", count=2, seed=1)
    assert not (lib / "batches").exists()


# ---- the button -------------------------------------------------------------

def call(inp, **kw):
    return budget.call("mint_make", inp, in_process=True, **kw)


def test_the_button_is_registered_and_listed_as_an_mcp_tool():
    registry.load_all()
    assert registry.get("mint_make").default_time_s
    assert "mint_make" in {t.name for t in mcp_server.list_tools()}


def test_mint_make_button(lib):
    ev = call({"algo": POWER, "count": 5, "seed": 3})
    assert ev.button == "mint_make" and ev.method == "timed" and ev.complete and ev.flags == []
    assert re.fullmatch(r"made 5 of 5 instances in \d+ attempts", ev.scope)
    assert ev.seed == 3
    r = ev.result
    assert r["batch"] == f"{DAY}-power-mod-01" and Path(r["path"]) == lib / "batches" / f"{r['batch']}.jsonl"
    assert read_batch(r["path"])[0] == r["summary"] and r["summary"]["made"] == 5


def test_button_reports_a_short_batch(lib):
    ev = call({"algo": ONE_OFF, "count": 3, "seed": 1})
    assert ev.scope == "made 1 of 3 instances in 15 attempts"
    assert [f["code"] for f in ev.flags] == ["short_batch"] and ev.complete
    assert ev.result["summary"]["stopped_by"] == "attempts"


def test_button_stops_itself_at_the_time_budget(lib):
    ev = call({"algo": SLOW, "count": 5, "seed": 1, "time_s": 0.1})
    assert not ev.complete and ev.result["summary"]["stopped_by"] == "time"
    assert ev.result["summary"]["made"] == 1 and Path(ev.result["path"]).is_file()


def test_button_passes_knobs_through(lib):
    ev = call({"algo": POWER, "count": 3, "seed": 3, "knobs": {"m": 7}})
    _, insts = read_batch(ev.result["path"])
    assert all(i["params"]["m"] == 7 for i in insts) and ev.result["summary"]["knobs"] == {"m": 7}


@pytest.mark.parametrize("inp, code", [
    ({"algo": "nt.nope", "count": 2, "seed": 1}, "no_such_algo"),
    ({"algo": "not an id", "count": 2, "seed": 1}, "bad_input"),
    ({"algo": POWER, "count": 2, "seed": 1, "knobs": {"zz": 1}}, "bad_input"),
    ({"algo": POWER, "count": 2}, "bad_input"),  # the seed is required
    ({"algo": "tmp.no-generate", "count": 2, "seed": 1}, "bad_input"),
    ({"algo": "tmp.broken", "count": 2, "seed": 1}, "bad_meta"),
])
def test_button_failures_are_flagged_evidence_and_write_nothing(lib, inp, code):
    store.write("tmp.broken", "META = {}\n")
    ev = call(inp)
    assert ev.result is None and not ev.complete and [f["code"] for f in ev.flags] == [code]
    assert not (lib / "batches").exists()


def test_button_rejects_a_bad_count_before_running(lib):
    for bad in (0, "3", 2.5, 5000):
        ev = call({"algo": POWER, "count": bad, "seed": 1})
        assert [f["code"] for f in ev.flags] == ["bad_input"], bad


def test_button_in_a_child_process(lib):
    ev = budget.call("mint_make", {"algo": CONST, "count": 3, "seed": 4}, time_s=120)
    assert ev.complete and ev.flags == [], ev.to_dict()
    assert ev.budget["stopped"] is False
    assert read_batch(ev.result["path"])[0]["made"] == 3


# ---- the CLI ----------------------------------------------------------------

@pytest.fixture
def fast(monkeypatch):
    """Run buttons in process, so a CLI test does not pay for a child process."""
    real = budget.call

    def in_process(name, inp, **kw):
        kw.setdefault("in_process", True)
        return real(name, inp, **kw)

    monkeypatch.setattr(budget, "call", in_process)


def cli(capsys, *argv):
    capsys.readouterr()
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_cli_mint_make(lib, capsys, fast):
    code, out, err = cli(capsys, "mint", "make", POWER, "--count", "4", "--seed", "9", "--knob", "m=11",
                         "--knob", "a=3")
    assert code == 0, err
    ev = json.loads(out)
    assert ev["button"] == "mint_make" and ev["scope"].startswith("made 4 of 4 instances in ")
    assert ev["seed"] == 9 and ev["result"]["summary"]["knobs"] == {"m": 11, "a": 3}
    _, insts = read_batch(ev["result"]["path"])
    assert all(i["params"]["m"] == 11 and i["params"]["a"] == 3 for i in insts)


def test_cli_knob_values_are_json_or_text(lib, capsys, fast):
    src = _meta("tmp.knobby", ["generate"], knobs={"c": {"choice": ["fast", "slow"]}, "f": {"bool": True},
                                                  "x": {"float": [0, 9]}}) + '''
def generate(rng, knobs):
    return {"params": dict(knobs, a=rng.randint(0, 10**6)), "statement": "Find it.", "answer": 1}
'''
    store.write("tmp.knobby", src)
    code, out, err = cli(capsys, "mint", "make", "tmp.knobby", "--count", "1", "--seed", "1",
                         "--knob", "c=fast", "--knob", "f=true", "--knob", "x=1.5")
    assert code == 0, err
    assert json.loads(out)["result"]["summary"]["knobs"] == {"c": "fast", "f": True, "x": 1.5}


def test_cli_accepts_a_file_path_and_the_common_flags(lib, capsys, fast):
    code, out, err = cli(capsys, "mint", "make", str(FIX / "lint_const.py"), "--count", "2", "--seed", "1",
                         "--time", "60", "--pretty")
    assert code == 0, err
    assert out.startswith("{\n") and json.loads(out)["result"]["summary"]["algo"] == CONST


def test_cli_bad_knob_syntax_exits_2(lib, capsys, fast):
    code, out, err = cli(capsys, "mint", "make", POWER, "--count", "2", "--seed", "1", "--knob", "m7")
    assert code == 2 and "--knob" in err and out == ""


def test_cli_failed_make_prints_the_evidence_and_exits_2(lib, capsys, fast):
    code, out, err = cli(capsys, "mint", "make", "nt.nope", "--count", "2", "--seed", "1")
    assert code == 2
    ev = json.loads(out)
    assert ev["result"] is None and ev["flags"][0]["code"] == "no_such_algo"
    assert not (lib / "batches").exists()


def test_cli_needs_a_subcommand_and_the_required_options(lib, capsys):
    assert cli(capsys, "mint")[0] == 2
    assert cli(capsys, "mint", "make", POWER, "--seed", "1")[0] == 2   # no --count
    assert cli(capsys, "mint", "make", POWER, "--count", "2")[0] == 2  # no --seed
    assert cli(capsys, "mint", "make", "--count", "2", "--seed", "1")[0] == 2  # no algo


def test_cli_mint_make_in_a_child_process(lib, capsys):
    code, out, err = cli(capsys, "mint", "make", CONST, "--count", "2", "--seed", "5", "--time", "120")
    assert code == 0, err
    ev = json.loads(out)
    assert ev["complete"] and ev["budget"]["limit_s"] == 120
    assert read_batch(ev["result"]["path"])[0]["made"] == 2
