"""Checker-only algorithm: how many integers from 1 to N have a digit sum divisible by d.

compute: brute force over the range.
check: a digit DP over the decimal digits of N, a different route that does not visit the integers one by one.
There is no generate role: this file checks a count someone else produced.
"""
from abacus.evidence import Evidence, make_compare

MAX_N = 2_000_000  # brute force stays fast below this

META = {
    "id": "examples.sum-of-digits-check",
    "title": "Count of integers with digit sum divisible by d",
    "summary": "The number of integers in 1..N whose digit sum is divisible by d, by brute force; "
               "checked with a digit DP.",
    "roles": ["compute", "check"],
    "tags": ["number-theory", "counting", "digit-dp"],
    "techniques": ["digit-dp", "brute-force"],
    "answer": {"format": "integer"},
    "knobs": {},
    "requires": [],
    "notes": "params are {'N': int >= 1, 'd': int >= 1}; N is at most 2,000,000.",
}


def _params(params):
    n, d = params["N"], params["d"]
    if not (isinstance(n, int) and isinstance(d, int) and 1 <= n <= MAX_N and d >= 1):
        raise ValueError(f"need integers 1 <= N <= {MAX_N} and d >= 1, got N={n!r}, d={d!r}")
    return n, d


def compute(params):
    n, d = _params(params)
    return sum(1 for k in range(1, n + 1) if sum(map(int, str(k))) % d == 0)


def _dp_count(n, d):
    """Integers in 1..n whose digit sum is 0 mod d, by a digit DP (0 is counted by the DP, then removed)."""
    tight_r = 0  # residue of the digit sum of n's own prefix
    loose = {}  # residue -> number of prefixes already below n's prefix
    for x in map(int, str(n)):
        nxt = {}
        for r, w in loose.items():
            for dig in range(10):
                key = (r + dig) % d
                nxt[key] = nxt.get(key, 0) + w
        for dig in range(x):
            key = (tight_r + dig) % d
            nxt[key] = nxt.get(key, 0) + 1
        loose = nxt
        tight_r = (tight_r + x) % d
    total = loose.get(0, 0) + (1 if tight_r == 0 else 0)  # 0..n with digit sum 0 mod d
    return total - 1  # remove the integer 0


def check(params, proposed):
    n, d = _params(params)
    r = _dp_count(n, d)
    ev = Evidence(button="check", result=r == proposed, method="exhaustive",
                  scope=f"digit DP over the {len(str(n))} digits of N={n} for d={d}, tracking the digit sum mod d")
    ev.compare = make_compare(proposed, r)
    return ev
