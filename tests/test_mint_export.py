"""`abacus mint review` and `mint export`, and the Osmosis adapter (kit/07 s3, s4)."""
import errno
import json
import re
from fractions import Fraction
from pathlib import Path

import pytest
import sympy as sp

from abacus import budget, mcp_server, registry
from abacus.adapters import osmosis
from abacus.adapters.osmosis import render_answer, to_create_questions
from abacus.cli import main
from abacus.library import store
from abacus.mint import batchfile, make as mk
from abacus.mint.batchfile import NoSuchBatch
from abacus.mint.export import export, export_batch
from abacus.mint.make import make
from abacus.mint.review import review, review_batch

FIX = Path(__file__).parent / "fixtures" / "algos"
DAY = "2026-10-07"
BATCH = f"{DAY}-hand-01"
POWER = "nt.power-mod"

MC_ALGO = ('META = {"id": "tmp.mc-sum", "title": "T", "summary": "S.", "roles": ["generate"], '
           '"answer": {"format": "choice"}}\n') + '''
def generate(rng, knobs):
    a, b = rng.randint(1, 50), rng.randint(1, 50)
    s = a + b
    return {"params": {"a": a, "b": b}, "statement": f"Find {a} + {b}.",
            "answer": {"format": "choice", "value": "B"},
            "choices": [{"body": str(s + 1), "correct": False, "note": "off by one"},
                        {"body": str(s), "correct": True},
                        {"body": str(s - 1), "correct": False}]}
'''


@pytest.fixture
def lib(tmp_path, monkeypatch):
    d = tmp_path / "lib"
    monkeypatch.setenv("ABACUS_LIBRARY", str(d))
    monkeypatch.setattr(mk, "_today", lambda: DAY)
    store.write(POWER, (FIX / "nt_power_mod.py").read_text(encoding="utf-8"))
    store.write("tmp.mc-sum", MC_ALGO)
    return d


def inst(index, **kw):
    """One instance row as `make` writes it (decision keep, no choices), with fields overridden by kw."""
    row = {"algo": "tmp.hand", "algo_hash": "abcd1234", "kit": "0.1.0", "seed": 1000 + index,
           "params": {"n": index}, "statement": f"Find {index}.",
           "answer": {"format": "integer", "value": index}, "choices": None, "solution": None,
           "demo": None, "evidence": [], "signals": {}, "index": index, "attempt": index,
           "flags": [], "decision": "keep"}
    row.update(kw)
    return row


def write_batch(lib, rows, batch=BATCH):
    batches = lib / "batches"
    batches.mkdir(parents=True, exist_ok=True)
    summary = {"summary": {"algo": "tmp.hand", "batch": batch, "count": len(rows), "made": len(rows)}}
    path = batches / f"{batch}.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in [summary, *rows]) + "\n", encoding="utf-8")
    return path


def read_batch(path):
    lines = Path(path).read_text(encoding="utf-8").split("\n")
    assert lines[-1] == "", "every line, the last too, ends in a newline"
    rows = [json.loads(line) for line in lines[:-1]]
    assert list(rows[0]) == ["summary"]
    return rows[0]["summary"], rows[1:]


def read_payload(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def litter(lib):
    """Anything in batches/ that is not a batch or an export: a temp file left behind."""
    return [p.name for p in (lib / "batches").iterdir() if not p.name.endswith((".jsonl", ".osmosis.json"))]


def five(lib):
    return write_batch(lib, [inst(i) for i in range(1, 6)])


# ---- render_answer ----------------------------------------------------------

@pytest.mark.parametrize("answer, text", [
    ({"format": "integer", "value": 42}, "42"),
    ({"format": "integer", "value": -7}, "-7"),
    ({"format": "integer", "value": sp.Integer(12)}, "12"),
    ({"format": "rational", "value": "3/4"}, "3/4"),
    ({"format": "rational", "value": Fraction(3, 4)}, "3/4"),
    ({"format": "rational", "value": 5}, "5"),
    ({"format": "rational", "value": Fraction(2, 1)}, "2"),
    ({"format": "rational", "value": "2/1"}, "2"),          # a Fraction(2, 1) in a batch file is the text "2/1"
    ({"format": "rational", "value": "-6/1"}, "-6"),
    ({"format": "rational", "value": "0/1"}, "0"),
    ({"format": "rational", "value": "21/10"}, "21/10"),    # only a denominator of 1 goes
    ({"format": "rational", "value": "1/12"}, "1/12"),
    ({"format": "expression", "value": "2/1"}, "2/1"),      # as written: it is not a rational
    ({"format": "text", "value": "2/1"}, "2/1"),
    ({"format": "expression", "value": "x**2 + 1"}, "x**2 + 1"),
    ({"format": "expression", "value": sp.Symbol("x") ** 2 + 1}, "x**2 + 1"),
    ({"format": "tuple", "value": [1, 2]}, "(1, 2)"),
    ({"format": "tuple", "value": (1, "3/4", "x + 1")}, "(1, 3/4, x + 1)"),
    ({"format": "tuple", "value": [[1, 2], 3]}, "((1, 2), 3)"),
    ({"format": "tuple", "value": []}, "()"),
    ({"format": "set", "value": [1, 2, 3]}, "{1, 2, 3}"),
    ({"format": "set", "value": {3, 1, 2}}, "{1, 2, 3}"),
    ({"format": "set", "value": frozenset({"b", "a"})}, "{a, b}"),
    ({"format": "set", "value": []}, "{}"),
    ({"format": "choice", "value": "C"}, "C"),
    ({"format": "text", "value": "x squared"}, "x squared"),
    ({"format": "text", "value": "(a, b) and {c}"}, "(a, b) and {c}"),
])
def test_render_answer(answer, text):
    assert render_answer(answer) == text


@pytest.mark.parametrize("answer", [
    None, 5, "42", {"value": 1}, {"format": "integer"},
    {"format": "integer", "value": None}, {"format": "matrix", "value": [[1]]},
])
def test_render_answer_rejects_what_is_not_an_answer(answer):
    with pytest.raises(ValueError):
        render_answer(answer)


def test_render_answer_handles_every_answer_format():
    from abacus.algo.loader import ANSWER_FORMATS
    shown = {"integer": 1, "rational": "1/2", "expression": "x", "choice": "A", "tuple": [1], "set": [1], "text": "t"}
    assert set(shown) == set(ANSWER_FORMATS)
    for fmt, value in shown.items():
        assert isinstance(render_answer({"format": fmt, "value": value}), str)


# ---- the adapter ------------------------------------------------------------

MC_CHOICES = [{"body": "12", "correct": True},
              {"body": "14", "correct": False, "note": "added instead of multiplied"},
              {"body": "16", "correct": False, "note": None},
              {"body": "18", "correct": False, "note": ""}]


def test_mc_instance_maps_to_an_mc_item():
    row = inst(1, choices=MC_CHOICES, statement="What is $3 \\cdot 4$?", answer={"format": "choice", "value": "A"})
    payload, problems = to_create_questions([row], tags=["arith"], batch_id=BATCH)
    assert problems == []
    assert payload["idempotency_key"] == BATCH
    (item,) = payload["questions"]
    assert item == {
        "type": "mc", "prompt": "What is $3 \\cdot 4$?",
        "choices": [{"body": "12", "is_correct": True},
                    {"body": "14", "is_correct": False, "misconception": "added instead of multiplied"},
                    {"body": "16", "is_correct": False},
                    {"body": "18", "is_correct": False}],
        "tags": ["arith"], "source_note": "abacus tmp.hand@abcd1234 seed 1001",
    }
    assert not {"model_answer", "explanation", "difficulty", "provenance", "node_keys", "family_id"} & set(item)


def test_written_instance_maps_to_a_written_item_with_the_answer_as_text():
    rows = [inst(1, answer={"format": "integer", "value": 7}),
            inst(2, answer={"format": "tuple", "value": [1, 2]}, statement="Find the pair."),
            inst(3, answer={"format": "set", "value": [1, 2, 3]}),
            inst(4, answer={"format": "rational", "value": "3/4"}),
            inst(5, answer={"format": "expression", "value": "x**2 + 1"}),
            inst(6, answer={"format": "text", "value": "a circle"})]
    payload, problems = to_create_questions(rows, tags=["t"], batch_id=BATCH)
    assert problems == []
    items = payload["questions"]
    assert [i["type"] for i in items] == ["written"] * 6
    assert [i["model_answer"] for i in items] == ["7", "(1, 2)", "{1, 2, 3}", "3/4", "x**2 + 1", "a circle"]
    assert items[1]["prompt"] == "Find the pair."
    assert all("choices" not in i and "explanation" not in i for i in items)


def test_source_note_names_the_algorithm_its_hash_and_the_instances_seed():
    payload, _ = to_create_questions([inst(3, algo="nt.power-mod", algo_hash="0123abcd", seed=77)],
                                     tags=["t"], batch_id=BATCH)
    assert payload["questions"][0]["source_note"] == "abacus nt.power-mod@0123abcd seed 77"


def test_source_note_leaves_out_what_the_instance_does_not_say():
    payload, _ = to_create_questions([inst(1, algo_hash=None, seed=None)], tags=["t"], batch_id=BATCH)
    assert payload["questions"][0]["source_note"] == "abacus tmp.hand"


def test_tags_node_keys_and_family_go_on_every_item():
    payload, problems = to_create_questions([inst(1), inst(2)], tags=["a", "b"], node_keys=["node:x", "node:y"],
                                            family_id="fam-1", batch_id=BATCH)
    assert problems == []
    for item in payload["questions"]:
        assert item["tags"] == ["a", "b"] and item["node_keys"] == ["node:x", "node:y"]
        assert item["family_id"] == "fam-1"
    assert payload["questions"][0]["tags"] is not payload["questions"][1]["tags"]


def test_node_keys_and_family_are_left_out_when_not_given():
    for kw in ({}, {"node_keys": None}, {"node_keys": []}, {"family_id": None}):
        (item,) = to_create_questions([inst(1)], tags=["t"], batch_id=BATCH, **kw)[0]["questions"]
        assert "node_keys" not in item and "family_id" not in item


def test_a_string_for_tags_is_one_tag_not_its_letters():
    payload, problems = to_create_questions([inst(1)], tags="algebra", batch_id=BATCH)
    assert payload["questions"][0]["tags"] == ["algebra"] and problems == []


def codes_of(problems):
    return [osmosis.split_problem(p)[0] for p in problems]


@pytest.mark.parametrize("choices, code", [
    ([{"body": "1", "correct": False}, {"body": "2", "correct": False}], "mc_choices"),                     # none correct
    ([{"body": "1", "correct": True}, {"body": "2", "correct": True}, {"body": "3", "correct": False}], "mc_choices"),
    ([{"body": "1", "correct": True}], "mc_choices"),                                                       # one choice
])
def test_an_mc_item_needs_two_choices_and_exactly_one_correct(choices, code):
    payload, problems = to_create_questions([inst(5, choices=choices)], tags=["t"], batch_id=BATCH)
    assert codes_of(problems) == [code]
    assert "instance 5" in problems[0]
    assert payload["questions"][0]["type"] == "mc"          # the item is still in the payload
    assert len(payload["questions"][0]["choices"]) == len(choices)


def test_an_empty_choices_list_is_no_choices_so_the_item_is_written():
    payload, problems = to_create_questions([inst(5, choices=[])], tags=["t"], batch_id=BATCH)
    q = payload["questions"][0]
    assert problems == [] and q["type"] == "written" and "choices" not in q and q["model_answer"] == "5"


def test_the_zero_correct_message_says_so():
    _, problems = to_create_questions(
        [inst(5, choices=[{"body": "1", "correct": False}, {"body": "2", "correct": False}])],
        tags=["t"], batch_id=BATCH)
    assert "0 correct" in problems[0]


def test_a_choice_without_a_body_or_a_true_or_false_correct_is_flagged():
    _, problems = to_create_questions(
        [inst(2, choices=[{"body": "", "correct": True}, {"body": "x"}, {"body": "y", "correct": "no"}, "z"])],
        tags=["t"], batch_id=BATCH)
    assert "bad_choice" in codes_of(problems)
    assert len([p for p in problems if p.startswith("bad_choice")]) == 4


def test_a_written_item_needs_a_model_answer():
    for answer in (None, {"format": "text", "value": ""}, {"format": "text", "value": "  "},
                   {"format": "integer", "value": None}, {"format": "matrix", "value": 1}):
        payload, problems = to_create_questions([inst(4, answer=answer)], tags=["t"], batch_id=BATCH)
        assert codes_of(problems) == ["bad_answer"], answer
        assert "instance 4" in problems[0]
        assert "model_answer" not in payload["questions"][0] or not payload["questions"][0]["model_answer"].strip()


@pytest.mark.parametrize("tags", [[], None, [""], ["ok", ""], ["  "], ["ok", 5]])
def test_missing_or_empty_tags_are_flagged_and_passed_through(tags):
    payload, problems = to_create_questions([inst(1), inst(2)], tags=tags, batch_id=BATCH)
    assert codes_of(problems) == ["bad_tags"]               # once, not once per item
    assert len(payload["questions"]) == 2
    assert payload["questions"][0]["tags"] == ([] if tags is None else tags)


@pytest.mark.parametrize("keys, bad", [(["node:ok", "algebra"], ["algebra"]), (["Node:x", "node-y", ""], ["Node:x", "node-y", ""]),
                                        ([5], [5])])
def test_node_keys_must_start_with_node_colon(keys, bad):
    payload, problems = to_create_questions([inst(1)], tags=["t"], node_keys=keys, batch_id=BATCH)
    assert codes_of(problems) == ["bad_node_key"] * len(bad)
    for key, problem in zip(bad, problems):
        assert repr(key) in problem
    assert payload["questions"][0]["node_keys"] == keys


def test_an_instance_without_a_statement_is_flagged():
    _, problems = to_create_questions([inst(1, statement=""), inst(2, statement=None)], tags=["t"], batch_id=BATCH)
    assert codes_of(problems) == ["bad_prompt", "bad_prompt"]


def test_no_instances_is_flagged_and_gives_an_empty_payload():
    payload, problems = to_create_questions([], tags=["t"], batch_id=BATCH)
    assert payload == {"questions": [], "idempotency_key": BATCH}
    assert codes_of(problems) == ["no_questions"]


def test_a_clean_batch_has_no_problems():
    rows = [inst(1), inst(2, choices=MC_CHOICES, answer={"format": "choice", "value": "A"})]
    _, problems = to_create_questions(rows, tags=["t"], node_keys=["node:n"], family_id="f", batch_id=BATCH)
    assert problems == []


# ---- review -----------------------------------------------------------------

def test_review_drops_and_notes_and_the_file_stays_valid(lib):
    path = five(lib)
    before_summary, before = read_batch(path)
    out = review(BATCH, drop=[2, 4], notes={3: "too easy", 4: "ambiguous"})
    assert out == path
    summary, rows = read_batch(path)
    assert summary == before_summary
    assert [r["index"] for r in rows] == [1, 2, 3, 4, 5]
    assert [r["decision"] for r in rows] == ["keep", "drop", "keep", "drop", "keep"]
    assert [r.get("note") for r in rows] == [None, None, "too easy", "ambiguous", None]
    for a, b in zip(before, rows):                      # nothing else changed
        assert {k: v for k, v in b.items() if k != "note"} == {**a, "decision": b["decision"]}
    assert litter(lib) == []


def test_review_keep_undoes_a_drop(lib):
    five(lib)
    review(BATCH, drop=[1, 2, 3])
    review(BATCH, keep=[2])
    _, rows = read_batch(lib / "batches" / f"{BATCH}.jsonl")
    assert [r["decision"] for r in rows] == ["drop", "keep", "drop", "keep", "keep"]


def test_review_an_empty_note_removes_the_note_and_keep_leaves_it(lib):
    five(lib)
    review(BATCH, notes={1: "hmm", 2: "ok"})
    review(BATCH, keep=[1], notes={2: ""})
    _, rows = read_batch(lib / "batches" / f"{BATCH}.jsonl")
    assert rows[0]["note"] == "hmm" and "note" not in rows[1]


def test_review_adds_a_decision_where_the_row_has_none(lib):
    row = inst(1)
    del row["decision"]
    path = write_batch(lib, [row, inst(2)])
    review(BATCH, notes={1: "n"})
    _, rows = read_batch(path)
    assert rows[0]["decision"] == "keep" and rows[0]["note"] == "n"


def test_review_by_path_and_by_the_file_name(lib):
    path = five(lib)
    review(str(path), drop=[1])
    review(path, drop=[2])
    review(f"{BATCH}.jsonl", drop=[3])
    _, rows = read_batch(path)
    assert [r["decision"] for r in rows] == ["drop", "drop", "drop", "keep", "keep"]


def test_review_a_batch_outside_the_library(lib, tmp_path):
    path = tmp_path / "elsewhere" / "mine.jsonl"
    path.parent.mkdir()
    path.write_text(write_batch(lib, [inst(1), inst(2)]).read_text(encoding="utf-8"), encoding="utf-8")
    review(str(path), drop=[2])
    assert [r["decision"] for r in read_batch(path)[1]] == ["keep", "drop"]
    assert [r["decision"] for r in read_batch(lib / "batches" / f"{BATCH}.jsonl")[1]] == ["keep", "keep"]


def test_review_unknown_index_raises_and_changes_nothing(lib):
    path = five(lib)
    before = path.read_bytes()
    for kw in ({"drop": [9]}, {"keep": [0]}, {"notes": {7: "x"}}, {"drop": [1], "keep": [6]}):
        with pytest.raises(ValueError, match="no instance"):
            review(BATCH, **kw)
    assert path.read_bytes() == before and litter(lib) == []


def test_review_an_index_both_dropped_and_kept_is_a_conflict(lib):
    path = five(lib)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="both"):
        review(BATCH, drop=[2], keep=[2])
    assert path.read_bytes() == before


@pytest.mark.parametrize("kw", [{"drop": ["2"]}, {"drop": [True]}, {"keep": [1.5]}, {"drop": "1,2"},
                                {"notes": {"1": "x"}}, {"notes": {1: 5}}, {"notes": {True: "x"}}])
def test_review_bad_arguments_raise_value_error(lib, kw):
    path = five(lib)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        review(BATCH, **kw)
    assert path.read_bytes() == before


def test_review_missing_batch_raises_no_such_batch(lib):
    with pytest.raises(NoSuchBatch):
        review("2026-10-07-nope-01", drop=[1])
    with pytest.raises(FileNotFoundError):
        review(str(lib / "batches" / "nope.jsonl"), drop=[1])
    with pytest.raises(FileNotFoundError):                     # a separator makes it a path, not an id
        review("../escape", drop=[1])
    for bad_id in ("", "a b", "x!", ".hidden", "-x"):
        with pytest.raises(ValueError, match="batch id"):
            review(bad_id, drop=[1])


def test_review_a_file_that_is_not_a_batch_raises_value_error(lib):
    (lib / "batches").mkdir(parents=True)
    bad = lib / "batches" / "bad.jsonl"
    for text in ("not json\n", '{"summary": {}}\n[1]\n', '{"summary": {}}\n{"index": 1}\n{"index": 1}\n',
                 '{"summary": {}}\n{"statement": "no index"}\n'):
        bad.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError):
            review("bad", drop=[1])
        assert bad.read_text(encoding="utf-8") == text


def test_review_is_atomic_a_failed_replace_leaves_the_batch_as_it_was(lib, monkeypatch):
    path = five(lib)
    before = path.read_bytes()

    def boom(src, dst):
        raise OSError("disk full")

    with monkeypatch.context() as m:
        m.setattr(batchfile.os, "replace", boom)
        with pytest.raises(OSError, match="disk full"):
            review(BATCH, drop=[1])
    assert path.read_bytes() == before and litter(lib) == []


def test_review_keeps_non_ascii_text_and_a_crlf_batch_file(lib):
    path = five(lib)
    text = path.read_text(encoding="utf-8").replace('"Find 2."', json.dumps("Trouvez é  2.", ensure_ascii=False))
    path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    review(BATCH, drop=[1])
    summary, rows = read_batch(path)
    assert rows[1]["statement"] == "Trouvez é  2." and rows[0]["decision"] == "drop"


def test_review_nothing_to_record_still_validates_the_batch_and_leaves_it_alone(lib):
    path = five(lib)
    before = path.read_bytes()
    assert review(BATCH) == path and path.read_bytes() == before
    with pytest.raises(NoSuchBatch):
        review("2026-10-07-nope-01")


def test_review_batch_reports_the_counts(lib):
    five(lib)
    path, info = review_batch(BATCH, drop=[2, 4], notes={1: "x"})
    assert info == {"batch": BATCH, "path": str(path), "instances": 5, "kept": 3, "dropped": 2,
                    "dropped_indexes": [2, 4], "changed": [1, 2, 4]}


# ---- export -----------------------------------------------------------------

def test_export_writes_the_payload_next_to_the_batch(lib):
    five(lib)
    out = export(BATCH, tags=["t1", "t2"])
    assert out == lib / "batches" / f"{BATCH}.osmosis.json"
    payload = read_payload(out)
    assert list(payload) == ["questions", "idempotency_key"]
    assert payload["idempotency_key"] == BATCH
    assert len(payload["questions"]) == 5
    assert litter(lib) == []


def test_export_has_only_the_kept_instances_in_index_order(lib):
    rows = [inst(i) for i in (3, 1, 5, 2, 4)]                 # not in index order in the file
    rows[1]["decision"] = "drop"                              # index 1
    del rows[4]["decision"]                                   # index 4: no decision is keep
    write_batch(lib, rows)
    review(BATCH, drop=[5])
    questions = read_payload(export(BATCH, tags=["t"]))["questions"]
    assert [q["prompt"] for q in questions] == ["Find 2.", "Find 3.", "Find 4."]


def test_export_after_review_drops_what_was_dropped(lib):
    five(lib)
    review(BATCH, drop=[2, 4])
    questions = read_payload(export(BATCH, tags=["t"]))["questions"]
    assert [q["prompt"] for q in questions] == ["Find 1.", "Find 3.", "Find 5."]


def test_export_mc_and_written_in_one_batch(lib):
    mc = inst(2, choices=MC_CHOICES, answer={"format": "choice", "value": "A"}, statement="Pick.")
    write_batch(lib, [inst(1, answer={"format": "tuple", "value": [3, 4]}), mc])
    q = read_payload(export(BATCH, tags=["t"]))["questions"]
    assert [i["type"] for i in q] == ["written", "mc"]
    assert q[0]["model_answer"] == "(3, 4)" and "choices" not in q[0]
    assert q[1]["choices"][1] == {"body": "14", "is_correct": False, "misconception": "added instead of multiplied"}
    assert "misconception" not in q[1]["choices"][0] and "model_answer" not in q[1]


def test_export_source_note_and_idempotency_key(lib):
    write_batch(lib, [inst(1, algo="nt.power-mod", algo_hash="deadbeef", seed=4242)])
    payload = read_payload(export(BATCH, tags=["t"]))
    assert payload["questions"][0]["source_note"] == "abacus nt.power-mod@deadbeef seed 4242"
    assert payload["idempotency_key"] == BATCH


def test_export_family_adds_family_id_to_every_item(lib):
    five(lib)
    q = read_payload(export(BATCH, tags=["t"], family_id="fam-7", node_keys=["node:a"]))["questions"]
    assert {i["family_id"] for i in q} == {"fam-7"} and len(q) == 5
    assert {tuple(i["node_keys"]) for i in q} == {("node:a",)}
    q = read_payload(export(BATCH, tags=["t"]))["questions"]
    assert all("family_id" not in i and "node_keys" not in i for i in q)


def test_export_is_repeatable_and_overwrites_its_own_file(lib):
    five(lib)
    first = export(BATCH, tags=["t"]).read_bytes()
    assert export(BATCH, tags=["t"]).read_bytes() == first
    review(BATCH, drop=[1])
    assert len(read_payload(export(BATCH, tags=["t"]))["questions"]) == 4
    assert litter(lib) == []


def test_export_by_path_writes_beside_the_batch_file(lib, tmp_path):
    path = tmp_path / "elsewhere" / f"{BATCH}.jsonl"
    path.parent.mkdir()
    path.write_text(write_batch(lib, [inst(1)]).read_text(encoding="utf-8"), encoding="utf-8")
    out = export(str(path), tags=["t"])
    assert out == path.parent / f"{BATCH}.osmosis.json" and read_payload(out)["idempotency_key"] == BATCH


def test_export_takes_the_batch_id_from_the_summary_else_from_the_file_name(lib):
    path = five(lib)
    no_head = lib / "batches" / "loose.jsonl"
    no_head.write_text("\n".join(path.read_text(encoding="utf-8").split("\n")[1:]), encoding="utf-8")
    out = export("loose", tags=["t"])
    assert out.name == "loose.osmosis.json" and read_payload(out)["idempotency_key"] == "loose"
    odd = lib / "batches" / "odd.jsonl"                       # a summary id that is not a file name
    odd.write_text(path.read_text(encoding="utf-8").replace(BATCH, "../x/y"), encoding="utf-8")
    out = export("odd", tags=["t"])
    assert out.name == "odd.osmosis.json" and read_payload(out)["idempotency_key"] == "odd"


def test_export_still_writes_the_payload_when_there_are_problems(lib):
    bad = inst(2, choices=[{"body": "1", "correct": False}, {"body": "2", "correct": False}])
    write_batch(lib, [inst(1), bad])
    path, info = export_batch(BATCH, tags=["good", ""], node_keys=["algebra"])
    assert path.is_file() and len(read_payload(path)["questions"]) == 2
    assert sorted(p["code"] for p in info["problems"]) == ["bad_node_key", "bad_tags", "mc_choices"]
    assert all(p["message"] for p in info["problems"])


def test_export_flags_an_empty_export(lib):
    five(lib)
    review(BATCH, drop=[1, 2, 3, 4, 5])
    path, info = export_batch(BATCH, tags=["t"])
    assert read_payload(path) == {"questions": [], "idempotency_key": BATCH}
    assert [p["code"] for p in info["problems"]] == ["no_questions"]


def test_export_leaves_out_and_flags_a_decision_that_is_neither_keep_nor_drop(lib):
    write_batch(lib, [inst(1), inst(2, decision="dropped"), inst(3, decision="drop")])
    path, info = export_batch(BATCH, tags=["t"])
    assert [q["prompt"] for q in read_payload(path)["questions"]] == ["Find 1."]
    assert [p["code"] for p in info["problems"]] == ["bad_decision"] and "instance 2" in info["problems"][0]["message"]
    assert (info["questions"], info["dropped"]) == (1, 1)


def test_export_batch_info(lib):
    five(lib)
    review(BATCH, drop=[5])
    path, info = export_batch(BATCH, tags=["t"], family_id="f")
    assert info == {"batch": BATCH, "path": str(path), "to": "osmosis", "questions": 4, "dropped": 1, "problems": []}


def test_export_only_knows_osmosis(lib):
    five(lib)
    with pytest.raises(ValueError, match="osmosis"):
        export(BATCH, to="moodle", tags=["t"])
    assert not (lib / "batches" / f"{BATCH}.moodle.json").exists() and litter(lib) == []


def test_export_missing_batch_raises_no_such_batch(lib):
    with pytest.raises(NoSuchBatch):
        export("2026-10-07-nope-01", tags=["t"])


def test_export_is_atomic(lib, monkeypatch):
    five(lib)
    out = export(BATCH, tags=["t"])
    before = out.read_bytes()
    review(BATCH, drop=[1])

    def boom(src, dst):
        raise OSError("disk full")

    with monkeypatch.context() as m:
        m.setattr(batchfile.os, "replace", boom)
        with pytest.raises(OSError):
            export(BATCH, tags=["t"])
    assert out.read_bytes() == before and litter(lib) == []


def test_make_review_export_end_to_end(lib):
    path = make(POWER, count=6, seed=3)
    assert path.name == f"{DAY}-power-mod-01.jsonl"
    review(path.stem, drop=[2], notes={3: "check this one"})
    out, info = export_batch(path.stem, tags=["number-theory"], node_keys=["node:modular-arithmetic"], family_id="pm")
    assert info["problems"] == [] and info["questions"] == 5 and info["dropped"] == 1
    payload = read_payload(out)
    assert out.name == f"{DAY}-power-mod-01.osmosis.json" and payload["idempotency_key"] == path.stem
    _, rows = read_batch(path)
    kept = [r for r in rows if r["decision"] == "keep"]
    assert [q["prompt"] for q in payload["questions"]] == [r["statement"] for r in kept]
    for q, r in zip(payload["questions"], kept):
        assert q["type"] == "written" and q["model_answer"] == str(r["answer"]["value"])
        assert q["source_note"] == f"abacus {r['algo']}@{r['algo_hash']} seed {r['seed']}"
        assert q["family_id"] == "pm" and q["tags"] == ["number-theory"]
    assert rows[2]["note"] == "check this one"


def test_make_review_export_end_to_end_with_choices(lib):
    path = make("tmp.mc-sum", count=3, seed=5)
    out, info = export_batch(path.stem, tags=["t"])
    assert info["problems"] == []
    for q in read_payload(out)["questions"]:
        assert q["type"] == "mc" and "model_answer" not in q
        assert [c["is_correct"] for c in q["choices"]] == [False, True, False]
        assert q["choices"][0]["misconception"] == "off by one" and "misconception" not in q["choices"][1]


# ---- the buttons ------------------------------------------------------------

def call(name, inp, **kw):
    return budget.call(name, inp, in_process=True, **kw)


def codes(ev):
    return [f["code"] for f in ev.flags]


def test_the_buttons_are_registered_and_listed_as_mcp_tools():
    registry.load_all()
    for name in ("mint_review", "mint_export"):
        assert registry.get(name).default_time_s
        assert name in {t.name for t in mcp_server.list_tools()}


def test_mint_review_button(lib):
    path = five(lib)
    ev = call("mint_review", {"batch": BATCH, "drop": [2, 3], "keep": [3 + 1], "notes": {"1": "too easy"}})
    assert ev.button == "mint_review" and ev.method == "timed" and ev.complete and ev.flags == []
    assert ev.result == {"batch": BATCH, "path": str(path), "instances": 5, "kept": 3, "dropped": 2,
                         "dropped_indexes": [2, 3], "changed": [1, 2, 3, 4]}
    assert re.fullmatch(r".*4 of 5.*2 dropped.*", ev.scope), ev.scope
    _, rows = read_batch(path)
    assert [r["decision"] for r in rows] == ["keep", "drop", "drop", "keep", "keep"] and rows[0]["note"] == "too easy"


@pytest.mark.parametrize("inp, code", [
    ({"batch": "2026-10-07-nope-01", "drop": [1]}, "no_such_batch"),
    ({"batch": BATCH, "drop": [99]}, "bad_input"),
    ({"batch": BATCH, "drop": [1], "keep": [1]}, "bad_input"),
    ({"batch": BATCH, "notes": {"one": "x"}}, "bad_input"),
    ({"batch": "not an id!", "drop": [1]}, "bad_input"),
    ({"batch": "bad", "drop": [1]}, "bad_batch"),
    ({"batch": BATCH, "drop": ["1"]}, "bad_input"),
    ({"drop": [1]}, "bad_input"),
])
def test_mint_review_failures_are_flagged_evidence_and_change_nothing(lib, inp, code):
    path = five(lib)
    (lib / "batches" / "bad.jsonl").write_text("not json\n", encoding="utf-8")
    before = path.read_bytes()
    ev = call("mint_review", inp)
    assert ev.result is None and not ev.complete and codes(ev) == [code], ev.to_dict()
    assert path.read_bytes() == before


def test_mint_export_button(lib):
    five(lib)
    review(BATCH, drop=[1])
    ev = call("mint_export", {"batch": BATCH, "tags": ["t1", "t2"], "node_keys": ["node:a"], "family_id": "F"})
    out = lib / "batches" / f"{BATCH}.osmosis.json"
    assert ev.button == "mint_export" and ev.method == "timed" and ev.complete and ev.flags == []
    assert ev.result == {"batch": BATCH, "path": str(out), "to": "osmosis", "questions": 4, "dropped": 1}
    assert "4" in ev.scope
    q = read_payload(out)["questions"]
    assert len(q) == 4 and all(i["tags"] == ["t1", "t2"] and i["family_id"] == "F" for i in q)


def test_mint_export_button_reports_problems_as_flags_and_still_writes(lib):
    write_batch(lib, [inst(1, choices=[{"body": "a", "correct": False}, {"body": "b", "correct": False}])])
    ev = call("mint_export", {"batch": BATCH, "tags": [""], "node_keys": ["nope"]})
    assert ev.complete and ev.result["questions"] == 1
    assert sorted(codes(ev)) == ["bad_node_key", "bad_tags", "mc_choices"]
    assert all(f["message"] for f in ev.flags)
    assert (lib / "batches" / f"{BATCH}.osmosis.json").is_file()


def test_mint_export_button_with_no_tags_at_all_is_flagged_not_refused(lib):
    five(lib)
    ev = call("mint_export", {"batch": BATCH, "tags": []})
    assert codes(ev) == ["bad_tags"] and ev.result["questions"] == 5


@pytest.mark.parametrize("inp, code", [
    ({"batch": "2026-10-07-nope-01", "tags": ["t"]}, "no_such_batch"),
    ({"batch": "bad", "tags": ["t"]}, "bad_batch"),
    ({"batch": BATCH, "tags": ["t"], "to": "moodle"}, "bad_input"),
    ({"batch": BATCH}, "bad_input"),                       # tags are required
    ({"batch": BATCH, "tags": "t1,t2"}, "bad_input"),
    ({"tags": ["t"]}, "bad_input"),
])
def test_mint_export_failures_are_flagged_evidence_and_write_nothing(lib, inp, code):
    five(lib)
    (lib / "batches" / "bad.jsonl").write_text("not json\n", encoding="utf-8")
    ev = call("mint_export", inp)
    assert ev.result is None and not ev.complete and codes(ev) == [code], ev.to_dict()
    assert litter(lib) == []
    assert not list((lib / "batches").glob("*.osmosis.json"))


def test_buttons_in_a_child_process(lib):
    five(lib)
    ev = budget.call("mint_review", {"batch": BATCH, "drop": [5]}, time_s=120)
    assert ev.complete and ev.flags == [] and ev.result["dropped"] == 1, ev.to_dict()
    ev = budget.call("mint_export", {"batch": BATCH, "tags": ["t"]}, time_s=120)
    assert ev.complete and ev.flags == [] and ev.result["questions"] == 4, ev.to_dict()
    assert ev.budget["stopped"] is False


# ---- the CLI ----------------------------------------------------------------

@pytest.fixture
def fast(monkeypatch):
    """Run buttons in process, so a CLI test does not pay for a child process."""
    real = budget.call

    def in_process(name, inp, **kw):
        kw.setdefault("in_process", True)
        return real(name, inp, **kw)

    monkeypatch.setattr(budget, "call", in_process)


def cli(capsys, *argv):
    capsys.readouterr()
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_cli_mint_review(lib, capsys, fast):
    path = five(lib)
    code, out, err = cli(capsys, "mint", "review", BATCH, "--drop", "2,4", "--keep", "5",
                         "--note", "1", "too easy", "--note", "3", "check the wording")
    assert code == 0, err
    ev = json.loads(out)
    assert ev["button"] == "mint_review" and ev["result"]["dropped"] == 2 and ev["result"]["changed"] == [1, 2, 3, 4, 5]
    _, rows = read_batch(path)
    assert [r["decision"] for r in rows] == ["keep", "drop", "keep", "drop", "keep"]
    assert [r.get("note") for r in rows] == ["too easy", None, "check the wording", None, None]


def test_cli_mint_review_options_repeat_and_accept_a_path_and_the_common_flags(lib, capsys, fast):
    path = five(lib)
    code, out, err = cli(capsys, "mint", "review", str(path), "--drop", "1", "--drop", "2,3", "--pretty")
    assert code == 0, err
    assert out.startswith("{\n") and json.loads(out)["result"]["dropped_indexes"] == [1, 2, 3]


def test_cli_mint_review_with_nothing_to_record_is_fine(lib, capsys, fast):
    five(lib)
    code, out, err = cli(capsys, "mint", "review", BATCH)
    assert code == 0, err
    assert json.loads(out)["result"]["changed"] == []


@pytest.mark.parametrize("argv", [["--drop", "x"], ["--drop", "1,,2"], ["--keep", "1.5"], ["--note", "one", "text"],
                                  ["--note", "1"]])
def test_cli_mint_review_bad_arguments_exit_2(lib, capsys, fast, argv):
    five(lib)
    code, out, err = cli(capsys, "mint", "review", BATCH, *argv)
    assert code == 2 and out == ""
    assert err


def test_cli_mint_review_failures_print_the_evidence_and_exit_2(lib, capsys, fast):
    five(lib)
    code, out, err = cli(capsys, "mint", "review", BATCH, "--drop", "99")
    assert code == 2
    ev = json.loads(out)
    assert ev["result"] is None and ev["flags"][0]["code"] == "bad_input" and "99" in ev["flags"][0]["message"]
    code, out, _ = cli(capsys, "mint", "review", "2026-10-07-nope-01", "--drop", "1")
    assert code == 2 and json.loads(out)["flags"][0]["code"] == "no_such_batch"


def test_cli_mint_export(lib, capsys, fast):
    five(lib)
    review(BATCH, drop=[3])
    code, out, err = cli(capsys, "mint", "export", BATCH, "--to", "osmosis", "--tags", "t1,t2",
                         "--node-key", "node:a", "--node-key", "node:b", "--family", "F")
    assert code == 0, err
    ev = json.loads(out)
    assert ev["button"] == "mint_export" and ev["flags"] == [] and ev["result"]["questions"] == 4
    payload = read_payload(ev["result"]["path"])
    assert payload["idempotency_key"] == BATCH and len(payload["questions"]) == 4
    for q in payload["questions"]:
        assert q["tags"] == ["t1", "t2"] and q["node_keys"] == ["node:a", "node:b"] and q["family_id"] == "F"


def test_cli_mint_export_to_defaults_to_osmosis_and_tags_are_trimmed(lib, capsys, fast):
    five(lib)
    code, out, err = cli(capsys, "mint", "export", BATCH, "--tags", " a , b ", "--pretty")
    assert code == 0, err
    assert read_payload(json.loads(out)["result"]["path"])["questions"][0]["tags"] == ["a", "b"]


def test_cli_mint_export_flags_problems_and_still_exits_0(lib, capsys, fast):
    five(lib)
    code, out, err = cli(capsys, "mint", "export", BATCH, "--tags", "a,,b", "--node-key", "plain")
    assert code == 0, err
    ev = json.loads(out)
    assert sorted(f["code"] for f in ev["flags"]) == ["bad_node_key", "bad_tags"]
    assert Path(ev["result"]["path"]).is_file()


def test_cli_mint_export_needs_tags_and_a_known_target(lib, capsys, fast):
    five(lib)
    assert cli(capsys, "mint", "export", BATCH)[0] == 2
    assert cli(capsys, "mint", "export", BATCH, "--tags", "t", "--to", "moodle")[0] == 2
    assert cli(capsys, "mint", "export", "--tags", "t")[0] == 2
    assert not list((lib / "batches").glob("*.osmosis.json"))


def test_cli_mint_export_failure_prints_the_evidence_and_exits_2(lib, capsys, fast):
    five(lib)
    code, out, _ = cli(capsys, "mint", "export", "2026-10-07-nope-01", "--tags", "t")
    assert code == 2 and json.loads(out)["flags"][0]["code"] == "no_such_batch"


def test_cli_review_and_export_in_a_child_process(lib, capsys):
    five(lib)
    code, out, err = cli(capsys, "mint", "review", BATCH, "--drop", "1", "--time", "120")
    assert code == 0, err
    ev = json.loads(out)
    assert ev["complete"] and ev["budget"]["limit_s"] == 120 and ev["result"]["dropped"] == 1
    code, out, err = cli(capsys, "mint", "export", BATCH, "--tags", "t", "--time", "120")
    assert code == 0, err
    assert json.loads(out)["result"]["questions"] == 4


# --- the exclusive write where hard links are not available (FAT, network drives) ---

def _no_links(monkeypatch):
    """os.link fails as on a file system without hard links; os.replace overwrites, so it must stay unused."""
    def nolink(src, dst, **kw):
        raise OSError(errno.EPERM, "hard links are not supported")

    def nope(src, dst):
        raise AssertionError("the link fallback must not use os.replace: it overwrites")

    monkeypatch.setattr(batchfile.os, "link", nolink)
    monkeypatch.setattr(batchfile.os, "replace", nope)


def test_exclusive_write_without_hard_links_publishes_a_new_file(tmp_path, monkeypatch):
    _no_links(monkeypatch)
    target = tmp_path / "b.jsonl"
    batchfile.write_atomic(target, b"new\n", exclusive=True)
    assert target.read_bytes() == b"new\n"
    assert [p.name for p in tmp_path.iterdir()] == ["b.jsonl"]  # no temp file left


def test_exclusive_write_without_hard_links_never_overwrites(tmp_path, monkeypatch):
    _no_links(monkeypatch)
    target = tmp_path / "b.jsonl"
    target.write_bytes(b"old\n")
    with pytest.raises(FileExistsError):
        batchfile.write_atomic(target, b"new\n", exclusive=True)
    assert target.read_bytes() == b"old\n"
    assert [p.name for p in tmp_path.iterdir()] == ["b.jsonl"]  # no temp file left


def test_the_posix_fallback_creates_the_target_exclusively(tmp_path):
    """Where os.name is not "nt" the fallback is an O_EXCL create and a copy; it is the same on any host."""
    src = tmp_path / "src.tmp"
    src.write_bytes(b"new\n" * 1000)
    target = tmp_path / "b.jsonl"
    batchfile._create_new(str(src), target)
    assert target.read_bytes() == b"new\n" * 1000
    target.write_bytes(b"old\n")
    with pytest.raises(FileExistsError):
        batchfile._create_new(str(src), target)
    assert target.read_bytes() == b"old\n"


def test_a_temp_file_that_cannot_be_deleted_does_not_fail_a_published_write(tmp_path, monkeypatch):
    """On Windows an antivirus scan can hold the temp file: the batch is already published by then."""
    real = Path.unlink

    def held(self, *a, **kw):
        if self.name.endswith(".tmp"):
            raise PermissionError(13, "the file is in use")
        return real(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", held)
    target = tmp_path / "b.jsonl"
    batchfile.write_atomic(target, b"new\n")
    assert target.read_bytes() == b"new\n"
