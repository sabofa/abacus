"""The Evidence envelope (spec 03). No verdict fields, ever."""
from __future__ import annotations

import fractions
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import sympy as sp

from . import __version__
from .config import get_config

METHODS = {"exhaustive", "sampled", "symbolic", "numeric", "search", "fit", "timed"}


def jsonable(x: Any) -> Any:
    if x is None or isinstance(x, (bool, str)):
        return x
    if isinstance(x, sp.Basic):
        if x.is_Integer:
            return int(x)
        if x.is_Rational:
            return f"{x.p}/{x.q}"
        return str(x)
    if isinstance(x, fractions.Fraction):
        return f"{x.numerator}/{x.denominator}"
    if isinstance(x, np.ndarray):
        return jsonable(x.tolist())
    if isinstance(x, np.generic):
        return jsonable(x.item())
    if isinstance(x, int):
        return x
    if isinstance(x, float):
        if math.isnan(x):
            return "nan"
        if math.isinf(x):
            return "inf" if x > 0 else "-inf"
        return x
    if isinstance(x, (set, frozenset)):
        items = [jsonable(i) for i in x]
        try:
            return sorted(items)
        except TypeError:
            return sorted(items, key=repr)
    if isinstance(x, (list, tuple)):
        return [jsonable(i) for i in x]
    if isinstance(x, dict):
        return {k if isinstance(k, str) else str(jsonable(k)): jsonable(v) for k, v in x.items()}
    return str(x)


def _equal(a: Any, b: Any) -> bool:
    try:
        sa, sb = sp.sympify(a), sp.sympify(b)
        return bool(sp.simplify(sa - sb) == 0)
    except Exception:
        pass
    try:
        return bool(a == b)
    except Exception:
        return False


def make_compare(proposed: Any, computed: Any) -> dict:
    return {"proposed": jsonable(proposed), "computed": jsonable(computed),
            "equal": _equal(proposed, computed)}


@dataclass
class Evidence:
    button: str
    result: Any
    method: str
    scope: str
    complete: bool = True
    precision: Any = None
    examples: list = field(default_factory=list)
    compare: dict | None = None
    flags: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    seed: int | None = None
    budget: dict = field(default_factory=dict)
    kit: str = __version__
    input: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.scope or not str(self.scope).strip():
            raise ValueError("Evidence.scope must be non-empty")
        if self.method not in METHODS:
            raise ValueError(f"Evidence.method must be one of {sorted(METHODS)}, got {self.method!r}")

    def flag(self, code: str, message: str) -> None:
        self.flags.append({"code": code, "message": message})

    def to_dict(self, full: bool = False) -> dict:
        examples, notes = list(self.examples), list(self.notes)
        cap = get_config().max_examples
        if not full and len(examples) > cap:
            notes.append(f"showing {cap} of {len(examples)} examples")
            examples = examples[:cap]
        return jsonable({
            "button": self.button, "result": self.result, "method": self.method,
            "scope": self.scope, "complete": self.complete, "precision": self.precision,
            "examples": examples, "compare": self.compare, "flags": self.flags,
            "notes": notes, "seed": self.seed, "budget": self.budget,
            "kit": self.kit, "input": self.input,
        })
