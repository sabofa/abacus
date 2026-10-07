import json
from pathlib import Path

from abacus import budget, mcp_server, registry
from abacus.algo.roles import Instance, run_role
from abacus.evidence import Evidence

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
    ok = run_role(FAM, "check", args={"params": params, "proposed": 7}, in_process=True)
    assert ok.result is True and ok.compare["equal"] is True
    no = run_role(FAM, "check", args={"params": params, "proposed": 8}, in_process=True)
    assert no.result is False and no.compare["equal"] is False
    assert run_role(FAM, "hand_space", args={"params": params}, in_process=True).result == 9
    miss = run_role(FAM, "demo", args={"instance": {}}, in_process=True)
    assert miss.complete is False and miss.flags[0]["code"] == "missing_role"
    assert run_role(ONE, "check", args={"params": {}, "proposed": 1}, in_process=True).flags[0]["code"] == "missing_role"


def test_bad_role_and_bad_file(tmp_path):
    assert run_role(FAM, "solution", in_process=True).flags[0]["code"] == "bad_input"
    p = tmp_path / "bad.py"
    p.write_text("META = {}\n")
    ev = run_role(p, "compute", args={"params": {}}, in_process=True)
    assert not ev.complete and ev.flags[0]["code"] == "bad_meta" and "id: missing" in ev.flags[0]["message"]


def test_compute_in_a_child_process():
    ev = run_role(FAM, "compute", args={"params": {"a": 7, "b": 9, "m": 10}}, time_s=20)
    assert ev.complete and ev.result == 7
    assert ev.budget["stopped"] is False


def test_timeout_gives_incomplete():
    ev = run_role(FIX / "slow.py", "compute", args={"params": {}}, time_s=1)
    assert ev.complete is False and ev.budget["stopped"] is True


def test_run_role_args_are_the_roles_own_and_never_splatted():
    params = {"a": 3, "b": 4, "m": 5}
    # keys that look like run_role's own keywords are just ignored role arguments, not a TypeError
    ev = run_role(FAM, "compute", args={"params": params, "seed": 1, "role": "x", "knobs": 2, "time_s": 3},
                  in_process=True)
    assert ev.complete and ev.result == 1
    ev = run_role(FAM, "generate", seed=5, args={"seed": 1}, in_process=True)
    assert ev.complete and ev.seed == 5
    bare = run_role(FAM, "compute", args=None, in_process=True)  # no params: the role raises, the budget reports it
    assert not bare.complete and bare.flags[0]["code"] == "error"


def test_the_mcp_algo_run_button_records_the_seed_it_drew():
    for in_process in (True, False):
        ev = budget.call("algo_run", {"path": str(FAM), "role": "generate"}, in_process=in_process, time_s=60)
        assert ev.complete, ev.flags
        assert isinstance(ev.seed, int) and ev.result["seed"] == ev.seed, in_process
        again = budget.call("algo_run", {"path": str(FAM), "role": "generate"}, in_process=True)
        assert again.seed != ev.seed or again.result == ev.result
        same = budget.call("algo_run", {"path": str(FAM), "role": "generate", "seed": ev.seed}, in_process=True)
        assert same.result == ev.result and same.seed == ev.seed


def test_the_mcp_algo_run_button_does_not_record_a_seed_for_other_roles():
    ev = budget.call("algo_run", {"path": str(FAM), "role": "compute", "args": {"params": {"a": 3, "b": 4, "m": 5}}},
                     in_process=True)
    assert ev.complete and ev.result == 1 and ev.seed is None


def test_mcp_call_tool_algo_run_and_args_round_trip():
    text, is_err = mcp_server.call_tool("algo_run", {"path": str(FAM), "role": "generate", "knobs": {"m": 9}})
    ev = json.loads(text)
    assert not is_err and ev["complete"] and isinstance(ev["seed"], int)
    assert ev["result"]["params"]["m"] == 9 and ev["result"]["seed"] == ev["seed"]
    text, _ = mcp_server.call_tool("algo_run", {"path": str(FAM), "role": "compute",
                                                "args": {"params": {"a": 3, "b": 4, "m": 5}}})
    assert json.loads(text)["result"] == 1


def test_algo_role_is_not_a_separate_tool_or_button():
    registry.load_all()
    names = {b.name for b in registry.all_buttons()}
    assert "algo_role" not in names and {"algo_run", "algo_lint"} <= names
    assert "algo_role" not in {t.name for t in mcp_server.list_tools()}


def test_instance_evidence_objects_serialise_as_evidence_not_repr():
    inner = Evidence(button="check", result=True, method="exhaustive", scope="by hand")
    d = Instance(params={}, statement="s", answer=1, evidence=[inner, {"already": "a dict"}]).to_dict()
    assert d["evidence"][0]["button"] == "check" and d["evidence"][0]["scope"] == "by hand"
    assert d["evidence"][1] == {"already": "a dict"}
    assert Instance.from_dict(json.loads(json.dumps(d))).evidence == d["evidence"]
