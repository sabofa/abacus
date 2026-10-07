"""The computer-science buttons: diff_test, growth (kit/04 s13-14, known answers kit/09 s1)."""
import math
import os
import time

import pytest

import abacus.kit as ak
from abacus import budget, registry
from abacus.config import get_config

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


def test_both_buttons_are_registered():
    registry.load_all()
    names = {b.name for b in registry.all_buttons()}
    assert {"diff_test", "growth"} <= names
    assert registry.get("diff_test").uses_seed is True


# ------------------------------------------------------------------------------------------------ diff_test

TRIANGLE_REF = "lambda n: sum(range(n + 1))"
OFF_BY_ONE = "lambda n: n*(n+1)//2 - (1 if n > 5 else 0)"


def test_off_by_one_is_shrunk_to_the_minimal_input():
    ev = ak.diff_test(fast=OFF_BY_ONE, reference=TRIANGLE_REF, inputs="integers(1, 100)", seed=1)
    assert ev.method == "sampled" and ev.complete is True and ev.scope.strip()
    assert ev.result["disagreements"] >= 1 and ev.result["agreements"] >= 1
    first = ev.result["disagreement_examples"][0]
    assert first["input"] == 6
    assert first["fast"] == {"value": 20} and first["reference"] == {"value": 21}
    assert first["shrunk"] is True
    assert ev.examples and ev.examples[0]["input"] == 6
    no_verdict_keys(ev)


def test_agreeing_implementations_report_nothing_and_say_what_ran():
    ev = ak.diff_test(fast="lambda n: n*(n+1)//2", reference=TRIANGLE_REF, inputs="integers(0, 200)",
                      examples=300, seed=2)
    assert ev.result["disagreements"] == 0 and ev.result["disagreement_examples"] == []
    assert ev.result["agreements"] == ev.result["inputs_run"] > 0
    assert ev.method == "sampled" and ev.complete is True and ev.flags == []
    scope = ev.scope.lower()
    assert str(ev.result["inputs_run"]) in ev.scope
    assert "not proof" in scope and "edge" in scope
    no_verdict_keys(ev)


def test_one_raising_and_one_not_is_a_disagreement():
    ev = ak.diff_test(fast="lambda n: 10 // n", reference="lambda n: 10 // n if n else 0",
                      inputs="integers(0, 20)", seed=3)
    assert ev.result["disagreements"] >= 1
    d = ev.result["disagreement_examples"][0]
    assert d["input"] == 0
    assert "ZeroDivisionError" in d["fast"]["raised"]
    assert d["reference"] == {"value": 0}


def test_both_raising_is_agreement_and_is_counted():
    ev = ak.diff_test(fast="lambda n: 1 // n", reference="lambda n: 1 // (n * 1)", inputs="integers(0, 5)", seed=4)
    assert ev.result["disagreements"] == 0 and ev.result["both_raised"] >= 1


def test_seeded_rerun_is_identical():
    inp = dict(fast=OFF_BY_ONE, reference=TRIANGLE_REF, inputs="integers(1, 100)", seed=7, examples=200)
    a, b = ak.diff_test(**inp), ak.diff_test(**inp)
    assert stable(a) == stable(b)
    assert a.seed == 7


def test_edge_on_and_off():
    inp = dict(fast="lambda n: n if n < 10**6 else 0", reference="lambda n: n", inputs="integers(0, 10**6)",
               examples=20, seed=5)
    on = ak.diff_test(**inp)
    assert on.result["edge_inputs"] > 0
    assert any(d["input"] == 10**6 for d in on.result["disagreement_examples"])
    assert "edge" in on.scope and "included" in on.scope
    off = ak.diff_test(**inp, edge=False)
    assert off.result["edge_inputs"] == 0
    assert "not included" in off.scope


def test_edge_includes_the_empty_list():
    ev = ak.diff_test(fast="lambda xs: max(xs)", reference="lambda xs: max(xs) if xs else 0",
                      inputs="lists(integers(0, 9), max_size=8)", examples=10, seed=6)
    assert any(d["input"] == [] for d in ev.result["disagreement_examples"])


def test_bad_strategy_code_is_flagged():
    for bad in ("integers(", "nonsense(1, 2)", "integers(5, 1)", "3", "__import__('os')", "open('x')"):
        ev = ak.diff_test(fast="lambda n: n", reference="lambda n: n", inputs=bad)
        assert "bad_input" in flags(ev), bad
        assert ev.complete is False and ev.scope.strip(), bad


def test_bad_function_code_is_flagged():
    ev = ak.diff_test(fast="lambda n: (", reference="lambda n: n", inputs="integers(0, 5)")
    assert "bad_input" in flags(ev) and ev.complete is False
    ev = ak.diff_test(fast="lambda n: n", reference="x = 3", inputs="integers(0, 5)")
    assert "bad_input" in flags(ev) and ev.complete is False
    ev = ak.diff_test(fast="lambda a, b: a", reference="lambda n: n", inputs="integers(0, 5)")
    assert "bad_input" in flags(ev) and ev.complete is False
    ev = ak.diff_test(fast="lambda n: n", reference="lambda n: n", inputs="integers(0, 5)", examples=0)
    assert "bad_input" in flags(ev)


def test_no_hypothesis_directory_is_created(tmp_path):
    # a fresh interpreter in an empty directory: Hypothesis decides where to write when it is first imported
    import subprocess
    import sys
    code = chr(10).join([
        "import abacus.kit as ak",
        "ev = ak.diff_test(fast='lambda n: n*(n+1)//2 - (1 if n > 5 else 0)', reference='lambda n: sum(range(n+1))',",
        "                  inputs='integers(1, 100)', seed=1, examples=100)",
        "assert ev.result['disagreement_examples'][0]['input'] == 6",
    ])
    done = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    assert os.listdir(tmp_path) == []


def test_def_source_uses_the_last_def_and_an_expression_uses_the_input_names():
    fast = "def helper(n):\n    return n + 1\n\ndef f(a, b):\n    return a * b\n"
    ev = ak.diff_test(fast=fast, reference="a * b", inputs="{'a': integers(0, 9), 'b': integers(0, 9)}", seed=8)
    assert ev.result["disagreements"] == 0 and ev.result["inputs_run"] > 0 and ev.flags == []
    ev = ak.diff_test(fast="lambda a, b: a + b", reference="a * b",
                      inputs="{'a': integers(0, 9), 'b': integers(0, 9)}", seed=8)
    d = ev.result["disagreement_examples"][0]
    assert set(d["input"]) == {"a", "b"} and d["input"]["a"] + d["input"]["b"] != d["input"]["a"] * d["input"]["b"]
    # a tuple of strategies is positional
    ev = ak.diff_test(fast="lambda a, b: a - b", reference="lambda a, b: a + b",
                      inputs="(integers(0, 9), integers(0, 9))", seed=8)
    assert ev.result["disagreements"] >= 1
    assert all(isinstance(d["input"], list) and len(d["input"]) == 2 for d in ev.result["disagreement_examples"])
    # a single dict-free expression is called x
    ev = ak.diff_test(fast="x + 1", reference="1 + x", inputs="integers(0, 9)", seed=8)
    assert ev.result["disagreements"] == 0 and ev.flags == []


def test_outputs_are_compared_the_way_make_compare_does():
    ev = ak.diff_test(fast="lambda n: Fraction(1, n)", reference="lambda n: 1 / n if n in (1, 2, 4, 8) else Fraction(1, n)",
                      inputs="sampled_from([1, 2, 4, 8])", seed=9)
    assert ev.result["disagreements"] == 0
    ev = ak.diff_test(fast="lambda xs: tuple(xs)", reference="lambda xs: list(xs)",
                      inputs="lists(integers(0, 3), max_size=4)", seed=9)
    assert ev.result["disagreements"] == 0
    ev = ak.diff_test(fast="lambda xs: set(xs)", reference="lambda xs: sorted(set(xs), reverse=True)",
                      inputs="lists(integers(0, 3), max_size=4)", seed=9)
    assert ev.result["disagreements"] > 0      # a set against a list is a real difference
    ev = ak.diff_test(fast="lambda xs: {x for x in xs}", reference="lambda xs: set(reversed(xs))",
                      inputs="lists(integers(0, 3), max_size=4)", seed=9)
    assert ev.result["disagreements"] == 0


def test_inputs_are_not_shared_between_the_two_functions():
    ev = ak.diff_test(fast="lambda xs: xs.sort() or xs", reference="lambda xs: sorted(xs)",
                      inputs="lists(integers(0, 9), max_size=8)", seed=10)
    assert ev.result["disagreements"] == 0 and ev.result["inputs_run"] > 10


def test_generator_inputs():
    gen = "def gen(rng):\n    for _ in range(50):\n        yield (rng.randint(0, 100),)\n"
    ev = ak.diff_test(fast=OFF_BY_ONE, reference=TRIANGLE_REF, inputs=gen, seed=11, examples=50)
    assert ev.result["inputs_run"] == 50 and ev.result["disagreements"] > 0
    assert ev.result["disagreement_examples"][0]["shrunk"] is False
    assert "not shrunk" in ev.scope
    again = ak.diff_test(fast=OFF_BY_ONE, reference=TRIANGLE_REF, inputs=gen, seed=11, examples=50)
    assert stable(ev) == stable(again)


def test_the_number_of_shrunk_disagreements_is_capped_by_max_examples(monkeypatch):
    monkeypatch.setenv("ABACUS_MAX_EXAMPLES", "1")
    assert get_config().max_examples == 1
    ev = ak.diff_test(fast="lambda n: 10 // n if n > 5 else 7 // n", reference="lambda n: 10 // n if n else 0",
                      inputs="integers(0, 40)", seed=12)
    assert len(ev.result["disagreement_examples"]) == 1
    assert ev.result["disagreements"] > 1
    assert "not shown (cap 1)" in ev.scope
    assert any("1 of 2 kinds of disagreement" in n for n in ev.notes)


def test_a_time_stopped_diff_test_is_incomplete_and_says_how_far_it_got():
    slow = "def f(n):\n    import time\n    time.sleep(0.01)\n    return n\n"
    ak.diff_test(fast="lambda n: n", reference="lambda n: n", inputs="integers(0, 9)", examples=5)  # imports Hypothesis
    t0 = time.monotonic()
    ev = run("diff_test", dict(fast=slow, reference="lambda n: n", inputs="integers(0, 10**6)",
                               examples=100000, seed=13), time_s=1.0)
    assert time.monotonic() - t0 < 5
    assert ev.complete is False and ev.method == "sampled"
    assert "stopped" in ev.scope and ev.scope.strip()
    assert ev.result["inputs_run"] < 100000


def test_diff_test_has_no_verdict_keys_anywhere():
    ev = ak.diff_test(fast=OFF_BY_ONE, reference=TRIANGLE_REF, inputs="integers(1, 100)", seed=1)
    no_verdict_keys(ev)
    ev = ak.diff_test(fast="lambda n: n", reference="lambda n: n", inputs="nonsense()")
    no_verdict_keys(ev)


# ------------------------------------------------------------------------------------------------ growth

NESTED = ("def f(xs):\n    c = 0\n    for a in xs:\n        for b in xs:\n            c += 1\n    return c\n")
MAKE_LIST = "lambda n: list(range(n))"
MAKE_RANDOM = "def make(n):\n    import random\n    return [random.random() for _ in range(n)]\n"


def test_fit_classes_recovers_exact_synthetic_curves():
    from abacus.kit.growth import CLASSES, fit_classes
    sizes = [16, 32, 64, 128, 256, 512, 1024]
    shapes = {
        "1": lambda n: 3.0, "log n": lambda n: 2 * math.log(n), "n": lambda n: 5e-3 * n,
        "n log n": lambda n: 1e-3 * n * math.log(n), "n^2": lambda n: 1e-4 * n * n,
        "n^3": lambda n: 1e-6 * n ** 3, "2^n": lambda n: 1e-6 * 2.0 ** (n / 64),
    }
    assert set(shapes) == set(CLASSES)
    for name, f in shapes.items():
        sz = [10, 12, 14, 16, 18, 20, 22] if name == "2^n" else sizes
        fits = fit_classes(sz, [f(n) if name != "2^n" else 1e-6 * 2.0 ** n for n in sz])
        assert fits[0]["class"] == name, (name, fits[:2])
        assert fits[0]["rms_log_residual"] < 1e-9
        assert fits[1]["rms_log_residual"] > fits[0]["rms_log_residual"]


def test_nested_loop_fits_n_squared_or_is_flagged_unreliable():
    ev = ak.growth(fn=NESTED, make_input=MAKE_LIST, sizes=[64, 128, 256, 512, 1024], repeats=3)
    assert ev.method == "timed" and ev.complete is True and ev.scope.strip()
    assert ev.result["sizes"] == [64, 128, 256, 512, 1024]
    assert len(ev.result["median_s"]) == 5 and all(t > 0 for t in ev.result["median_s"])
    assert ev.result["best"] == "n^2" or "unreliable_fit" in flags(ev)
    assert ev.result["runner_up"] in ("n^3", "n log n", "n", "n^2")
    assert isinstance(ev.result["fit"]["rms_log_residual"], float)
    assert ev.result["ranking"][0]["class"] == ev.result["best"]
    assert any("noisy" in n for n in ev.notes) and any("5 sizes" in n for n in ev.notes)
    no_verdict_keys(ev)


def test_sorted_on_random_lists_fits_n_log_n_or_n():
    ev = ak.growth(fn="lambda xs: sorted(xs)", make_input=MAKE_RANDOM,
                   sizes=[2 ** k for k in range(10, 16)], repeats=3)
    top2 = [c["class"] for c in ev.result["ranking"][:2]]
    assert "n log n" in top2, ev.result["ranking"]
    assert ev.result["best"] in ("n log n", "n")


def test_inputs_are_not_mutated_between_calls():
    ev = ak.growth(fn="lambda xs: xs.sort()", make_input="lambda n: list(range(n, 0, -1))",
                   sizes=[256, 512, 1024, 2048], repeats=3)
    assert ev.complete is True and ev.flags == [] or "unreliable_fit" in flags(ev)
    assert ev.result["sizes"] == [256, 512, 1024, 2048]
    assert any("fn changed its input" in n for n in ev.notes)


def test_fewer_than_four_sizes_is_called_unreliable():
    ev = ak.growth(fn=NESTED, make_input=MAKE_LIST, sizes=[64, 128, 256], repeats=3)
    assert ev.result["best"] is None and ev.result["runner_up"] is None
    assert "unreliable_fit" in flags(ev)
    assert any("unreliable" in n and "3 sizes" in n for n in ev.notes)
    assert "unreliable" in ev.scope
    assert len(ev.result["median_s"]) == 3 and ev.result["ranking"]
    no_verdict_keys(ev)


def test_default_sizes_double_from_16_until_the_budget_runs_out():
    t0 = time.monotonic()
    ev = run("growth", dict(fn="lambda xs: sum(xs)", make_input=MAKE_LIST, repeats=3), time_s=1.5)
    assert time.monotonic() - t0 < 4
    sizes = ev.result["sizes"]
    assert sizes[0] == 16 and all(b == 2 * a for a, b in zip(sizes, sizes[1:])) and len(sizes) >= 4
    assert ev.method == "timed" and ev.scope.strip()
    assert ev.complete is True
    assert f"{len(sizes)} sizes" in " ".join(ev.notes)
    assert "16" in ev.scope and str(sizes[-1]) in ev.scope


def test_a_time_stopped_growth_is_incomplete_and_says_how_far_it_got():
    t0 = time.monotonic()
    ev = run("growth", dict(fn=NESTED, make_input=MAKE_LIST, sizes=[64, 128, 256, 512, 1024, 2048, 4096],
                            repeats=3), time_s=0.4)
    assert time.monotonic() - t0 < 6
    assert ev.complete is False and ev.method == "timed"
    assert "stopped" in ev.scope and ev.scope.strip()
    assert 0 < len(ev.result["sizes"]) < 7
    # what was timed is still reported, and a short fit is not a verdict
    assert len(ev.result["median_s"]) == len(ev.result["sizes"])
    if len(ev.result["sizes"]) < 4:
        assert ev.result["best"] is None


def test_a_function_that_raises_is_bad_input_with_what_was_timed():
    ev = ak.growth(fn="lambda xs: 1 // (len(xs) - 64)", make_input=MAKE_LIST, sizes=[16, 32, 64, 128], repeats=3)
    assert "bad_input" in flags(ev) and ev.complete is False
    assert ev.result["sizes"] == [16, 32] and "64" in ev.scope
    ev = ak.growth(fn="lambda xs: 1", make_input="lambda n: 1 / 0", sizes=[16, 32, 64, 128])
    assert "bad_input" in flags(ev) and ev.complete is False and ev.scope.strip()


def test_bad_growth_input_is_flagged():
    for kw in (dict(fn="lambda x: (", make_input=MAKE_LIST),
               dict(fn="lambda x: 1", make_input="lambda n: ("),
               dict(fn="lambda x: 1", make_input=MAKE_LIST, sizes=[]),
               dict(fn="lambda x: 1", make_input=MAKE_LIST, sizes=[1, 2, 3, 4]),
               dict(fn="lambda x: 1", make_input=MAKE_LIST, sizes=[16, "a"]),
               dict(fn="lambda x: 1", make_input=MAKE_LIST, repeats=0),
               dict(fn="x = 3", make_input=MAKE_LIST)):
        ev = ak.growth(**kw)
        assert "bad_input" in flags(ev), kw
        assert ev.complete is False and ev.scope.strip(), kw
        no_verdict_keys(ev)
