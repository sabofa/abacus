"""Buttons that expose minting to the MCP surface and the registry (not spec buttons): `mint_make`,
`mint_review` and `mint_export` (kit/07 s2 to s4).

A bad algorithm, batch, knob or input is a flagged Evidence with no result and no file, never an exception.
"""
from __future__ import annotations

from .. import registry
from ..algo.loader import AlgoImportError, MetaError
from ..evidence import Evidence
from ..library import store
from . import batchfile, export as _export, make as _make, review as _review

BUTTON = "mint_make"
REVIEW = "mint_review"
EXPORT = "mint_export"
BUDGET_SHARE = 0.8  # make stops starting attempts here, leaving the rest to write the file and answer


def _fail(code: str, msg: str, scope: str, button: str = BUTTON) -> Evidence:
    ev = Evidence(button=button, result=None, method="timed", scope=scope, complete=False)
    ev.flag(code, msg)
    return ev


@registry.button(
    BUTTON,
    description="Make a batch of problem instances from an algorithm (a library id or a file path): for each of "
                "`count` attempts a seed is derived from `seed`, then generate, compute, check and demo run and their "
                "Evidence is stored on the instance. Flags are set across the batch and never drop an instance: "
                "duplicate_params, duplicate_statement, duplicate_answer, derivations_disagree, out_of_range, "
                "incomplete. A repeat of params already in the batch is skipped and generation goes on, up to "
                "count x 5 attempts. `knobs` fixes generate's knobs. `seed` is required; the same algorithm, "
                "seed and knobs make the same instances. Writes <library>/batches/<date>-<slug>-<nn>.jsonl, whose "
                "first line is a summary (count, made, attempts, flags_by_code, answer_spread, time_s). "
                "`time_s` caps the time spent; it makes fewer instances rather than overrun.",
    input_schema={
        "type": "object",
        "properties": {
            "algo": {"type": "string"},
            "count": {"type": "integer", "minimum": 1, "maximum": 1000},
            "seed": {"type": "integer", "minimum": 0},
            "knobs": {"type": "object"},
            "time_s": {"type": "number", "exclusiveMinimum": 0},
        },
        "required": ["algo", "count"],  # seed is required too, but the budget layer takes it out before validating
    },
    default_time_s=300,
)
def mint_make(inp: dict, ctx) -> Evidence:
    if inp.get("seed") is None:
        return _fail("bad_input", "seed is required: the same algorithm, seed and knobs make the same batch",
                     "input rejected before running; nothing was written")
    budget_s = ctx.time_left() * BUDGET_SHARE
    if inp.get("time_s") is not None:
        budget_s = min(budget_s, inp["time_s"])
    try:
        path, summary = _make.make_batch(inp["algo"], count=inp["count"], seed=inp["seed"],
                                         knobs=inp.get("knobs"), time_s=budget_s)
    except store.NoSuchAlgo as e:  # before AlgoImportError and ValueError, which it is not a kind of
        return _fail("no_such_algo", str(e), "no algorithm with this id is in the library; nothing was written")
    except MetaError as e:  # a ValueError, so before the bad input case
        return _fail("bad_meta", str(e), "the algorithm's META is invalid; nothing was written")
    except AlgoImportError as e:
        return _fail("import_error", str(e), "the algorithm file could not be imported; nothing was written")
    except ValueError as e:
        return _fail("bad_input", str(e), "input rejected before running; nothing was written")
    made, count = summary["made"], summary["count"]
    ev = Evidence(button=BUTTON, result={"batch": summary["batch"], "path": str(path), "summary": summary},
                  method="timed", scope=f"made {made} of {count} instances in {summary['attempts']} attempts",
                  complete=summary["stopped_by"] != "time", notes=list(summary["notes"]))
    if made < count:
        ev.flag("short_batch", f"made only {made} of the {count} instances asked for")
    return ev


def _batch_fail(button: str, e: Exception) -> Evidence:
    """The Evidence for a batch that cannot be read, or input that cannot be used. Nothing was written."""
    if isinstance(e, batchfile.NoSuchBatch):  # an OSError, so before the general OSError case
        return _fail("no_such_batch", str(e), "no batch with this id or path; nothing was written", button)
    if isinstance(e, batchfile.BadBatch):  # a ValueError, so before the bad input case
        return _fail("bad_batch", str(e), "the file is not a batch; nothing was written", button)
    if isinstance(e, OSError):
        return _fail("io_error", f"{type(e).__name__}: {e}", "the batch could not be read or written", button)
    return _fail("bad_input", str(e), "input rejected before running; nothing was written", button)


def _index_notes(raw: dict | None) -> dict[int, str]:
    """`notes` arrives as JSON, whose keys are text: {"5": "too easy"} is the note for instance 5."""
    notes = {}
    for k, v in (raw or {}).items():
        try:
            notes[int(k)] = v
        except ValueError:
            raise ValueError(f"notes: {k!r} is not an instance index; use the index as the key, such as \"5\"") from None
    return notes


@registry.button(
    REVIEW,
    description="Record decisions in a batch made by mint_make. `batch` is a batch id (such as "
                "2026-10-07-power-mod-01) or a path to a batch file. Each instance in `drop` gets decision 'drop' and "
                "each in `keep` gets 'keep' (the default); `notes` maps an instance index (as text, such as \"5\") to "
                "a note, and an empty note removes it. Indexes are the instances' `index` field. An unknown index "
                "changes nothing. This is bookkeeping: abacus attaches no conditions to a decision, and a dropped "
                "instance stays in the file. Rewrites the batch file atomically.",
    input_schema={
        "type": "object",
        "properties": {
            "batch": {"type": "string"},
            "drop": {"type": "array", "items": {"type": "integer"}},
            "keep": {"type": "array", "items": {"type": "integer"}},
            "notes": {"type": "object", "additionalProperties": {"type": "string"}},
        },
        "required": ["batch"],
    },
    default_time_s=30,
)
def mint_review(inp: dict, ctx) -> Evidence:
    try:
        path, info = _review.review_batch(inp["batch"], drop=inp.get("drop") or (), keep=inp.get("keep") or (),
                                          notes=_index_notes(inp.get("notes")))
    except (ValueError, OSError) as e:
        return _batch_fail(REVIEW, e)
    n = info["instances"]
    return Evidence(button=REVIEW, result=info, method="timed",
                    scope=f"recorded decisions on {len(info['changed'])} of {n} instances; "
                          f"{info['kept']} kept, {info['dropped']} dropped")


@registry.button(
    EXPORT,
    description="Export a batch's kept instances as an Osmosis create_questions payload, written to "
                "<batch-id>.osmosis.json beside the batch file (replacing an earlier export). Nothing is sent: the "
                "caller sends the file's `questions` to Osmosis with idempotency_key (the batch id). An instance is kept "
                "unless mint_review dropped it. An instance with `choices` becomes an mc item, any other a written item "
                "with the answer as model_answer. `tags` are required and must already exist in Osmosis; `node_keys` "
                "must start with 'node:'; `family_id` is added to every item, for pools. Problems with the payload "
                "(bad_tags, bad_node_key, mc_choices, bad_choice, bad_answer, bad_prompt, bad_decision, "
                "no_questions) come back as flags; the file is written anyway.",
    input_schema={
        "type": "object",
        "properties": {
            "batch": {"type": "string"},
            "to": {"enum": list(_export.TARGETS)},
            "tags": {"type": "array", "items": {"type": "string"}},
            "node_keys": {"type": "array", "items": {"type": "string"}},
            "family_id": {"type": "string"},
        },
        "required": ["batch", "tags"],
    },
    default_time_s=30,
)
def mint_export(inp: dict, ctx) -> Evidence:
    try:
        path, info = _export.export_batch(inp["batch"], to=inp.get("to", "osmosis"), tags=inp["tags"],
                                          node_keys=inp.get("node_keys"), family_id=inp.get("family_id"))
    except (ValueError, OSError) as e:
        return _batch_fail(EXPORT, e)
    problems = info.pop("problems")
    q = info["questions"]
    ev = Evidence(button=EXPORT, result=info, method="timed",
                  scope=f"exported {q} kept instance{'s' if q != 1 else ''} to {path.name}; {info['dropped']} dropped")
    for p in problems:
        ev.flag(p["code"], p["message"])
    return ev
