# 06 — Library and links

**Owns:** where algorithms live, how they're found, how they're tied to items in a consumer, and usage records.

---

## 1. Layout

```
library/                                 ABACUS_LIBRARY; default: library/ in the abacus repo
├── nt/last-three-digits-of-tower.py     id: nt.last-three-digits-of-tower
├── comb/…
├── prob/…
├── examples/…                           the example algorithms the repo ships (09 §5)
├── batches/                             minted batches (07), tracked
├── links.jsonl                          one link per line (§3), tracked
├── usage.jsonl                          one line per role run (§4); local, gitignored
└── .index.sqlite                        derived; gitignored; rebuilt from the files
```

- **Files are the truth.** The index is only a cache (`abacus index rebuild`).
- **Ids map to paths:** `nt.last-three-digits-of-tower` ↔ `nt/last-three-digits-of-tower.py`.

**Decision: files in git, not a database.**
- **Why:** algorithms are code. Files are diffable and reviewable, and git gives the versioning that `05` §6 relies on.
- **When the rival wins:** a database-first library wins if many writers, or a server, have to share it. Neither is true in these specs.

## 2. Finding algorithms

`abacus algo search` (MCP: `algo_search`):
- **Full text** over id, title, summary, tags and techniques.
- **Filters:** `role`, `tag`, `technique`, `answer_format`, `linked` (to a consumer, or to one specific target), `unlinked`.
- **Sort:** `recent`, `most_linked`, `most_used`, `id`.

`abacus algo show <id>` shows the header, roles, links, usage counts and the last lint result.

## 3. Links

A link ties an algorithm to one item in a consumer. It exists so the AI can index and sort a large bank, with questions like:
- Which questions came from this algorithm?
- Which algorithm made this question?
- Which families have no questions yet?

**Links are reversible.** Adding or removing one never changes the algorithm or the consumer's item.

```json
{"algo": "nt.last-three-digits-of-tower", "target": "osmosis:q:6b1f…", "kind": "minted",
 "algo_hash": "3f2a9c1e", "seed": 1739201, "batch": "2026-09-26-nt-tower-01", "at": "2026-09-26T14:02:11Z"}
```

- **`target`** has the form `<consumer>:<kind>:<id>`. Osmosis targets:
  - `osmosis:q:<lineage_id>`, a question. It uses the lineage id because that survives edits, while the version id does not.
  - `osmosis:family:<family_id>`, a family (spec 2).
- **`kind`:**
  - `minted`: the item was made from this algorithm
  - `checks`: the algorithm checks an item it didn't make
  - `family`: spec 2
- **Commands:**
  - `abacus link add`, `abacus link rm`, `abacus link list`
  - `abacus link find <target>` for reverse lookup
  - `rm` deletes the line; git history keeps the record.
- **The core treats `target` as an opaque string with a prefix.** Only the adapter knows what `osmosis:q:` means.

## 4. Usage

Every role run appends one line to `usage.jsonl`: `algo`, `role`, time, `complete`. It powers the `most_used` sort, and it is the evidence for promoting a kind of algorithm to a button (`04`, "Changing the list"). It stays local to each machine, because it's convenience data, not a record.
