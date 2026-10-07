META = {"id": "lint.range", "title": "T", "summary": "S.", "roles": ["generate", "compute"], "answer": {"format": "integer", "range": [0, 5]}}


def compute(params):
    return params["a"]


def generate(rng, knobs):
    a = rng.randint(100, 200)
    return {"params": {"a": a}, "statement": "Find a.", "answer": a}
