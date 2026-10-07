# 01 — Research findings (2026-10-07)

There were four research passes, all run by agents for the spec-3 brainstorm. The first covered AI problem generation (2026-09-26). The other three covered difficulty, judging quality without an expert, and verification for proofs, interpretive quant and geometry (2026-10-07).

**Caveats:**
- Many 2026 sources are preprints or workshop papers.
- "Not found" means the agent searched and found nothing. It does not mean the thing doesn't exist.
- The synthesis at the end of each section is Claude's, not the sources'.

---

## 1. Generating problems (2026-09-26)

**Methods:**
- **Concept composition.** Combine skills or concepts drawn from seed problems: MathScale 2024, KPDDS 2024, MATH² 2024.
- **Concept → designer rationale → problem.** PromptCoT 2025; its 2.0 version's answers rest only on majority votes.
- **Mutate upward or downward.** WizardMath / Evol-Instruct 2023.
- **Forward deduction plus traceback, geometry only.** AlphaGeometry 2024, TongGeometry 2024 (3 of its problems were used in real olympiads).
- **Self-play.** R-Zero 2025. Verifier-backed generation, 2026, adds an independent verifier because setter/solver loops reward-hack.
- **Check a reference solution against brute force.** AutoCode 2025. This is the kit's `compute`/`check`/`diff_test`.

**Failure modes:**
- **Harder problems break more.** R-Zero's answer-key accuracy fell from 79% to 63% as difficulty rose.
- **AI review catches little.** In MATH², AI filters passed only 18–46% of candidates, humans passed 11–66% of those, and 62% of the problems humans accepted still needed edits.
- **Models don't spot broken problems.** They rarely recognise an unsolvable problem, and GPT-5 "proved" false statements 29% of the time (BrokenMath 2025).
- **Novelty is rare.** Only about 23% of AutoCode's problems were judged novel. Even 8 of 30 real AIME 2025 problems had near-copies online (MathArena 2025).
- **Outputs converge.** Mode collapse happens within and across models, and higher temperature doesn't fix it ("Artificial Hivemind", 2025).

**Problem composers** (Evan Chen, "From the Author's Side", 2021):
- Start from a core idea. Working **backwards** (hide a solution idea) gives slick solutions but dull statements. Working **forwards** (explore and mutate a statement) gives the reverse.
- Then specialise, copy-edit (quantifiers, degenerate cases) and fit the answer format.
- The aim is one "aha", with little computation.
- Brown & Walter's "what-if-not" (1983): list a problem's attributes and negate each one.

## 2. Judging quality without an expert

- **Per-item psychometrics need many examinees.** Discrimination and point-biserial are undefined with one learner. LLMs simulating examinees reached only a 0.231 rank correlation with human discrimination (2026).
- **Comparative judgement.**
  - Reliability of .70 needs 10–14 comparisons per item; .90 needs 26–37 (Verhavert 2019).
  - Non-expert judges were unreliable, peers better, experts best (Jones & Alcock 2014).
  - Adaptive pairing can inflate reliability statistics (Bramley 2015).
- **LLM judges.**
  - On problem quality, o3 against experts correlated 0.07 for quality and 0.11 for novelty, while LLMs agreed with each other at about 0.72 (AutoCode 2025). A panel of models probably shares the same error.
  - Self-preference bias argues for judges from a different model family.
  - No calibration study was found for math-problem quality.
- **Solve-rate ladders.** Difficulty and "difficulty gain" were the best predictors of human-rated quality, at r up to 0.60 in programming (AutoCode). The pitfall: a broken problem also looks hard (benchmark label-error studies 2024–2025).
- **Learning-outcome quality** needs many students per item. At most, it can be measured at the family level, with randomised held-out probes.
- **Blind mixing.** Judges classified AI versus human problems at chance (50.9%). So mixing is a good bias control, but it isn't a quality measure.
- **Setters' stated criteria:** clarity, then quality, then a difficulty curve; no "know it or don't"; one key idea; no tedium (Chen 2020; Trang 2026; Vandervelde 2008). These are essays, not validated measures.
- **The only ground truth found:** periodic ratings of 20–30 items by an expert. Every other signal is unvalidated for this domain without it (open question B3).

## 3. Difficulty

- **Feature-based prediction explains about 20–55% of item difficulty** (LLTM on arithmetic about 20%; PISA competency demands just over 50%). No figures exist for competition math. A creation-time vector is therefore a **prior with wide variance, not a measurement**.
- **Expert blind spots.** Teachers' difficulty predictions deviated systematically from real student data (Nathan & Koedinger 2000). An AI's predictions will have blind spots too.
- **The AoPS scale** is ordinal, coarse and mostly positional. Po-Shen Loh's LIVE already applies Elo to AMC/AIME problems (no validation published).
- **LLM signals versus expert difficulty.** Log-probability and length metrics reach r ≈ 0.35–0.40, and fall under 0.10 on Putnam problems (2026). Prompting an LLM directly for difficulty gave r ≈ 0. Simulated classrooms fitted with IRT gave r ≈ 0.75–0.82, but only on K-12 multiple choice.
- **Few data.**
  - Elo with a decaying step size, U(n) = a/(1+bn), works well when the learner changes (Pelánek 2016).
  - The Additive Factors Model, logit p = student + Σ(β_k + γ_k·attempts_k), fits the knowledge-component structure (Cen, Koedinger & Junker 2006).
  - For item families: a multilevel model per family; choose the family, then a random clone (Glas & van der Linden 2003).
- **Insight.** Difficulty has separable causes: perceptual, knowledge, process (Kershaw & Ohlsson 2004). That supports a vector. Fixation is learner-relative: the familiar method blocks the better one, even in experts (Bilalić 2008).

**Candidate dimensions found:**
- prerequisite knowledge-component load (strongest evidence)
- breadth of areas combined
- solution length
- computation load
- insight / representational change
- misdirection (learner-relative)
- representation (symbolic, verbal, proof)
- baseline LLM solve rate (covariate only)

**What the research points to (Claude's synthesis, for the design):**
- A predicted vector at creation serves as the prior.
- An observed per-learner model on top: per-dimension skills that drift over time, with families pooling data.
- Choose items at a predicted success rate of about 0.5–0.7, varying one dimension at a time.
- Track residuals per dimension to catch the predictor's blind spots.

## 4. Verification beyond computed answers

**Proofs:**
- **Autoformalization is unreliable.**
  - Statement accuracy is about 45% at undergrad level (EMNLP 2025).
  - Benchmark formalisations were 28% false and another 27% unfaithful (ICML-W 2026).
  - Statements that compile are often unfaithful (miniF2F revisited 2025; "Beyond Compilation" 2026, a 3–29 point gap).
- **Provers as a filter.** Proving a statement's negation is a usable falsity filter (FormalMATH 2025). Goedel-Prover-V2 8B scores 84.6% on miniF2F and runs locally in about 5.5 GB VRAM.
- **LLM judges of proofs.** A three-judge jury with reconciliation came close to human grading (MathArena USAMO 2026). Unanimous judges still passed about 15% wrong proofs (2026). Self-bias is large.
- **No measured catch rate** was found for counterexample search or small-case checks.

**Interpretive quant:**
- **Fermi estimates** are scored by log error, or by a proper interval score such as Winkler's (FermiEval 2025).
- **Market-making** is computable under an explicit counterparty model: expected P&L, Glosten–Milgrom zero-profit quotes, Kelly fractions. Practice tools score process, not P&L, because P&L is dominated by luck (TraderMath).
- **Not computable:** whether the assumed market model is realistic.

**Geometry:**
- **Algebraic provers.** Wu's method solved 15 of 30 IMO-AG problems, 21 combined with deductive search (2024). Newclid is an open-source engine with GeoGebra input (2024). GeoGebra's ProveDetails (Gröbner) proves equalities only; it can't handle inequalities or point ordering.
- **AI-drawn diagrams compile only about 36% of the time** (2026). Render diagrams from solved coordinates instead, and check claims numerically over random configurations.
