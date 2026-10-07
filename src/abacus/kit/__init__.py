"""The library surface (kit/01 §3): every registered button as ``ak.<name>(**inp) -> Evidence``.

Buttons live in the modules of this package; ``registry.load_all()`` imports them. Calls from here
run in-process (the sandbox is the AI's own Python); ``budget(...)`` runs one in a child process
with the time and memory guard (kit/02 §5).
"""
from __future__ import annotations

from typing import Any


def budget(name: str, inp: dict, **limits: Any):
    """Run button ``name`` in a child process under the budget guard."""
    from .. import budget as _budget, registry
    registry.load_all()
    return _budget.call(name, inp, **limits)


def __getattr__(name: str):
    if name.startswith("_"):
        raise AttributeError(name)
    from .. import budget as _budget, registry
    registry.load_all()
    try:
        registry.get(name)
    except KeyError:
        raise AttributeError(f"abacus.kit has no button {name!r}") from None

    def call(**inp: Any):
        return _budget.call(name, inp, in_process=True)

    call.__name__ = name
    return call
