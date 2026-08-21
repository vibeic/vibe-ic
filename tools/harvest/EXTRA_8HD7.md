# 8HD-7 — 633 checkouts nobody had counted

`verdicts_extra_8hd7.tsv` is **not** a contract shard. The 355-row split covers hosts 105,
114 and 120. Host **8HD-7 (192.168.1.102)** was in nobody's shard, and it holds 633 more
checkouts of this repository. It sat idle all night.

Same rule, same four verdicts, same evidence shape as `verdicts_shard_{a,b,c}.tsv`, so the
files join. Kept under a separate name so it can never be mistaken for a contract shard.

| | |
|---|---|
| RECOVER | 502 |
| LANDED | 110 |
| ABANDON | 21 |
| UNREACHABLE | 0 |

## What had to be true first

**520 of the 633 are visible to git; 113 are not.** Their worktree *registration* was pruned:
`git -C <path> rev-parse HEAD` fails outright, so there is no HEAD, no branch, no merge-base,
and `git worktree list` never mentions them — while their files sit on disk. They are judged
from the files, which is what the rule asks about anyway.

**A pruned checkout still needs a scope, and it has no ref to get one from.** Without a scope
every checkout older than one landing lists all of main's later churn as differing and every
verdict comes back RECOVER. The scope is taken from content instead: the plugin manifest is
rewritten by every landing, so the manifest bytes on disk name the commit on `origin/main`
the checkout was taken from.

**The first map was built from the wrong clone.** It held 188 of main's manifest blobs where a
full clone holds 1157, and 11 checkouts came back `UNDETERMINED_NO_BASE` — honest, and
needlessly ignorant. Rebuilt from the deepest clone on the host (2707 commits), all 11
resolved: 6 LANDED or empty, 5 RECOVER.

**79 of the host's 82 clones were on a stale `origin/main`** before the fetch, which is the
fault this whole re-triage exists to correct. Fetched once per clone, under `flock`.

## Every LANDED was derived twice

106 registered and 9 pruned, by a route sharing no code with the first: real `sha256sum` on
both sides of every file the checkout owns, or — where it owns none — whole-**tree-OID**
equality with a commit `origin/main` publishes, because "all 0 owned files matched" is vacuous
and must never be printed as evidence. 115 of 115 confirmed, 0 disagreements.

Nothing deleted.
