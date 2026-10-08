"""Probability family (quant style): expected number of rolls until the running total exceeds N.

compute: exact, by the recurrence f(s) = 1 + (1/sides) * sum f(s + face) over Fractions.
check: a short seeded Monte Carlo through `simulate`; the evidence is simulate's own, so it carries the
estimate and its interval. `compare.equal` there says only whether the proposed value is consistent with the
estimate (|z| at most 3); it is not a proof.
"""
from fractions import Fraction

import abacus.kit as ak

META = {
    "id": "examples.dice-expected-value",
    "title": "Expected rolls until the total exceeds N",
    "summary": "A fair die is rolled until the running total exceeds N; the expected number of rolls, exactly "
               "by recurrence and checked by a seeded Monte Carlo.",
    "roles": ["generate", "compute", "check", "hand_space"],
    "tags": ["probability", "expected-value", "quant"],
    "techniques": ["recurrence", "monte-carlo"],
    "answer": {"format": "rational", "range": [1, 30]},
    "knobs": {
        "n": {"int": [6, 24], "pattern_knob": True},
        "sides": {"choice": [4, 6, 8]},
    },
    "requires": [],
    "notes": "check runs 10000 trials with a seed taken from the parameters, so it is repeatable.",
}

TRIALS = 10_000
Z_LIMIT = 3.0  # |z| above about 3 is unlikely by chance alone (simulate's own z_note)


def compute(params):
    n, sides = params["n"], params["sides"]
    f = {}
    for s in range(n, -1, -1):  # f(s): expected further rolls from a total of s; the game ends above n
        f[s] = 1 + Fraction(1, sides) * sum(f.get(s + face, 0) for face in range(1, sides + 1))
    return f[0]


def _seed(params):
    return (params["n"] * 1009 + params["sides"] * 31) % 2**31


def check(params, proposed):
    n, sides = params["n"], params["sides"]
    trial = (f"def t(rng):\n    total = 0\n    rolls = 0\n    while total <= {n}:\n"
             f"        total += rng.randint(1, {sides})\n        rolls += 1\n    return rolls\n")
    ev = ak.simulate(trial=trial, trials=TRIALS, seed=_seed(params), proposed=str(Fraction(str(proposed))))
    cmp = ev.compare
    if isinstance(cmp, dict) and cmp.get("z") is not None:
        cmp["equal"] = abs(cmp["z"]) <= Z_LIMIT
        ev.notes.append(f"compare.equal here means the proposed value is consistent with the estimate "
                        f"(|z| <= {Z_LIMIT:g}); it is not an exact comparison")
    return ev


def generate(rng, knobs):
    n = knobs.get("n", rng.randint(6, 24))
    sides = knobs.get("sides", rng.choice([4, 6, 6, 6, 8]))
    p = {"n": n, "sides": sides}
    return {"params": p,
            "statement": (f"A fair ${sides}$-sided die, with faces $1$ to ${sides}$, is rolled repeatedly until the "
                          f"running total exceeds ${n}$. What is the expected number of rolls?"),
            "answer": compute(p)}


def hand_space(params):
    """Roll sequences a person would have to weigh, bounded by sides^n."""
    return params["sides"] ** params["n"]
