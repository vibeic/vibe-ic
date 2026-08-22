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
