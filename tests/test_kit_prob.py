"""The probability buttons: simulate, markov (kit/04 s7-8, known answers kit/09 s1)."""
import math
import sys
import types

import numpy as np
import pytest
import sympy as sp

import abacus.kit as ak
from abacus import budget, registry

VERDICT_KEYS = {"correct", "pass", "valid", "score"}


def flags(ev):
    return [f["code"] for f in ev.flags]


def keys_of(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from keys_of(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from keys_of(v)


def no_verdict_keys(ev):
    assert not (set(keys_of(ev.to_dict(full=True))) & VERDICT_KEYS)


def stable(ev):
    d = ev.to_dict(full=True)
    d.pop("budget")
    return d


def run(name, inp, **kw):
    registry.load_all()
    return budget.call(name, inp, in_process=True, **kw)


def test_the_buttons_are_registered():
    registry.load_all()
    names = {b.name for b in registry.all_buttons()}
    assert {"simulate", "markov"} <= names
    assert registry.get("simulate").uses_seed is True


def test_surface_can_be_called_twice():
    for _ in range(2):
        ev = ak.simulate(trial="rng.randint(1, 6)", trials=100, seed=1)
        assert ev.result["trials_run"] == 100
    for _ in range(2):
        ev = ak.markov(op="stationary", matrix=[["1/2", "1/2"], ["1/2", "1/2"]])
        assert ev.result["stationary"] == {"0": "1/2", "1": "1/2"}


# ------------------------------------------------------------------------------------------------ simulate

TWO_DICE_SEVEN = "rng.randint(1, 6) + rng.randint(1, 6) == 7"


def test_two_dice_sum_seven_wilson_interval_contains_one_sixth():
    ev = run("simulate", {"trial": TWO_DICE_SEVEN, "trials": 200_000, "seed": 12345})
    r = ev.result
    lo, hi = r["ci95"]
    assert lo < 1 / 6 < hi
    assert r["trials_run"] == 200_000 and ev.complete is True
    assert ev.method == "sampled" and ev.seed == 12345 and ev.scope.strip()
    assert 0.16 < r["probability"] < 0.173 and r["successes"] == round(r["probability"] * 200_000)
    assert math.isclose(r["mean"], r["probability"])
    # the Wilson interval, not the normal one: recompute it
    n, p, z = 200_000, r["probability"], 1.959963984540054
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    assert math.isclose(lo, centre - half, rel_tol=1e-9) and math.isclose(hi, centre + half, rel_tol=1e-9)
    assert ev.precision is not None
    no_verdict_keys(ev)


def test_same_seed_reruns_identically_and_another_seed_differs():
    inp = {"trial": TWO_DICE_SEVEN, "trials": 20_000, "seed": 7}
    a, b = run("simulate", dict(inp)), run("simulate", dict(inp))
    assert stable(a) == stable(b)
    c = run("simulate", {**inp, "seed": 8})
    assert c.result["successes"] != a.result["successes"]


def test_numeric_trial_mean_interval_variance_and_histogram():
    ev = run("simulate", {"trial": "rng.randint(1, 6)", "trials": 100_000, "seed": 3})
    r = ev.result
    lo, hi = r["ci95"]
    assert lo < 3.5 < hi and abs(r["mean"] - 3.5) < 0.05
    assert abs(r["variance"] - 35 / 12) < 0.1
    assert r["trials_run"] == 100_000
    hist = {h["value"]: h["count"] for h in r["histogram"]}
    assert set(hist) == {1, 2, 3, 4, 5, 6} and sum(hist.values()) == 100_000
    assert ev.method == "sampled"
    no_verdict_keys(ev)


def test_continuous_trial_has_no_histogram():
    ev = run("simulate", {"trial": "rng.normal(2.0, 1.0)", "trials": 50_000, "seed": 1})
    assert "histogram" not in ev.result
    lo, hi = ev.result["ci95"]
    assert lo < 2.0 < hi


def test_python_random_is_available_on_the_rng():
    code = ("def trial(rng):\n"
            "    xs = list(range(5)); rng.shuffle(xs)\n"
            "    return xs[0] + rng.choice([0, 0]) + len(rng.sample(range(9), 3)) + int(rng.py.random() < 2)\n")
    ev = run("simulate", {"trial": code, "trials": 500, "seed": 5})
    assert ev.complete and ev.result["trials_run"] == 500 and "bad_input" not in flags(ev)
    assert 4 <= ev.result["mean"] <= 8
    assert isinstance(__import__("abacus.kit.simulate", fromlist=["Rng"]).Rng(1), __import__("numpy").random.Generator)


def test_vectorized_option():
    ev = run("simulate", {"trial": "lambda rng, n: rng.integers(1, 7, n) + rng.integers(1, 7, n) == 7",
                          "vectorized": True, "trials": 1_000_000, "seed": 9})
    lo, hi = ev.result["ci95"]
    assert lo < 1 / 6 < hi and ev.result["trials_run"] == 1_000_000
    ev2 = run("simulate", {"trial": "def t(rng, n):\n    return rng.normal(0, 1, n)\n", "vectorized": True,
                           "trials": 10_000, "seed": 9})
    assert ev2.result["trials_run"] == 10_000 and abs(ev2.result["mean"]) < 0.1
    again = run("simulate", {"trial": "lambda rng, n: rng.integers(1, 7, n) + rng.integers(1, 7, n) == 7",
                             "vectorized": True, "trials": 1_000_000, "seed": 9})
    assert stable(again) == stable(ev)


def test_vectorized_wrong_length_is_flagged():
    ev = run("simulate", {"trial": "lambda rng, n: rng.normal(0, 1, 3)", "vectorized": True, "trials": 100})
    assert "bad_input" in flags(ev) and ev.complete is False


def test_budget_stopped_simulation_gives_partial_estimate():
    ev = budget.call("simulate", {"trial": TWO_DICE_SEVEN, "trials": 10**12, "seed": 4}, time_s=2)
    assert ev.complete is False
    r = ev.result
    assert r and r["trials_run"] > 0 and r["ci95"][0] < r["probability"] < r["ci95"][1]
    assert "stopped" in ev.scope and ev.scope.strip()


def test_in_process_budget_stop_reports_how_far_it_got():
    ev = run("simulate", {"trial": "rng.random()", "trials": 10**12, "seed": 4}, time_s=0.5)
    assert ev.complete is False and ev.result["trials_run"] > 0
    assert str(ev.result["trials_run"]) in ev.scope.replace(",", "") or "stopped" in ev.scope


def test_proposed_gives_compare_with_z_score():
    ev = run("simulate", {"trial": TWO_DICE_SEVEN, "trials": 100_000, "seed": 11, "proposed": "1/6"})
    c = ev.compare
    assert c and set(c) >= {"proposed", "computed", "equal", "z"}
    assert abs(c["z"]) < 4 and c["equal"] is False
    ev2 = run("simulate", {"trial": TWO_DICE_SEVEN, "trials": 100_000, "seed": 11, "proposed": 0.5})
    assert abs(ev2.compare["z"]) > 50
    ev3 = run("simulate", {"trial": "rng.randint(1, 6)", "trials": 50_000, "seed": 11, "proposed": "7/2"})
    assert abs(ev3.compare["z"]) < 4
    no_verdict_keys(ev3)


def test_simulate_bad_input_is_flagged_not_raised():
    for inp in ({"trial": "rng.randint(1,"}, {"trial": "1 +"}, {"trial": "lambda a, b, c: 1"},
                 {"trial": "rng.nonsense()", "trials": 10},
                 {"trial": "'abc'", "trials": 10},
                 {"trial": "rng.randint(1, 6)", "trials": 0},
                 {"trial": "float('nan')", "trials": 10},
                 {"trial": "rng.randint(1, 6)", "trials": 10, "proposed": "not a number ??"}):
        ev = run("simulate", dict(inp))
        assert "bad_input" in flags(ev) and ev.complete is False and ev.scope.strip(), inp


def test_trial_mixing_bool_and_numbers_is_flagged():
    ev = run("simulate", {"trial": "True if rng.random() < 0.5 else 3", "trials": 200, "seed": 2})
    assert "bad_input" in flags(ev) and ev.complete is False


def test_scope_of_a_sampled_result_does_not_overclaim():
    ev = run("simulate", {"trial": TWO_DICE_SEVEN, "trials": 1000, "seed": 1})
    assert "estimate" in ev.scope and "seed 1" in ev.scope



# ------------------------------------------------------------------------- review round 1: reproducibility

def _fake_clock(step):
    state = {"t": 0.0}

    def monotonic():
        state["t"] += step
        return state["t"]
    return types.SimpleNamespace(monotonic=monotonic)


SMALL_DTYPE_TRIALS = {
    "uint8": "lambda rng, n: rng.integers(0, 2, n, dtype=np.uint8) == 1",
    "uint16": "lambda rng, n: rng.integers(0, 2, n, dtype=np.uint16) == 1",
    "bool": "lambda rng, n: rng.integers(0, 2, n, dtype=bool)",
    "uint8-values": "lambda rng, n: rng.integers(0, 200, n, dtype=np.uint8)",
    "int64": "lambda rng, n: rng.integers(1, 7, n) + rng.integers(1, 7, n)",
}


@pytest.mark.parametrize("name", sorted(SMALL_DTYPE_TRIALS))
def test_vectorized_results_do_not_depend_on_cpu_timing(name, monkeypatch):
    sim = sys.modules["abacus.kit.simulate"]
    inp = {"trial": SMALL_DTYPE_TRIALS[name], "vectorized": True, "trials": 2_000_000, "seed": 3}
    results = []
    for step in (0.0, 0.004, 0.09, 3.0):
        monkeypatch.setattr(sim, "time", _fake_clock(step))
        results.append(stable(run("simulate", dict(inp))))
    assert all(r == results[0] for r in results[1:])
    monkeypatch.undo()
    assert stable(run("simulate", dict(inp))) == results[0]


def test_scalar_results_do_not_depend_on_cpu_timing(monkeypatch):
    sim = sys.modules["abacus.kit.simulate"]
    inp = {"trial": "rng.random() * rng.randint(1, 6)", "trials": 30_000, "seed": 11}
    results = []
    for step in (0.0, 0.004, 3.0):
        monkeypatch.setattr(sim, "time", _fake_clock(step))
        results.append(stable(run("simulate", dict(inp))))
    assert all(r == results[0] for r in results[1:])


# ------------------------------------------------------------------------------- review round 1: small n

def _t95(df):
    from scipy.stats import t
    return float(t.ppf(0.975, df))


def test_two_trials_get_a_t_interval_and_an_honest_note():
    ev = run("simulate", {"trial": "rng.normal(0, 1)", "trials": 2, "seed": 1})
    r = ev.result
    assert r["trials_run"] == 2 and r["std_error"] > 0
    lo, hi = r["ci95"]
    assert math.isclose((hi - lo) / 2, _t95(1) * r["std_error"], rel_tol=1e-9)     # 12.7 standard errors, not 1.96
    assert (hi - lo) / 2 > 12 * r["std_error"]
    assert math.isclose(ev.precision["ci95_halfwidth"], (hi - lo) / 2)
    assert "Student" in r["interval"] and "1 degree" in r["interval"]
    assert any("not reliable" in n for n in ev.notes)


def test_the_multiplier_follows_the_degrees_of_freedom_and_settles_to_the_normal_value():
    for n, df in ((5, 4), (10, 9), (29, 28), (60, 59)):
        ev = run("simulate", {"trial": "rng.normal(0, 1)", "trials": n, "seed": 2})
        lo, hi = ev.result["ci95"]
        assert math.isclose((hi - lo) / 2 / ev.result["std_error"], _t95(df), rel_tol=1e-9), n
    ev = run("simulate", {"trial": "rng.normal(0, 1)", "trials": 20_000, "seed": 2})
    lo, hi = ev.result["ci95"]
    assert math.isclose((hi - lo) / 2 / ev.result["std_error"], 1.959963984540054, rel_tol=2e-4)
    assert not any("reliable" in n for n in ev.notes)


def test_few_trials_note_below_thirty_but_not_at_thirty():
    assert any("not reliable" in n for n in run("simulate", {"trial": "rng.normal(0, 1)", "trials": 29,
                                                            "seed": 2}).notes)
    assert not any("not reliable" in n for n in run("simulate", {"trial": "rng.normal(0, 1)", "trials": 30,
                                                                "seed": 2}).notes)


def test_a_zero_variance_sample_has_a_flagged_interval_and_no_infinite_z():
    ev = run("simulate", {"trial": "5", "trials": 100, "seed": 1, "proposed": 6})
    r = ev.result
    assert r["variance"] == 0 and r["ci95"] == [5, 5]
    assert any("not reliable" in n and "identical" in n for n in ev.notes)
    c = ev.compare
    assert c["z"] is None and c["standard_error"] == 0
    assert any("z-score" in n or "z score" in n for n in ev.notes)
    for p in (5, "5", 5.5, 0):
        ev = run("simulate", {"trial": "5", "trials": 100, "seed": 1, "proposed": p})
        assert ev.compare["z"] is None
        assert not any(isinstance(v, float) and not math.isfinite(v) for v in ev.compare.values())
    # a bool trial whose proposed probability is 0 or 1 has a zero standard error too
    for p in (0, 1):
        ev = run("simulate", {"trial": "rng.random() < 0.5", "trials": 100, "seed": 1, "proposed": p})
        assert ev.compare["z"] is None and any("z-score" in n for n in ev.notes)


def test_dice_intervals_still_contain_the_truth_at_every_size():
    ev = run("simulate", {"trial": TWO_DICE_SEVEN, "trials": 200_000, "seed": 12345})
    assert ev.result["ci95"][0] < 1 / 6 < ev.result["ci95"][1]
    for n, seed in ((40, 3), (500, 4), (100_000, 5)):
        ev = run("simulate", {"trial": "rng.randint(1, 6)", "trials": n, "seed": seed})
        lo, hi = ev.result["ci95"]
        assert lo < 3.5 < hi, (n, lo, hi)


def test_one_trial_has_no_interval_claim_beyond_infinity_and_a_note():
    ev = run("simulate", {"trial": "rng.normal(0, 1)", "trials": 1, "seed": 1, "proposed": 0})
    assert ev.result["std_error"] is None and ev.compare["z"] is None
    assert any("not reliable" in n for n in ev.notes)


# ------------------------------------------------------------------------------------ review round 1: the Rng

def test_rng_spawn_gives_independent_deterministic_children():
    sim = sys.modules["abacus.kit.simulate"]
    kids = sim.Rng(5).spawn(3)
    assert len(kids) == 3 and all(isinstance(k, sim.Rng) and hasattr(k, "py") for k in kids)
    draws = [(k.random(), k.integers(0, 10**9), k.randint(1, 10**9)) for k in kids]
    assert len(set(draws)) == 3
    again = [(k.random(), k.integers(0, 10**9), k.randint(1, 10**9)) for k in sim.Rng(5).spawn(3)]
    assert draws == again
    assert [k.random() for k in sim.Rng(6).spawn(3)] != [d[0] for d in draws]


def test_rng_survives_deepcopy_copy_and_pickle_with_both_streams():
    import copy
    import pickle
    sim = sys.modules["abacus.kit.simulate"]
    base = sim.Rng(3)
    base.random(), base.integers(0, 9, 4)              # advance both streams
    for clone in (copy.deepcopy(base), copy.copy(base), pickle.loads(pickle.dumps(base))):
        assert isinstance(clone, sim.Rng) and clone is not base and clone.py is not base.py
        probe = copy.deepcopy(base)
        assert clone.random() == probe.random()
        assert clone.integers(0, 10**9, 3).tolist() == probe.integers(0, 10**9, 3).tolist()
        assert clone.py.random() == probe.py.random()
        assert clone.randint(1, 10**6) == probe.randint(1, 10**6)
    # the clone is independent: advancing it leaves the original alone
    snap = copy.deepcopy(base)
    clone = copy.deepcopy(base)
    clone.py.random(), clone.integers(0, 9, 10)
    assert base.py.random() == snap.py.random() and base.integers(0, 10**9) == snap.integers(0, 10**9)


def test_rng_sample_accepts_sets_frozensets_and_mixed_sets():
    sim = sys.modules["abacus.kit.simulate"]
    r = sim.Rng(8)
    s = {3, 1, 2, 9, 7}
    got = r.sample(s, 3)
    assert len(got) == 3 and len(set(got)) == 3 and set(got) <= s
    assert sim.Rng(8).sample(s, 3) == got                                  # deterministic, sorted before sampling
    assert sim.Rng(8).sample(s, 3) == sim.Rng(8).sample(sorted(s), 3)
    assert set(r.sample(frozenset("abcdef"), 4)) <= set("abcdef")
    mixed = {1, "a", (2, 3)}                                               # not comparable: iteration order
    assert set(r.sample(mixed, 2)) <= mixed
    assert len(r.sample({}.keys() | {5, 6}, 2)) == 2
    assert r.sample([1, 2, 3], 2) and r.sample(range(5), 5) and r.sample("abc", 1)


def test_a_trial_can_sample_from_a_set():
    ev = run("simulate", {"trial": "len(rng.sample({1, 2, 3, 4, 5}, 2))", "trials": 50, "seed": 2})
    assert ev.complete and ev.result["mean"] == 2 and "bad_input" not in flags(ev)


# ------------------------------------------------------------------------------------------------ markov

def R(x, y=None):
    return sp.Rational(x) if y is None else sp.Rational(x, y)


def exact(ev):
    return ev.method == "symbolic"


def coin_chain(pattern):
    """Suffix-state chain for a fair coin until `pattern` appears; the states are the matched prefixes."""
    states = [pattern[:i] for i in range(len(pattern) + 1)]

    def nxt(s, c):
        t = s + c
        while t and not pattern.startswith(t):
            t = t[1:]
        return t
    rows = []
    for s in states:
        row = [0] * len(states)
        if s == pattern:
            row[-1] = 1
        else:
            for c in "HT":
                row[states.index(nxt(s, c))] += R("1/2")
        rows.append([str(v) for v in row])
    return states, rows


@pytest.mark.parametrize("pattern,expected", [("HH", 6), ("HT", 4), ("HHH", 14), ("HTH", 10)])
def test_expected_flips_to_see_a_pattern_matrix(pattern, expected):
    states, rows = coin_chain(pattern)
    ev = run("markov", {"op": "hitting", "matrix": rows, "states": states, "start": "", "target": [pattern]})
    assert exact(ev) and ev.complete and ev.scope.strip()
    assert sp.sympify(ev.result["from_start"]) == expected
    assert sp.sympify(ev.result["expected_steps"][""]) == expected
    assert sp.sympify(ev.result["expected_steps"][pattern]) == 0
    assert any("exact" in n for n in ev.notes)
    no_verdict_keys(ev)


def test_expected_flips_to_see_hh_from_a_step_function_and_a_predicate():
    step = ("def step(s):\n"
            "    if s == 'HH': return [(s, 1)]\n"
            "    nxt = {'': ('', 'H'), 'H': ('', 'HH')}[s]\n"
            "    return [(nxt[0], '1/2'), (nxt[1], '1/2')]\n")
    ev = run("markov", {"op": "hitting", "start": "", "step": step, "target": "state == 'HH'"})
    assert exact(ev) and sp.sympify(ev.result["from_start"]) == 6
    ev2 = run("markov", {"op": "hitting", "start": "", "step": step, "target": ["HH"]})
    assert sp.sympify(ev2.result["from_start"]) == 6


def test_hitting_is_infinite_where_the_target_is_not_reached_surely():
    # 0 -> 1 or 2 (absorbing, not the target); the target is 1
    m = [["0", "1/2", "1/2"], ["0", "1", "0"], ["0", "0", "1"]]
    ev = run("markov", {"op": "hitting", "matrix": m, "target": [1]})
    assert ev.result["expected_steps"]["0"] == "inf" and ev.result["expected_steps"]["1"] == 0
    assert ev.result["expected_steps"]["2"] == "inf"


def test_rock_paper_scissors_has_value_zero_and_uniform_strategy():
    m = [[0, -1, 1], [1, 0, -1], [-1, 1, 0]]
    ev = run("markov", {"op": "game", "matrix": m})
    assert exact(ev) and ev.complete
    assert ev.result["value"] == 0
    third = [sp.Rational(1, 3)] * 3
    assert [sp.sympify(x) for x in ev.result["row_strategy"]] == third
    assert [sp.sympify(x) for x in ev.result["col_strategy"]] == third
    assert ev.result["verified_exactly"] is True
    no_verdict_keys(ev)


def test_game_with_saddle_point_and_with_a_fractional_value():
    ev = run("markov", {"op": "game", "matrix": [[3, 2], [1, 4]]})   # mixed: value 5/2
    assert sp.sympify(ev.result["value"]) == R("5/2")
    assert [sp.sympify(x) for x in ev.result["row_strategy"]] == [R("3/4"), R("1/4")]
    assert [sp.sympify(x) for x in ev.result["col_strategy"]] == [R("1/2"), R("1/2")]
    ev = run("markov", {"op": "game", "matrix": [[4, 2], [3, 1]]})   # saddle at (0, 1): value 2
    assert ev.result["value"] == 2
    assert [sp.sympify(x) for x in ev.result["row_strategy"]] == [1, 0]
    assert [sp.sympify(x) for x in ev.result["col_strategy"]] == [0, 1]
    ev = run("markov", {"op": "game", "matrix": [["1/2", "-3/2", 2], [-1, 1, "0.5"]]})
    assert ev.result["verified_exactly"] is True


def test_game_float_entries_and_large_games_fall_back_to_floats():
    import numpy as np
    big = np.random.default_rng(0).integers(-5, 6, size=(45, 45)).tolist()
    ev = run("markov", {"op": "game", "matrix": big})
    assert ev.method == "numeric" and ev.complete
    assert abs(sum(ev.result["row_strategy"]) - 1) < 1e-8 and abs(sum(ev.result["col_strategy"]) - 1) < 1e-8
    assert any("float" in n for n in ev.notes)
    ev = run("markov", {"op": "game", "matrix": [[0.1234567890123456789, -1.5], [2.718281828459045, 0.3]]})
    assert ev.method == "numeric" and isinstance(ev.result["value"], float)


def gamblers_ruin(n, p="1/2"):
    q = str(1 - R(p))
    rows = []
    for i in range(n + 1):
        row = ["0"] * (n + 1)
        if i in (0, n):
            row[i] = "1"
        else:
            row[i + 1], row[i - 1] = p, q
        rows.append(row)
    return rows


def test_gamblers_ruin_absorption_is_i_over_n():
    N = 10
    ev = run("markov", {"op": "absorb", "matrix": gamblers_ruin(N)})
    assert exact(ev) and ev.complete
    for i in range(1, N):
        assert sp.sympify(ev.result["absorption"][str(i)][str(N)]) == R(i) / N
        assert sp.sympify(ev.result["absorption"][str(i)]["0"]) == 1 - R(i) / N
    assert sp.sympify(ev.result["expected_steps"]["3"]) == 3 * 7      # i (N - i)
    assert ev.result["absorbing"] == ["0", str(N)]
    assert ev.result["absorption"]["0"] == {"0": 1}


def test_gamblers_ruin_with_a_step_function_and_from_start():
    step = ("def step(i):\n"
            "    if i in (0, 8): return []\n"
            "    return [(i + 1, '1/2'), (i - 1, '1/2')]\n")
    ev = run("markov", {"op": "absorb", "start": 3, "step": step})
    assert exact(ev) and any("absorbing" in n for n in ev.notes)
    assert sp.sympify(ev.result["from_start"]["8"]) == R(3, 8)
    # an unfair walk: p = 2/3 to win: ((q/p)^i - 1) / ((q/p)^N - 1)
    step = ("def step(i):\n"
            "    if i in (0, 5): return [(i, 1)]\n"
            "    return [(i + 1, '2/3'), (i - 1, '1/3')]\n")
    ev = run("markov", {"op": "absorb", "start": 2, "step": step})
    r = R(1, 2)
    assert sp.sympify(ev.result["from_start"]["5"]) == (r ** 2 - 1) / (r ** 5 - 1)


def test_absorption_into_a_closed_class_of_several_states():
    m = [["1/2", "1/2", 0, 0], [0, 0, "1/2", "1/2"], [0, 0, 0, 1], [0, 0, 1, 0]]
    ev = run("markov", {"op": "absorb", "matrix": m})
    assert exact(ev)
    # state 0 loops until it moves to 1; from 1 it enters the class {2,3}
    keys = list(ev.result["absorption"]["0"])
    assert len(keys) == 1 and sp.sympify(ev.result["absorption"]["0"][keys[0]]) == 1
    assert "2" in keys[0] and "3" in keys[0]


def test_three_state_stationary_distribution():
    m = [["1/2", "1/2", 0], ["1/4", "1/2", "1/4"], [0, "1/2", "1/2"]]
    ev = run("markov", {"op": "stationary", "matrix": m})
    assert exact(ev) and ev.complete
    got = [sp.sympify(ev.result["stationary"][k]) for k in ("0", "1", "2")]
    assert got == [R("1/4"), R("1/2"), R("1/4")]
    assert ev.result["recurrent_classes"][0]["period"] == 1


def test_stationary_with_floats_and_with_two_classes_and_periodic():
    ev = run("markov", {"op": "stationary", "matrix": [[0.9, 0.1], [0.5, 0.5]]})
    assert exact(ev) and sp.sympify(ev.result["stationary"]["0"]) == R("5/6")
    ev = run("markov", {"op": "stationary", "matrix": [[1, 0, 0], [0, "1/2", "1/2"], [0, "1/2", "1/2"]]})
    assert ev.result["stationary"] is None and len(ev.result["recurrent_classes"]) == 2
    assert any("recurrent classes" in n for n in ev.notes)
    ev = run("markov", {"op": "stationary", "matrix": [[0, 1], [1, 0]]})
    assert ev.result["recurrent_classes"][0]["period"] == 2 and any("period" in n for n in ev.notes)


def test_stationary_of_a_transient_state_is_zero():
    ev = run("markov", {"op": "stationary", "matrix": [["1/2", "1/2"], [0, 1]]})
    assert ev.result["stationary"] == {"0": 0, "1": 1}


def test_optimal_stopping_two_dice_rolls():
    # roll a fair die; you may take it or roll once more and keep that: value 17/4
    step = "[(k, '1/6') for k in range(1, 7)]"
    ev = run("markov", {"op": "stop", "start": 0, "step": step, "payoff": "state", "horizon": 2})
    assert exact(ev) and ev.complete
    assert sp.sympify(ev.result["value_at_start"]) == R("17/4")
    ev = run("markov", {"op": "stop", "start": 0, "step": step, "payoff": "state", "horizon": 3})
    assert sp.sympify(ev.result["value_at_start"]) == R("14/3")      # 1/6 sum max(k, 17/4)
    by_t = {b["t"]: b for b in ev.result["by_time"]}
    assert by_t[1]["stop"] == ["5", "6"]                             # roll again below 4.25 with two rolls left
    assert by_t[2]["stop"] == ["4", "5", "6"]                        # 3.5 with one left
    assert by_t[3]["stop"] == ["1", "2", "3", "4", "5", "6"]         # forced at the horizon


def test_optimal_stopping_matrix_chain_with_table_and_discount():
    # two states, always move to the other one; payoff table; discount 1/2
    m = [[0, 1], [1, 0]]
    ev = run("markov", {"op": "stop", "matrix": m, "payoff": {"0": 1, "1": 4}, "horizon": 2, "discount": "1/2"})
    # t=2: V=(1,4); t=1: V0=max(1, 1/2*4)=2, V1=max(4, 1/2*1)=4; t=0: V0=max(1, 1/2*4)=2, V1=4
    assert exact(ev)
    assert {k: sp.sympify(v) for k, v in ev.result["value"].items()} == {"0": 2, "1": 4}
    assert ev.result["policy"] == {"0": "continue", "1": "stop"}
    assert ev.result["horizon"] == 2 and sp.sympify(ev.result["discount"]) == R("1/2")


def test_stop_horizon_zero_and_required_inputs():
    ev = run("markov", {"op": "stop", "start": 0, "step": "[(0, 1)]", "payoff": "state + 5", "horizon": 0})
    assert sp.sympify(ev.result["value_at_start"]) == 5
    ev = run("markov", {"op": "stop", "start": 0, "step": "[(0, 1)]", "payoff": "state"})
    assert "bad_input" in flags(ev) and ev.complete is False


def test_unparseable_chains_are_flagged():
    cases = [
        {"op": "stationary", "matrix": [[0.5, 0.5], [1]]},                 # not square
        {"op": "stationary", "matrix": [["1/2", "1/3"], ["1/2", "1/2"]]},    # row does not sum to 1
        {"op": "stationary", "matrix": [["x", "y"], ["1/2", "1/2"]]},        # not numbers
        {"op": "stationary", "matrix": [[-0.5, 1.5], [0.5, 0.5]]},           # negative
        {"op": "stationary", "matrix": []},
        {"op": "stationary"},                                                # no chain
        {"op": "hitting", "matrix": [[1]], "target": [7]},                   # unknown target state
        {"op": "hitting", "matrix": [[1]]},                                  # no target
        {"op": "absorb", "start": 0, "step": "[(1,"},                        # code does not parse
        {"op": "absorb", "start": 0, "step": "1 / 0"},                       # code raises
        {"op": "absorb", "start": 0, "step": "[(1, 'x')]"},                  # bad probability
        {"op": "absorb", "start": 0, "step": "[({}, 1)]"},                   # unhashable state
        {"op": "absorb", "start": 0, "step": "[(1, '1/2')]"},                # row sums to 1/2
        {"op": "absorb", "step": "[(1, 1)]"},                                # step without start
        {"op": "absorb", "matrix": [[1]], "states": [1, 2]},                 # wrong number of labels
        {"op": "game", "matrix": [[1, 2], [3]]},
        {"op": "game", "matrix": []},
    ]
    for inp in cases:
        ev = run("markov", dict(inp))
        assert "bad_input" in flags(ev) and ev.complete is False and ev.scope.strip(), inp
        no_verdict_keys(ev)


def test_unknown_op_is_rejected_by_the_schema():
    ev = run("markov", {"op": "bogus"})
    assert "bad_input" in flags(ev) and ev.complete is False


def test_exact_below_200_states_and_float_above_with_a_note():
    def cycle(n):   # a deterministic-ish walk on a cycle, lazy: stationary is uniform
        rows = []
        for i in range(n):
            row = ["0"] * n
            row[i] = "1/2"
            row[(i + 1) % n] = "1/2"
            rows.append(row)
        return rows
    ev = run("markov", {"op": "stationary", "matrix": cycle(200)})
    assert exact(ev) and any("exact" in n and "200" in n for n in ev.notes)
    assert sp.sympify(ev.result["stationary"]["17"]) == R(1, 200)
    ev = run("markov", {"op": "stationary", "matrix": cycle(201)})
    assert ev.method == "numeric" and ev.precision
    assert any("float" in n and "200" in n for n in ev.notes)
    assert abs(ev.result["stationary"]["17"] - 1 / 201) < 1e-12
    # floats that are not simple fractions switch to float arithmetic too
    ev = run("markov", {"op": "stationary", "matrix": [[0.123456789012345678, 0.876543210987654322],
                                                       [0.5, 0.5]]})
    assert ev.method == "numeric" and any("float" in n for n in ev.notes)
    assert abs(ev.result["stationary"]["0"] - 0.5 / (0.5 + 0.876543210987654322)) < 1e-12
    ev = run("markov", {"op": "hitting", "matrix": [[0.5, 0.25, 0.2500000001], [0, 1, 0], [0, 0, 1]],
                        "target": [1, 2]})
    assert ev.method == "numeric" and any("float" in n for n in ev.notes)
    assert abs(ev.result["expected_steps"]["0"] - 2) < 1e-6


def test_one_third_floats_are_read_as_one_third():
    ev = run("markov", {"op": "stationary", "matrix": [[1 / 3, 1 / 3, 1 / 3]] * 3})
    assert exact(ev) and sp.sympify(ev.result["stationary"]["0"]) == R(1, 3)
    assert any("fraction" in n for n in ev.notes)


def test_state_cap_is_flagged():
    ev = run("markov", {"op": "hitting", "start": 0, "step": "[(state + 1, 1)]", "target": [-1]})
    assert "state_cap" in flags(ev) and ev.complete is False
    assert "5000" in ev.scope and ev.scope.strip()
    ev = run("markov", {"op": "absorb", "start": 0, "step": "[(state + 1, '1/2'), (state + 2, '1/2')]",
                        "max_states": 50})
    assert "state_cap" in flags(ev) and "50" in ev.scope


def test_float_chain_of_a_few_thousand_states_runs():
    # a 3000-state chain walks forward, slows at the end: expected hitting time of the last state
    n = 3000
    step = f"[(state, 0.5), (state + 1, 0.5)] if state < {n} else [(state, 1)]"
    ev = run("markov", {"op": "hitting", "start": 0, "step": step, "target": f"state == {n}"})
    assert ev.method == "numeric" and ev.complete
    assert abs(ev.result["from_start"] - 2 * n) < 1e-6
    assert any("float" in n_ for n_ in ev.notes)


def test_tuple_states_and_json_style_lists():
    step = ("def step(s):\n"
            "    a, b = s\n"
            "    if a == 2: return [(s, 1)]\n"
            "    return [((a + 1, b), '1/2'), ((a, b + 1), '1/2')] if b < 1 else [((a + 1, b), 1)]\n")
    ev = run("markov", {"op": "hitting", "start": [0, 0], "step": step, "target": "state[0] == 2"})
    assert exact(ev) and ev.complete
    # E(a,1) = 2 - a, E(1,0) = 1 + E(1,1)/2 = 3/2, E(0,0) = 1 + E(1,0)/2 + E(0,1)/2 = 11/4
    assert sp.sympify(ev.result["from_start"]) == R("11/4")
    assert "(0, 0)" in ev.result["expected_steps"]


def test_proposed_compare_for_markov():
    states, rows = coin_chain("HH")
    ev = run("markov", {"op": "hitting", "matrix": rows, "states": states, "start": "", "target": ["HH"],
                        "proposed": 6})
    assert ev.compare and ev.compare["equal"] is True
    ev = run("markov", {"op": "hitting", "matrix": rows, "states": states, "start": "", "target": ["HH"],
                        "proposed": "5"})
    assert ev.compare["equal"] is False
    ev = run("markov", {"op": "game", "matrix": [[0, -1, 1], [1, 0, -1], [-1, 1, 0]], "proposed": "0"})
    assert ev.compare["equal"] is True


def _op_cases():
    """One input per op, each with a matrix form or a step-function form (whose states are found by search)."""
    states, rows = coin_chain("HT")
    step = ("def step(s):\n"
            "    if s == 'HT': return [(s, 1)]\n"
            "    nxt = {'': ('', 'H'), 'H': ('H', 'HT')}[s]\n"
            "    return [(nxt[0], '1/2'), (nxt[1], '1/2')]\n")
    walk = ("def step(i):\n"
            "    if i in (0, 6): return []\n"
            "    return [(i + 1, '1/3'), (i - 1, '2/3')]\n")
    big = np.random.default_rng(3).integers(-9, 10, size=(45, 45)).tolist()      # solved in floats
    return {
        "absorb-matrix": {"op": "absorb", "matrix": gamblers_ruin(6)},
        "absorb-step": {"op": "absorb", "start": 3, "step": walk},
        "hitting-matrix": {"op": "hitting", "matrix": rows, "states": states, "start": "", "target": ["HT"]},
        "hitting-step": {"op": "hitting", "start": "", "step": step, "target": "state == 'HT'"},
        "stationary-matrix": {"op": "stationary", "matrix": [["1/2", "1/2", 0], ["1/4", "1/2", "1/4"],
                                                              [0, "1/2", "1/2"]]},
        "stationary-step": {"op": "stationary", "start": "", "step": step},
        "stop-step": {"op": "stop", "start": 0, "step": "[(k, '1/6') for k in range(1, 7)]", "payoff": "state",
                      "horizon": 3},
        "stop-matrix": {"op": "stop", "matrix": [[0, 1], [1, 0]], "payoff": {"0": 1, "1": 4}, "horizon": 2},
        "game-exact": {"op": "game", "matrix": [[3, 2], [1, 4]]},
        "game-float": {"op": "game", "matrix": big},
    }


@pytest.mark.parametrize("case", sorted(_op_cases()))
def test_every_markov_op_is_deterministic(case):
    inp = _op_cases()[case]
    a, b = run("markov", dict(inp)), run("markov", dict(inp))
    assert a.complete and not a.flags
    assert stable(a) == stable(b)


def test_markov_is_deterministic_across_processes_with_string_states():
    # a fresh process has a fresh string hash seed, so anything that leans on set or dict-of-set order would show
    states, rows = coin_chain("HHT")
    inp = {"op": "absorb", "matrix": rows, "states": states}
    a, b = budget.call("markov", dict(inp), time_s=60), budget.call("markov", dict(inp), time_s=60)
    assert a.complete and stable(a) == stable(b)


# ------------------------------------------------------------------------- review round 1: float to fraction

def test_nums_accepts_only_a_float_that_is_a_few_ulps_from_a_simple_fraction():
    from fractions import Fraction
    from abacus.kit.markov import Nums
    for x, want in ((0.3333333333333333, Fraction(1, 3)), (0.1666666666666667, Fraction(1, 6)),
                    (0.6666666666666666, Fraction(2, 3)), (0.25, Fraction(1, 4)), (0.1, Fraction(1, 10))):
        assert Nums().num(x, "x") == want
    nums = Nums()
    assert nums.num(0.3333333333333333, "x") == Fraction(1, 3) and nums.simplified and nums.clean
    # a tiny probability is itself, never 0, and a near-one is never 1
    for x in (3.333333333333333e-14, 0.9999999999999667, 1.2345678901234568e-9, 0.12345678901234568):
        nums = Nums()
        got = nums.num(x, "x")
        assert got != 0 and float(got) == x and nums.simplified is False and nums.clean is False, x
    # random 17-digit floats are essentially never taken for simple fractions
    changed = 0
    for x in np.random.default_rng(0).random(2000).tolist():
        nums = Nums()
        nums.num(x, "x")
        changed += nums.simplified
    assert changed <= 2


def test_a_tiny_escape_probability_gives_a_huge_hitting_time_not_inf():
    m = [[0.9999999999999667, 3.33e-14], [0, 1]]
    ev = run("markov", {"op": "hitting", "matrix": m, "target": [1]})
    assert ev.method == "numeric" and ev.complete and ev.precision
    got = ev.result["expected_steps"]["0"]
    assert got != math.inf and math.isclose(got, 1 / 3.33e-14, rel_tol=1e-6)
    assert any("float" in n and "not simple fractions" in n for n in ev.notes)
    ev = run("markov", {"op": "hitting", "matrix": [[0.9999999999999667, 3.333333333333333e-14], [0, 1]],
                        "target": [1]})
    assert math.isclose(ev.result["expected_steps"]["0"], 3e13, rel_tol=1e-2)


def test_game_reads_long_floats_as_fractions_and_says_so():
    ev = run("markov", {"op": "game", "matrix": [[0.3333333333333333, 1], [1, 0.6666666666666666]]})
    assert exact(ev) and sp.sympify(ev.result["value"]) == R(7, 9)
    assert any("nearest simple fraction" in n for n in ev.notes)


def test_game_float_matrix_does_not_claim_a_fraction_it_did_not_read():
    ev = run("markov", {"op": "game", "matrix": [[0.1234567890123456789, -1.5], [2.718281828459045, 0.3]]})
    assert ev.method == "numeric" and not any("nearest simple fraction" in n for n in ev.notes)


def test_a_long_float_proposed_is_snapped_with_a_note_only_when_it_is_a_few_ulps_away():
    m = [[1, 0], [0, 1]]
    ev = run("markov", {"op": "game", "matrix": m, "proposed": 0.5000000000000001})
    assert ev.compare["equal"] is True
    assert any("proposed" in n and "nearest simple fraction" in n for n in ev.notes)
    for far in (0.5000000000001, 0.123456789012345678):
        ev = run("markov", {"op": "game", "matrix": m, "proposed": far})
        assert ev.compare["equal"] is False
        assert not any("proposed" in n and "nearest simple fraction" in n for n in ev.notes)


def test_a_matrix_over_max_states_reports_its_own_size_and_cap():
    ev = run("markov", {"op": "stationary", "matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "max_states": 2})
    assert "state_cap" in flags(ev) and ev.complete is False
    assert "3" in ev.scope and "2" in ev.scope and "5000" not in ev.scope
    assert "search from the start" not in ev.scope and "matrix" in ev.scope
    ev = run("markov", {"op": "stationary", "matrix": [[1, 0], [0, 1]], "max_states": 1})
    assert "2" in ev.scope and "1" in ev.scope and "5000" not in ev.scope


# ------------------------------------------------------------------------- review round 1: time budgets

def _dense_chain(n, seed=0):
    w = np.random.default_rng(seed).integers(1, 10, size=(n, n))
    return [[f"{int(v)}/{int(row.sum())}" for v in row] for row in w]


def _is_float_result_with_note(ev):
    return (ev.result is not None and ev.method == "numeric" and "exact_timeout" in flags(ev)
            and any("exact arithmetic exceeded the time budget; floats used" in n for n in ev.notes))


def test_dense_exact_chain_over_its_budget_falls_back_to_floats_or_is_flagged():
    ev = budget.call("markov", {"op": "stationary", "matrix": _dense_chain(150)}, time_s=3)
    if ev.result is None or ev.complete is False:
        assert "stopped_before_result" in flags(ev) and ev.scope.strip()
        return
    assert _is_float_result_with_note(ev) and ev.precision
    dist = list(ev.result["stationary"].values())
    assert abs(sum(dist) - 1) < 1e-9 and min(dist) >= -1e-12


def test_exact_stationary_timeout_in_process_gives_the_float_answer():
    ev = run("markov", {"op": "stationary", "matrix": _dense_chain(200, 1)}, time_s=3)
    assert ev.complete and _is_float_result_with_note(ev), (ev.scope, flags(ev), ev.notes)
    dist = ev.result["stationary"]
    assert len(dist) == 200 and abs(sum(dist.values()) - 1) < 1e-9
    assert not any(n.startswith("exact rational arithmetic") for n in ev.notes)
    assert any("floating point" in n for n in ev.notes)


def test_exact_hitting_and_absorb_timeouts_fall_back_too():
    n = 160
    rows = _dense_chain(n, 2)
    rows[n - 1] = ["0"] * (n - 1) + ["1"]            # the last state absorbs
    for op, inp in (("hitting", {"op": "hitting", "matrix": rows, "target": [n - 1]}),
                    ("absorb", {"op": "absorb", "matrix": rows})):
        ev = run("markov", inp, time_s=3)
        assert ev.complete and _is_float_result_with_note(ev), (op, ev.scope, flags(ev))


def test_exact_game_timeout_falls_back_to_linprog_with_the_note():
    from abacus.kit.markov import _linprog_game
    g = np.random.default_rng(5).integers(1, 10**14, size=(40, 40))
    A = [[f"{int(v)}/{10**14}" for v in row] for row in g]
    ev = run("markov", {"op": "game", "matrix": A}, time_s=3)
    assert ev.complete and _is_float_result_with_note(ev), (ev.scope, flags(ev), ev.notes)
    assert ev.result["verified_exactly"] is False
    vf, _, _ = _linprog_game(g / 10**14)
    assert abs(ev.result["value"] - vf) < 1e-9
    assert abs(sum(ev.result["row_strategy"]) - 1) < 1e-9


def test_a_state_search_the_budget_stops_is_flagged_as_stopped_before_a_result():
    ev = run("markov", {"op": "hitting", "start": 0, "step": "[(state + 1, 1)]", "target": [-1],
                        "max_states": 10**9}, time_s=0.5)
    assert ev.complete is False and "stopped_before_result" in flags(ev)
    assert "before" in ev.scope and "result" in ev.scope


def test_exact_arithmetic_within_budget_is_unchanged_and_unflagged():
    ev = run("markov", {"op": "stationary", "matrix": gamblers_ruin(8)}, time_s=30)
    assert exact(ev) and not flags(ev) and not any("exceeded" in n for n in ev.notes)
