# 07 — Minting

**Owns:** making a batch of instances ahead of time, the AI's review of it, exporting it to a consumer, and linking the results.
**Defers to:** `05` for instances, `06` for links, and `live/02` for exporting into a family's pool instead of as standalone questions.

---

## 1. The flow

```
abacus mint make <algo> --count 40 --seed S [--knob a=7]    → library/batches/<batch-id>.jsonl
    the AI reads the batch and runs whatever else it wants
abacus mint review <batch> --drop 3,17 --note 5 "too easy"   (or the AI edits the file)
abacus mint export <batch> --to osmosis --tags t1,t2 [--node-key k]
                                                             → library/batches/<batch-id>.osmosis.json
    the AI submits that payload with Osmosis create_questions (or scripts/mcp-batch)
abacus mint link <batch> --created <creation response>.json   → links.jsonl
```

**Nothing here calls Osmosis.** abacus writes payloads and reads responses. The AI, which holds the Osmosis connection, sends them. That keeps the core free of any consumer (principle 5).

## 2. `mint make`

**For each i from 1 to count:**
1. Derive seed_i from (S, i), and run `generate`.
2. Run `compute` and `check`, if the algorithm has them, and store their Evidence in `instance.evidence`.
3. Run `solution` and `demo`, if present.
4. Compute signals (`08`).

**Then, across the whole batch, set flags. Flags never drop an instance:**
- `duplicate_params`, `duplicate_statement`
- `duplicate_answer`: the same answer as another instance. Worth knowing for pools.
- `derivations_disagree`: `generate`, `compute` and `check` don't all agree.
- `out_of_range`
- `incomplete`: a role hit its budget.
- `answer_in_statement` (`08`)

**The batch file starts with a summary line:** count, flags by code, answer spread, total time.

**Duplicates:** if `generate` keeps producing duplicates, `make` stops after count × 5 attempts and says how many distinct instances it found.

**Batch id:** `<date>-<algo-slug>-<nn>`. Batches are tracked in git, because they hold the signals the future difficulty model needs (`08` §3).

## 3. `mint review`

Records the AI's decisions in the batch. Each instance gets `decision`, either `keep` (the default) or `drop`, plus an optional note. This is pure bookkeeping for the AI; abacus attaches no conditions to it.

## 4. Export to Osmosis (`adapters/osmosis.py`)

Each kept instance becomes one `create_questions` item:

| Osmosis field | Filled from |
|---|---|
| `type` | `mc` if the instance has `choices`, otherwise `written` |
| `prompt` | `statement` |
| `choices` | `choices`: `body`, `is_correct` ← `correct`, `misconception` ← `note` |
| `model_answer` | the answer rendered as text (written items only) |
| `explanation` | not set while `solution` is deferred (`05` §5) |
| `tags`, `node_keys` | from the export command; they must already exist in Osmosis. In v1, abacus tags are not mapped automatically |
| `source_note` | `abacus <algo>@<hash> seed <seed>`. A hint people can see, shown in Osmosis's question detail |
| `difficulty` | not set (open question 1) |
| `provenance` | not set. The enum has no abacus value yet; `live/handoff-osmosis.md` A8 asks for one |

The batch-level `idempotency_key` is the batch id, so re-sending a batch creates nothing twice.

## 5. `mint link`

`mint link` reads the consumer's creation response and pairs each entry with a kept instance. The adapter (`adapters/osmosis.py`) turns the response into neutral entries `{remote_id, target, preview}`; for Osmosis, `created: [{id, lineage_id, prompt_preview}]` becomes `remote_id = id`, `target = osmosis:q:<lineage_id>`. Only the adapter knows the response's field names.
- **Matching:** by order is primary. When the counts differ or the previews don't agree, match on the preview, and an entry that fits more than one free instance is flagged `ambiguous` and not linked. Entries and instances left over are reported (`no_match`, `unmatched_instance`).
- **Output:** one `minted` link per question, and `remote_id` and `target` recorded in the batch row.
- **Relinking:** the same response twice adds nothing. An instance that already has a different target keeps its first link, and the new one is flagged `relinked_conflict`. Every target is validated before anything is written (`bad_target`).
- **Locking:** `link` and `review` take the same batch file lock.
