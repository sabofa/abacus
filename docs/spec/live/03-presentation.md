# 03 — Presentation

**Owns:** how an instance gets in front of Ben on each path, and how it's graded.

---

## 1. The live path: an in-environment AI in a session

```
abacus instance <algo> [--seed S] [--knob …] [--check]
    → one instance as JSON, with its solution and demo if the algorithm has those roles
create_questions {ephemeral: true, session_id, family_id, …the instance payload}
present_item {question_id}
await_item_outcome
grade: written → grade_response, using the instance's answer; mc → automatic
optional: a demo (05)
```

- **What's missing today:** everything above already exists in Osmosis except `family_id`.
- **Checking first:** the AI may run any check on the instance before presenting it, but whether to is its call. `--check` runs the algorithm's `compute` and `check` roles and attaches their Evidence.

## 2. The pool path: Osmosis serves the instance

- **Unattended draws** (daily draws, templates, `tag_query`): the family is one draw unit, and Osmosis picks the instance (`02` §3).
- **In a session:** the AI calls `present_item {family_id}` (handoff A3), and Osmosis picks the instance. An in-environment AI can use this too, for example when it would rather not generate.

## 3. The connector-only path: claude.ai with the Osmosis connector

Here the AI can't run abacus.
- **It can:** present families from their pools (`present_item {family_id}`), grade against the stored answer, and replay recorded demos (`05` §2).
- **It can't:** generate, check or mint.
- **What carries over:** the refill list tells the next in-environment session what needs minting.

## 4. Grading

- **`mc` instances:** graded automatically, as today.
- **`written` instances, with an AI present:** the AI grades with `grade_response`, using the instance's stored answer. In-environment, it can add any abacus check it wants, e.g. `identity` to confirm that an equivalent form of an expression answer is correct.
- **`written` instances, with no AI present** (unattended pool draws): Ben grades himself, as today.
  - **Ask A6** is exact-answer auto-grading for integers, rationals and normalised strings, so an AIME-style answer grades itself.
  - Without A6 the pool path still works; it just relies on self-grading.
