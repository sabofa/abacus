META = {
    "id": "misc.one-off-sum",
    "title": "A fixed sum",
    "summary": "One fixed problem with no knobs.",
    "roles": ["generate", "compute"],
    "answer": {"format": "integer"},
}


def compute(params):
    return sum(range(1, 101))


def generate(rng, knobs):
    return {"params": {}, "statement": "Find $1+2+\\cdots+100$.", "answer": compute({})}
