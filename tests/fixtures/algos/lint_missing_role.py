META = {"id": "lint.missing", "title": "T", "summary": "S.", "roles": ["generate", "compute", "check"], "answer": {"format": "integer"}}


def compute(params):
    return params["a"]


def generate(rng, knobs):
    a = rng.randint(0, 100)
    return {"params": {"a": a}, "statement": "Find a.", "answer": a}
