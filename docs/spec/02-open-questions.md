# 02 — Open questions

Numbered. Closed questions stay in the list, marked with their answer.

---

1. **Difficulty.**
   - **Moved into spec 3 (Ben, 2026-10-07):** a well-researched, multi-variable score, not a single number out of 100. Claude researches and decides. The research is in `create/01-research-findings.md` §3. The design is still to come.
   - **Was open:**
     - Which scale? Candidates:
       - contest positions: AMC 12 #1–25, AIME #1–15, quant tiers
       - the AoPS 1–10 scale
       - Osmosis's 1–5
     - Is difficulty predicted at creation and then corrected by observed results?
     - Who records the "why it's hard" breakdown?
   - **Owner:** the difficulty boundary, in its own spec. The kit only records measured signals (`kit/08`).
   - **Ideas on record from the 2026-09-26 brainstorm, not decisions:**
     - Place a problem by comparing it with reference problems, not by absolute rating.
     - Keep predicted and observed difficulty separate, and treat the gap between them as the AI's calibration error.
     - Rate observed difficulty Elo-style from Ben's attempts. Pooling results per family makes ratings workable with a single learner.
     - Keep a breakdown of why a problem is hard, e.g.:
       - how many key ideas it needs
       - how standard its technique is
       - solution length
       - computation load
       - traps
       - how many topics it mixes
2. **Goal 2: creating original problems.**
   - **Owner:** spec 3, "create", which is next.
   - The algorithm format (`kit/05`) already has the `generate` role and `knobs` that spec 3 will use.
   - Spec 3 decides how the AI arrives at a new family. Candidates: techniques, mutations of existing problems, parameter search for clean answers, novelty checks, and distractors for multiple choice.
3. **Server-side execution.**
   - **Open:** should abacus ever run off Ben's machine? Two cases:
     - a hosted MCP server for connector-only sessions
     - live generation during unattended draws
   - **Constraint:** either needs a real isolation layer, because Osmosis's `/mcp` is public through the tunnel. Options:
     - a locked-down subprocess on puplirserver (bubblewrap or nsjail, no network, resource limits)
     - Pyodide in the browser: sympy, numpy, mpmath and networkx are available there; z3 is doubtful
   - **Not in kit or live.** Until this is decided, pools cover the connector path (`live/03`).
4. **Online lookups.**
   - **Open:** may `sequence` query OEIS over the network?
   - **Kit default:** off, with `ABACUS_NETWORK` to turn it on. Ben decides whether it should be on by default.
5. **Live-instance history across Osmosis nodes.**
   - **The problem:** live instances are ephemeral questions, and ephemeral questions don't sync today. Their responses must still count toward the family on every node.
   - **Status:** `live/handoff-osmosis.md` A4 asks for this; Osmosis decides how to do it.
