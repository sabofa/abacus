# 09 — Testing

**Owns:** what the build must prove before the kit counts as working.

---

## 1. Known answers, for every button

Each button is tested against results with published values, on every change. Each button needs at least one of these and should grow to three:

| Button | Known answers |
|---|---|
| `exact` | 2¹⁰⁰ mod 1000 = 376; φ(1000) = 400 |
| `cas` | x⁴ + 4 factors as (x² − 2x + 2)(x² + 2x + 2) |
| `identity` | sin²x + cos²x = 1 is `equal`; (x + 1)² vs x² + 1 finds a counterexample |
| `enumerate` | derangements of 5 = 44; lattice paths to (5, 5) = 252 |
| `sequence` | 1, 1, 2, 5, 14, 42, 132 → Catalan, with the held-out terms correct |
| `counterexample` | n² + n + 41 is prime fails first at n = 40 |
| `simulate` | P(two dice sum to 7): the interval contains 1/6 |
| `markov` | expected coin flips to HH = 6 and to HT = 4; rock-paper-scissors has value 0 with the uniform strategy |
| `identify` | 0.5772156649015328606 → γ |
| `extremum` | min of x + 1/x on (0, ∞) is 2, at x = 1 |
| `numeric` | ∫₀^∞ e^(−x²) dx = √π/2, to 30 digits |
| `construct` | the centroid divides each median 2:1, invariant over random triangles; O, G, H collinear (the Euler line), invariant |
| `diff_test` | a deliberately off-by-one `fast` is caught, and shrunk to the minimal failing input |
| `growth` | a nested loop fits n²; `sorted` on random lists fits n log n (with n as an acceptable runner-up) |

## 2. Honesty

- A budget-stopped enumeration returns `complete: false` with a scope saying how far it got.
- A `sequence` candidate fitted on every term carries the zero-holdout note.
- A schema test confirms that no Evidence anywhere has a verdict field (`03` §2 rule 1).

## 3. Determinism

- Every sampled button gives identical Evidence, apart from timings, for the same input and seed.
- `generate` is deterministic, checked by running `algo lint` on the example algorithms.

## 4. The surfaces agree

The registry, the CLI commands, the MCP tool list and the list of buttons in `04-buttons.md` must match.

## 5. Example algorithms, end to end

The repo ships three example algorithms in `library/examples/`:
- a number theory family with an AIME-style integer answer
- a probability family (quant) that uses `simulate` as its `check`
- a checker-only algorithm

The minting flow (make → review → export → link) is tested end to end against a recorded Osmosis `create_questions` response. No live Osmosis instance is needed in tests.

## 6. Both platforms

The suite runs on both Windows and Linux.
