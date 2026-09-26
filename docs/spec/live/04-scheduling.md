# 04 — Scheduling

**Owns:** what "scheduled per family" means.
**Defers to:** Osmosis for the scheduler itself.

---

## 1. The rule

Anywhere Osmosis schedules or draws by question lineage today, **a family counts as one unit, the equivalent of one lineage.** Its history is **every response to any of its instances**: pool or live, across all sessions and all nodes.

## 2. Against today's Osmosis

From a read of the Osmosis code on 2026-09-26:

**Draws** (daily draws, templates) work per lineage, in three ways. For a family, each one applies to the family as a whole:

| Today, per lineage | For a family |
|---|---|
| Eligibility | the family is one eligibility entry |
| A recency exclusion (`daily_recent_lineage`) | recency excludes the whole family |
| `weak_weighted`, from the lineage's last 3 response scores | uses the family's last 3 responses, across all its instances |

**The retention schedule** is keyed by `identity_key` (a tag slug or a node key), not by question.
- A family carries tags and node keys like any question, so it takes part without any change.
- Separately, that schedule doesn't yet advance when results come in. That is an Osmosis gap, not this spec's.

**Eligibility:** a family can be drawn only if it can serve an instance, meaning its pool isn't empty.

## 3. Repeats

A repeated instance (served because the pool ran out) is marked on its attempt. Scoring and later analysis can then discount it.
