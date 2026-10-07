from pathlib import Path

from abacus.algo.roles import Instance, run_role

FIX = Path(__file__).parent / "fixtures" / "algos"
FAM, ONE = FIX / "nt_power_mod.py", FIX / "one_off.py"


def test_generate_reproducible_from_seed():
    a = run_role(FAM, "generate", seed=1739201, in_process=True)
    b = run_role(FAM, "generate", seed=1739201, in_process=True)
    c = run_role(FAM, "generate", seed=1739202, in_process=True)
    assert a.complete and a.result == b.result and a.seed == 1739201
    assert a.result != c.result
    inst = Instance.from_dict(a.result)
    p = inst.params
    assert inst.algo == "nt.power-mod" and len(inst.algo_hash) == 8 and inst.seed == 1739201
    assert inst.answer == {"format": "integer", "value": pow(p["a"], p["b"], p["m"])}
    assert inst.solution is None and inst.choices is None and inst.evidence == []
    assert "$" in inst.statement


def test_generate_without_seed_records_one():
    ev = run_role(FAM, "generate", in_process=True)
    assert isinstance(ev.seed, int)
    assert run_role(FAM, "generate", seed=ev.seed, in_process=True).result == ev.result


def test_generate_respects_knobs_and_rejects_bad_ones():
    ev = run_role(FAM, "generate", seed=3, knobs={"a": 7, "b": 9, "m": 10}, in_process=True)
    assert ev.result["params"] == {"a": 7, "b": 9, "m": 10} and ev.result["answer"]["value"] == 7
    bad = run_role(FAM, "generate", seed=3, knobs={"a": 1000}, in_process=True)
    assert not bad.complete and bad.flags[0]["code"] == "bad_knobs"


def test_one_off_generates_without_knobs():
    ev = run_role(ONE, "generate", seed=1, in_process=True)
    assert ev.result["params"] == {} and ev.result["answer"]["value"] == 5050
    assert ev.result["algo"] == "misc.one-off-sum"


def test_check_hand_space_and_missing_roles():
    params = {"a": 7, "b": 9, "m": 10}
    ok = run_role(FAM, "check", params=params, proposed=7, in_process=True)
    assert ok.result is True and ok.compare["equal"] is True
    no = run_role(FAM, "check", params=params, proposed=8, in_process=True)
    assert no.result is False and no.compare["equal"] is False
    assert run_role(FAM, "hand_space", params=params, in_process=True).result == 9
    miss = run_role(FAM, "demo", instance={}, in_process=True)
    assert miss.complete is False and miss.flags[0]["code"] == "missing_role"
    assert run_role(ONE, "check", params={}, proposed=1, in_process=True).flags[0]["code"] == "missing_role"


def test_bad_role_and_bad_file(tmp_path):
    assert run_role(FAM, "solution", in_process=True).flags[0]["code"] == "bad_input"
    p = tmp_path / "bad.py"
    p.write_text("META = {}\n")
    ev = run_role(p, "compute", params={}, in_process=True)
    assert not ev.complete and ev.flags[0]["code"] == "bad_meta" and "id: missing" in ev.flags[0]["message"]


def test_compute_in_a_child_process():
    ev = run_role(FAM, "compute", params={"a": 7, "b": 9, "m": 10}, time_s=20)
    assert ev.complete and ev.result == 7
    assert ev.budget["stopped"] is False


def test_timeout_gives_incomplete():
    ev = run_role(FIX / "slow.py", "compute", params={}, time_s=1)
    assert ev.complete is False and ev.budget["stopped"] is True
