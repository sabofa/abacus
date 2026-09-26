# Handoff — Osmosis (from abacus)

**To:** Osmosis core (github.com/sabofa/Osmosis). **From:** abacus spec 2 (`live/`), 2026-09-26.
**Status:** proposed. Osmosis decides its own design.

abacus is a math toolkit that an AI uses on Ben's machine. Spec 2 makes a **family** into one schedulable item in Osmosis. A family is an abacus algorithm that generates problem instances, and Ben sees a fresh instance each time the family comes up.

This handoff asks for the smallest change that makes that possible. **Spec 1 (the kit) needs nothing from you:** it exports ordinary `create_questions` payloads.

---

## Constraints

- **Osmosis never runs abacus code**, on the server or in the browser. Everything arrives as data over MCP.
- **Osmosis never imports abacus.** The only thing shared is `abacus_ref`, an opaque string.
- **Additive.** Nothing changes for questions, draws or grading that don't involve a family.

## Asks

### A1: family records (must)
- **Ask:** create, list, get and retire families. A family has: title, tags, node_keys, `abacus_ref` (the algorithm id), created_at, retired.
- **Accepted when:** an AI can create a family over MCP, and list it with its instance counts.

### A2: instances belong to a family (must)
- **Ask:** `create_questions` accepts `family_id`, for both ordinary (pool) and ephemeral (live) questions. Family instances can't be drawn on their own, and don't count separately in bank counts.
- **Accepted when:**
  - a pool instance never appears in a draw except through its family
  - a live, ephemeral instance is still retired at `end_session`

### A3: the family is the draw unit (must)
- **Ask:**
  - Eligibility, the recency exclusion and `weak_weighted` treat the family as one lineage, using all its instances' responses.
  - When a family is drawn, serve an instance: never-presented first (oldest-minted first), then the least recently presented.
  - Mark a repeat on its attempt.
  - `present_item` accepts `family_id`.
- **Accepted when:**
  - a daily draw that includes a family serves an unseen instance
  - `weak_weighted` for the family reflects responses to both pool and live instances

### A4: family history everywhere (must)
- **Ask:** responses to live (ephemeral) instances count for the family on every node.
- **Why it's needed:** ephemeral questions don't sync today (`sync.ts`). Either sync family instances, or record family results in something that does sync.
- **Accepted when:** a live instance answered on the laptop node shows up in the family's history on the canonical node.

### A5: low-pool signal (should)
- **Ask:** families whose unseen pool count is at or below a threshold (default 3) are visible to the AI, e.g. in `bootstrap` or as a `list_families` filter.
- **Accepted when:** an AI can list the families that need refilling in one call.

### A6: exact-answer auto-grading (should)
- **Ask:** written items can declare an answer format (integer, rational, normalised string), and the answer is compared on submit. This is useful beyond abacus.
- **Accepted when:** an AIME-style instance in an unattended draw grades itself.

### A7: recorded demos (could)
- **Ask:** a question can carry a show payload (`markdown` or `graph`), and the AI can present it as a show.
- **Accepted when:** a connector-only session can replay a pool instance's demo.

### A8: provenance value (could)
- **Ask:** the `provenance` enum gains `abacus_generated`.

## A suggested design (not binding)

- A `family` table, plus a nullable `question.family_id` foreign key.
- **Draw eligibility:** standalone latest-version lineages, plus families with at least one instance they can serve. Per-family stats come from grouping responses through `question.family_id`.
- **`present_item {family_id}`:** pick an instance by the A3 rule, then follow the existing attempt path.
- **MCP tools:**
  - `create_family`
  - `list_families`: with counts (instances, unseen, attempts, last 3 scores) and a `needs_refill` filter
  - `retire_family`
  - `family_id` added to `create_questions` and `present_item`

## What abacus does on its side

- Produces family instances as `create_questions` payloads with `family_id`.
- Records a link `osmosis:family:<family_id>` in its library.
- Generates live instances in-environment, and mints pools when the AI asks.

It never calls Osmosis directly; the AI does.
