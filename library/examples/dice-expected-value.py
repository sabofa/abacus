"""Probability family (quant style): expected number of rolls until the running total exceeds N.

compute: exact, by the recurrence f(s) = 1 + (1/sides) * sum f(s + face) over Fractions.
check: a short seeded Monte Carlo through `simulate`; the evidence is simulate's own, so it carries the
estimate and its interval. simulate's `compare.equal` stays what it is (an exact comparison, false for an
estimate); this file adds `compare.consistent`, whether the proposed value is within |z| <= 3 of the
estimate. That is not a proof.

The knobs keep the exact answer short enough to type: its denominator divides sides^n, which is under 10^6
here (n up to 7, sides up to 6), so the answer is a fraction a person can enter by hand.
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
    "answer": {"format": "rational", "range": [1.3, 4.4]},
    "knobs": {
        "n": {"int": [2, 7], "pattern_knob": True},
        "sides": {"choice": [3, 4, 5, 6]},
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
        cmp["consistent"] = abs(cmp["z"]) <= Z_LIMIT
        ev.notes.append(f"compare.consistent: the proposed value is within |z| <= {Z_LIMIT:g} of the estimate; "
                        "it is not an exact comparison")
    return ev


def generate(rng, knobs):
    n = knobs.get("n", rng.randint(2, 7))
    sides = knobs.get("sides", rng.choice([3, 4, 5, 6]))
    p = {"n": n, "sides": sides}
    return {"params": p,
            "statement": (f"A fair ${sides}$-sided die, with faces $1$ to ${sides}$, is rolled repeatedly until the "
                          f"running total exceeds ${n}$. What is the expected number of rolls?"),
            "answer": compute(p)}


def hand_space(params):
    """Roll sequences a person would have to weigh, bounded by sides^n."""
    return params["sides"] ** params["n"]
