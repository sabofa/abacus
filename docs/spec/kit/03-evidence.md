# 03 — Evidence

**Owns:** the result envelope every button returns, and the rules for being honest about what a result shows.

---

## 1. Shape

```json
{
  "button": "enumerate",
  "result": { "count": 1247 },
  "method": "exhaustive",
  "scope": "a, b, c in [1, 20]: 8000 tuples checked",
  "complete": true,
  "precision": null,
  "examples": [ { "a": 1, "b": 2, "c": 3 } ],
  "compare": { "proposed": 1248, "computed": 1247, "equal": false },
  "flags": [],
  "notes": [],
  "seed": null,
  "budget": { "time_s": 0.4, "limit_s": 20, "stopped": false, "mem_enforced": true },
  "kit": "0.1.0",
  "input": { "…": "the normalised input, so the call can be repeated exactly" }
}
```

| Field | Meaning |
|---|---|
| `result` | the button's answer; its shape is per button (`04`) |
| `method` | `exhaustive`, `sampled`, `symbolic`, `numeric`, `search`, `fit` or `timed` |
| `scope` | one line saying what was covered |
| `complete` | false if a budget stopped the run. `result` is then partial, and `scope` says how far it got |
| `precision` | digits, a tolerance or a confidence interval, when the method is numeric or sampled |
| `examples` | witnesses: objects counted, counterexamples found, inputs where two implementations disagree. Capped by `ABACUS_MAX_EXAMPLES` |
| `compare` | present only when the caller passed `proposed`. A plain comparison of two values, nothing more |
| `flags` | things abacus noticed (principle 3), each as `{code, message}` |
| `notes` | caveats the AI should read. Examples: float precision; sympy returned a conditional result; fewer holdout terms than asked for |
| `seed`, `kit`, `input` | what's needed to reproduce the call (principle 4) |

## 2. Rules

1. **No verdict field.** There is no `correct`, `pass`, `valid` or `score` field anywhere. `compare.equal` states whether two values are equal. It is not a judgement of the AI.
2. **Scope is never empty, and never claims more than was done.** A bounded search is never reported as "true". Its scope states the bound.
3. **Sampled results carry an interval. Numeric results carry their precision.**
4. **Partial results are labelled.** `complete: false` always comes with a scope saying where the run stopped.
5. **A symbolic "yes" names its source.** For example, an identity check reports `sympy simplify → 0`. It also notes that sympy saying "unknown" doesn't mean "no".
6. **Compact by default.** Examples are capped. `--full` on the CLI, or `full: true`, returns everything.
