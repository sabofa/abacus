# abacus — spec

A math toolkit for AI. It does for an AI working on competition and quant math what a calculator does for a person. The AI reaches for it when it wants to. It computes what thinking alone can't do reliably. It never tells the AI what to do.

**Status (2026-09-26):** spec'd, not built. These specs came out of the Osmosis brainstorming session with Ben on 2026-09-26. The code will live at github.com/sabofa/abacus. That repo's `docs/spec/` is a mirror of this folder; **this folder is canonical** (Learn `LAYOUT.md` §7).

## Why it exists

AI is good at problems with a straightforward answer. It is weak at two things Ben's work needs:

- **Checking an interpretive answer** without relying on its own reasoning.
- **Making original problems** at the level of AMC 12, AIME and quant interviews.

Ben's context is a math major, AMC 12 and AIME, and the quant track (Learn `tracks/quant/`). That is past the point where a standard alg 2 → precalc → calc sequence and its existing material are enough.

## Two goals, three specs

| Goal | Spec | Folder | Status |
|---|---|---|---|
| 1. Help the AI check its own answers | **Kit**: the Python package, 14 buttons and a sandbox, the algorithm format, the library of algorithms and its links, minting batches into Osmosis | [`kit/`](kit/00-README.md) | spec'd, draft |
| (builds on 1) | **Live**: a fresh instance every time a question comes up, pools, per-family scheduling, demos | [`live/`](live/00-README.md) | spec'd, draft |
| 2. Help the AI come up with original problems | **Create**: how the AI invents problems using the kit; it also takes over difficulty (Ben, 2026-10-07) | [`create/`](create/00-README.md) | **brainstorming**: Ben's answers and the research are in; approaches next |

**Difficulty is deliberately left open.** That covers how hard a problem is, on what scale, and whether it is predicted or observed. It is its own boundary ([`02-open-questions.md`](02-open-questions.md) #1). The kit only records measured signals ([`kit/08-signals.md`](kit/08-signals.md)).

## Files

| File | Holds | In force |
|---|---|---|
| `00-README.md` | this index | yes |
| [`01-principles.md`](01-principles.md) | the rules every abacus project follows, and the glossary | draft, for Ben's review |
| [`02-open-questions.md`](02-open-questions.md) | what's undecided, and who decides it | yes |
| [`kit/`](kit/00-README.md) | spec 1 | draft, for Ben's review |
| [`live/`](live/00-README.md) | spec 2, including `handoff-osmosis.md` | draft, for Ben's review |
| [`create/`](create/00-README.md) | spec 3, brainstorming: Ben's answers, research findings, open questions | not a spec yet |

## Relationships

- **Osmosis** is the first consumer, not the owner.
  - The kit needs nothing from Osmosis: minting uses the existing `create_questions`.
  - Live needs a small Osmosis change, set out in [`live/handoff-osmosis.md`](live/handoff-osmosis.md).
- **Forge** (`question genorate/` on Ben's laptop, July 2026) is a different project. It is a locked-down pipeline for school-level questions, in which the LLM is never a source of truth.
  - abacus borrows a few technical pieces: seeded, regenerable instances with full provenance; solution traces; and a feature vector stored with each question.
  - It does **not** borrow Forge's invariants, its closed kernel, or its difficulty rubric.
- **Tutor**: abacus's first principle points the same way as the tutor's ruling of 2026-09-22, "the ledger, not the gate".
