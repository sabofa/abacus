"""The RNG handed to `generate`: one seed, both random.Random and numpy's Generator (spec 05 s3)."""
from __future__ import annotations

import random
from typing import Any, MutableSequence, Sequence

import numpy as np


class AbacusRNG:
    def __init__(self, seed: int):
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("seed must be an integer >= 0")
        self.seed = seed
        self.py = random.Random(seed)
        self.np = np.random.default_rng(seed)

    def randint(self, a: int, b: int) -> int:
        """Uniform integer in [a, b], both ends included."""
        return self.py.randint(a, b)

    def choice(self, seq: Sequence) -> Any:
        return self.py.choice(seq)

    def shuffle(self, seq: MutableSequence) -> None:
        """Shuffle in place."""
        self.py.shuffle(seq)

    def sample(self, seq: Sequence, k: int) -> list:
        return self.py.sample(seq, k)

    def random(self) -> float:
        return self.py.random()

    def uniform(self, a: float, b: float) -> float:
        return self.py.uniform(a, b)
