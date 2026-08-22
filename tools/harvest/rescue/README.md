# `rescue-2026-08-22.bundle` — the uncommitted bytes from five worktrees, and how to get any of them back

**One bundle, one ref.** This replaces emitting a branch per rescued thing. It costs
the shared remote nothing beyond the branch already carrying my shard, and it
preserves exactly as much.

## What is in it and why it was rescued

Five worktrees were marked **LANDED** — the verdict a later job acts on by deleting
— while holding uncommitted bytes that are on no commit and no remote. Four were in
my `verdicts_shard_a.tsv`, one in my `verdicts_unreachable_resolved.tsv`. All five
are corrected to RECOVER by the overlays beside this directory. The bundle exists so
the bytes survive even if a sweep reaches the directories before the correction does.

| directory in the bundle | live path | host | files | what it holds |
|---|---|---|---|---:|
| `_agentjob_i1015_wt/` | `/home/reyerchu/_agentjob_i1015/wt` | .120 | 98 | 1576 lines main lacks; 3 paths main never held |
| `_agent_scratch_whatif_wt_C/` | `/home/reyerchu/_agent_scratch_whatif/wt_C` | .120 | 58 | 1119 lines main lacks + 29 untracked files |
| `_wt_1236/` | `/home/reyerchu/_wt_1236` | .120 | 5 | 576 lines; `liar_census.py` +224; `test_issue1115_not_applicable_is_not_a_pass.py` main never held |
| `_wt_1486/` | `/home/reyerchu/_wt_1486` | .120 | 2 | 5 lines main lacks |
| `_a1456/` | `/home/reyerchu/_a1456` | .112 | 1 | 61 lines main lacks — `test_matrix_63x8_census_freshness.py` |

164 files, 10.8 MB of content, 3.0 MB bundled.

## Get it back

    git clone /path/to/rescue-2026-08-22.bundle recovered
    cd recovered            # master, tag rescue-2026-08-22

One file, without cloning:

    git bundle unbundle rescue-2026-08-22.bundle
    git cat-file -p <commit>:_wt_1236/tools/liar_census.py > liar_census.py

Everything for one worktree:

    git archive --format=tar <commit>:_agentjob_i1015_wt | tar -x -C <dest>

## Verified before this was written down

Per the rescue order — fetch, count, `bundle verify`, match by SHA, and only then
rely on it:

    $ git bundle verify rescue-2026-08-22.bundle
      The bundle records a complete history.
    $ every file hashed against the LIVE worktree it came from
      matched-by-sha 164   mismatched 0   missing 0

`MANIFEST.sha1` lists all 164 blob SHAs, so any future copy can be re-checked
against the same numbers without re-reading the hosts.

**Nothing was deleted, moved, or stopped being tracked.** The five worktrees are
untouched; this is a copy. `harvest/worktree-triage-jharvest` also stays — the
acceptance ledger reads its verdicts.
