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
    assert "optimum_at_infinity" in codes(ev) or "boundary_optimum" in codes(ev)
    assert any("infinity" in n or "infimum" in n for n in ev.notes + [f["message"] for f in ev.flags])


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


def test_numeric_slow_convergence_is_noted_for_a_slow_sum():
    ev = run("numeric", op="sum", expr="1/n**(11/10)", var="n", lo="1", hi="oo", digits=20)
    assert any("converge" in n for n in ev.notes), ev.notes
    assert "slow_convergence" in codes(ev) or "low_accuracy" in codes(ev)


def test_numeric_large_error_estimate_is_noted_for_an_oscillatory_integral():
    ev = run("numeric", op="integral", expr="sin(x)/x", var="x", lo="0", hi="oo")
    assert {"low_accuracy", "no_convergence"} & set(codes(ev))
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
