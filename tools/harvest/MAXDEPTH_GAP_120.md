# My enumeration used `-maxdepth 4`. On .120 that cost exactly one worktree.

jharv3's SCOPE.md showed a bounded `find` reporting a coverage gap that was its own
horizon. My `enum_all.sh` and `other_repos.sh` used `-maxdepth 4`, so the same
applies to every population figure I published (701, then 811). Measured on .120:

    maxdepth 4 : 266 vibe-ic checkouts
    full depth : 337          -> 71 the bounded sweep could not see

**But the composition is the finding, not the count.** Of those 71:

| what it is | n |
|---|---:|
| per-test fixture repos (`bt/test_git_*/repo`, `pytest-of-*`) | 69 |
| plugin marketplace copies under `.codex` / `.claude` | 2 |
| a real worktree | **1** |

`/home/reyerchu/_rb_r808/repo/base_wt` — judged here, LANDED, 0 files differing from
main; its clone was fetched first (867de428 -> a4caccef) because it was not in shard
A's fetch set and would otherwise have been judged against a stale ref.

So on this host the horizon bug cost ONE row, not 71. A raw count of unjudged
checkouts overstates the risk by ~70x, because the deep population is test-harness
scratch that no one authored and nothing would recover. Anyone reading "3140
unjudged" should classify before scoping work to it.

Not claimed: that .105/.102/.108 have the same composition. Only .120 was measured.
