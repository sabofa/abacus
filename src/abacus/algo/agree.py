"""One reading of what a `check` role's Evidence says about a proposed answer.

The kit hard-codes no statistical threshold. A sampled check (such as `simulate`) leaves `compare.equal` as
its exact comparison and may add `compare.consistent`, its own judgement that the proposed value is
consistent with the estimate; this reads both.
"""
from __future__ import annotations

from typing import Any


def check_agrees(ev: Any) -> bool | None:
    """True when `compare.equal` is True, else when `compare.consistent` is True, else the `result` when it
    is a bool. Otherwise False if `compare` said `equal` or `consistent` was False, and None (no verdict)
    when it said neither."""
    cmp = getattr(ev, "compare", None)
    cmp = cmp if isinstance(cmp, dict) else {}
    if cmp.get("equal") is True or cmp.get("consistent") is True:
        return True
    result = getattr(ev, "result", None)
    if isinstance(result, bool):
        return result
    if cmp.get("equal") is False or cmp.get("consistent") is False:
        return False
    return None
