import fractions
import math

import numpy as np
import pytest
import sympy as sp

from abacus.config import get_config
from abacus.evidence import Evidence, jsonable, make_compare

BANNED = {"correct", "pass", "valid", "score"}


def ev(**kw):
    base = dict(button="b", result=1, method="exhaustive", scope="s")
    base.update(kw)
    return Evidence(**base)


def test_jsonable_sympy():
    assert jsonable(sp.Integer(5)) == 5 and type(jsonable(sp.Integer(5))) is int
    assert jsonable(sp.Rational(1, 3)) == "1/3"
    assert jsonable(fractions.Fraction(2, 6)) == "1/3"
    assert jsonable(sp.sqrt(2)) == "sqrt(2)"


def test_jsonable_numpy():
    assert type(jsonable(np.int64(3))) is int
    assert type(jsonable(np.float64(1.5))) is float
    assert jsonable(np.array([[1, 2], [3, 4]])) == [[1, 2], [3, 4]]


def test_jsonable_containers():
    assert jsonable({3, 1, 2}) == [1, 2, 3]
    assert jsonable(frozenset({2, 1})) == [1, 2]
    assert jsonable((1, (2, 3))) == [1, [2, 3]]
    assert jsonable({"a": [sp.Integer(1), {sp.Rational(1, 2)}]}) == {"a": [1, ["1/2"]]}


def test_jsonable_nonfinite():
    assert jsonable(float("nan")) == "nan"
    assert jsonable(math.inf) == "inf"
    assert jsonable(-math.inf) == "-inf"


def test_example_cap_and_note():
    e = ev(examples=list(range(37))).to_dict()
    assert len(e["examples"]) == get_config().max_examples == 10
    assert "showing 10 of 37 examples" in e["notes"]


def test_cap_env(monkeypatch):
    monkeypatch.setenv("ABACUS_MAX_EXAMPLES", "3")
    assert len(ev(examples=list(range(5))).to_dict()["examples"]) == 3


def test_full_uncapped():
    e = ev(examples=list(range(37))).to_dict(full=True)
    assert len(e["examples"]) == 37 and e["notes"] == []


def test_compare():
    assert make_compare(8, 8) == {"proposed": 8, "computed": 8, "equal": True}
    assert make_compare(1248, 1247)["equal"] is False
    assert make_compare("sqrt(8)", "2*sqrt(2)")["equal"] is True
    assert make_compare(sp.sqrt(8), 2 * sp.sqrt(2))["equal"] is True
    assert make_compare([1, 2], [1, 3])["equal"] is False


def test_compare_containers_equal_by_plain_equality():
    assert make_compare({1, 2}, {1, 2})["equal"] is True
    assert make_compare({1, 2}, {2, 1})["equal"] is True
    assert make_compare(frozenset({1, 2}), {1, 2})["equal"] is True
    assert make_compare((1, 2), (1, 2))["equal"] is True
    assert make_compare([1, 2], [1, 2])["equal"] is True
    assert make_compare([(1, 2), {3}], [(1, 2), {3}])["equal"] is True
    assert make_compare({1, 2}, {1, 3})["equal"] is False
    assert make_compare({1, 2}, {1, 2, 3})["equal"] is False
    assert make_compare((1, 2), (1, 3))["equal"] is False
    assert make_compare([1, 2], [1])["equal"] is False


def test_compare_mixed_container_types_by_normal_form():
    assert make_compare((1, 2), [1, 2])["equal"] is True
    assert make_compare([1, 2], (1, 2))["equal"] is True
    assert make_compare(([1, 2], {3}), [(1, 2), frozenset({3})])["equal"] is True
    assert make_compare({"a": (1, 2)}, {"a": [1, 2]})["equal"] is True
    assert make_compare(np.array([1, 2, 3]), [1, 2, 3])["equal"] is True
    assert make_compare([1, 2, 3], np.array([1, 2, 3]))["equal"] is True
    assert make_compare(np.array([[1, 2], [3, 4]]), [[1, 2], [3, 4]])["equal"] is True
    assert make_compare((np.int64(1), np.float64(2.5)), [1, 2.5])["equal"] is True
    assert make_compare({1, 2}, frozenset({2, 1}))["equal"] is True
    assert make_compare([{1, 2}, 3], [frozenset({1, 2}), 3])["equal"] is True


def test_compare_mixed_container_types_stay_unequal_when_the_contents_differ():
    assert make_compare([1, 2], [2, 1])["equal"] is False
    assert make_compare((1, 2), [2, 1])["equal"] is False
    assert make_compare((1, 2), [1, 2, 3])["equal"] is False
    assert make_compare(np.array([1, 2]), [2, 1])["equal"] is False
    assert make_compare({"a": (1, 2)}, {"a": [1, 3]})["equal"] is False
    assert make_compare({"a": 1}, {"b": 1})["equal"] is False
    assert make_compare({1, 2}, frozenset({1, 3}))["equal"] is False
    assert make_compare([{1, 2}], [{1, 3}])["equal"] is False


def test_validation():
    with pytest.raises(ValueError):
        ev(scope="")
    with pytest.raises(ValueError):
        ev(method="vibes")


def test_flag():
    e = ev()
    e.flag("c", "m")
    assert e.to_dict()["flags"] == [{"code": "c", "message": "m"}]


def _keys(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from _keys(v)
    elif isinstance(x, list):
        for v in x:
            yield from _keys(v)


def test_no_verdict_keys():
    e = ev(compare=make_compare(1, 1), examples=[{"a": 1}], flags=[{"code": "x", "message": "y"}])
    d = e.to_dict()
    assert not (set(_keys(d)) & BANNED)
    assert not (set(Evidence.__dataclass_fields__) & BANNED)


# ---------------------------------------------------------------- T3 hardening: no sympify of strings

def test_compare_numeric_strings():
    assert make_compare("1/2", 0.5)["equal"] is True
    assert make_compare("0.25", fractions.Fraction(1, 4))["equal"] is True
    assert make_compare("1/2", 0.75)["equal"] is False


def test_compare_expression_string_goes_through_the_whitelist():
    assert make_compare("x + x", "2*x")["equal"] is True
    assert make_compare("x + x", "3*x")["equal"] is False
    assert make_compare("(x+1)**2", "x**2 + 2*x + 1")["equal"] is True


def test_compare_never_sympifies_a_string(monkeypatch):
    real = sp.sympify

    def guard(a, *args, **kw):
        assert not isinstance(a, str), f"sympify called on a string: {a!r}"
        return real(a, *args, **kw)

    monkeypatch.setattr(sp, "sympify", guard)
    assert make_compare("1/2", 0.5)["equal"] is True
    assert make_compare("x + x", "2*x")["equal"] is True
    assert make_compare("abc def", "xyz")["equal"] is False


@pytest.mark.parametrize("text", ["'a'", '"a" + "b"', "x.func", "__import__('os')", "a b c", "1 +", "lambda: 1"])
def test_compare_rejected_strings_compare_as_plain_text(text):
    assert make_compare(text, text)["equal"] is True
    assert make_compare(text, "something else")["equal"] is False
    assert make_compare(text, 0)["equal"] is False
