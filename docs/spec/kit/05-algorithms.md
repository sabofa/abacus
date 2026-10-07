# 05 — Algorithms

**Owns:** the algorithm file format, its roles, the instance format, solutions (show-your-work), versioning, and `algo lint`.
**Defers to:** `06` for where files live, `07` for batches, and spec 3 for how the AI decides what to write.

---

## 1. What an algorithm is

An algorithm is a single Python file: a `META` header plus one or more role functions. The AI writes it. abacus loads, runs, lints, stores and indexes it. An algorithm can be:
- a checker only (`compute` and/or `check`)
- a family (`generate`, plus others)
- anything in between

## 2. The header

```python
META = {
    "id": "nt.last-three-digits-of-tower",       # unique in the library; dots group by area
    "title": "Last three digits of a power tower",
    "summary": "a^(b^c) mod 1000 via CRT on 8 and 125 and Euler's theorem.",
    "roles": ["generate", "compute", "check", "solution"],
    "tags": ["number-theory", "modular-arithmetic"],
    "techniques": ["euler-theorem", "crt"],
    "answer": {"format": "integer", "range": [0, 999]},
    "knobs": {                                    # what generate may vary
        "a": {"int": [2, 99]},
        "b": {"int": [2, 20]},
        "c": {"int": [2, 9], "pattern_knob": False},
    },
    "requires": [],                               # extras beyond core, e.g. "nt", "solve"
    "notes": "",
}
```

- **`tags` and `techniques`** are free-form slugs for the library index. An adapter may map them to a consumer's vocabulary (such as Osmosis tags) at export.
- **Answer formats:** `integer`, `rational`, `expression` (compared with sympy), `choice` (A–E), `tuple`, `set`, `text`. `range` is optional; AIME is `[0, 999]`.
- **`knobs` may be empty.** An algorithm with `generate` and no knobs is a **one-off**: one fixed problem, still stored, linked and checkable like any other (Ben, 2026-10-07: one-offs allowed).
- **`pattern_knob: true`** marks an integer knob along which small cases are meaningful. The `small_case_pattern` signal uses it (`08`).

## 3. Roles

| Role | Signature | Returns |
|---|---|---|
| `compute` | `compute(params) -> answer` | the answer for the given params |
| `check` | `check(params, proposed) -> Evidence` | evidence about a proposed answer, usually by a different route from `compute` |
| `generate` | `generate(rng, knobs) -> Instance` | one instance. It must use only `rng` for randomness |
| `solution` | `solution(instance) -> list[Step]` | worked steps (§5); a stretch goal |
| `demo` | `demo(instance) -> Show` | a show payload for live sessions (`live/05`) |
| `hand_space` | `hand_space(params) -> int` | optional: the size of the naive search a person would face, for the `hand_cases` signal (`08`) |

- **`rng`** is an abacus RNG object wrapping `random.Random` and `numpy.random.Generator`. Both are seeded from the instance seed.
- **`knobs`** holds the values the caller fixed, within the ranges in `META`. `generate` picks the rest.
- **A role may call any kit function.** A `check` that runs `simulate` or `enumerate` is the normal case.

## 4. Instance

```json
{
  "algo": "nt.last-three-digits-of-tower",
  "algo_hash": "3f2a9c1e",
  "kit": "0.1.0",
  "seed": 1739201,
  "params": { "a": 7, "b": 9, "c": 4 },
  "statement": "Find the last three digits of $7^{9^{4}}$.",
  "answer": { "format": "integer", "value": 7 },
  "choices": null,
  "solution": null,
  "demo": null,
  "evidence": [],
  "signals": {}
}
```

- **`statement`** is Markdown with `$…$` LaTeX. The template lives in the algorithm, so writing the statement is the AI's work.
- **`choices`**, when the answer is multiple choice: `[{"body": "…", "correct": true, "note": "…"}]`. How distractors are chosen belongs to spec 3.
- **`evidence`** is filled in by minting (`07`): the results of running `compute` and `check`, plus anything the AI adds.
- **`signals`** is filled in by minting (`08`).
- **`solution`** and **`demo`** hold the rendered outputs of those roles, when present.

## 5. Solutions (show-your-work): deferred

**Deferred (Ben, 2026-10-07: no step-by-step solutions for now).** The `solution` role name stays reserved in the format, but it isn't built. The design below is kept for when it returns.

`solution` returns an ordered list of steps. Each step is a text template plus the values it cites, and **those values are computed in the algorithm from the instance**:

```python
def solution(inst):
    a, b, c = inst.params["a"], inst.params["b"], inst.params["c"]
    e_mod_100 = pow(b, c, 100)
    return [
        step("Work mod 8 and mod 125 separately, then combine by CRT."),
        step("Mod 125: φ(125) = 100, so reduce the exponent {b}^{c} mod 100 to {e}.",
             b=b, c=c, e=e_mod_100),
        # …
    ]
```

- **Why computed values:** every number in a rendered solution comes from computation, so a solution can't contain an arithmetic slip that the answer doesn't.
- **Where it goes:** the solution renders to Markdown and is exported to the Osmosis `explanation` field (`07` §4).
- **Origin:** the idea is borrowed from Forge's solution traces. Unlike in Forge, the wording is the AI's own.

## 6. Versioning

- **`algo_hash`** is the first 8 hex characters of a sha256 over the file's bytes, with line endings normalised. Every instance records it.
- **Editing an algorithm changes its hash.** Old instances keep the hash they were made with.
- **Re-running an old instance** means getting the file as it was at that hash, from the library's git history. `abacus algo show <id> --hash <h>` does that lookup.
- **An algorithm's `id` survives edits.** The library's links point at the `id` (`06`).

## 7. `abacus algo lint`

`abacus algo lint` runs an algorithm through the kit and reports what it finds, as Evidence. Nothing about the result stops the algorithm from being stored. It reports:

- **Header:** whether it's valid, whether the declared roles exist, and whether `requires` is installed.
- **Determinism:** whether `generate` gives identical instances when run twice with the same seed.
- **Agreement:** on k seeds (default 20), it compares `generate`'s answer with `compute(params)` and with `check(params, answer)`, and lists any disagreements.
- **Range:** whether answers fall inside `answer.range`.
- **Spread:** how many distinct answers the k seeds produce. A family that always gives the same answer is flagged.
- **Cost:** time per role.

A file that can't be imported can't be linted. The Python error comes back verbatim.
