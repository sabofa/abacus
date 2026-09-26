# 02 — Families and pools

**Owns:** family identity, instances in a consumer, pools, and refill.
**Defers to:** `../kit/05` (algorithms and instances), `../kit/07` (minting), and `handoff-osmosis.md` (how Osmosis stores all this).

---

## 1. Identity

- **In abacus,** a family is identified by its algorithm `id`.
- **In Osmosis,** it's a family record (handoff A1) that carries `abacus_ref = <algo id>`.
- **The link** `osmosis:family:<family_id>`, with kind `family`, goes in the abacus library (`../kit/06` §3).

**Which record is authoritative for what:**
- Osmosis's family record is authoritative for membership and scheduling: which instances belong to the family, and what has been seen.
- The abacus link is authoritative for the algorithm index.

`abacus link find osmosis:family:<id>` and Osmosis's `abacus_ref` should agree. If they don't, the AI fixes the link. Nothing breaks either way.

**Editing the algorithm doesn't create a new family.**
- Instances record `algo_hash`, so instances made before and after an edit can be told apart.
- A change big enough to be a different thing to learn gets a new algorithm id and a new family. That's the AI's call.

## 2. Instances in Osmosis

Each instance becomes an Osmosis question that belongs to its family (handoff A2):

| Path | The Osmosis question | Lifetime |
|---|---|---|
| pool | ordinary (not ephemeral), with `family_id` set; never drawn on its own | until retired |
| live | ephemeral, in the session, with `family_id` set | retired at `end_session`, as today. Its responses still count for the family (handoff A2, A4) |

Instance payloads come from the kit's Osmosis adapter (`../kit/07` §4), with `family_id` added.

## 3. Pools

**Making a pool.** Use the minting flow, then export with `--family`:

```
abacus mint export <batch> --to osmosis --family <family_id>
```

**Which instance is served when the family is drawn** (handoff A3):
1. Instances never presented, oldest-minted first.
2. Once every instance has been presented, the least recently presented.
3. Repeats happen only when the pool is used up, and they are marked on the attempt.

**Refill.**
- Osmosis reports families whose unseen count is at or below a threshold, default 3 (handoff A5).
- An AI in-environment that sees this mints more. `abacus pool plan <list>` turns that list into the mint commands to run.
- Nothing refills automatically. The AI decides.

**Pool size** is the AI's choice per family. The working guess is 20–40 for a family that will be scheduled for months.

## 4. Collisions between the two paths

A live instance picks a random seed, so it can happen to match a pool instance's params. With wide knobs this is rare, and it's harmless: it's the same problem, presented once more. The spec does not try to prevent it.
