import time

META = {
    "id": "lint.hang",
    "title": "Compute hangs",
    "summary": "generate is fine; compute never returns, so only a killable child can stop lint.",
    "roles": ["generate", "compute"],
    "answer": {"format": "integer"},
    "knobs": {"n": {"int": [1, 99]}},
}


def compute(params):
    while True:
        time.sleep(0.05)


def generate(rng, knobs):
    n = knobs.get("n", rng.randint(1, 99))
    return {"params": {"n": n}, "statement": "Find n.", "answer": n}
