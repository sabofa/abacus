# Ledger: abacus kit, first build

**Plan:** `docs/plans/2026-10-07-kit-build.md`. **Branch:** `kit/build`. **Rules:** Learn `build/osmosis/AGENT-SYSTEM.md`.

**Status legend:** `[ ]` not started · `[~]` in progress · `[x]` done and reviewed READY.

## Tasks

| Task | Status | Commits | Review |
|---|---|---|---|
| T1 Foundation | [ ] | | |
| T2 Surfaces | [ ] | | |
| T3 Buttons: arithmetic and algebra | [ ] | | |
| T4 Buttons: counting and discrete math | [ ] | | |
| T5 Buttons: probability and quant | [ ] | | |
| T6 Buttons: continuous math | [ ] | | |
| T7 Buttons: CS | [ ] | | |
| T8 Algorithm format | [ ] | | |
| T9 Library | [ ] | | |
| T10 Minting and examples | [ ] | | |

## Subtasks

Each subtask's goal, files, test and acceptance line are in the plan. Copy them in here as each task starts, and tick them off as they finish.

- [ ] T1.1  - [ ] T1.2  - [ ] T1.3 (risky: own review)
- [ ] T2.1  - [ ] T2.2  - [ ] T2.3
- [ ] T3.1  - [ ] T3.2  - [ ] T3.3
- [ ] T4.1  - [ ] T4.2  - [ ] T4.3
- [ ] T5.1  - [ ] T5.2
- [ ] T6.1  - [ ] T6.2  - [ ] T6.3
- [ ] T7.1  - [ ] T7.2
- [ ] T8.1  - [ ] T8.2  - [ ] T8.3
- [ ] T9.1  - [ ] T9.2  - [ ] T9.3
- [ ] T10.1 - [ ] T10.2 - [ ] T10.3

## Deltas from the spec

Record each one here, and in Learn `build/abacus/DELTA-FROM-SPEC.md` once that folder exists.

- `jsonschema` is a core dependency, used for validating button input. kit/02 §2 doesn't list it.
- On Windows, memory caps aren't enforced (`mem_enforced: false`). kit/02 §5 allows this.
- Not built: `construct`, signals, the `solution` role (see the plan's Scope).

## Minors carried

(none yet)
