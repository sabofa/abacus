# 08 — Signals

**Owns:** the measured, non-subjective facts recorded about each instance, for a future difficulty model.
**Status (2026-10-07):** on hold. Ben moved difficulty into spec 3 ("create") as a researched, multi-variable score. These signals will be revised to fit that design, and they aren't built until then. Minting keeps a no-op signals step in their place.
**Defers to:** open question 1, which covers the scale, the prediction, the observed rating, and any score. **The kit computes no difficulty score and no band.**

---

## 1. Why record them now

The lesson from Forge (its spec 05 §7): store the features behind a difficulty judgement with each question. A later model can then be fitted, and refitted, without regenerating anything.

Competition difficulty mostly lives in how hidden the key idea is, and that can't be measured. These signals are the part that can.

## 2. The signals

| Signal | What it measures | How |
|---|---|---|
| `answer_digits` | how big the answer is | from `answer` |
| `answer_in_statement` | whether the answer, or a trivial combination of two given numbers (sum, product, difference), appears in the statement | parse the numbers in `statement` |
| `max_intermediate_digits` | the largest number in the worked solution | from the `solution` values, if present |
| `solution_steps` | how many steps the solution has | from `solution`, if present |
| `hand_cases` | how big the naive search space is that a person would face | the optional `hand_space(params)` role (`05` §3) |
| `small_case_pattern` | whether small cases give the answer away: can `sequence`, run on small values of the pattern knob, predict this instance's answer? | `sequence` with holdout, when a knob is marked `pattern_knob` (`05` §2) |
| `closed_form` | whether `compute` is exact or symbolic (true), or only numeric or sampled (false) | the `method` in compute's Evidence |
| `compute_ms`, `check_ms` | how much time the algorithm's own roles take | timed |

**Absent means "not measured", never zero.**

## 3. Where they go

Signals go on each instance (`signals`) in its batch file. Batch files are tracked in git (`07` §2), so the signals survive until there is a difficulty model to use them.

Osmosis has no field for signals yet. Adding one belongs to the difficulty boundary.
