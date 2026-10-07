META = {"id": "lint.disagree", "title": "T", "summary": "S.", "roles": ["generate", "compute"], "answer": {"format": "integer"}}


def compute(params):
    return params["a"] + 1


def generate(rng, knobs):
    a = rng.randint(0, 100)
    return {"params": {"a": a}, "statement": "Find a.", "answer": a}
