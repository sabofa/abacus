# 02 — Architecture

**Owns:** the package layout, dependencies, the registry that generates the surfaces, configuration, the execution model and budgets.

---

## 1. Repository

```
abacus/                          github.com/sabofa/abacus
├── pyproject.toml               package `abacus`, console script `abacus`
├── src/abacus/
│   ├── evidence.py              the Evidence envelope (03)
│   ├── budget.py                budgets and the child-process runner (§5)
│   ├── registry.py              button registry: name → function, input schema, result shape, description, default budget
│   ├── kit/                     the functions, one module per area
│   │   ├── exact.py  cas.py  identity.py
│   │   ├── enumerate.py  sequence.py  counterexample.py
│   │   ├── simulate.py  markov.py
│   │   ├── identify.py  extremum.py  numeric.py
│   │   ├── construct.py
│   │   └── difftest.py  growth.py
│   ├── algo/                    the algorithm format: load, lint, run roles (05)
│   ├── library/                 the library store, index, links (06)
│   ├── mint/                    batches: make, review, export, link (07)
│   ├── signals.py               measured signals (08)
│   ├── adapters/
│   │   └── osmosis.py           instance → create_questions payload; Osmosis link targets
│   ├── cli.py                   generated from the registry, plus the algo/library/mint commands
│   └── mcp_server.py            generated from the registry, plus the algo/library/mint/run tools
├── library/                     the default algorithm library (06), tracked in git
├── tests/
└── docs/spec/                   a mirror of Learn spec/abacus (canonical there)
```

`adapters/` is the only place a consumer's name appears. The core never imports an adapter.

## 2. Dependencies

Python ≥ 3.11. Runs on Windows (Ben's laptop) and Linux.

| Kind | Packages |
|---|---|
| Core | sympy, mpmath, numpy, scipy, networkx, hypothesis (shrinking in `diff_test`), mcp (the Python MCP SDK) |
| Extra `abacus[nt]` | python-flint (fast number theory) |
| Extra `abacus[solve]` | z3-solver (constraint search; spec 3 will lean on it) |

- The sandbox may import anything installed.
- The buttons depend on the core only.
- An algorithm declares any extra it needs (`05` §2), and `algo lint` reports a missing one.

## 3. The registry

Each button is registered once, with:

- its name
- a one-paragraph description, written for an AI reader
- a JSON Schema for its input
- the shape of its Evidence `result`
- its default budget

The CLI subcommands, `--help`, the MCP tool list and the list in `04` are all generated from or checked against the registry. A test fails if they differ (`09` §4).

## 4. Configuration

| Setting | Env var | Default |
|---|---|---|
| Library directory | `ABACUS_LIBRARY` | `library/` in the abacus checkout |
| Default time budget | `ABACUS_TIME_S` | 20 s |
| Maximum time budget | `ABACUS_TIME_MAX_S` | 600 s |
| Memory cap | `ABACUS_MEM_MB` | 2048 |
| Network (OEIS) | `ABACUS_NETWORK` | off (open question 4) |
| Examples per result | `ABACUS_MAX_EXAMPLES` | 10 |

## 5. Execution model and budgets

- **Budgets.** Every button call and every algorithm role runs in a **child process**, with a time budget and a memory cap. When the budget runs out, the child is killed. The Evidence comes back with `complete: false`, plus whatever partial result the button had streamed so far (counts so far, trials so far).
- **Memory caps** are enforced where the OS allows: an rlimit on Linux, a job object on Windows. Where a cap isn't enforced, the Evidence says so (`budget.mem_enforced`).
- **This is a runaway guard, not a security boundary.** Code runs as the user, with the user's permissions, exactly as it would if the AI ran Python itself. That is acceptable only because abacus runs where the AI already runs code (principle 8).
- **The sandbox.** Calls from the sandbox (`import abacus`) run in-process by default, because the sandbox is the AI's own Python. `ak.budget(...)` wraps a call in a child process when the AI wants the guard.
- **Seeds.** Every random function takes `seed`. If none is given, one is drawn and reported in the Evidence.
