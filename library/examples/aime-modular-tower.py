"""AIME-style family: the remainder of a power tower a^(b^c) modulo m.

compute: Euler's theorem (the exponent b^c is reduced modulo phi(m), then one small pow).
check: a different route, a search for the cycle of a^k mod m, then the exact exponent b^c is placed in it.
"""
from abacus.evidence import Evidence, make_compare

META = {
    "id": "examples.aime-modular-tower",
    "title": "Remainder of a power tower",
    "summary": "The remainder of a^(b^c) divided by m, by Euler's theorem; checked by finding the cycle of a^k mod m.",
    "roles": ["generate", "compute", "check", "hand_space", "demo"],
    "tags": ["number-theory", "modular-arithmetic", "aime"],
    "techniques": ["euler-theorem", "residue-cycle"],
    "answer": {"format": "integer", "range": [0, 999]},
    "knobs": {
        "a": {"int": [2, 99]},
        "b": {"int": [2, 20]},
        "c": {"int": [2, 9], "pattern_knob": True},
        "m": {"int": [100, 999]},
    },
    "requires": [],
    "notes": "The answer is a remainder modulo m <= 999, so it fits an AIME answer. generate skips parameters "
             "whose answer is 0 or 1, which would give the problem away.",
}


def _phi(n):
    """Euler's totient, by trial division (n <= 999 here)."""
    result, p = n, 2
    while p * p <= n:
        if n % p == 0:
            while n % p == 0:
                n //= p
            result -= result // p
        p += 1
    if n > 1:
        result -= result // n
    return result


def compute(params):
    a, b, c, m = params["a"], params["b"], params["c"], params["m"]
    e = b ** c
    phi = _phi(m)
    # a^e = a^(e mod phi + phi) (mod m) whenever e >= log2(m), even if gcd(a, m) > 1; a small e is used as it is.
    if e > 12:
        e = e % phi + phi
    return pow(a, e, m)


def _cycle(a, m):
    """(residues of a^0, a^1, ... up to the first repeat, the index where the repeat starts)."""
    seen, seq = {}, []
    r = 1 % m
    while r not in seen:
        seen[r] = len(seq)
        seq.append(r)
        r = r * a % m
    return seq, seen[r]


def check(params, proposed):
    a, b, c, m = params["a"], params["b"], params["c"], params["m"]
    seq, start = _cycle(a, m)
    e = b ** c  # the exact exponent, never reduced by a formula
    r = seq[e] if e < len(seq) else seq[start + (e - start) % (len(seq) - start)]
    ev = Evidence(button="check", result=r == proposed, method="exhaustive",
                  scope=f"cycle of a^k mod m: {len(seq)} residues until the first repeat, then b^c placed in it")
    ev.compare = make_compare(proposed, r)
    return ev


def generate(rng, knobs):
    fixed = {k: knobs[k] for k in ("a", "b", "c", "m") if k in knobs}
    for _ in range(100):
        p = {"a": fixed.get("a", rng.randint(2, 99)),
             "b": fixed.get("b", rng.randint(2, 20)),
             "c": fixed.get("c", rng.randint(2, 9)),
             "m": fixed.get("m", rng.randint(100, 999))}
        answer = compute(p)
        if answer > 1 or len(fixed) == 4:
            break
    a, b, c, m = p["a"], p["b"], p["c"], p["m"]
    return {"params": p,
            "statement": f"Find the remainder when ${a}^{{{b}^{{{c}}}}}$ is divided by ${m}$.",
            "answer": answer}


def hand_space(params):
    """Multiplications a person would do by repeated multiplication: b^c of them."""
    return params["b"] ** params["c"]


def demo(instance):
    p = instance["params"] if isinstance(instance, dict) else instance.params
    a, m = p["a"], p["m"]
    seq, start = _cycle(a, m)
    shown = seq[:12]
    rows = "\n".join(f"| {k} | {r} |" for k, r in enumerate(shown))
    period = len(seq) - start
    more = "" if len(shown) == len(seq) else "\n| ... | ... |"
    body = (f"Powers of ${a}$ modulo ${m}$\n\n| k | ${a}^k \\bmod {m}$ |\n|---|---|\n{rows}{more}\n\n"
            f"The residues repeat with period {period}, starting at k = {start}.")
    return {"kind": "markdown", "body": body}
