# Harvest consolidation

This directory is the canonical consolidation of worktree-triage shards A, B,
and C.  It is based on current main `6dd97611eafa2af2d1aacc13dae88bd40c3c0e8b`
and preserves the full rescue histories from:

- `164420946ef5ff3df3c2fed8019f9615a32efdd8` (three-shard harvest)
- `66326d8ef7dfa833c018b53ce8599b764c3cf498` (false-LANDED corrections and rescue bundle)

The canonical contract is exactly three tab-separated fields in each
`verdicts_shard_{a,b,c}.tsv`: `path`, `verdict`, and content-based `evidence`.
The source rosters provide the host.  `verdicts_joined.tsv` is derived with
`(host,path)` as its key because six literal paths legitimately occur more than
once across different hosts or shards.

Run the complete acceptance, including a clean bundle restore, strict fsck,
164/164 blob comparison, and an unsafe-deletion negative control:

```bash
python3 tools/harvest/verify_consolidation.py --full --self-test
```

Regenerate the joined ledger after an intentional canonical shard edit:

```bash
python3 tools/harvest/verify_consolidation.py --write-joined
```

The acceptance requires exactly 114 + 131 + 110 = 355 source/verdict rows and
also enforces the ledger's `>=355` threshold.  All absolute paths are valid;
16 rows intentionally live under `/tmp`, so a `/home/reyerchu`-only grep is not
an acceptance check.

Deletion safety is content-based, not ancestry-based.  Batch 72 was
squash-landed.  In particular, five corrected rows contain uncommitted bytes
and must remain `RECOVER`; changing one to `LANDED` or `ABANDON` makes the
negative control fail.

Rescue bundle identity:

- SHA-256: `1ea1e03def8d0b7a7e7d09cf12da7dbbafe3f16d529024a1b61b35149b88a677`
- SHA-1: `25b4dd5aa43280bb03c536ffd5a371b1c5fcb6f4`
- restored HEAD: `f0ee47468cbc68fcbc70465cc7ecc4f864d2f3c7`

No verdict in this directory authorizes deletion by itself.  Re-measure live
hosts immediately before any destructive action.
