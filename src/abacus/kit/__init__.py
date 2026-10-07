"""The library surface (kit/01 §3): every registered button as ``ak.<name>(**inp) -> Evidence``.

Buttons live in the modules of this package; ``registry.load_all()`` imports them. Calls from here
run in-process (the sandbox is the AI's own Python); ``budget(...)`` runs one in a child process
with the time and memory guard (kit/02 §5).

Importing ``abacus.kit.exact`` sets the package attribute ``exact`` to that module, which would hide
the wrapper; ``_bind()`` runs after every ``load_all()`` and rebinds each button name to its wrapper.
"""
from __future__ import annotations

from typing import Any


def _wrapper(name: str):
    def call(**inp: Any):
        from .. import budget as _budget
        return _budget.call(name, inp, in_process=True)

    call.__name__ = name
    return call


def _bind() -> None:
    from .. import registry
    registry.load_all()
    g = globals()
    for b in registry.all_buttons():
        if not callable(g.get(b.name)) or getattr(g.get(b.name), "__name__", None) != b.name \
                or not getattr(g.get(b.name), "_abacus_button", False):
            w = _wrapper(b.name)
            w._abacus_button = True
            g[b.name] = w


def budget(name: str, inp: dict, **limits: Any):
    """Run button ``name`` in a child process under the budget guard."""
    from .. import budget as _budget
    _bind()
    return _budget.call(name, inp, **limits)


def __getattr__(name: str):
    if name.startswith("_"):
        raise AttributeError(name)
    _bind()
    g = globals()
    if name in g and getattr(g[name], "_abacus_button", False):
        return g[name]
    raise AttributeError(f"abacus.kit has no button {name!r}")
