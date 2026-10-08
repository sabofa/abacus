"""The minting flow end to end (kit/09 s5): make, review, export, link, with a recorded create_questions response.

No Osmosis is called. The response in tests/fixtures/create_questions_response.json was recorded from the
batch this test makes (seed SEED, instance 4 dropped), so it has one entry per kept instance, in order.
"""
import json
import shutil
from pathlib import Path

import pytest

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
        assert row["lineage_id"] == entry["lineage_id"] and row["osmosis_id"] == entry["id"]
    assert "lineage_id" not in next(r for r in rows if r["index"] == 4)  # the dropped one is not linked


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
    by_lineage = {r["lineage_id"]: r for r in rows if "lineage_id" in r}
    for entry in created["created"]:
        assert by_lineage[entry["lineage_id"]]["statement"].startswith(entry["prompt_preview"].rstrip("…"))


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
