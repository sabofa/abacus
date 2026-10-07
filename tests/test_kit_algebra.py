"""The algebra buttons: exact, cas, identity (spec 04 s1-3; known answers in spec 09 s1)."""
import importlib
import json
import math

import pytest

import abacus.kit as ak
from abacus import budget, registry

alg = importlib.import_module("abacus.kit._algebra")

VERDICT_KEYS = {"correct", "pass", "valid", "score"}


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _keys(v)


def run(name, **inp):
    """Call a button in process (what `ak.<name>(**inp)` does) and check what every Evidence must satisfy.

    `ak.exact` itself is not used: once abacus.kit.exact is imported the package attribute is the module,
    which hides the library-surface wrapper (see the note in the commit message).
    """
    registry.load_all()
    ev = budget.call(name, inp, in_process=True)
    d = ev.to_dict(full=True)
    assert not VERDICT_KEYS & set(_keys(d)), f"verdict key in {name} evidence"
    assert ev.scope and ev.scope.strip()
    assert ev.method in {"symbolic", "numeric", "sampled", "exhaustive", "search", "fit", "timed"}
    json.dumps(d)  # must serialise
    return ev


def digits_of(n):
    """str(n) for an int past Python's 4300-digit print limit."""
    with alg.big_ints():
        return str(n)


def codes(ev):
    return [f["code"] for f in ev.flags]


def notes(ev):
    return " | ".join(ev.notes)


# ---------------------------------------------------------------- registry


def test_the_three_buttons_are_registered():
    registry.load_all()
    for name in ("exact", "cas", "identity"):
        assert registry.get(name).input_schema["type"] == "object"
    assert registry.get("identity").uses_seed is True
    assert registry.get("exact").uses_seed is False and registry.get("cas").uses_seed is False


def test_the_schemas_name_no_verdict_key():
    for name in ("exact", "cas", "identity"):
        assert not VERDICT_KEYS & set(_keys(registry.get(name).input_schema))


# ---------------------------------------------------------------- exact: known answers


def test_exact_two_to_the_hundred_mod_a_thousand():
    ev = run("exact", expr="2**100", mod=1000)
    assert ev.result["value"] == "376"
    assert ev.method == "symbolic" and ev.complete


def test_exact_two_to_the_hundred_mod_inline_and_caret():
    assert run("exact", expr="2**100 % 1000").result["value"] == "376"
    ev = run("exact", expr="2^100", mod=1000)
    assert ev.result["value"] == "376"
    assert "exponentiation" in notes(ev)  # ^ is a power here, not XOR


def test_exact_totient_of_a_thousand():
    assert run("exact", expr="totient(1000)").result["value"] == "400"


def test_exact_value_has_latex_and_a_30_digit_decimal():
    ev = run("exact", expr="1/3")
    assert ev.result["value"] == "1/3"
    assert ev.result["latex"] == r"\frac{1}{3}"
    assert ev.result["decimal"] == "0." + "3" * 30
    ev = run("exact", expr="sqrt(8)")
    assert ev.result["value"] == "2*sqrt(2)"
    assert ev.result["decimal"].startswith("2.8284271247461900976033774484")
    assert len(ev.result["decimal"].replace(".", "")) == 30


def test_exact_a_big_integer_is_exact_past_the_python_digit_limit():
    ev = run("exact", expr="factorial(2000)")
    assert ev.result["value"] == digits_of(math.factorial(2000))
    assert len(ev.result["value"]) > 4300
    assert ev.result["latex"] == ev.result["value"]


def test_exact_surds_and_rationals_stay_exact():
    assert run("exact", expr="sqrt(2)*sqrt(8)").result["value"] == "4"
    assert run("exact", expr="1/3 + 1/6").result["value"] == "1/2"
    ev = run("exact", expr="(1 + sqrt(5))/2 * (1 - sqrt(5))/2")
    assert ev.result["value"] == "-1"


def test_exact_reads_decimal_literals_as_exact_rationals():
    ev = run("exact", expr="0.1 + 0.2")
    assert ev.result["value"] == "3/10"
    assert "rational" in notes(ev)


@pytest.mark.parametrize("expr,expected", [
    ("factorint(360)", "{2: 3, 3: 2, 5: 1}"),
    ("divisors(12)", "[1, 2, 3, 4, 6, 12]"),
    ("totient(36)", "12"),
    ("mobius(30)", "-1"),
    ("primepi(100)", "25"),
    ("isprime(97)", "True"),
    ("isprime(91)", "False"),
    ("nextprime(100)", "101"),
    ("gcd(12, 18)", "6"),
    ("lcm(4, 6)", "12"),
    ("binomial(10, 3)", "120"),
    ("multinomial(2, 3, 1)", "60"),
    ("factorial(10)", "3628800"),
    ("fibonacci(50)", "12586269025"),
    ("catalan(10)", "16796"),
    ("partition(100)", "190569292"),
    ("legendre(2, 7)", "1"),
    ("legendre(3, 7)", "-1"),
    ("jacobi(2, 15)", "1"),
    ("n_order(2, 7)", "3"),
    ("primitive_root(7)", "3"),
    ("discrete_log(41, 15, 7)", "3"),
    ("crt([3, 5, 7], [2, 3, 2])", "(23, 105)"),
    ("sqrt_mod(11, 43)", "21"),
    ("powmod(3, 10**18, 7)", str(pow(3, 10**18, 7))),
])
def test_exact_number_theory_namespace(expr, expected):
    ev = run("exact", expr=expr)
    assert ev.complete and not ev.flags, ev.flags
    assert ev.result["value"] == expected


def test_exact_every_spec_name_is_in_the_namespace():
    names = ("factorint divisors totient mobius primepi isprime nextprime gcd lcm binomial multinomial "
             "factorial fibonacci catalan partition legendre jacobi n_order primitive_root discrete_log "
             "crt sqrt_mod").split()
    ns = alg.exact_namespace()
    for n in names:
        assert callable(ns[n]), n
    assert ns["__builtins__"] == {}


def test_exact_mod_of_a_rational_uses_the_inverse():
    assert run("exact", expr="1/3", mod=7).result["value"] == "5"  # 3 * 5 = 15 = 1 (mod 7)


def test_exact_mod_gives_the_non_negative_residue():
    assert run("exact", expr="-7", mod=5).result["value"] == "3"


def test_exact_powmod_is_reduced_without_building_it():
    # 7**(10**18) would never finish if it were built first
    ev = run("exact", expr="powmod(7, 10**18, 1000)")
    assert ev.result["value"] == str(pow(7, 10**18, 1000))


# ---------------------------------------------------------------- exact: compare, bad input, honesty


def test_exact_proposed_gives_a_compare():
    ev = run("exact", expr="2**100", mod=1000, proposed=376)
    assert ev.compare == {"proposed": 376, "computed": 376, "equal": True}
    ev = run("exact", expr="2**100", mod=1000, proposed=375)
    assert ev.compare["equal"] is False and ev.compare["computed"] == 376
    ev = run("exact", expr="sqrt(8)", proposed="2*sqrt(2)")
    assert ev.compare["equal"] is True
    ev = run("exact", expr="sqrt(8)", proposed="3")
    assert ev.compare["equal"] is False
    assert run("exact", expr="2**100").compare is None  # present only when proposed was passed


def test_exact_compare_of_a_dict_and_a_list():
    assert run("exact", expr="factorint(360)", proposed="{2: 3, 3: 2, 5: 1}").compare["equal"] is True
    assert run("exact", expr="divisors(12)", proposed=[1, 2, 3, 4, 6, 12]).compare["equal"] is True
    assert run("exact", expr="divisors(12)", proposed=[1, 2, 3, 4, 6]).compare["equal"] is False


def test_exact_compare_of_a_huge_integer_serialises():
    ev = run("exact", expr="factorial(2000)", proposed=digits_of(math.factorial(2000)))
    assert ev.compare["equal"] is True
    json.dumps(ev.to_dict())  # no 5000-digit int in the JSON


@pytest.mark.parametrize("expr", ["2**", "((", "1 +* 2", "", "   ", "__import__(\x27os\x27)", "n_order(2, 4)"])
def test_exact_unparseable_input_is_flagged_not_raised(expr):
    ev = run("exact", expr=expr)
    assert "bad_input" in codes(ev) and ev.complete is False
    assert ev.result is None


def test_exact_a_misspelt_function_is_not_silently_returned():
    ev = run("exact", expr="factoril(5)")
    assert "bad_input" in codes(ev) and ev.complete is False
    assert "factoril" in ev.flags[0]["message"]


def test_exact_free_symbols_are_rejected():
    ev = run("exact", expr="x + 1")
    assert "bad_input" in codes(ev) and "x" in ev.flags[0]["message"]


def test_exact_mod_of_something_that_is_not_a_rational_is_flagged():
    ev = run("exact", expr="sqrt(2)", mod=5)
    assert "bad_input" in codes(ev) and ev.complete is False
    ev = run("exact", expr="1/5", mod=10)  # 5 is not invertible mod 10
    assert "bad_input" in codes(ev)


def test_exact_a_misspelt_key_is_rejected_not_ignored():
    ev = run("exact", expr="2**100", modulus=1000)
    assert "bad_input" in codes(ev) and ev.result is None


def test_exact_an_inexact_result_is_flagged():
    ev = run("exact", expr="sqrt(2).n(20)")
    assert "inexact" in codes(ev)


def test_exact_a_value_too_long_to_print_is_summarised_not_cut():
    ev = run("exact", expr="3**40000")
    assert "value_too_long" in codes(ev)
    full = digits_of(3**40000)
    assert ev.result["value"] is None and ev.result["digits"] == len(full)
    assert ev.result["head"] == full[:40] and ev.result["tail"] == full[-40:]
    assert "e+" in ev.result["decimal"].lower()  # the 30-digit decimal is still there


# ---------------------------------------------------------------- cas: known answers


def test_cas_factor_x4_plus_4():
    ev = run("cas", op="factor", expr="x**4 + 4", vars=["x"])
    assert ev.result["value"] == "(x**2 - 2*x + 2)*(x**2 + 2*x + 2)"
    assert "x^{2}" in ev.result["latex"]
    assert ev.method == "symbolic" and ev.complete and not ev.flags


@pytest.mark.parametrize("op,inp,expected", [
    ("simplify", dict(expr="(x**2 - 1)/(x - 1)", vars=["x"]), "x + 1"),
    ("expand", dict(expr="(x + 1)**3", vars=["x"]), "x**3 + 3*x**2 + 3*x + 1"),
    ("diff", dict(expr="x**3", vars=["x"]), "3*x**2"),
    ("integrate", dict(expr="x**2", vars=["x"]), "x**3/3"),
    ("apart", dict(expr="1/(x**2 - 1)", vars=["x"]), "-1/(2*(x + 1)) + 1/(2*(x - 1))"),
    ("together", dict(expr="1/x + 1/y", vars=["x", "y"]), "(x + y)/(x*y)"),
    ("resultant", dict(exprs=["x**2 - 1", "x - 2"], var="x"), "3"),
    ("minimal_polynomial", dict(expr="sqrt(2) + sqrt(3)", var="x"), "x**4 - 10*x**2 + 1"),
    ("limit", dict(expr="sin(x)/x", var="x", point="0"), "1"),
    ("series", dict(expr="exp(x)", var="x", point="0", order=4), "1 + x + x**2/2 + x**3/6 + O(x**4)"),
    ("sum", dict(expr="k", var="k", lower="1", upper="n", vars=["n"]), "n**2/2 + n/2"),
    ("sum", dict(expr="1/k**2", var="k", lower="1", upper="oo"), "pi**2/6"),
    ("product", dict(expr="k", var="k", lower="1", upper="n", vars=["n"]), "factorial(n)"),
    ("solve", dict(expr="x**2 - 4", vars=["x"]), "[-2, 2]"),
    ("solve", dict(expr="x**2 = 4", vars=["x"]), "[-2, 2]"),
    ("solve", dict(exprs=["x + y = 3", "x - y = 1"], vars=["x", "y"]), "[{x: 2, y: 1}]"),
    ("solveset", dict(expr="x**2 - 4", var="x"), "{-2, 2}"),
    ("roots", dict(expr="x**2 - 3*x + 2", var="x"), "{1: 1, 2: 1}"),
    ("nsimplify", dict(expr="0.3333333333333333"), "1/3"),
])
def test_cas_ops(op, inp, expected):
    ev = run("cas", op=op, **inp)
    assert ev.complete and "bad_input" not in codes(ev), (ev.flags, ev.scope)
    assert ev.result["value"] == expected
    assert ev.result["latex"]
    assert ev.method == "symbolic"


@pytest.mark.parametrize("op,inp,expected", [
    ("integrate", dict(expr="x*exp(-x)", var="x", lower=0, upper="oo"), "1"),
    ("limit", dict(expr="(1 + 1/x)**x", var="x", point="oo"), "E"),
    ("limit", dict(expr="1/x", var="x", point="0", direction="-"), "-oo"),
    ("diff", dict(expr="x**4", var="x", order=2), "12*x**2"),
    ("series", dict(expr="1/(1 - x)", var="x", order=3), "1 + x + x**2 + O(x**3)"),
    ("solve", dict(expr="a*x - 6", vars=["x"], assumptions={"a": "integer > 0"}), "[6/a]"),
    ("solveset", dict(expr="x**2 - 4", var="x", assumptions={"x": "integer"}), "{-2, 2}"),
])
def test_cas_more_ops(op, inp, expected):
    ev = run("cas", op=op, **inp)
    assert ev.complete and "bad_input" not in codes(ev), (ev.flags, ev.scope)
    assert ev.result["value"] == expected


def test_cas_scope_says_what_was_done_and_to_which_variable():
    ev = run("cas", op="diff", expr="x*y", vars=["x", "y"], var="y")
    assert ev.result["value"] == "x"
    assert "diff" in ev.scope and "y" in ev.scope


def test_cas_limit_both_sides_by_default():
    ev = run("cas", op="limit", expr="Abs(x)/x", var="x", point="0")
    assert ev.result["value"] is None and ev.result["left"] == "-1" and ev.result["right"] == "1"
    assert "does not exist" in notes(ev)
    ev = run("cas", op="limit", expr="Abs(x)/x", var="x", point="0", direction="+")
    assert ev.result["value"] == "1"


def test_cas_assumptions_change_the_answer():
    plain = run("cas", op="simplify", expr="sqrt(x**2)", vars=["x"])
    assert plain.result["value"] == "sqrt(x**2)"
    pos = run("cas", op="simplify", expr="sqrt(x**2)", vars=["x"], assumptions={"x": "positive integer"})
    assert pos.result["value"] == "x"
    assert "positive" in pos.scope


# ---------------------------------------------------------------- cas: honesty


def test_cas_notes_an_unevaluated_integral():
    ev = run("cas", op="integrate", expr="x**x", vars=["x"])
    assert ev.result["value"] == "Integral(x**x, x)"
    assert "unevaluated" in notes(ev) and "Integral" in notes(ev)
    assert "not a proof" in notes(ev) or "does not mean" in notes(ev)


def test_cas_notes_a_conditional_result():
    ev = run("cas", op="integrate", expr="1/x**n", vars=["x", "n"], var="x")
    assert "Piecewise" in ev.result["value"]
    assert "conditional" in notes(ev) and "Piecewise" in notes(ev)


def test_cas_notes_a_condition_set():
    ev = run("cas", op="solveset", expr="cos(x) - x", var="x", assumptions={"x": "real"})
    assert "ConditionSet" in ev.result["value"]
    assert "ConditionSet" in notes(ev)


def test_cas_notes_a_set_sympy_could_not_simplify():
    # the true answer is {0}; sympy leaves the intersections of 2*n*pi with the integers unevaluated
    ev = run("cas", op="solveset", expr="sin(x)", var="x", assumptions={"x": "integer"})
    assert "Intersection" in ev.result["value"] and "Intersection" in notes(ev)


def test_cas_notes_an_unevaluated_sum():
    ev = run("cas", op="sum", expr="1/(k**3 + k + 1)", var="k", lower="1", upper="oo")
    assert ev.result["value"].startswith("Sum(") and "unevaluated" in notes(ev) and "Sum" in notes(ev)


def test_cas_notes_a_limit_that_is_only_bounds():
    ev = run("cas", op="limit", expr="sin(1/x)", var="x", point="0")
    assert "AccumBounds" in ev.result["value"] and "AccumBounds" in notes(ev)


def test_cas_notes_roots_it_could_not_find():
    ev = run("cas", op="roots", expr="x**5 - x - 1", var="x")
    assert ev.result["value"] == "{}"
    assert "0 of 5" in notes(ev)


def test_cas_series_carries_its_remainder_term():
    ev = run("cas", op="series", expr="exp(x)", var="x", point="0", order=3)
    assert "O(x**3)" in ev.result["value"]
    assert "O(" in notes(ev)


def test_cas_an_indefinite_integral_says_the_constant_is_left_out():
    ev = run("cas", op="integrate", expr="x**2", vars=["x"])
    assert "constant" in notes(ev)


def test_cas_nsimplify_says_it_is_a_guess_within_a_tolerance():
    ev = run("cas", op="nsimplify", expr="0.3333333333333333")
    assert "not proof" in notes(ev) or "approximat" in notes(ev)


def test_cas_solve_with_no_solutions_is_not_called_none_exist():
    ev = run("cas", op="solve", expr="exp(x) + 1", vars=["x"], assumptions={"x": "real"})
    assert ev.result["value"] == "[]"
    assert "does not prove" in notes(ev)


def test_cas_undefined_functions_are_listed():
    ev = run("cas", op="diff", expr="f(x)*x", vars=["x"])
    assert ev.result["value"] == "x*Derivative(f(x), x) + f(x)"
    assert "undefined function" in notes(ev) and "f" in notes(ev)


def test_cas_sympy_giving_up_is_flagged_not_raised():
    ev = run("cas", op="solve", expr="sin(x) - x", vars=["x"])
    assert "unsupported" in codes(ev) and ev.complete is False
    assert ev.result is None or ev.result["value"] is None


# ---------------------------------------------------------------- cas: compare and bad input


def test_cas_proposed_gives_a_compare():
    ev = run("cas", op="factor", expr="x**4 + 4", vars=["x"], proposed="(x**2 + 2*x + 2)*(x**2 - 2*x + 2)")
    assert ev.compare["equal"] is True
    ev = run("cas", op="factor", expr="x**4 + 4", vars=["x"], proposed="(x**2 + 2)**2")
    assert ev.compare["equal"] is False
    assert ev.compare["computed"] == "(x**2 - 2*x + 2)*(x**2 + 2*x + 2)"
    assert run("cas", op="factor", expr="x**4 + 4", vars=["x"]).compare is None


def test_cas_solution_sets_compare_without_regard_to_order():
    ev = run("cas", op="solve", expr="x**2 - 4", vars=["x"], proposed=[2, -2])
    assert ev.compare["equal"] is True
    ev = run("cas", op="solve", expr="x**2 - 4", vars=["x"], proposed=[2])
    assert ev.compare["equal"] is False
    ev = run("cas", op="solve", exprs=["x + y = 3", "x - y = 1"], vars=["x", "y"], proposed=[{"x": 2, "y": 1}])
    assert ev.compare["equal"] is True
    ev = run("cas", op="roots", expr="x**2 - 3*x + 2", var="x", proposed={"1": 1, "2": 1})
    assert ev.compare["equal"] is True


@pytest.mark.parametrize("inp", [
    dict(op="factor", expr="x**"),
    dict(op="factor", expr="(x + "),
    dict(op="factor", expr="__import__(\x27os\x27)"),
    dict(op="limit", expr="sin(x)/x", var="x"),                      # no point
    dict(op="sum", expr="k", var="k", lower="1"),                    # no upper bound
    dict(op="sum", expr="k*m", lower="1", upper="3"),                # which variable?
    dict(op="solve", expr="x + y"),                                  # which unknown?
    dict(op="resultant", exprs=["x - 1"], var="x"),                  # needs two
    dict(op="factor", exprs=["x - 1", "x - 2"]),                     # one expression only
    dict(op="factor", expr="x", exprs=["x"]),                        # expr or exprs, not both
    dict(op="factor"),                                               # neither
    dict(op="roots", expr="sin(x)", var="x"),                        # not a polynomial
    dict(op="simplify", expr="x", assumptions={"x": "gibberish"}),   # bad assumption
])
def test_cas_bad_input_is_flagged_not_raised(inp):
    ev = run("cas", **inp)
    assert "bad_input" in codes(ev), (inp, ev.flags)
    assert ev.complete is False


def test_cas_inequalities_go_to_solveset():
    ev = run("cas", op="solve", expr="x**2 <= 4", vars=["x"])
    assert "bad_input" in codes(ev) and "solveset" in ev.flags[0]["message"]
    ev = run("cas", op="solveset", expr="x**2 <= 4", var="x")
    assert ev.result["value"] == "Interval(-2, 2)" and "reals" in notes(ev)


def test_whole_number_floats_are_accepted_where_an_integer_is_asked():
    assert run("exact", expr="2**100", mod=1000.0).result["value"] == "376"
    assert run("cas", op="diff", expr="x**4", var="x", order=2.0).result["value"] == "12*x**2"
    assert run("identity", lhs="x", rhs="x+1", vars=["x"], points=5.0, digits=10.0, seed=1).result["numeric"][
        "points_requested"] == 5


def test_cas_an_unknown_op_is_rejected_by_the_schema():
    ev = run("cas", op="frobnicate", expr="x")
    assert "bad_input" in codes(ev) and ev.complete is False


# ---------------------------------------------------------------- identity: known answers


def test_identity_sin2_plus_cos2_is_equal():
    ev = run("identity", lhs="sin(x)**2 + cos(x)**2", rhs="1", vars=["x"], seed=1)
    sym, num = ev.result["symbolic"], ev.result["numeric"]
    assert sym["relation"] == "equal" and "simplify" in sym["source"] and "0" in sym["source"]
    assert num["points_tested"] == 50 and num["counterexample"] is None
    assert float(num["max_abs_diff"]) < 1e-30
    assert ev.method == "symbolic" and ev.complete and ev.seed == 1
    assert ev.precision["digits"] == 30


def test_identity_x_plus_1_squared_vs_x2_plus_1_finds_a_counterexample():
    ev = run("identity", lhs="(x+1)**2", rhs="x**2 + 1", vars=["x"], seed=3)
    sym, num = ev.result["symbolic"], ev.result["numeric"]
    cx = num["counterexample"]
    assert cx is not None
    x = cx["point"]["x"]
    assert abs((float(cx["lhs"]) - float(cx["rhs"])) - 2 * x) < 1e-9 * max(1, abs(x))
    assert sym["relation"] == "not_equal" and "polynomial" in sym["source"]
    assert float(num["max_abs_diff"]) > 1
    assert ev.examples and ev.examples[0] == cx
    assert "counterexample_found" in codes(ev)


def test_identity_default_points_and_digits():
    ev = run("identity", lhs="x", rhs="x", vars=["x"])
    assert ev.result["numeric"]["points_requested"] == 50
    assert ev.precision["digits"] == 30


def test_identity_points_and_digits_are_honoured():
    ev = run("identity", lhs="sin(x)**2 + cos(x)**2", rhs="1", vars=["x"], points=7, digits=12)
    assert ev.result["numeric"]["points_requested"] == 7 and ev.result["numeric"]["points_tested"] == 7
    assert ev.precision["digits"] == 12
    assert "7" in ev.scope and "12" in ev.scope


# ---------------------------------------------------------------- identity: domains


def test_identity_integer_domain_is_enumerated_when_it_is_small():
    ev = run("identity", lhs="n**2", rhs="n", vars=["n"], domain={"n": "integer >= 1"}, seed=5)
    num = ev.result["numeric"]
    assert num["enumerated"] is True and num["domain_covered"] is False  # every point of the window, not of the domain
    assert num["points_requested"] == 50 and num["points_tested"] == 31  # the domain has 31 points: 1..31
    assert num["counterexample"]["point"] == {"n": 2}  # n = 1 agrees
    assert isinstance(num["counterexample"]["point"]["n"], int)


def test_identity_real_interval_domain_is_respected():
    ev = run("identity", lhs="x", rhs="x + 1", vars=["x"], domain={"x": "real in (0, pi)"}, seed=2)
    assert ev.result["symbolic"]["relation"] == "not_equal"
    assert ev.result["numeric"]["mismatches"] == 50  # every point disagrees by 1
    for ex in ev.examples:
        assert 0 < ex["point"]["x"] < math.pi
    assert "(0, pi)" in ev.scope


def test_identity_a_domain_lets_sympy_use_the_assumptions():
    ev = run("identity", lhs="sqrt(x**2)", rhs="x", vars=["x"], domain={"x": "real >= 0"}, seed=1)
    assert ev.result["symbolic"]["relation"] == "equal"
    assert ev.result["numeric"]["counterexample"] is None
    # on all the reals (the default domain) they differ, and the numeric part finds it
    ev = run("identity", lhs="sqrt(x**2)", rhs="x", vars=["x"], seed=1)
    assert ev.result["symbolic"]["relation"] != "equal"
    assert ev.result["numeric"]["counterexample"]["point"]["x"] < 0


def test_identity_undeclared_symbols_are_sampled_and_noted():
    ev = run("identity", lhs="x + y", rhs="y + x", vars=["x"], seed=1)
    assert ev.result["symbolic"]["relation"] == "equal"
    assert "y" in notes(ev) and ev.result["numeric"]["points_tested"] == 50


def test_identity_a_point_where_one_side_is_undefined_is_skipped_and_counted():
    ev = run("identity", lhs="(x**2 - 1)/(x - 1)", rhs="x + 1", vars=["x"], domain={"x": "integer in [-3, 3]"})
    num = ev.result["numeric"]
    assert ev.result["symbolic"]["relation"] == "equal"
    assert num["counterexample"] is None
    assert num["points_skipped"] == 1 and num["one_side_undefined"] == 1 and num["points_tested"] == 6
    assert "undefined" in notes(ev)


# ---------------------------------------------------------------- identity: honesty


def test_identity_unknown_is_not_not_equal_when_every_point_agrees():
    # sympy cannot reduce this one, but it is true: the numeric part agrees everywhere it looks
    ev = run("identity", lhs="fibonacci(n + 2)", rhs="fibonacci(n + 1) + fibonacci(n)", vars=["n"],
             domain={"n": "integer >= 1"}, seed=4)
    sym, num = ev.result["symbolic"], ev.result["numeric"]
    assert sym["relation"] == "unknown"
    assert "unknown" in sym["source"] and "not" in sym["source"]
    assert num["counterexample"] is None and num["points_tested"] > 0 and num["mismatches"] == 0
    assert "not a proof" in notes(ev) or "not proof" in notes(ev)


def test_identity_numeric_counterexample_with_symbolic_unknown():
    ev = run("identity", lhs="atan(x) + atan(1/x)", rhs="pi/2", vars=["x"], seed=1)
    assert ev.result["symbolic"]["relation"] == "unknown"
    assert ev.result["numeric"]["counterexample"] is not None  # x < 0
    assert ev.result["numeric"]["counterexample"]["point"]["x"] < 0
    ev = run("identity", lhs="atan(x) + atan(1/x)", rhs="pi/2", vars=["x"], domain={"x": "real > 0"}, seed=1)
    assert ev.result["symbolic"]["relation"] == "unknown"
    assert ev.result["numeric"]["counterexample"] is None


def test_identity_symbolic_equal_with_a_numeric_disagreement_is_flagged(monkeypatch):
    # force a (fake) symbolic "equal" for two sides that differ, to see the button report both honestly
    ident = importlib.import_module("abacus.kit.identity")
    monkeypatch.setattr(ident, "_symbolic", lambda *a, **k: ("equal", "pretend source", True))
    ev = run("identity", lhs="x", rhs="x + 1", vars=["x"], seed=1)
    assert ev.result["symbolic"] == {"relation": "equal", "source": "pretend source"}
    assert ev.result["numeric"]["counterexample"] is not None
    assert "symbolic_numeric_disagree" in codes(ev)


def test_identity_numeric_agreement_alone_never_becomes_a_symbolic_equal():
    ev = run("identity", lhs="fibonacci(n + 2)", rhs="fibonacci(n + 1) + fibonacci(n)", vars=["n"],
             domain={"n": "integer in [1, 10]"})
    assert ev.result["numeric"]["enumerated"] is True and ev.result["numeric"]["domain_covered"] is True
    assert ev.result["symbolic"]["relation"] == "unknown"


def test_identity_undefined_functions_leave_no_numeric_points_and_say_so():
    ev = run("identity", lhs="f(x)", rhs="f(x)", vars=["x"], seed=1)
    assert ev.result["numeric"]["points_tested"] == 0
    assert "undefined function" in notes(ev)
    assert "no_points_tested" in codes(ev)


def test_identity_complex_points():
    ev = run("identity", lhs="z*conjugate(z)", rhs="Abs(z)**2", vars=["z"], domain={"z": "complex"}, seed=1)
    assert ev.result["numeric"]["counterexample"] is None and ev.result["numeric"]["points_tested"] == 50
    ev = run("identity", lhs="z**2", rhs="Abs(z)**2", vars=["z"], domain={"z": "complex"}, seed=1)
    cx = ev.result["numeric"]["counterexample"]
    assert cx is not None and isinstance(cx["point"]["z"], str) and "I" in cx["point"]["z"]


def test_identity_stopped_at_the_budget_is_labelled_partial(monkeypatch):
    monkeypatch.setattr(budget.Ctx, "time_left", lambda self: 0.0)
    ev = run("identity", lhs="sin(x)**2 + cos(x)**2", rhs="1", vars=["x"], seed=1)
    assert ev.complete is False
    assert "time budget" in ev.scope
    assert ev.result["numeric"]["points_tested"] == 0
    assert ev.result["symbolic"]["relation"] == "unknown" and "time budget" in ev.result["symbolic"]["source"]


# ---------------------------------------------------------------- identity: seed, compare, bad input


def test_identity_same_seed_same_evidence():
    kw = dict(lhs="(x+1)**2", rhs="x**2 + 1", vars=["x", "y"], seed=11)
    a, b = run("identity", **kw), run("identity", **kw)
    for f in ("result", "scope", "examples", "precision", "notes", "flags", "seed", "input"):
        assert getattr(a, f) == getattr(b, f), f
    c = run("identity", **{**kw, "seed": 12})
    assert c.result["numeric"]["counterexample"] != a.result["numeric"]["counterexample"]


def test_identity_a_seed_is_drawn_and_reported_when_none_is_given():
    ev = run("identity", lhs="x", rhs="x", vars=["x"])
    assert isinstance(ev.seed, int)
    again = run("identity", lhs="(x+1)**2", rhs="x**2+1", vars=["x"], seed=ev.seed)
    assert again.seed == ev.seed


def test_identity_proposed_gives_a_compare():
    ev = run("identity", lhs="sin(x)**2 + cos(x)**2", rhs="1", vars=["x"], proposed="equal", seed=1)
    assert ev.compare == {"proposed": "equal", "computed": "equal", "equal": True}
    ev = run("identity", lhs="(x+1)**2", rhs="x**2+1", vars=["x"], proposed="equal", seed=1)
    assert ev.compare["equal"] is False and ev.compare["computed"] == "not_equal"
    ev = run("identity", lhs="x", rhs="x", vars=["x"], proposed=True, seed=1)
    assert ev.compare["equal"] is True
    assert run("identity", lhs="x", rhs="x", vars=["x"], seed=1).compare is None


@pytest.mark.parametrize("inp", [
    dict(lhs="x**", rhs="x", vars=["x"]),
    dict(lhs="x", rhs="(x +", vars=["x"]),
    dict(lhs="__import__(\x27os\x27)", rhs="1"),
    dict(lhs="x > 1", rhs="x", vars=["x"]),                            # not an expression
    dict(lhs="x", rhs="x", vars=["x"], domain={"x": "gibberish"}),
    dict(lhs="x", rhs="x", vars=["x"], domain={"x": "integer in (1, 2)"}),   # empty
    dict(lhs="x", rhs="x", vars=["x"], domain={"x": "complex >= 1"}),
])
def test_identity_bad_input_is_flagged_not_raised(inp):
    ev = run("identity", **inp)
    assert "bad_input" in codes(ev), (inp, ev.flags)
    assert ev.complete is False and ev.result is None


def test_identity_a_misspelt_key_is_rejected_not_ignored():
    ev = run("identity", lhs="x", rhs="x", vars=["x"], point=10)
    assert "bad_input" in codes(ev)


# ---------------------------------------------------------------- the domain grammar (shared with cas assumptions)


@pytest.mark.parametrize("spec,kind,assumptions", [
    ("integer >= 1", "integer", {"integer": True, "positive": True}),
    ("integer", "integer", {"integer": True}),
    ("positive integer", "integer", {"integer": True, "positive": True}),
    ("real in (0, pi)", "real", {"real": True, "positive": True}),
    ("real in [0, 1]", "real", {"real": True, "nonnegative": True}),
    ("real", "real", {"real": True}),
    ("positive", "real", {"real": True, "positive": True}),
    ("negative real", "real", {"real": True, "negative": True}),
    ("real <= 0", "real", {"real": True, "nonpositive": True}),
    ("integer > 0, <= 10", "integer", {"integer": True, "positive": True}),
    ("integer in [-5, 5]", "integer", {"integer": True}),
    ("complex", "complex", {}),
    ("REAL in (-oo, 3)", "real", {"real": True}),
])
def test_domain_grammar(spec, kind, assumptions):
    d = alg.parse_domain(spec)
    assert d.kind == kind
    assert d.assumptions() == assumptions


@pytest.mark.parametrize("spec", ["", "gibberish", "integer in (1, 2)", "real in (3, 1)", "complex >= 1",
                                  "integer >=", "real in (0, x)", "real in 0, 1", "integer integer", "real in (1, 2, 3)"])
def test_domain_grammar_rejects(spec):
    with pytest.raises(ValueError):
        alg.parse_domain(spec)


def test_domain_windows_say_what_is_sampled():
    assert alg.parse_domain("integer >= 1").window == (1, 31)
    assert alg.parse_domain("integer").window == (-30, 30)
    assert alg.parse_domain("real").window == (-10.0, 10.0)
    assert alg.parse_domain("real in (0, pi)").window == (0.0, pytest.approx(math.pi))
    assert alg.parse_domain("integer in [-5, 5]").count == 11
    assert alg.parse_domain("integer in [-5, 5]").is_infinite() is False
    assert alg.parse_domain("integer >= 1").is_infinite() is True
    assert alg.parse_domain("real in (0, 1)").is_infinite() is True


# ---------------------------------------------------------------- the child-process path


def test_identity_runs_in_a_child_process_under_the_budget_with_the_same_seeded_result():
    # one child only: a spawn imports the whole package and is slow, and the three buttons share the path
    ev = ak.budget("identity", {"lhs": "(x+1)**2", "rhs": "x**2+1", "vars": ["x"], "seed": 9}, time_s=120)
    inproc = run("identity", lhs="(x+1)**2", rhs="x**2+1", vars=["x"], seed=9)
    assert ev.complete and ev.budget["stopped"] is False
    assert ev.result == inproc.result and ev.seed == 9
    assert ev.scope == inproc.scope and ev.examples == inproc.examples


# ---------------------------------------------------------------- review round 1


_EVIL = ('S("_"*2+"imp"+"ort"+"_"*2+"(\x27os\x27).getpid()")',
         'Integer(0)*S("_"*2+"imp"+"ort"+"_"*2+"(\x27os\x27).getpid()")',
         'sympify("1+1")',
         "S('1')",
         'Symbol("x")')


@pytest.mark.parametrize("payload", _EVIL)
def test_a_string_built_at_runtime_is_never_evaluated(payload):
    for name, inp in (("exact", dict(expr=payload)),
                      ("cas", dict(op="simplify", expr=payload)),
                      ("cas", dict(op="solve", expr=payload, vars=["x"])),
                      ("identity", dict(lhs=payload, rhs="1")),
                      ("identity", dict(lhs="1", rhs=payload))):
        ev = run(name, **inp)
        assert "bad_input" in codes(ev), (name, payload, ev.flags)
        assert ev.complete is False and ev.result is None


@pytest.mark.parametrize("name", ["S", "sympify", "parse_expr", "symbols"])
def test_no_whitelisted_name_evaluates_a_string(name):
    assert name not in alg.exact_namespace()
    assert name not in alg.parsing._whitelist()


@pytest.mark.parametrize("quote", ["'", '"'])
def test_parse_rejects_any_quote(quote):
    with pytest.raises(ValueError, match="quote"):
        alg.parse(f"1 + {quote}2{quote}")


def test_exact_mod_of_a_huge_power_finishes_without_building_it():
    import time
    t0 = time.perf_counter()
    ev = run("exact", expr="2**(10**12)", mod=7)
    assert time.perf_counter() - t0 < 2
    assert ev.result["value"] == str(pow(2, 10**12, 7)) and ev.complete and not ev.flags
    assert "modular exponentiation" in ev.scope
    # nested powers, a sum of them, and the `^` spelling
    assert run("exact", expr="3^(2^40) + 5*7**(10**15) - 1", mod=1000).result["value"] ==         str((pow(3, 2**40, 1000) + 5 * pow(7, 10**15, 1000) - 1) % 1000)
    assert run("exact", expr="2**3**4", mod=1000).result["value"] == str(pow(2, 3**4, 1000))
    assert run("exact", expr="-2**(10**12)", mod=7).result["value"] == str((-pow(2, 10**12, 7)) % 7)


def test_exact_mod_after_full_evaluation_says_so():
    ev = run("exact", expr="factorial(20)", mod=1000)
    assert ev.result["value"] == str(math.factorial(20) % 1000)
    assert "after" in notes(ev) and "whole value" in notes(ev)
    assert "after" not in notes(run("exact", expr="2**100"))


def test_exact_an_unevaluated_sum_is_noted():
    ev = run("exact", expr="Sum(k, (k, 1, 10))")
    assert "unevaluated" in notes(ev) and "Sum" in notes(ev)


def test_exact_no_result_is_flagged_and_incomplete():
    ev = run("exact", expr="sqrt_mod(3, 7)")
    assert "no_result" in codes(ev) and ev.complete is False
    assert ev.result["value"] is None


def test_exact_division_by_zero_is_an_undefined_value():
    for src in ("1/0", "0/0"):
        ev = run("exact", expr=src)
        assert "undefined_value" in codes(ev), src
    assert "undefined_value" not in codes(run("exact", expr="1/3"))


def test_cas_a_limit_sympy_gives_up_on_is_not_a_disagreement():
    ev = run("cas", op="limit", expr="f(x)", var="x", point="0")
    assert "limits differ" not in notes(ev) and "two-sided limit does not exist" not in notes(ev)
    assert "could not decide" in notes(ev)
    ev = run("cas", op="limit", expr="Abs(x)/x", var="x", point="0")
    assert "does not exist" in notes(ev) and "could not decide" not in notes(ev)


@pytest.mark.parametrize("expr", ["x==1", "x == 1", "x>=1 == 2"])
def test_cas_solve_with_a_double_equals_is_bad_input(expr):
    ev = run("cas", op="solve", expr=expr, vars=["x"])
    assert "bad_input" in codes(ev) and ev.complete is False
    assert "error" not in codes(ev)
    assert "=" in ev.flags[0]["message"]


def test_cas_a_keyword_argument_is_not_an_equation():
    ev = run("cas", op="simplify", expr="Poly(x**2 + 6, x, modulus=5).as_expr()", vars=["x"])
    assert "bad_input" not in codes(ev), ev.flags
    assert ev.result["value"] == "x**2 + 1"
    ev = run("cas", op="solve", expr="Poly(x**2 - 1, x, modulus=5).as_expr() = 0", vars=["x"])
    assert "bad_input" not in codes(ev), ev.flags
    assert sorted(ev.result["value"].strip("[]").split(", ")) == ["-1", "1"]


def test_cas_diff_says_it_ignored_point():
    ev = run("cas", op="diff", expr="x**2", var="x", point="3")
    assert ev.result["value"] == "2*x"
    assert "point" in notes(ev) and "ignored" in notes(ev)
    assert "ignored" not in notes(run("cas", op="diff", expr="x**2", var="x"))


def test_cas_limit_at_infinity_says_it_ignored_direction():
    ev = run("cas", op="limit", expr="1/x", var="x", point="oo", direction="+")
    assert ev.result["value"] == "0"
    assert "direction" in notes(ev) and "ignored" in notes(ev)
    ev = run("cas", op="limit", expr="1/x", var="x", point="0", direction="+")
    assert "ignored" not in notes(ev)
