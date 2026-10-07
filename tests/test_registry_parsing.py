import pytest
import sympy as sp

from abacus import registry
from abacus.evidence import Evidence
from abacus.parsing import compile_code, parse_expr


@pytest.fixture
def clean_registry():
    snap = dict(registry._REGISTRY)
    yield
    registry._REGISTRY.clear()
    registry._REGISTRY.update(snap)


def _make(name):
    @registry.button(name, description="d", input_schema={"type": "object"})
    def fn(inp, ctx):
        return Evidence(button=name, result=1, method="exhaustive", scope="s")
    return fn


def test_register_get_all(clean_registry):
    _make("zz_b")
    _make("zz_a")
    b = registry.get("zz_a")
    assert b.name == "zz_a" and b.default_time_s is None and b.uses_seed is False
    names = [x.name for x in registry.all_buttons()]
    assert names == sorted(names) and {"zz_a", "zz_b"} <= set(names)


def test_duplicate_raises(clean_registry):
    _make("zz_dup")
    with pytest.raises(ValueError):
        _make("zz_dup")


def test_get_unknown_lists_names(clean_registry):
    _make("zz_known")
    with pytest.raises(KeyError) as e:
        registry.get("nope")
    assert "zz_known" in str(e.value)


def test_load_all_tolerates_missing_kit():
    registry.load_all()


def test_parse_factorint():
    assert parse_expr("factorint(12)") == {2: 2, 3: 1}


def test_parse_symbols():
    x = sp.Symbol("x")
    assert parse_expr("x**2+1", ["x"]) == x**2 + 1
    assert parse_expr("sqrt(8)") == 2 * sp.sqrt(2)


def test_parse_unknown_name_is_symbol():
    assert parse_expr("y + 1") == sp.Symbol("y") + 1


@pytest.mark.parametrize("s", ["__import__('os')", "x.__class__", "lambda: 1",
                               "exec('1')", "eval('1')", "open('f')", "'import os'"])
def test_parse_rejects(s):
    with pytest.raises(ValueError):
        parse_expr(s)


def test_compile_expr():
    f = compile_code("a*b + math.floor(2.5)", kind="expr", args=["a", "b"])
    assert f(3, 4) == 14


def test_compile_func():
    f = compile_code("def sq(n):\n    return sum(1 for _ in itertools.repeat(0, n))\n",
                     kind="func", name="sq")
    assert f(5) == 5


def test_compile_func_missing_name():
    with pytest.raises(ValueError):
        compile_code("x = 1", kind="func", name="f")
