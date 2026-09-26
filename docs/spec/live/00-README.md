# abacus / live — spec 2

A **family** is an algorithm with a `generate` role. In Osmosis it becomes one item in the schedule, and each time it comes up, Ben sees an instance he hasn't seen before.

An instance reaches him in one of two ways:
- **Live:** an AI that can run abacus generates it on the spot.
- **Pool:** Osmosis draws it from a stock minted ahead of time.

**Demos** come second: the AI running an algorithm to show Ben something during a session.

**Priority (Ben, 2026-09-26):** fresh instances first. Demos are included, at lower priority.
**Status:** spec'd 2026-09-26, not built. **Needs Osmosis changes** ([`handoff-osmosis.md`](handoff-osmosis.md)). Builds on [`../kit/`](../kit/00-README.md).

| File | Holds |
|---|---|
| [`01-overview.md`](01-overview.md) | the model, the two paths, what's out of scope |
| [`02-families-and-pools.md`](02-families-and-pools.md) | family identity, instances in Osmosis, pools, refill |
| [`03-presentation.md`](03-presentation.md) | the live path, the pool path, the connector-only path, grading |
| [`04-scheduling.md`](04-scheduling.md) | what "scheduled per family" means |
| [`05-demos.md`](05-demos.md) | demos, live and recorded |
| [`06-runtime-and-safety.md`](06-runtime-and-safety.md) | where abacus code runs, and where it never does |
| [`handoff-osmosis.md`](handoff-osmosis.md) | what this spec asks of Osmosis |
