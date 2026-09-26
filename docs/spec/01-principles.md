# 01 — Principles and glossary

**Owns:** the rules every abacus project follows, and the vocabulary.

---

## Principles

1. **A tool, not a gate.** abacus never accepts, rejects, blocks, scores or grades the AI's work, and it never writes a verdict into a consumer. It computes and reports. The AI decides what a result means.
2. **Evidence, honestly scoped.** Every result says how it was obtained and what it covered. For example: "counted exhaustively for n ≤ 12", "10⁶ trials, 95% interval", "30 digits", "stopped at the time budget". A result never claims more than its method supports. **Brute force is evidence, not proof.**
3. **Flags are information.** When abacus notices something, it says so and does nothing else. Examples: two derivations disagree, two instances collide, a search was cut short.
4. **Reproducible.** Everything random takes a seed. Every stored result records the seed, the algorithm's content hash and the kit version, so re-running it gives the same output.
5. **Multi-project.** The core knows nothing about any consumer. Translating to a consumer's formats is done by an adapter. Osmosis is the first adapter, not the owner.
6. **Python. One kit, three surfaces.** Everything is a Python function in one kit. The same functions can be reached three ways: as a library (import), a CLI (`abacus`), and an MCP server (`abacus mcp`). **A button is a promoted algorithm.** When the AI keeps writing the same kind of algorithm, that algorithm becomes a button.
7. **Sized for an AI's context.** Output is compact by default: a result, its scope and a few examples. More is available on request.
8. **Code runs where the AI already runs code.** In these specs, abacus runs on the machine the AI works on. That is about 90% of use: in-environment, e.g. Claude Code. Nothing runs abacus code on a public server. That is an open question (`02` #3), not a default.
9. **The encoding caveat is stated, not hidden.** A computation confirms the answer to the problem *as encoded*. If the encoding is wrong, abacus confidently confirms the wrong answer.
   - The docs and the MCP tool descriptions tell the AI this.
   - The kit makes it cheap to encode the problem twice, independently, and compare. `diff_test` does this, and so does an algorithm's `compute` role checked against its `generate` role.

---

## Glossary

| Term | Meaning |
|---|---|
| **kit** | the Python package `abacus`: every function below |
| **button** | a kit function on the fixed, defined list (`kit/04`), with a schema, exposed on all three surfaces |
| **sandbox** | free Python with the kit imported, for anything the buttons don't cover |
| **evidence** | the standard result envelope every button returns (`kit/03`) |
| **algorithm** | a Python file in the library with a header and one or more roles (`kit/05`) |
| **role** | one job an algorithm can do: `compute`, `check`, `generate`, `solution`, `demo` |
| **instance** | one concrete problem produced by an algorithm's `generate`: statement, answer, seed, params |
| **family** | an algorithm with a `generate` role, used as one schedulable item in a consumer (`live/02`) |
| **batch** | a file of instances made in one run, reviewed by the AI, then exported to a consumer (`kit/07`) |
| **mint** | make a batch ahead of time |
| **pool** | a family's minted instances, stored in the consumer and served when nobody can generate live (`live/02`) |
| **library** | the directory of algorithms, with their links, batches and index (`kit/06`) |
| **link** | a reversible record tying an algorithm to an item in a consumer, e.g. `osmosis:q:<lineage_id>` |
| **signal** | a measured, non-subjective fact about an instance, recorded for the future difficulty model (`kit/08`) |
| **adapter** | code that translates abacus formats to one consumer's formats |
| **consumer** | a project that uses abacus output; Osmosis is the first |
| **in-environment** | the AI runs where it can execute code, e.g. Claude Code. The opposite is **connector-only**: claude.ai chat with just the Osmosis connector |
