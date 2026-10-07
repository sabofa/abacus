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


def test_a_seed_the_button_drew_itself_is_kept_and_the_callers_wins():
    for in_process in (True, False):
        ev = budget.call("t_own_seed", {}, in_process=in_process, time_s=30)
        assert ev.seed == 424242 and ev.result == 424242, in_process
        ev = budget.call("t_own_seed", {"seed": 9}, in_process=in_process, time_s=30)
        assert ev.seed == 9 and ev.result == 9, in_process
    assert budget.call("t_schema", {"n": 1}, in_process=True).seed is None


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


def test_cooperative_stop_wins_race():
    ev = budget.call("t_polite", {}, time_s=1)
    assert ev.result == "mine" and ev.scope == "stopped myself"
    assert ev.budget["stopped"] is False and ev.complete is False


def test_grace_window_lets_a_late_button_deliver():
    ev = budget.call("t_polite_late", {}, time_s=1)
    assert ev.result == "mine-late" and ev.scope == "stopped myself late"
    assert ev.budget["stopped"] is False


def test_time_s_validation():
    for bad in (0, -1, float("nan"), float("inf")):
        assert "bad_input" in codes(budget.call("t_schema", {"n": 1}, time_s=bad, in_process=True))
    ev = budget.call("t_schema", {"n": 1}, time_s=10**9, in_process=True)
    assert ev.budget["limit_s"] <= budget.get_config().time_max_s


def test_seed_validation():
    for bad in (-1, 1.5, True, "7"):
        assert "bad_input" in codes(budget.call("t_seeded", {"seed": bad}, in_process=True))
    assert budget.call("t_seeded", {"seed": 0}, in_process=True).seed == 0


def test_in_process_error_keeps_partial():
    ev = budget.call("t_raise_after", {}, in_process=True)
    assert "error" in codes(ev) and ev.complete is False
    assert ev.result == 3 and ev.scope == "got to 3"


def test_startup_timeout(monkeypatch):
    monkeypatch.setattr(budget, "STARTUP_S", 0.01)
    ev = budget.call("t_schema", {"n": 1})
    assert "startup_timeout" in codes(ev) and ev.budget["stopped"] is False
    assert ev.scope.startswith("the child process did not start")
