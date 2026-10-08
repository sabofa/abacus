# Ledger: abacus kit, first build

**Plan:** `docs/plans/2026-10-07-kit-build.md`. **Branch:** `kit/build`. **Rules:** Learn `build/osmosis/AGENT-SYSTEM.md`.

**Status legend:** `[ ]` not started · `[~]` in progress · `[x]` done and reviewed READY.

## Tasks

| Task | Status | Commits | Review |
|---|---|---|---|
| T1 Foundation | [x] | f7555a4 c5833dd a4e8c1e; fixes in 93d40ce, 76ae73b | READY after 2 rounds (Sonnet) |
| T2 Surfaces | [x] | 93d40ce c4e2f5b a030c95; fixes bf16f47, f92e19f | 2 rounds (Sonnet); round 2 (the thread-safe flush) has a deterministic test but no re-review: the cap was reached |
| T3 Buttons: arithmetic and algebra | [x] | 8c6e573; fixes fda71bc, e7eb791 | READY after 2 rounds (Sonnet). Round 1: 1 critical (parser string-eval) + 3 important. A payload-hunting re-review was cut short by a safety classifier; the hardening round (e7eb791) added no-attribute-access, no sympify of strings in compare, validated identity vars. Final defensive re-review: READY |
| T4 Buttons: counting and discrete math | [x] | a9790c2; fix 6697a1b | READY after 1 round (Sonnet). Round 1 had 3 important; the re-review confirmed all fixed |
| T5 Buttons: probability and quant | [x] | 0c137db; fix a61e8d0 | READY after 1 round (Sonnet). Round 1 had 1 critical (float-to-fraction snap turned 3.3e-14 into 0 and hitting returned inf) + 4 important; re-review confirmed all fixed |
| T6 Buttons: continuous math | [~] **OPEN FINDING (capped)** | c8f2826; fixes ead8c67, 7793247 | 2 rounds (Sonnet). Round 1: 2 critical (divergent sums and infinite integrals reported as converged to 30 digits). Round 2 re-review: all confirmed fixed except **one Important regression: a narrow integrand far from the origin returns a confident wrong value.** `numeric(integral, exp(-(x-5000)**2), -oo..oo, digits=20)` gives value 0, reliable_digits 20, complete True, no flag (true value sqrt(pi)). Same for (x-1000) over -oo..oo and (x-5000) over 0..oo. Cause: geometric splits stop at 2^11 / 3^7 so the peak is never sampled. The old code returned no_convergence for these. Suggested fix: flag `zero_from_unsampled_tail`/withhold the value when an infinite-range integral comes out ~0 with an error far below the integrand's scale, or extend the reach to ~1e4. Cap reached: needs Ben's go-ahead or the next chat |
| T7 Buttons: CS | [x] (cap reached) | cc0cba8; fixes e764074, 0fdaeb1 | 2 rounds (Sonnet). Round 1: 6 important. Round-1 re-review: growth fixes held; 2 important left (stale in-flight claim after the first 50 inputs named the wrong function; growth dropped-half spike unflagged), both fixed in round 2 (0fdaeb1) with tests but no re-review |
| T8 Algorithm format | [x] | 522003c ae8f26a 1005b75; fixes 42e4c64, c127ca0 | READY after 2 rounds (Sonnet) | 522003c ae8f26a 1005b75; fixes 42e4c64 | Round 1 (Sonnet): NOT READY, 1 critical + 6 important. Re-review of 42e4c64: all fixed; 1 important left (mixed tuple/list equality) + minors, sent to round 2 (the cap). The T9 review checks the round-2 commit |
| T9 Library | [x] | 0f76ae3 077bbc2 2b1cd50; fixes 7e42f2b, dd46621 | 2 rounds (Sonnet). Round 1's 4 important + 3 extras were READY on re-review. Round 2 (dd46621: child stdout → stderr, stale-lock race, startup_timeout usage) has tests but no re-review: the cap was reached |
| T10 Minting and examples | [~] T10.1–T10.2 done; T10.3 built (665bd85), review round 1 NOT READY, fixer running | 7fc2653 cf32ab6; fixes 7a23fac, 8af1006 | 2 rounds (Sonnet). Round 1 had 2 important; its re-review left 1 (the link-fallback test). Round 2 (8af1006) has tests but no re-review: the cap was reached |

## Subtasks

Each subtask's goal, files, test and acceptance line are in the plan. Copy them in here as each task starts, and tick them off as they finish.

- [x] T1.1  - [x] T1.2  - [x] T1.3 (risky: own review)
- [x] T2.1  - [x] T2.2  - [x] T2.3
- [x] T3.1  - [x] T3.2  - [x] T3.3
- [x] T4.1  - [x] T4.2  - [x] T4.3
- [x] T5.1  - [x] T5.2
- [x] T6.1  - [x] T6.2  - [x] T6.3
- [x] T7.1  - [x] T7.2
- [x] T8.1  - [x] T8.2  - [x] T8.3 (1005b75)
- [x] T9.1  - [x] T9.2  - [x] T9.3 (2b1cd50)
- [x] T10.1 - [x] T10.2 (cf32ab6) - [~] T10.3 (665bd85)

## Deltas from the spec

Record each one here, and in Learn `build/abacus/DELTA-FROM-SPEC.md` once that folder exists.

- `jsonschema` is a core dependency, used for validating button input. kit/02 §2 doesn't list it.
- On Windows, memory caps aren't enforced (`mem_enforced: false`). kit/02 §5 allows this.
- Not built: `construct`, signals, the `solution` role (see the plan's Scope).

## Minors carried

- budget: numpy ints are rejected as time_s/seed; an invalid cfg.time_s default is reported as the caller's bad_input; an overrun inside the grace window carries no flag.
- sandbox: `sys.__stdout__` writes bypass capture (it's not a security boundary); `abacus --pretty exp '{}'` (an option before the button) gives exit 2.
- The full suite takes ~45–60 s because of spawned children (~3 s each); look at it once the buttons land.
- Process: one agent's `git add -A` swept another agent's T1 fixes into 93d40ce. Stage paths only (now in AGENT-SYSTEM.md).
- T8 review minors (logged, not fixed): lint feeds `check` only the right answer (a perturbed one would test it); demo has no positive test; lint doesn't flag a non-int `hand_space`.
- T8 re-review minor (logged): lint never calls ctx.progress, so a lint killed at the hard limit loses the checks that had already finished (result=None).
- make_compare on two numpy arrays: equal=False (pre-existing; round 2's normal form may cover it).
- T10.1 judgement (for the T10 review): mint make runs roles in-process for speed, so an over-budget role is flagged `incomplete` but not killed. The calling button's child budget bounds the whole run.
- T9 review minors (logged): links.add accepts a negative seed, an unknown algo and duplicates; algo show lacks the last lint result; a META id that disagrees with its path still loads in show.
- T10 review minors (logged): concurrent `mint_review` calls can lose decisions (no lock); usage.jsonl gets one row per role call (304 for a 100-instance batch), which inflates most_used; mint/surface.py descriptions name Osmosis fields (documentation only).
- T10 re-review minor (logged): mkstemp makes batch files 0600 on POSIX (doesn't matter on Windows).
- T10 round-2 leftover (logged): sympify can still be slow on other pathological answers (e.g. factorial(10**7)); answer keys run outside any per-role budget.
- T9 round-2 notes: the stale-lock break re-links a fresh lock with os.link (lost on filesystems without hard links); the race test fakes the stale check; there's no real two-thread stale test.

## Deltas added during the build
- Internal (non-spec) buttons are registered so that MCP lists them: run, algo_lint, algo_run, algo_search, algo_show, link_add, link_rm, link_find, mint_make, mint_review, mint_export (`INTERNAL` in tests/test_surfaces_agree.py). They also appear in the CLI `buttons` listing.
- Every budget child sends stdout to stderr at the fd level (protects the MCP stdio stream); `run` captures its own.
- mint make runs roles in-process for speed. The button's child budget bounds the whole batch.
- Usage is recorded from budget.call (algo_run), once per role run.

## Stop point, 2026-10-07 (abacus chat)
Everything not blocked is built and reviewed: T1, T2, T8, T9, T10.1, T10.2. Full suite: 562 passing at dd46621.
Blocked: T3–T7 (buttons) and T10.3 (the example algorithms call buttons). Both wait on Ben's B1.
- T3 review minors (logged): Domain.sample float-bound edge (~5e-18 outside); finite integer domains stay `unknown` after exhaustive agreement.
- B1 answered 2026-10-07: keep all 14 buttons (T3–T7 + T10.3 unblocked; construct waits on spec 3). B2: no Lean/prover for now. B3: one-time expert rating of 10–20 problems (rating sheet still to prepare). B4: OEIS off. B5: Osmosis keeps tech:, abacus uses technique:.
- T4 round-1 minors (logged): DESCRIPTION strings don't mention the new result keys (capped, unlisted_unsupported, margin_errors, capped_at_k).
- A test in tests/test_kit_algebra.py (test_exact_mod_of_a_huge_power_finishes_without_building_it) failed once during the T4 fixer's full run, while the T3 hardening fixer was mid-edit. Re-check when the hardening commit lands.
- A safety classifier cut short a hostile-payload review of the parser. Don't re-run payload-hunting reviews; use defensive code review and ordinary tests.
- T4 re-review minors (logged): `capped_at_k` is set even when the k-th counterexample was the last point; two child-process test assertions still accept "before any progress".
- T3 final-review minors (logged): `Matrix` is in the parser whitelist but `exact` now rejects it (not a sp.Basic): allow sp.MatrixBase or drop Matrix; the mod fast path has no tests for 0**0, mod 1 and negative exponents (hand-checked right); **mint/make.py:121 still calls sympy.sympify on an answer string** (behind _costly + try/except): route it through parsing.parse_expr; `__x` is a legal identifier for identity `vars`.
- T5 re-review minors (logged): VECTOR_CHUNK=65536 can't be interrupted (wide vectorized trials overshoot the budget, ~524MB per chunk); one test asserts only truthiness for Rng.sample.
- T6 round-2 minors (logged): `exp(-(x-200)**2)` over -oo..oo and similar are convergent but flagged no_convergence (honest false rejection); `exp(-(x-50)**2)` reports 18 digits, true error 10^-17.82 (about 0.2 digit over-stated).
- A T6 builder ran `pkill -f python` once in Git Bash to stop a hung script: it could have killed other agents' Python processes. Agents are now told not to kill processes.
- T10.3 review round 1 (NOT READY): 4 important: Osmosis field names leaked outside the adapter (mint/link.py, mint/surface.py); a different response for the same batch left stale links; the prompt fallback guessed between look-alike instances without a flag; the dice example's answer had a 15-digit denominator. The reviewer also proposed replacing the dice example's `compare.equal = |z|<=3` with a generic `check_agrees` helper (equal → consistent → result bool) used by `mint make` and `lint`. The fixer was told to adopt it.
