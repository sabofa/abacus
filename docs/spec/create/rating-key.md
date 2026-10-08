# Rating key (do not show to the rater)

The answer key for [`rating-sheet.md`](rating-sheet.md) (printable: `rating-sheet.pdf`). Draft, for Ben's check before printing. Keep this file away from the professor: it says which problems are real and which are kit-made.

**Set:** 14 problems. 8 real past-contest problems, 6 kit-made. Order on the sheet is mixed so neither kind is grouped (real: 1, 3, 5, 6, 8, 10, 12, 14; kit: 2, 4, 7, 9, 11, 13).

## The key

"Difficulty guess" is mine (a contest slot it should feel like). For real problems it also shows the real slot. The kit's own difficulty signals are "on hold (difficulty design pending)", so the kit guesses are judged by hand, which is what the professor's "Feels like" column will test.

| # | Source | Answer | Difficulty guess | Topic |
|---|---|---|---|---|
| 1 | real: AMC 10B 2012 #13 (`amc10B_2012_p13`) | 40 | easy, AMC 10 #12 to #14 | algebra, rates |
| 2 | kit: `examples.dice-expected-value@0adccd7b`, knobs n=3, sides=6, batch seed 201 (instance seed 763040281) | 343/216 | easy, AMC 10 #12 to #15. See doubt A | probability, expected value (quant) |
| 3 | real: AMC 12A 2018 #14 (`amc12A_2018_p14`) | 31 (x = 4/27, p + q) | mid-easy, AMC 12 #14 | algebra, logarithms |
| 4 | kit: `examples.aime-modular-tower@c69218a3`, knobs a=3, b=2, c=4, m=500, batch seed 101 (instance seed 690596709) | 221 | easy, AMC 10 #15 / AMC 12 #12 | number theory |
| 5 | real: AMC 12B 2015 #13 (`amc12B_2015_p13`) | 6 (angle chase gives AC = BC) | easy-mid, AMC 12 #12 to #14. No figure needed | geometry |
| 6 | real: AMC 10A 2022 #14 (`amc10A_2022_p14`) | 144 | mid, AMC 10 #14 to #18 | counting |
| 7 | kit: `examples.aime-modular-tower@c69218a3`, knobs a=12, b=17, c=8, m=990, batch seed 103 (instance seed 2073674200) | 342 | hard, AIME #6 to #9. gcd(12, 990) = 6, so plain Euler fails | number theory |
| 8 | real: AMC 12A 2016 #23 (`amc12A_2016_p23`) | 1/2 | mid. Printed at slot 23 but a classic; may feel like AMC 12 #14 to #18 | probability, geometric |
| 9 | kit: `examples.dice-expected-value@0adccd7b`, knobs n=5, sides=4, batch seed 202 (instance seed 2304105832) | 2869/1024 | mid, AMC 12 #17 to #20, by recurrence | probability, expected value (quant) |
| 10 | real: AMC 12B 2003 #18 (`amc12B_2003_p18`) | 31 (x = 7^5 11^8, so 5 + 8 + 7 + 11) | mid, AMC 12 #16 to #18 | number theory |
| 11 | kit: `examples.aime-modular-tower@c69218a3`, knobs a=11, b=12, c=4, m=700, batch seed 102 (instance seed 3713772813) | 561 | mid-hard, AIME #3 to #6 (CRT over 4, 25, 7) | number theory |
| 12 | real: AMC 12B 2021 #23 (`amc12B_2021_p23`) | 55 (p/q = 6/49) | hard, AMC 12 #23 / AIME #8 to #10 | probability |
| 13 | kit: `examples.dice-expected-value@0adccd7b`, knobs n=7, sides=6, batch seed 203 (instance seed 3252715728) | 776887/279936 | mid-hard by method, bash-heavy by hand. See doubt A | probability, expected value (quant) |
| 14 | real: AMC 12B 2014 #23 (`amc12B_2014_p23`) | 1024 | very hard, AIME #10 to #13 | number theory |

Reading the kit rows: the `abacus` source form is `abacus <algorithm id>@<hash> seed <seed>`. The hash is of the algorithm file as in `library/examples/` on branch `kit/build` (HEAD `9b893fa`; both example files are unchanged from there). The "batch seed" is what `mint make --count 1 --seed S` takes with the knobs fixed; the "instance seed" is what `generate` then ran with (derived from the batch seed). To re-make an instance, run `abacus mint make <id> --count 1 --seed <batch seed> --knob a=... ` with an `ABACUS_LIBRARY` holding the examples at their id paths.

Topic mix of the sheet: probability 5 (three expected-value problems, two real), number theory 5, algebra 2, counting 1, geometry 1.

## How each answer was checked

- **Real problems.** Taken from Ben's problem bank, the `problems` table of the tutor's `var/tutor.db` on puplirserver (`/srv/learn/tutor/var/`; a read-only copy was taken). Source dataset `kaggle-aimo/amc_filtered`, answers repaired from the official LIVE archive key (`verified_by = 'oracle'`, see Learn `build/tutor/BANK.md`). All eight rows are `oracle`-verified, with their official letter (1 B, 3 D, 5 B, 6 E, 8 C, 10 B, 12 A, 14 C), and I recomputed each by an independent route:
  - 1: 1 / (1/24 - 1/60) = 40.
  - 3: x = 4/27 satisfies both logarithms.
  - 5: angle chase, then checked chord lengths on a circle.
  - 6: exhaustive count of the pairings of 1 to 14.
  - 8: Monte Carlo 0.4998 (the classic value 1/2).
  - 10: exponent congruences, 5 and 8.
  - 12: sum of 6 (1/8)^(a+d) over a, d >= 1, which is 6/49.
  - 14: exact sum of the binomials mod 2017.
- **Kit problems.** Each was made by `mint make` (its own `compute` and `check` roles agree, no flags), and recomputed by routes that do not use the kit's code:
  - Towers: Python `pow(a, b**c, m)` with the full exponent.
  - Dice: the tail-sum formula E[N] = sum over k >= 0 of P(S_k <= n), by an exact distribution over Fractions. The kit's seeded Monte Carlo is consistent with each value (2: mean 1.5793; 9: 2.7893; 13: 2.7857; inside the 95% intervals).

## Kit coverage limit

The kit-made problems come from the two example families only (`aime-modular-tower`, `dice-expected-value`). So they cover only number theory and probability. The calibration says nothing about kit-made algebra, counting or geometry, because none exist yet. All kit statements are the family's single template, with only the numbers varying, and the professor's ratings of Q3 (interesting) on them are really ratings of the template.

## Doubts and things to check before printing

- **A. The dice family has a closed form when n <= sides.** Problem 2 (n=3, sides=6) is (7/6)^3 and the answer is just that. Problem 13 (n=7 > 6) has no such shortcut and a six-digit denominator, so it is hard to type or check by hand and the difficulty is in the arithmetic, not the idea. Both are honest kit output; the professor may well rate them low on Q3 and Q4, and that is the signal.
- **B. The tower family says only "Find the remainder when a^(b^c) is divided by m".** It is a bare computation, with no story or twist. Expect low Q3. The `a`, `b`, `c`, `m` were fixed by me (the generator was not left to draw them), to get the answer spread (221, 561, 342) and a non-coprime case (problem 7); the generator itself skips answers 0 or 1 only when not all four knobs are given, and I avoided those answers by hand.
- **C. No AIME problems were available.** Ben's bank is AMC 10/12 only (`amc_filtered`, no AIME). The "AIME level" end of the sheet is therefore the hardest real AMC 12 items (12, 14) and the kit tower problems (answer 0 to 999, the AIME format), not real AIME problems.
- **D. Mixed answer forms.** There are no choices on any problem. Every problem has an "Answer format" line: "an integer from 0 to 999" (real and kit alike, wherever it holds: 1, 3, 4, 5, 6, 7, 10, 11, 12), "a common fraction in lowest terms" (2, 8, 9, 13), "a nonnegative integer" (14, whose answer 1024 is outside 0 to 999). Real AMC problems have choices, so the real items lost theirs (the bank does not store them in the statement; the options are in `choices_json`). All eight real items are self-contained as free response.
- **E. Question 2.** "Right difficulty for its level" needs a level. The sheet asks the rater to write the contest and position under "Feels like" and judge Q2 against that. I read "once, 'Roughly which contest and position does this feel like?'" as one such field per problem. If Ben meant a single question for the whole sheet, move it.
- **F. Bank text normalisation.** The bank's statements had lost some punctuation to the scrape (a space before every comma and full stop after a closing dollar sign, some missing question marks). Beyond that the text is as stored. The only changes from the stored text, all formatting:
  - 3: removed stray spaces, including `\tfrac {p}{q}` to `\tfrac{p}{q}`; added the missing `?`.
  - 5: removed a stray space; added the missing `?`.
  - 12: "independantly" to "independently" (the stored typo); `....` to `\ldots`; removed a stray space before the closing parenthesis.
  - 14: removed stray and doubled spaces.
  - 1, 6, 8, 10: unchanged.
  The kit statements are exactly the family's own text (checked by string equality).
- **G. Licence.** The bank has no cleared licence (Learn `build/tutor/BANK.md`, "The licence question"). This sheet is for one professor's private calibration, which is the same personal-use act as the bank itself. Do not circulate it beyond that.
- **H. Possible tells.** The kit statements are short and uniform in wording (every tower item starts "Find the remainder when"; every dice item is one template). A sharp rater may notice that without trying. I cannot remove it without making the kit items less representative.
- **I. The PDF.** Two sides of one letter sheet, set by headless Edge with KaTeX math (see `00-README.md`). The answer key is not in it.
