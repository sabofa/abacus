"""The continuous buttons: identify, extremum, numeric (spec 04 s9-11; known answers in spec 09 s1)."""
import json

import mpmath as mp
import pytest
import sympy as sp

import abacus.kit as ak
from abacus import budget, registry

VERDICT_KEYS = {"correct", "pass", "valid", "score"}


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _keys(v)


def run(name, time_s=None, **inp):
    """Call a button in process and check what every Evidence must satisfy."""
    registry.load_all()
    ev = budget.call(name, inp, in_process=True, time_s=time_s)
    d = ev.to_dict(full=True)
    assert not VERDICT_KEYS & set(_keys(d)), f"verdict key in {name} evidence"
    assert ev.scope and ev.scope.strip()
    assert ev.method in {"symbolic", "numeric", "sampled", "exhaustive", "search", "fit", "timed"}
    json.dumps(d)
    return ev


def codes(ev):
    return [f["code"] for f in ev.flags]


def notes(ev):
    return " | ".join(ev.notes)


def exprs(ev):
    return [c["expression"] for c in ev.result["candidates"]]


def has_candidate(ev, target):
    t = sp.sympify(target)
    for c in ev.result["candidates"]:
        if sp.simplify(sp.sympify(c["expression"]) - t) == 0:
            return c
    return None


# ---------------------------------------------------------------- registry


def test_the_three_buttons_are_registered():
    registry.load_all()
    for name in ("identify", "extremum", "numeric"):
        assert registry.get(name).input_schema["type"] == "object"
        assert not VERDICT_KEYS & set(_keys(registry.get(name).input_schema))
    assert registry.get("extremum").uses_seed is True
    assert registry.get("identify").uses_seed is False and registry.get("numeric").uses_seed is False


def test_the_library_surface_reaches_them():
    ev = ak.numeric(op="sum", expr="1/n**2", var="n", lo="1", hi="oo", digits=15)
    assert ev.button == "numeric" and ev.result["value"].startswith("1.644934066848")


# ---------------------------------------------------------------- identify


def test_identify_euler_gamma_among_the_candidates():
    ev = run("identify", value="0.5772156649015328606")
    c = has_candidate(ev, sp.EulerGamma)
    assert c is not None, exprs(ev)
    assert c["digits_used"] == 19
    assert "residual" in c and float(c["residual"]) < 1e-18
    assert ev.method == "numeric" and ev.complete
    assert ev.precision and "digits" in json.dumps(ev.precision)
    assert not [n for n in ev.notes if "fewer than 15" in n]


def test_identify_with_few_digits_says_the_candidates_are_weak():
    ev = run("identify", value="0.57721566")
    assert any("fewer than 15" in n and "weak" in n for n in ev.notes)
    assert "weak_evidence" in codes(ev)
    assert ev.result["digits_used"] == 8


def test_identify_a_plain_algebraic_number_gives_a_polynomial():
    ev = run("identify", value="sqrt(2)+1", digits=40)
    alg = [c for c in ev.result["candidates"] if c["kind"] == "algebraic"]
    assert alg, exprs(ev)
    assert alg[0]["polynomial"] == "x**2 - 2*x - 1"
    assert alg[0]["coefficients"] == [1, -2, -1]
    assert sp.simplify(sp.sympify(alg[0]["expression"]) - (1 + sp.sqrt(2))) == 0
    assert has_candidate(ev, 1 + sp.sqrt(2)) is not None   # also as a combination of 1 and sqrt(2)


def test_identify_a_cube_root_is_found_as_an_algebraic_number():
    ev = run("identify", value="2**(1/3)", digits=40)
    alg = [c for c in ev.result["candidates"] if c["kind"] == "algebraic"]
    assert alg and alg[0]["polynomial"] == "x**3 - 2"


def test_identify_pi_squared_over_six():
    ev = run("identify", value="1.6449340668482264365")
    assert has_candidate(ev, sp.pi ** 2 / 6) is not None, exprs(ev)


def test_identify_a_rational():
    ev = run("identify", value="0.3333333333333333333")
    assert has_candidate(ev, sp.Rational(1, 3)) is not None


def test_identify_with_a_custom_basis():
    ev = run("identify", value="1+3*log(5)", digits=30, basis=["log(5)", "log(7)"])
    assert has_candidate(ev, 1 + 3 * sp.log(5)) is not None
    assert ev.result["basis"] == ["1", "log(5)", "log(7)"]


def test_identify_value_from_an_expression_uses_the_digits_asked():
    ev = run("identify", value="EulerGamma + 2*zeta(3)", digits=35)
    assert ev.result["digits_used"] == 35
    assert has_candidate(ev, sp.EulerGamma + 2 * sp.zeta(3)) is not None


def test_identify_random_digits_find_nothing_and_say_it_is_not_a_proof():
    ev = run("identify", value="0.38197142817583349520913578")
    assert ev.result["candidates"] == []
    assert "not a proof" in ev.scope or "not a proof" in notes(ev)


def test_identify_random_15_digit_decimals_give_no_spurious_relation():
    # 15 digits is the float limit and the "reliable" threshold: a relation found there must not be an accident.
    import random
    rnd = random.Random(7)
    for _ in range(6):
        v = "0." + str(rnd.randint(1, 9)) + "".join(rnd.choice("0123456789") for _ in range(13)) + str(rnd.randint(1, 9))
        ev = run("identify", value=v)
        assert ev.result["digits_used"] == 15
        assert ev.result["candidates"] == [], (v, ev.result["candidates"])


def test_identify_the_golden_ratio_is_one_candidate():
    ev = run("identify", value="1.6180339887498948482045868343656")
    golden = [c for c in ev.result["candidates"] if sp.simplify(sp.sympify(c["expression"]) - (1 + sp.sqrt(5)) / 2) == 0]
    assert len(golden) == 1, exprs(ev)


def test_identify_candidates_are_ordered_simplest_first():
    ev = run("identify", value="0.5772156649015328606")
    lens = [c["coefficient_digits"] for c in ev.result["candidates"]]
    assert lens == sorted(lens)


def test_identify_proposed_sets_compare():
    ev = run("identify", value="0.5772156649015328606", proposed="EulerGamma")
    assert ev.compare and ev.compare["equal"] is True
    ev = run("identify", value="0.5772156649015328606", proposed="pi/4")
    assert ev.compare["equal"] is False


def test_identify_float_input_counts_only_15_digits():
    ev = run("identify", value=0.5772156649015329)
    assert ev.result["digits_used"] == 15
    assert any("float" in n for n in ev.notes)


@pytest.mark.parametrize("bad", ["", "abc*", "pi.evalf()", "'1'", "0", "1/0"])
def test_identify_bad_value_is_bad_input(bad):
    ev = run("identify", value=bad)
    assert "bad_input" in codes(ev) and ev.complete is False


def test_identify_bad_basis_is_bad_input():
    assert "bad_input" in codes(run("identify", value="1.5", basis=["x.real"]))
    assert "bad_input" in codes(run("identify", value="1.5", basis=["y"]))


def test_identify_a_budget_stop_is_incomplete():
    ev = run("identify", value="0.38197142817583349520913578", time_s=1e-9)
    assert ev.complete is False and "budget_stop" in codes(ev)


# ---------------------------------------------------------------- extremum


def point(best):
    return [best["point"][k] for k in best["point"]]


def test_extremum_x_plus_one_over_x():
    ev = run("extremum", f="x + 1/x", vars={"x": [0, "oo"]}, goal="min", seed=1)
    best = ev.result["best"]
    assert best["value"] == pytest.approx(2.0, abs=1e-7)
    assert best["point"]["x"] == pytest.approx(1.0, abs=1e-3)
    assert ev.result["on_boundary"] is False
    assert ev.seed == 1 and ev.method == "search"
    assert ev.result["starts"] >= 1
    assert "not proof" in ev.scope or "not proof" in notes(ev)


def test_extremum_boundary_optimum_is_flagged():
    ev = run("extremum", f="x**2 + y", vars={"x": [-1, 3], "y": [1, 4]}, goal="min", seed=2)
    best = ev.result["best"]
    assert best["value"] == pytest.approx(1.0, abs=1e-6)
    assert best["point"]["y"] == pytest.approx(1.0, abs=1e-6)
    assert ev.result["on_boundary"] is True
    assert "boundary_optimum" in codes(ev)
    assert any("y" in a and "lower" in a for a in ev.result["active"])


def test_extremum_constrained_x_times_y():
    ev = run("extremum", f="x*y", vars={"x": [0, 2], "y": [0, 2]}, constraints=["x + y == 2"],
             goal="max", seed=3)
    best = ev.result["best"]
    assert best["value"] == pytest.approx(1.0, abs=1e-6)
    assert best["point"]["x"] == pytest.approx(1.0, abs=1e-3) and best["point"]["y"] == pytest.approx(1.0, abs=1e-3)
    assert isinstance(ev.result["near_optimal"], list)
    assert ev.result["starts"] >= 1


def test_extremum_symmetric_case_lists_the_other_optimum():
    ev = run("extremum", f="(x**2 - 1)**2", vars={"x": [-2, 2]}, goal="min", method="multistart",
             starts=30, seed=4)
    best = ev.result["best"]
    assert best["value"] == pytest.approx(0.0, abs=1e-8)
    xs = [best["point"]["x"]] + [p["point"]["x"] for p in ev.result["near_optimal"]]
    assert any(x == pytest.approx(1, abs=1e-3) for x in xs) and any(x == pytest.approx(-1, abs=1e-3) for x in xs)
    others = [p for p in ev.result["near_optimal"] if abs(p["value"] - best["value"]) < 1e-8]
    assert others and all(p["gap"] < 1e-8 for p in others)


def test_extremum_inequality_constraint_is_active():
    ev = run("extremum", f="x + y", vars={"x": [0.1, 10], "y": [0.1, 10]}, constraints=["x*y >= 1"],
             goal="min", seed=5)
    best = ev.result["best"]
    assert best["value"] == pytest.approx(2.0, abs=1e-5)
    assert ev.result["on_boundary"] is True
    assert any("x*y" in a for a in ev.result["active"])


def test_extremum_grid_and_lagrange_agree():
    kw = dict(f="x*y", vars={"x": [0, 2], "y": [0, 2]}, constraints=["x + y == 2"], goal="max")
    g = run("extremum", method="grid", seed=1, **kw)
    lg = run("extremum", method="lagrange", **kw)
    assert g.result["best"]["value"] == pytest.approx(1.0, abs=1e-6)
    assert lg.result["best"]["value"] == pytest.approx(g.result["best"]["value"], abs=1e-6)
    for k in ("x", "y"):
        assert lg.result["best"]["point"][k] == pytest.approx(g.result["best"]["point"][k], abs=1e-3)
    assert lg.method == "symbolic" and lg.result["best"]["exact"] == "1"


def test_extremum_lagrange_unconstrained_and_boundary():
    ev = run("extremum", f="x*(2-x)", vars={"x": [0, 3]}, goal="max", method="lagrange")
    assert ev.result["best"]["value"] == pytest.approx(1.0) and ev.result["best"]["exact"] == "1"
    assert ev.result["on_boundary"] is False
    ev = run("extremum", f="x*(2-x)", vars={"x": [0, 3]}, goal="min", method="lagrange")
    assert ev.result["best"]["exact"] == "-3" and ev.result["on_boundary"] is True
    assert "boundary_optimum" in codes(ev)


def test_extremum_grid_alone_on_a_box():
    ev = run("extremum", f="(x-0.3)**2 + (y-0.7)**2", vars={"x": [0, 1], "y": [0, 1]}, method="grid", seed=1)
    assert ev.result["best"]["value"] == pytest.approx(0.0, abs=1e-8)


def test_extremum_seeded_rerun_is_identical():
    for method in ("multistart", "evolution", "auto"):
        kw = dict(f="sin(3*x) + cos(5*y) + x*y/10", vars={"x": [-2, 2], "y": [-2, 2]}, goal="min",
                  method=method, seed=11)
        a, b = run("extremum", **kw), run("extremum", **kw)
        assert a.result == b.result, method


def test_extremum_different_seeds_still_find_the_optimum():
    vals = [run("extremum", f="(x-1)**2 + (y+2)**2", vars={"x": [-5, 5], "y": [-5, 5]},
                method="evolution", seed=s).result["best"]["value"] for s in (1, 2)]
    assert all(v == pytest.approx(0.0, abs=1e-8) for v in vals)


def test_extremum_code_function():
    ev = run("extremum", f={"code": "lambda x, y: (x-1)**2 + abs(y)"}, vars={"x": [-3, 3], "y": [-3, 3]},
             method="multistart", starts=30, seed=3)
    assert ev.result["best"]["value"] == pytest.approx(0.0, abs=1e-4)
    assert ev.result["best"]["point"]["x"] == pytest.approx(1.0, abs=1e-3)


def test_extremum_proposed_sets_compare():
    ev = run("extremum", f="x + 1/x", vars={"x": [0, "oo"]}, seed=1, proposed="2")
    assert ev.compare["equal"] is True
    ev = run("extremum", f="x + 1/x", vars={"x": [0, "oo"]}, seed=1, proposed=3)
    assert ev.compare["equal"] is False


def test_extremum_bound_forms():
    ev = run("extremum", f="cos(x)", vars={"x": {"min": 0, "max": "2*pi"}}, goal="min", seed=1)
    assert ev.result["best"]["value"] == pytest.approx(-1.0, abs=1e-8)
    assert ev.result["best"]["point"]["x"] == pytest.approx(3.14159265, abs=1e-3)


def test_extremum_unbounded_infimum_is_flagged():
    ev = run("extremum", f="exp(-x)", vars={"x": [0, "oo"]}, goal="min", seed=1)
    assert codes(ev) == ["optimum_at_infinity"]
    assert any("infimum" in n for n in ev.notes)
    assert any("infinity" in f["message"] for f in ev.flags)


def test_extremum_lagrange_on_an_unbounded_variable_does_not_claim_a_minimum():
    # x**3 - 3x has a local minimum -2 at x = 1 but the infimum on the real line is -oo
    ev = run("extremum", f="x**3 - 3*x", vars={"x": [None, None]}, method="lagrange", seed=1)
    assert "optimum_at_infinity" in codes(ev)
    assert ev.complete is False
    assert any("not the global optimum" in n for n in ev.notes)
    # a function that really has a minimum on the line is not flagged
    ev = run("extremum", f="x**2 - 2*x", vars={"x": [None, None]}, method="lagrange", seed=1)
    assert "optimum_at_infinity" not in codes(ev) and ev.complete is True


@pytest.mark.parametrize("kw", [
    dict(f="x + 1/x", vars={"x": ["-oo", "oo"]}),
    dict(f="-x", vars={"x": [0, "oo"]}),
])
def test_extremum_unbounded_problems_stop_early(kw):
    import time
    t = time.monotonic()
    ev = run("extremum", seed=1, **kw)
    assert "optimum_at_infinity" in codes(ev) and "budget_stop" not in codes(ev)
    assert ev.complete is False
    assert ev.result["best"] is None                      # not the -4e12 sample on the way to infinity
    assert abs(ev.result["probe_value"]["value"]) > 1e3   # it is kept, but labelled as a probe
    assert time.monotonic() - t < 8
    assert ev.result["starts"] < 20


RASTRIGIN = "20 + (x**2 - 10*cos(2*pi*x)) + (y**2 - 10*cos(2*pi*y))"


def test_extremum_auto_cross_checks_a_multimodal_function():
    ev = run("extremum", f=RASTRIGIN, vars={"x": [-5.12, 5.12], "y": [-5.12, 5.12]}, seed=1)
    assert abs(ev.result["best"]["value"]) < 1e-6      # the global minimum 0, not the nearest local one (0.995)
    assert "multimodal" in codes(ev)
    assert "evolution" in ev.result["methods_run"]
    assert "not proofs" in notes(ev) + " ".join(f["message"] for f in ev.flags)


def test_extremum_a_single_optimum_is_not_multimodal():
    ev = run("extremum", f="(x - 1)**2 + (y + 2)**2", vars={"x": [-5, 5], "y": [-5, 5]}, seed=1)
    assert "multimodal" not in codes(ev) and ev.result["methods_run"] == ["multistart"]


def test_extremum_grid_near_optimal_holds_only_polished_points():
    ev = run("extremum", f="x**2 + y**2", vars={"x": [-3, 3], "y": [-3, 3]}, method="grid", seed=1)
    assert ev.result["best"]["value"] < 1e-9
    for e in ev.result["near_optimal"]:   # a raw grid seed (value 4.5e-4 and up) is not a result
        assert e["gap"] < 1e-6, e


def test_extremum_near_optimal_drops_unconverged_garbage():
    ev = run("extremum", f="x**2 + y**2", vars={"x": [None, None], "y": [None, None]},
             constraints=["x*y >= 1"], seed=1)
    assert ev.result["best"]["value"] == pytest.approx(2.0, abs=1e-6)
    assert all(e["value"] < 1e3 for e in ev.result["near_optimal"]), ev.result["near_optimal"]


@pytest.mark.parametrize("kw", [
    dict(f="x + z", vars={"x": [0, 1]}),                       # z is not a variable
    dict(f="x", vars={"x": [2, 1]}),                           # empty interval
    dict(f="x.real", vars={"x": [0, 1]}),                      # attribute access
    dict(f="'x'", vars={"x": [0, 1]}),                         # quote
    dict(f="x", vars={"x": [0, 1]}, constraints=["x ~ 1"]),    # not a relation
    dict(f="x", vars={"x": [0, 1]}, constraints=["w >= 1"]),   # unknown name in a constraint
    dict(f={"code": "lambda x: x"}, vars={"x": [0, 1]}, method="lagrange"),
    dict(f="x", vars={"x": [0, "banana"]}),
    dict(f="x*y", vars={"x": [0, 1], "y": [0, 1]}, constraints=["x**2 == y**2"],
         method="grid"),                                       # an equality grid cannot eliminate
])
def test_extremum_bad_input(kw):
    ev = run("extremum", seed=1, **kw)
    assert "bad_input" in codes(ev) and ev.complete is False, ev.flags


def test_extremum_a_budget_stop_is_incomplete():
    ev = run("extremum", f="sin(3*x) + cos(5*y)", vars={"x": [-2, 2], "y": [-2, 2]}, seed=1, time_s=1e-9)
    assert ev.complete is False and "budget_stop" in codes(ev)


def test_extremum_streams_progress():
    seen = []
    from abacus.budget import Ctx
    import time as _t
    b = registry.get("extremum")
    ev = b.fn({"f": "sin(3*x) + cos(5*y)", "vars": {"x": [-2, 2], "y": [-2, 2]}, "method": "multistart",
               "starts": 10, "seed": 1}, Ctx(1, _t.monotonic() + 30, seen.append))
    assert seen and all("result" in p and "scope" in p for p in seen)
    assert ev.complete


# ---------------------------------------------------------------- numeric


def mpv(ev, dps=60):
    with mp.workdps(dps):
        return mp.mpf(ev.result["value"])


def test_numeric_gaussian_integral_to_30_digits():
    ev = run("numeric", op="integral", expr="exp(-x**2)", var="x", lo="0", hi="oo")
    assert ev.method == "numeric" and ev.complete
    with mp.workdps(60):
        assert abs(mpv(ev) - mp.sqrt(mp.pi) / 2) < mp.mpf(10) ** -29
    assert ev.result["digits"] == 30
    assert ev.precision["digits"] >= 29
    assert ev.result["error_estimate"] is not None


def test_numeric_integral_over_the_whole_line():
    ev = run("numeric", op="integral", expr="exp(-x**2)", var="x", lo="-oo", hi="oo", digits=20)
    with mp.workdps(40):
        assert abs(mpv(ev, 40) - mp.sqrt(mp.pi)) < mp.mpf(10) ** -19


def test_numeric_sum_of_inverse_squares():
    ev = run("numeric", op="sum", expr="1/n**2", var="n", lo="1", hi="oo")
    with mp.workdps(60):
        assert abs(mpv(ev) - mp.pi ** 2 / 6) < mp.mpf(10) ** -29


def test_numeric_finite_sum_is_exactly_summed():
    ev = run("numeric", op="sum", expr="n", var="n", lo="1", hi="100", digits=10)
    assert ev.result["value"].startswith("5050")


def test_numeric_product():
    ev = run("numeric", op="product", expr="1 - 1/(n+1)**2", var="n", lo="1", hi="oo", digits=20)
    assert abs(mpv(ev) - mp.mpf("0.5")) < mp.mpf(10) ** -19


def test_numeric_limits():
    ev = run("numeric", op="limit", expr="sin(x)/x", var="x", at="0")
    assert abs(mpv(ev) - 1) < mp.mpf(10) ** -29
    ev = run("numeric", op="limit", expr="(1 + 1/n)**n", var="n", at="oo", digits=25)
    with mp.workdps(60):
        assert abs(mpv(ev) - mp.e) < mp.mpf(10) ** -24


def test_numeric_root():
    ev = run("numeric", op="root", expr="cos(x) - x", var="x", x0="0.7")
    with mp.workdps(60):
        assert abs(mpv(ev) - mp.findroot(lambda x: mp.cos(x) - x, mp.mpf("0.7"))) < mp.mpf(10) ** -29
    assert float(ev.result["residual"]) < 1e-29


def test_numeric_root_with_a_bracket_and_an_equation():
    ev = run("numeric", op="root", expr="x**2 == 2", var="x", x0=["1", "2"], digits=40)
    with mp.workdps(60):
        assert abs(mpv(ev) - mp.sqrt(2)) < mp.mpf(10) ** -39


def test_numeric_root_of_a_system():
    ev = run("numeric", op="root", expr=["x**2 + y**2 - 1", "x - y"], var=["x", "y"], x0=["1", "1"])
    with mp.workdps(60):
        vals = [mp.mpf(v) for v in ev.result["value"]]
        assert all(abs(v - mp.sqrt(2) / 2) < mp.mpf(10) ** -29 for v in vals)


def test_numeric_ode_exponential():
    ev = run("numeric", op="ode", expr="y", var="t", y="y", y0="1", t0="0", at="1")
    with mp.workdps(60):
        assert abs(mpv(ev) - mp.e) < mp.mpf(10) ** -29
    ev = run("numeric", op="ode", expr="y", var="t", y="y", y0="1", t0="0", at="-1", digits=20)
    with mp.workdps(40):
        assert abs(mpv(ev, 40) - mp.exp(-1)) < mp.mpf(10) ** -19


def test_numeric_ode_system():
    # y'' = -y as y' = z, z' = -y;  y(0) = 0, z(0) = 1  ->  y = sin t
    ev = run("numeric", op="ode", expr=["z", "-y"], var="t", y=["y", "z"], y0=["0", "1"], t0="0", at="1",
             digits=20)
    with mp.workdps(40):
        assert abs(mp.mpf(ev.result["value"][0]) - mp.sin(1)) < mp.mpf(10) ** -19
        assert abs(mp.mpf(ev.result["value"][1]) - mp.cos(1)) < mp.mpf(10) ** -19


def test_numeric_states_its_digits():
    ev = run("numeric", op="integral", expr="exp(-x**2)", var="x", lo="0", hi="oo", digits=50)
    assert ev.result["digits"] == 50
    assert len(ev.result["value"].replace(".", "").lstrip("0")) >= 50


def test_numeric_slow_convergence_is_flagged_and_the_value_is_right():
    ev = run("numeric", op="sum", expr="1/n**(11/10)", var="n", lo="1", hi="oo", digits=20)
    assert codes(ev) == ["slow_convergence"], ev.flags
    assert any("converge" in n for n in ev.notes), ev.notes
    with mp.workdps(40):
        assert abs(mpv(ev, 40) - mp.zeta(mp.mpf(11) / 10)) < mp.mpf(10) ** -18
    assert ev.complete is True and ev.result["reliable_digits"] >= 19


@pytest.mark.parametrize("expr,lo,code", [
    ("1/n", "1", "divergent"),
    ("1", "1", "divergent"),
    ("2**n", "0", "divergent"),
    ("(-1)**n", "0", "divergent"),
    ("n", "1", "divergent"),
    ("1/(n*log(n+1))", "1", None),     # borderline: diverges, and a numeric test cannot tell it from p > 1
])
def test_numeric_divergent_and_oscillating_sums_are_flagged_not_reported(expr, lo, code):
    ev = run("numeric", op="sum", expr=expr, var="n", lo=lo, hi="oo", digits=30)
    assert ev.complete is False
    assert ev.result is None
    assert set(codes(ev)) & {"divergent", "no_convergence"}
    if code:
        assert code in codes(ev), ev.flags


@pytest.mark.parametrize("expr,lo,exact", [
    ("1/n**2", "1", "pi**2/6"),
    ("1/n**3", "1", "zeta(3)"),
    ("1/n**4", "1", "pi**4/90"),
    ("(-1)**n/n", "1", "-log(2)"),
    ("1/2**n", "0", "2"),
])
def test_numeric_convergent_sums_are_still_computed(expr, lo, exact):
    ev = run("numeric", op="sum", expr=expr, var="n", lo=lo, hi="oo", digits=30)
    assert ev.complete is True and not ({"divergent", "no_convergence"} & set(codes(ev))), ev.flags
    assert ev.result["reliable_digits"] >= 29
    with mp.workdps(50):
        assert abs(mpv(ev, 50) - mp.mpf(str(sp.N(sp.sympify(exact), 50)))) < mp.mpf(10) ** -29


def test_numeric_divergent_product_is_flagged():
    ev = run("numeric", op="product", expr="1 + 1/n", var="n", lo="1", hi="oo")
    assert ev.complete is False and ev.result is None and "divergent" in codes(ev)


@pytest.mark.parametrize("expr", ["sin(x)", "1", "cos(x**2)"])
def test_numeric_infinite_integrals_with_no_limit_are_not_reported(expr):
    # mpmath returned about -2.5e44 for sin(x) with an error estimate of 1 and a clean "30 digits"
    ev = run("numeric", op="integral", expr=expr, var="x", lo="0", hi="oo")
    assert ev.complete is False
    assert codes(ev) == ["no_convergence"]
    assert _value(ev) is None, ev.result
    assert (ev.result or {}).get("reliable_digits", 0) == 0


def test_numeric_infinite_integrals_that_converge_are_still_computed():
    ev = run("numeric", op="integral", expr="exp(-x**2)", var="x", lo="0", hi="oo")
    assert ev.complete is True and ev.result["reliable_digits"] >= 29
    with mp.workdps(50):
        assert abs(mpv(ev, 50) - mp.sqrt(mp.pi) / 2) < mp.mpf(10) ** -29
    ev = run("numeric", op="integral", expr="1/(1 + x**2)", var="x", lo="-oo", hi="oo")
    with mp.workdps(50):
        assert ev.complete is True and abs(mpv(ev, 50) - mp.pi) < mp.mpf(10) ** -29


def test_numeric_oscillating_decaying_integral_is_either_right_or_flagged():
    ev = run("numeric", op="integral", expr="cos(x**2)", var="x", lo="0", hi="oo")
    if ev.complete:
        with mp.workdps(50):
            assert abs(mpv(ev, 50) - mp.sqrt(mp.pi / 8)) < mp.mpf(10) ** -(ev.result["reliable_digits"] - 1)
    else:
        assert "no_convergence" in codes(ev)
        assert ev.result is None or abs(mp.mpf(ev.result["value"])) < 1e6   # never the 1e44 garbage


def test_numeric_removable_singularity_inside_the_range():
    ev = run("numeric", op="integral", expr="sin(x)/x", var="x", lo="-1", hi="1")
    assert ev.complete is True and "bad_input" not in codes(ev)
    with mp.workdps(50):
        assert abs(mpv(ev, 50) - 2 * mp.si(1)) < mp.mpf(10) ** -29
    ev = run("numeric", op="integral", expr="sin(x - 1)/(x - 1)", var="x", lo="0", hi="2")   # at the midpoint
    assert ev.complete is True
    with mp.workdps(50):
        assert abs(mpv(ev, 50) - 2 * mp.si(1)) < mp.mpf(10) ** -29


def test_numeric_a_real_pole_inside_the_range_is_not_integrated_through():
    ev = run("numeric", op="integral", expr="1/x", var="x", lo="-1", hi="1")
    assert ev.complete is False


def test_numeric_root_without_a_sign_change_in_the_bracket_is_flagged():
    ev = run("numeric", op="root", expr="x**2 - 4", var="x", x0=["0", "1"])
    assert "no_sign_change" in codes(ev) and "root_outside_bracket" in codes(ev)
    ev = run("numeric", op="root", expr="x**2 - 4", var="x", x0=["0", "3"])
    assert not {"no_sign_change", "root_outside_bracket"} & set(codes(ev))


@pytest.mark.parametrize("expr", ["(x - 1)**2", "(x - 1)**3"])
def test_numeric_a_multiple_root_is_found_through_the_derivative(expr):
    ev = run("numeric", op="root", expr=expr, var="x", x0="3")
    assert ev.complete is True and "multiple_root" in codes(ev)
    assert abs(mpv(ev) - 1) < mp.mpf(10) ** -25


def test_numeric_a_simple_root_is_not_marked_multiple():
    ev = run("numeric", op="root", expr="x**2 - 4", var="x", x0="3")
    assert "multiple_root" not in codes(ev)


def test_numeric_large_error_estimate_is_noted_for_an_oscillatory_integral():
    ev = run("numeric", op="integral", expr="sin(x)/x", var="x", lo="0", hi="oo")
    assert "no_convergence" in codes(ev) and ev.complete is False
    assert ev.precision["digits"] < 30
    assert any("error estimate" in n for n in ev.notes)


def test_numeric_proposed_sets_compare():
    ev = run("numeric", op="integral", expr="exp(-x**2)", var="x", lo="0", hi="oo", proposed="sqrt(pi)/2")
    assert ev.compare["equal"] is True
    ev = run("numeric", op="integral", expr="exp(-x**2)", var="x", lo="0", hi="oo", proposed="0.9")
    assert ev.compare["equal"] is False


@pytest.mark.parametrize("kw", [
    dict(op="integral", expr="x + y", var="x", lo="0", hi="1"),             # y is free
    dict(op="integral", expr="x.real", var="x", lo="0", hi="1"),            # attribute
    dict(op="integral", expr="'x'", var="x", lo="0", hi="1"),               # quote
    dict(op="integral", expr="x", var="x", lo="0"),                         # no upper limit
    dict(op="integral", expr="x", var="x", lo="a", hi="1"),                 # bound not a number
    dict(op="sum", expr="1/n", var="n", lo="1"),
    dict(op="limit", expr="x", var="x"),
    dict(op="root", expr="x", var="x"),
    dict(op="ode", expr="y", var="t", y="y", y0="1", t0="0"),               # no `at`
    dict(op="integral", expr="1/x", var="x", lo="0", hi="1", digits=10),    # divergent: reported, not raised
])
def test_numeric_bad_input(kw):
    ev = run("numeric", **kw)
    assert "bad_input" in codes(ev) or "no_convergence" in codes(ev), ev.flags
    assert ev.complete is False


def test_numeric_schema_rejects_an_unknown_op_and_digits_out_of_range():
    assert "bad_input" in codes(run("numeric", op="derivative", expr="x"))
    assert "bad_input" in codes(run("numeric", op="integral", expr="x", var="x", lo="0", hi="1", digits=0))


def test_numeric_a_budget_stop_is_incomplete():
    ev = run("numeric", op="integral", expr="exp(-x**2)", var="x", lo="0", hi="oo", digits=300, time_s=1e-9)
    assert ev.complete is False and "budget_stop" in codes(ev)


def test_numeric_leaves_the_global_precision_alone():
    before = mp.mp.dps
    run("numeric", op="integral", expr="exp(-x**2)", var="x", lo="0", hi="oo", digits=80)
    run("identify", value="0.5772156649015328606")
    assert mp.mp.dps == before


# ---------------------------------------------------------------- T6 review round 2


def _value(ev):
    return None if ev.result is None else ev.result.get("value")


@pytest.mark.parametrize("expr,lo,hi,true", [
    ("exp(-100*x)", "0", "oo", lambda: mp.mpf(1) / 100),
    ("exp(-1000*x)", "0", "oo", lambda: mp.mpf(1) / 1000),
    ("x**40*exp(-x)", "0", "oo", lambda: mp.factorial(40)),
    ("exp(-(x - 20)**2)", "0", "oo", lambda: mp.sqrt(mp.pi) * (1 + mp.erf(20)) / 2),
    ("exp(-(x - 50)**2)", "-oo", "oo", lambda: mp.sqrt(mp.pi)),
])
def test_numeric_fast_decaying_or_shifted_integrals_are_not_rejected(expr, lo, hi, true):
    # the scale test used to compare against |f| on the first 10 units only, so each of these looked "enormous"
    ev = run("numeric", op="integral", expr=expr, var="x", lo=lo, hi=hi, digits=20)
    assert ev.complete is True and "no_convergence" not in codes(ev), (ev.flags, ev.result)
    assert ev.result["reliable_digits"] >= 15
    with mp.workdps(60):
        t = true()
        assert abs(mpv(ev, 60) - t) <= abs(t) * mp.mpf(10) ** -15


@pytest.mark.parametrize("expr", ["1/x", "x**(-1.1)"])
def test_numeric_slow_or_divergent_infinite_integrals_carry_no_digits(expr):
    ev = run("numeric", op="integral", expr=expr, var="x", lo="1", hi="oo")
    assert ev.complete is False and codes(ev) == ["no_convergence"]
    assert _value(ev) is None
    assert (ev.result or {}).get("reliable_digits", 0) == 0
    assert "error_estimate" not in (ev.result or {}) and (ev.precision or {}).get("digits", 0) == 0


def test_numeric_flagged_finite_divergent_integral_carries_no_digits():
    ev = run("numeric", op="integral", expr="1/x", var="x", lo="0", hi="1")
    assert ev.complete is False
    assert _value(ev) is None and (ev.result or {}).get("reliable_digits", 0) == 0


def test_numeric_root_with_equal_ends_and_equal_signs_is_no_sign_change_not_bad_input():
    ev = run("numeric", op="root", expr="x**2 - 4", var="x", x0=["-3", "3"])
    assert "bad_input" not in codes(ev) and "no_sign_change" in codes(ev), (ev.flags, ev.result)


# ---------------------------------------------------------------- infinite range: mass outside the sampled reach


@pytest.mark.parametrize("expr,lo", [
    ("exp(-(x - 5000)**2)", "-oo"),
    ("exp(-(x - 1000)**2)", "-oo"),
    ("exp(-(x - 5000)**2)", "0"),
])
def test_numeric_infinite_integral_with_mass_outside_the_sampled_reach_is_withheld(expr, lo):
    # sqrt(pi) was reported as 0 with 20 reliable digits: the splits and the scale probe never saw the far peak
    ev = run("numeric", op="integral", expr=expr, var="x", lo=lo, hi="oo", digits=20)
    assert _value(ev) is None, ev.result
    assert ev.complete is False
    assert (ev.result or {}).get("reliable_digits", 0) == 0
    assert "error_estimate" not in (ev.result or {}) and (ev.precision or {}).get("digits", 0) == 0
    assert "no_mass_observed" in codes(ev), ev.flags
    assert "sampled" in ev.scope and "cannot be ruled out" in ev.scope


@pytest.mark.parametrize("expr,lo,hi,true", [
    ("exp(-x**2)", "-oo", "oo", lambda: mp.sqrt(mp.pi)),
    ("exp(-(x - 20)**2)", "-oo", "oo", lambda: mp.sqrt(mp.pi)),
    ("exp(-(x - 50)**2)", "-oo", "oo", lambda: mp.sqrt(mp.pi)),
    ("1/(1 + x**2)", "0", "oo", lambda: mp.pi / 2),
    ("x**2*exp(-x)", "0", "oo", lambda: mp.mpf(2)),
    ("1/x**2", "1", "oo", lambda: mp.mpf(1)),
])
def test_numeric_spikes_and_tails_inside_the_reach_still_compute_and_state_the_reach(expr, lo, hi, true):
    ev = run("numeric", op="integral", expr=expr, var="x", lo=lo, hi=hi, digits=20)
    assert ev.complete is True and ev.result["reliable_digits"] >= 15, (ev.flags, ev.result)
    with mp.workdps(60):
        t = true()
        assert abs(mpv(ev, 60) - t) <= abs(t) * mp.mpf(10) ** -15
    assert "|x| <=" in ev.scope and "cannot be ruled out" in ev.scope
    assert "sampled reach only" in notes(ev)


def test_numeric_infinite_integral_not_known_to_decay_in_the_reach_is_withheld():
    # exp(-1e-9 x) is still ~0.9 at the edge of the sampled reach: the answer (1e9) depends on unsampled mass
    ev = run("numeric", op="integral", expr="exp(-x/10**9)", var="x", lo="0", hi="oo", digits=20)
    assert _value(ev) is None and ev.complete is False
    assert (ev.result or {}).get("reliable_digits", 0) == 0
    assert set(codes(ev)) & {"unconfirmed_decay", "no_convergence"}, ev.flags


# ---------------------------------------------------------------- infinite sums: mass outside the sampled reach


@pytest.mark.parametrize("expr", [
    "exp(-(n - 5000)**2)",          # sqrt(pi)
    "exp(-(n - 100)**2/20)",        # about 7.9
    "exp(-(n - 200)**2/20)",
    "exp(-(n - 1000)**2/20)",
])
def test_numeric_infinite_sum_with_mass_outside_the_sampled_reach_is_withheld(expr):
    # all four were reported as 0, complete, with no flag
    ev = run("numeric", op="sum", expr=expr, var="n", lo="0", hi="oo", digits=20)
    assert _value(ev) is None, ev.result
    assert ev.complete is False
    assert (ev.result or {}).get("reliable_digits", 0) == 0
    assert "error_estimate" not in (ev.result or {}) and (ev.precision or {}).get("digits", 0) == 0
    assert set(codes(ev)) & {"no_mass_observed", "unconfirmed_decay"}, ev.flags
    assert "sampled" in ev.scope and "cannot be ruled out" in ev.scope


def test_numeric_infinite_sum_not_negligible_near_the_edge_of_the_reach_is_withheld():
    # terms of size ~1 out to n ~ 1e8: they pass the divergence check at 1e9 yet are not seen to decay in the reach
    ev = run("numeric", op="sum", expr="exp(-(n/10**8)**2)", var="n", lo="0", hi="oo", digits=20)
    assert _value(ev) is None and ev.complete is False
    assert (ev.result or {}).get("reliable_digits", 0) == 0
    assert set(codes(ev)) & {"unconfirmed_decay", "no_convergence", "divergent"}, ev.flags


@pytest.mark.parametrize("expr,lo,true", [
    ("exp(-(n - 20)**2/20)", "0", lambda: sum(mp.exp(-(mp.mpf(k) - 20) ** 2 / 20) for k in range(0, 400))),
    ("1/n**2", "1", lambda: mp.pi ** 2 / 6),
    ("1/n**3", "1", lambda: mp.zeta(3)),
    ("1/n**4", "1", lambda: mp.pi ** 4 / 90),
    ("(-1)**n/n", "1", lambda: -mp.log(2)),
    ("n/2**n", "0", lambda: mp.mpf(2)),
    ("n**2/3**n", "0", lambda: mp.mpf(3) / 2),
    ("1/(n**2 + 1)", "0", lambda: (1 + mp.pi * mp.coth(mp.pi)) / 2),
    ("1/n**1.5", "1", lambda: mp.zeta(mp.mpf(3) / 2)),
    ("1/n**2", "1000", lambda: mp.zeta(2) - sum(1 / mp.mpf(k) ** 2 for k in range(1, 1000))),
    ("1/n**(11/10)", "1", lambda: mp.zeta(mp.mpf(11) / 10)),
    ("1/n**(11/10)", "1000", lambda: mp.zeta(mp.mpf(11) / 10) - sum(1 / mp.mpf(k) ** mp.mpf("1.1") for k in range(1, 1000))),
])
def test_numeric_infinite_sums_inside_the_reach_still_compute_and_state_the_reach(expr, lo, true):
    ev = run("numeric", op="sum", expr=expr, var="n", lo=lo, hi="oo", digits=15)
    assert ev.complete is True and not ({"divergent", "no_convergence", "no_mass_observed", "unconfirmed_decay"}
                                        & set(codes(ev))), (ev.flags, ev.result)
    assert ev.result["reliable_digits"] >= 12, ev.result
    with mp.workdps(60):
        t = true()
        assert abs(mpv(ev, 60) - t) <= abs(t) * mp.mpf(10) ** -12
    assert "n - " in ev.scope and "cannot be ruled out" in ev.scope
    assert "sampled reach only" in notes(ev)


def test_numeric_the_reach_wording_names_peaks_between_the_sampled_points():
    ev = run("numeric", op="integral", expr="exp(-x**2)", var="x", lo="-oo", hi="oo", digits=15)
    assert "mass beyond that, or in a narrow peak between the sampled points, cannot be ruled out" in ev.scope
    assert "narrow peak between the sampled points" in notes(ev)
    ev = run("numeric", op="sum", expr="1/n**2", var="n", lo="1", hi="oo", digits=15)
    assert "mass beyond that, or in a narrow peak between the sampled points, cannot be ruled out" in ev.scope
    assert "narrow peak between the sampled points" in notes(ev)


def test_numeric_description_names_the_known_limitation():
    registry.load_all()
    desc = registry.get("numeric").description if hasattr(registry, "get") else ""
    assert "narrow peak between the sampled points" in desc
