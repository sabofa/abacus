# abacus / create — spec 3 (brainstorming; not a spec yet)

How an AI comes up with original problems, at the level of AMC 12, AIME, quant interviews and the math major, using the kit.

**Status (2026-10-07):** brainstorming.
- Ben has answered the constraint questions (below).
- Three research passes are done ([`01-research-findings.md`](01-research-findings.md)).
- **Next:** propose 2–3 approaches, then design the sections with Ben.

---

## Ben's answers (2026-10-07)

| # | Question | Answer |
|---|---|---|
| 1 | What are created problems for? | **All of it:** drilling, mock contests, filling bank gaps. He has ~2000 AMC 12 problems but wants something more adaptive, and problems the AI makes itself at AMC/AIME level |
| 2 | Must every problem be a family? | **No.** One-offs are allowed |
| 3 | How original? | **New to the world.** A problem may grow from one base problem, or from several problems combined |
| 4 | Who decides what to make? | **The tutoring AI**, judging from all of Ben's data. Where he struggles, it finds the edge. Where he's proficient, it tests how deep that goes. His existing bank alone can only test so much |
| 5 | The tutor's authoring gate and its "drills are past-paper only" rule | **Ignore them for now.** The tutor is "too tight on itself" and will be reworked |
| 6 | Difficulty | **A well-researched, multi-variable score, not a single number out of 100.** Claude researches and decides |
| 7 | A written by-hand solution with each problem | **Not for now.** Claude meant a written human solution path; the risk it guarded against becomes a difficulty dimension instead (hand-solvability) |
| 8 | Scope | **Everything:** proofs, interpretive quant, geometry. The one exclusion is step-by-step solutions |
| 9 | Ben's feedback on quality | **Ben isn't an expert mathematician.** Judging quality without him is the design's job |
| 10 | A blind second solver | **Yes, but it belongs to the AI, not the tool.** Spec 3 therefore has two halves: abacus tools, and the AI's own method |
| 11 | Volume and cost | **Tracked in the project inventory** (Learn `build/osmosis/PROJECTS.md`) |

## Carried constraints

- **From the abacus principles** (`../01-principles.md`): tool, not gate; evidence honestly scoped; multi-project; code runs only where the AI already runs code.
- **From the kit and live specs:** a created problem is an abacus algorithm. If it has knobs, it can become a family; with no knobs, it's a one-off.
- **The difficulty score is the tutor's control surface.**
  - To find the edge: change one dimension at a time and hold the rest steady.
  - To test depth: push one dimension up on a strong area.
- **Problems must be new to the world.** So a novelty check is needed against Ben's bank and wider sources. Disguised copies slip past plain similarity checks (`01` §2).

## Ben's answers to B1–B5 (2026-10-07, relayed by the "Osmosis projects inventory" session)

| # | Answer |
|---|---|
| B1 | **Keep all 14 buttons.** The buttons get built. `construct` still waits on spec 3's geometry design |
| B2 | **No Lean or local prover for now**: "wait until i get a better computer (next year)". Spec 3 designs proof checking without them, with a slot to add them later |
| B3 | **A one-time expert calibration.** Ben's precalc professor rates one set of 10–20 problems, once. Spec 3 treats it as a one-time calibration set; after that, Ben's own ratings carry it. Still to do: a one-page rating sheet. It mixes real past-contest problems and kit-made ones, unlabelled, at AMC 10/12 and AIME level, with a short rubric (well-posed? right difficulty? interesting rather than mechanical? would you use it?), and takes 30–45 minutes |
| B4 | **OEIS is off by default**, as built |
| B5 | **Osmosis keeps `tech:`** (a rendering requirement). Learn's technique tags and abacus use `technique:`. The Learn bank's tags get renamed only if spec 3 or export needs them, and the rename is noted when it happens |

## Open questions for Ben (all answered above)

| # | Question | Blocks |
|---|---|---|
| B1 | The kit's 14-button list hasn't been reviewed. Should any button be cut or added? | Nothing yet. The first build covers 13 of the 14 (all but `construct`); a cut button would be dropped |
| B2 | May Lean 4 + mathlib (several GB) and a local prover model (~5.5 GB VRAM at 8B) be installed on Ben's PC, for proof-problem evidence? | Proof-problem verification in spec 3 |
| B3 | Is there anyone with competition-math experience (a coach, a math club, a UIUC professor) who could rate 20–30 problems now and then? The research found this is the only ground truth for validating every other quality signal | The quality design in spec 3 |
| B4 | Should `sequence` look up OEIS over the network by default? (open question 4) | Only `sequence`'s network path; the build is offline by default |
| B5 | The `tech:` prefix means "technique" in the Learn bank and "rendering requirement" in Osmosis. Which wins? | How spec 3 targets techniques, and tags on export |

## Files

| File | Holds |
|---|---|
| `00-README.md` | this: status, Ben's answers, open questions |
| [`01-research-findings.md`](01-research-findings.md) | the three research passes of 2026-10-07, with sources, and what they point to |
