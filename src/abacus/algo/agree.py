"""One reading of what a `check` role's Evidence says about a proposed answer.

The kit hard-codes no statistical threshold. A sampled check (such as `simulate`) leaves `compare.equal` as
its exact comparison and may add `compare.consistent`, its own judgement that the proposed value is
consistent with the estimate; this reads both.
"""
from __future__ import annotations

from typing import Any


def check_agrees(ev: Any) -> bool | None:
    """True when `compare.equal` is True, else when `compare.consistent` is True. Otherwise False when `compare`
    says either one is False (a comparison that says "not equal" is not overruled by a bool result). With
    neither in `compare`, the `result` when it is a bool; None (no verdict) when there is nothing to read."""
    cmp = getattr(ev, "compare", None)
    cmp = cmp if isinstance(cmp, dict) else {}
    if cmp.get("equal") is True or cmp.get("consistent") is True:
        return True
    if cmp.get("equal") is False or cmp.get("consistent") is False:
        return False
    result = getattr(ev, "result", None)
    if isinstance(result, bool):
        return result
    return None
