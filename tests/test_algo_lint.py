from pathlib import Path

from abacus.algo import surface  # noqa: F401  (registers the algo_lint button the budget tests call)
from abacus.algo.lint import CHECKS, lint

FIX = Path(__file__).parent / "fixtures" / "algos"
BANNED = {"correct", "pass", "passed", "valid", "score", "verdict"}


def by_name(ev):
    return {c["check"]: c for c in ev.result["checks"]}


def walk_keys(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from walk_keys(v)
    elif isinstance(x, list):
        for v in x:
            yield from walk_keys(v)


def test_clean_file_reports_ok_and_no_verdict_keys():
    ev = lint(FIX / "nt_power_mod.py", k=4)
    c = by_name(ev)
    assert list(c) == list(CHECKS)
    assert all(v["status"] in ("ok", "problem", "skipped") for v in c.values())
    for name in ("header", "roles exist", "requires", "determinism", "agreement", "range", "spread", "cost"):
        assert c[name]["status"] == "ok", c[name]
    assert ev.result["distinct_answers"] >= 1
    assert c["spread"]["detail"]["seeds"] == 4
    assert not BANNED & set(walk_keys(ev.to_dict()))
    assert ev.complete


def test_one_off_has_spread_of_one_and_no_range_problem():
    c = by_name(lint(FIX / "one_off.py", k=3))
    assert c["spread"]["detail"]["distinct"] == 1
    assert c["range"]["status"] == "ok"
    assert c["agreement"]["status"] == "ok"


def test_nondeterministic_generate():
    c = by_name(lint(FIX / "lint_nondet.py", k=3))
    assert c["determinism"]["status"] == "problem"
    assert c["header"]["status"] == "ok"


def test_compute_disagrees_with_generate():
    c = by_name(lint(FIX / "lint_disagree.py", k=3))
    assert c["agreement"]["status"] == "problem"
    assert c["agreement"]["detail"][0]["role"] == "compute"
    assert c["determinism"]["status"] == "ok"


def test_out_of_range():
    c = by_name(lint(FIX / "lint_range.py", k=3))
    assert c["range"]["status"] == "problem"
    assert "outside" in c["range"]["detail"][0]


def test_missing_declared_role():
    c = by_name(lint(FIX / "lint_missing_role.py", k=2))
    assert c["roles exist"]["status"] == "problem"
    assert "check" in c["roles exist"]["detail"]
    assert c["agreement"]["status"] == "ok"  # compute alone still agrees


def test_syntax_error_is_verbatim_and_rest_skipped():
    ev = lint(FIX / "lint_syntax_error.py")
    c = by_name(ev)
    assert c["header"]["status"] == "problem"
    assert "SyntaxError" in c["header"]["detail"]
    assert all(c[n]["status"] == "skipped" for n in CHECKS if n != "header")


def test_bad_meta_and_missing_file(tmp_path):
    f = tmp_path / "bad.py"
    f.write_text("META = {'id': 'Nope'}\n", encoding="utf-8")
    c = by_name(lint(f))
    assert c["header"]["status"] == "problem" and "bad META" in c["header"]["detail"]
    c2 = by_name(lint(tmp_path / "absent.py"))
    assert c2["header"]["status"] == "problem"


def test_missing_requires(tmp_path):
    f = tmp_path / "req.py"
    f.write_text(
        'META = {"id": "x.req", "title": "T", "summary": "S.", "roles": ["compute"],'
        ' "answer": {"format": "integer"}, "requires": ["no_such_module_zzz"]}\n'
        "def compute(params):\n    return 1\n", encoding="utf-8")
    c = by_name(lint(f))
    assert c["requires"]["status"] == "problem"
    assert c["determinism"]["status"] == "skipped"


def flags_by_code(ev):
    return {f["code"]: f["message"] for f in ev.flags}


def test_default_k_is_the_spec_default():
    from abacus.algo.lint import DEFAULT_K
    assert DEFAULT_K == 20
    assert lint(FIX / "lint_syntax_error.py").result["k"] == 20


def test_constant_answer_with_knobs_is_flagged_in_spread():
    ev = lint(FIX / "lint_const.py", k=4)
    c = by_name(ev)
    assert c["spread"]["status"] == "problem"
    assert c["spread"]["detail"]["distinct"] == 1 and c["spread"]["detail"]["seeds"] == 4
    assert "knobs" in c["spread"]["detail"]["note"]
    assert c["agreement"]["status"] == "ok" and c["range"]["status"] == "ok"
    assert "spread" in flags_by_code(ev)


def test_one_off_spread_is_ok_with_a_note_that_one_answer_is_expected():
    ev = lint(FIX / "one_off.py", k=3)
    d = by_name(ev)["spread"]
    assert d["status"] == "ok" and d["detail"]["distinct"] == 1
    assert "one answer is expected" in d["detail"]["note"]
    assert ev.flags == []


def test_one_instance_cannot_show_a_spread_problem():
    d = by_name(lint(FIX / "lint_const.py", k=1))["spread"]
    assert d["status"] == "ok" and "only one instance" in d["detail"]["note"]


def _write(tmp_path, name, header_extra, body):
    f = tmp_path / name
    f.write_text('META = {"id": "x.t", "title": "T", "summary": "S.", "roles": ["generate", "compute"],'
                 f" {header_extra}}}\n" + body, encoding="utf-8")
    return f


def test_sympy_and_numpy_integers_are_integers(tmp_path):
    f = _write(tmp_path, "sym.py",
               '"answer": {"format": "integer", "range": [0, 100]}, "knobs": {"n": {"int": [1, 9]}}',
               "import sympy as sp\nimport numpy as np\n"
               "def compute(params):\n    return params['n']\n"
               "def generate(rng, knobs):\n"
               "    n = rng.randint(1, 9)\n"
               "    ans = sp.Integer(n) if n % 2 else np.int64(n)\n"
               "    return {'params': {'n': n}, 'statement': 's', 'answer': ans}\n")
    ev = lint(f, k=6)
    c = by_name(ev)
    assert c["range"]["status"] == "ok", c["range"]
    assert c["agreement"]["status"] == "ok" and c["determinism"]["status"] == "ok"
    assert ev.flags == []


def test_sympy_rational_and_numpy_float_fit_a_numeric_range(tmp_path):
    f = _write(tmp_path, "rat.py",
               '"answer": {"format": "rational", "range": [0, 1]}, "knobs": {"n": {"int": [2, 9]}}',
               "import sympy as sp\nimport numpy as np\n"
               "def compute(params):\n    return sp.Rational(1, params['n'])\n"
               "def generate(rng, knobs):\n"
               "    n = rng.randint(2, 9)\n"
               "    ans = sp.Rational(1, n) if n % 2 else np.float64(1 / n)\n"
               "    return {'params': {'n': n}, 'statement': 's', 'answer': ans}\n")
    assert by_name(lint(f, k=6))["range"]["status"] == "ok"


def test_a_real_non_integer_and_a_real_out_of_range_still_report(tmp_path):
    f = _write(tmp_path, "bad.py",
               '"answer": {"format": "integer", "range": [0, 5]}, "knobs": {"n": {"int": [1, 9]}}',
               "import sympy as sp\n"
               "def compute(params):\n    return params['n']\n"
               "def generate(rng, knobs):\n"
               "    n = rng.randint(1, 9)\n"
               "    return {'params': {'n': n}, 'statement': 's', 'answer': sp.Rational(n, 2) if n == 3 else n + 10}\n")
    out = by_name(lint(f, k=8))["range"]
    assert out["status"] == "problem"
    assert any("not an integer" in m for m in out["detail"]) and any("outside" in m for m in out["detail"])


def test_each_problem_is_mirrored_into_a_flag_named_for_its_check():
    ev = lint(FIX / "lint_range.py", k=3)
    flags = flags_by_code(ev)
    assert set(flags) == {c["check"].replace(" ", "_") for c in ev.result["checks"] if c["status"] == "problem"}
    assert "range" in flags and "outside" in flags["range"]
    ev = lint(FIX / "lint_syntax_error.py")
    assert flags_by_code(ev)["header"].startswith("SyntaxError")
    assert lint(FIX / "nt_power_mod.py", k=3).flags == []


def test_flag_codes_are_snake_case_while_check_names_keep_their_spaces():
    ev = lint(FIX / "lint_missing_role.py", k=2)
    assert by_name(ev)["roles exist"]["status"] == "problem"  # the check name in the result is unchanged
    codes = [f["code"] for f in ev.flags]
    assert "roles_exist" in codes and "roles exist" not in codes
    assert all(" " not in c for c in codes)
    assert "check" in flags_by_code(ev)["roles_exist"]


def test_import_time_exit_is_a_header_problem_not_a_crash(tmp_path):
    f = tmp_path / "quits.py"
    f.write_text("import sys\nsys.exit(2)\n", encoding="utf-8")
    c = by_name(lint(f))
    assert c["header"]["status"] == "problem" and "SystemExit" in c["header"]["detail"]


def test_a_role_that_exits_is_reported_not_fatal(tmp_path):
    f = _write(tmp_path, "exit_gen.py", '"answer": {"format": "integer"}',
               "import sys\ndef compute(params):\n    return 1\n"
               "def generate(rng, knobs):\n    sys.exit(1)\n")
    c = by_name(lint(f, k=2))
    assert c["determinism"]["status"] == "problem" and "SystemExit" in str(c["determinism"]["detail"])


def test_lint_stops_at_its_deadline_and_says_how_far_it_got():
    ev = lint(FIX / "lint_slow_gen.py", k=50, time_s=0.8)
    assert ev.complete is False
    assert "time budget" in ev.scope and "seeds" in ev.scope and "generate" in ev.scope
    c = by_name(ev)
    assert list(c) == list(CHECKS)
    assert c["header"]["status"] == "ok"
    assert c["determinism"]["status"] == "skipped" and c["agreement"]["status"] == "skipped"
    assert ev.result["total_seconds"] < 3
    assert any("time budget" in n for n in ev.notes)


def test_deadline_is_checked_before_each_role_call_in_the_later_passes():
    # three seeds take about 0.9 s to generate; the deadline falls inside the determinism pass
    ev = lint(FIX / "lint_slow_gen.py", k=3, time_s=1.1)
    c = by_name(ev)
    assert ev.complete is False
    # Holds at any machine speed: generate sleeps at least 0.3 s a call, so the deadline of 1.1 s has always
    # passed by the second determinism check (0.9 s of generate + 0.3 s of the first re-run), and a slower
    # machine only moves the cut earlier, into generate, which also leaves determinism skipped.
    assert c["determinism"]["status"] == "skipped"
    assert "time budget" in c["determinism"]["detail"]
    assert c["agreement"]["status"] == "skipped"
    assert ev.result["total_seconds"] < 2.5


def test_lint_within_its_budget_is_complete():
    ev = lint(FIX / "nt_power_mod.py", k=3, time_s=60)
    assert ev.complete and not ev.notes


def test_the_algo_lint_button_runs_under_the_budget_and_passes_the_time_down():
    from abacus import budget
    ev = budget.call("algo_lint", {"path": str(FIX / "lint_slow_gen.py"), "k": 50}, time_s=3, in_process=True)
    assert ev.complete is False and ev.button == "algo_lint"
    assert "time budget" in ev.scope
    assert ev.budget["stopped"] is False  # lint stopped itself, well before the limit
    assert by_name(ev)["header"]["status"] == "ok"
    ok = budget.call("algo_lint", {"path": str(FIX / "nt_power_mod.py"), "k": 3}, time_s=60, in_process=True)
    assert ok.complete and by_name(ok)["spread"]["status"] == "ok"


def test_a_hung_role_is_killed_at_the_budget_when_linted_through_the_button():
    from abacus import budget
    ev = budget.call("algo_lint", {"path": str(FIX / "lint_hang.py"), "k": 2}, time_s=2)
    assert ev.complete is False and ev.budget["stopped"] is True
    assert ev.budget["time_s"] < 6
