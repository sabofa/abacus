"""Buttons that expose minting to the MCP surface and the registry (not spec buttons): `mint_make` (kit/07 s2).

A bad algorithm, knob or input is a flagged Evidence with no result and no file, never an exception.
"""
from __future__ import annotations

from .. import registry
from ..algo.loader import AlgoImportError, MetaError
from ..evidence import Evidence
from ..library import store
from . import make as _make

BUTTON = "mint_make"
BUDGET_SHARE = 0.8  # make stops starting attempts here, leaving the rest to write the file and answer


def _fail(code: str, msg: str, scope: str) -> Evidence:
    ev = Evidence(button=BUTTON, result=None, method="timed", scope=scope, complete=False)
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
