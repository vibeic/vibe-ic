# 11 RECOVER rows in shards B and C are now equal to main's tip — and 5 of them must stay RECOVER anyway

For the owners of `verdicts_shard_b.tsv` and `verdicts_shard_c.tsv`. Both files are
frozen in batch 72; **nothing here edits them.** Measurement only.

## The gap: a history walk cannot see a row that landed at the TIP

`jharv3`'s landed-by-history test asks, for each file that still DIFFERS from main's
tip, whether main's history ever held those bytes. It is the right test and it found
real defects — 15 in shard A, 23 in shard B.

It is structurally blind to one case. **A row whose files ALL now match main's tip
has no differing files, so there is nothing for the walk to examine, and it never
appears as a finding.** That is not an oversight in their method; it is a different
question. The two are complements:

| test | catches | cost |
|---|---|---|
| tip-equality — all files match main's tip | work that landed RECENTLY | one `git diff` per row |
| history walk — differing blobs in main's past | work that landed and main moved past | `--full-history` per file, minutes per row |

Measured on my own shard A: of the 5 false RECOVERs I found beyond jharv3's sweep,
**3 were invisible to the history walk** for exactly this reason (`_wt_v1610`,
`vibe-ic-wt-caravel-final`, `vibe-ic-wt-caravel-rerun`). Run both.

## Result on shards B and C, against main `a4caccef`

188 RECOVER rows, all 188 heads resolvable from the `.120` clone.
**11 are now tip-equal.** Disk state then read on each row's own host:

| | rows |
|---|---:|
| tracked files modified and uncommitted — **KEEP RECOVER** | **5** |
| clean of tracked mods, some untracked present | 3 |
| 0 untracked, 0 modified — LANDED candidates | 3 |

The five that must not move: `_counts2` (12 modified), `_pgv/anch_pr1123` (4),
`_wt_synthfe` (1), `_a1456` (1), and `_v1123` — **384 modified files**.

**This is the whole point of running the guard before the flip.** Tip-equality says
the committed content is in main; it says nothing about content held by no commit.
An uncommitted edit exists on one disk and deleting it is the one error nothing
undoes. I hit this on my own shard with `_pg_pair` and `_wt_x`, which pass the
history test cleanly and still stay RECOVER.

Per-row data, including head and host, in `2026-08-22-shards-b-c-tip-equal-rows.tsv`.
