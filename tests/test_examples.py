"""The three example algorithms in library/examples/ (kit/09 s5)."""
import json
from fractions import Fraction
from pathlib import Path

import pytest

from abacus.algo import surface  # noqa: F401  (registers the algo_lint button)
from abacus.algo.lint import CHECKS, lint
from abacus.algo.loader import load_algo
from abacus.algo.rng import AbacusRNG
from abacus.algo.roles import normalise_instance

EXAMPLES = Path(__file__).resolve().parents[1] / "library" / "examples"
SLUGS = ("aime-modular-tower", "dice-expected-value", "sum-of-digits-check")
BANNED = {"correct", "pass", "passed", "valid", "score", "verdict"}


def algo(slug):
    return load_algo(EXAMPLES / f"{slug}.py")


def statuses(ev):
    return {c["check"]: c["status"] for c in ev.result["checks"]}


def instance(slug, seed, **knobs):
    a = algo(slug)
    return a, normalise_instance(a.module.generate(AbacusRNG(seed), knobs), a, seed)


def walk_keys(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from walk_keys(v)
    elif isinstance(x, list):
        for v in x:
            yield from walk_keys(v)


@pytest.mark.parametrize("slug", SLUGS)
def test_loads_with_the_id_that_names_its_file(slug):
    a = algo(slug)
    assert a.meta["id"] == f"examples.{slug}"
    assert a.meta["tags"]


@pytest.mark.parametrize("slug", ["aime-modular-tower", "dice-expected-value"])
def test_family_lints_clean(slug):
    ev = lint(EXAMPLES / f"{slug}.py", k=10)
    st = statuses(ev)
    assert list(st) == list(CHECKS)
    assert all(v == "ok" for v in st.values()), ev.result["checks"]
    assert not BANNED & set(walk_keys(ev.to_dict()))
    assert ev.complete and not ev.flags


def test_checker_only_lints_clean_and_skips_only_the_generate_checks():
    ev = lint(EXAMPLES / "sum-of-digits-check.py", k=3)
    st = statuses(ev)
    for name in ("header", "roles exist", "requires"):
        assert st[name] == "ok"
    for name in ("determinism", "agreement", "range", "spread"):
        assert st[name] == "skipped"
    assert "problem" not in st.values()
    assert algo("sum-of-digits-check").meta["roles"] == ["compute", "check"]
    assert not hasattr(algo("sum-of-digits-check").module, "generate")
    assert not ev.flags


# --- aime-modular-tower ---------------------------------------------------------------------------

def test_aime_is_deterministic_and_statement_is_latex():
    _, one = instance("aime-modular-tower", 7)
    _, two = instance("aime-modular-tower", 7)
    assert one.to_dict() == two.to_dict()
    assert one.statement.startswith("Find the remainder when $") and one.statement.count("$") == 4


def test_aime_answers_are_aime_integers_with_a_spread():
    answers = []
    for seed in range(10):
        _, inst = instance("aime-modular-tower", seed)
        v = inst.answer["value"]
        assert isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 999
        assert v > 1
        answers.append(v)
    assert len(set(answers)) >= 5


def test_aime_known_values_and_two_routes_agree():
    a = algo("aime-modular-tower")
    # 2^(3^2) = 2^9 = 512, and 512 mod 500 = 12
    assert a.module.compute({"a": 2, "b": 3, "c": 2, "m": 500}) == 12
    # 7^(2^4) = 7^16 = 33232930569601; mod 1000 = 601
    assert a.module.compute({"a": 7, "b": 2, "c": 4, "m": 1000}) == 601
    # gcd(a, m) > 1 and a big exponent: 6^(10^9) mod 900 is checked against pow
    p = {"a": 6, "b": 10, "c": 9, "m": 900}
    assert a.module.compute(p) == pow(6, 10 ** 9, 900)
    for params in ({"a": 12, "b": 5, "c": 3, "m": 360}, {"a": 98, "b": 19, "c": 9, "m": 997},
                   {"a": 2, "b": 2, "c": 2, "m": 128}):
        value = pow(params["a"], params["b"] ** params["c"], params["m"])
        assert a.module.compute(params) == value
        ev = a.module.check(params, value)
        assert ev.result is True and ev.compare["equal"] is True
        assert a.module.check(params, (value + 1) % params["m"]).result is False


def test_aime_knobs_fix_params_and_hand_space_and_demo():
    a, inst = instance("aime-modular-tower", 3, a=7, b=9, c=4)
    assert inst.params["a"] == 7 and inst.params["b"] == 9 and inst.params["c"] == 4
    assert a.module.hand_space(inst.params) == 9 ** 4
    show = a.module.demo(inst)
    assert show["kind"] == "markdown" and "| k |" in show["body"]
    assert a.module.demo(inst.to_dict()) == show


# --- dice-expected-value --------------------------------------------------------------------------

def test_dice_is_deterministic_and_rational():
    _, one = instance("dice-expected-value", 5)
    _, two = instance("dice-expected-value", 5)
    assert one.to_dict() == two.to_dict()
    assert "$" in one.statement and "expected number of rolls" in one.statement
    assert algo("dice-expected-value").meta["answer"]["format"] == "rational"
    for seed in range(10):
        _, inst = instance("dice-expected-value", seed)
        v = Fraction(str(inst.answer["value"]))
        assert 1 <= v <= 30


def test_dice_exact_values():
    a = algo("dice-expected-value")
    # compute is general, though the knobs start higher: any roll exceeds 0; a fair coin die {1, 2} to exceed 2
    # takes 3 rolls with probability 1/4 and 2 rolls otherwise: 9/4; to exceed 1 it takes 1 roll or 2: 3/2.
    assert a.module.compute({"n": 0, "sides": 6}) == 1
    assert a.module.compute({"n": 1, "sides": 2}) == Fraction(3, 2)
    assert a.module.compute({"n": 2, "sides": 2}) == Fraction(9, 4)


def test_dice_check_is_simulates_evidence_and_has_no_verdict_key():
    a = algo("dice-expected-value")
    params = {"n": 10, "sides": 6}
    exact = a.module.compute(params)
    ev = a.module.check(params, exact)
    d = ev.to_dict()
    assert ev.button == "simulate" and ev.method == "sampled"
    assert d["result"]["trials_run"] <= 20_000 and len(d["result"]["ci95"]) == 2
    assert d["compare"]["equal"] is True
    assert not BANNED & set(walk_keys(d))
    again = a.module.check(params, exact).to_dict()  # seeded, so repeatable apart from timings
    assert {**d, "budget": None} == {**again, "budget": None}
    wrong = a.module.check(params, exact + 1)
    assert wrong.compare["equal"] is False
    assert wrong.result == ev.result  # the estimate does not depend on what was proposed


# --- sum-of-digits-check --------------------------------------------------------------------------

@pytest.mark.parametrize("n, d, expected", [
    (9, 3, 3),          # 3, 6, 9
    (19, 2, 9),         # 2 4 6 8 11 13 15 17 19
    (99, 9, 11),        # the multiples of 9 up to 99
    (100, 1, 100),      # every digit sum is divisible by 1
    (1000, 10, 99),     # 63 with digit sum 10, 36 with digit sum 20, and none else below 1000; 1000 has sum 1
])
def test_checker_only_known_values(n, d, expected):
    a = algo("sum-of-digits-check")
    params = {"N": n, "d": d}
    assert a.module.compute(params) == expected
    ev = a.module.check(params, expected)
    assert ev.result is True and ev.compare["equal"] is True
    bad = a.module.check(params, expected + 1)
    assert bad.result is False and bad.compare["computed"] == expected


def test_checker_only_dp_matches_brute_force_on_many_inputs():
    m = algo("sum-of-digits-check").module
    for n in (1, 2, 10, 11, 98, 101, 999, 1234, 5000):
        for d in (1, 2, 3, 7, 11, 40):
            assert m._dp_count(n, d) == m.compute({"N": n, "d": d}), (n, d)


def test_checker_only_rejects_bad_input():
    m = algo("sum-of-digits-check").module
    with pytest.raises(ValueError):
        m.compute({"N": 0, "d": 3})
    with pytest.raises(ValueError):
        m.compute({"N": 10 ** 9, "d": 3})
