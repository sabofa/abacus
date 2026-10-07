META = {
    "id": "lint.const",
    "title": "Always seven",
    "summary": "A family with a knob whose answer never changes.",
    "roles": ["generate", "compute"],
    "answer": {"format": "integer"},
    "knobs": {"n": {"int": [1, 9]}},
}


def compute(params):
    return 7


def generate(rng, knobs):
    n = knobs.get("n", rng.randint(1, 9))
    return {"params": {"n": n}, "statement": f"Find $7$ (the number {n} is ignored).", "answer": 7}
