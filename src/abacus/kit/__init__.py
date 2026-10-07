"""The library surface (kit/01 §3): every registered button as ``ak.<name>(**inp) -> Evidence``.

Buttons live in the modules of this package; ``registry.load_all()`` imports them. Calls from here
run in-process (the sandbox is the AI's own Python); ``budget(...)`` runs one in a child process
with the time and memory guard (kit/02 §5).

Importing ``abacus.kit.exact`` sets the package attribute ``exact`` to that module, which would hide
the wrapper, so the package's module class resolves every registered button name to its wrapper
first. Submodules stay reachable through ``sys.modules`` / ``import abacus.kit.exact``.
"""
from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

_WRAPPERS: dict = {}


def _wrapper(name: str):
    def call(**inp: Any):
        from .. import budget as _budget
        return _budget.call(name, inp, in_process=True)

    call.__name__ = name
    call._abacus_button = True
    return call


def _button_wrapper(name: str):
    if name in _WRAPPERS:
        return _WRAPPERS[name]
    from .. import registry
    registry.load_all()
    try:
        registry.get(name)
    except KeyError:
        return None
    _WRAPPERS[name] = _wrapper(name)
    return _WRAPPERS[name]


def budget(name: str, inp: dict, **limits: Any):
    """Run button ``name`` in a child process under the budget guard."""
    from .. import budget as _budget, registry
    registry.load_all()
    return _budget.call(name, inp, **limits)


class _Kit(ModuleType):
    def __getattribute__(self, name: str):
        if not name.startswith("_") and name != "budget":
            w = _button_wrapper(name)
            if w is not None:
                return w
        return super().__getattribute__(name)

    def __getattr__(self, name: str):
        raise AttributeError(f"abacus.kit has no button {name!r}")


sys.modules[__name__].__class__ = _Kit
