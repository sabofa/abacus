"""Configuration, read from the environment at call time."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    library: Path
    time_s: float
    time_max_s: float
    mem_mb: int
    network: bool
    max_examples: int


def get_config() -> Config:
    env = os.environ
    return Config(
        library=Path(env.get("ABACUS_LIBRARY") or _REPO_ROOT / "library"),
        time_s=float(env.get("ABACUS_TIME_S", 20)),
        time_max_s=float(env.get("ABACUS_TIME_MAX_S", 600)),
        mem_mb=int(env.get("ABACUS_MEM_MB", 2048)),
        network=env.get("ABACUS_NETWORK", "").strip().lower() in _TRUE,
        max_examples=int(env.get("ABACUS_MAX_EXAMPLES", 10)),
    )
