import os
import sys
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


def test_import_time_system_exit_is_an_import_error(tmp_path):
    p = tmp_path / "quits.py"
    p.write_text("import sys\nsys.exit(3)\n")
    with pytest.raises(AlgoImportError, match="SystemExit: 3"):
        load_algo(p)
    p.write_text("raise SystemExit\n")
    with pytest.raises(AlgoImportError, match="SystemExit"):
        load_algo(p)


def _meta_src(algo_id: str) -> str:
    return (f'META = {{"id": "{algo_id}", "title": "T", "summary": "S.", "roles": ["compute"],'
            ' "answer": {"format": "integer"}}\n\ndef compute(params):\n    return 1\n')


def test_load_reads_source_not_bytecode_and_writes_none(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", False)  # the environment may have turned it on
    p = tmp_path / "same_size.py"
    p.write_text(_meta_src("x.one"), encoding="utf-8")
    st = p.stat()
    assert load_algo(p).meta["id"] == "x.one"
    new = _meta_src("x.two")
    assert len(new) == len(_meta_src("x.one"))
    p.write_text(new, encoding="utf-8")
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))  # same size, same mtime: stale bytecode would match
    assert p.stat().st_mtime_ns == st.st_mtime_ns
    assert load_algo(p).meta["id"] == "x.two"
    assert not (tmp_path / "__pycache__").exists()
    assert not list(tmp_path.rglob("*.pyc"))


def test_loaded_module_is_usable_and_keeps_file_info(tmp_path):
    p = tmp_path / "dc.py"
    p.write_text(
        "from dataclasses import dataclass\n"
        'META = {"id": "x.dc", "title": "T", "summary": "S.", "roles": ["compute"], "answer": {"format": "integer"}}\n'
        "@dataclass\nclass Box:\n    n: int = 4\n"
        "def compute(params):\n    return Box().n\n", encoding="utf-8")
    a = load_algo(p)
    assert a.module.compute({}) == 4 and Path(a.module.__file__) == p.resolve()


def test_syntax_error_is_an_import_error(tmp_path):
    p = tmp_path / "syn.py"
    p.write_text("def (:\n")
    with pytest.raises(AlgoImportError, match="SyntaxError"):
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
