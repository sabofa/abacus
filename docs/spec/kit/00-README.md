# abacus / kit — spec 1

The kit is the Python package: its fixed buttons, the free sandbox, the algorithm format, the library of algorithms with its links to consumers, and minting batches of instances into Osmosis. Its purpose is **goal 1: help the AI check its own answers.** It also defines the formats that live generation (spec 2) and problem creation (spec 3) build on.

**Status:** spec'd 2026-09-26, not built. **Needs nothing from Osmosis.** Read [`../01-principles.md`](../01-principles.md) first.

| File | Holds |
|---|---|
| [`01-overview.md`](01-overview.md) | scope, non-goals, the three surfaces, how the AI uses the kit |
| [`02-architecture.md`](02-architecture.md) | package layout, dependencies, the registry, configuration, the execution model and budgets |
| [`03-evidence.md`](03-evidence.md) | the result envelope every button returns, and the honesty rules |
| [`04-buttons.md`](04-buttons.md) | the 14 buttons and the `run` sandbox |
| [`05-algorithms.md`](05-algorithms.md) | the algorithm file format, roles, instances, solutions, versioning, `algo lint` |
| [`06-library-and-links.md`](06-library-and-links.md) | where algorithms live, how they're found, reversible links |
| [`07-minting.md`](07-minting.md) | generate a batch, review it, export it, link it |
| [`08-signals.md`](08-signals.md) | measured difficulty signals (the difficulty model itself is open) |
| [`09-testing.md`](09-testing.md) | what the build must prove |
