# What this harvest covers, and what it does not

`verdicts_all.tsv` holds 1439 decided worktrees. That is not "all the vibe-ic checkouts on the
fleet", and nothing in the file says so — this does.

## Measured 2026-08-22, full-depth filesystem census, six reachable hosts

| host | checkouts on disk | carrying a verdict | not judged |
|---|---|---|---|
| .105 (8HD-9) | 1394 | 481 | 913 |
| .102 (8HD-7) | 2062 | 631 | 1431 |
| .108 (8HD-6) | 828 | 32 | 796 |
| .112 | census did not complete | — | — |
| .114 | 3578 | 99 | 3479 |
| .120 | 3784 | 122 | 3662 |
| .121 | 1662 | 51 | 1611 |
| **total** | **13308** | **1416** | **11892** |

`.112`'s census was still running when this was written and is NOT included — its row says so
rather than carrying a zero. A missing measurement and a measured zero look identical in a table,
which is the whole reason this file exists.

A checkout counts if it has a `.git` and either `vibe-ic-marketplace/` or `.claude-plugin/`.
`.107` answers ICMP with every TCP port filtered, so it cannot be censused at all.

**1416 of 13308 is 11%.** The harvest was never an enumeration of the fleet — it was a roster of
477, and 1084 rows beyond it that two hosts happened to surface.

## Why the gap is scope, not failure

The job was defined by a roster: 477 worktrees, 355 still needing a verdict, split into three
shards. Shard B was 131 of those, and every one is decided. The other 1084 rows are worktrees I
found on 8HD-9 and 8HD-7 that the roster never listed — work beyond the brief, not a claim to have
enumerated the fleet.

**The number that matters for safety is not coverage, it is that no verdict is wrong.** An
unjudged checkout is untouched; a wrong verdict deletes. Every one of the 213 deletion-bound rows
has a recorded guard result, and nothing here has been deleted.

## The census had to be run twice, and the first run was the misleading one

A `-maxdepth 4` search reported 714 checkouts on .105 and claimed 586 were unjudged. It saw only
**126 of the 481 rows I already had**, because most live at depth 6-7 under
`/tmp/claude-1000/<session>/scratchpad/...`. A bounded search reported a coverage gap that was its
own horizon, and the shape of the answer — a big plausible number of "missing" rows — looked exactly
like a real finding.

Full depth: 1394 on that host, all 481 known rows present, 0 of them gone.

## Untracked files: the category no rescue anchor can reach

Every anchor in this harvest preserves **commits**. An untracked file is on no commit, so all of
them miss it by construction — and "the tree is clean" cannot answer the question either, because
an untracked file does not make a tree dirty in the sense a verdict measures.

Swept all 1439 judged worktrees, every host:

| | |
|---|---|
| host group | untracked files | distinct blobs | on **no** origin ref |
|---|---|---|---|
| .105 + .102 (1113 rows) | 2,111 | 1,409 | 1,247 |
| .108 .112 .114 .120 .121 (326 rows) | 18,878 | 4,895 | **34** |

The five-host figure is the interesting one: 18,878 untracked files and only 34 blobs that exist
nowhere on origin. Volume is not risk — `.121` alone contributes 18,785 of those files and almost
all of them are build output already represented on origin.

Classified by the repo's own `git check-ignore`, not by extension: **247 paths ignored, 331 not.**
Of the 331, 194 files are `benchmark-data/` evaluation output — that path was split out into
`vibeic/benchmark-data`, so this repo's ignore rules no longer describe it — and most of the rest is
agent scratch (`.scratch/`, `.probe/`, `.sweep-*`).

**23 are authored source, tests and handoff documents** (16 from the first group, 7 from the second) under `vibe-ic-marketplace/` and `tools/`,
each verified absent from origin before inclusion, preserved at
`harvest/preserve-untracked-authored` and `-2`, each with a `MANIFEST.tsv` recording which worktree each came from.

(The paths inside that commit carry a doubled `preserved/preserved/` prefix — a cosmetic slip in the
tree builder. The files and the manifest are correct; recording it here rather than leaving a reader
to wonder whether the duplication means something.)
