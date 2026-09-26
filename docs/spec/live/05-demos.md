# 05 — Demos

**Owns:** the AI showing Ben something computed, during a session. This has lower priority than fresh instances (Ben, 2026-09-26).

---

## 1. Live demos

An algorithm's `demo(instance)` role returns a show payload, in one of the kinds Osmosis `present_show` already accepts:

```json
{"kind": "markdown", "body": "| n | count |\n|---|---|\n| 1 | 1 |\n…"}
{"kind": "graph", "spec": "…a graph_spec…"}
```

- **In-environment:** `abacus demo <algo> --instance <file>` produces the payload, and the AI passes it to `present_show`. **This works with today's Osmosis. No change is needed.**
- **Typical demos:**
  - a table of small cases
  - a simulation's running mean converging on the exact value
  - a histogram of outcomes
  - a construction drawn as a figure (from `construct`, once graph engine v2 constructions exist)
- **Demos not tied to an instance:** the AI may run any button and present the result as a show. `abacus show <evidence.json>` renders any Evidence as a Markdown show payload.

## 2. Recorded demos

When a pool instance is minted, its `demo` output is recorded on the instance (`../kit/07` §2).

- **The ask:** so that the connector-only path can replay a recorded demo, Osmosis stores it with the instance and lets the AI present it (handoff A7, lower priority).
- **Until A7 lands,** recorded demos are available only in-environment, from the batch file.

## 3. Later: interactive demos

Dragging a parameter and watching the answer change needs graph engine v2's `@param`, which is designed but not built. When it lands, a `demo` can return a `graph_spec` with `@param` bindings. Nothing in this spec blocks that.
