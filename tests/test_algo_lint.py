from pathlib import Path

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
