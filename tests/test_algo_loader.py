from pathlib import Path

import pytest

from abacus.algo.loader import AlgoImportError, MetaError, algo_hash, load_algo, validate_knobs, validate_meta
from abacus.algo.rng import AbacusRNG

FIX = Path(__file__).parent / "fixtures" / "algos"
GOOD = {"id": "x.y", "title": "T", "summary": "S", "roles": ["compute"], "answer": {"format": "integer"}}


def test_loads_family_and_one_off():
    a = load_algo(FIX / "nt_power_mod.py")
    assert a.meta["id"] == "nt.power-mod" and set(a.meta["knobs"]) == {"a", "b", "m"}
    assert len(a.hash) == 8 and callable(a.module.generate)
    o = load_algo(FIX / "one_off.py")
    assert o.meta["knobs"] == {} and o.meta["tags"] == [] and o.meta["requires"] == []


def test_good_minimal_meta_gets_defaults():
    m = validate_meta(GOOD)
    assert m["knobs"] == {} and m["notes"] == "" and m["techniques"] == []


def test_meta_lists_every_problem():
    bad = {"id": "Bad Id", "title": "", "roles": ["compute", "frobnicate"], "tags": "nt",
           "answer": {"format": "complex", "range": [5, 1]},
           "knobs": {"a": {"int": [9, 2]}, "b": {"float": [0, 1], "pattern_knob": True}, "c": {}},
           "extra": 1}
    with pytest.raises(MetaError) as ei:
        validate_meta(bad)
    text = " | ".join(ei.value.problems)
    for frag in ("summary: missing", "id:", "title:", "frobnicate", "tags:", "answer.format",
                 "answer.range", "knobs.a.int", "knobs.b.pattern_knob", "knobs.c", "unknown keys"):
        assert frag in text, frag
    assert len(ei.value.problems) >= 10


def test_meta_must_be_dict_and_present(tmp_path):
    with pytest.raises(MetaError):
        validate_meta([1])
    p = tmp_path / "nometa.py"
    p.write_text("x = 1\n")
    with pytest.raises(MetaError):
        load_algo(p)


def test_import_error_is_verbatim(tmp_path):
    p = tmp_path / "boom.py"
    p.write_text("raise RuntimeError('kaboom')\n")
    with pytest.raises(AlgoImportError, match="RuntimeError: kaboom"):
        load_algo(p)


def test_hash_stable_across_line_endings(tmp_path):
    src = "META = 1\nx = 2\n\ny = 3\n"
    lf, crlf = tmp_path / "lf.py", tmp_path / "crlf.py"
    lf.write_bytes(src.encode())
    crlf.write_bytes(src.replace("\n", "\r\n").encode())
    assert algo_hash(lf) == algo_hash(crlf)
    assert len(algo_hash(lf)) == 8
    lf.write_bytes((src + "z = 4\n").encode())
    assert algo_hash(lf) != algo_hash(crlf)


def test_validate_knobs():
    m = load_algo(FIX / "nt_power_mod.py").meta
    assert validate_knobs(m, {"a": 5, "b": 3}) == []
    assert len(validate_knobs(m, {"a": 1000, "zz": 1, "b": True})) == 3


def test_rng_reproducible_and_dual():
    def draw(r):
        return ([r.randint(0, 10**9) for _ in range(5)], r.random(), r.choice("abcdef"),
                r.np.integers(0, 10**9, 5).tolist())

    assert draw(AbacusRNG(42)) == draw(AbacusRNG(42))
    l1, l2 = list(range(20)), list(range(20))
    AbacusRNG(7).shuffle(l1)
    AbacusRNG(7).shuffle(l2)
    assert l1 == l2 and l1 != list(range(20))
    assert draw(AbacusRNG(1)) != draw(AbacusRNG(2))
    with pytest.raises(ValueError):
        AbacusRNG(-1)
