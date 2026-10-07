"""The discrete-math buttons: enumerate, sequence, counterexample (kit/04 s4-6, known answers kit/09 s1)."""
import collections
import itertools
import math

import pytest
import sympy as sp

import abacus.kit as ak
from abacus import budget, registry
from abacus.config import get_config

VERDICT_KEYS = {"correct", "pass", "valid", "score"}
ANY_BUTTON_NAMES = ("enumerate", "sequence", "counterexample")


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


def test_the_three_buttons_are_registered():
    registry.load_all()
    names = {b.name for b in registry.all_buttons()}
    assert set(ANY_BUTTON_NAMES) <= names
    assert registry.get("counterexample").uses_seed is True
    assert registry.get("enumerate").uses_seed is False


def test_surface_can_be_called_twice():
    # the submodule named like the button must not shadow the callable on abacus.kit
    for _ in range(2):
        assert ak.enumerate(space={"permutations": 3}).result["count"] == 6
    for _ in range(2):
        assert ak.sequence(terms=[1, 2, 3, 4, 5, 6, 7]).method == "fit"
    for _ in range(2):
        ev = ak.counterexample(claim="n < 5", domain={"n": [0, 9]}, mode="exhaustive")
        assert ev.result["counterexamples"][0] == {"n": 5}


# ----------------------------------------------------------------------------------------------- enumerate

DERANGED = "all(x[i] != i for i in range(len(x)))"


def test_derangements_of_5_is_44():
    ev = ak.enumerate(space={"permutations": 5}, where=DERANGED)
    assert ev.result["count"] == 44 and ev.result["space_size"] == 120
    assert ev.method == "exhaustive" and ev.complete is True and ev.scope.strip()
    assert ev.flags == []
    assert ev.examples and all(all(p[i] != i for i in range(5)) for p in ev.examples)
    assert ev.examples[0] == (1, 0, 3, 4, 2) or list(ev.examples[0]) == [1, 0, 3, 4, 2]
    no_verdict_keys(ev)


def test_lattice_paths_to_5_5_is_252():
    ev = ak.enumerate(space={"lattice_paths": {"to": [5, 5], "steps": [[1, 0], [0, 1]]}})
    assert ev.result["count"] == 252 and ev.result["space_size"] == 252
    ev = ak.enumerate(space={"lattice_paths": {"to": [5, 5]}})  # steps default to right and up
    assert ev.result["count"] == 252


def test_lattice_paths_with_a_condition_and_other_steps():
    # never above the diagonal: Catalan(5) = 42; the object is the tuple of points visited
    ev = ak.enumerate(space={"lattice_paths": {"to": [5, 5]}}, where="all(px >= py for px, py in x)")
    assert ev.result["count"] == 42
    # Dyck-like paths with up/down steps, 2n steps ending at height 0, never below 0
    ev = ak.enumerate(space={"lattice_paths": {"to": [8, 0], "steps": [[1, 1], [1, -1]]}},
                      where="all(py >= 0 for px, py in x)")
    assert ev.result["count"] == 14 and ev.result["space_size"] == 70
    # Delannoy number D(3, 3) = 63
    ev = ak.enumerate(space={"lattice_paths": {"to": [3, 3], "steps": [[1, 0], [0, 1], [1, 1]]}})
    assert ev.result["count"] == 63


def test_lattice_paths_that_could_run_forever_are_bad_input():
    ev = ak.enumerate(space={"lattice_paths": {"to": [3, 3], "steps": [[1, 0], [-1, 0]]}})
    assert "bad_input" in flags(ev) and ev.complete is False and ev.scope.strip()


def test_sweep_derangements_1_to_6():
    ev = ak.enumerate(space={"permutations": "n"}, where=DERANGED, sweep={"n": [1, 6]})
    assert ev.result["counts"] == [0, 1, 2, 9, 44, 265]
    assert ev.result["sweep"] == {"n": [1, 2, 3, 4, 5, 6]}
    assert ev.result["space_size"] == [1, 2, 6, 24, 120, 720]
    assert ev.complete and ev.method == "exhaustive"
    assert "count" not in ev.result


def test_sweep_variable_is_visible_in_where_and_in_a_product():
    ev = ak.enumerate(space={"product": {"a": [1, "n"], "b": [1, "n"]}}, where="a < b",
                      sweep={"n": [1, 5]})
    assert ev.result["counts"] == [0, 1, 3, 6, 10]
    ev = ak.enumerate(space={"product": {"a": [1, 6]}}, where="a % n == 0", sweep={"n": [1, 4]})
    assert ev.result["counts"] == [6, 3, 2, 1]
    ev = ak.enumerate(space={"product": {"a": [1, 6]}},
                      where="def where(a):\n    return a % n == 0", sweep={"n": [1, 4]})
    assert ev.result["counts"] == [6, 3, 2, 1]


def test_group_by_gives_a_distribution():
    ev = ak.enumerate(space={"product": {"d1": [1, 6], "d2": [1, 6]}}, group_by="d1 + d2")
    dist = ev.result["distribution"]
    assert dist == {str(s): 6 - abs(s - 7) for s in range(2, 13)}
    assert list(dist) == [str(s) for s in range(2, 13)]  # natural order of the keys
    assert ev.result["count"] == 36 and ev.result["distinct_keys"] == 11
    assert "distribution" in ev.result and ev.complete


def test_group_by_with_where_and_a_function():
    ev = ak.enumerate(space={"permutations": 4}, where="x[0] != 0",
                      group_by="def group_by(x):\n    return sum(1 for i, v in enumerate(x) if v == i)")
    want = collections.Counter(sum(1 for i, v in enumerate(p) if v == i)
                               for p in itertools.permutations(range(4)) if p[0] != 0)
    assert ev.result["distribution"] == {str(k): want[k] for k in sorted(want)}
    assert ev.result["count"] == 18 == sum(ev.result["distribution"].values())


def test_sweep_with_group_by_gives_a_distribution_per_value():
    ev = ak.enumerate(space={"words": {"alphabet": "HT", "length": "n"}}, group_by="x.count('H')",
                      sweep={"n": [1, 3]})
    assert ev.result["distributions"] == [{"0": 1, "1": 1}, {"0": 1, "1": 2, "2": 1}, {"0": 1, "1": 3, "2": 3, "3": 1}]


@pytest.mark.parametrize("space,size,where,expected", [
    ({"product": {"a": [1, 20], "b": [1, 20]}}, 400, "a * b == 36", 7),
    ({"combinations": {"of": 6, "k": 3}}, 20, None, 20),
    ({"combinations": {"of": ["a", "b", "c", "d"], "k": 2}}, 6, "'a' in x", 3),
    ({"subsets": 5}, 32, "sum(x) == 5", 4),
    ({"subsets": [1, 2, 3, 4, 5]}, 32, "sum(x) == 5", 3),
    ({"compositions": {"n": 5, "parts": 3}}, 6, None, 6),
    ({"compositions": {"n": 6, "parts": 3}}, 10, "max(x) == 4", 3),
    ({"partitions": 10}, 42, None, 42),
    ({"partitions": 6}, 11, "len(x) == 3", 3),
    ({"words": {"alphabet": "HT", "length": 10}}, 1024, "x.count('H') == 5", 252),
    ({"graphs": {"n": 4}}, 64, "len(x) == 3", 20),
    ({"graphs": {"n": 3}}, 8, "len(x) >= 2 and n == 3", 4),
    ({"permutations": ["a", "b", "c"]}, 6, "x[0] == 'a'", 2),
    ({"code": "def space():\n    for i in range(10):\n        yield i * i"}, None, "x % 2 == 0", 5),
])
def test_other_spaces(space, size, where, expected):
    inp = {"space": space}
    if where:
        inp["where"] = where
    ev = ak.enumerate(**inp)
    assert ev.result["count"] == expected, ev.flags
    assert ev.result["space_size"] == size
    assert ev.complete and ev.scope.strip() and ev.flags == []


def test_partitions_match_sympy_up_to_20():
    for n in (0, 1, 2, 5, 12, 20):
        assert ak.enumerate(space={"partitions": n}).result["count"] == sp.functions.combinatorial.numbers.partition(n)


def test_a_where_function_over_named_vars():
    ev = ak.enumerate(space={"product": {"a": [1, 20], "b": [1, 20]}},
                      where="def where(a, b):\n    return math.gcd(a, b) == 1")
    assert ev.result["count"] == sum(1 for a in range(1, 21) for b in range(1, 21) if math.gcd(a, b) == 1)
    ev = ak.enumerate(space={"product": {"a": [1, 20], "b": [1, 20]}}, where="lambda a, b: a + b == 20")
    assert ev.result["count"] == 19


def test_product_examples_are_named_and_capped():
    ev = ak.enumerate(space={"product": {"a": [1, 20], "b": [1, 20]}}, where="a * b == 36")
    assert ev.examples[0] == {"a": 2, "b": 18}
    ev = ak.enumerate(space={"product": {"a": [1, 40]}}, where="a > 0")
    assert len(ev.examples) <= get_config().max_examples


def test_proposed_is_compared():
    ev = ak.enumerate(space={"permutations": 5}, where=DERANGED, proposed=44)
    assert ev.compare == {"proposed": 44, "computed": 44, "equal": True}
    ev = ak.enumerate(space={"permutations": 5}, where=DERANGED, proposed=45)
    assert ev.compare["equal"] is False and ev.compare["computed"] == 44
    assert ak.enumerate(space={"permutations": 5}).compare is None
    ev = ak.enumerate(space={"permutations": "n"}, where=DERANGED, sweep={"n": [1, 4]}, proposed=[0, 1, 2, 9])
    assert ev.compare["equal"] is True


def test_the_scope_names_the_space_and_what_was_checked():
    ev = ak.enumerate(space={"product": {"a": [1, 20], "b": [1, 20]}}, where="a < b")
    assert "400" in ev.scope and "a" in ev.scope


def test_bad_enumerate_input_is_flagged_not_raised():
    for inp in (
        {"space": {"nonsense": 3}},
        {"space": {"permutations": 3, "subsets": 2}},
        {"space": {"permutations": -1}},
        {"space": {"permutations": 3}, "where": "x[0] == "},
        {"space": {"permutations": 3}, "where": "undefined_name > 1"},
        {"space": {"product": {"a": [1, 3]}}, "where": "def where(q, r):\n    return True"},
        {"space": {"product": {"a": [5, 1.5]}}},
        {"space": {"product": {"a": [1, 3]}}, "sweep": {"a": [1, 3]}},
        {"space": {"permutations": "n"}},
        {"space": {"permutations": "n"}, "sweep": {"n": [1, 2], "m": [1, 2]}},
        {"space": {"words": {"alphabet": "", "length": 2}}},
        {"space": {"code": "x = 3"}},
        {"space": {"permutations": 3}, "group_by": "[x]"},
    ):
        ev = ak.enumerate(**inp)
        assert "bad_input" in flags(ev) and ev.complete is False and ev.scope.strip(), inp
        assert ev.method == "exhaustive"
        no_verdict_keys(ev)


def test_a_where_that_fails_part_way_reports_the_object_and_what_was_counted():
    ev = ak.enumerate(space={"product": {"a": [0, 5]}}, where="10 // (a - 3) < 0")
    assert "bad_input" in flags(ev) and ev.complete is False and ev.scope.strip()
    assert ev.result["count"] == 3  # a = 0, 1, 2 counted, then a = 3 divides by zero
    msg = ev.flags[0]["message"]
    assert "ZeroDivisionError" in msg and "a" in msg and "3" in msg


def test_space_too_large_is_flagged_and_it_still_runs():
    inp = {"space": {"product": {"a": [1, 10**6], "b": [1, 10**6], "c": [1, 10**6]}},
           "where": "(a * b + c) % 7 == 0"}
    ev = run("enumerate", inp, time_s=1)
    assert "space_too_large" in flags(ev)
    assert ev.complete is False and ev.scope.strip()
    assert ev.result["count"] > 0 and ev.result["space_size"] == "1000000000000000000"
    assert "stopped" in ev.scope
    assert ev.budget["time_s"] < 6
    no_verdict_keys(ev)


def test_a_small_space_is_not_flagged():
    assert "space_too_large" not in flags(ak.enumerate(space={"permutations": 6}, where=DERANGED))


def test_budget_stopped_big_enumeration_in_a_child_process():
    inp = {"space": {"product": {"a": [1, 10**6], "b": [1, 10**6]}}, "where": "(a * b) % 7 == 3"}
    ev = budget.call("enumerate", inp, time_s=2)
    assert ev.complete is False and ev.scope.strip()
    assert ev.budget["time_s"] < 15
    assert ev.method == "exhaustive"
    # a starved child can be killed before its first partial; it then says so, and that is the only way out
    assert "before any progress" in ev.scope or "stopped before any progress" in ev.scope or (
        ev.result["count"] > 0 and "space_too_large" in flags(ev) and "stopped" in ev.scope), ev.scope
    no_verdict_keys(ev)


def test_a_stopped_sweep_keeps_the_values_it_finished():
    ev = run("enumerate", {"space": {"permutations": "n"}, "where": DERANGED, "sweep": {"n": [1, 14]}}, time_s=1)
    assert ev.complete is False
    done = ev.result["counts"]
    assert done == [0, 1, 2, 9, 44, 265, 1854, 14833, 133496][:len(done)] and 3 <= len(done) < 14
    assert ev.result["sweep"]["n"] == list(range(1, len(done) + 1))
    assert "in_progress" in ev.result and ev.result["in_progress"]["n"] == len(done) + 1
    assert "space_too_large" in flags(ev)


def test_a_huge_permutation_space_does_not_hang_the_size_estimate():
    ev = run("enumerate", {"space": {"permutations": 5000}, "where": "x[0] == 0"}, time_s=1)
    assert "space_too_large" in flags(ev) and ev.complete is False


def test_group_by_with_too_many_keys_is_truncated_honestly():
    ev = ak.enumerate(space={"product": {"a": [1, 3000]}}, group_by="a")
    assert ev.result["distinct_keys"] == 3000 and len(ev.result["distribution"]) <= 1000
    assert any("distribution" in n for n in ev.notes)


# ----------------------------------------------------------------------------------------------- sequence

def candidates(ev, form=None):
    cs = ev.result["candidates"]
    return [c for c in cs if form is None or c["form"] == form]


def test_catalan_terms_give_catalan_with_the_holdout_right():
    ev = ak.sequence(terms=[1, 1, 2, 5, 14, 42, 132])
    cat = [c for c in candidates(ev, "known sequence") if "catalan" in c["expression"].lower()]
    assert cat, ev.result
    assert cat[0]["held_out"] == 3 and cat[0]["held_out_tested"] == 3 and cat[0]["fitted_on"] == 4
    assert ev.method == "fit" and ev.scope.strip() and ev.complete
    assert ev.result["holdout"] == 3
    no_verdict_keys(ev)


def test_fibonacci_gives_a_recurrence_a_gf_and_the_known_sequence():
    terms = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]
    ev = ak.sequence(terms=terms)
    assert any("fibonacci" in c["expression"].lower() for c in candidates(ev, "known sequence"))
    rec = candidates(ev, "linear recurrence")
    assert rec and rec[0]["held_out"] == 3 == rec[0]["held_out_tested"]
    assert "a(n-1)" in rec[0]["expression"] and "a(n-2)" in rec[0]["expression"]
    gf = candidates(ev, "rational generating function")
    assert gf
    x = sp.Symbol("x")
    series = sp.series(sp.sympify(gf[0]["expression"]), x, 0, 10).removeO()
    assert [series.coeff(x, i) for i in range(10)] == terms


def test_a_polynomial_is_found_by_finite_differences():
    ev = ak.sequence(terms=[n**3 - n for n in range(0, 10)])
    poly = candidates(ev, "polynomial")
    assert poly and poly[0]["held_out"] == poly[0]["held_out_tested"] == 3
    n = sp.Symbol("n")
    assert sp.expand(sp.sympify(poly[0]["expression"]) - (n**3 - n)) == 0


def test_offset_shifts_the_index():
    ev = ak.sequence(terms=[n**2 for n in range(5, 15)], offset=5)
    poly = candidates(ev, "polynomial")[0]
    n = sp.Symbol("n")
    assert sp.expand(sp.sympify(poly["expression"]) - n**2) == 0
    assert ev.result["offset"] == 5


def test_a_hypergeometric_term_is_found():
    ev = ak.sequence(terms=[math.factorial(n) for n in range(0, 12)])
    hyp = candidates(ev, "hypergeometric")
    assert hyp and hyp[0]["held_out"] == hyp[0]["held_out_tested"] == 3
    ev = ak.sequence(terms=[math.comb(2 * n, n) // (n + 1) for n in range(0, 16)])
    assert candidates(ev, "hypergeometric")


def test_code_with_n_range():
    ev = ak.sequence(code="n**3 - n", n_range=[0, 12])
    assert candidates(ev, "polynomial") and ev.result["offset"] == 0
    ev = ak.sequence(code="def f(n):\n    return 2**n + 1", n_range=[3, 14])
    assert ev.result["offset"] == 3 and ev.result["terms"] == 12
    assert any(c["held_out"] == 3 for c in ev.result["candidates"])


def test_zero_holdout_candidates_are_marked_unsupported():
    ev = ak.sequence(terms=[1, 1, 2, 5, 14, 42, 132], holdout=0)
    cs = ev.result["candidates"]
    assert cs
    for c in cs:
        assert c["held_out"] == 0 and c["held_out_tested"] == 0 and c["fitted_on"] == 7
        assert "unsupported" in c["note"]
    assert any("unsupported" in n for n in ev.notes)


def test_a_holdout_larger_than_the_list_is_lowered_and_says_so():
    ev = ak.sequence(terms=[1, 4, 9, 16], holdout=9)
    assert ev.result["holdout"] == 1 and ev.result["holdout_requested"] == 9 and ev.result["fit_terms"] == 3
    assert any("holdout" in n and "lowered" in n for n in ev.notes)
    ev = ak.sequence(terms=[1, 4], holdout=9)
    assert ev.result["holdout"] == 0 and any("too few" in n for n in ev.notes) and ev.complete


def test_nothing_fits_random_terms_and_the_scope_says_what_was_tried():
    terms = [3, 141, 59, 26, 5358, 97, 9323, 84, 62, 6, 4, 338, 327, 9502]
    ev = ak.sequence(terms=terms)
    assert ev.result["candidates"] == [] and ev.result["refuted"] >= 1
    assert ev.scope.strip() and ev.complete


def test_rational_terms_are_accepted():
    ev = ak.sequence(terms=["1", "1/2", "1/4", "1/8", "1/16", "1/32", "1/64", "1/128"])
    rec = candidates(ev, "linear recurrence")
    assert rec and rec[0]["held_out"] == 3


def test_the_sequence_button_does_not_phone_oeis_when_the_network_is_off(monkeypatch):
    import urllib.request

    def boom(*a, **k):
        raise AssertionError("the network was used")

    monkeypatch.delenv("ABACUS_NETWORK", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    ev = ak.sequence(terms=[1, 1, 2, 5, 14, 42, 132])
    assert "oeis" not in ev.result and "network_failed" not in flags(ev)


def test_bad_sequence_input_is_flagged():
    for inp in (
        {},
        {"terms": []},
        {"terms": ["x", 1, 2]},
        {"terms": [1.5, 2, 3]},
        {"terms": [1, 2, 3], "holdout": -1},
        {"code": "n"},
        {"code": "n +", "n_range": [0, 5]},
        {"code": "n", "n_range": [5, 0]},
        {"terms": [1, 2, 3], "code": "n", "n_range": [0, 5]},
        {"code": "1 // (n - 2)", "n_range": [0, 5]},
        {"terms": list(range(2000))},
    ):
        ev = ak.sequence(**inp)
        assert "bad_input" in flags(ev) and ev.complete is False and ev.scope.strip(), inp


# ----------------------------------------------------------------------------------------------- counterexample

def test_n_squared_plus_n_plus_41_fails_first_at_40():
    ev = ak.counterexample(claim="sp.isprime(n**2 + n + 41)", domain={"n": [0, 100]}, mode="exhaustive")
    assert ev.result["counterexamples"][0] == {"n": 40}
    assert ev.method == "exhaustive" and ev.scope.strip()
    assert ev.examples[0] == {"n": 40}
    no_verdict_keys(ev)
    ev = ak.counterexample(claim="sp.isprime(n**2 + n + 41)", domain={"n": [0, 100]}, mode="exhaustive", k=1)
    assert ev.result["counterexamples"] == [{"n": 40}] and ev.result["checked"] == 41
    assert "40" in ev.scope or "41" in ev.scope  # says where it stopped


def test_no_counterexample_is_not_reported_as_true():
    ev = ak.counterexample(claim="n * n >= 0", domain={"n": [-5, 5]}, mode="exhaustive")
    assert ev.result["counterexamples"] == [] and ev.result["checked"] == 11
    assert ev.method == "exhaustive" and ev.complete is True
    low = ev.scope.lower()
    assert "11" in ev.scope and "true" not in low and "proves" not in low and "holds for all" not in low
    ev = ak.counterexample(claim="x * x >= 0", domain={"x": {"real": [-1, 1]}}, mode="random", samples=500, seed=1)
    assert ev.result["counterexamples"] == [] and ev.method == "sampled"
    assert "not" in ev.scope.lower() and "sampled" in ev.scope.lower()


def test_exhaustive_over_two_variables_is_in_lexicographic_order():
    ev = ak.counterexample(claim="a * b != 6", domain={"a": [1, 6], "b": [1, 6]}, mode="exhaustive", k=10)
    assert ev.result["counterexamples"] == [{"a": 1, "b": 6}, {"a": 2, "b": 3}, {"a": 3, "b": 2}, {"a": 6, "b": 1}]
    assert ev.result["checked"] == 36


def test_margin_for_an_inequality_gives_the_closest_calls():
    ev = ak.counterexample(claim="x * x >= 2 * x - 1", margin="x * x - (2 * x - 1)",
                           domain={"x": [-3, 5]}, mode="exhaustive")
    assert ev.result["counterexamples"] == []
    closest = ev.result["closest"]
    assert closest[0] == {"point": {"x": 1}, "margin": 0}
    assert [c["margin"] for c in closest] == sorted(c["margin"] for c in closest)
    assert closest[1]["margin"] == 1 and {c["point"]["x"] for c in closest[1:3]} == {0, 2}
    ev = ak.counterexample(claim="x <= 3", margin="3 - x", domain={"x": [0, 6]}, mode="exhaustive", k=2)
    assert ev.result["counterexamples"] == [{"x": 4}, {"x": 5}]
    assert ev.result["closest"][0] == {"point": {"x": 5}, "margin": -2}


def test_margin_alone_defines_the_claim_as_margin_nonnegative():
    ev = ak.counterexample(margin="x - 3", domain={"x": [0, 6]}, mode="exhaustive", k=10)
    assert [c["x"] for c in ev.result["counterexamples"]] == [0, 1, 2]
    assert ev.result["closest"][0]["margin"] == -3
    ev = ak.counterexample(domain={"x": [0, 6]})
    assert "bad_input" in flags(ev)


def test_margin_on_reals_reports_how_close_a_true_inequality_came():
    ev = ak.counterexample(margin="(a - b) ** 2",
                           domain={"a": {"real": [0, 1]}, "b": {"real": [0, 1]}}, mode="random", samples=2000, seed=3)
    assert ev.result["counterexamples"] == []
    assert all(c["margin"] >= 0 for c in ev.result["closest"])
    assert len(ev.result["closest"]) >= 3
    assert ev.result["closest"][0]["margin"] < 0.01


def test_random_mode_is_seeded_and_reruns_are_identical():
    inp = dict(claim="x < 0.999", domain={"x": {"real": [0, 1]}, "n": [1, 10**6]}, mode="random",
               samples=3000, seed=5, k=3)
    a, b = ak.counterexample(**inp), ak.counterexample(**inp)
    assert stable(a) == stable(b) and a.seed == 5
    inp2 = dict(inp, seed=6)
    assert stable(ak.counterexample(**inp2)) != stable(a)
    inp = dict(claim="x * x != 0.25", margin="abs(x * x - 0.25)", domain={"x": {"real": [0, 1]}},
               mode="random", samples=500, seed=11)
    assert stable(ak.counterexample(**inp)) == stable(ak.counterexample(**inp))
    # seeded through the budget wrapper too, and the seed drawn for an unseeded call is recorded
    ev = budget.call("counterexample", dict(claim="x < 0.9", domain={"x": {"real": [0, 1]}}, mode="random",
                                           samples=100), in_process=True)
    assert isinstance(ev.seed, int)


def test_random_finds_a_real_counterexample():
    ev = ak.counterexample(claim="x * x < 0.25", domain={"x": {"real": [0, 1]}}, mode="random", samples=1000, seed=2)
    cx = ev.result["counterexamples"]
    assert cx and all(c["x"] ** 2 >= 0.25 for c in cx) and ev.method == "sampled"


def test_random_mode_tries_the_corners_of_the_domain():
    # only the endpoint x = 0 breaks this claim; uniform sampling would essentially never hit it
    ev = ak.counterexample(claim="x > 0", domain={"x": {"real": [0, 1]}}, mode="random", samples=50, seed=1)
    assert ev.result["counterexamples"][0] == {"x": 0}


def test_integer_random_sampling_and_a_sampler_and_values():
    ev = ak.counterexample(claim="n % 7 != 0", domain={"n": [1, 10**9]}, mode="random", samples=200, seed=4)
    assert ev.result["counterexamples"] or ev.result["checked"] == 200
    ev = ak.counterexample(claim="n % 7 != 0", domain={"n": {"sampler": "lambda rng: rng.randint(1, 10**6)"}},
                           mode="random", samples=500, seed=4)
    assert ev.result["counterexamples"] and all(c["n"] % 7 == 0 for c in ev.result["counterexamples"])
    ev = ak.counterexample(claim="p > 3", domain={"p": {"values": [2, 3, 5, 7]}}, mode="exhaustive", k=9)
    assert ev.result["counterexamples"] == [{"p": 2}, {"p": 3}]
    ev = ak.counterexample(claim="len(w) < 4", domain={"w": {"sampler": "def sample(rng):\n    return 'a' * rng.randint(1, 5)"}},
                           mode="random", samples=100, seed=1)
    assert ev.result["counterexamples"]


def test_both_mode_is_exhaustive_when_the_domain_is_small_and_finite():
    ev = ak.counterexample(claim="n < 50", domain={"n": [0, 99]}, mode="both", k=1000, seed=1)
    assert ev.method == "exhaustive" and ev.result["checked"] == 100 and len(ev.result["counterexamples"]) == 50
    assert "100" in ev.scope
    # mixed finite and real: the exhaustive part is skipped and the note says so
    ev = ak.counterexample(claim="n + x < 100", domain={"n": [0, 99], "x": {"real": [0, 1]}}, mode="both",
                           samples=300, seed=1)
    assert ev.method == "sampled" and any("exhaustive" in n for n in ev.notes)
    assert ev.result["checked"] <= 300 + 64


def test_both_mode_samples_when_the_finite_domain_is_too_big():
    ev = run("counterexample", dict(claim="n != 123456789012", domain={"n": [1, 10**15]}, mode="both", seed=1,
                                    samples=5000), time_s=3)
    assert ev.method == "sampled" and ev.result["checked"] > 0
    # the exhaustive pass takes up to half the time, then hands over to 5000 random points and the 2 corners
    assert ev.complete and "gave way to sampling" in ev.scope and "seed 1" in ev.scope
    assert "5000 random points sampled" in ev.scope and "2 corner points" in ev.scope
    first = int(ev.scope.split("the first ")[1].split(" ")[0])
    assert first > 0 and ev.result["checked"] == first + 5000 + 2


def test_exhaustive_needs_a_finite_domain():
    ev = ak.counterexample(claim="x > -1", domain={"x": {"real": [0, 1]}}, mode="exhaustive")
    assert "bad_input" in flags(ev) and ev.complete is False and ev.scope.strip()


def test_a_stopped_counterexample_search_says_how_far_it_got():
    ev = run("counterexample", dict(claim="n >= 0", domain={"n": [0, 10**12]}, mode="exhaustive"), time_s=1)
    assert ev.complete is False and ev.method == "exhaustive"
    assert ev.result["checked"] > 1000 and "stopped" in ev.scope
    ev = budget.call("counterexample", dict(claim="n >= 0", domain={"n": [0, 10**12]}, mode="exhaustive"), time_s=2)
    assert ev.complete is False and ev.scope.strip()
    assert "before any progress" in ev.scope or "stopped before any progress" in ev.scope or (
        ev.result["checked"] > 0 and "stopped" in ev.scope), ev.scope
    no_verdict_keys(ev)


def test_claim_errors_at_a_point_are_counted_not_fatal():
    ev = ak.counterexample(claim="1 / x > 0", domain={"x": [-2, 3]}, mode="exhaustive", k=10)
    assert ev.result["errored"] == 1 and "claim_error" in flags(ev)
    assert [c["x"] for c in ev.result["counterexamples"]] == [-2, -1]
    assert ev.result["checked"] == 6


def test_bad_counterexample_input_is_flagged():
    for inp in (
        {"claim": "n >", "domain": {"n": [0, 3]}},
        {"claim": "undefined_name > 1", "domain": {"n": [0, 3]}},
        {"claim": "n > 1", "domain": {}},
        {"claim": "n > 1", "domain": {"n": [3, 0]}},
        {"claim": "n > 1", "domain": {"n": [0.5, 3]}},
        {"claim": "n > 1", "domain": {"n": {"real": [2, 1]}}},
        {"claim": "n > 1", "domain": {"n": {"mystery": 1}}},
        {"claim": "n > 1", "domain": {"n": {"sampler": "lambda"}}, "mode": "random"},
        {"claim": "n > 1", "domain": {"n": [0, 3]}, "margin": "n +"},
        {"claim": "n > 1", "domain": {"n": [0, 3]}, "samples": 0},
        {"claim": "n > 1", "domain": {"def": [0, 3]}},
        {"claim": "n > 1", "domain": {"n": [0, 3]}, "k": 0},
    ):
        ev = ak.counterexample(**inp)
        assert "bad_input" in flags(ev) and ev.complete is False and ev.scope.strip(), inp
        no_verdict_keys(ev)


def test_no_verdict_keys_in_any_result():
    evs = [
        ak.enumerate(space={"permutations": 5}, where=DERANGED, proposed=44),
        ak.enumerate(space={"product": {"a": [1, 6]}}, group_by="a % 2"),
        ak.sequence(terms=[1, 1, 2, 5, 14, 42, 132]),
        ak.sequence(terms=[1, 1, 2, 5, 14, 42, 132], holdout=0),
        ak.counterexample(claim="n < 5", domain={"n": [0, 9]}, mode="exhaustive"),
        ak.counterexample(claim="x < 1", margin="1 - x", domain={"x": {"real": [0, 2]}}, mode="random", samples=50, seed=1),
        ak.enumerate(space={"nope": 1}),
    ]
    for ev in evs:
        no_verdict_keys(ev)
        assert ev.scope.strip()


def test_a_lattice_too_big_to_count_is_flagged_and_does_not_hang():
    ev = run("enumerate", {"space": {"lattice_paths": {"to": [3000, 3000]}}}, time_s=1)
    assert "space_too_large" in flags(ev) and ev.complete is False and ev.scope.strip()
    assert ev.budget["time_s"] < 6


def test_sequence_with_no_structure_is_fast_and_lists_nothing():
    import random
    rnd = random.Random(1)
    ev = ak.sequence(terms=[rnd.randint(1, 10**10) for _ in range(400)])
    assert ev.result["candidates"] == [] and ev.complete and ev.budget["time_s"] < 8


# ------------------------------------------------------------------------------------------------ T4 review round 1

def test_a_margin_error_does_not_hide_the_claim():
    ev = ak.counterexample(claim="x != 0", margin="1/x", domain={"x": [-2, 2]}, mode="exhaustive")
    assert ev.result["counterexamples"] == [{"x": 0}]
    assert ev.result["margin_errors"] == 1 and ev.result["errored"] == 0 and ev.result["checked"] == 5
    assert ev.complete is True
    flag = next(f for f in ev.flags if f["code"] == "margin_error")
    assert "margin" in flag["message"] and "claim was still evaluated" in flag["message"]
    assert "claim_error" not in flags(ev)
    # the points that had a margin still feed closest
    assert {c["point"]["x"] for c in ev.result["closest"]} <= {-2, -1, 1, 2}


def test_a_margin_alone_that_errors_names_the_margin_not_the_claim():
    ev = ak.counterexample(margin="1/x", domain={"x": [-1, 1]}, mode="exhaustive")
    assert ev.result["errored"] == 1 and ev.result["margin_errors"] == 0
    msg = next(f["message"] for f in ev.flags if f["code"] == "claim_error")
    assert "margin" in msg and "no claim was given" in msg


def test_a_result_truncated_by_k_says_so():
    ev = ak.counterexample(claim="n < 5", domain={"n": [0, 99]}, mode="exhaustive", k=3)
    assert ev.result["capped_at_k"] is True and len(ev.result["counterexamples"]) == 3
    assert "capped_at_k" not in ak.counterexample(claim="n < 500", domain={"n": [0, 99]}, mode="exhaustive").result


def order_41_terms(count):
    a = list(range(1, 42))                      # a(n) = a(n-1) + a(n-41), a genuine order-41 recurrence
    while len(a) < count:
        a.append(a[-1] + a[-41])
    return a


def test_a_search_stopped_by_its_caps_says_so():
    ev = ak.sequence(terms=order_41_terms(200))
    assert ev.result["candidates"] == [] and ev.complete
    assert "recurrence<=40" in ev.result["capped"]
    assert any("limits" in n and "recurrence<=40" in n for n in ev.notes)
    plain = ak.sequence(terms=[1, 1, 2, 5, 14, 42, 132])
    assert "capped" not in plain.result and not any("limits" in n for n in plain.notes)


def test_a_polynomial_above_the_degree_cap_says_so():
    ev = ak.sequence(terms=[n ** 35 for n in range(60)])
    assert "polynomial_degree<=30" in ev.result["capped"]


def test_five_squares_are_found_with_a_lowered_holdout_and_thin_evidence_is_noted():
    ev = ak.sequence(terms=[1, 4, 9, 16, 25])
    assert ev.result["holdout"] == 2 and ev.result["fit_terms"] == 3 and ev.result["holdout_requested"] == 3
    poly = candidates(ev, "polynomial")
    assert poly and poly[0]["held_out"] == 2 and poly[0]["held_out_tested"] == 2
    assert any("holdout lowered from 3 to 2" in n for n in ev.notes)
    assert any("thin evidence" in n for n in ev.notes)
    # a long list is untouched
    long = ak.sequence(terms=[n * n for n in range(20)])
    assert long.result["holdout"] == 3 and not any("thin evidence" in n or "lowered" in n for n in long.notes)


def test_candidates_pinned_by_every_term_are_counted_not_listed():
    ev = ak.sequence(terms=[1, 1, 2, 5, 14, 42, 132], holdout=0)
    assert ev.result["unlisted_unsupported"] >= 1
    assert not candidates(ev, "polynomial")          # degree 6 on 7 terms: any 7 numbers fit it
    assert any("not listed" in n for n in ev.notes)
    assert "unlisted_unsupported" not in ak.sequence(terms=[1, 1, 2, 5, 14, 42, 132]).result


def test_a_code_space_that_hit_the_budget_is_flagged_after_the_fact():
    code = "def space():\n    n = 0\n    while True:\n        yield n\n        n += 1"
    ev = run("enumerate", {"space": {"code": code}, "where": "x % 3 == 0"}, time_s=1)
    assert ev.complete is False
    msg = next(f["message"] for f in ev.flags if f["code"] == "space_too_large")
    assert "unknown" in msg
    done = ak.enumerate(space={"code": "def space():\n    yield from range(5)"})
    assert "space_too_large" not in flags(done) and done.complete


def test_a_lattice_sizing_timeout_is_not_called_more_than_10_to_300(monkeypatch):
    from abacus.kit import enumerate as _w  # noqa: F401  (the wrapper; the module is below)
    import sys
    mod = sys.modules["abacus.kit.enumerate"]
    real = mod._lattice_ways
    monkeypatch.setattr(mod, "_lattice_ways", lambda steps, w, target, deadline=0: (None, "timeout"))
    ev = ak.enumerate(space={"lattice_paths": {"to": [3, 3]}}, where="True")
    msg = next(f["message"] for f in ev.flags if f["code"] == "space_too_large")
    assert "timed out" in msg and "10^300" not in msg
    monkeypatch.setattr(mod, "_lattice_ways", real)


def test_repeated_items_are_counted_by_position_and_say_so():
    ev = ak.enumerate(space={"combinations": {"of": [1, 1, 2], "k": 2}})
    assert ev.result["count"] == 3 and any("by position" in n for n in ev.notes)
    assert any("by position" in n for n in ak.enumerate(space={"permutations": [1, 1, 2]}).notes)
    assert not any("by position" in n for n in ak.enumerate(space={"permutations": [1, 2, 3]}).notes)


def test_sweep_x_on_a_non_product_space_is_bad_input():
    ev = ak.enumerate(space={"permutations": "x"}, sweep={"x": [1, 4]})
    assert "bad_input" in flags(ev) and ev.complete is False and "sweep" in ev.flags[0]["message"]
    ok = ak.enumerate(space={"permutations": "n"}, where="x[0] == 0", sweep={"n": [1, 4]})
    assert ok.result["counts"] == [1, 1, 2, 6]
    bad = ak.enumerate(space={"graphs": {"n": "n + 1"}}, where="n > 1", sweep={"n": [1, 2]})
    assert "bad_input" in flags(bad)


def test_a_slow_where_checks_the_clock_after_the_first_object():
    slow = "sum(range(10**6)) >= 0"                       # tens of milliseconds an object
    ev = run("enumerate", {"space": {"product": {"a": [1, 10**6]}}, "where": slow}, time_s=0.5)
    assert ev.complete is False and ev.result["objects_checked"] < 64
    ev = run("counterexample", dict(claim=slow, domain={"n": [0, 10**12]}, mode="exhaustive"), time_s=0.5)
    assert ev.complete is False and ev.result["checked"] < 64
