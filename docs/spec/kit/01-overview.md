# 01 — Overview

**Owns:** what the kit is for, what it isn't, and how an AI reaches it.
**Defers to:** `../01-principles.md` for the rules.

---

## 1. What the kit does

- **Checks.** The AI has an answer and wants evidence for it. It can:
  - count by brute force
  - simulate
  - turn a decimal into a closed form
  - test an identity at random points
  - search for a counterexample
  - measure a figure by construction
  - compare a clever solution against a brute-force one
- **Stores** the algorithms the AI writes, so a check or a generator can be re-run, found later, and linked to the questions it produced.
- **Mints** batches of problem instances from an algorithm. The AI reviews a batch and exports it as questions.

## 2. Not in the kit

- **Deciding whether the AI is right.** See principle 1.
- **How the AI invents a new problem.** That is spec 3.
- **Difficulty scoring.** Open question 1. The kit records signals only (`08`).
- **Formal proof, e.g. Lean.** Nothing here proves a statement "for all n". The kit's evidence is bounded, and says so.
- **Running on a server.** See principle 8.
- **Presenting anything in Osmosis.** That is spec 2.

## 3. Three surfaces, one kit

| Surface | For | Form |
|---|---|---|
| Library | the sandbox: free Python | `import abacus.kit as ak` |
| CLI | in-environment calls from a shell, and scripts | `abacus <button> '<json>'` prints the Evidence as JSON on stdout; `--pretty` for people |
| MCP | any MCP client on the same machine (Claude Code, Claude Desktop) | `abacus mcp` (stdio). One tool per button, plus the library, mint and `run` tools |

All three are generated from one registry (`02` §3), so a button's schema, its CLI help and its MCP tool description can't drift apart.

## 4. How the AI is expected to use it

This is not a procedure. The AI uses what it wants, when it wants. Typical uses:

- **Quick check.** The AI solved a counting problem by reasoning. It runs `enumerate` on a small case and compares.
- **Two derivations.** It writes a brute-force version of the problem and runs `diff_test` against its formula.
- **Pattern.** It computes small cases with an `enumerate` sweep, then uses `sequence` to find a closed form, with holdout terms kept back to test the guess.
- **A family.** It writes an algorithm with `generate` and `compute`, runs `abacus algo lint`, mints 40 instances, reads the batch, drops what it doesn't like, exports the rest, and links them.

Where it applies, each MCP tool description includes principle 9 (the encoding caveat) in one sentence.
