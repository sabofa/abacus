from abacus import budget
from tests import _budget_buttons  # noqa: F401


def codes(ev):
    return [f["code"] for f in ev.flags]


def test_timeout_keeps_partial():
    ev = budget.call("t_sleep_loop", {}, time_s=1)
    assert ev.complete is False and ev.budget["stopped"] is True
    assert ev.result > 0 and ev.scope.startswith("counted to")
    assert ev.method == "search" and ev.budget["time_s"] < 5


def test_seed_drawn_and_respected():
    ev = budget.call("t_seeded", {})
    assert ev.seed is not None and ev.result == ev.seed and ev.input["seed"] == ev.seed
    ev = budget.call("t_seeded", {"seed": 7}, in_process=True)
    assert ev.seed == 7 and ev.result == 7 and ev.complete


def test_bad_input():
    ev = budget.call("t_schema", {"n": "x"})
    assert "bad_input" in codes(ev) and ev.complete is False
    assert budget.call("t_schema", {"n": 1}, in_process=True).result == 2


def test_raise():
    ev = budget.call("t_raise", {})
    assert "error" in codes(ev) and ev.complete is False
    assert "ValueError: boom" in ev.flags[0]["message"]


def test_in_process():
    ev = budget.call("t_schema", {"n": 4}, in_process=True)
    assert ev.result == 5 and ev.complete and ev.budget["mem_enforced"] is False
    assert any("in process" in n for n in ev.notes)
