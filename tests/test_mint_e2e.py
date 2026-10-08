"""The minting flow end to end (kit/09 s5): make, review, export, link, with a modelled create_questions response.

No Osmosis is called. The response in tests/fixtures/create_questions_response.json is modelled on Osmosis's reply (it is not a
capture) and built from the batch this test makes (seed SEED, instance 4 dropped), so it has one entry per kept instance, in order.
"""
import json
import shutil
from pathlib import Path

import pytest

from abacus.adapters import osmosis
from abacus.cli import main
from abacus.library import index, links, usage
from abacus.mint import batchfile, export, link, make, review

ROOT = Path(__file__).resolve().parents[1]
ALGO_ID = "examples.aime-modular-tower"
SEED = 20261007
RESPONSE = ROOT / "tests" / "fixtures" / "create_questions_response.json"
TAGS = ["math:number_theory"]
NODE_KEYS = ["node:aime:number_theory:modular_towers"]


@pytest.fixture
def lib(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    (lib / "examples").mkdir(parents=True)
    shutil.copy(ROOT / "library" / "examples" / "aime-modular-tower.py", lib / "examples")
    monkeypatch.setenv("ABACUS_LIBRARY", str(lib))
    return lib


@pytest.fixture
def flow(lib):
    """make -> review (drop 4) -> export. Returns the pieces the tests look at."""
    path = make.make(ALGO_ID, count=10, seed=SEED)
    review.review(path, drop=[4], notes={4: "the exponent tower is too tame"})
    out = export.export(path, tags=TAGS, node_keys=NODE_KEYS)
    return {"batch": path, "payload": out}


def run(capsys, *argv):
    capsys.readouterr()
    code = main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def test_make_gives_ten_distinct_instances_with_evidence(lib):
    path = make.make(ALGO_ID, count=10, seed=SEED)
    head, rows = batchfile.read(path)
    assert path.parent == lib / "batches" and head["made"] == 10 and head["seed"] == SEED
    assert [r["index"] for r in rows] == list(range(1, 11))
    assert all(r["flags"] == [] and r["decision"] == "keep" for r in rows)
    assert {r["algo"] for r in rows} == {ALGO_ID}
    assert all(0 <= r["answer"]["value"] <= 999 for r in rows)
    assert all(r["demo"]["kind"] == "markdown" for r in rows)
    assert [e["button"] for e in rows[0]["evidence"]] == ["algo_run", "check"]


def test_review_drops_one_with_a_note(flow):
    head, rows = batchfile.read(flow["batch"])
    dropped = [r for r in rows if r["decision"] == "drop"]
    assert [r["index"] for r in dropped] == [4]
    assert dropped[0]["note"] == "the exponent tower is too tame"
    assert len(rows) == 10  # a dropped instance stays in the file


def test_export_writes_the_osmosis_payload(flow):
    out = flow["payload"]
    batch_id = batchfile.batch_id(flow["batch"], batchfile.read(flow["batch"])[0])
    assert out.name == f"{batch_id}.osmosis.json"
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["idempotency_key"] == batch_id
    qs = payload["questions"]
    assert len(qs) == 9
    for q in qs:
        assert q["type"] == "written"
        assert q["tags"] == TAGS and q["node_keys"] == NODE_KEYS
        assert q["prompt"].startswith("Find the remainder when $") and "$" in q["prompt"]
        assert q["model_answer"].isdigit() and 0 <= int(q["model_answer"]) <= 999
        assert q["source_note"].startswith(f"abacus {ALGO_ID}@") and f" seed " in q["source_note"]
    # the fixture's previews are the starts of these prompts, in this order
    created = json.loads(RESPONSE.read_text(encoding="utf-8"))["created"]
    assert len(created) == len(qs)
    for entry, q in zip(created, qs):
        assert q["prompt"].startswith(entry["prompt_preview"].rstrip("…"))


def test_export_twice_is_identical(flow):
    first = flow["payload"].read_bytes()
    again = export.export(flow["batch"], tags=TAGS, node_keys=NODE_KEYS)
    assert again == flow["payload"] and again.read_bytes() == first
    assert json.loads(first)["idempotency_key"] == batchfile.batch_id(flow["batch"], None)


def test_link_writes_one_minted_link_per_kept_instance(flow):
    created = json.loads(RESPONSE.read_text(encoding="utf-8"))["created"]
    path, info = link.link_batch(flow["batch"], RESPONSE)
    head, rows = batchfile.read(path)
    batch_id = batchfile.batch_id(path, head)
    assert info["matched_by"] == "order" and info["linked"] == 9 and info["already_linked"] == 0
    assert info["problems"] == []

    found = links.list_links(algo=ALGO_ID)
    assert len(found) == 9
    kept = [r for r in rows if r["decision"] == "keep"]
    for entry, row, rec in zip(created, kept, found):
        assert rec["target"] == f"osmosis:q:{entry['lineage_id']}" and rec["kind"] == "minted"
        assert rec["algo"] == ALGO_ID and rec["algo_hash"] == row["algo_hash"] == head["algo_hash"]
        assert rec["seed"] == row["seed"] and rec["batch"] == batch_id
        assert row["target"] == rec["target"] and row["remote_id"] == entry["id"]
    assert "target" not in next(r for r in rows if r["index"] == 4)  # the dropped one is not linked


def test_linking_the_same_response_again_adds_nothing(flow):
    link.link(flow["batch"], RESPONSE)
    _, info = link.link_batch(flow["batch"], json.loads(RESPONSE.read_text(encoding="utf-8")))
    assert info["linked"] == 0 and info["already_linked"] == 9
    assert len(links.list_links(algo=ALGO_ID)) == 9


def test_link_matches_on_prompt_when_the_order_differs(flow):
    created = json.loads(RESPONSE.read_text(encoding="utf-8"))
    created["created"].reverse()
    _, info = link.link_batch(flow["batch"], created)
    assert info["matched_by"] == "prompt" and info["linked"] == 9
    assert {p["code"] for p in info["problems"]} == {"no_match"} and len(info["problems"]) == 1
    rows = batchfile.read(flow["batch"])[1]
    by_target = {r["target"]: r for r in rows if "target" in r}
    for entry in created["created"]:
        assert by_target["osmosis:q:" + entry["lineage_id"]]["statement"].startswith(entry["prompt_preview"].rstrip("…"))


def test_link_reports_a_short_response_and_a_bad_entry(flow):
    created = json.loads(RESPONSE.read_text(encoding="utf-8"))
    created["created"] = created["created"][:-1] + [{"id": "q_x", "prompt_preview": "no lineage"}]
    _, info = link.link_batch(flow["batch"], created)
    codes = [p["code"] for p in info["problems"]]
    assert "bad_entry" in codes and "count_mismatch" in codes and "unmatched_instance" in codes
    assert info["linked"] == 8
    with pytest.raises(ValueError):
        link.link_batch(flow["batch"], {"questions": []})


def test_find_and_search_lead_back_to_the_algorithm(flow, capsys):
    created = json.loads(RESPONSE.read_text(encoding="utf-8"))["created"]
    code, ev = run(capsys, "mint", "link", str(flow["batch"]), "--created", str(RESPONSE))
    assert code == 0 and ev["result"]["linked"] == 9 and ev["flags"] == []

    target = f"osmosis:q:{created[2]['lineage_id']}"
    code, found = run(capsys, "link", "find", target)  # the link commands print the links themselves
    assert code == 0
    assert [r["algo"] for r in found] == [ALGO_ID]
    assert found[0]["kind"] == "minted" and found[0]["seed"] is not None

    [hit] = index.search("", tag="number-theory")
    assert hit["id"] == ALGO_ID and hit["links"] == 9
    assert hit["uses"] == usage.counts()[ALGO_ID] and hit["uses"] >= 10  # make ran generate/compute/check/demo
    assert [h["id"] for h in index.search("", tag="aime", linked="osmosis")] == [ALGO_ID]
    assert index.search("", tag="aime", unlinked=True) == []


# --- the adapter reads the response; link.py sees only neutral fields ---------------------------------

def test_parse_created_gives_neutral_entries():
    got = osmosis.parse_created({"created": [
        {"id": "q_1", "lineage_id": " ln_a ", "prompt_preview": "Find x\u2026"},
        {"id": "q_2", "prompt_preview": "no lineage"},
        "junk"]})
    assert got == [{"remote_id": "q_1", "target": "osmosis:q:ln_a", "preview": "Find x\u2026"},
                   {"remote_id": "q_2", "target": None, "preview": "no lineage"},
                   {"remote_id": None, "target": None, "preview": ""}]
    assert osmosis.parse_created([{"id": "q", "lineage_id": "l"}])[0]["target"] == "osmosis:q:l"
    with pytest.raises(ValueError):
        osmosis.parse_created({"questions": []})


def test_link_py_and_the_button_name_no_osmosis_field():
    for name in ("link.py", "surface.py"):
        text = (ROOT / "src" / "abacus" / "mint" / name).read_text(encoding="utf-8")
        assert "lineage_id" not in text and "osmosis_id" not in text and "prompt_preview" not in text


# --- stale, conflicting and ambiguous links ------------------------------------------------------

def _hand_batch(lib, statements):
    """A batch of kept instances written by hand: algo, seed and statement are all `link` needs."""
    path = lib / "batches" / "2026-10-07-hand-01.jsonl"
    head = {"batch": "2026-10-07-hand-01", "algo_hash": "h1"}
    rows = [{"index": i, "decision": "keep", "algo": ALGO_ID, "algo_hash": "h1", "seed": 100 + i, "statement": s}
            for i, s in enumerate(statements, start=1)]
    path.parent.mkdir(parents=True, exist_ok=True)
    batchfile.write_atomic(path, batchfile.render(head, rows))
    return path


def _response(prefix, previews):
    return {"created": [{"id": f"q_{prefix}{i}", "lineage_id": f"{prefix}{i}", "prompt_preview": p}
                        for i, p in enumerate(previews)]}


STATEMENTS = [f"Find the remainder when ${a}^{{5^{{7}}}}$ is divided by {m}." for a, m in
              ((2, 440), (3, 441), (4, 442), (5, 443))]
PREVIEWS = [s[:30] + "\u2026" for s in STATEMENTS]
SAME = "Find the remainder when $2^{5^{7}}$ is divided b"  # the start two different instances share


def test_the_same_response_twice_adds_nothing(lib):
    path = _hand_batch(lib, STATEMENTS)
    first = link.link_batch(path, _response("ln", PREVIEWS))[1]
    again = link.link_batch(path, _response("ln", PREVIEWS))[1]
    assert first["linked"] == 4 and again["linked"] == 0 and again["already_linked"] == 4
    assert again["problems"] == [] and len(links.list_links(algo=ALGO_ID)) == 4


def test_a_different_response_flags_the_conflicts_and_adds_no_links(lib):
    path = _hand_batch(lib, STATEMENTS)
    link.link(path, _response("ln", PREVIEWS))
    before = batchfile.read(path)[1]
    _, info = link.link_batch(path, _response("zz", PREVIEWS))
    assert info["linked"] == 0
    assert [p["code"] for p in info["problems"]] == ["relinked_conflict"] * 4
    assert "osmosis:q:ln0" in info["problems"][0]["message"] and "osmosis:q:zz0" in info["problems"][0]["message"]
    assert sorted(x["target"] for x in links.list_links(algo=ALGO_ID)) == [f"osmosis:q:ln{i}" for i in range(4)]
    assert batchfile.read(path)[1] == before  # the batch still records the first links


def test_identical_previews_are_ambiguous_and_not_linked(lib):
    stmts = [f"{SAME}y 440.", f"{SAME}y 938.", "Another question entirely."]
    path = _hand_batch(lib, stmts)
    # the entries are in another order than the instances, so the order rule does not apply
    resp = _response("ln", [stmts[2][:20], SAME + "\u2026", SAME + "\u2026"])
    _, info = link.link_batch(path, resp)
    assert info["matched_by"] == "prompt" and info["linked"] == 1
    amb = [p for p in info["problems"] if p["code"] == "ambiguous"]
    assert len(amb) == 2 and "entry 2" in amb[0]["message"] and "entry 3" in amb[1]["message"]
    assert [x["target"] for x in links.list_links(algo=ALGO_ID)] == ["osmosis:q:ln0"]
    assert {p["code"] for p in info["problems"]} >= {"ambiguous", "unmatched_instance"}
    assert [r.get("target") for r in batchfile.read(path)[1]] == [None, None, "osmosis:q:ln0"]


def test_order_stays_primary_when_previews_are_identical(lib):
    path = _hand_batch(lib, [f"{SAME}y 440.", f"{SAME}y 938."])
    _, info = link.link_batch(path, _response("ln", [SAME + "\u2026", SAME + "\u2026"]))
    assert info["matched_by"] == "order" and info["linked"] == 2 and info["problems"] == []


def test_an_entry_with_no_target_is_reported_and_the_rest_linked(lib):
    path = _hand_batch(lib, STATEMENTS[:2])
    resp = _response("ln", PREVIEWS[:2])
    resp["created"][1]["lineage_id"] = "   "
    _, info = link.link_batch(path, resp)
    assert info["linked"] == 1 and "bad_entry" in [p["code"] for p in info["problems"]]


def test_a_bad_target_is_checked_before_anything_is_written(lib):
    path = _hand_batch(lib, STATEMENTS[:3])
    resp = _response("ln", PREVIEWS[:3])
    resp["created"][2]["lineage_id"] = "x" + chr(10) + "y"
    _, info = link.link_batch(path, resp)
    assert "bad_target" in [p["code"] for p in info["problems"]]
    assert info["linked"] == 2 and len(links.list_links(algo=ALGO_ID)) == 2


def test_link_takes_the_lock_review_takes(lib, monkeypatch):
    import contextlib
    path = _hand_batch(lib, STATEMENTS[:1])
    held = []
    real = link.file_lock

    @contextlib.contextmanager
    def spy(p):
        with real(p):
            held.append(Path(p).name)
            yield
    monkeypatch.setattr(link, "file_lock", spy)
    link.link(path, _response("ln", PREVIEWS[:1]))
    assert held == [path.name]
    lock = path.with_name(path.name + ".lock")
    assert not lock.exists()
    lock.write_text("")  # a held lock makes review wait, then time out
    monkeypatch.setattr("abacus.library._jsonl.LOCK_TIMEOUT_S", 0.1)
    with pytest.raises(TimeoutError):
        review.review(path, drop=[1])
