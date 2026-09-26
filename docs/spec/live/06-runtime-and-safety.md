# 06 — Runtime and safety

**Owns:** where abacus code runs in spec 2, and where it doesn't.

---

| Where | Runs abacus code? |
|---|---|
| Ben's machine, with an in-environment AI | **yes**: live generation, checks, demos, minting |
| The Osmosis server (puplirserver) | **no** |
| The Osmosis web app (browser) | **no** |
| claude.ai with the connector | **no**: pools and recorded demos only |

- **Osmosis only stores and serves data** (instances, demo payloads). It never imports or runs abacus, and the handoff states this as a constraint.
- **Anything that looks like it needs server execution is covered by pools.** Revisit open question 3, and its isolation options, only when pools stop being enough: for example, if families run through their pools faster than Ben is in-environment to refill them.
- **Budgets apply in-environment too.** The kit's budgets (`../kit/02` §5) apply to `abacus instance` and `abacus demo`. If live generation runs out of budget, it returns no instance, and the AI falls back to the pool with `present_item {family_id}`.
