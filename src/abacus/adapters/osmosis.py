"""Instances to Osmosis `create_questions` items (kit/07 s4). The only module that knows Osmosis's field names.

`to_create_questions` never refuses: what Osmosis would reject (an mc item with no correct choice, no tags,
a node key without `node:`, ...) is reported in `problems` and the item is written as it is, so the AI can
read the problem and decide.

A problem is a string, `"<code>: <message>"`; `split_problem` takes it apart.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from ..algo.loader import ANSWER_FORMATS
from ..evidence import jsonable

NODE_PREFIX = "node:"
MIN_CHOICES = 2
# A Fraction with denominator 1, as a batch file spells it: "2/1".
_WHOLE_RATIONAL = re.compile(r"\s*([+-]?\d+)\s*/\s*1\s*")

# The codes a problem can have.
BAD_TAGS, BAD_NODE_KEY, BAD_PROMPT = "bad_tags", "bad_node_key", "bad_prompt"
MC_CHOICES, BAD_CHOICE, BAD_ANSWER, NO_QUESTIONS = "mc_choices", "bad_choice", "bad_answer", "no_questions"


def split_problem(problem: str) -> tuple[str, str]:
    """`"bad_tags: tags is empty"` becomes `("bad_tags", "tags is empty")`."""
    code, _, message = problem.partition(": ")
    return code, message


def _seq(v: Any) -> str:
    """A tuple or set element as text: nested sequences are parenthesised, scalars are `str`."""
    if isinstance(v, list):
        return "(" + ", ".join(_seq(x) for x in v) + ")"
    return str(v)


def render_answer(answer: dict) -> str:
    """An answer `{"format": ..., "value": ...}` as the text of a written item's `model_answer`.

    integer and rational: `str(value)`, and a rational with denominator 1 is the whole number (`2/1` is `2`).
    expression: the sympy string. tuple: `(a, b)`. set: `{a, b}`.
    choice: the letter. text: as is. ValueError for anything that is not an answer, an unknown format, or
    an answer with no value.
    """
    if not isinstance(answer, dict) or "format" not in answer or "value" not in answer:
        raise ValueError(f"an answer is {{'format': ..., 'value': ...}}, got {answer!r}")
    fmt, value = answer["format"], answer["value"]
    if fmt not in ANSWER_FORMATS:
        raise ValueError(f"unknown answer format {fmt!r}; known: {', '.join(ANSWER_FORMATS)}")
    if value is None:
        raise ValueError(f"the {fmt} answer has no value")
    if fmt in ("tuple", "set"):
        items = jsonable(value)  # a Python set becomes a sorted list; a tuple, a list
        if not isinstance(items, list):
            return str(items)
        inner = ", ".join(_seq(x) for x in items)
        return f"({inner})" if fmt == "tuple" else "{" + inner + "}"
    text = str(value)
    whole = _WHOLE_RATIONAL.fullmatch(text) if fmt == "rational" else None
    return str(int(whole.group(1))) if whole else text


def _label(inst: dict, position: int) -> str:
    index = inst.get("index")
    return f"instance {index if index is not None else position}"


def _text(x: Any) -> bool:
    return isinstance(x, str) and bool(x.strip())


def _source_note(inst: dict) -> str | None:
    algo = inst.get("algo")
    if not _text(algo):
        return None
    note = f"abacus {algo}"
    if inst.get("algo_hash"):
        note += f"@{inst['algo_hash']}"
    if inst.get("seed") is not None:
        note += f" seed {inst['seed']}"
    return note


def _choices(raw: Iterable, label: str, problems: list[str]) -> list[dict]:
    out = []
    for n, c in enumerate(raw, start=1):
        if not isinstance(c, dict):
            problems.append(f"{BAD_CHOICE}: {label}, choice {n} is not an object with a body and a correct flag")
            continue
        body, correct = c.get("body"), c.get("correct")
        if not _text(body):
            problems.append(f"{BAD_CHOICE}: {label}, choice {n} has no body text")
        if not isinstance(correct, bool):
            problems.append(f"{BAD_CHOICE}: {label}, choice {n} has `correct` = {correct!r}, not true or false")
        item = {"body": body if isinstance(body, str) else "", "is_correct": correct is True}
        if c.get("note"):  # no note, no misconception
            item["misconception"] = c["note"]
        out.append(item)
    return out


def _mc_count_problem(choices: list[dict]) -> str | None:
    said = []
    if len(choices) < MIN_CHOICES:
        said.append(f"{len(choices)} choice{'s' if len(choices) != 1 else ''} (at least {MIN_CHOICES} are needed)")
    right = sum(c["is_correct"] for c in choices)
    if right != 1:
        said.append(f"{right} correct choice{'s' if right != 1 else ''} (exactly one is needed)")
    return " and ".join(said) if said else None


def _item(inst: dict, position: int, tags: list, node_keys: list, family_id: str | None,
          problems: list[str]) -> dict:
    label = _label(inst, position)
    statement = inst.get("statement")
    if not _text(statement):
        problems.append(f"{BAD_PROMPT}: {label} has no statement, so the item has no prompt")
    # No choices, whether none or an empty list, is a written item.
    item: dict = {"type": "mc" if inst.get("choices") else "written",
                  "prompt": statement if isinstance(statement, str) else ""}
    if item["type"] == "mc":
        item["choices"] = _choices(inst["choices"] if isinstance(inst["choices"], list) else [], label, problems)
        said = _mc_count_problem(item["choices"])
        if said:
            problems.append(f"{MC_CHOICES}: {label} is mc and has {said}")
    else:
        try:
            text = render_answer(inst.get("answer"))
        except ValueError as e:
            problems.append(f"{BAD_ANSWER}: {label} is written but its answer cannot be rendered as a model_answer: {e}")
        else:
            if text.strip():
                item["model_answer"] = text
            else:
                problems.append(f"{BAD_ANSWER}: {label} is written but its answer renders as empty text, "
                                "so it has no model_answer")
    item["tags"] = list(tags)
    if node_keys:
        item["node_keys"] = list(node_keys)
    note = _source_note(inst)
    if note:
        item["source_note"] = note
    if family_id is not None:
        item["family_id"] = family_id  # Osmosis does not accept this yet (live/02); sent anyway, for pools
    return item


def to_create_questions(instances: Iterable[dict], *, tags, node_keys=None, family_id: str | None = None,
                        batch_id: str) -> tuple[dict, list[str]]:
    """The `create_questions` payload for `instances` (batch rows, all of them to be exported), and the
    problems found in it. The payload is always complete: `{"questions": [...], "idempotency_key": batch_id}`.
    The batch id is the idempotency key, so sending the same batch again creates nothing twice.
    """
    problems: list[str] = []
    tag_list = [tags] if isinstance(tags, str) else list(tags or [])
    if not tag_list:
        problems.append(f"{BAD_TAGS}: there are no tags; create_questions needs at least one, and it must already exist in Osmosis")
    elif not all(_text(t) for t in tag_list):
        problems.append(f"{BAD_TAGS}: tags must be non-empty strings, got {tag_list!r}")
    keys = [node_keys] if isinstance(node_keys, str) else list(node_keys or [])
    for key in keys:
        if not (isinstance(key, str) and key.startswith(NODE_PREFIX) and len(key) > len(NODE_PREFIX)):
            problems.append(f"{BAD_NODE_KEY}: node key {key!r} must start with '{NODE_PREFIX}' and name a node")
    questions = [_item(inst, n, tag_list, keys, family_id, problems) for n, inst in enumerate(instances, start=1)]
    if not questions:
        problems.append(f"{NO_QUESTIONS}: no instances to export, so the payload has no questions")
    return {"questions": questions, "idempotency_key": batch_id}, problems
