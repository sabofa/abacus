from abacus.evidence import Evidence, make_compare

META = {
    "id": "nt.power-mod",
    "title": "a to the b mod m",
    "summary": "Residue of a^b modulo m by fast exponentiation; checked by repeated multiplication.",
    "roles": ["generate", "compute", "check", "hand_space"],
    "tags": ["number-theory", "modular-arithmetic"],
    "techniques": ["fast-exponentiation"],
    "answer": {"format": "integer", "range": [0, 49]},
    "knobs": {
        "a": {"int": [2, 99]},
        "b": {"int": [2, 20], "pattern_knob": True},
        "m": {"int": [2, 50]},
    },
    "requires": [],
    "notes": "",
}


def compute(params):
    return pow(params["a"], params["b"], params["m"])


def check(params, proposed):
    r = 1
    for _ in range(params["b"]):
        r = r * params["a"] % params["m"]
    ev = Evidence(button="check", result=r == proposed, method="exhaustive",
                  scope="a^b mod m by repeated multiplication, b steps")
    ev.compare = make_compare(proposed, r)
    return ev


def generate(rng, knobs):
    a = knobs.get("a", rng.randint(2, 99))
    b = knobs.get("b", rng.randint(2, 20))
    m = knobs.get("m", rng.randint(2, 50))
    p = {"a": a, "b": b, "m": m}
    return {"params": p, "statement": f"Find the remainder of ${a}^{{{b}}}$ divided by ${m}$.",
            "answer": compute(p)}


def hand_space(params):
    return params["b"]
