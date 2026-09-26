# 01 — Overview

**Owns:** the model for spec 2, and its boundaries.

---

## 1. The model

- **A family is one thing to learn:** a technique in a problem shape. Its algorithm makes as many instances as needed.
- **Ben is scheduled on the family, not the instance** (Ben, 2026-09-26). Every instance he answers counts toward the family (`04`).
- **An instance reaches Ben by one of two paths:**
  - **Live.** An AI in-environment generates a fresh instance when it's time to present one, with a new seed. The supply is unlimited, and an instance effectively never repeats.
  - **Pool.** Osmosis serves an unseen instance that was minted earlier. This works when no AI is present (daily draws) and when the AI can't run code (claude.ai with the connector).
- **Both paths are always available.** In Ben's words, the AI should be allowed "to really do whatever it wants with this tool". The pool is also the fallback whenever live generation isn't possible.

## 2. Why both paths

- **Only live generation** gives unlimited fresh instances.
- **Only the pool** works without running code.
- **Running abacus on the Osmosis server** would make live generation work everywhere. But `/mcp` is public, so it would need real isolation first (open question 3). Pools remove the need.

## 3. Out of scope

- Server-side execution (open question 3).
- Interactive demos with sliders. They depend on graph engine v2's `@param`, which isn't built yet (`05` §3).
- How families are invented (spec 3).
- Difficulty (open question 1).
- Osmosis's internal design for families. `handoff-osmosis.md` states what's needed and how to tell it works, and suggests a design, but Osmosis decides.
