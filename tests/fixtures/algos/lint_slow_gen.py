import time

META = {
    "id": "lint.slow-gen",
    "title": "Slow generate",
    "summary": "generate takes a third of a second per call, so a short budget runs out part way.",
    "roles": ["generate", "compute"],
    "answer": {"format": "integer"},
    "knobs": {"n": {"int": [1, 99]}},
}


def compute(params):
    return params["n"]


def generate(rng, knobs):
    time.sleep(0.3)
    n = knobs.get("n", rng.randint(1, 99))
    return {"params": {"n": n}, "statement": "Find n.", "answer": n}
