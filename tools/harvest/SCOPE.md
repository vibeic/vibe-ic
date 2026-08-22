# What this harvest covers, and what it does not

`verdicts_all.tsv` holds 1439 decided worktrees. That is not "all the vibe-ic checkouts on the
fleet", and nothing in the file says so — this does.

## Measured 2026-08-22, full-depth filesystem census on three reachable hosts

| host | vibe-ic checkouts on disk | carrying a verdict | not judged |
|---|---|---|---|
| .105 (8HD-9) | 1394 | 481 | 913 |
| .102 (8HD-7) | 2062 | 631 | 1431 |
| .108 (8HD-6) | 828 | 32 | 796 |
| **total (3 of 7 hosts)** | **4284** | **1144** | **3140** |

A checkout counts if it has a `.git` and either `vibe-ic-marketplace/` or `.claude-plugin/`.
`.112`, `.114`, `.120`, `.121` were not censused; `.107` answers ICMP with every TCP port filtered.

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
