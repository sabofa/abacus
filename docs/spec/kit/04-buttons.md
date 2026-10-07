# 04 — Buttons

**Owns:** the defined list of buttons, and each one's input and result.
**Defers to:** `03` for the Evidence envelope every button returns.

Every button accepts `budget` (time and memory overrides). Where it makes sense, a button also accepts `seed` and `proposed` (a value to compare against).

**Inputs come in three kinds:**
- *expressions*: strings parsed by sympy against a whitelisted namespace
- *declarative specs*: JSON
- *code*: Python source, marked 🐍 below

**Decision: code inputs instead of a declarative-only language.**
- **Why:** the AI writes Python reliably. A declarative language would cap what buttons can express.
- **When the rival wins:** if buttons ever have to run on a public server. That is open question 3.
- **Consequence:** code inputs are why buttons run only locally (principle 8).

---

## Arithmetic and algebra

### 1. `exact`
Exact evaluation: big integers, rationals, surds, modular arithmetic, number theory.
- **Input:** `expr` (an expression) and an optional `mod`. The namespace includes: `factorint`, `divisors`, `totient`, `mobius`, `primepi`, `isprime`, `nextprime`, `gcd`, `lcm`, `binomial`, `multinomial`, `factorial`, `fibonacci`, `catalan`, `partition`, `legendre`, `jacobi`, `n_order`, `primitive_root`, `discrete_log`, `crt`, `sqrt_mod`.
- **Result:** `value` (the exact string plus LaTeX), and `decimal` (30 digits).
- **Method:** symbolic.

### 2. `cas`
Symbolic algebra.
- **Input:**
  - `op`, one of: `simplify`, `expand`, `factor`, `solve`, `solveset`, `sum`, `product`, `limit`, `series`, `diff`, `integrate`, `apart`, `together`, `roots`, `resultant`, `minimal_polynomial`, `nsimplify`
  - `expr` or `exprs`
  - `vars`
  - optional `assumptions`, e.g. `x: positive integer`
- **Result:** `value` (string plus LaTeX).
- **Notes:** says when sympy returned an unevaluated or conditional result (`Piecewise`, `ConditionSet`).

### 3. `identity`
Are two expressions equal?
- **Input:**
  - `lhs`, `rhs`, `vars`
  - an optional `domain` per variable, e.g. `n: integer >= 1` or `x: real in (0, pi)`
  - `points` (default 50) and `digits` (default 30)
- **Result:**
  - `symbolic`: one of `equal`, `not_equal` or `unknown`, with its source
  - `numeric`: the points tested, the largest |lhs − rhs|, and the first counterexample point if there is one
- **Method:** symbolic and numeric.

## Counting and discrete math

### 4. `enumerate` 🐍
Count the objects in a space that meet a condition.
- **Input:**
  - `space`, one of:
    - `{"product": {"a": [1, 20], "b": [1, 20]}}`
    - `{"permutations": n}` or `{"permutations": [items]}`
    - `{"combinations": {"of": …, "k": k}}`
    - `{"subsets": …}`
    - `{"compositions": {"n": n, "parts": k}}`
    - `{"partitions": n}`
    - `{"words": {"alphabet": "HT", "length": 10}}`
    - `{"lattice_paths": {"to": [m, n], "steps": [[1, 0], [0, 1]]}}`
    - `{"graphs": {"n": 5}}` (labelled graphs)
    - `{"code": "def space(): yield …"}` 🐍
  - `where` 🐍: a Python expression or function over the object's fields.
  - optional `sweep`, e.g. `{"n": [1, 12]}`: repeat for each n. The result becomes a sequence.
  - optional `group_by` 🐍: a key function. The result becomes a distribution instead of a count.
- **Result:** `count` (or `counts` per sweep value, or `distribution`), plus `space_size`.
- **Method:** exhaustive.
- **Flags:** `space_too_large`, when the space is estimated before starting to be bigger than the budget can finish. The button still runs and returns a partial result.

### 5. `sequence`
Find a closed form or recurrence from terms.
- **Input:** `terms` (a list, starting at `offset`), or code 🐍 for `f(n)` with an `n_range`. `holdout` (default 3): how many terms to keep back to test each guess.
- **Result:** `candidates`. Each has:
  - a form: `polynomial`, `linear recurrence`, `rational generating function`, `hypergeometric`, or `known sequence` (from a built-in list: Catalan, Fibonacci, Bell, Motzkin, derangements, …)
  - the expression
  - `fitted_on`: the terms used
  - `held_out`: how many of the held-out terms it predicted correctly
- **Method:** fit.
- **Rule:** a candidate that used every term has `held_out: 0`, and a note saying it is unsupported.
- **Network:** OEIS is queried only when `ABACUS_NETWORK` is on. Results then include A-numbers.

### 6. `counterexample` 🐍
Search for a case that breaks a claim.
- **Input:**
  - `claim` 🐍: a predicate over named variables
  - `domain` per variable: integer ranges, real intervals, or a sampler
  - `mode`: `exhaustive`, `random` or `both`
  - optional `margin` 🐍: for inequalities, `lhs - rhs`, so the closest calls can be reported
- **Result:** `counterexamples` (the first k), `closest` (the smallest margins with their points), `checked`.
- **Method:** exhaustive or sampled.

## Probability and quant

### 7. `simulate` 🐍
Monte Carlo.
- **Input:**
  - `trial` 🐍: a function of an `rng` that returns a number or a bool
  - `trials`: default 10⁶, or as many as the budget allows
  - `seed`
  - optional `vectorized`: the trial takes `rng` and `n` and returns an array
- **Result:** `mean`, `ci95`, `variance`, `trials_run`, and a `histogram` when there are few distinct outcomes. For bools, a probability with a Wilson interval. With `proposed`, `compare` also includes the z-score.
- **Method:** sampled.

### 8. `markov`
Exact Markov chains, optimal stopping and small games.
- **Input:**
  - `op`, one of:
    - `absorb`: absorption probabilities
    - `hitting`: expected steps to reach a set
    - `stationary`
    - `stop`: optimal stopping by backward induction
    - `game`: value and optimal mixed strategy of a zero-sum matrix game
  - the chain, either as an explicit matrix, or as a `start` state plus a `step` function 🐍 (state → `[(next_state, prob)]`, with states discovered by search)
- **Result:**
  - exact rationals when the chain is small enough (said so), floats otherwise
  - for `stop`: the value function and the policy
  - for `game`: the value and the strategies
- **Method:** symbolic (exact) or numeric.

## Continuous math

### 9. `identify`
Turn a decimal into a closed form.
- **Input:** `value` (a string with as many digits as are available, or an expression evaluated to `digits`), and an optional `basis`. The default basis is 1, π, e, √2, √3, √5, ln 2, ln 3, γ, ζ(3) and Catalan's G.
- **Result:** `candidates`, each with its residual and `digits_used`.
- **Notes:** with fewer than 15 reliable digits, candidates are weak, and the result says so.
- **Method:** numeric (PSLQ via `mpmath.identify`).

### 10. `extremum`
Maximise or minimise a function, e.g. to test an inequality.
- **Input:**
  - `f`: an expression, or code 🐍
  - `vars` with bounds
  - `constraints`: equalities and inequalities
  - `goal`: `min` or `max`
  - `method`: `auto`, `grid`, `multistart`, `evolution` or `lagrange`. `lagrange` finds critical points symbolically via `cas`, for small cases only.
- **Result:** the best value, where it occurs, and other near-optimal points (to spot equality cases and symmetry), plus the number of starts run.
- **Method:** numeric search, or symbolic.

### 11. `numeric`
High-precision numerics.
- **Input:**
  - `op`: `integral`, `sum`, `product`, `limit`, `root` or `ode` (an initial value problem, evaluated at a point)
  - the expression or expressions
  - `digits` (default 30)
- **Result:** the value, with its digits stated. A note when convergence is slow or the error estimate is large.
- **Method:** numeric (mpmath).

## Geometry

### 12. `construct`
Build a figure by construction and measure it.

**Status (2026-10-07):** not in the first build. It waits on spec 3's geometry design. Ben put geometry in scope, and the research suggests adding an algebraic prover (Wu / Gröbner) and drawing diagrams from solved coordinates (`../create/01-research-findings.md` §4).
- **Input:**
  - `steps`: construction statements, one per line.
    - Free points take coordinates, or `random` (for testing generality).
    - Where the vocabulary overlaps, it mirrors the construction syntax of Osmosis graph engine v2, so a figure can later be exported as a `graph_spec`. For example: `m = line through P parallel to A-B`, `X = intersect m, n`, `midpoint`, `foot`, `centroid`, `incenter`, `circumcenter`, `orthocenter`, `reflect`, `rotate`, `incircle`, `circumcircle`, `tangent from P`.
  - `queries`: `length A-B`, `angle A-B-C`, `area A-B-C-D`, `ratio`, `collinear`, `concyclic`, `concurrent`, `parallel`, `perpendicular`, `power of P wrt ω`.
  - optional `trials`: rebuild the figure with random free points n times, and report whether each query's value (or truth) stays the same. This is a numeric check of whether a property holds in general.
- **Result:**
  - coordinates
  - query values: exact via sympy when the construction is algebraic and small, otherwise numeric with a tolerance
  - `invariant` for each query across the trials
  - `degenerate` flags: intersections that don't exist, coincident points
- **Method:** symbolic or numeric.

## CS

### 13. `diff_test` 🐍
Run two implementations on random inputs and report where they disagree.
- **Input:**
  - `fast` 🐍, and `reference` 🐍 (usually brute force)
  - `inputs`: a Hypothesis strategy spec, e.g. `integers(1, 100)` or `lists(integers(0, 9), max_size=8)`, or a generator 🐍
  - `examples` (default 500)
  - `edge`: include boundary values (default on)
- **Result:** counts of agreements and disagreements. Each disagreement is shrunk to a minimal failing input (by Hypothesis) and shown with both outputs.
- **Method:** sampled.
- This is the general form of every other check. It is how the AI tests a formula against brute force.

### 14. `growth` 🐍
How does running time grow with input size?
- **Input:**
  - `fn` 🐍
  - `make_input` 🐍: n → an input
  - `sizes`: default doubles from 2⁴ until the budget runs out
  - `repeats` (default 5)
- **Result:** the median timing for each n. The best-fitting class among 1, log n, n, n log n, n², n³ and 2ⁿ, with fit quality and the runner-up.
- **Method:** timed.
- **Notes:** timings are noisy, and fits on small n are unreliable.

---

## The sandbox: `run` 🐍

`run` is not a button. It is free Python with `abacus.kit` imported as `ak`, run under the budget.

- **CLI:** `abacus run file.py`
- **MCP:** the `run` tool. Code goes in; stdout and the value of the last expression come out.
- **Why it exists:** in-environment, the AI can just run Python itself. `run` gives the sandbox to MCP-only clients on the same machine too.

## Changing the list

Adding or removing a button is a spec change here first, then a registry change. A good candidate for promotion is a kind of algorithm the AI keeps writing. `06` §4 records how often each algorithm is run, and `algo search` by technique shows how many similar algorithms exist.
