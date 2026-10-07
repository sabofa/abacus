import random

META = {"id": "lint.nondet", "title": "T", "summary": "S.", "roles": ["generate", "compute"], "answer": {"format": "integer"}}


def compute(params):
    return params["a"]


def generate(rng, knobs):
    a = random.randint(0, 10**9)  # ignores the seeded rng
    return {"params": {"a": a}, "statement": "Find a.", "answer": a}
