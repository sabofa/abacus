from abacus import budget, sandbox  # noqa: F401


def test_stdout_before_timeout_survives():
    ev = budget.call("run", {"code": 'print("a"); print("b")\nwhile True: pass'}, time_s=1.5)
    assert ev.complete is False
    assert "a\nb" in ev.result["stdout"]


def test_stdout_survives_exception():
    ev = budget.call("run", {"code": 'print("before"); raise ValueError("x")'}, time_s=30)
    assert ev.result == {"stdout": "before\n", "value": None}
    assert ev.complete is False
    assert any("ValueError: x" in str(f) for f in ev.flags)


def test_heavy_aliases_are_lazy_and_available():
    ns = sandbox.namespace()
    assert "np" not in dict.keys(ns)
    assert sandbox.run_code("np.arange(3).sum()")[1] == 3
    assert sandbox.run_code("def f():\n    return sp.Symbol('x').name\nf()")[1] == "x"
    try:
        sandbox.run_code("nope")
    except NameError:
        pass
    else:
        raise AssertionError("expected NameError")
