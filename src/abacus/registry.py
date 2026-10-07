"""The button registry: name -> function, schema, description, default budget."""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from typing import Any, Callable

_REGISTRY: dict[str, "Button"] = {}


@dataclass(frozen=True)
class Button:
    name: str
    fn: Callable[[dict, Any], Any]
    description: str
    input_schema: dict
    default_time_s: float | None
    uses_seed: bool


def button(name: str, *, description: str, input_schema: dict,
           default_time_s: float | None = None, uses_seed: bool = False):
    def deco(fn):
        if name in _REGISTRY:
            raise ValueError(f"button {name!r} is already registered")
        _REGISTRY[name] = Button(name, fn, description, input_schema, default_time_s, uses_seed)
        return fn
    return deco


def get(name: str) -> Button:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown button {name!r}; known: {sorted(_REGISTRY)}") from None


def all_buttons() -> list[Button]:
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


def load_all() -> None:
    try:
        pkg = importlib.import_module("abacus.kit")
    except ModuleNotFoundError as e:
        if e.name == "abacus.kit":
            return
        raise
    for m in pkgutil.iter_modules(pkg.__path__):
        importlib.import_module(f"abacus.kit.{m.name}")
